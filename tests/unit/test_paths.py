from __future__ import annotations

from legionctl.settings import LegionPaths, get_paths, load_settings, save_settings


def test_xdg_path_resolution(legion_home: LegionPaths) -> None:
    paths = get_paths()
    assert paths.config_dir.name == "legion"
    assert paths.inventory_file.name == "inventory.json"
    assert paths.audit_log.name == "audit.jsonl"
    assert paths.config_dir == legion_home.config_dir
    assert paths.data_dir == legion_home.data_dir
    assert paths.state_dir == legion_home.state_dir


def test_settings_round_trip(legion_home: LegionPaths) -> None:
    settings = load_settings()
    assert settings.concurrency == 5
    settings.concurrency = 8
    save_settings(settings)
    reloaded = load_settings()
    assert reloaded.concurrency == 8
