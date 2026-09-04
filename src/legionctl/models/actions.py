from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ActionResultName = Literal["accepted", "dry_run", "unreachable", "error"]
ErrorKind = Literal["none", "unreachable", "auth", "other"]


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str
    ok: bool
    result: ActionResultName
    error: str | None = None
    error_kind: ErrorKind = "none"
    delivery: str | None = None
    queued: bool | None = None
    technology: str | None = None
    duration_seconds: int | None = None
    timestamp_utc: str | None = None
