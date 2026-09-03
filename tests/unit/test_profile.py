from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from legionctl.errors import ValidationFailed
from legionctl.models.profile import Profile, is_mac_address, is_oui, is_uuid
from legionctl.services.profiles import profile_json_schema, validate_profile_file

MINIMAL_SCAN = {
    "wifi_2_4_channels": [1, 6, 11],
    "wifi_5_channels": [36, 40, 44, 48],
    "wifi_scan_interval_seconds": 15,
    "wifi_dwell_ms": 250,
    "ble_scan_interval_ms": 100,
    "ble_scan_window_ms": 30,
    "classic_inquiry_seconds": 10,
    "classic_rest_seconds": 20,
}


def _rule(**overrides: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "fox-03-classic",
        "name": "FOX-03 Bluetooth Classic",
        "enabled": True,
        "technology": "bt_classic",
        "match": {"all": [{"field": "address", "equals": "AA:BB:CC:DD:EE:FF"}]},
        "minimum_rssi_dbm": -78,
        "required_hits": 2,
        "window_seconds": 20,
        "cooldown_seconds": 300,
        "severity": "high",
    }
    rule.update(overrides)
    return rule


def _profile(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "event-alpha",
        "revision": 4,
        "description": "test",
        "default_cooldown_seconds": 300,
        "scan_policy": dict(MINIMAL_SCAN),
        "rules": [_rule()],
    }
    payload.update(overrides)
    return payload


def test_example_profile_validates(example_profile_path: Path) -> None:
    profile = validate_profile_file(example_profile_path)
    assert profile.profile_id == "event-alpha"
    assert profile.revision == 4
    assert profile.technologies() == ["ble", "bt_classic", "wifi"]


def test_mac_oui_uuid_helpers() -> None:
    assert is_mac_address("AA:BB:CC:DD:EE:FF")
    assert not is_mac_address("AA-BB-CC-DD-EE-FF")
    assert not is_mac_address("AABBCCDDEEFF")
    assert is_oui("AA:BB:CC")
    assert not is_oui("AA:BB:CC:DD")
    assert is_uuid("12345678-1234-1234-1234-1234567890ab")
    assert is_uuid("0x1234")
    assert is_uuid("1234")
    assert is_uuid("0x12345678")
    assert not is_uuid("not-a-uuid")


def test_unknown_technology_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown technology"):
        Profile.model_validate(_profile(rules=[_rule(technology="zigbee")]))


def test_rule_requires_positive_matcher() -> None:
    with pytest.raises(ValidationError, match="positive matcher"):
        Profile.model_validate(
            _profile(rules=[_rule(match={"exclude": [{"field": "name", "equals": "x"}]})])
        )


def test_invalid_mac_rejected() -> None:
    with pytest.raises(ValidationError, match="colon-separated"):
        Profile.model_validate(
            _profile(rules=[_rule(match={"all": [{"field": "address", "equals": "not-a-mac"}]})])
        )


def test_invalid_oui_rejected() -> None:
    with pytest.raises(ValidationError, match="three colon-separated octets"):
        Profile.model_validate(
            _profile(
                rules=[
                    _rule(
                        technology="ble",
                        match={"all": [{"field": "oui", "equals": "AA:BB"}]},
                    )
                ]
            )
        )


def test_invalid_uuid_rejected() -> None:
    with pytest.raises(ValidationError, match="UUID"):
        Profile.model_validate(
            _profile(
                rules=[
                    _rule(
                        id="ble-1",
                        technology="ble",
                        match={"all": [{"field": "service_uuid", "equals": "zzzz"}]},
                    )
                ]
            )
        )


def test_rssi_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(rules=[_rule(minimum_rssi_dbm=1)]))
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(rules=[_rule(minimum_rssi_dbm=-101)]))


def test_required_hits_and_durations() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(rules=[_rule(required_hits=0)]))
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(rules=[_rule(window_seconds=0)]))
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(scan_policy={**MINIMAL_SCAN, "wifi_dwell_ms": 0}))


def test_channel_validation() -> None:
    with pytest.raises(ValidationError, match="1-14"):
        Profile.model_validate(_profile(scan_policy={**MINIMAL_SCAN, "wifi_2_4_channels": [1, 15]}))
    with pytest.raises(ValidationError, match="5 GHz"):
        Profile.model_validate(_profile(scan_policy={**MINIMAL_SCAN, "wifi_5_channels": [1]}))


def test_ble_window_must_fit_interval() -> None:
    with pytest.raises(ValidationError, match="ble_scan_window_ms"):
        Profile.model_validate(
            _profile(
                scan_policy={**MINIMAL_SCAN, "ble_scan_interval_ms": 20, "ble_scan_window_ms": 30}
            )
        )


def test_revision_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_profile(revision=0))


def test_unsupported_schema_version() -> None:
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        Profile.model_validate(_profile(schema_version=2))


def test_exactly_one_operator() -> None:
    with pytest.raises(ValidationError, match="exactly one comparison operator"):
        Profile.model_validate(
            _profile(
                rules=[
                    _rule(
                        match={
                            "all": [
                                {
                                    "field": "address",
                                    "equals": "AA:BB:CC:DD:EE:FF",
                                    "contains": "AA",
                                }
                            ]
                        }
                    )
                ]
            )
        )


def test_wifi_field_not_valid_for_ble() -> None:
    with pytest.raises(ValidationError, match="not valid"):
        Profile.model_validate(
            _profile(
                rules=[
                    _rule(
                        technology="ble",
                        match={"all": [{"field": "bssid", "equals": "AA:BB:CC:DD:EE:FF"}]},
                    )
                ]
            )
        )


def test_band_only_for_wifi() -> None:
    with pytest.raises(ValidationError, match="band is only valid"):
        Profile.model_validate(_profile(rules=[_rule(band="5ghz")]))


def test_duplicate_rule_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate rule id"):
        Profile.model_validate(_profile(rules=[_rule(), _rule()]))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed, match="not found"):
        validate_profile_file(tmp_path / "missing.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationFailed, match="invalid JSON"):
        validate_profile_file(path)


def test_validation_error_paths(tmp_path: Path) -> None:
    path = tmp_path / "bad-profile.json"
    path.write_text(json.dumps(_profile(rules=[_rule(minimum_rssi_dbm=5)])), encoding="utf-8")
    with pytest.raises(ValidationFailed) as exc:
        validate_profile_file(path)
    assert any("minimum_rssi_dbm" in item for item in exc.value.errors)


def test_json_schema_export() -> None:
    schema = profile_json_schema()
    assert schema["type"] == "object"
    assert "profile_id" in schema["properties"]
    assert "rules" in schema["properties"]
