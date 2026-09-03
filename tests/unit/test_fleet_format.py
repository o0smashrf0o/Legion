from __future__ import annotations

from legionctl.errors import AuthenticationError, NodeUnreachableError
from legionctl.models.fleet import FleetNodeStatus
from legionctl.output.console import format_battery, format_profile, format_scanners, format_wifi
from legionctl.services.fleet import classify_error, fleet_exit_code


def _row(**kwargs: object) -> FleetNodeStatus:
    payload: dict[str, object] = {
        "sentinel_id": "sentinel-north-door-01",
        "zone": "North Door",
        "ok": True,
        "reachable": True,
        "error": None,
        "error_kind": "none",
        "battery_percent": 67,
        "wifi_connected": True,
        "wifi_band": "5ghz",
        "wifi_rssi_dbm": -58,
        "scanner_wifi": "running",
        "scanner_ble": "running",
        "bt_classic_coprocessor": "healthy",
        "alert_queue_depth": 0,
        "profile_id": "event-alpha",
        "profile_revision": 4,
        "timestamp_utc": "2026-09-03T22:30:00Z",
    }
    payload.update(kwargs)
    return FleetNodeStatus.model_validate(payload)


def test_status_formatters() -> None:
    row = _row()
    assert format_battery(row) == "67%"
    assert format_wifi(row) == "5 GHz / -58 dBm"
    assert format_scanners(row) == "running"
    assert format_profile(row) == "event-alpha r4"
    down = _row(
        ok=False,
        reachable=False,
        battery_percent=None,
        wifi_connected=None,
        scanner_wifi=None,
        scanner_ble=None,
        profile_id=None,
        profile_revision=None,
        timestamp_utc=None,
        error="unreachable",
        error_kind="unreachable",
    )
    assert format_battery(down) == "--"
    assert format_wifi(down) == "unreachable"
    assert format_scanners(down) == "unknown"
    assert format_profile(down) == "unknown"


def test_fleet_exit_code() -> None:
    ok = _row()
    unreachable = _row(ok=False, reachable=False, error_kind="unreachable", error="down")
    auth = _row(ok=False, reachable=False, error_kind="auth", error="unauthorized")
    assert fleet_exit_code([ok]) == 0
    assert fleet_exit_code([ok, unreachable]) == 2
    assert fleet_exit_code([unreachable]) == 2
    assert fleet_exit_code([auth, auth]) == 3
    assert fleet_exit_code([]) == 1
    assert classify_error(NodeUnreachableError("down")) == "unreachable"
    assert classify_error(AuthenticationError("no")) == "auth"
