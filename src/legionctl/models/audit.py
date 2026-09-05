from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_utc: datetime
    operation: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    targets: list[str] = Field(default_factory=list)
    profile_id: str | None = None
    profile_revision: int | None = Field(default=None, ge=1)
    dry_run: bool = False
    confirmed_with_yes: bool = False
    result: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("timestamp_utc")
    def _serialize_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            utc = value.replace(microsecond=0)
        else:
            utc = value.astimezone(datetime.timezone.utc).replace(microsecond=0)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
