from __future__ import annotations

import asyncio
from typing import Annotated, Literal

import typer

from legionctl.commands.common import audit_action, exit_cli, resolve_cli_targets
from legionctl.context import get_app_context
from legionctl.errors import ConfirmationDeclined, LegionError, UsageError
from legionctl.models.actions import ActionResult
from legionctl.models.inventory import SentinelNode
from legionctl.output.console import (
    confirm_or_decline,
    console,
    print_warning,
    render_action_table,
)
from legionctl.output.json import action_payload, emit_json
from legionctl.services.actions import (
    execute_reboots,
    execute_scans,
    execute_test_alerts,
    validate_scan_request,
)
from legionctl.services.credentials import CredentialStore
from legionctl.services.fleet import fleet_exit_code
from legionctl.settings import load_settings

NodeOpt = Annotated[str | None, typer.Option("--node", help="Target a Sentinel node ID.")]
GroupOpt = Annotated[str | None, typer.Option("--group", help="Target a local inventory group.")]
AllOpt = Annotated[bool, typer.Option("--all", help="Target all enabled Sentinel nodes.")]
SelectorOpt = Annotated[
    str | None,
    typer.Option("--selector", help="Target selector, for example zone=North Door."),
]


def _show_targets(nodes: list[SentinelNode]) -> None:
    console.print(f"Resolved targets: {len(nodes)}")
    for node in nodes:
        label = node.zone or node.hostname or node.base_url
        console.print(f"  {node.sentinel_id} ({label})")


def _emit(rows: list[ActionResult], *, json_output: bool, dry_run: bool) -> None:
    if json_output:
        emit_json(action_payload(rows, dry_run=dry_run))
        return
    console.print(render_action_table(rows))
    for row in rows:
        if not row.ok and row.error:
            print_warning(f"{row.sentinel_id}: {row.error}")


def _finish(rows: list[ActionResult]) -> None:
    code = fleet_exit_code(rows)
    if code != 0:
        raise typer.Exit(code)


def test_alert_cmd(
    ctx: typer.Context,
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
    message: Annotated[str, typer.Option("--message")] = "Legion test alert",
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Send a Discord test alert through selected Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        if not app_ctx.json_output:
            _show_targets(nodes)
        if not app_ctx.dry_run:
            confirm_or_decline(
                f"Send a Discord test alert to {len(nodes)} Sentinel node(s)?",
                yes=confirmed,
            )
        rows = asyncio.run(
            execute_test_alerts(
                nodes,
                CredentialStore(),
                message=message,
                include_health_summary=True,
                dry_run=app_ctx.dry_run,
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "test_alert",
        targets=[item.sentinel_id for item in nodes],
        result="success" if all(row.ok for row in rows) else "partial",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={
            "accepted": [row.sentinel_id for row in rows if row.ok],
            "failed": [row.sentinel_id for row in rows if not row.ok],
        },
    )
    _emit(rows, json_output=app_ctx.json_output, dry_run=app_ctx.dry_run)
    _finish(rows)


def scan_cmd(
    ctx: typer.Context,
    technology: Annotated[
        Literal["wifi", "ble", "bt_classic"],
        typer.Option("--technology", help="wifi, ble, or bt_classic."),
    ],
    duration: Annotated[
        int,
        typer.Option("--duration", help="Bounded scan duration in seconds."),
    ],
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Start a bounded diagnostic scan on selected Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        settings = load_settings()
        validate_scan_request(technology, duration, settings.max_scan_duration_seconds)
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        if not app_ctx.json_output:
            _show_targets(nodes)
        if not app_ctx.dry_run:
            confirm_or_decline(
                (
                    f"Start a bounded {technology} scan ({duration}s) "
                    f"on {len(nodes)} Sentinel node(s)?"
                ),
                yes=confirmed,
            )
        rows = asyncio.run(
            execute_scans(
                nodes,
                CredentialStore(),
                technology=technology,
                duration_seconds=duration,
                dry_run=app_ctx.dry_run,
                app_ctx=app_ctx,
                settings=settings,
            )
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "scan",
        targets=[item.sentinel_id for item in nodes],
        result="success" if all(row.ok for row in rows) else "partial",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={
            "technology": technology,
            "duration_seconds": duration,
            "accepted": [row.sentinel_id for row in rows if row.ok],
            "failed": [row.sentinel_id for row in rows if not row.ok],
        },
    )
    _emit(rows, json_output=app_ctx.json_output, dry_run=app_ctx.dry_run)
    _finish(rows)


def reboot_cmd(
    ctx: typer.Context,
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
    force_all: Annotated[
        bool,
        typer.Option("--force-all", help="Required with --all to reboot every node."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Reboot selected Sentinel nodes. Disruptive; requires confirmation."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if all_nodes and not force_all:
            raise UsageError("reboot --all requires --force-all")
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        if not app_ctx.json_output:
            _show_targets(nodes)
        if not app_ctx.dry_run:
            names = ", ".join(item.sentinel_id for item in nodes)
            confirm_or_decline(
                f"Reboot Sentinel node(s) {names}?",
                yes=confirmed,
            )
        rows = asyncio.run(
            execute_reboots(
                nodes,
                CredentialStore(),
                reason="operator_requested",
                dry_run=app_ctx.dry_run,
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "reboot",
        targets=[item.sentinel_id for item in nodes],
        result="success" if all(row.ok for row in rows) else "partial",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={
            "force_all": force_all,
            "accepted": [row.sentinel_id for row in rows if row.ok],
            "failed": [row.sentinel_id for row in rows if not row.ok],
        },
    )
    _emit(rows, json_output=app_ctx.json_output, dry_run=app_ctx.dry_run)
    _finish(rows)
