from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from legionctl.models.inventory import SentinelNode


class MdnsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    server: str | None = None
    port: int = 443
    addresses: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)


class DiscoveredService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentinel_id: str = Field(min_length=1)
    hostname: str | None = None
    ip: str | None = None
    port: int = 443
    base_url: str = Field(min_length=1)
    zone: str | None = None
    display_name: str | None = None
    firmware_version: str | None = None
    api_version: str | None = None
    profile_id: str | None = None
    profile_revision: int | None = None
    reachable: bool | None = None
    known: bool = False

    def to_inventory_node(self) -> SentinelNode:
        return SentinelNode(
            sentinel_id=self.sentinel_id,
            display_name=self.display_name,
            zone=self.zone,
            hostname=self.hostname,
            base_url=self.base_url,
            last_known_ip=self.ip,
            api_version=self.api_version or "v1",
            firmware_version=self.firmware_version,
        )


class DiscoveryIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["duplicate_id", "inconsistent_hostname"]
    sentinel_id: str
    message: str
    hostnames: list[str] = Field(default_factory=list)


class DiscoveryCache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_utc: datetime
    records: list[DiscoveredService] = Field(default_factory=list)
