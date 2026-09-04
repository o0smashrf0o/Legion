from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

import httpx

from legionctl import __version__
from legionctl.constants import MAX_SCAN_DURATION_SECONDS
from legionctl.context import AppContext
from legionctl.errors import CredentialError, UsageError
from legionctl.models.actions import ActionResult
from legionctl.models.inventory import SentinelNode
from legionctl.services.audit import format_utc
from legionctl.services.credentials import CredentialStore
from legionctl.services.fleet import (
    _api_client,
    _bounded_map,
    classify_error,
    client_timeouts,
    error_message,
)
from legionctl.settings import AppSettings, load_settings

ScanTechnology = Literal["wifi", "ble", "bt_classic"]
ALLOWED_SCAN_TECHNOLOGIES = frozenset({"wifi", "ble", "bt_classic"})


def _http_client(app_ctx: AppContext, settings: AppSettings) -> httpx.AsyncClient:
    connect, read, write = client_timeouts(app_ctx, settings)
    timeout = httpx.Timeout(connect=connect, read=read, write=write, pool=read)
    verify: bool | str = False if app_ctx.insecure_skip_tls_verify else True
    return httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=False,
        headers={"User-Agent": f"legionctl/{__version__}", "Accept": "application/json"},
    )


def validate_scan_request(technology: str, duration_seconds: int, maximum: int) -> None:
    if technology not in ALLOWED_SCAN_TECHNOLOGIES:
        raise UsageError("technology must be one of wifi, ble, bt_classic")
    if duration_seconds < 1:
        raise UsageError("scan duration must be at least 1 second")
    if duration_seconds > maximum:
        raise UsageError(f"scan duration must be <= {maximum} seconds")


def _failed(node: SentinelNode, exc: BaseException) -> ActionResult:
    kind = classify_error(exc)
    result: Literal["unreachable", "error"] = "unreachable" if kind == "unreachable" else "error"
    return ActionResult(
        sentinel_id=node.sentinel_id,
        ok=False,
        result=result,
        error=error_message(exc),
        error_kind=kind,
    )


def _dry_run_rows(nodes: Sequence[SentinelNode], **fields: object) -> list[ActionResult]:
    return [
        ActionResult.model_validate(
            {
                "sentinel_id": node.sentinel_id,
                "ok": True,
                "result": "dry_run",
                **fields,
            }
        )
        for node in nodes
    ]


async def execute_test_alerts(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    message: str,
    include_health_summary: bool,
    dry_run: bool,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ActionResult]:
    if dry_run:
        return _dry_run_rows(nodes)
    resolved = settings or load_settings()
    async with _http_client(app_ctx, resolved) as http:

        async def one(node: SentinelNode) -> ActionResult:
            if not credentials.has_token(node.sentinel_id):
                return _failed(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                payload = await api.test_alert(
                    message=message,
                    include_health_summary=include_health_summary,
                )
            except Exception as exc:
                return _failed(node, exc)
            return ActionResult(
                sentinel_id=node.sentinel_id,
                ok=True,
                result="accepted",
                delivery=payload.delivery,
                queued=payload.queued,
                timestamp_utc=format_utc(payload.timestamp_utc),
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def execute_scans(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    technology: str,
    duration_seconds: int,
    dry_run: bool,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ActionResult]:
    resolved = settings or load_settings()
    maximum = resolved.max_scan_duration_seconds or MAX_SCAN_DURATION_SECONDS
    validate_scan_request(technology, duration_seconds, maximum)
    tech = cast(ScanTechnology, technology)
    if dry_run:
        return _dry_run_rows(
            nodes, technology=tech, duration_seconds=duration_seconds
        )
    async with _http_client(app_ctx, resolved) as http:

        async def one(node: SentinelNode) -> ActionResult:
            if not credentials.has_token(node.sentinel_id):
                return _failed(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                payload = await api.scan(
                    action="start",
                    technology=tech,
                    duration_seconds=duration_seconds,
                )
            except Exception as exc:
                return _failed(node, exc)
            return ActionResult(
                sentinel_id=node.sentinel_id,
                ok=True,
                result="accepted",
                technology=payload.technology or tech,
                duration_seconds=payload.duration_seconds or duration_seconds,
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def execute_reboots(
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    reason: str,
    dry_run: bool,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ActionResult]:
    if dry_run:
        return _dry_run_rows(nodes)
    resolved = settings or load_settings()
    async with _http_client(app_ctx, resolved) as http:

        async def one(node: SentinelNode) -> ActionResult:
            if not credentials.has_token(node.sentinel_id):
                return _failed(
                    node, CredentialError(f"no bearer token stored for {node.sentinel_id}")
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                await api.reboot(reason=reason)
            except Exception as exc:
                return _failed(node, exc)
            return ActionResult(
                sentinel_id=node.sentinel_id,
                ok=True,
                result="accepted",
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def check_node_credential(
    node: SentinelNode,
    credentials: CredentialStore,
    *,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> str:
    resolved = settings or load_settings()
    if not credentials.has_token(node.sentinel_id):
        raise CredentialError(f"no bearer token stored for {node.sentinel_id}")
    async with _http_client(app_ctx, resolved) as http:
        api = _api_client(node, credentials, http, app_ctx, resolved)
        info = await api.get_info()
    return info.sentinel_id
