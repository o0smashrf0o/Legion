from __future__ import annotations

import getpass
import json
from datetime import UTC, datetime
from typing import Any

from legionctl.models.audit import AuditRecord
from legionctl.redaction import redact_any
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import append_jsonl


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        utc = value.replace(microsecond=0)
    else:
        utc = value.astimezone(UTC).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def read_recent_audit(limit: int = 20, paths: LegionPaths | None = None) -> list[dict[str, Any]]:
    resolved = paths or get_paths()
    if not resolved.audit_log.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in reversed(resolved.audit_log.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
        if len(records) >= limit:
            break
    return records
