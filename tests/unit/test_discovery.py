from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from legionctl.models.discovery import MdnsRecord
from legionctl.models.inventory import Inventory, SentinelNode
from legionctl.services.credentials import CredentialStore
from legionctl.services.discovery import (
    detect_discovery_issues,
    enrich_discovered,
    load_discovery_cache,
    mark_known,
    mdns_record_from_service_info,
    parse_mdns_record,
    save_discovery_cache,
)
from legionctl.settings import LegionPaths


def _mdns(
    *,
    name: str = "sentinel-north-door-01._sentinel._tcp.local.",
    server: str = "sentinel-north-door-01.local.",
    addresses: list[str] | None = None,
    properties: dict[str, str] | None = None,
    port: int = 443,
) -> MdnsRecord:
    return MdnsRecord(
        name=name,
        server=server,
        port=port,
        addresses=addresses or ["192.168.50.41"],
        properties=properties
        or {
            "sentinel_id": "sentinel-north-door-01",
            "zone": "North Door",
            "firmware": "0.1.0",
            "profile_id": "event-alpha",
            "profile_revision": "4",
        },
    )


def test_parse_mdns_record_into_inventory_node() -> None:
    discovered = parse_mdns_record(_mdns())
    assert discovered.sentinel_id == "sentinel-north-door-01"
    assert discovered.hostname == "sentinel-north-door-01.local"
    assert discovered.ip == "192.168.50.41"
    assert discovered.zone == "North Door"
    assert discovered.firmware_version == "0.1.0"
    assert discovered.profile_id == "event-alpha"
    assert discovered.profile_revision == 4
    assert discovered.base_url == "https://sentinel-north-door-01.local"
    node = discovered.to_inventory_node()
    assert node.sentinel_id == "sentinel-north-door-01"
    assert node.hostname == "sentinel-north-door-01.local"
    assert node.last_known_ip == "192.168.50.41"
    assert node.base_url.startswith("https://")


def test_parse_uses_instance_name_and_strips_secret_txt() -> None:
    record = _mdns(
        properties={"token": "super-secret-token", "zone": "Hall B"},
    )
    discovered = parse_mdns_record(record)
    assert discovered.sentinel_id == "sentinel-north-door-01"
    assert discovered.zone == "Hall B"
    dumped = discovered.model_dump()
    assert "super-secret-token" not in str(dumped)
    assert "token" not in dumped


def test_mdns_record_from_service_info() -> None:
    info = SimpleNamespace(
        name="sentinel-hall-b-01._sentinel._tcp.local.",
        server="sentinel-hall-b-01.local.",
        port=8443,
        properties={b"sentinel_id": b"sentinel-hall-b-01", b"token": b"nope"},
        parsed_addresses=lambda: ["10.0.0.9"],
    )
    record = mdns_record_from_service_info(info)
    assert record.addresses == ["10.0.0.9"]
    assert "token" not in record.properties
    discovered = parse_mdns_record(record)
    assert discovered.base_url == "https://sentinel-hall-b-01.local:8443"


def test_duplicate_id_and_inconsistent_hostname() -> None:
    first = parse_mdns_record(_mdns())
    second = parse_mdns_record(
        _mdns(
            name="sentinel-north-door-01._sentinel._tcp.local.",
            server="other-host.local.",
            addresses=["192.168.50.42"],
        )
    )
    inventory = Inventory(
        nodes=[
            SentinelNode(
                sentinel_id="sentinel-north-door-01",
                hostname="inventory-host.local",
                base_url="https://inventory-host.local",
            )
        ]
    )
    issues = detect_discovery_issues([first, second], inventory)
    codes = {issue.code for issue in issues}
    assert "duplicate_id" in codes
    assert "inconsistent_hostname" in codes
    assert any("sentinel-north-door-01" in issue.message for issue in issues)


def test_hostname_claimed_by_two_ids() -> None:
    door = parse_mdns_record(_mdns())
    hall = parse_mdns_record(
        _mdns(
            name="sentinel-hall-b-01._sentinel._tcp.local.",
            server="sentinel-north-door-01.local.",
            properties={"sentinel_id": "sentinel-hall-b-01"},
        )
    )
    issues = detect_discovery_issues([door, hall], Inventory())
    assert any(issue.code == "inconsistent_hostname" for issue in issues)


def test_mark_known_and_cache(legion_home: LegionPaths) -> None:
    discovered = [parse_mdns_record(_mdns())]
    inventory = Inventory(
        nodes=[
            SentinelNode(
                sentinel_id="sentinel-north-door-01",
                hostname="sentinel-north-door-01.local",
                base_url="https://sentinel-north-door-01.local",
            )
        ]
    )
    marked = mark_known(discovered, inventory)
    assert marked[0].known is True
    save_discovery_cache(marked)
    loaded = load_discovery_cache()
    assert loaded is not None
    assert loaded.records[0].sentinel_id == "sentinel-north-door-01"
    raw = legion_home.discovery_cache.read_text(encoding="utf-8")
    assert "token" not in raw.lower()
    assert "webhook" not in raw.lower()


@pytest.mark.asyncio
async def test_enrich_with_mocked_http(respx_mock: respx.MockRouter) -> None:
    discovered = parse_mdns_record(_mdns())
    respx_mock.get("https://sentinel-north-door-01.local/api/v1/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "api_version": "v1",
                "sentinel_id": "sentinel-north-door-01",
                "display_name": "North Door",
                "zone": "North Door",
                "firmware_version": "0.2.0",
                "profile_id": "event-alpha",
                "profile_revision": 5,
            },
        )
    )
    store = CredentialStore(store=_Mem({"sentinel-north-door-01": "super-secret-token"}))
    enriched = await enrich_discovered(
        [discovered],
        store,
        timeout=httpx.Timeout(1.0),
        verify=True,
    )
    assert enriched[0].reachable is True
    assert enriched[0].firmware_version == "0.2.0"
    assert "super-secret-token" not in str(enriched[0].model_dump())


class _Mem:
    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    def set_token(self, sentinel_id: str, token: str) -> None:
        self._tokens[sentinel_id] = token

    def get_token(self, sentinel_id: str) -> str | None:
        return self._tokens.get(sentinel_id)

    def delete_token(self, sentinel_id: str) -> None:
        self._tokens.pop(sentinel_id, None)
