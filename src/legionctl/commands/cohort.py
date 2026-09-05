from __future__ import annotations

from typing import Annotated

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import ConfirmationDeclined, LegionError
from legionctl.output.console import confirm_or_decline, console
from legionctl.output.json import emit_json
from legionctl.services import org
from legionctl.services.inventory import load_inventory

app = typer.Typer(
    help="Manage Cohorts. Groups are flexible labels; Cohorts are operational units."
)


@app.command("list")
def cohort_list(ctx: typer.Context) -> None:
    """List Cohorts."""
    app_ctx = get_app_context(ctx)
    try:
        cohorts = org.list_cohorts()
        inventory = load_inventory()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json({"cohorts": [cohort.model_dump(mode="json") for cohort in cohorts]})
        return
    if not cohorts:
        console.print("No Cohorts defined.")
        return
    for cohort in cohorts:
        readiness, _flags, roster = org.cohort_readiness(cohort, inventory)
        console.print(
            f"{cohort.cohort_id}  {cohort.display_name}  {roster}/5  {readiness}  "
            f"primus={cohort.primus_sentinel_id or '--'}"
        )


@app.command("create")
def cohort_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name")],
    cohort_id: Annotated[str | None, typer.Option("--id")] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Create a Cohort."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(f"Create Cohort '{name}'?", yes=confirmed)
        cohort = org.create_cohort(
            display_name=name,
            cohort_id=cohort_id,
            description=description,
            dry_run=app_ctx.dry_run,
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_create",
        targets=[cohort.cohort_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"name": cohort.display_name},
    )
    console.print(f"Created Cohort {cohort.cohort_id}.")


@app.command("assign-zone")
def cohort_assign_zone(
    ctx: typer.Context,
    cohort_id: Annotated[str, typer.Argument()],
    zone_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Assign a Cohort to one Zone."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        before = org.get_cohort(cohort_id)
        if not app_ctx.dry_run:
            confirm_or_decline(
                f"Assign Cohort {cohort_id} to Zone {zone_id}?",
                yes=confirmed,
            )
        cohort = org.assign_cohort_zone(cohort_id, zone_id, dry_run=app_ctx.dry_run)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_assign_zone",
        targets=[cohort_id, zone_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"before": before.zone_id, "after": cohort.zone_id},
    )
    console.print(f"Assigned {cohort_id} to {zone_id}.")


@app.command("add-sentinel")
def cohort_add_sentinel(
    ctx: typer.Context,
    cohort_id: Annotated[str, typer.Argument()],
    sentinel_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Add a Sentinel to a Cohort."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(
                f"Add Sentinel {sentinel_id} to Cohort {cohort_id}?",
                yes=confirmed,
            )
        org.add_sentinel_to_cohort(cohort_id, sentinel_id, dry_run=app_ctx.dry_run)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_add_sentinel",
        targets=[cohort_id, sentinel_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"after": sentinel_id},
    )
    console.print(f"Added {sentinel_id} to {cohort_id}.")


@app.command("remove-sentinel")
def cohort_remove_sentinel(
    ctx: typer.Context,
    cohort_id: Annotated[str, typer.Argument()],
    sentinel_id: Annotated[str, typer.Argument()],
    new_primus: Annotated[str | None, typer.Option("--new-primus")] = None,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Remove a Sentinel from a Cohort."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(
                f"Remove Sentinel {sentinel_id} from Cohort {cohort_id}?",
                yes=confirmed,
            )
        org.remove_sentinel_from_cohort(
            cohort_id, sentinel_id, new_primus=new_primus, dry_run=app_ctx.dry_run
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_remove_sentinel",
        targets=[cohort_id, sentinel_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"new_primus": new_primus},
    )
    console.print(f"Removed {sentinel_id} from {cohort_id}.")


@app.command("set-primus")
def cohort_set_primus(
    ctx: typer.Context,
    cohort_id: Annotated[str, typer.Argument()],
    sentinel_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Set or transfer the Primus role. Primus is a designation, not mesh routing."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        before = org.get_cohort(cohort_id)
        if not app_ctx.dry_run:
            confirm_or_decline(
                (
                    f"Transfer Primus on {cohort_id} from "
                    f"{before.primus_sentinel_id} to {sentinel_id}?"
                ),
                yes=confirmed,
            )
        org.set_primus(cohort_id, sentinel_id, dry_run=app_ctx.dry_run)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_set_primus",
        targets=[cohort_id, sentinel_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"before": before.primus_sentinel_id, "after": sentinel_id},
    )
    console.print(f"Primus for {cohort_id} is {sentinel_id}.")


@app.command("deactivate")
def cohort_deactivate(
    ctx: typer.Context,
    cohort_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Deactivate a Cohort without deleting history."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        if not app_ctx.dry_run:
            confirm_or_decline(f"Deactivate Cohort {cohort_id}?", yes=confirmed)
        org.deactivate_cohort(cohort_id, dry_run=app_ctx.dry_run)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "cohort_deactivate",
        targets=[cohort_id],
        result="success",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        details={"before": "active", "after": "inactive"},
    )
    console.print(f"Deactivated Cohort {cohort_id}.")


@app.command("status")
def cohort_status(ctx: typer.Context, cohort_id: Annotated[str, typer.Argument()]) -> None:
    """Show Cohort roster and derived readiness."""
    app_ctx = get_app_context(ctx)
    try:
        cohort = org.get_cohort(cohort_id)
        inventory = load_inventory()
        readiness, flags, roster = org.cohort_readiness(cohort, inventory)
    except LegionError as exc:
        exit_cli(exc)
    payload = {
        **cohort.model_dump(mode="json"),
        "readiness": readiness,
        "flags": flags,
        "roster": f"{roster}/5",
    }
    if app_ctx.json_output:
        emit_json(payload)
        return
    console.print(
        f"COHORT // {cohort.display_name}\n"
        f"Readiness {readiness}  roster {roster}/5  primus {cohort.primus_sentinel_id or '--'}"
    )
