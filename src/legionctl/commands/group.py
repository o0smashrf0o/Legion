from __future__ import annotations

from typing import Annotated

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console, render_groups_table
from legionctl.output.json import emit_json, groups_payload
from legionctl.services.inventory import (
    add_group_member,
    create_group,
    list_groups,
    remove_group_member,
)

app = typer.Typer(help="Manage local Sentinel groups.")


@app.command("list")
def group_list(ctx: typer.Context) -> None:
    """List Sentinel groups in the local inventory."""
    app_ctx = get_app_context(ctx)
    try:
        groups = list_groups()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(groups_payload(groups))
        return
    if not groups:
        console.print("No Sentinel groups in inventory.")
        return
    console.print(render_groups_table(groups))


@app.command("create")
def group_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Group name.")],
    description: Annotated[str, typer.Option("--description")] = "",
) -> None:
    """Create a local inventory group. Does not contact Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            audit_action(
                "group_create",
                targets=[],
                result="success",
                dry_run=True,
                details={"group": name},
            )
            console.print(f"Would create group {name}.")
            return
        create_group(name, description=description)
    except LegionError as exc:
        exit_cli(exc)
    audit_action("group_create", targets=[], result="success", details={"group": name})
    console.print(f"Created group {name}.")


@app.command("add-member")
def group_add_member_cmd(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group name.")],
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
) -> None:
    """Add a Sentinel node to a local group. Does not contact the node."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            audit_action(
                "group_add_member",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
                details={"group": group},
            )
            console.print(f"Would add {sentinel_id} to group {group}.")
            return
        add_group_member(group, sentinel_id)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "group_add_member",
        targets=[sentinel_id],
        result="success",
        details={"group": group},
    )
    console.print(f"Added {sentinel_id} to group {group}.")


@app.command("remove-member")
def group_remove_member_cmd(
    ctx: typer.Context,
    group: Annotated[str, typer.Argument(help="Group name.")],
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
) -> None:
    """Remove a Sentinel node from a local group. Does not contact the node."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            audit_action(
                "group_remove_member",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
                details={"group": group},
            )
            console.print(f"Would remove {sentinel_id} from group {group}.")
            return
        remove_group_member(group, sentinel_id)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "group_remove_member",
        targets=[sentinel_id],
        result="success",
        details={"group": group},
    )
    console.print(f"Removed {sentinel_id} from group {group}.")
