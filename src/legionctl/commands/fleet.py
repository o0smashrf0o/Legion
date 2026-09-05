from __future__ import annotations

import typer

from legionctl.commands.common import exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console
from legionctl.output.json import emit_json
from legionctl.services import org
from legionctl.services.inventory import list_nodes, load_inventory

app = typer.Typer(help="Fleet overview for LEGION command-and-control.")


@app.command("status")
def fleet_status(ctx: typer.Context) -> None:
    """Show Fleet counts for Zones, Cohorts, and Sentinels."""
    app_ctx = get_app_context(ctx)
    try:
        inventory = load_inventory()
        nodes = list_nodes()
        zones = org.list_zones()
        cohorts = org.list_cohorts()
    except LegionError as exc:
        exit_cli(exc)
    readiness_counts: dict[str, int] = {}
    for cohort in cohorts:
        readiness, _flags, _roster = org.cohort_readiness(cohort, inventory)
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
    payload = {
        "sentinels": len(nodes),
        "zones": len(zones),
        "cohorts": len(cohorts),
        "cohort_readiness": readiness_counts,
        "note": "Groups remain ad hoc CLI labels; Cohorts are operational units.",
    }
    if app_ctx.json_output:
        emit_json(payload)
        return
    console.print("LEGION // FLEET")
    console.print(
        f"Sentinels {payload['sentinels']}  "
        f"Zones {payload['zones']}  Cohorts {payload['cohorts']}"
    )
    for key, value in sorted(readiness_counts.items()):
        console.print(f"  {key}: {value}")
