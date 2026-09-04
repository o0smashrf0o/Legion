from __future__ import annotations

import uuid
from collections.abc import Sequence

import httpx

from legionctl import __version__
from legionctl.context import AppContext
from legionctl.errors import CredentialError, NodeValidationError, UsageError
from legionctl.models.deploy import DeployAction, ProfilePlanRow, ProfilePushResult
from legionctl.models.inventory import SentinelNode
from legionctl.models.node_api import RulesResponse
from legionctl.models.profile import Profile
from legionctl.services.credentials import CredentialStore
from legionctl.services.fleet import (
    _api_client,
    _bounded_map,
    classify_error,
    client_timeouts,
    error_message,
)
from legionctl.settings import AppSettings, load_settings


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


def plan_action(
    profile: Profile,
    current_id: str | None,
    current_revision: int | None,
) -> DeployAction:
    if not current_id:
        return "install"
    if current_id == profile.profile_id and current_revision == profile.revision:
        return "unchanged"
    if (
        current_id == profile.profile_id
        and current_revision is not None
        and current_revision > profile.revision
    ):
        return "downgrade"
    return "update"


def will_write(row: ProfilePlanRow, *, allow_downgrade: bool) -> bool:
    if row.action in {"update", "install"}:
        return True
    return row.action == "downgrade" and allow_downgrade


def reject_downgrades(plan: Sequence[ProfilePlanRow], *, allow_downgrade: bool) -> None:
    if allow_downgrade:
        return
    blocked = [row for row in plan if row.action == "downgrade"]
    if not blocked:
        return
    details = ", ".join(
        f"{row.sentinel_id} ({row.current_profile_id} r{row.current_revision})"
        for row in blocked
    )
    raise UsageError(f"revision downgrade requires --allow-downgrade: {details}")


def _active_label(profile_id: str | None, revision: int | None) -> str | None:
    if not profile_id:
        return None
    if revision is None:
        return profile_id
    return f"{profile_id} r{revision}"


async def collect_push_plan(
    profile: Profile,
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ProfilePlanRow]:
    resolved = settings or load_settings()
    async with _http_client(app_ctx, resolved) as http:

        async def one(node: SentinelNode) -> ProfilePlanRow:
            if not credentials.has_token(node.sentinel_id):
                return ProfilePlanRow(
                    sentinel_id=node.sentinel_id,
                    zone=node.zone,
                    candidate_profile_id=profile.profile_id,
                    candidate_revision=profile.revision,
                    action="unreachable",
                    reachable=False,
                    ok=False,
                    error=error_message(
                        CredentialError(f"no bearer token stored for {node.sentinel_id}")
                    ),
                    error_kind="auth",
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                info = await api.get_info()
            except Exception as exc:
                kind = classify_error(exc)
                return ProfilePlanRow(
                    sentinel_id=node.sentinel_id,
                    zone=node.zone,
                    candidate_profile_id=profile.profile_id,
                    candidate_revision=profile.revision,
                    action="unreachable",
                    reachable=False,
                    ok=False,
                    error=error_message(exc),
                    error_kind=kind,
                )
            action = plan_action(profile, info.profile_id, info.profile_revision)
            key = str(uuid.uuid4()) if action in {"update", "install", "downgrade"} else None
            return ProfilePlanRow(
                sentinel_id=node.sentinel_id,
                zone=node.zone,
                current_profile_id=info.profile_id,
                current_revision=info.profile_revision,
                candidate_profile_id=profile.profile_id,
                candidate_revision=profile.revision,
                action=action,
                reachable=True,
                ok=True,
                idempotency_key=key,
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)


async def execute_push(
    profile: Profile,
    plan: Sequence[ProfilePlanRow],
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    allow_downgrade: bool,
    dry_run: bool,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ProfilePushResult]:
    resolved = settings or load_settings()
    by_id = {node.sentinel_id: node for node in nodes}
    results: list[ProfilePushResult] = []
    to_write = [row for row in plan if will_write(row, allow_downgrade=allow_downgrade)]
    if dry_run:
        for row in plan:
            if will_write(row, allow_downgrade=allow_downgrade):
                results.append(
                    ProfilePushResult(
                        sentinel_id=row.sentinel_id,
                        result="dry_run",
                        active_profile=None,
                        ok=True,
                        idempotency_key=row.idempotency_key,
                    )
                )
            elif row.action == "unchanged":
                results.append(
                    ProfilePushResult(
                        sentinel_id=row.sentinel_id,
                        result="skipped",
                        active_profile=_active_label(
                            row.current_profile_id, row.current_revision
                        ),
                        ok=True,
                    )
                )
            else:
                results.append(
                    ProfilePushResult(
                        sentinel_id=row.sentinel_id,
                        result="unreachable",
                        ok=False,
                        error=row.error,
                        error_kind=row.error_kind,
                    )
                )
        return results

    written: dict[str, ProfilePushResult] = {}
    if to_write:
        async with _http_client(app_ctx, resolved) as http:

            async def one(row: ProfilePlanRow) -> ProfilePushResult:
                node = by_id[row.sentinel_id]
                api = _api_client(node, credentials, http, app_ctx, resolved)
                try:
                    activated = await api.put_rules(
                        profile, idempotency_key=row.idempotency_key
                    )
                except NodeValidationError as exc:
                    return ProfilePushResult(
                        sentinel_id=row.sentinel_id,
                        result="rejected",
                        ok=False,
                        error=error_message(exc),
                        error_kind="other",
                        idempotency_key=row.idempotency_key,
                    )
                except Exception as exc:
                    kind = classify_error(exc)
                    result_name = "unreachable" if kind == "unreachable" else "error"
                    return ProfilePushResult(
                        sentinel_id=row.sentinel_id,
                        result=result_name,  # type: ignore[arg-type]
                        ok=False,
                        error=error_message(exc),
                        error_kind=kind,
                        idempotency_key=row.idempotency_key,
                    )
                return ProfilePushResult(
                    sentinel_id=row.sentinel_id,
                    result="activated",
                    active_profile=_active_label(activated.profile_id, activated.revision),
                    ok=True,
                    idempotency_key=row.idempotency_key,
                )

            for item in await _bounded_map(to_write, one, concurrency=resolved.concurrency):
                written[item.sentinel_id] = item

    for row in plan:
        if row.sentinel_id in written:
            results.append(written[row.sentinel_id])
        elif row.action == "unchanged":
            results.append(
                ProfilePushResult(
                    sentinel_id=row.sentinel_id,
                    result="skipped",
                    active_profile=_active_label(row.current_profile_id, row.current_revision),
                    ok=True,
                )
            )
        else:
            results.append(
                ProfilePushResult(
                    sentinel_id=row.sentinel_id,
                    result="unreachable",
                    ok=False,
                    error=row.error,
                    error_kind=row.error_kind,
                )
            )
    return results


async def collect_profile_diff(
    profile: Profile,
    nodes: Sequence[SentinelNode],
    credentials: CredentialStore,
    *,
    app_ctx: AppContext,
    settings: AppSettings | None = None,
) -> list[ProfilePlanRow]:
    resolved = settings or load_settings()
    async with _http_client(app_ctx, resolved) as http:

        async def one(node: SentinelNode) -> ProfilePlanRow:
            if not credentials.has_token(node.sentinel_id):
                return ProfilePlanRow(
                    sentinel_id=node.sentinel_id,
                    zone=node.zone,
                    candidate_profile_id=profile.profile_id,
                    candidate_revision=profile.revision,
                    action="unreachable",
                    reachable=False,
                    ok=False,
                    error=error_message(
                        CredentialError(f"no bearer token stored for {node.sentinel_id}")
                    ),
                    error_kind="auth",
                )
            api = _api_client(node, credentials, http, app_ctx, resolved)
            try:
                info = await api.get_info()
            except Exception as exc:
                return ProfilePlanRow(
                    sentinel_id=node.sentinel_id,
                    zone=node.zone,
                    candidate_profile_id=profile.profile_id,
                    candidate_revision=profile.revision,
                    action="unreachable",
                    reachable=False,
                    ok=False,
                    error=error_message(exc),
                    error_kind=classify_error(exc),
                )
            current_id = info.profile_id
            current_revision = info.profile_revision
            try:
                rules: RulesResponse = await api.get_rules()
                current_id = rules.profile_id
                current_revision = rules.revision
            except Exception:
                pass
            action = plan_action(profile, current_id, current_revision)
            return ProfilePlanRow(
                sentinel_id=node.sentinel_id,
                zone=node.zone,
                current_profile_id=current_id,
                current_revision=current_revision,
                candidate_profile_id=profile.profile_id,
                candidate_revision=profile.revision,
                action=action,
                reachable=True,
                ok=True,
            )

        return await _bounded_map(nodes, one, concurrency=resolved.concurrency)
