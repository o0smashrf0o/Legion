from __future__ import annotations

from pathlib import Path

import pytest

from legionctl.errors import InventoryError, NoTargetsError, TargetNotFoundError
from legionctl.models.inventory import SentinelNode
from legionctl.services import inventory as inventory_service
from legionctl.settings import LegionPaths
from legionctl.storage import atomic_write_text


def _node(sentinel_id: str, **kwargs: object) -> SentinelNode:
    payload = {
        "sentinel_id": sentinel_id,
        "display_name": sentinel_id,
        "zone": "North Door",
        "hostname": f"{sentinel_id}.local",
        "base_url": f"https://{sentinel_id}.local",
        "enabled": True,
    }
    payload.update(kwargs)
    return SentinelNode.model_validate(payload)


def test_crud_and_persistence(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01"))
    inventory_service.create_group("event-alpha", description="Event Alpha")
    inventory_service.add_group_member("event-alpha", "sentinel-north-door-01")

    loaded = inventory_service.load_inventory()
    assert loaded.node_by_id("sentinel-north-door-01") is not None
    group = loaded.group_by_name("event-alpha")
    assert group is not None
    assert group.members == ["sentinel-north-door-01"]

    updated = inventory_service.update_node(
        "sentinel-north-door-01",
        display_name="North Door",
        zone="North Door",
    )
    assert updated.display_name == "North Door"

    inventory_service.remove_group_member("event-alpha", "sentinel-north-door-01")
    inventory_service.remove_node("sentinel-north-door-01")
    empty = inventory_service.load_inventory()
    assert empty.nodes == []
    assert empty.groups[0].members == []


def test_duplicate_node_rejected(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01"))
    with pytest.raises(InventoryError, match="duplicate Sentinel ID"):
        inventory_service.add_node(_node("sentinel-north-door-01"))


def test_inconsistent_hostname_rejected(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01", hostname="door.local"))
    with pytest.raises(InventoryError, match="inconsistent hostname"):
        inventory_service.add_node(
            _node("sentinel-hall-b-01", hostname="door.local", zone="Hall B")
        )


def test_atomic_write_preserves_original_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.json"
    atomic_write_text(target, '{"ok": true}\n')
    original = target.read_text(encoding="utf-8")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(target, '{"ok": false}\n')
    assert target.read_text(encoding="utf-8") == original
    leftovers = list(tmp_path.glob(".inventory.json.*.tmp"))
    assert leftovers == []


def test_resolve_group_and_selector(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01", zone="North Door"))
    inventory_service.add_node(_node("sentinel-hall-b-01", zone="Hall B"))
    inventory_service.add_node(_node("sentinel-garage-01", zone="Garage", enabled=False))
    inventory_service.create_group("event-alpha")
    inventory_service.add_group_member("event-alpha", "sentinel-north-door-01")
    inventory_service.add_group_member("event-alpha", "sentinel-hall-b-01")

    inventory = inventory_service.load_inventory()
    group_targets = inventory_service.resolve_targets(inventory, group="event-alpha")
    assert {node.sentinel_id for node in group_targets} == {
        "sentinel-north-door-01",
        "sentinel-hall-b-01",
    }

    zone_targets = inventory_service.resolve_targets(inventory, selector="zone=North Door")
    assert [node.sentinel_id for node in zone_targets] == ["sentinel-north-door-01"]

    all_enabled = inventory_service.resolve_targets(inventory, all_nodes=True)
    assert {node.sentinel_id for node in all_enabled} == {
        "sentinel-north-door-01",
        "sentinel-hall-b-01",
    }


def test_resolve_zero_nodes_is_error(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01", zone="North Door"))
    inventory = inventory_service.load_inventory()
    with pytest.raises(NoTargetsError, match="zero"):
        inventory_service.resolve_targets(inventory, selector="zone=Nowhere")
    with pytest.raises(NoTargetsError, match="no target"):
        inventory_service.resolve_targets(inventory)
    with pytest.raises(TargetNotFoundError):
        inventory_service.resolve_targets(inventory, node="missing")


def test_inventory_does_not_store_tokens(legion_home: LegionPaths) -> None:
    inventory_service.add_node(_node("sentinel-north-door-01"))
    raw = legion_home.inventory_file.read_text(encoding="utf-8")
    assert "token" not in raw.lower()
    assert "bearer" not in raw.lower()
