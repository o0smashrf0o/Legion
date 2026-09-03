from __future__ import annotations

from collections.abc import Callable

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from legionctl.errors import ConfirmationDeclined
from legionctl.models.inventory import Group, SentinelNode
from legionctl.models.profile import Profile

console = Console(highlight=False, soft_wrap=True)
err_console = Console(stderr=True, highlight=False, soft_wrap=True)


def safe(value: str | None) -> str:
    if value is None or value == "":
        return "--"
    return escape(value)


def print_error(message: str) -> None:
    err_console.print(f"[red]{escape(message)}[/red]")


def print_warning(message: str) -> None:
    err_console.print(f"[yellow]{escape(message)}[/yellow]")


def confirm_or_decline(
    prompt: str,
    *,
    yes: bool,
    ask: Callable[[str], bool] | None = None,
) -> None:
    if yes:
        return
    confirmer = ask or (
        lambda text: console.input(f"{text} [y/N]: ").strip().lower() in {"y", "yes"}
    )
    if not confirmer(prompt):
        raise ConfirmationDeclined("confirmation declined")


def _table(title: str, headers: list[str]) -> Table:
    table = Table(title=title)
    for header in headers:
        table.add_column(header, overflow="fold", no_wrap=False)
    return table


def render_nodes_table(nodes: list[SentinelNode]) -> Table:
    table = _table(
        "Sentinel inventory",
        ["ID", "Display name", "Zone", "Hostname", "URL", "Groups", "Enabled"],
    )
    for node in nodes:
        table.add_row(
            safe(node.sentinel_id),
            safe(node.display_name),
            safe(node.zone),
            safe(node.hostname),
            safe(node.base_url),
            safe(", ".join(node.groups)),
            "yes" if node.enabled else "no",
        )
    return table


def render_groups_table(groups: list[Group]) -> Table:
    table = _table("Sentinel groups", ["Group", "Description", "Members", "Count"])
    for group in groups:
        table.add_row(
            safe(group.group),
            safe(group.description),
            safe(", ".join(group.members)),
            str(len(group.members)),
        )
    return table


def render_profile_valid(profile: Profile) -> str:
    technologies = ", ".join(profile.technologies()) or "none"
    return (
        f"Profile {profile.profile_id} revision {profile.revision} is valid.\n"
        f"Rules: {len(profile.rules)}\n"
        f"Technologies: {technologies}"
    )
