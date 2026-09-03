from __future__ import annotations


class LegionError(Exception):
    """Base error for Legion CLI and services."""

    exit_code = 1


class UsageError(LegionError):
    exit_code = 1


class ValidationFailed(LegionError):
    exit_code = 1

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "validation failed")


class NoTargetsError(LegionError):
    exit_code = 1


class TargetNotFoundError(LegionError):
    exit_code = 1


class InventoryError(LegionError):
    exit_code = 1


class CredentialError(LegionError):
    exit_code = 3


class AuthenticationError(LegionError):
    exit_code = 3


class TlsError(LegionError):
    exit_code = 3


class NodeUnreachableError(LegionError):
    exit_code = 2


class SentinelApiError(LegionError):
    exit_code = 1


class NodeConflictError(SentinelApiError):
    exit_code = 1


class NodeValidationError(SentinelApiError):
    exit_code = 1


class ConfirmationDeclined(LegionError):
    exit_code = 4


def map_http_status(status_code: int, message: str = "") -> LegionError:
    """Map a Sentinel HTTP status code to a Legion error.

    Response bodies must already be redacted by the caller. `message` must not
    contain bearer tokens, Wi-Fi credentials, or Discord webhook URLs.
    """
    text = message.strip() if message else f"HTTP {status_code}"
    if status_code in {401, 403}:
        return AuthenticationError(text)
    if status_code == 404:
        return SentinelApiError(text)
    if status_code == 409:
        return NodeConflictError(text)
    if status_code == 422:
        return NodeValidationError(text)
    if status_code >= 500:
        return SentinelApiError(text)
    return SentinelApiError(text)


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, LegionError):
        return exc.exit_code
    return 1
