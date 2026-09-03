from __future__ import annotations

import typer

from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console, print_error, render_nodes_table
from legionctl.output.json import emit_json, nodes_payload
from legionctl.services.inventory import list_nodes

app = typer.Typer(help="Manage Sentinel node inventory.")


@app.command("list")
def node_list(ctx: typer.Context) -> None:
    """List Sentinel nodes in the local inventory."""
    app_ctx = get_app_context(ctx)
    try:
        nodes = list_nodes()
    except LegionError as exc:
        print_error(str(exc))
        raise typer.Exit(exc.exit_code) from exc
    if app_ctx.json_output:
        emit_json(nodes_payload(nodes))
        return
    if not nodes:
        console.print("No Sentinel nodes in inventory.")
        return
    console.print(render_nodes_table(nodes))
