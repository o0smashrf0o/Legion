from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.errors import ConfirmationDeclined, UsageError
from legionctl.models.inventory import Inventory, SentinelNode
from legionctl.services.actions import validate_scan_request
from legionctl.services.credentials import CredentialStore
from legionctl.services.inventory import save_inventory
from legionctl.settings import LegionPaths

runner = CliRunner()
TOKEN = "super-secret-token"
NORTH = "sentinel-north-door-01"
HALL = "sentinel-hall-b-01"


def _node(sentinel_id: str, zone: str) -> SentinelNode:
    return SentinelNode(
        sentinel_id=sentinel_id,
        display_name=zone,
        zone=zone,
        hostname=f"{sentinel_id}.local",
        base_url=f"https://{sentinel_id}.local",
    )


@pytest.fixture
def ops_home(legion_home: LegionPaths) -> LegionPaths:
    save_inventory(Inventory(nodes=[_node(NORTH, "North Door"), _node(HALL, "Hall B")]))
    store = CredentialStore()
    store.set_token(NORTH, TOKEN)
    store.set_token(HALL, TOKEN)
    return legion_home


def test_validate_scan_duration() -> None:
    validate_scan_request("ble", 30, 300)
    with pytest.raises(UsageError, match="<= 300"):
        validate_scan_request("ble", 301, 300)


def test_scan_requires_duration_and_rejects_over_max(ops_home: LegionPaths) -> None:
    missing = runner.invoke(app, ["scan", "--node", NORTH, "--technology", "ble", "--yes"])
    assert missing.exit_code != 0
    result = runner.invoke(
        app,
        ["scan", "--node", NORTH, "--technology", "ble", "--duration", "301", "--yes"],
    )
    assert result.exit_code == 1
    assert "300" in result.output


def test_test_alert_success_audit_and_no_retry(
    ops_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/test-alert").mock(
        return_value=httpx.Response(
            200,
            json={
                "accepted": True,
                "queued": False,
                "delivery": "success",
                "timestamp_utc": "2026-09-03T22:32:00Z",
            },
        )
    )
    result = runner.invoke(app, ["--json", "test-alert", "--node", NORTH, "--yes"])
    assert result.exit_code == 0, result.output
    assert '"result": "accepted"' in result.stdout
    assert TOKEN not in result.output
    assert route.call_count == 1
    audit = ops_home.audit_log.read_text(encoding="utf-8")
    assert '"operation": "test_alert"' in audit
    assert '"confirmed_with_yes": true' in audit
    assert TOKEN not in audit
    assert "webhook" not in audit.lower()


def test_test_alert_timeout_is_not_retried(
    ops_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/test-alert").mock(
        side_effect=httpx.ReadTimeout("read timeout")
    )
    result = runner.invoke(app, ["test-alert", "--node", NORTH, "--yes"])
    assert result.exit_code == 2
    assert route.call_count == 1


def test_dry_run_does_not_write(ops_home: LegionPaths, respx_mock: respx.MockRouter) -> None:
    alert = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/test-alert").mock(
        return_value=httpx.Response(
            200,
            json={
                "accepted": True,
                "queued": False,
                "delivery": "ok",
                "timestamp_utc": "2026-09-03T22:32:00Z",
            },
        )
    )
    scan = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/scan").mock(
        return_value=httpx.Response(200, json={"accepted": True})
    )
    reboot = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/reboot").mock(
        return_value=httpx.Response(200, json={"accepted": True})
    )
    for args in (
        ["--dry-run", "test-alert", "--node", NORTH],
        ["--dry-run", "scan", "--node", NORTH, "--technology", "ble", "--duration", "30"],
        ["--dry-run", "reboot", "--node", NORTH],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    assert alert.call_count == 0
    assert scan.call_count == 0
    assert reboot.call_count == 0
    audit = ops_home.audit_log.read_text(encoding="utf-8")
    assert audit.count('"dry_run": true') >= 3


def test_confirmation_required(
    ops_home: LegionPaths, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/reboot").mock(
        return_value=httpx.Response(200, json={"accepted": True})
    )

    def decline(_prompt: str, *, yes: bool, ask: object = None) -> None:
        raise ConfirmationDeclined("confirmation declined")

    monkeypatch.setattr("legionctl.commands.actions.confirm_or_decline", decline)
    result = runner.invoke(app, ["reboot", "--node", NORTH])
    assert result.exit_code == 4
    assert route.call_count == 0
    assert NORTH in result.output or "sentinel-north-door-01" in result.output


def test_reboot_all_requires_force_all(ops_home: LegionPaths) -> None:
    result = runner.invoke(app, ["reboot", "--all", "--yes"])
    assert result.exit_code == 1
    assert "force-all" in result.output


def test_reboot_all_force_all(
    ops_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    north = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/reboot").mock(
        return_value=httpx.Response(200, json={"accepted": True})
    )
    hall = respx_mock.post(f"https://{HALL}.local/api/v1/commands/reboot").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    result = runner.invoke(app, ["--json", "reboot", "--all", "--force-all", "--yes"])
    assert result.exit_code == 2, result.output
    assert north.call_count == 1
    assert hall.call_count == 1
    assert TOKEN not in result.output


def test_scan_success_no_retry(ops_home: LegionPaths, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"https://{NORTH}.local/api/v1/commands/scan").mock(
        side_effect=httpx.ReadTimeout("read timeout")
    )
    result = runner.invoke(
        app,
        ["scan", "--node", NORTH, "--technology", "ble", "--duration", "30", "--yes"],
    )
    assert result.exit_code == 2
    assert route.call_count == 1


def test_credential_set_check_delete(
    ops_home: LegionPaths, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    help_result = runner.invoke(app, ["credential", "set", "--help"])
    assert "--token-stdin" in help_result.stdout
    assert "--token TEXT" not in help_result.stdout

    store = CredentialStore()
    store.delete_token(NORTH)
    set_result = runner.invoke(
        app, ["credential", "set", NORTH, "--token-stdin"], input=f"{TOKEN}\n"
    )
    assert set_result.exit_code == 0, set_result.output
    assert TOKEN not in set_result.output
    assert store.get_token(NORTH) == TOKEN

    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "api_version": "v1",
                "sentinel_id": NORTH,
                "firmware_version": "0.1.0",
            },
        )
    )
    check = runner.invoke(app, ["credential", "check", NORTH])
    assert check.exit_code == 0, check.output
    assert TOKEN not in check.output

    def decline(_prompt: str, *, yes: bool, ask: object = None) -> None:
        raise ConfirmationDeclined("confirmation declined")

    monkeypatch.setattr("legionctl.commands.credential.confirm_or_decline", decline)
    declined = runner.invoke(app, ["credential", "delete", NORTH])
    assert declined.exit_code == 4
    assert store.get_token(NORTH) == TOKEN

    monkeypatch.setattr("legionctl.commands.credential.confirm_or_decline", lambda *a, **k: None)
    deleted = runner.invoke(app, ["credential", "delete", NORTH, "--yes"])
    assert deleted.exit_code == 0
    assert store.get_token(NORTH) is None
    assert TOKEN not in deleted.output
    audit = ops_home.audit_log.read_text(encoding="utf-8")
    assert TOKEN not in audit
    assert "credential_delete" in audit
