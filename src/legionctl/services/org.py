from __future__ import annotations

from typing import Any

from legionctl.constants import NOMINAL_COHORT_SIZE
from legionctl.errors import InventoryError, TargetNotFoundError, UsageError
from legionctl.models.fleet import FleetNodeStatus
from legionctl.models.inventory import Inventory, SentinelNode
from legionctl.models.org import (
    Cohort,
    CohortReadiness,
    SentinelPresence,
    Zone,
    ZoneCoverage,
)
from legionctl.services.audit import utc_now
from legionctl.services.inventory import load_inventory, save_inventory
from legionctl.settings import LegionPaths


def list_zones(paths: LegionPaths | None = None) -> list[Zone]:
    return list(load_inventory(paths).zones)


def list_cohorts(paths: LegionPaths | None = None) -> list[Cohort]:
    return list(load_inventory(paths).cohorts)


def get_zone(zone_id: str, paths: LegionPaths | None = None) -> Zone:
    zone = load_inventory(paths).zone_by_id(zone_id)
    if zone is None:
        raise TargetNotFoundError(f"zone '{zone_id}' is not in inventory")
    return zone


def get_cohort(cohort_id: str, paths: LegionPaths | None = None) -> Cohort:
    cohort = load_inventory(paths).cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    return cohort


def _safe_id(value: str, kind: str) -> str:
    text = value.strip()
    if not text or any(part in text for part in ("/", "\\", "..")):
        raise UsageError(f"invalid {kind}")
    return text


def _slug(value: str, prefix: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return cleaned or prefix


def sentinel_presence(
    node: SentinelNode | None, health: FleetNodeStatus | None
) -> SentinelPresence:
    if node is None:
        return "unknown"
    if not node.enabled:
        return "dormant"
    if health is None:
        return "unknown"
    if not health.reachable:
        return "offline"
    if not health.ok or health.wifi_connected is False:
        return "degraded"
    return "online"


def active_members(cohort: Cohort, inventory: Inventory) -> list[str]:
    members: list[str] = []
    for sentinel_id in cohort.sentinel_ids:
        node = inventory.node_by_id(sentinel_id)
        if node is not None and node.enabled:
            members.append(sentinel_id)
    return members


def cohort_readiness(
    cohort: Cohort,
    inventory: Inventory,
    health_by_id: dict[str, FleetNodeStatus] | None = None,
) -> tuple[CohortReadiness, list[str], int]:
    flags: list[str] = []
    roster = len(active_members(cohort, inventory))
    if cohort.status != "active":
        return "inactive", ["inactive"], roster
    if not cohort.zone_id or inventory.zone_by_id(cohort.zone_id) is None:
        flags.append("unassigned")
    if not cohort.primus_sentinel_id:
        flags.append("no_primus")
    elif cohort.primus_sentinel_id not in cohort.sentinel_ids:
        flags.append("no_primus")
    primus_state: SentinelPresence = "unknown"
    if cohort.primus_sentinel_id:
        primus_node = inventory.node_by_id(cohort.primus_sentinel_id)
        primus_health = (
            None if health_by_id is None else health_by_id.get(cohort.primus_sentinel_id)
        )
        primus_state = sentinel_presence(primus_node, primus_health)
        if primus_state in {"offline", "degraded", "dormant"}:
            flags.append("primus_unhealthy")
    if "unassigned" in flags:
        primary: CohortReadiness = "unassigned"
    elif "primus_unhealthy" in flags:
        primary = "degraded"
    elif roster < NOMINAL_COHORT_SIZE:
        primary = "understrength"
    elif roster > NOMINAL_COHORT_SIZE:
        primary = "reinforced"
    elif "no_primus" in flags:
        primary = "degraded"
    else:
        primary = "nominal"
        if primus_state not in {"online", "unknown"}:
            primary = "degraded"
    if roster < NOMINAL_COHORT_SIZE and "understrength" not in flags:
        flags.append("understrength")
    if roster > NOMINAL_COHORT_SIZE:
        flags.append("reinforced")
    if roster == NOMINAL_COHORT_SIZE:
        flags.append("nominal_size")
    return primary, flags, roster


def zone_coverage(
    zone: Zone,
    inventory: Inventory,
    health_by_id: dict[str, FleetNodeStatus] | None = None,
) -> ZoneCoverage:
    if zone.status != "active":
        return "inactive"
    assigned = [
        cohort
        for cohort in inventory.cohorts
        if cohort.status == "active" and cohort.zone_id == zone.zone_id
    ]
    if not assigned:
        return "unstaffed"
    snapshots = [cohort_readiness(cohort, inventory, health_by_id) for cohort in assigned]
    if any(state == "degraded" or "primus_unhealthy" in flags for state, flags, _n in snapshots):
        return "degraded"
    if any(state in {"nominal", "reinforced"} for state, _flags, _n in snapshots):
        return "covered"
    return "partial"


def _audit_save(
    inventory: Inventory,
    *,
    paths: LegionPaths | None,
    dry_run: bool,
) -> None:
    if not dry_run:
        save_inventory(inventory, paths)


def create_zone(
    *,
    name: str,
    zone_id: str | None = None,
    description: str = "",
    zone_type: str = "physical",
    metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Zone:
    inventory = load_inventory(paths)
    ident = _safe_id(zone_id or _slug(name, "zone"), "zone_id")
    if inventory.zone_by_id(ident) is not None:
        raise InventoryError(f"zone '{ident}' already exists")
    if zone_type not in {"physical", "logical", "mission"}:
        raise UsageError("zone_type must be physical, logical, or mission")
    now = utc_now()
    zone = Zone(
        zone_id=ident,
        name=name.strip(),
        description=description,
        zone_type=zone_type,  # type: ignore[arg-type]
        status="active",
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )
    inventory.zones.append(zone)
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return zone


def update_zone(
    zone_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    zone_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Zone:
    inventory = load_inventory(paths)
    zone = inventory.zone_by_id(zone_id)
    if zone is None:
        raise TargetNotFoundError(f"zone '{zone_id}' is not in inventory")
    updates: dict[str, Any] = {"updated_at": utc_now()}
    if name is not None:
        updates["name"] = name.strip()
    if description is not None:
        updates["description"] = description
    if zone_type is not None:
        if zone_type not in {"physical", "logical", "mission"}:
            raise UsageError("zone_type must be physical, logical, or mission")
        updates["zone_type"] = zone_type
    if metadata is not None:
        updates["metadata"] = metadata
    updated = zone.model_copy(update=updates)
    inventory.zones = [updated if item.zone_id == zone_id else item for item in inventory.zones]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def archive_zone(
    zone_id: str,
    *,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Zone:
    inventory = load_inventory(paths)
    zone = inventory.zone_by_id(zone_id)
    if zone is None:
        raise TargetNotFoundError(f"zone '{zone_id}' is not in inventory")
    updated = zone.model_copy(update={"status": "inactive", "updated_at": utc_now()})
    inventory.zones = [updated if item.zone_id == zone_id else item for item in inventory.zones]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def create_cohort(
    *,
    display_name: str,
    cohort_id: str | None = None,
    description: str = "",
    zone_id: str | None = None,
    mission_metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    ident = _safe_id(cohort_id or _slug(display_name, "cohort"), "cohort_id")
    if inventory.cohort_by_id(ident) is not None:
        raise InventoryError(f"cohort '{ident}' already exists")
    if zone_id:
        zone = inventory.zone_by_id(zone_id)
        if zone is None:
            raise TargetNotFoundError(f"zone '{zone_id}' is not in inventory")
    now = utc_now()
    cohort = Cohort(
        cohort_id=ident,
        display_name=display_name.strip(),
        description=description,
        zone_id=zone_id,
        status="active",
        sentinel_ids=[],
        primus_sentinel_id=None,
        mission_metadata=mission_metadata or {},
        created_at=now,
        updated_at=now,
    )
    inventory.cohorts.append(cohort)
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return cohort


def update_cohort(
    cohort_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    mission_metadata: dict[str, Any] | None = None,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    updates: dict[str, Any] = {"updated_at": utc_now()}
    if display_name is not None:
        updates["display_name"] = display_name.strip()
    if description is not None:
        updates["description"] = description
    if mission_metadata is not None:
        updates["mission_metadata"] = mission_metadata
    updated = cohort.model_copy(update=updates)
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def deactivate_cohort(
    cohort_id: str,
    *,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    updated = cohort.model_copy(update={"status": "inactive", "updated_at": utc_now()})
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def assign_cohort_zone(
    cohort_id: str,
    zone_id: str | None,
    *,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    if zone_id:
        zone = inventory.zone_by_id(zone_id)
        if zone is None:
            raise TargetNotFoundError(f"zone '{zone_id}' is not in inventory")
        if zone.status != "active":
            raise UsageError(f"zone '{zone_id}' is inactive")
    updated = cohort.model_copy(update={"zone_id": zone_id, "updated_at": utc_now()})
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def add_sentinel_to_cohort(
    cohort_id: str,
    sentinel_id: str,
    *,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    if cohort.status != "active":
        raise UsageError(f"cohort '{cohort_id}' is inactive")
    if inventory.node_by_id(sentinel_id) is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    current = inventory.cohort_for_sentinel(sentinel_id)
    if current is not None and current.cohort_id != cohort_id:
        raise UsageError(
            f"Sentinel '{sentinel_id}' already belongs to active cohort '{current.cohort_id}'"
        )
    members = list(cohort.sentinel_ids)
    if sentinel_id not in members:
        members.append(sentinel_id)
    primus = cohort.primus_sentinel_id or (sentinel_id if len(members) == 1 else None)
    updated = cohort.model_copy(
        update={"sentinel_ids": members, "primus_sentinel_id": primus, "updated_at": utc_now()}
    )
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def remove_sentinel_from_cohort(
    cohort_id: str,
    sentinel_id: str,
    *,
    new_primus: str | None = None,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    if sentinel_id not in cohort.sentinel_ids:
        raise UsageError(f"Sentinel '{sentinel_id}' is not in cohort '{cohort_id}'")
    members = [item for item in cohort.sentinel_ids if item != sentinel_id]
    primus = cohort.primus_sentinel_id
    if primus == sentinel_id:
        if members:
            if not new_primus:
                raise UsageError("select a new Primus before removing the current Primus")
            if new_primus not in members:
                raise UsageError("new Primus must remain a cohort member")
            primus = new_primus
        else:
            primus = None
    updated = cohort.model_copy(
        update={"sentinel_ids": members, "primus_sentinel_id": primus, "updated_at": utc_now()}
    )
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def set_primus(
    cohort_id: str,
    sentinel_id: str | None,
    *,
    dry_run: bool = False,
    paths: LegionPaths | None = None,
) -> Cohort:
    inventory = load_inventory(paths)
    cohort = inventory.cohort_by_id(cohort_id)
    if cohort is None:
        raise TargetNotFoundError(f"cohort '{cohort_id}' is not in inventory")
    if sentinel_id is None:
        if cohort.sentinel_ids and cohort.status == "active":
            raise UsageError("assign a replacement Primus or deactivate the Cohort")
    elif sentinel_id not in cohort.sentinel_ids:
        raise UsageError("Primus must be a member of the Cohort")
    updated = cohort.model_copy(
        update={"primus_sentinel_id": sentinel_id, "updated_at": utc_now()}
    )
    inventory.cohorts = [
        updated if item.cohort_id == cohort_id else item for item in inventory.cohorts
    ]
    _audit_save(inventory, paths=paths, dry_run=dry_run)
    return updated


def fleet_overview(
    health_rows: list[FleetNodeStatus] | None = None,
    paths: LegionPaths | None = None,
) -> dict[str, Any]:
    inventory = load_inventory(paths)
    health_by_id = {row.sentinel_id: row for row in health_rows} if health_rows else None
    presence_counts = {"online": 0, "degraded": 0, "offline": 0, "dormant": 0, "unknown": 0}
    sentinel_views: list[dict[str, Any]] = []
    for node in inventory.nodes:
        health = None if health_by_id is None else health_by_id.get(node.sentinel_id)
        presence = sentinel_presence(node, health)
        presence_counts[presence] = presence_counts.get(presence, 0) + 1
        cohort = inventory.cohort_for_sentinel(node.sentinel_id)
        zone = inventory.zone_by_id(cohort.zone_id) if cohort and cohort.zone_id else None
        sentinel_views.append(
            {
                "sentinel_id": node.sentinel_id,
                "display_name": node.display_name,
                "enabled": node.enabled,
                "presence": presence,
                "zone_id": None if zone is None else zone.zone_id,
                "zone_name": None if zone is None else zone.name,
                "cohort_id": None if cohort is None else cohort.cohort_id,
                "cohort_name": None if cohort is None else cohort.display_name,
                "role": "Primus"
                if cohort is not None and cohort.primus_sentinel_id == node.sentinel_id
                else "Sentinel",
                "profile_id": None if health is None else health.profile_id,
                "profile_revision": None if health is None else health.profile_revision,
                "capabilities": node.capabilities,
                "health": None if health is None else health.model_dump(mode="json"),
            }
        )
    cohort_views: list[dict[str, Any]] = []
    readiness_counts: dict[str, int] = {}
    extra_flags = {"no_primus": 0, "primus_unhealthy": 0, "unassigned": 0}
    for cohort in inventory.cohorts:
        readiness, flags, roster = cohort_readiness(cohort, inventory, health_by_id)
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
        for flag in extra_flags:
            if flag in flags:
                extra_flags[flag] += 1
        zone = inventory.zone_by_id(cohort.zone_id) if cohort.zone_id else None
        cohort_views.append(
            {
                **cohort.model_dump(mode="json"),
                "readiness": readiness,
                "flags": flags,
                "roster": roster,
                "roster_label": f"{roster}/5",
                "zone_name": None if zone is None else zone.name,
            }
        )
    zone_views: list[dict[str, Any]] = []
    for zone in inventory.zones:
        coverage = zone_coverage(zone, inventory, health_by_id)
        assigned = [
            cohort.cohort_id
            for cohort in inventory.cohorts
            if cohort.zone_id == zone.zone_id and cohort.status == "active"
        ]
        zone_views.append(
            {
                **zone.model_dump(mode="json"),
                "coverage": coverage,
                "cohort_ids": assigned,
            }
        )
    unassigned_sentinels = [
        node.sentinel_id
        for node in inventory.nodes
        if inventory.cohort_for_sentinel(node.sentinel_id) is None
    ]
    return {
        "sentinels_total": len(inventory.nodes),
        "presence": presence_counts,
        "zones_total": len(inventory.zones),
        "cohorts_total": len(inventory.cohorts),
        "cohort_readiness": readiness_counts,
        "cohort_flags": extra_flags,
        "zones": zone_views,
        "cohorts": cohort_views,
        "sentinels": sentinel_views,
        "unassigned_sentinels": unassigned_sentinels,
        "groups_note": "Groups are ad hoc CLI labels; Cohorts are operational units.",
    }


def assignment_for(sentinel_id: str, paths: LegionPaths | None = None) -> dict[str, Any]:
    inventory = load_inventory(paths)
    node = inventory.node_by_id(sentinel_id)
    if node is None:
        raise TargetNotFoundError(f"Sentinel node '{sentinel_id}' is not in inventory")
    cohort = inventory.cohort_for_sentinel(sentinel_id)
    zone = inventory.zone_by_id(cohort.zone_id) if cohort and cohort.zone_id else None
    return {
        "sentinel_id": sentinel_id,
        "display_name": node.display_name,
        "enabled": node.enabled,
        "cohort_id": None if cohort is None else cohort.cohort_id,
        "cohort_name": None if cohort is None else cohort.display_name,
        "zone_id": None if zone is None else zone.zone_id,
        "zone_name": None if zone is None else zone.name,
        "role": "Primus"
        if cohort is not None and cohort.primus_sentinel_id == sentinel_id
        else "Sentinel",
        "groups": node.groups,
    }
