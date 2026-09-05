from __future__ import annotations

from typing import Annotated

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import ConfirmationDeclined, LegionError
from legionctl.output.console import confirm_or_decline, console
from legionctl.output.json import emit_json
from legionctl.services import org

app = typer.Typer(help="Manage Legion Zones. Groups are ad hoc labels; Zones are coverage areas.")


@app.command("list")
def zone_list(ctx: typer.Context) -> None:
    """List Zones in the local Fleet model."""
    app_ctx = get_app_context(ctx)
    try:
        zones = org.list_zones()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json({"zones": [zone.model_dump(mode="json") for zone in zones]})
        return
    if not zones:
        console.print("No Zones defined.")
        return
    for zone in zones:
        console.print(f"{zone.zone_id}  {zone.name}  {zone.status}  {zone.zone_type}")


@app.command("show")
def zone_show(ctx: typer.Context, zone_id: Annotated[str, typer.Argument()]) -> None:
    """Show one Zone."""
    app_ctx = get_app_context(ctx)
    try:
        zone = org.get_zone(zone_id)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(zone.model_dump(mode="json"))
        return
    console.print(f"ZONE // {zone.name}\nID {zone.zone_id}\n{zone.description}")


@app.command("create")
def zone_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name")],
    zone_type: Annotated[str, typer.Option("--type")] = "physical",
    description: Annotated[str, typer.Option("--description")] = "",
    zone_id: Annotated[str | None, typer.Option("--id")] = None,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Create a Zone."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(f"Create Zone '{name}'?", yes=confirmed)
        zone = org.create_zone(
            name=name,
            zone_id=zone_id,
            description=description,
            zone_type=zone_type,
            dry_run=app_ctx.dry_run,
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "zone_create",
        targets=[zone.zone_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"name": zone.name, "before": None, "after": zone.zone_id},
    )
    console.print(f"Created Zone {zone.zone_id}.")


@app.command("archive")
def zone_archive(
    ctx: typer.Context,
    zone_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Archive a Zone without deleting history."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(f"Archive Zone {zone_id}?", yes=confirmed)
        zone = org.archive_zone(zone_id, dry_run=app_ctx.dry_run)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "zone_archive",
        targets=[zone.zone_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"before": "active", "after": "inactive"},
    )
    console.print(f"Archived Zone {zone.zone_id}.")
