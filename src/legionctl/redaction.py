from __future__ import annotations

import logging
import re
from typing import Any

_BEARER_RE = re.compile(r"(?i)(bearer)\s+\S+")
_WEBHOOK_RE = re.compile(
    r"https?://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\S+",
    re.IGNORECASE,
)
_SECRET_KV_RE = re.compile(
    r"(?i)\b(token|password|secret|webhook(?:_url)?|wifi_password|"
    r"discord_webhook(?:_url)?)\s*[:=]\s*\S+"
)
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*:\s*)(?!Bearer\b)\S+")
_SECRET_KEYS = frozenset(
    {
        "token",
        "password",
        "secret",
        "authorization",
        "webhook",
        "webhook_url",
        "wifi_password",
        "discord_webhook",
        "discord_webhook_url",
        "bearer",
        "api_token",
        "access_token",
    }
)


def redact_secrets(value: str) -> str:
    """Remove credentials and webhook URLs from a string."""
    redacted = _BEARER_RE.sub(r"\1 [REDACTED]", value)
    redacted = _WEBHOOK_RE.sub("https://discord.com/api/webhooks/[REDACTED]", redacted)
    redacted = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SECRET_KEYS or lowered.endswith("_token") or lowered.endswith("_password")


def redact_any(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_secret_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_any(item)
        return redacted
    if isinstance(value, list):
        return [redact_any(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_any(item) for item in value)
    return value


class SecretRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact_secrets(message)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        return True


def setup_logging(*, verbose: bool = False, debug: bool = False) -> None:
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("legionctl")
    root.handlers.clear()
    root.addHandler(handler)
    root.addFilter(SecretRedactFilter())
    root.setLevel(level)
    root.propagate = False
