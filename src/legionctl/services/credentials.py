from __future__ import annotations

import getpass
import json
import os
import sys
from collections.abc import Callable
from typing import Protocol, TextIO

from cryptography.fernet import Fernet, InvalidToken

from legionctl.constants import KEYRING_SERVICE
from legionctl.errors import CredentialError
from legionctl.settings import LegionPaths, get_paths
from legionctl.storage import atomic_write_text

try:
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
except Exception:  # pragma: no cover - import guard
    keyring = None  # type: ignore[assignment]
    KeyringError = Exception  # type: ignore[misc,assignment]
    NoKeyringError = Exception  # type: ignore[misc,assignment]


class TokenStore(Protocol):
    def set_token(self, sentinel_id: str, token: str) -> None: ...
    def get_token(self, sentinel_id: str) -> str | None: ...
    def delete_token(self, sentinel_id: str) -> None: ...


class KeyringTokenStore:
    def set_token(self, sentinel_id: str, token: str) -> None:
        if keyring is None:
            raise CredentialError("system keyring is unavailable")
        try:
            keyring.set_password(KEYRING_SERVICE, sentinel_id, token)
        except (KeyringError, NoKeyringError) as exc:
            raise CredentialError("system keyring is unavailable") from exc

    def get_token(self, sentinel_id: str) -> str | None:
        if keyring is None:
            raise CredentialError("system keyring is unavailable")
        try:
            return keyring.get_password(KEYRING_SERVICE, sentinel_id)
        except (KeyringError, NoKeyringError) as exc:
            raise CredentialError("system keyring is unavailable") from exc

    def delete_token(self, sentinel_id: str) -> None:
        if keyring is None:
            raise CredentialError("system keyring is unavailable")
        try:
            keyring.delete_password(KEYRING_SERVICE, sentinel_id)
        except Exception as exc:
            if exc.__class__.__name__ == "PasswordDeleteError":
                return
            raise CredentialError("system keyring is unavailable") from exc


class EncryptedFileTokenStore:
    def __init__(self, paths: LegionPaths) -> None:
        self._paths = paths

    def set_token(self, sentinel_id: str, token: str) -> None:
        payload = self._load()
        payload[sentinel_id] = token
        self._save(payload)

    def get_token(self, sentinel_id: str) -> str | None:
        return self._load().get(sentinel_id)

    def delete_token(self, sentinel_id: str) -> None:
        payload = self._load()
        if sentinel_id in payload:
            del payload[sentinel_id]
            self._save(payload)

    def _fernet(self) -> Fernet:
        key_path = self._paths.credential_key_file
        if key_path.exists():
            key = key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
        return Fernet(key)

    def _load(self) -> dict[str, str]:
        store_path = self._paths.credential_store_file
        if not store_path.exists():
            return {}
        try:
            decrypted = self._fernet().decrypt(store_path.read_bytes())
            payload = json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError, OSError) as exc:
            raise CredentialError("encrypted credential store is unreadable") from exc
        if not isinstance(payload, dict):
            raise CredentialError("encrypted credential store is unreadable")
        return {str(key): str(value) for key, value in payload.items()}

    def _save(self, payload: dict[str, str]) -> None:
        token = self._fernet().encrypt(json.dumps(payload).encode("utf-8"))
        atomic_write_text(
            self._paths.credential_store_file,
            token.decode("utf-8"),
            mode=0o600,
        )


def keyring_available() -> bool:
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    name = type(backend).__name__.lower()
    module = type(backend).__module__.lower()
    if "fail" in name or "fail" in module:
        return False
    if "null" in name:
        return False
    return True


class CredentialStore:
    def __init__(
        self,
        paths: LegionPaths | None = None,
        *,
        store: TokenStore | None = None,
    ) -> None:
        self._paths = paths or get_paths()
        if store is not None:
            self._store = store
        elif keyring_available():
            self._store = KeyringTokenStore()
        else:
            self._store = EncryptedFileTokenStore(self._paths)

    def set_token(self, sentinel_id: str, token: str) -> None:
        if not sentinel_id:
            raise CredentialError("sentinel_id is required")
        if not token:
            raise CredentialError("token must not be empty")
        self._store.set_token(sentinel_id, token)

    def get_token(self, sentinel_id: str) -> str | None:
        return self._store.get_token(sentinel_id)

    def delete_token(self, sentinel_id: str) -> None:
        self._store.delete_token(sentinel_id)

    def has_token(self, sentinel_id: str) -> bool:
        token = self.get_token(sentinel_id)
        return bool(token)


def read_bearer_token(
    sentinel_id: str,
    *,
    token_stdin: bool = False,
    from_keyring: bool = False,
    credentials: CredentialStore | None = None,
    stdin: TextIO | None = None,
    prompt: Callable[[str], str] | None = None,
) -> str:
    if token_stdin and from_keyring:
        raise CredentialError("use only one of --token-stdin or --from-keyring")
    if from_keyring:
        store = credentials or CredentialStore()
        token = store.get_token(sentinel_id)
        if not token:
            raise CredentialError(f"no bearer token stored for {sentinel_id}")
        return token
    if token_stdin:
        handle = stdin if stdin is not None else sys.stdin
        token = handle.readline().strip()
    else:
        reader = prompt or getpass.getpass
        token = reader(f"Bearer token for {sentinel_id}: ").strip()
    if not token:
        raise CredentialError("token must not be empty")
    return token
