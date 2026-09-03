from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.models.inventory import Group, Inventory, SentinelNode
from legionctl.services.inventory import save_inventory
from legionctl.settings import LegionPaths

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "legionctl" in result.stdout
    assert "profile" in result.stdout
    assert "node" in result.stdout
    assert "group" in result.stdout


def test_profile_validate_example(example_profile_path: Path) -> None:
    result = runner.invoke(app, ["profile", "validate", str(example_profile_path)])
    assert result.exit_code == 0
    assert "event-alpha" in result.stdout
    assert "revision 4" in result.stdout
    assert "Rules: 3" in result.stdout


def test_profile_validate_invalid_exits_1(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["profile", "validate", str(path)])
    assert result.exit_code == 1
    assert "validation failed" in result.output.lower() or "failed" in result.output.lower()


def test_profile_validate_json(example_profile_path: Path) -> None:
    result = runner.invoke(app, ["--json", "profile", "validate", str(example_profile_path)])
    assert result.exit_code == 0
    assert '"valid": true' in result.stdout
    assert '"profile_id": "event-alpha"' in result.stdout


def test_node_and_group_list_empty(legion_home: LegionPaths) -> None:
    nodes = runner.invoke(app, ["node", "list"])
    groups = runner.invoke(app, ["group", "list"])
    assert nodes.exit_code == 0
    assert groups.exit_code == 0
    assert "No Sentinel nodes" in nodes.stdout
    assert "No Sentinel groups" in groups.stdout


def test_node_and_group_list_populated(legion_home: LegionPaths) -> None:
    save_inventory(
        Inventory(
            nodes=[
                SentinelNode(
                    sentinel_id="sentinel-north-door-01",
                    display_name="North Door",
                    zone="North Door",
                    hostname="sentinel-north-door-01.local",
                    base_url="https://sentinel-north-door-01.local",
                    groups=["event-alpha"],
                )
            ],
            groups=[
                Group(
                    group="event-alpha",
                    description="Event Alpha deployment",
                    members=["sentinel-north-door-01"],
                )
            ],
        )
    )
    human = runner.invoke(app, ["node", "list"])
    assert human.exit_code == 0
    assert "Sentinel inventory" in human.stdout

    json_nodes = runner.invoke(app, ["--json", "node", "list"])
    assert json_nodes.exit_code == 0
    assert '"sentinel_id": "sentinel-north-door-01"' in json_nodes.stdout
    json_groups = runner.invoke(app, ["--json", "group", "list"])
    assert json_groups.exit_code == 0
    assert '"group": "event-alpha"' in json_groups.stdout
