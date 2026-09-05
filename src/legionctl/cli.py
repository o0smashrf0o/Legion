from __future__ import annotations

from typing import Annotated

import typer

from legionctl import __version__
from legionctl.commands import cohort as cohort_commands
from legionctl.commands import credential as credential_commands
from legionctl.commands import fleet as fleet_commands
from legionctl.commands import group as group_commands
from legionctl.commands import map_commands
from legionctl.commands import node as node_commands
from legionctl.commands import profile as profile_commands
from legionctl.commands import sentinel as sentinel_commands
from legionctl.commands import zone as zone_commands
from legionctl.commands.actions import reboot_cmd, scan_cmd, test_alert_cmd
from legionctl.commands.discover import discover_cmd
from legionctl.commands.status import events_cmd, health_cmd, status_cmd
from legionctl.context import AppContext
from legionctl.output.console import print_warning
from legionctl.redaction import setup_logging

app = typer.Typer(
    name="legionctl",
    help="Legion — Sentinel fleet command-and-control CLI.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(node_commands.app, name="node")
app.add_typer(group_commands.app, name="group")
app.add_typer(profile_commands.app, name="profile")
app.add_typer(credential_commands.app, name="credential")
app.add_typer(fleet_commands.app, name="fleet")
app.add_typer(zone_commands.app, name="zone")
app.add_typer(cohort_commands.app, name="cohort")
app.add_typer(map_commands.app, name="map")
app.add_typer(sentinel_commands.app, name="sentinel")
app.command("discover")(discover_cmd)
app.command("status")(status_cmd)
app.command("health")(health_cmd)
app.command("events")(events_cmd)
app.command("test-alert")(test_alert_cmd)
app.command("scan")(scan_cmd)
app.command("reboot")(reboot_cmd)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"legionctl {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Override request timeout in seconds."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable informational logging."),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging. Secrets are redacted."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show write actions without applying them."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip confirmation prompts."),
    ] = False,
    insecure_skip_tls_verify: Annotated[
        bool,
        typer.Option(
            "--insecure-skip-tls-verify",
            help="Development-only: skip TLS certificate verification for this command.",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """Legion management plane for autonomous Sentinel nodes."""
    del version
    setup_logging(verbose=verbose, debug=debug)
    if insecure_skip_tls_verify:
        print_warning(
            "WARNING: TLS certificate verification disabled for this command "
            "(--insecure-skip-tls-verify)."
        )
    ctx.obj = AppContext(
        json_output=json_output,
        timeout=timeout,
        verbose=verbose,
        debug=debug,
        dry_run=dry_run,
        yes=yes,
        insecure_skip_tls_verify=insecure_skip_tls_verify,
    )


def run() -> None:
    app()
