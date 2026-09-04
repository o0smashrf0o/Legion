from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import ConfirmationDeclined, LegionError
from legionctl.output.console import confirm_or_decline, console
from legionctl.output.json import emit_json
from legionctl.services.actions import check_node_credential
from legionctl.services.credentials import CredentialStore, read_bearer_token
from legionctl.services.inventory import get_node
from legionctl.settings import load_settings

app = typer.Typer(help="Manage per-node Sentinel API credentials.")


@app.command("set")
def credential_set(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
    token_stdin: Annotated[
        bool,
        typer.Option("--token-stdin", help="Read the bearer token from stdin."),
    ] = False,
) -> None:
    """Store a Sentinel bearer token. The token is never accepted as a flag."""
    app_ctx = get_app_context(ctx)
    credentials = CredentialStore()
    try:
        if app_ctx.dry_run:
            console.print(f"Would store a bearer token for {sentinel_id}.")
            audit_action(
                "credential_set",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
            )
            return
        token = read_bearer_token(sentinel_id, token_stdin=token_stdin, credentials=credentials)
        credentials.set_token(sentinel_id, token)
    except LegionError as exc:
        exit_cli(exc)
    audit_action("credential_set", targets=[sentinel_id], result="success")
    console.print(f"Stored token for {sentinel_id} in system keyring.")


@app.command("check")
def credential_check(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
) -> None:
    """Verify the stored token with an authenticated GET /api/v1/info."""
    app_ctx = get_app_context(ctx)
    try:
        node = get_node(sentinel_id)
        identity = asyncio.run(
            check_node_credential(
                node,
                CredentialStore(),
                app_ctx=app_ctx,
                settings=load_settings(),
            )
        )
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json({"ok": True, "sentinel_id": identity})
        return
    console.print(f"Credential for {identity} is valid.")


@app.command("delete")
def credential_delete(
    ctx: typer.Context,
    sentinel_id: Annotated[str, typer.Argument(help="Sentinel node ID.")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Delete the stored bearer token for a Sentinel node."""
    app_ctx = get_app_context(ctx)
    confirmed = yes or app_ctx.yes
    credentials = CredentialStore()
    try:
        if app_ctx.dry_run:
            console.print(f"Would delete the stored token for {sentinel_id}.")
            audit_action(
                "credential_delete",
                targets=[sentinel_id],
                result="success",
                dry_run=True,
                confirmed_with_yes=confirmed,
            )
            return
        confirm_or_decline(
            f"Delete stored bearer token for {sentinel_id}?",
            yes=confirmed,
        )
        credentials.delete_token(sentinel_id)
    except ConfirmationDeclined as exc:
        exit_cli(exc)
    except LegionError as exc:
        exit_cli(exc)
    audit_action(
        "credential_delete",
        targets=[sentinel_id],
        result="success",
        confirmed_with_yes=confirmed,
    )
    console.print(f"Deleted stored token for {sentinel_id}.")
