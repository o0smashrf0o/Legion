from __future__ import annotations

import pytest
from typer.testing import CliRunner

from legionctl.cli import app
from legionctl.models.discovery import DiscoveredService
from legionctl.models.inventory import Inventory, SentinelNode
from legionctl.services.credentials import CredentialStore
from legionctl.services.inventory import get_node, load_inventory, save_inventory
from legionctl.settings import LegionPaths

runner = CliRunner()


def _seed_node(legion_home: LegionPaths) -> None:
    save_inventory(
        Inventory(
            nodes=[
                SentinelNode(
                    sentinel_id="sentinel-north-door-01",
                    display_name="North Door",
                    zone="North Door",
                    hostname="sentinel-north-door-01.local",
                    base_url="https://sentinel-north-door-01.local",
                    last_known_ip="192.168.50.41",
                )
            ]
        )
    )


def test_node_add_token_stdin_not_argument(legion_home: LegionPaths) -> None:
    result = runner.invoke(
        app,
        [
            "node",
            "add",
            "--id",
            "sentinel-north-door-01",
            "--url",
            "https://192.168.50.41",
            "--zone",
            "North Door",
            "--token-stdin",
        ],
        input="super-secret-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "super-secret-token" not in result.output
    node = get_node("sentinel-north-door-01")
    assert node.base_url == "https://192.168.50.41"
    store = CredentialStore()
    assert store.get_token("sentinel-north-door-01") == "super-secret-token"
    inventory_text = legion_home.inventory_file.read_text(encoding="utf-8")
    assert "super-secret-token" not in inventory_text
    audit = legion_home.audit_log.read_text(encoding="utf-8")
    assert "super-secret-token" not in audit
    assert "node_add" in audit

    rejected = runner.invoke(
        app,
        [
            "node",
            "add",
            "--id",
            "other",
            "--url",
            "https://192.168.50.42",
            "--token",
            "super-secret-token",
        ],
    )
    assert rejected.exit_code != 0
    help_result = runner.invoke(app, ["node", "add", "--help"])
    assert "--token-stdin" in help_result.stdout
    assert "--from-keyring" in help_result.stdout
    assert "--token TEXT" not in help_result.stdout


def test_node_show_and_rename(legion_home: LegionPaths) -> None:
    _seed_node(legion_home)
    shown = runner.invoke(app, ["--json", "node", "show", "sentinel-north-door-01"])
    assert shown.exit_code == 0
    assert '"sentinel_id": "sentinel-north-door-01"' in shown.stdout
    assert "token" not in shown.stdout.lower()
    renamed = runner.invoke(
        app,
        [
            "node",
            "rename",
            "sentinel-north-door-01",
            "--display-name",
            "North Door West",
            "--zone",
            "North",
        ],
    )
    assert renamed.exit_code == 0
    node = get_node("sentinel-north-door-01")
    assert node.display_name == "North Door West"
    assert node.zone == "North"


def test_node_remove_requires_confirmation(legion_home: LegionPaths) -> None:
    _seed_node(legion_home)
    declined = runner.invoke(app, ["node", "remove", "sentinel-north-door-01"], input="n\n")
    assert declined.exit_code == 4
    assert get_node("sentinel-north-door-01").sentinel_id == "sentinel-north-door-01"
    removed = runner.invoke(app, ["node", "remove", "sentinel-north-door-01", "--yes"])
    assert removed.exit_code == 0
    inventory = load_inventory()
    assert inventory.nodes == []
    audit = legion_home.audit_log.read_text(encoding="utf-8")
    assert "node_remove" in audit
    assert '"confirmed_with_yes": true' in audit


def test_group_commands_are_local_only(
    legion_home: LegionPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_node(legion_home)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("group commands must not contact Sentinel nodes")

    monkeypatch.setattr("legionctl.clients.sentinel_api.SentinelApiClient.__init__", boom)
    created = runner.invoke(
        app,
        ["group", "create", "event-alpha", "--description", "Event Alpha deployment"],
    )
    added = runner.invoke(app, ["group", "add-member", "event-alpha", "sentinel-north-door-01"])
    listed = runner.invoke(app, ["--json", "group", "list"])
    removed = runner.invoke(
        app, ["group", "remove-member", "event-alpha", "sentinel-north-door-01"]
    )
    assert created.exit_code == 0, created.output
    assert added.exit_code == 0, added.output
    assert listed.exit_code == 0
    assert '"group": "event-alpha"' in listed.stdout
    assert removed.exit_code == 0
    assert "token" not in listed.stdout.lower()


def test_discover_uses_mdns_double(
    legion_home: LegionPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = DiscoveredService(
        sentinel_id="sentinel-north-door-01",
        hostname="sentinel-north-door-01.local",
        ip="192.168.50.41",
        port=443,
        base_url="https://sentinel-north-door-01.local",
        zone="North Door",
        firmware_version="0.1.0",
        profile_id="event-alpha",
        profile_revision=4,
        reachable=True,
        known=False,
    )

    def fake_discover(
        *_args: object, **_kwargs: object
    ) -> tuple[list[DiscoveredService], list[object]]:
        return [record], []

    monkeypatch.setattr("legionctl.commands.discover.discover_sentinels", fake_discover)
    result = runner.invoke(app, ["--json", "discover"])
    assert result.exit_code == 0, result.output
    assert '"sentinel_id": "sentinel-north-door-01"' in result.stdout
    assert "token" not in result.stdout.lower()
    assert "webhook" not in result.stdout.lower()
    cache = legion_home.discovery_cache.read_text(encoding="utf-8")
    assert "sentinel-north-door-01" in cache

    added = runner.invoke(
        app,
        ["discover", "--add", "--yes", "--token-stdin"],
        input="super-secret-token\n",
    )
    assert added.exit_code == 0, added.output
    assert "super-secret-token" not in added.output
    node = get_node("sentinel-north-door-01")
    assert node.zone == "North Door"
    assert CredentialStore().get_token("sentinel-north-door-01") == "super-secret-token"
