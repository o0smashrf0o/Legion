from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.errors import ConfirmationDeclined
from legionctl.models.inventory import Group, Inventory, SentinelNode
from legionctl.services.credentials import CredentialStore
from legionctl.services.inventory import save_inventory
from legionctl.services.profiles import import_profile
from legionctl.settings import LegionPaths

runner = CliRunner()
TOKEN = "super-secret-token"
NORTH = "sentinel-north-door-01"
HALL = "sentinel-hall-b-01"
GARAGE = "sentinel-garage-01"


def _node(sentinel_id: str, zone: str) -> SentinelNode:
    return SentinelNode(
        sentinel_id=sentinel_id,
        display_name=zone,
        zone=zone,
        hostname=f"{sentinel_id}.local",
        base_url=f"https://{sentinel_id}.local",
    )


def _info(
    sentinel_id: str, revision: int | None, profile_id: str | None = "event-alpha"
) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "sentinel_id": sentinel_id,
        "zone": "North Door",
        "firmware_version": "0.1.0",
        "profile_id": profile_id,
        "profile_revision": revision,
        "uptime_seconds": 1,
    }


def _activated(revision: int = 4) -> dict[str, Any]:
    return {
        "status": "activated",
        "profile_id": "event-alpha",
        "revision": revision,
        "activation_timestamp_utc": "2026-09-03T22:31:00Z",
    }


@pytest.fixture
def deployed_home(legion_home: LegionPaths, example_profile_path: Path) -> LegionPaths:
    save_inventory(
        Inventory(
            nodes=[
                _node(NORTH, "North Door"),
                _node(HALL, "Hall B"),
                _node(GARAGE, "Garage"),
            ],
            groups=[Group(group="event-alpha", members=[NORTH, HALL, GARAGE])],
        )
    )
    store = CredentialStore()
    for sentinel_id in (NORTH, HALL, GARAGE):
        store.set_token(sentinel_id, TOKEN)
    import_profile(example_profile_path)
    return legion_home


def test_invalid_profile_makes_no_network_calls(
    deployed_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    path = deployed_home.profiles_dir / "event-alpha.json"
    path.write_text("{not-json", encoding="utf-8")
    result = runner.invoke(app, ["profile", "push", "event-alpha", "--all", "--yes"])
    assert result.exit_code == 1
    assert respx_mock.calls.call_count == 0


def test_revision_downgrade_rejected(
    deployed_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, 5))
    )
    put_route = respx_mock.put(f"https://{NORTH}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    result = runner.invoke(app, ["profile", "push", "event-alpha", "--node", NORTH, "--yes"])
    assert result.exit_code == 1, result.output
    assert "allow-downgrade" in result.output
    assert put_route.call_count == 0


def test_dry_run_never_writes(
    deployed_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, 3))
    )
    put_route = respx_mock.put(f"https://{NORTH}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    result = runner.invoke(
        app, ["--dry-run", "--json", "profile", "push", "event-alpha", "--node", NORTH]
    )
    assert result.exit_code == 0, result.output
    assert '"dry_run": true' in result.stdout
    assert put_route.call_count == 0
    audit = deployed_home.audit_log.read_text(encoding="utf-8")
    assert '"dry_run": true' in audit
    assert TOKEN not in audit


def test_confirmation_required(
    deployed_home: LegionPaths,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, 3))
    )
    put_route = respx_mock.put(f"https://{NORTH}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )

    def decline(_prompt: str, *, yes: bool, ask: object = None) -> None:
        raise ConfirmationDeclined("confirmation declined")

    monkeypatch.setattr("legionctl.commands.profile.confirm_or_decline", decline)
    result = runner.invoke(app, ["profile", "push", "event-alpha", "--node", NORTH])
    assert result.exit_code == 4
    assert put_route.call_count == 0


def test_yes_logged_and_idempotency_per_node(
    deployed_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, 3))
    )
    respx_mock.get(f"https://{HALL}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(HALL, 4))
    )
    respx_mock.get(f"https://{GARAGE}.local/api/v1/info").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    north_put = respx_mock.put(f"https://{NORTH}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    hall_put = respx_mock.put(f"https://{HALL}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    garage_put = respx_mock.put(f"https://{GARAGE}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    result = runner.invoke(
        app, ["--json", "profile", "push", "event-alpha", "--group", "event-alpha", "--yes"]
    )
    assert result.exit_code == 2, result.output
    assert north_put.call_count == 1
    assert hall_put.call_count == 0
    assert garage_put.call_count == 0
    key = north_put.calls[0].request.headers["Idempotency-Key"]
    assert key
    assert TOKEN not in result.output
    audit = deployed_home.audit_log.read_text(encoding="utf-8")
    assert '"confirmed_with_yes": true' in audit
    assert '"operation": "profile_push"' in audit
    assert TOKEN not in audit
    assert "webhook" not in audit.lower()
    assert NORTH in audit


def test_two_nodes_get_distinct_idempotency_keys(
    deployed_home: LegionPaths, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(f"https://{NORTH}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(NORTH, None, None))
    )
    respx_mock.get(f"https://{HALL}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(HALL, 3))
    )
    respx_mock.get(f"https://{GARAGE}.local/api/v1/info").mock(
        return_value=httpx.Response(200, json=_info(GARAGE, 4))
    )
    north_put = respx_mock.put(f"https://{NORTH}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    hall_put = respx_mock.put(f"https://{HALL}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    garage_put = respx_mock.put(f"https://{GARAGE}.local/api/v1/rules").mock(
        return_value=httpx.Response(200, json=_activated())
    )
    result = runner.invoke(
        app, ["profile", "push", "event-alpha", "--group", "event-alpha", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert north_put.call_count == 1
    assert hall_put.call_count == 1
    assert garage_put.call_count == 0
    north_key = north_put.calls[0].request.headers["Idempotency-Key"]
    hall_key = hall_put.calls[0].request.headers["Idempotency-Key"]
    assert north_key
    assert hall_key
    assert north_key != hall_key


def test_profile_lifecycle_cli(deployed_home: LegionPaths, tmp_path: Path) -> None:
    listed = runner.invoke(app, ["--json", "profile", "list"])
    assert listed.exit_code == 0
    assert '"profile_id": "event-alpha"' in listed.stdout
    shown = runner.invoke(app, ["profile", "show", "event-alpha"])
    assert shown.exit_code == 0
    cloned = runner.invoke(app, ["profile", "clone", "event-alpha", "event-alpha-r5"])
    assert cloned.exit_code == 0
    exported = runner.invoke(
        app,
        ["profile", "export", "event-alpha-r5", "--output", str(tmp_path / "out.json")],
    )
    assert exported.exit_code == 0
    created = runner.invoke(app, ["profile", "create", "fresh-profile"])
    assert created.exit_code == 0
    help_result = runner.invoke(app, ["profile", "--help"])
    assert "push" in help_result.stdout
    assert "diff" in help_result.stdout
    assert "import" in help_result.stdout
