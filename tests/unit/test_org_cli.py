from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.errors import ConfirmationDeclined
from legionctl.models.inventory import Inventory, SentinelNode
from legionctl.services.inventory import save_inventory
from legionctl.settings import LegionPaths

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

runner = CliRunner()


def test_fleet_hierarchy_cli(legion_home: LegionPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    save_inventory(
        Inventory(
            nodes=[
                SentinelNode(
                    sentinel_id="sentinel-north-01",
                    hostname="sentinel-north-01.local",
                    base_url="https://sentinel-north-01.local",
                ),
                SentinelNode(
                    sentinel_id="sentinel-north-02",
                    hostname="sentinel-north-02.local",
                    base_url="https://sentinel-north-02.local",
                ),
            ]
        )
    )
    created = runner.invoke(app, ["zone", "create", "--name", "North Entry", "--yes"])
    assert created.exit_code == 0, created.output
    cohort = runner.invoke(
        app,
        [
            "cohort",
            "create",
            "--id",
            "cohort-north-entry-01",
            "--name",
            "North Entry Cohort 01",
            "--yes",
        ],
    )
    assert cohort.exit_code == 0, cohort.output
    assigned = runner.invoke(
        app, ["cohort", "assign-zone", "cohort-north-entry-01", "north-entry", "--yes"]
    )
    assert assigned.exit_code == 0, assigned.output
    added = runner.invoke(
        app, ["cohort", "add-sentinel", "cohort-north-entry-01", "sentinel-north-01", "--yes"]
    )
    assert added.exit_code == 0, added.output
    added2 = runner.invoke(
        app, ["cohort", "add-sentinel", "cohort-north-entry-01", "sentinel-north-02", "--yes"]
    )
    assert added2.exit_code == 0, added2.output
    primus = runner.invoke(
        app, ["cohort", "set-primus", "cohort-north-entry-01", "sentinel-north-02", "--yes"]
    )
    assert primus.exit_code == 0, primus.output
    shown = runner.invoke(app, ["--json", "sentinel", "assignment", "sentinel-north-02"])
    assert shown.exit_code == 0
    assert '"role": "Primus"' in shown.stdout

    def decline(_prompt: str, *, yes: bool, ask: object = None) -> None:
        raise ConfirmationDeclined("confirmation declined")

    monkeypatch.setattr("legionctl.commands.zone.confirm_or_decline", decline)
    declined = runner.invoke(app, ["zone", "archive", "north-entry"])
    assert declined.exit_code == 4
    dry = runner.invoke(app, ["--dry-run", "zone", "archive", "north-entry", "--yes"])
    assert dry.exit_code == 0
    audit = legion_home.audit_log.read_text(encoding="utf-8")
    assert "cohort_set_primus" in audit
    assert "super-secret" not in audit
    fleet = runner.invoke(app, ["fleet", "status"])
    assert fleet.exit_code == 0
    assert "FLEET" in fleet.stdout


def test_gui_api_requires_confirm(legion_home: LegionPaths) -> None:
    pytest.importorskip("flask")
    from gui.app import app as flask_app

    client = flask_app.test_client()
    response = client.post("/api/zones", json={"name": "North Entry"})
    assert response.status_code == 400
    assert b"confirmation required" in response.data
