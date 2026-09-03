from __future__ import annotations

from pathlib import Path

import pytest

from legionctl.settings import LegionPaths, get_paths


@pytest.fixture
def legion_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LegionPaths:
    config = tmp_path / "config"
    data = tmp_path / "data"
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    return get_paths()


@pytest.fixture
def example_profile_path() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "examples" / "event-alpha.json"
