from __future__ import annotations

from typing import Annotated

import typer

from legionctl.commands.common import exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console
from legionctl.output.json import emit_json
from legionctl.services import org

app = typer.Typer(help="Sentinel assignment view for Fleet hierarchy.")


@app.command("assignment")
def sentinel_assignment(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument()],
) -> None:
    """Show Zone, Cohort, and Primus role for a Sentinel."""
    app_ctx = get_app_context(ctx)
    try:
        payload = org.assignment_for(sentinel_id)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(payload)
        return
    console.print(
        f"Sentinel: {payload['sentinel_id']}\n"
        f"Zone: {payload['zone_name'] or '--'}\n"
        f"Cohort: {payload['cohort_name'] or '--'}\n"
        f"Role: {payload['role']}"
    )
