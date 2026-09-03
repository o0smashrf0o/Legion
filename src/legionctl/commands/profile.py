from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from legionctl.context import get_app_context
from legionctl.errors import LegionError, ValidationFailed
from legionctl.output.console import console, print_error, render_profile_valid
from legionctl.output.json import emit_json, profile_invalid_payload, profile_valid_payload
from legionctl.services.profiles import validate_profile_file

app = typer.Typer(help="Create, validate, and manage SOI profiles.")


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
        print_error(str(exc))
        raise typer.Exit(exc.exit_code) from exc
    if app_ctx.json_output:
        emit_json(profile_valid_payload(profile))
        return
    console.print(render_profile_valid(profile))
