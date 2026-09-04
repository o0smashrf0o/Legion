from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DeployAction = Literal["update", "unchanged", "install", "downgrade", "unreachable"]
DeployResultName = Literal["activated", "skipped", "rejected", "unreachable", "error", "dry_run"]
ErrorKind = Literal["none", "unreachable", "auth", "other"]


class ProfilePlanRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str
    zone: str | None = None
    current_profile_id: str | None = None
    current_revision: int | None = None
    candidate_profile_id: str
    candidate_revision: int
    action: DeployAction
    reachable: bool
    ok: bool = True
    error: str | None = None
    error_kind: ErrorKind = "none"
    idempotency_key: str | None = None


class ProfilePushResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str
    result: DeployResultName
    active_profile: str | None = None
    ok: bool
    error: str | None = None
    error_kind: ErrorKind = "none"
    idempotency_key: str | None = None


def current_label(row: ProfilePlanRow) -> str:
    if not row.reachable:
        return "unknown"
    if not row.current_profile_id:
        return "none"
    if row.current_revision is None:
        return row.current_profile_id
    return f"{row.current_profile_id} r{row.current_revision}"


def candidate_label(row: ProfilePlanRow) -> str:
    return f"{row.candidate_profile_id} r{row.candidate_revision}"
