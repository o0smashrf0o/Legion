from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from legionctl.models.node_api import SentinelEvent


class FleetNodeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str
    zone: str | None = None
    ok: bool
    reachable: bool
    error: str | None = None
    error_kind: Literal["none", "unreachable", "auth", "other"] = "none"
    battery_percent: int | None = None
    battery_charging: bool | None = None
    wifi_connected: bool | None = None
    wifi_band: str | None = None
    wifi_rssi_dbm: int | None = None
    scanner_wifi: str | None = None
    scanner_ble: str | None = None
    bt_classic_coprocessor: str | None = None
    alert_queue_depth: int | None = None
    profile_id: str | None = None
    profile_revision: int | None = None
    timestamp_utc: str | None = None


class FleetNodeHealth(FleetNodeStatus):
    battery_voltage_v: float | None = None
    wifi_reconnect_count: int | None = None
    alert_last_delivery: str | None = None
    free_heap_bytes: int | None = None
    reset_reason: str | None = None
    watchdog_resets: int | None = None


class FleetNodeEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str
    zone: str | None = None
    ok: bool
    reachable: bool
    error: str | None = None
    error_kind: Literal["none", "unreachable", "auth", "other"] = "none"
    events: list[dict[str, Any]] = Field(default_factory=list)


def event_to_json(event: SentinelEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    timestamp = payload.get("timestamp_utc")
    if isinstance(timestamp, str) and timestamp.endswith("+00:00"):
        payload["timestamp_utc"] = timestamp.replace("+00:00", "Z")
    return payload
