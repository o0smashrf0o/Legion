from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.models.inventory import Group, Inventory, SentinelNode
from legionctl.services.credentials import CredentialStore
from legionctl.services.inventory import save_inventory
from legionctl.settings import LegionPaths

runner = CliRunner()
TOKEN = "super-secret-token"

NORTH = "sentinel-north-door-01"
HALL = "sentinel-hall-b-01"
GARAGE = "sentinel-garage-01"


def _node(sentinel_id: str, zone: str, host: str) -> SentinelNode:
    return SentinelNode(
        sentinel_id=sentinel_id,
        display_name=zone,
        zone=zone,
        hostname=f"{host}.local",
        base_url=f"https://{host}.local",
    )


def _info(sentinel_id: str, zone: str, revision: int = 4) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "sentinel_id": sentinel_id,
        "display_name": zone,
        "zone": zone,
        "firmware_version": "0.1.0",
        "profile_id": "event-alpha",
        "profile_revision": revision,
        "uptime_seconds": 10,
    }


def _health(
    sentinel_id: str,
    *,
    percent: int,
    band: str,
    rssi: int,
    queue: int,
) -> dict[str, Any]:
    return {
        "sentinel_id": sentinel_id,
        "timestamp_utc": "2026-09-03T22:30:00Z",
        "battery": {"voltage_v": 3.9, "percent": percent, "charging": False},
        "wifi": {
            "connected": True,
            "ssid": "REDACTED_OR_OPTIONAL",
            "band": band,
            "rssi_dbm": rssi,
            "ip": "192.168.50.41",
            "reconnect_count": 0,
        },
        "scanners": {
            "wifi": "running",
            "ble": "running",
            "bt_classic_coprocessor": "healthy",
        },
        "alert_queue": {"depth": queue, "last_delivery": "success"},
        "system": {"free_heap_bytes": 1000, "reset_reason": "power_on", "watchdog_resets": 0},
    }


EVENTS: dict[str, Any] = {
    "sentinel_id": NORTH,
    "events": [
        {
            "event_id": "evt_01J7",
            "timestamp_utc": "2026-09-03T22:20:00Z",
            "event_type": "alert",
            "soi_id": "fox-03",
            "technology": "bt_classic",
            "rssi_dbm": -63,
            "confidence": {"hits": 3, "window_seconds": 15},
            "discord_delivery": "success",
        }
    ],
}


@pytest.fixture
def fleet_inventory(legion_home: LegionPaths) -> LegionPaths:
    save_inventory(
        Inventory(
            nodes=[
                _node(NORTH, "North Door", NORTH),
                _node(HALL, "Hall B", HALL),
                _node(GARAGE, "Garage", GARAGE),
            ],
            groups=[
                Group(group="event-alpha", description="Event Alpha", members=[NORTH, HALL]),
            ],
        )
    )
    store = CredentialStore()
    for sentinel_id in (NORTH, HALL, GARAGE):
        store.set_token(sentinel_id, TOKEN)
    return legion_home


def _mock_ok(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, "North Door"))
    )
    respx_mock.get(f"https://{NORTH}.local/api/v1/health").mock(
        return_value=httpx.Response(
            200, json=_health(NORTH, percent=67, band="5ghz", rssi=-58, queue=0)
        )
    )
    respx_mock.get(f"https://{HALL}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(HALL, "Hall B"))
    )
    respx_mock.get(f"https://{HALL}.local/api/v1/health").mock(
        return_value=httpx.Response(
            200, json=_health(HALL, percent=41, band="2.4ghz", rssi=-70, queue=1)
        )
    )
    respx_mock.get(f"https://{GARAGE}.local/api/v1/info").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    respx_mock.get(f"https://{GARAGE}.local/api/v1/health").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )


def test_status_all_partial_failure(
    fleet_inventory: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    _mock_ok(respx_mock)
    result = runner.invoke(app, ["--json", "status", "--all"])
    assert result.exit_code == 2, result.output
    assert '"sentinel_id": "sentinel-north-door-01"' in result.stdout
    assert '"battery_percent": 67' in result.stdout
    assert '"wifi_band": "5ghz"' in result.stdout
    assert '"reachable": false' in result.stdout
    assert TOKEN not in result.output
    assert "webhook" not in result.output.lower()

    human = runner.invoke(app, ["status", "--all"])
    assert human.exit_code == 2
    assert "unreachable" in human.stdout or "unreachable" in human.output


def test_status_selector_and_node(
    fleet_inventory: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    _mock_ok(respx_mock)
    selected = runner.invoke(app, ["--json", "status", "--selector", "zone=North Door"])
    assert selected.exit_code == 0, selected.output
    assert NORTH in selected.stdout
    assert HALL not in selected.stdout

    single = runner.invoke(app, ["--json", "status", "--node", NORTH])
    assert single.exit_code == 0
    assert '"ok": true' in single.stdout


def test_health_group(fleet_inventory: LegionPaths, respx_mock: respx.MockRouter) -> None:
    _mock_ok(respx_mock)
    result = runner.invoke(app, ["--json", "health", "--group", "event-alpha"])
    assert result.exit_code == 0, result.output
    assert NORTH in result.stdout
    assert HALL in result.stdout
    assert GARAGE not in result.stdout
    assert '"battery_voltage_v": 3.9' in result.stdout
    assert TOKEN not in result.output


def test_events_node_limit(fleet_inventory: LegionPaths, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"https://{NORTH}.local/api/v1/events/recent").mock(
        return_value=httpx.Response(200, json=EVENTS)
    )
    result = runner.invoke(
        app, ["--json", "events", "--node", NORTH, "--limit", "50"]
    )
    assert result.exit_code == 0, result.output
    assert '"event_type": "alert"' in result.stdout
    assert '"soi_id": "fox-03"' in result.stdout
    assert "pcap" not in result.stdout.lower()
    assert TOKEN not in result.output
    assert route.calls[0].request.url.params["limit"] == "50"


def test_status_requires_target(fleet_inventory: LegionPaths) -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1


def test_mixed_auth_and_success_is_exit_2(
    fleet_inventory: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    _mock_ok(respx_mock)
    respx_mock.get(f"https://{HALL}.local/api/v1/health").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    respx_mock.get(f"https://{HALL}.local/api/v1/info").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    result = runner.invoke(app, ["--json", "status", "--group", "event-alpha"])
    assert result.exit_code == 2, result.output
    assert TOKEN not in result.output
