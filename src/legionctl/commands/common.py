from __future__ import annotations

from typing import Any, NoReturn

import typer

from legionctl.errors import LegionError
from legionctl.models.inventory import SentinelNode
from legionctl.output.console import print_error
from legionctl.services.audit import build_audit_record, write_audit_record
from legionctl.services.inventory import load_inventory, resolve_targets


def exit_cli(exc: LegionError) -> NoReturn:
    print_error(str(exc))
    raise typer.Exit(exc.exit_code) from exc


def resolve_cli_targets(
    *,
    node: str | None,
    group: str | None,
    all_nodes: bool,
    selector: str | None,
) -> list[SentinelNode]:
    return resolve_targets(
        load_inventory(),
        node=node,
        group=group,
        all_nodes=all_nodes,
        selector=selector,
    )


def audit_action(
    operation: str,
    *,
    targets: list[str],
    result: str,
    dry_run: bool = False,
    confirmed_with_yes: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    write_audit_record(
        build_audit_record(
            operation,
            targets=targets,
            result=result,
            dry_run=dry_run,
            confirmed_with_yes=confirmed_with_yes,
            details=details,
        )
    )
