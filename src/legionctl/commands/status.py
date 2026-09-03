from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from legionctl.commands.common import exit_cli, resolve_cli_targets
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.models.fleet import FleetNodeEvents, FleetNodeHealth, FleetNodeStatus
from legionctl.output.console import (
    console,
    print_warning,
    render_events_table,
    render_health_table,
    render_status_table,
)
from legionctl.output.json import emit_json, events_payload, health_payload, status_payload
from legionctl.services.credentials import CredentialStore
from legionctl.services.fleet import collect_events, collect_health, collect_status, fleet_exit_code
from legionctl.settings import load_settings

NodeOpt = Annotated[str | None, typer.Option("--node", help="Target a Sentinel node ID.")]
GroupOpt = Annotated[str | None, typer.Option("--group", help="Target a local inventory group.")]
AllOpt = Annotated[bool, typer.Option("--all", help="Target all enabled Sentinel nodes.")]
SelectorOpt = Annotated[
    str | None,
    typer.Option("--selector", help="Target selector, for example zone=North Door."),
]


def _finish(rows: list[FleetNodeStatus] | list[FleetNodeHealth] | list[FleetNodeEvents]) -> None:
    code = fleet_exit_code(rows)
    if code != 0:
        raise typer.Exit(code)


def _warn_failures(
    rows: list[FleetNodeStatus] | list[FleetNodeHealth] | list[FleetNodeEvents],
) -> None:
    for row in rows:
        if not row.ok and row.error:
            print_warning(f"{row.sentinel_id}: {row.error}")


def status_cmd(
    ctx: typer.Context,
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
) -> None:
    """Show status and health for selected Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        rows = asyncio.run(
            collect_status(
                nodes,
                CredentialStore(),
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(status_payload(rows))
    else:
        console.print(render_status_table(rows))
        _warn_failures(rows)
    _finish(rows)


def health_cmd(
    ctx: typer.Context,
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
) -> None:
    """Show health for selected Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        rows = asyncio.run(
            collect_health(
                nodes,
                CredentialStore(),
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(health_payload(rows))
    else:
        console.print(render_health_table(rows))
        _warn_failures(rows)
    _finish(rows)


def events_cmd(
    ctx: typer.Context,
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum events per node.")] = 100,
) -> None:
    """Show recent metadata-only events for selected Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        rows = asyncio.run(
            collect_events(
                nodes,
                CredentialStore(),
                limit=limit,
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(events_payload(rows))
    else:
        console.print(render_events_table(rows))
        _warn_failures(rows)
    _finish(rows)
