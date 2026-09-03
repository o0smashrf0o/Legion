from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from legionctl.clients.sentinel_api import build_api_url
from legionctl.constants import MDNS_SERVICE_TYPE
from legionctl.errors import DiscoveryError
from legionctl.models.discovery import (
    DiscoveredService,
    DiscoveryCache,
    DiscoveryIssue,
    MdnsRecord,
)
from legionctl.models.inventory import Inventory
from legionctl.models.node_api import InfoResponse
from legionctl.redaction import is_secret_key
from legionctl.services.audit import utc_now
from legionctl.services.credentials import CredentialStore
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import atomic_write_json, read_json

logger = logging.getLogger("legionctl.services.discovery")

DEFAULT_DISCOVERY_TIMEOUT = 5.0
BrowseFn = Callable[[float], list[MdnsRecord]]


def _first_ipv4(addresses: list[str]) -> str | None:
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version == 4:
            return address
    return addresses[0] if addresses else None


def _sanitize_txt(properties: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in properties.items() if not is_secret_key(key)}


def _txt_get(properties: dict[str, str], *keys: str) -> str | None:
    lowered = {key.lower(): value for key, value in properties.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value:
            return value
    return None


def instance_name(fullname: str) -> str:
    marker = "._sentinel._tcp"
    lowered = fullname.lower()
    index = lowered.find(marker)
    if index > 0:
        return fullname[:index]
    return fullname.rstrip(".")


def build_base_url(hostname: str | None, ip: str | None, port: int) -> str:
    host = hostname or ip
    if not host:
        raise DiscoveryError("discovery record is missing hostname and IP")
    if port in {0, 443}:
        return f"https://{host}"
    return f"https://{host}:{port}"


def parse_mdns_record(record: MdnsRecord) -> DiscoveredService:
    properties = _sanitize_txt(record.properties)
    sentinel_id = _txt_get(properties, "sentinel_id", "id") or instance_name(record.name)
    hostname = record.server.rstrip(".") if record.server else None
    ip = _first_ipv4(record.addresses)
    port = record.port or 443
    revision_raw = _txt_get(properties, "profile_revision", "revision")
    revision: int | None = None
    if revision_raw:
        try:
            revision = int(revision_raw)
        except ValueError:
            revision = None
    return DiscoveredService(
        sentinel_id=sentinel_id,
        hostname=hostname,
        ip=ip,
        port=port,
        base_url=build_base_url(hostname, ip, port),
        zone=_txt_get(properties, "zone", "aor"),
        display_name=_txt_get(properties, "display_name", "name"),
        firmware_version=_txt_get(properties, "firmware_version", "firmware", "fw"),
        api_version=_txt_get(properties, "api_version", "api"),
        profile_id=_txt_get(properties, "profile_id", "profile"),
        profile_revision=revision,
    )


def mdns_record_from_service_info(info: Any) -> MdnsRecord:
    addresses: list[str] = []
    parsed = getattr(info, "parsed_addresses", None)
    if callable(parsed):
        addresses = [item for item in parsed() if item]
    properties: dict[str, str] = {}
    raw_properties = getattr(info, "properties", {}) or {}
    for key, value in raw_properties.items():
        decoded_key = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
        if is_secret_key(decoded_key):
            continue
        if value is None:
            properties[decoded_key] = ""
        elif isinstance(value, bytes):
            properties[decoded_key] = value.decode("utf-8", errors="replace")
        else:
            properties[decoded_key] = str(value)
    server = getattr(info, "server", None)
    name = getattr(info, "name", "")
    port = int(getattr(info, "port", 443) or 443)
    return MdnsRecord(
        name=str(name),
        server=str(server).rstrip(".") if server else None,
        port=port,
        addresses=addresses,
        properties=properties,
    )


def browse_mdns(timeout: float = DEFAULT_DISCOVERY_TIMEOUT) -> list[MdnsRecord]:
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except Exception as exc:  # pragma: no cover - import guard
        raise DiscoveryError("zeroconf is unavailable") from exc

    class Listener(ServiceListener):
        def __init__(self) -> None:
            self.names: list[str] = []

        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            self.names.append(name)

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            return

        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            return

    zeroconf = Zeroconf()
    listener = Listener()
    browser = ServiceBrowser(zeroconf, MDNS_SERVICE_TYPE, listener)
    try:
        time.sleep(max(timeout, 0.1))
        records: list[MdnsRecord] = []
        for name in listener.names:
            info = zeroconf.get_service_info(
                MDNS_SERVICE_TYPE,
                name,
                timeout=max(int(timeout * 1000), 100),
            )
            if info is not None:
                records.append(mdns_record_from_service_info(info))
        return records
    except Exception as exc:
        raise DiscoveryError("mDNS discovery failed") from exc
    finally:
        browser.cancel()
        zeroconf.close()


def detect_discovery_issues(
    discovered: list[DiscoveredService],
    inventory: Inventory,
) -> list[DiscoveryIssue]:
    issues: list[DiscoveryIssue] = []
    by_id: dict[str, list[DiscoveredService]] = {}
    for item in discovered:
        by_id.setdefault(item.sentinel_id, []).append(item)

    for sentinel_id, items in by_id.items():
        hostnames = sorted(
            {
                item.hostname or item.ip or ""
                for item in items
                if item.hostname or item.ip
            }
        )
        if len(hostnames) > 1:
            issues.append(
                DiscoveryIssue(
                    code="duplicate_id",
                    sentinel_id=sentinel_id,
                    message=(
                        f"duplicate Sentinel ID '{sentinel_id}' advertised on "
                        f"hostnames: {', '.join(hostnames)}"
                    ),
                    hostnames=hostnames,
                )
            )
        known = inventory.node_by_id(sentinel_id)
        discovered_hostname = items[0].hostname
        if (
            known is not None
            and known.hostname
            and discovered_hostname
            and known.hostname != discovered_hostname
        ):
            issues.append(
                DiscoveryIssue(
                    code="inconsistent_hostname",
                    sentinel_id=sentinel_id,
                    message=(
                        f"inconsistent hostname for '{sentinel_id}': inventory has "
                        f"'{known.hostname}', discovery has '{discovered_hostname}'"
                    ),
                    hostnames=[known.hostname, discovered_hostname],
                )
            )

    by_hostname: dict[str, set[str]] = {}
    for item in discovered:
        if item.hostname:
            by_hostname.setdefault(item.hostname, set()).add(item.sentinel_id)
    for node in inventory.nodes:
        if node.hostname:
            by_hostname.setdefault(node.hostname, set()).add(node.sentinel_id)
    for hostname, ids in by_hostname.items():
        if len(ids) > 1:
            issues.append(
                DiscoveryIssue(
                    code="inconsistent_hostname",
                    sentinel_id=sorted(ids)[0],
                    message=(
                        f"inconsistent hostname '{hostname}' claimed by "
                        f"{', '.join(sorted(ids))}"
                    ),
                    hostnames=[hostname],
                )
            )
    return issues


def mark_known(
    discovered: list[DiscoveredService], inventory: Inventory
) -> list[DiscoveredService]:
    marked: list[DiscoveredService] = []
    for item in discovered:
        known = inventory.node_by_id(item.sentinel_id) is not None
        marked.append(item.model_copy(update={"known": known}))
    return marked


async def probe_sentinel_info(
    base_url: str,
    token: str | None,
    *,
    timeout: httpx.Timeout,
    verify: bool = True,
) -> InfoResponse | None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = build_api_url(base_url, "info")
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=verify, follow_redirects=False
        ) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            return None
        return InfoResponse.model_validate(response.json())
    except Exception:
        logger.debug("discovery info probe failed for %s", urlparse(base_url).netloc)
        return None


async def enrich_discovered(
    discovered: list[DiscoveredService],
    credentials: CredentialStore,
    *,
    timeout: httpx.Timeout,
    verify: bool = True,
) -> list[DiscoveredService]:
    enriched: list[DiscoveredService] = []
    for item in discovered:
        token = credentials.get_token(item.sentinel_id)
        info = await probe_sentinel_info(item.base_url, token, timeout=timeout, verify=verify)
        if info is None:
            enriched.append(item.model_copy(update={"reachable": False}))
            continue
        updates: dict[str, object] = {
            "reachable": True,
            "sentinel_id": info.sentinel_id or item.sentinel_id,
            "display_name": info.display_name or item.display_name,
            "zone": info.zone or item.zone,
            "firmware_version": info.firmware_version or item.firmware_version,
            "api_version": info.api_version or item.api_version,
            "profile_id": info.profile_id or item.profile_id,
            "profile_revision": info.profile_revision or item.profile_revision,
        }
        enriched.append(item.model_copy(update=updates))
    return enriched


def discover_sentinels(
    inventory: Inventory,
    credentials: CredentialStore,
    *,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    verify: bool = True,
    browse: BrowseFn | None = None,
    http_timeout: httpx.Timeout | None = None,
) -> tuple[list[DiscoveredService], list[DiscoveryIssue]]:
    records = (browse or browse_mdns)(timeout)
    discovered = [parse_mdns_record(record) for record in records]
    probe_timeout = http_timeout or httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=10.0)
    discovered = asyncio.run(
        enrich_discovered(discovered, credentials, timeout=probe_timeout, verify=verify)
    )
    discovered = mark_known(discovered, inventory)
    issues = detect_discovery_issues(discovered, inventory)
    return discovered, issues


def save_discovery_cache(
    records: list[DiscoveredService],
    paths: LegionPaths | None = None,
) -> None:
    resolved = paths or get_paths()
    cache = DiscoveryCache(timestamp_utc=utc_now(), records=records)
    atomic_write_json(resolved.discovery_cache, cache.model_dump(mode="json"))


def load_discovery_cache(paths: LegionPaths | None = None) -> DiscoveryCache | None:
    resolved = paths or get_paths()
    payload = read_json(resolved.discovery_cache)
    if payload is None:
        return None
    return DiscoveryCache.model_validate(payload)
