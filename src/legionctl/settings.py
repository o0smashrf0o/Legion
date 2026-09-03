from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from legionctl.constants import (
    APP_NAME,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_CONCURRENCY,
    IDEMPOTENT_READ_RETRIES,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SCAN_DURATION_SECONDS,
    READ_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from legionctl.storage import atomic_write_json, read_json


def _xdg_home(env_name: str, default_subpath: Path) -> Path:
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw).expanduser() / APP_NAME
    return Path.home() / default_subpath / APP_NAME


@dataclass(frozen=True)
class LegionPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def inventory_file(self) -> Path:
        return self.config_dir / "inventory.json"

    @property
    def profiles_dir(self) -> Path:
        return self.config_dir / "profiles"

    @property
    def trust_dir(self) -> Path:
        return self.config_dir / "trust"

    @property
    def schema_dir(self) -> Path:
        return self.data_dir / "schema"

    @property
    def profile_schema_file(self) -> Path:
        return self.schema_dir / "profile.schema.json"

    @property
    def audit_log(self) -> Path:
        return self.state_dir / "audit.jsonl"

    @property
    def discovery_cache(self) -> Path:
        return self.state_dir / "discovery-cache.json"

    @property
    def last_results(self) -> Path:
        return self.state_dir / "last-results.json"

    @property
    def credential_key_file(self) -> Path:
        return self.config_dir / ".credential-key"

    @property
    def credential_store_file(self) -> Path:
        return self.state_dir / "credentials.enc"


def get_paths() -> LegionPaths:
    return LegionPaths(
        config_dir=_xdg_home("XDG_CONFIG_HOME", Path(".config")),
        data_dir=_xdg_home("XDG_DATA_HOME", Path(".local") / "share"),
        state_dir=_xdg_home("XDG_STATE_HOME", Path(".local") / "state"),
    )


class AppSettings(BaseModel):
    connect_timeout_seconds: float = Field(default=CONNECT_TIMEOUT_SECONDS, gt=0)
    read_timeout_seconds: float = Field(default=READ_TIMEOUT_SECONDS, gt=0)
    write_timeout_seconds: float = Field(default=WRITE_TIMEOUT_SECONDS, gt=0)
    idempotent_read_retries: int = Field(default=IDEMPOTENT_READ_RETRIES, ge=0)
    concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1)
    max_scan_duration_seconds: int = Field(default=MAX_SCAN_DURATION_SECONDS, ge=1)
    max_request_bytes: int = Field(default=MAX_REQUEST_BYTES, ge=1024)
    max_response_bytes: int = Field(default=MAX_RESPONSE_BYTES, ge=1024)


def load_settings(paths: LegionPaths | None = None) -> AppSettings:
    resolved = paths or get_paths()
    payload = read_json(resolved.config_file)
    if payload is None:
        return AppSettings()
    if not isinstance(payload, dict):
        return AppSettings()
    return AppSettings.model_validate(payload)


def save_settings(settings: AppSettings, paths: LegionPaths | None = None) -> None:
    resolved = paths or get_paths()
    atomic_write_json(resolved.config_file, settings.model_dump())
