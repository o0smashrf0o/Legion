from __future__ import annotations

from pathlib import Path

import pytest

from legionctl.errors import UsageError
from legionctl.services.profiles import (
    clone_profile,
    create_profile,
    export_profile,
    import_profile,
    list_installed_profiles,
    load_installed_profile,
)
from legionctl.settings import LegionPaths


def test_create_import_clone_export(legion_home: LegionPaths, example_profile_path: Path) -> None:
    created = create_profile("skeleton", description="template")
    assert created.revision == 1
    assert created.rules == []
    listed = list_installed_profiles()
    assert [item.profile_id for item in listed] == ["skeleton"]

    imported = import_profile(example_profile_path)
    assert imported.profile_id == "event-alpha"
    assert imported.revision == 4
    with pytest.raises(UsageError, match="already exists"):
        import_profile(example_profile_path)

    cloned = clone_profile("event-alpha", "event-alpha-r5")
    assert cloned.profile_id == "event-alpha-r5"
    assert cloned.revision == 1
    assert len(cloned.rules) == 3

    dest = legion_home.config_dir / "out.json"
    export_profile("event-alpha", dest)
    raw = dest.read_text(encoding="utf-8")
    assert "event-alpha" in raw
    assert "token" not in raw.lower()
    assert "webhook" not in raw.lower()
    assert load_installed_profile("event-alpha").profile_id == "event-alpha"


def test_create_rejects_path_profile_id(legion_home: LegionPaths) -> None:
    with pytest.raises(UsageError, match="path separators"):
        create_profile("../escape")
