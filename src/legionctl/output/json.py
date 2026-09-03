from __future__ import annotations

import json
from typing import Any

from rich.console import Console

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
