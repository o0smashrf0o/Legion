from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, TypeVar

import httpx

from legionctl import __version__
from legionctl.clients.sentinel_api import SentinelApiClient
from legionctl.context import AppContext
from legionctl.errors import AuthenticationError, CredentialError, LegionError, TlsError
from legionctl.models.fleet import (
    FleetNodeEvents,
    FleetNodeHealth,
    FleetNodeStatus,
    event_to_json,
)
from legionctl.models.inventory import SentinelNode
from legionctl.models.node_api import HealthResponse, InfoResponse
from legionctl.redaction import redact_secrets
from legionctl.services.audit import format_utc
from legionctl.services.credentials import CredentialStore
from legionctl.settings import AppSettings, load_settings

T = TypeVar("T")
R = TypeVar("R")
ErrorKind = Literal["none", "unreachable", "auth", "other"]


def classify_error(exc: BaseException) -> ErrorKind:
    if isinstance(exc, (AuthenticationError, CredentialError, TlsError)):
        return "auth"
    if isinstance(exc, LegionError) and exc.exit_code == 2:
        return "unreachable"
    return "other"


def error_message(exc: BaseException) -> str:
    return redact_secrets(str(exc) or exc.__class__.__name__)


def fleet_exit_code(rows: Sequence[Any]) -> int:
    if not rows:
        return 1
    failures = [row for row in rows if not row.ok]
    if not failures:
        return 0
    successes = [row for row in rows if row.ok]
    if not successes and all(row.error_kind == "auth" for row in failures):
        return 3
    return 2


def client_timeouts(app_ctx: AppContext, settings: AppSettings) -> tuple[float, float, float]:
    if app_ctx.timeout is not None:
        value = app_ctx.timeout
        return value, value, value
    return (
        settings.connect_timeout_seconds,
        settings.read_timeout_seconds,
        settings.write_timeout_seconds,
    )


async def _bounded_map(
    items: Sequence[T],
    handler: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
) -> list[R]:
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run(item: T) -> R:
        async with semaphore:
            return await handler(item)

    return list(await asyncio.gather(*[run(item) for item in items]))


def _status_from_health(
    node: SentinelNode,
    health: HealthResponse | None,
    info: InfoResponse | None,
    *,
    ok: bool,
    reachable: bool,
    error: str | None,
    error_kind: ErrorKind,
) -> FleetNodeStatus:
    battery = health.battery if health is not None else None
    wifi = health.wifi if health is not None else None
    scanners = health.scanners if health is not None else None
    queue = health.alert_queue if health is not None else None
    return FleetNodeStatus(
        sentinel_id=node.sentinel_id,
        zone=node.zone,
        ok=ok,
        reachable=reachable,
        error=error,
        error_kind=error_kind,
        battery_percent=None if battery is None else battery.percent,
        battery_charging=None if battery is None else battery.charging,
        wifi_connected=None if wifi is None else wifi.connected,
        wifi_band=None if wifi is None else wifi.band,
        wifi_rssi_dbm=None if wifi is None else wifi.rssi_dbm,
        scanner_wifi=None if scanners is None else scanners.wifi,
        scanner_ble=None if scanners is None else scanners.ble,
        bt_classic_coprocessor=None if scanners is None else scanners.bt_classic_coprocessor,
        alert_queue_depth=None if queue is None else queue.depth,
        profile_id=None if info is None else info.profile_id,
        profile_revision=None if info is None else info.profile_revision,
        timestamp_utc=format_utc(None if health is None else health.timestamp_utc),
    )


def _health_from_parts(
    node: SentinelNode,
    health: HealthResponse | None,
    info: InfoResponse | None,
    *,
    ok: bool,
    reachable: bool,
    error: str | None,
    error_kind: ErrorKind,
) -> FleetNodeHealth:
    base = _status_from_health(
        node,
        health,
        info,
        ok=ok,
        reachable=reachable,
        error=error,
        error_kind=error_kind,
    )
    system = health.system if health is not None else None
    battery = health.battery if health is not None else None
    wifi = health.wifi if health is not None else None
    queue = health.alert_queue if health is not None else None
    return FleetNodeHealth(
        **base.model_dump(),
        battery_voltage_v=None if battery is None else battery.voltage_v,
        wifi_reconnect_count=None if wifi is None else wifi.reconnect_count,
        alert_last_delivery=None if queue is None else queue.last_delivery,
        free_heap_bytes=None if system is None else system.free_heap_bytes,
        reset_reason=None if system is None else system.reset_reason,
        watchdog_resets=None if system is None else system.watchdog_resets,
    )


def _failed_status(node: SentinelNode, exc: BaseException) -> FleetNodeStatus:
    kind = classify_error(exc)
    return FleetNodeStatus(
        sentinel_id=node.sentinel_id,
        zone=node.zone,
        ok=False,
        reachable=False,
        error=error_message(exc),
        error_kind=kind,
    )


def _failed_health(node: SentinelNode, exc: BaseException) -> FleetNodeHealth:
    kind = classify_error(exc)
    return FleetNodeHealth(
        sentinel_id=node.sentinel_id,
        zone=node.zone,
        ok=False,
        reachable=False,
        error=error_message(exc),
        error_kind=kind,
    )


def _failed_events(node: SentinelNode, exc: BaseException) -> FleetNodeEvents:
    kind = classify_error(exc)
    return FleetNodeEvents(
        sentinel_id=node.sentinel_id,
        zone=node.zone,
        ok=False,
        reachable=False,
        error=error_message(exc),
        error_kind=kind,
        events=[],
    )


def _api_client(
    node: SentinelNode,
    credentials: CredentialStore,
    http: httpx.AsyncClient,
    app_ctx: AppContext,
    settings: AppSettings,
) -> SentinelApiClient:
    connect, read, write = client_timeouts(app_ctx, settings)
    return SentinelApiClient(
        node.base_url,
        node.sentinel_id,
        credentials,
        connect_timeout=connect,
        read_timeout=read,
        write_timeout=write,
        read_retries=settings.idempotent_read_retries,
        max_request_bytes=settings.max_request_bytes,
        max_response_bytes=settings.max_response_bytes,
        insecure_skip_tls_verify=app_ctx.insecure_skip_tls_verify,
        client=http,
    )


async def collect_status(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[FleetNodeStatus]:
    resolved = settings or load_settings()
    connect, read, write = client_timeouts(app_ctx, resolved)
    timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=read)
    verify: bool | str = False if app_ctx.insecure_skip_tls_verify else True

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=False,
        headers={"User-Agent": f"legionctl/{__version__}", "Accept": "application/json"},
    ) as http:

        async def one(node: SentinelNode) -> FleetNodeStatus:
            if not credentials.has_token(node.sentinel_id):
                return _failed_status(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            health_result, info_result = await asyncio.gather(
                api.get_health(),
                api.get_info(),
                return_exceptions=True,
            )
            health = health_result if isinstance(health_result, HealthResponse) else None
            info = info_result if isinstance(info_result, InfoResponse) else None
            errors: list[BaseException] = [
                item
                for item in (health_result, info_result)
                if isinstance(item, BaseException)
            ]
            if not errors:
                return _status_from_health(
                    node, health, info, ok=True, reachable=True, error=None, error_kind="none"
                )
            primary = errors[0]
            reachable = health is not None
            return _status_from_health(
                node,
                health,
                info,
                ok=False,
                reachable=reachable,
                error=error_message(primary),
                error_kind=classify_error(primary),
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def collect_health(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[FleetNodeHealth]:
    resolved = settings or load_settings()
    connect, read, write = client_timeouts(app_ctx, resolved)
    timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=read)
    verify: bool | str = False if app_ctx.insecure_skip_tls_verify else True

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=False,
        headers={"User-Agent": f"legionctl/{__version__}", "Accept": "application/json"},
    ) as http:

        async def one(node: SentinelNode) -> FleetNodeHealth:
            if not credentials.has_token(node.sentinel_id):
                return _failed_health(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                health = await api.get_health()
            except Exception as exc:
                return _failed_health(node, exc)
            return _health_from_parts(
                node,
                health,
                None,
                ok=True,
                reachable=True,
                error=None,
                error_kind="none",
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def collect_events(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    limit: int,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[FleetNodeEvents]:
    resolved = settings or load_settings()
    connect, read, write = client_timeouts(app_ctx, resolved)
    timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=read)
    verify: bool | str = False if app_ctx.insecure_skip_tls_verify else True

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=False,
        headers={"User-Agent": f"legionctl/{__version__}", "Accept": "application/json"},
    ) as http:

        async def one(node: SentinelNode) -> FleetNodeEvents:
            if not credentials.has_token(node.sentinel_id):
                return _failed_events(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                payload = await api.recent_events(limit=limit)
            except Exception as exc:
                return _failed_events(node, exc)
            return FleetNodeEvents(
                sentinel_id=node.sentinel_id,
                zone=node.zone,
                ok=True,
                reachable=True,
                error=None,
                error_kind="none",
                events=[event_to_json(event) for event in payload.events],
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)
