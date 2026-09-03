from __future__ import annotations

import logging

from legionctl.redaction import SecretRedactFilter, redact_secrets


def test_redact_bearer_and_webhook() -> None:
    text = (
        "Authorization: Bearer abcdef123456 "
        "https://discord.com/api/webhooks/123/secret-token "
        "token=plaintext-token password=wifi-secret"
    )
    redacted = redact_secrets(text)
    assert "abcdef123456" not in redacted
    assert "secret-token" not in redacted
    assert "plaintext-token" not in redacted
    assert "wifi-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_logging_filter_redacts_interpolated_message() -> None:
    record = logging.LogRecord(
        name="legionctl",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer %s",
        args=("super-secret-token",),
        exc_info=None,
    )
    assert SecretRedactFilter().filter(record)
    formatted = record.getMessage()
    assert "super-secret-token" not in formatted
    assert "Bearer [REDACTED]" in formatted
