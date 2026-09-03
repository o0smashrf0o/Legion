from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from legionctl.errors import ValidationFailed
from legionctl.models.profile import Profile, loc_to_path
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


def installed_profile_path(profile_id: str, paths: LegionPaths | None = None) -> Path:
    resolved = paths or get_paths()
    return resolved.profiles_dir / f"{profile_id}.json"


def export_schema_to_data_dir(paths: LegionPaths | None = None) -> Path:
    resolved = paths or get_paths()
    destination = resolved.profile_schema_file
    atomic_write_json(destination, profile_json_schema(), mode=0o644)
    return destination
