from __future__ import annotations

import ipaddress
from typing import Annotated
from urllib.parse import urlparse

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError, UsageError
from legionctl.models.inventory import SentinelNode
from legionctl.output.console import (
    confirm_or_decline,
    console,
    render_node_detail,
    render_nodes_table,
)
from legionctl.output.json import emit_json, node_payload, nodes_payload
from legionctl.services.credentials import CredentialStore, read_bearer_token
from legionctl.services.inventory import (
    add_node,
    get_node,
    list_nodes,
    remove_node,
    update_node,
)

app = typer.Typer(help="Manage Sentinel node inventory.")


def _node_from_add_options(
    sentinel_id: str,
    url: str,
    *,
    hostname: str | None,
    zone: str | None,
    display_name: str | None,
) -> SentinelNode:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise UsageError("--url must be an https URL")
    host = hostname or parsed.hostname
    last_known_ip: str | None = None
    if parsed.hostname:
        try:
            ipaddress.ip_address(parsed.hostname)
            last_known_ip = parsed.hostname
        except ValueError:
            last_known_ip = None
    return SentinelNode(
        sentinel_id=sentinel_id,
        display_name=display_name,
        zone=zone,
        hostname=host,
        base_url=url.rstrip("/"),
        last_known_ip=last_known_ip,
    )


@app.command("list")
def node_list(ctx: typer.Context) -> None:
    """List Sentinel nodes in the local inventory."""
    app_ctx = get_app_context(ctx)
    try:
        nodes = list_nodes()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(nodes_payload(nodes))
        return
    if not nodes:
        console.print("No Sentinel nodes in inventory.")
        return
    console.print(render_nodes_table(nodes))


@app.command("show")
def node_show(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
) -> None:
    """Show one Sentinel node from the local inventory."""
    app_ctx = get_app_context(ctx)
    try:
        node = get_node(sentinel_id)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(node_payload(node))
        return
    console.print(render_node_detail(node))


@app.command("add")
def node_add(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Option("--id", help="Sentinel node ID.")],
    url: Annotated[str, typer.Option("--url", help="Base HTTPS URL for the node.")],
    token_stdin: Annotated[
        bool,
        typer.Option("--token-stdin", help="Read the bearer token from stdin."),
    ] = False,
    from_keyring: Annotated[
        bool,
        typer.Option("--from-keyring", help="Use a bearer token already in the keyring."),
    ] = False,
    hostname: Annotated[str | None, typer.Option("--hostname")] = None,
    zone: Annotated[str | None, typer.Option("--zone")] = None,
    display_name: Annotated[str | None, typer.Option("--display-name")] = None,
) -> None:
    """Add a Sentinel node to the local inventory."""
    app_ctx = get_app_context(ctx)
    credentials = CredentialStore()
    try:
        node = _node_from_add_options(
            sentinel_id,
            url,
            hostname=hostname,
            zone=zone,
            display_name=display_name,
        )
        if app_ctx.dry_run:
            audit_action(
                "node_add",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
            )
            console.print(f"Would add {sentinel_id} to inventory.")
            return
        token = read_bearer_token(
            sentinel_id,
            token_stdin=token_stdin,
            from_keyring=from_keyring,
            credentials=credentials,
        )
        if not from_keyring:
            credentials.set_token(sentinel_id, token)
        add_node(node)
    except LegionError as exc:
        exit_cli(exc)
    audit_action("node_add", targets=[sentinel_id], result="success", dry_run=False)
    console.print(f"Added {sentinel_id} to inventory and stored token in system keyring.")


@app.command("remove")
def node_remove(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Remove a Sentinel node from the local inventory."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    try:
        get_node(sentinel_id)
        if app_ctx.dry_run:
            audit_action(
                "node_remove",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
                confirmed_with_yes=confirmed,
            )
            console.print(f"Would remove {sentinel_id} from inventory.")
            return
        confirm_or_decline(f"Remove Sentinel node {sentinel_id} from inventory?", yes=confirmed)
        remove_node(sentinel_id)
        CredentialStore().delete_token(sentinel_id)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "node_remove",
        targets=[sentinel_id],
        result="success",
        confirmed_with_yes=confirmed,
    )
    console.print(f"Removed {sentinel_id} from inventory.")


@app.command("rename")
def node_rename(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
    display_name: Annotated[str | None, typer.Option("--display-name")] = None,
    zone: Annotated[str | None, typer.Option("--zone")] = None,
) -> None:
    """Update a Sentinel node's display name and/or zone."""
    app_ctx = get_app_context(ctx)
    if display_name is None and zone is None:
        exit_cli(UsageError("provide --display-name and/or --zone"))
    try:
        if app_ctx.dry_run:
            audit_action(
                "node_rename",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
                details={"display_name": display_name, "zone": zone},
            )
            console.print(f"Would rename {sentinel_id}.")
            return
        updated = update_node(sentinel_id, display_name=display_name, zone=zone)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "node_rename",
        targets=[sentinel_id],
        result="success",
        details={"display_name": updated.display_name, "zone": updated.zone},
    )
    console.print(f"Updated {sentinel_id}.")
