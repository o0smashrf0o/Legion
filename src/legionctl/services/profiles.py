from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from legionctl.errors import TargetNotFoundError, UsageError, ValidationFailed
from legionctl.models.profile import Profile, ScanPolicy, loc_to_path
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import atomic_write_json


def profile_json_schema() -> dict[str, Any]:
    return Profile.model_json_schema()


def bundled_schema_path() -> Path:
    resource = files("legionctl.resources").joinpath("profile.schema.json")
    return Path(str(resource))


def format_validation_errors(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        path = loc_to_path(error["loc"])
        message = error["msg"]
        if path:
            messages.append(f"{path}: {message}")
        else:
            messages.append(message)
    return messages


def load_profile(path: Path) -> Profile:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationFailed([f"unable to read {path}: {exc}"]) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed([f"{path}: invalid JSON: {exc.msg}"]) from exc
    try:
        return Profile.model_validate(payload)
    except ValidationError as exc:
        raise ValidationFailed(format_validation_errors(exc)) from exc


def validate_profile_file(path: Path) -> Profile:
    if not path.exists():
        raise ValidationFailed([f"profile file not found: {path}"])
    return load_profile(path)


def write_profile(profile: Profile, path: Path) -> None:
    atomic_write_json(path, json.loads(profile.model_dump_json()))


def assert_safe_profile_id(profile_id: str) -> str:
    if not profile_id or any(part in profile_id for part in ("/", "\\", "..")):
        raise UsageError("profile_id must not contain path separators")
    return profile_id


def installed_profile_path(profile_id: str, paths: LegionPaths | None = None) -> Path:
    resolved = paths or get_paths()
    return resolved.profiles_dir / f"{assert_safe_profile_id(profile_id)}.json"


def load_installed_profile(profile_id: str, paths: LegionPaths | None = None) -> Profile:
    path = installed_profile_path(profile_id, paths)
    if not path.exists():
        raise TargetNotFoundError(f"profile '{profile_id}' is not installed")
    return load_profile(path)


def list_installed_profiles(paths: LegionPaths | None = None) -> list[Profile]:
    resolved = paths or get_paths()
    if not resolved.profiles_dir.exists():
        return []
    profiles: list[Profile] = []
    for path in sorted(resolved.profiles_dir.glob("*.json")):
        try:
            profiles.append(load_profile(path))
        except ValidationFailed:
            continue
    return profiles


def _write_installed(profile: Profile, *, overwrite: bool, paths: LegionPaths | None) -> Path:
    dest = installed_profile_path(profile.profile_id, paths)
    if dest.exists() and not overwrite:
        raise UsageError(f"profile '{profile.profile_id}' already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_profile(profile, dest)
    return dest


def minimal_profile(profile_id: str, *, description: str = "") -> Profile:
    return Profile(
        schema_version=1,
        profile_id=assert_safe_profile_id(profile_id),
        revision=1,
        description=description,
        default_cooldown_seconds=300,
        scan_policy=ScanPolicy(
            wifi_2_4_channels=[1, 6, 11],
            wifi_5_channels=[36, 40, 44, 48],
            wifi_scan_interval_seconds=15,
            wifi_dwell_ms=250,
            ble_scan_interval_ms=100,
            ble_scan_window_ms=30,
            classic_inquiry_seconds=10,
            classic_rest_seconds=20,
        ),
        rules=[],
    )


def create_profile(
    profile_id: str,
    *,
    description: str = "",
    overwrite: bool = False,
    paths: LegionPaths | None = None,
) -> Profile:
    profile = minimal_profile(profile_id, description=description)
    _write_installed(profile, overwrite=overwrite, paths=paths)
    return profile


def import_profile(
    path: Path,
    *,
    overwrite: bool = False,
    paths: LegionPaths | None = None,
) -> Profile:
    profile = validate_profile_file(path)
    _write_installed(profile, overwrite=overwrite, paths=paths)
    return profile


def export_profile(
    profile_id: str,
    output: Path,
    paths: LegionPaths | None = None,
) -> Profile:
    profile = load_installed_profile(profile_id, paths)
    write_profile(profile, output)
    return profile


def clone_profile(
    source_id: str,
    dest_id: str,
    *,
    overwrite: bool = False,
    paths: LegionPaths | None = None,
) -> Profile:
    source = load_installed_profile(source_id, paths)
    cloned = source.model_copy(
        update={"profile_id": assert_safe_profile_id(dest_id), "revision": 1}
    )
    _write_installed(cloned, overwrite=overwrite, paths=paths)
    return cloned


_FUZZY_FIELDS = frozenset({"ssid", "name", "local_name"})
_WATCHLIST_FIELDS = (
    "ssid",
    "bssid",
    "address",
    "oui",
    "local_name",
    "device_name",
    "service_uuid",
    "manufacturer_id",
)
_FIELD_MAP = {"device_name": "name"}


def _slug(value: str, fallback: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return cleaned or fallback


def _condition(field: str, value: str) -> dict[str, str]:
    text = value.strip()
    match_field = _FIELD_MAP.get(field, field)
    if match_field in _FUZZY_FIELDS:
        return {"field": match_field, "contains": text}
    return {"field": match_field, "equals": text}


def profile_from_watchlist(payload: dict[str, Any]) -> Profile:
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        raise ValidationFailed(["profile_id is required"])
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValidationFailed(["at least one SOI target is required"])
    rules: list[dict[str, Any]] = []
    for index, raw in enumerate(targets):
        if not isinstance(raw, dict):
            raise ValidationFailed([f"targets[{index}] must be an object"])
        technology = str(raw.get("technology") or "").strip()
        name = str(raw.get("name") or f"target-{index + 1}").strip()
        rule_id = str(raw.get("id") or _slug(name, f"target-{index + 1}"))
        matchers: list[dict[str, str]] = []
        for field in _WATCHLIST_FIELDS:
            value = raw.get(field)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                matchers.append(_condition(field, text))
        if not matchers:
            raise ValidationFailed(
                [f"targets[{index}] needs a broadcast identifier (SSID, MAC, UUID, name, or OUI)"]
            )
        try:
            rssi = int(raw.get("minimum_rssi_dbm", -80))
            hits = int(raw.get("required_hits", 2))
            window = int(raw.get("window_seconds", 15))
            cooldown = int(raw.get("cooldown_seconds", 300))
        except (TypeError, ValueError) as exc:
            raise ValidationFailed([f"targets[{index}] has invalid numeric fields"]) from exc
        rule: dict[str, Any] = {
            "id": rule_id,
            "name": name,
            "enabled": True,
            "technology": technology,
            "match": {"all": matchers},
            "minimum_rssi_dbm": rssi,
            "required_hits": hits,
            "window_seconds": window,
            "cooldown_seconds": cooldown,
            "severity": str(raw.get("severity") or "medium"),
        }
        band = str(raw.get("band") or "").strip()
        if technology == "wifi" and band:
            rule["band"] = band
        rules.append(rule)
    skeleton = minimal_profile(profile_id, description=str(payload.get("description") or ""))
    document = skeleton.model_dump(mode="json")
    document["rules"] = rules
    revision = payload.get("revision")
    if revision is not None:
        document["revision"] = revision
    try:
        return Profile.model_validate(document)
    except ValidationError as exc:
        raise ValidationFailed(format_validation_errors(exc)) from exc


def watchlist_from_profile(profile: Profile) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for rule in profile.rules:
        target: dict[str, Any] = {
            "id": rule.id,
            "name": rule.name,
            "technology": rule.technology,
            "band": rule.band,
            "minimum_rssi_dbm": rule.minimum_rssi_dbm,
            "required_hits": rule.required_hits,
            "window_seconds": rule.window_seconds,
            "cooldown_seconds": rule.cooldown_seconds,
            "severity": rule.severity,
        }
        for condition in rule.match.all:
            operator, value = condition.operator_value()
            if operator in {"equals", "contains", "prefix"} and isinstance(value, str):
                key = "device_name" if condition.field == "name" else condition.field
                target[key] = value
        targets.append(target)
    return {
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "description": profile.description,
        "targets": targets,
    }


def save_watchlist(payload: dict[str, Any], paths: LegionPaths | None = None) -> Profile:
    profile = profile_from_watchlist(payload)
    dest = installed_profile_path(profile.profile_id, paths)
    if dest.exists():
        existing = load_installed_profile(profile.profile_id, paths)
        if profile.revision <= existing.revision:
            profile = profile.model_copy(update={"revision": existing.revision + 1})
    _write_installed(profile, overwrite=True, paths=paths)
    return profile


def export_schema_to_data_dir(paths: LegionPaths | None = None) -> Path:
    resolved = paths or get_paths()
    destination = resolved.profile_schema_file
    atomic_write_json(destination, profile_json_schema(), mode=0o644)
    return destination
