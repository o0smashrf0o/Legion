from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from legionctl.commands.common import audit_action, exit_cli, resolve_cli_targets
from legionctl.context import get_app_context
from legionctl.errors import ConfirmationDeclined, LegionError, ValidationFailed
from legionctl.output.console import (
    confirm_or_decline,
    console,
    print_error,
    render_profile_plan_table,
    render_profile_push_table,
    render_profile_valid,
    render_profiles_table,
)
from legionctl.output.json import (
    emit_json,
    profile_invalid_payload,
    profile_list_payload,
    profile_plan_payload,
    profile_push_payload,
    profile_valid_payload,
)
from legionctl.services.credentials import CredentialStore
from legionctl.services.deploy import (
    collect_profile_diff,
    collect_push_plan,
    execute_push,
    reject_downgrades,
    will_write,
)
from legionctl.services.fleet import fleet_exit_code
from legionctl.services.profiles import (
    clone_profile,
    create_profile,
    export_profile,
    import_profile,
    list_installed_profiles,
    load_installed_profile,
    validate_profile_file,
)
from legionctl.settings import load_settings

app = typer.Typer(help="Create, validate, and manage SOI profiles.")

NodeOpt = Annotated[str | None, typer.Option("--node", help="Target a Sentinel node ID.")]
GroupOpt = Annotated[str | None, typer.Option("--group", help="Target a local inventory group.")]
AllOpt = Annotated[bool, typer.Option("--all", help="Target all enabled Sentinel nodes.")]
SelectorOpt = Annotated[
    str | None,
    typer.Option("--selector", help="Target selector, for example zone=North Door."),
]


@app.command("validate")
def profile_validate(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Path to a profile JSON file.")],
) -> None:
    """Validate a local SOI profile without contacting Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        profile = validate_profile_file(path)
    except ValidationFailed as exc:
        if app_ctx.json_output:
            emit_json(profile_invalid_payload(exc.errors))
        else:
            print_error("Profile validation failed:")
            for error in exc.errors:
                print_error(f"  {error}")
        raise typer.Exit(exc.exit_code) from exc
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(profile_valid_payload(profile))
        return
    console.print(render_profile_valid(profile))


@app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List locally stored SOI profiles."""
    app_ctx = get_app_context(ctx)
    try:
        profiles = list_installed_profiles()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(profile_list_payload(profiles))
        return
    if not profiles:
        console.print("No SOI profiles installed.")
        return
    console.print(render_profiles_table(profiles))


@app.command("show")
def profile_show(
    ctx: typer.Context,
    profile_id: Annotated[str, typer.Argument(help="Installed profile ID.")],
) -> None:
    """Show a locally stored SOI profile."""
    app_ctx = get_app_context(ctx)
    try:
        profile = load_installed_profile(profile_id)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(profile.model_dump(mode="json"))
        return
    console.print(render_profile_valid(profile))
    if profile.description:
        console.print(f"Description: {profile.description}")


@app.command("create")
def profile_create_cmd(
    ctx: typer.Context,
    profile_id: Annotated[str, typer.Argument(help="New profile ID.")],
    description: Annotated[str, typer.Option("--description")] = "",
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Create a valid minimal SOI profile from the built-in template."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            console.print(f"Would create profile {profile_id}.")
            return
        profile = create_profile(profile_id, description=description, overwrite=overwrite)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(profile_valid_payload(profile))
        return
    console.print(f"Created profile {profile.profile_id} revision {profile.revision}.")


@app.command("import")
def profile_import_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Path to a profile JSON file.")],
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an existing profile with the same ID."),
    ] = False,
) -> None:
    """Import a validated SOI profile into local storage."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            profile = validate_profile_file(path)
            console.print(f"Would import profile {profile.profile_id}.")
            return
        profile = import_profile(path, overwrite=overwrite)
    except ValidationFailed as exc:
        print_error("Profile validation failed:")
        for error in exc.errors:
            print_error(f"  {error}")
        raise typer.Exit(exc.exit_code) from exc
    except LegionError as exc:
        exit_cli(exc)
    console.print(f"Imported profile {profile.profile_id} revision {profile.revision}.")


@app.command("export")
def profile_export_cmd(
    ctx: typer.Context,
    profile_id: Annotated[str, typer.Argument(help="Installed profile ID.")],
    output: Annotated[Path, typer.Option("--output", help="Destination JSON file.")],
) -> None:
    """Export an installed SOI profile to a JSON file."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            console.print(f"Would export {profile_id} to {output}.")
            return
        export_profile(profile_id, output)
    except LegionError as exc:
        exit_cli(exc)
    console.print(f"Exported {profile_id} to {output}.")


@app.command("clone")
def profile_clone_cmd(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source profile ID.")],
    dest_id: Annotated[str, typer.Argument(help="New profile ID.")],
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Clone an installed SOI profile to a new profile ID at revision 1."""
    app_ctx = get_app_context(ctx)
    try:
        if app_ctx.dry_run:
            console.print(f"Would clone {source_id} to {dest_id}.")
            return
        profile = clone_profile(source_id, dest_id, overwrite=overwrite)
    except LegionError as exc:
        exit_cli(exc)
    console.print(f"Cloned {source_id} to {profile.profile_id} revision {profile.revision}.")


@app.command("diff")
def profile_diff_cmd(
    ctx: typer.Context,
    profile_id: Annotated[str, typer.Argument(help="Installed profile ID.")],
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
) -> None:
    """Compare a local SOI profile to the active profile on Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    try:
        profile = load_installed_profile(profile_id)
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        plan = asyncio.run(
            collect_profile_diff(
                profile,
                nodes,
                CredentialStore(),
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(profile_plan_payload(profile, plan))
    else:
        console.print(f"Resolved targets: {len(nodes)}")
        console.print(render_profile_plan_table(plan))
    code = fleet_exit_code(plan)
    if code != 0:
        raise typer.Exit(code)


@app.command("push")
def profile_push_cmd(
    ctx: typer.Context,
    profile_id: Annotated[str, typer.Argument(help="Installed profile ID.")],
    node: NodeOpt = None,
    group: GroupOpt = None,
    all_nodes: AllOpt = False,
    selector: SelectorOpt = None,
    allow_downgrade: Annotated[
        bool,
        typer.Option("--allow-downgrade", help="Allow pushing a lower revision."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Validate and atomically deploy an SOI profile to Sentinel nodes."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        profile = load_installed_profile(profile_id)
        nodes = resolve_cli_targets(
            node=node, group=group, all_nodes=all_nodes, selector=selector
        )
        plan = asyncio.run(
            collect_push_plan(
                profile,
                nodes,
                CredentialStore(),
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)

    if not app_ctx.json_output:
        console.print(f"Resolved targets: {len(nodes)}")
        console.print(render_profile_plan_table(plan))

    try:
        reject_downgrades(plan, allow_downgrade=allow_downgrade)
        writable = [row for row in plan if will_write(row, allow_downgrade=allow_downgrade)]
        if writable and not app_ctx.dry_run:
            confirm_or_decline(
                f"Deploy {profile.profile_id} revision {profile.revision} "
                f"to {len(writable)} Sentinel nodes?",
                yes=confirmed,
            )
        results = asyncio.run(
            execute_push(
                profile,
                plan,
                nodes,
                CredentialStore(),
                allow_downgrade=allow_downgrade,
                dry_run=app_ctx.dry_run,
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)

    activated = [row.sentinel_id for row in results if row.result == "activated"]
    failed = [row.sentinel_id for row in results if not row.ok]
    skipped = [row.sentinel_id for row in results if row.result in {"skipped", "dry_run"}]
    audit_action(
        "profile_push",
        targets=[node.sentinel_id for node in nodes],
        result="success" if not failed else "partial",
        dry_run=app_ctx.dry_run,
        confirmed_with_yes=confirmed,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        details={"activated": activated, "failed": failed, "skipped": skipped},
    )
    if app_ctx.json_output:
        emit_json(profile_push_payload(profile, plan, results, dry_run=app_ctx.dry_run))
    else:
        console.print(render_profile_push_table(results))
    code = fleet_exit_code(results)
    if code != 0:
        raise typer.Exit(code)
