from __future__ import annotations

from legionctl.errors import InventoryError, NoTargetsError, TargetNotFoundError
from legionctl.models.inventory import Group, Inventory, SentinelNode
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import atomic_write_json, read_json


def load_inventory(paths: LegionPaths | None = None) -> Inventory:
    resolved = paths or get_paths()
    payload = read_json(resolved.inventory_file)
    if payload is None:
        return Inventory()
    return Inventory.model_validate(payload)


def save_inventory(inventory: Inventory, paths: LegionPaths | None = None) -> None:
    resolved = paths or get_paths()
    atomic_write_json(resolved.inventory_file, inventory.model_dump(mode="json"))


def list_nodes(paths: LegionPaths | None = None) -> list[SentinelNode]:
    return list(load_inventory(paths).nodes)


def list_groups(paths: LegionPaths | None = None) -> list[Group]:
    return list(load_inventory(paths).groups)


def get_node(sentinel_id: str, paths: LegionPaths | None = None) -> SentinelNode:
    node = load_inventory(paths).node_by_id(sentinel_id)
    if node is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    return node


def identity_conflicts(
    inventory: Inventory,
    *,
    sentinel_id: str,
    hostname: str | None,
    ignore_existing_id: bool = False,
) -> list[str]:
    messages: list[str] = []
    existing = inventory.node_by_id(sentinel_id)
    if existing is not None and not ignore_existing_id:
        messages.append(f"duplicate Sentinel ID '{sentinel_id}'")
        if hostname and existing.hostname and existing.hostname != hostname:
            messages.append(
                f"inconsistent hostname for '{sentinel_id}': inventory has "
                f"'{existing.hostname}', new value is '{hostname}'"
            )
    if hostname:
        for node in inventory.nodes:
            if node.hostname == hostname and node.sentinel_id != sentinel_id:
                messages.append(
                    f"inconsistent hostname '{hostname}' already assigned to '{node.sentinel_id}'"
                )
    return messages


def add_node(node: SentinelNode, paths: LegionPaths | None = None) -> Inventory:
    inventory = load_inventory(paths)
    conflicts = identity_conflicts(
        inventory,
        sentinel_id=node.sentinel_id,
        hostname=node.hostname,
    )
    if conflicts:
        raise InventoryError("; ".join(conflicts))
    inventory.nodes.append(node)
    save_inventory(inventory, paths)
    return inventory


def remove_node(sentinel_id: str, paths: LegionPaths | None = None) -> Inventory:
    inventory = load_inventory(paths)
    if inventory.node_by_id(sentinel_id) is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    inventory.nodes = [node for node in inventory.nodes if node.sentinel_id != sentinel_id]
    for group in inventory.groups:
        group.members = [member for member in group.members if member != sentinel_id]
    save_inventory(inventory, paths)
    return inventory


def update_node(
    sentinel_id: str,
    *,
    display_name: str | None = None,
    zone: str | None = None,
    paths: LegionPaths | None = None,
) -> SentinelNode:
    inventory = load_inventory(paths)
    node = inventory.node_by_id(sentinel_id)
    if node is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    updates: dict[str, str] = {}
    if display_name is not None:
        updates["display_name"] = display_name
    if zone is not None:
        updates["zone"] = zone
    updated = node.model_copy(update=updates)
    inventory.nodes = [
        updated if item.sentinel_id == sentinel_id else item for item in inventory.nodes
    ]
    save_inventory(inventory, paths)
    return updated


def create_group(
    name: str,
    *,
    description: str = "",
    paths: LegionPaths | None = None,
) -> Group:
    inventory = load_inventory(paths)
    if inventory.group_by_name(name) is not None:
        raise InventoryError(f"group '{name}' already exists")
    group = Group(group=name, description=description, members=[])
    inventory.groups.append(group)
    save_inventory(inventory, paths)
    return group


def add_group_member(
    group_name: str,
    sentinel_id: str,
    paths: LegionPaths | None = None,
) -> Group:
    inventory = load_inventory(paths)
    group = inventory.group_by_name(group_name)
    if group is None:
        raise TargetNotFoundError(f"group '{group_name}' is not in inventory")
    node = inventory.node_by_id(sentinel_id)
    if node is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    if sentinel_id not in group.members:
        group.members.append(sentinel_id)
    if group_name not in node.groups:
        node.groups.append(group_name)
    save_inventory(inventory, paths)
    return group


def remove_group_member(
    group_name: str,
    sentinel_id: str,
    paths: LegionPaths | None = None,
) -> Group:
    inventory = load_inventory(paths)
    group = inventory.group_by_name(group_name)
    if group is None:
        raise TargetNotFoundError(f"group '{group_name}' is not in inventory")
    group.members = [member for member in group.members if member != sentinel_id]
    node = inventory.node_by_id(sentinel_id)
    if node is not None:
        node.groups = [item for item in node.groups if item != group_name]
    save_inventory(inventory, paths)
    return group


def parse_selector(selector: str) -> tuple[str, str]:
    if "=" not in selector:
        raise InventoryError("selector must be key=value, for example zone=North Door")
    key, value = selector.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise InventoryError("selector must be key=value, for example zone=North Door")
    if key != "zone":
        raise InventoryError(f"unsupported selector '{key}'")
    return key, value


def resolve_targets(
    inventory: Inventory,
    *,
    node: str | None = None,
    group: str | None = None,
    all_nodes: bool = False,
    selector: str | None = None,
    include_disabled: bool = False,
) -> list[SentinelNode]:
    specified = [item for item in (node, group, selector) if item]
    if all_nodes:
        specified.append("all")
    if not specified:
        raise NoTargetsError("no target specified; use --node, --group, --all, or --selector")
    if all_nodes and (node or group or selector):
        raise InventoryError("--all cannot be combined with --node, --group, or --selector")

    selected: dict[str, SentinelNode] = {}

    def consider(candidate: SentinelNode) -> None:
        if not include_disabled and not candidate.enabled and node is None:
            return
        selected[candidate.sentinel_id] = candidate

    if all_nodes:
        for candidate in inventory.nodes:
            consider(candidate)
    if node:
        found = inventory.node_by_id(node)
        if found is None:
            raise TargetNotFoundError(f"Sentinel node '{node}' is not in inventory")
        selected[found.sentinel_id] = found
    if group:
        found_group = inventory.group_by_name(group)
        if found_group is None:
            raise TargetNotFoundError(f"group '{group}' is not in inventory")
        for member_id in found_group.members:
            member = inventory.node_by_id(member_id)
            if member is None:
                raise TargetNotFoundError(
                    f"group '{group}' member '{member_id}' is not in inventory"
                )
            consider(member)
    if selector:
        _key, value = parse_selector(selector)
        for candidate in inventory.nodes:
            if candidate.zone == value:
                consider(candidate)

    if not selected:
        raise NoTargetsError("selector resolved to zero Sentinel nodes")
    return list(selected.values())
