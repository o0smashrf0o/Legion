from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from legionctl.models.discovery import DiscoveredService, DiscoveryIssue
from legionctl.models.fleet import FleetNodeEvents, FleetNodeHealth, FleetNodeStatus
from legionctl.models.inventory import Group, SentinelNode
from legionctl.models.profile import Profile

_stdout = Console(highlight=False)


def emit_json(payload: Any) -> None:
    _stdout.print(json.dumps(payload, indent=2, sort_keys=True))


def nodes_payload(nodes: list[SentinelNode]) -> dict[str, Any]:
    return {"nodes": [node.model_dump(mode="json") for node in nodes]}


def groups_payload(groups: list[Group]) -> dict[str, Any]:
    return {"groups": [group.model_dump(mode="json") for group in groups]}


def profile_valid_payload(profile: Profile) -> dict[str, Any]:
    return {
        "valid": True,
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "rules": len(profile.rules),
        "technologies": profile.technologies(),
    }


def profile_invalid_payload(errors: list[str]) -> dict[str, Any]:
    return {"valid": False, "errors": errors}


def node_payload(node: SentinelNode) -> dict[str, Any]:
    return node.model_dump(mode="json")


def discovered_payload(
    records: list[DiscoveredService],
    issues: list[DiscoveryIssue],
) -> dict[str, Any]:
    return {
        "discovered": [record.model_dump(mode="json") for record in records],
        "issues": [issue.model_dump(mode="json") for issue in issues],
    }


def status_payload(rows: list[FleetNodeStatus]) -> dict[str, Any]:
    return {"results": [row.model_dump(mode="json") for row in rows]}


def health_payload(rows: list[FleetNodeHealth]) -> dict[str, Any]:
    return {"results": [row.model_dump(mode="json") for row in rows]}


def events_payload(rows: list[FleetNodeEvents]) -> dict[str, Any]:
    return {"results": [row.model_dump(mode="json") for row in rows]}
