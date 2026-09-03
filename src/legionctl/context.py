from __future__ import annotations

from dataclasses import dataclass

import typer


@dataclass
class AppContext:
    json_output: bool = False
    timeout: float | None = None
    verbose: bool = False
    debug: bool = False
    dry_run: bool = False
    insecure_skip_tls_verify: bool = False


def get_app_context(ctx: typer.Context) -> AppContext:
    root = ctx.find_root()
    obj = root.obj
    if isinstance(obj, AppContext):
        return obj
    return AppContext()
