from __future__ import annotations

from legionctl.services.credentials import CredentialStore, EncryptedFileTokenStore
from legionctl.settings import LegionPaths


class MemoryStore:
    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def set_token(self, sentinel_id: str, token: str) -> None:
        self._tokens[sentinel_id] = token

    def get_token(self, sentinel_id: str) -> str | None:
        return self._tokens.get(sentinel_id)

    def delete_token(self, sentinel_id: str) -> None:
        self._tokens.pop(sentinel_id, None)


def test_memory_store_round_trip(legion_home: LegionPaths) -> None:
    store = CredentialStore(legion_home, store=MemoryStore())
    store.set_token("sentinel-north-door-01", "super-secret-token")
    assert store.has_token("sentinel-north-door-01")
    assert store.get_token("sentinel-north-door-01") == "super-secret-token"
    store.delete_token("sentinel-north-door-01")
    assert store.get_token("sentinel-north-door-01") is None


def test_encrypted_file_store_does_not_write_plaintext(legion_home: LegionPaths) -> None:
    backend = EncryptedFileTokenStore(legion_home)
    store = CredentialStore(legion_home, store=backend)
    store.set_token("sentinel-north-door-01", "super-secret-token")
    assert store.get_token("sentinel-north-door-01") == "super-secret-token"
    raw = legion_home.credential_store_file.read_text(encoding="utf-8")
    assert "super-secret-token" not in raw
    inventory = legion_home.inventory_file
    if inventory.exists():
        assert "super-secret-token" not in inventory.read_text(encoding="utf-8")
