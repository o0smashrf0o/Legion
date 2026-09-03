from __future__ import annotations

import getpass
from datetime import UTC, datetime
from typing import Any

from legionctl.models.audit import AuditRecord
from legionctl.redaction import redact_any
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import append_jsonl


def utc_now() -> datetime:
    return datetime.now(UTC)


def current_operator() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def build_audit_record(
    operation: str,
    *,
    targets: list[str] | None = None,
    result: str,
    profile_id: str | None = None,
    profile_revision: int | None = None,
    dry_run: bool = False,
    confirmed_with_yes: bool = False,
    details: dict[str, Any] | None = None,
    operator: str | None = None,
    timestamp_utc: datetime | None = None,
) -> AuditRecord:
    safe_details = redact_any(details or {})
    if not isinstance(safe_details, dict):
        safe_details = {}
    return AuditRecord(
        timestamp_utc=timestamp_utc or utc_now(),
        operation=operation,
        operator=operator or current_operator(),
        targets=list(targets or []),
        profile_id=profile_id,
        profile_revision=profile_revision,
        dry_run=dry_run,
        confirmed_with_yes=confirmed_with_yes,
        result=result,
        details=safe_details,
    )


def write_audit_record(record: AuditRecord, paths: LegionPaths | None = None) -> None:
    resolved = paths or get_paths()
    append_jsonl(resolved.audit_log, record.model_dump(mode="json"))
