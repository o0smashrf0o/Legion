from __future__ import annotations

from collections.abc import Callable

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from legionctl.errors import ConfirmationDeclined
from legionctl.models.discovery import DiscoveredService, DiscoveryIssue
from legionctl.models.fleet import FleetNodeEvents, FleetNodeHealth, FleetNodeStatus
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


def render_node_detail(node: SentinelNode) -> str:
    return "\n".join(
        [
            f"ID: {safe(node.sentinel_id)}",
            f"Display name: {safe(node.display_name)}",
            f"Zone: {safe(node.zone)}",
            f"Hostname: {safe(node.hostname)}",
            f"URL: {safe(node.base_url)}",
            f"IP: {safe(node.last_known_ip)}",
            f"Firmware: {safe(node.firmware_version)}",
            f"API: {safe(node.api_version)}",
            f"Groups: {safe(', '.join(node.groups) if node.groups else None)}",
            f"Enabled: {'yes' if node.enabled else 'no'}",
        ]
    )


def render_discovery_table(records: list[DiscoveredService]) -> Table:
    table = _table(
        "Discovered Sentinel nodes",
        ["ID", "Zone", "Hostname", "IP", "Firmware", "Profile", "Reachable", "Known"],
    )
    for item in records:
        profile = "--"
        if item.profile_id:
            revision = f" r{item.profile_revision}" if item.profile_revision is not None else ""
            profile = f"{item.profile_id}{revision}"
        reachable = "--"
        if item.reachable is True:
            reachable = "yes"
        elif item.reachable is False:
            reachable = "no"
        table.add_row(
            safe(item.sentinel_id),
            safe(item.zone),
            safe(item.hostname),
            safe(item.ip),
            safe(item.firmware_version),
            safe(profile if profile != "--" else None),
            reachable,
            "yes" if item.known else "no",
        )
    return table


def render_discovery_issues(issues: list[DiscoveryIssue]) -> None:
    for issue in issues:
        print_warning(issue.message)


def _format_band(band: str | None) -> str | None:
    if not band:
        return None
    mapping = {"5ghz": "5 GHz", "2.4ghz": "2.4 GHz", "6ghz": "6 GHz"}
    return mapping.get(band.lower(), band)


def format_battery(row: FleetNodeStatus) -> str:
    if row.battery_percent is None:
        return "--"
    return f"{row.battery_percent}%"


def format_wifi(row: FleetNodeStatus) -> str:
    if not row.reachable:
        return "unreachable"
    if row.wifi_connected is None:
        return "--"
    if not row.wifi_connected:
        return "disconnected"
    band = _format_band(row.wifi_band)
    if band and row.wifi_rssi_dbm is not None:
        return f"{band} / {row.wifi_rssi_dbm} dBm"
    if band:
        return band
    if row.wifi_rssi_dbm is not None:
        return f"{row.wifi_rssi_dbm} dBm"
    return "connected"


def format_scanners(row: FleetNodeStatus) -> str:
    if not row.reachable:
        return "unknown"
    states = [value for value in (row.scanner_wifi, row.scanner_ble) if value]
    if not states:
        return "--"
    if all(state == "running" for state in states):
        return "running"
    return ",".join(states)


def format_coprocessor(row: FleetNodeStatus) -> str:
    if not row.reachable:
        return "unknown"
    return safe(row.bt_classic_coprocessor)


def format_queue(row: FleetNodeStatus) -> str:
    if row.alert_queue_depth is None:
        return "--"
    return str(row.alert_queue_depth)


def format_profile(row: FleetNodeStatus) -> str:
    if not row.reachable:
        return "unknown"
    if not row.profile_id:
        return "--"
    if row.profile_revision is None:
        return safe(row.profile_id)
    return escape(f"{row.profile_id} r{row.profile_revision}")


def render_status_table(rows: list[FleetNodeStatus]) -> Table:
    table = _table(
        "Sentinel status",
        [
            "Sentinel",
            "Zone",
            "Battery",
            "Wi-Fi",
            "Scanners",
            "BT coprocessor",
            "Queue",
            "Profile",
            "Seen",
        ],
    )
    for row in rows:
        table.add_row(
            safe(row.sentinel_id),
            safe(row.zone),
            format_battery(row),
            format_wifi(row),
            format_scanners(row),
            format_coprocessor(row),
            format_queue(row),
            format_profile(row),
            safe(row.timestamp_utc),
        )
    return table


def render_health_table(rows: list[FleetNodeHealth]) -> Table:
    table = _table(
        "Sentinel health",
        [
            "Sentinel",
            "Zone",
            "Battery",
            "Wi-Fi",
            "Scanners",
            "BT coprocessor",
            "Queue",
            "Heap",
            "Seen",
        ],
    )
    for row in rows:
        heap = "--" if row.free_heap_bytes is None else str(row.free_heap_bytes)
        table.add_row(
            safe(row.sentinel_id),
            safe(row.zone),
            format_battery(row),
            format_wifi(row),
            format_scanners(row),
            format_coprocessor(row),
            format_queue(row),
            heap,
            safe(row.timestamp_utc),
        )
    return table


def render_events_table(rows: list[FleetNodeEvents]) -> Table:
    table = _table(
        "Recent Sentinel events",
        ["Sentinel", "Timestamp", "Type", "SOI", "Technology", "RSSI", "Delivery"],
    )
    for row in rows:
        if not row.ok:
            table.add_row(
                safe(row.sentinel_id),
                "--",
                "unreachable" if row.error_kind == "unreachable" else "error",
                "--",
                "--",
                "--",
                safe(row.error),
            )
            continue
        if not row.events:
            table.add_row(safe(row.sentinel_id), "--", "--", "--", "--", "--", "--")
            continue
        for event in row.events:
            rssi = event.get("rssi_dbm")
            table.add_row(
                safe(row.sentinel_id),
                safe(str(event.get("timestamp_utc") or "")),
                safe(str(event.get("event_type") or "")),
                safe(str(event.get("soi_id") or "")),
                safe(str(event.get("technology") or "")),
                "--" if rssi is None else str(rssi),
                safe(str(event.get("discord_delivery") or "")),
            )
    return table


def render_profile_valid(profile: Profile) -> str:
    technologies = ", ".join(profile.technologies()) or "none"
    return (
        f"Profile {profile.profile_id} revision {profile.revision} is valid.\n"
        f"Rules: {len(profile.rules)}\n"
        f"Technologies: {technologies}"
    )
