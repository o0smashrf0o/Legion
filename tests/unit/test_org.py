from __future__ import annotations

import pytest

from legionctl.errors import UsageError
from legionctl.models.fleet import FleetNodeStatus
from legionctl.models.inventory import SentinelNode
from legionctl.services import org
from legionctl.services.audit import read_recent_audit
from legionctl.services.inventory import add_node
from legionctl.settings import LegionPaths


def _node(sentinel_id: str) -> SentinelNode:
    return SentinelNode(
        sentinel_id=sentinel_id,
        display_name=sentinel_id,
        hostname=f"{sentinel_id}.local",
        base_url=f"https://{sentinel_id}.local",
    )


def _health(sentinel_id: str, *, reachable: bool = True, ok: bool = True) -> FleetNodeStatus:
    return FleetNodeStatus(
        sentinel_id=sentinel_id,
        ok=ok,
        reachable=reachable,
        wifi_connected=ok and reachable,
    )


def _seed(count: int = 6) -> list[str]:
    ids = [f"sentinel-north-0{index}" for index in range(1, count + 1)]
    for sentinel_id in ids:
        add_node(_node(sentinel_id))
    return ids


def test_zone_create_edit_archive(legion_home: LegionPaths) -> None:
    zone = org.create_zone(name="North Entry", zone_type="physical")
    assert zone.zone_id == "north-entry"
    edited = org.update_zone(zone.zone_id, description="Primary north-side entrance")
    assert edited.description.startswith("Primary")
    archived = org.archive_zone(zone.zone_id)
    assert archived.status == "inactive"


def test_cohort_zone_assignment_and_uniqueness(legion_home: LegionPaths) -> None:
    ids = _seed(2)
    zone = org.create_zone(name="North Entry")
    cohort = org.create_cohort(
        display_name="North Entry Cohort 01",
        cohort_id="cohort-north-entry-01",
    )
    org.assign_cohort_zone(cohort.cohort_id, zone.zone_id)
    org.add_sentinel_to_cohort(cohort.cohort_id, ids[0])
    other = org.create_cohort(display_name="Other", cohort_id="cohort-other")
    with pytest.raises(UsageError, match="already belongs"):
        org.add_sentinel_to_cohort(other.cohort_id, ids[0])
    assigned = org.assignment_for(ids[0])
    assert assigned["cohort_id"] == "cohort-north-entry-01"
    assert assigned["zone_id"] == zone.zone_id
    assert assigned["role"] == "Primus"


def test_primus_must_be_member_and_transfer(legion_home: LegionPaths) -> None:
    ids = _seed(2)
    org.create_cohort(display_name="C1", cohort_id="c1")
    org.add_sentinel_to_cohort("c1", ids[0])
    org.add_sentinel_to_cohort("c1", ids[1])
    with pytest.raises(UsageError, match="member"):
        org.set_primus("c1", "missing")
    updated = org.set_primus("c1", ids[1])
    assert updated.primus_sentinel_id == ids[1]
    with pytest.raises(UsageError, match="new Primus"):
        org.remove_sentinel_from_cohort("c1", ids[1])
    org.remove_sentinel_from_cohort("c1", ids[1], new_primus=ids[0])
    assert org.get_cohort("c1").primus_sentinel_id == ids[0]


def test_readiness_understrength_nominal_reinforced(legion_home: LegionPaths) -> None:
    ids = _seed(6)
    zone = org.create_zone(name="North Entry")
    org.create_cohort(display_name="C1", cohort_id="c1", zone_id=zone.zone_id)
    from legionctl.services.inventory import load_inventory

    for sentinel_id in ids[:3]:
        org.add_sentinel_to_cohort("c1", sentinel_id)
    inventory = load_inventory()
    readiness, _flags, roster = org.cohort_readiness(org.get_cohort("c1"), inventory)
    assert readiness == "understrength"
    assert roster == 3
    for sentinel_id in ids[3:5]:
        org.add_sentinel_to_cohort("c1", sentinel_id)
    inventory = load_inventory()
    readiness, _flags, roster = org.cohort_readiness(org.get_cohort("c1"), inventory)
    assert readiness == "nominal"
    assert roster == 5
    org.add_sentinel_to_cohort("c1", ids[5])
    inventory = load_inventory()
    readiness, _flags, roster = org.cohort_readiness(org.get_cohort("c1"), inventory)
    assert readiness == "reinforced"
    assert roster == 6


def test_offline_primus_is_degraded(legion_home: LegionPaths) -> None:
    ids = _seed(5)
    zone = org.create_zone(name="North Entry")
    org.create_cohort(display_name="C1", cohort_id="c1", zone_id=zone.zone_id)
    for sentinel_id in ids:
        org.add_sentinel_to_cohort("c1", sentinel_id)
    from legionctl.services.inventory import load_inventory

    inventory = load_inventory()
    cohort = org.get_cohort("c1")
    health = {
        sentinel_id: _health(sentinel_id, reachable=sentinel_id != ids[0])
        for sentinel_id in ids
    }
    readiness, flags, _roster = org.cohort_readiness(cohort, inventory, health)
    assert readiness == "degraded"
    assert "primus_unhealthy" in flags


def test_org_audit_and_no_secrets(legion_home: LegionPaths) -> None:
    from legionctl.commands.common import audit_action

    zone = org.create_zone(name="North Entry")
    audit_action(
        "zone_create",
        targets=[zone.zone_id],
        result="success",
        details={"name": zone.name, "token": "super-secret-token"},
    )
    records = read_recent_audit(5)
    assert records
    assert records[0]["operation"] == "zone_create"
    blob = legion_home.audit_log.read_text(encoding="utf-8")
    assert "super-secret-token" not in blob
    assert "webhook" not in blob.lower()
