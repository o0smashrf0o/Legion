from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ZoneType = Literal["physical", "logical", "mission"]
OrgStatus = Literal["active", "inactive"]
CohortReadiness = Literal[
    "nominal",
    "understrength",
    "reinforced",
    "degraded",
    "inactive",
    "unassigned",
]
ZoneCoverage = Literal["unstaffed", "partial", "covered", "degraded", "inactive"]
SentinelPresence = Literal["online", "degraded", "offline", "dormant", "unknown"]


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    zone_type: ZoneType = "physical"
    status: OrgStatus = "active"
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class Cohort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    zone_id: str | None = None
    status: OrgStatus = "active"
    sentinel_ids: list[str] = Field(default_factory=list)
    primus_sentinel_id: str | None = None
    mission_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
