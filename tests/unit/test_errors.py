from __future__ import annotations

from legionctl.errors import (
    AuthenticationError,
    ConfirmationDeclined,
    NodeConflictError,
    NodeUnreachableError,
    NodeValidationError,
    SentinelApiError,
    exit_code_for,
    map_http_status,
)
from legionctl.output.console import confirm_or_decline


def test_http_status_mapping() -> None:
    assert isinstance(map_http_status(401), AuthenticationError)
    assert isinstance(map_http_status(403), AuthenticationError)
    assert isinstance(map_http_status(409), NodeConflictError)
    assert isinstance(map_http_status(422), NodeValidationError)
    assert isinstance(map_http_status(500), SentinelApiError)
    assert exit_code_for(AuthenticationError("no")) == 3
    assert exit_code_for(NodeUnreachableError("down")) == 2
    assert exit_code_for(ConfirmationDeclined("no")) == 4


def test_confirmation_yes_skips_prompt() -> None:
    confirm_or_decline("Deploy?", yes=True, ask=lambda _prompt: False)


def test_confirmation_decline() -> None:
    try:
        confirm_or_decline("Deploy?", yes=False, ask=lambda _prompt: False)
    except ConfirmationDeclined:
        return
    raise AssertionError("expected ConfirmationDeclined")
