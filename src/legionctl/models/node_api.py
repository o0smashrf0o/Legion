from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from legionctl.models.profile import Rule, ScanPolicy


class InfoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_version: str
    sentinel_id: str
    display_name: str | None = None
    zone: str | None = None
    firmware_version: str | None = None
    build_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    profile_id: str | None = None
    profile_revision: int | None = None
    uptime_seconds: int | None = Field(default=None, ge=0)


class BatteryHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voltage_v: float | None = None
    percent: int | None = Field(default=None, ge=0, le=100)
    charging: bool | None = None


class WifiHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    connected: bool
    ssid: str | None = None
    band: str | None = None
    rssi_dbm: int | None = None
    ip: str | None = None
    reconnect_count: int | None = Field(default=None, ge=0)


class ScannerHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wifi: str | None = None
    ble: str | None = None
    bt_classic_coprocessor: str | None = None


class AlertQueueHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    depth: int = Field(ge=0)
    last_delivery: str | None = None


class SystemHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    free_heap_bytes: int | None = Field(default=None, ge=0)
    reset_reason: str | None = None
    watchdog_resets: int | None = Field(default=None, ge=0)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentinel_id: str
    timestamp_utc: datetime
    battery: BatteryHealth | None = None
    wifi: WifiHealth | None = None
    scanners: ScannerHealth | None = None
    alert_queue: AlertQueueHealth | None = None
    system: SystemHealth | None = None


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentinel_id: str
    zone: str | None = None
    timezone: str | None = None
    profile_id: str | None = None
    profile_revision: int | None = None
    discord_configured: bool | None = None
    wifi_configured: bool | None = None
    scan_policy: ScanPolicy | None = None


class RulesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile_id: str
    revision: int = Field(ge=1)
    schema_version: int = Field(ge=1)
    rules: list[Rule] = Field(default_factory=list)


class RulesActivationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["activated"]
    profile_id: str
    revision: int = Field(ge=1)
    activation_timestamp_utc: datetime


class RuleValidationError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    message: str


class RulesRejectionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["rejected"]
    errors: list[RuleValidationError] = Field(default_factory=list)


class TestAlertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Legion test alert"
    include_health_summary: bool = True


class TestAlertResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: bool
    queued: bool
    delivery: str
    timestamp_utc: datetime


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start", "stop"]
    technology: Literal["wifi", "ble", "bt_classic"]
    duration_seconds: int = Field(ge=1, le=300)


class RebootRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "operator_requested"


class EventConfidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hits: int = Field(ge=0)
    window_seconds: int = Field(ge=0)


class SentinelEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    timestamp_utc: datetime
    event_type: str
    soi_id: str | None = None
    technology: str | None = None
    rssi_dbm: int | None = None
    confidence: EventConfidence | None = None
    discord_delivery: str | None = None


class RecentEventsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sentinel_id: str
    events: list[SentinelEvent] = Field(default_factory=list)


class ScanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: bool = True
    action: str | None = None
    technology: str | None = None
    duration_seconds: int | None = None


class RebootResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accepted: bool = True
    reason: str | None = None


