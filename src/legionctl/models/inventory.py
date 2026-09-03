from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from legionctl.constants import INVENTORY_SCHEMA_VERSION


class SentinelNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str = Field(min_length=1)
    display_name: str | None = None
    zone: str | None = None
    hostname: str | None = None
    base_url: str = Field(min_length=1)
    last_known_ip: str | None = None
    api_version: str = "v1"
    firmware_version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    enabled: bool = True
    last_seen_utc: datetime | None = None


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str = Field(min_length=1)
    description: str = ""
    members: list[str] = Field(default_factory=list)


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=INVENTORY_SCHEMA_VERSION, ge=1)
    nodes: list[SentinelNode] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)

    def node_by_id(self, sentinel_id: str) -> SentinelNode | None:
        for node in self.nodes:
            if node.sentinel_id == sentinel_id:
                return node
        return None

    def group_by_name(self, name: str) -> Group | None:
        for group in self.groups:
            if group.group == name:
                return group
        return None
