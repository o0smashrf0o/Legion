from __future__ import annotations

from datetime import UTC, datetime

from legionctl.services.audit import build_audit_record, write_audit_record
from legionctl.settings import LegionPaths


def test_audit_record_generation_and_secret_redaction(legion_home: LegionPaths) -> None:
    record = build_audit_record(
        "profile_push",
        targets=["sentinel-north-door-01"],
        result="success",
        profile_id="event-alpha",
        profile_revision=4,
        dry_run=False,
        confirmed_with_yes=True,
        details={
            "activated": ["sentinel-north-door-01"],
            "failed": [],
            "token": "super-secret-token",
        },
        operator="tester",
        timestamp_utc=datetime(2026, 9, 3, 22, 45, tzinfo=UTC),
    )
    dumped = record.model_dump(mode="json")
    assert dumped["timestamp_utc"] == "2026-09-03T22:45:00Z"
    assert dumped["operation"] == "profile_push"
    assert dumped["confirmed_with_yes"] is True
    assert dumped["details"]["token"] == "[REDACTED]"
    assert "super-secret-token" not in str(dumped)

    write_audit_record(record)
    written = legion_home.audit_log.read_text(encoding="utf-8")
    assert "super-secret-token" not in written
    assert "profile_push" in written
    assert written.endswith("\n")
