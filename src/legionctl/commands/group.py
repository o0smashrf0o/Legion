from __future__ import annotations

import typer

from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console, print_error, render_groups_table
from legionctl.output.json import emit_json, groups_payload
from legionctl.services.inventory import list_groups

app = typer.Typer(help="Manage local Sentinel groups.")


@app.command("list")
def group_list(ctx: typer.Context) -> None:
    """List Sentinel groups in the local inventory."""
    app_ctx = get_app_context(ctx)
    try:
        groups = list_groups()
    except LegionError as exc:
        print_error(str(exc))
        raise typer.Exit(exc.exit_code) from exc
    if app_ctx.json_output:
        emit_json(groups_payload(groups))
        return
    if not groups:
        console.print("No Sentinel groups in inventory.")
        return
    console.print(render_groups_table(groups))
