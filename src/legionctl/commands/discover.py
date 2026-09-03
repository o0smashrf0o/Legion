from __future__ import annotations

from typing import Annotated

import httpx
import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.models.discovery import DiscoveredService, DiscoveryIssue
from legionctl.output.console import (
    confirm_or_decline,
    console,
    render_discovery_issues,
    render_discovery_table,
)
from legionctl.output.json import discovered_payload, emit_json
from legionctl.services.credentials import CredentialStore, read_bearer_token
from legionctl.services.discovery import (
    DEFAULT_DISCOVERY_TIMEOUT,
    discover_sentinels,
    save_discovery_cache,
)
from legionctl.services.inventory import add_node, load_inventory
from legionctl.settings import load_settings


def _add_discovered(
    records: list[DiscoveredService],
    issues: list[DiscoveryIssue],
    *,
    yes: bool,
    dry_run: bool,
    token_stdin: bool,
) -> None:
    blocked = {
        issue.sentinel_id
        for issue in issues
        if issue.code in {"duplicate_id", "inconsistent_hostname"}
    }
    credentials = CredentialStore()
    added: list[str] = []
    for item in records:
        if item.known or item.sentinel_id in blocked:
            continue
        label = item.zone or item.display_name or item.hostname or item.ip or item.sentinel_id
        detail = f"{label}, {item.ip}" if item.ip else label
        prompt = f"Add discovered Sentinel node {item.sentinel_id} ({detail}) to inventory?"
        if dry_run:
            console.print(f"Would add {item.sentinel_id} to inventory.")
            added.append(item.sentinel_id)
            continue
        confirm_or_decline(prompt, yes=yes)
        if not credentials.has_token(item.sentinel_id):
            token = read_bearer_token(
                item.sentinel_id,
                token_stdin=token_stdin,
                credentials=credentials,
            )
            credentials.set_token(item.sentinel_id, token)
        add_node(item.to_inventory_node())
        added.append(item.sentinel_id)
        console.print(
            f"Added {item.sentinel_id} to inventory and stored token in system keyring."
        )
    if added:
        audit_action(
            "discover_add",
            targets=added,
            result="success",
            dry_run=dry_run,
            confirmed_with_yes=yes,
        )


def discover_cmd(
    ctx: typer.Context,
    add: Annotated[
        bool,
        typer.Option("--add", help="Add discovered Sentinel nodes to inventory."),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="mDNS browse timeout in seconds."),
    ] = None,
    token_stdin: Annotated[
        bool,
        typer.Option("--token-stdin", help="Read bearer tokens from stdin when adding."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip confirmation prompts when adding."),
    ] = False,
) -> None:
    """Discover `_sentinel._tcp.local.` services via mDNS/zeroconf."""
    app_ctx = get_app_context(ctx)
    settings = load_settings()
    browse_timeout = timeout
    if browse_timeout is None:
        browse_timeout = app_ctx.timeout or DEFAULT_DISCOVERY_TIMEOUT
    credentials = CredentialStore()
    try:
        inventory = load_inventory()
        records, issues = discover_sentinels(
            inventory,
            credentials,
            timeout=browse_timeout,
            verify=not app_ctx.insecure_skip_tls_verify,
            http_timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.write_timeout_seconds,
                pool=settings.read_timeout_seconds,
            ),
        )
        save_discovery_cache(records)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(discovered_payload(records, issues))
    else:
        if issues:
            render_discovery_issues(issues)
        if not records:
            console.print("No Sentinel nodes discovered.")
        else:
            console.print(render_discovery_table(records))
    if add:
        try:
            _add_discovered(
                records,
                issues,
                yes=yes or app_ctx.yes,
                dry_run=app_ctx.dry_run,
                token_stdin=token_stdin,
            )
        except LegionError as exc:
            exit_cli(exc)
