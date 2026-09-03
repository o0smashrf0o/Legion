from __future__ import annotations

import pytest
from pydantic import ValidationError

from legionctl.models.node_api import HealthResponse, InfoResponse, RecentEventsResponse


def test_info_and_health_models() -> None:
    info = InfoResponse.model_validate(
        {
            "api_version": "v1",
            "sentinel_id": "sentinel-north-door-01",
            "display_name": "North Door",
            "zone": "North Door",
            "firmware_version": "0.1.0",
            "build_id": "git-abcdef1",
            "capabilities": ["wifi_2_4ghz", "ble"],
            "profile_id": "event-alpha",
            "profile_revision": 4,
            "uptime_seconds": 81234,
        }
    )
    assert info.sentinel_id == "sentinel-north-door-01"

    health = HealthResponse.model_validate(
        {
            "sentinel_id": "sentinel-north-door-01",
            "timestamp_utc": "2026-09-03T22:30:00Z",
            "battery": {"voltage_v": 3.92, "percent": 67, "charging": False},
            "wifi": {
                "connected": True,
                "ssid": "REDACTED_OR_OPTIONAL",
                "band": "5ghz",
                "rssi_dbm": -58,
                "ip": "192.168.50.41",
                "reconnect_count": 2,
            },
            "scanners": {"wifi": "running", "ble": "running", "bt_classic_coprocessor": "healthy"},
            "alert_queue": {"depth": 0, "last_delivery": "success"},
            "system": {"free_heap_bytes": 145280, "reset_reason": "power_on", "watchdog_resets": 0},
        }
    )
    assert health.battery is not None
    assert health.battery.percent == 67


def test_malformed_health_is_rejected() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"sentinel_id": "x"})


def test_events_are_metadata_only() -> None:
    payload = RecentEventsResponse.model_validate(
        {
            "sentinel_id": "sentinel-north-door-01",
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
    )
    dumped = payload.model_dump()
    assert "pcap" not in dumped
    assert "payload" not in str(dumped).lower() or payload.events[0].event_type == "alert"
