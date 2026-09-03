from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legionctl.constants import (
    PROFILE_SCHEMA_VERSION,
    RSSI_MAX_DBM,
    RSSI_MIN_DBM,
    WIFI_5_CHANNELS,
    WIFI_24_CHANNELS,
)

Technology = Literal["wifi", "ble", "bt_classic"]
Severity = Literal["low", "medium", "high", "critical"]
WifiBand = Literal["2.4ghz", "5ghz"]

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
OUI_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){2}$")
UUID_128_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
UUID_32_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]{8}$")
UUID_16_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]{4}$")
MANUFACTURER_ID_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]{4}$")

WIFI_FIELDS = frozenset({"bssid", "ssid", "oui"})
BLE_FIELDS = frozenset({"address", "local_name", "service_uuid", "manufacturer_id", "oui"})
BT_CLASSIC_FIELDS = frozenset({"address", "name", "local_name", "oui"})
FIELDS_BY_TECHNOLOGY: dict[str, frozenset[str]] = {
    "wifi": WIFI_FIELDS,
    "ble": BLE_FIELDS,
    "bt_classic": BT_CLASSIC_FIELDS,
}
MAC_FIELDS = frozenset({"address", "bssid"})
KNOWN_TECHNOLOGIES = frozenset({"wifi", "ble", "bt_classic"})


def loc_to_path(loc: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def is_mac_address(value: str) -> bool:
    return bool(MAC_RE.fullmatch(value))


def is_oui(value: str) -> bool:
    return bool(OUI_RE.fullmatch(value))


def is_uuid(value: str) -> bool:
    return bool(
        UUID_128_RE.fullmatch(value) or UUID_32_RE.fullmatch(value) or UUID_16_RE.fullmatch(value)
    )


def is_manufacturer_id(value: str) -> bool:
    return bool(MANUFACTURER_ID_RE.fullmatch(value))


class MatchCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    equals: str | None = None
    contains: str | None = None
    prefix: str | None = None
    regex: str | None = None
    exists: bool | None = None

    @model_validator(mode="after")
    def exactly_one_operator(self) -> Self:
        operators = [self.equals, self.contains, self.prefix, self.regex]
        present = sum(value is not None for value in operators)
        if self.exists is not None:
            present += 1
        if present != 1:
            raise ValueError("exactly one comparison operator is required")
        if self.regex is not None:
            try:
                re.compile(self.regex)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc
        return self

    def operator_value(self) -> tuple[str, str | bool]:
        if self.equals is not None:
            return "equals", self.equals
        if self.contains is not None:
            return "contains", self.contains
        if self.prefix is not None:
            return "prefix", self.prefix
        if self.regex is not None:
            return "regex", self.regex
        if self.exists is not None:
            return "exists", self.exists
        raise ValueError("exactly one comparison operator is required")


class MatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: list[MatchCondition] = Field(default_factory=list)
    any: list[MatchCondition] = Field(default_factory=list)
    exclude: list[MatchCondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_positive_matcher(self) -> Self:
        if not self.all and not self.any:
            raise ValueError("at least one positive matcher in 'all' or 'any' is required")
        return self


class ScanPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wifi_2_4_channels: list[int] = Field(default_factory=list)
    wifi_5_channels: list[int] = Field(default_factory=list)
    wifi_scan_interval_seconds: int | None = Field(default=None, ge=1, le=3600)
    wifi_dwell_ms: int = Field(ge=10, le=5000)
    ble_scan_interval_ms: int = Field(ge=1, le=10_000)
    ble_scan_window_ms: int = Field(ge=1, le=10_000)
    classic_inquiry_seconds: int = Field(ge=1, le=60)
    classic_rest_seconds: int = Field(ge=1, le=3600)

    @field_validator("wifi_2_4_channels")
    @classmethod
    def validate_24_channels(cls, value: list[int]) -> list[int]:
        invalid = [channel for channel in value if channel not in WIFI_24_CHANNELS]
        if invalid:
            raise ValueError(f"Wi-Fi 2.4 GHz channels must be 1-14; invalid: {invalid}")
        if len(set(value)) != len(value):
            raise ValueError("Wi-Fi 2.4 GHz channels must be unique")
        return value

    @field_validator("wifi_5_channels")
    @classmethod
    def validate_5_channels(cls, value: list[int]) -> list[int]:
        invalid = [channel for channel in value if channel not in WIFI_5_CHANNELS]
        if invalid:
            raise ValueError(f"unsupported Wi-Fi 5 GHz channel(s): {invalid}")
        if len(set(value)) != len(value):
            raise ValueError("Wi-Fi 5 GHz channels must be unique")
        return value

    @model_validator(mode="after")
    def window_within_interval(self) -> Self:
        if self.ble_scan_window_ms > self.ble_scan_interval_ms:
            raise ValueError("ble_scan_window_ms must be <= ble_scan_interval_ms")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool = True
    technology: Technology
    band: WifiBand | None = None
    match: MatchModel
    minimum_rssi_dbm: int = Field(ge=RSSI_MIN_DBM, le=RSSI_MAX_DBM)
    required_hits: int = Field(ge=1)
    window_seconds: int = Field(ge=1, le=3600)
    cooldown_seconds: int = Field(ge=0, le=86_400)
    severity: Severity

    @field_validator("technology", mode="before")
    @classmethod
    def reject_unknown_technology(cls, value: Any) -> Any:
        if isinstance(value, str) and value not in KNOWN_TECHNOLOGIES:
            raise ValueError(f"unknown technology '{value}'")
        return value

    @model_validator(mode="after")
    def validate_match_fields(self) -> Self:
        if self.band is not None and self.technology != "wifi":
            raise ValueError("band is only valid for wifi rules")
        allowed = FIELDS_BY_TECHNOLOGY[self.technology]
        for group_name, conditions in (
            ("all", self.match.all),
            ("any", self.match.any),
            ("exclude", self.match.exclude),
        ):
            for index, condition in enumerate(conditions):
                if condition.field not in allowed:
                    raise ValueError(
                        f"match.{group_name}[{index}].field '{condition.field}' is not valid "
                        f"for technology '{self.technology}'"
                    )
                _validate_condition_value(condition, path=f"match.{group_name}[{index}]")
        return self


def _validate_condition_value(condition: MatchCondition, *, path: str) -> None:
    operator, raw = condition.operator_value()
    if operator == "exists":
        return
    if not isinstance(raw, str):
        raise ValueError(f"{path}: comparison value must be a string")
    if operator != "equals":
        return
    if condition.field in MAC_FIELDS and not is_mac_address(raw):
        raise ValueError(
            f"{path}.{condition.field} must be a colon-separated MAC/BSSID address"
        )
    if condition.field == "oui" and not is_oui(raw):
        raise ValueError(f"{path}.oui must be three colon-separated octets")
    if condition.field == "service_uuid" and not is_uuid(raw):
        raise ValueError(
            f"{path}.service_uuid must be a 16-bit, 32-bit, or 128-bit UUID"
        )
    if condition.field == "manufacturer_id" and not is_manufacturer_id(raw):
        raise ValueError(f"{path}.manufacturer_id must be a 16-bit hex value")


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    profile_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    description: str = ""
    default_cooldown_seconds: int = Field(ge=0, le=86_400)
    scan_policy: ScanPolicy
    rules: list[Rule] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value: int) -> int:
        if value != PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {value}; expected {PROFILE_SCHEMA_VERSION}"
            )
        return value

    @model_validator(mode="after")
    def unique_rule_ids(self) -> Self:
        seen: set[str] = set()
        duplicates: list[str] = []
        for rule in self.rules:
            if rule.id in seen:
                duplicates.append(rule.id)
            seen.add(rule.id)
        if duplicates:
            raise ValueError(f"duplicate rule id(s): {', '.join(duplicates)}")
        return self

    def technologies(self) -> list[str]:
        return sorted({rule.technology for rule in self.rules})
