from __future__ import annotations

import os
from threading import RLock


class CredentialStoreUnavailable(RuntimeError):
    """The operating system credential service cannot safely store a secret."""


class CredentialStore:
    def get(self, key: str) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class KeyringCredentialStore(CredentialStore):
    service_name = "bid-design-writer-desktop"

    def _keyring(self):
        try:
            import keyring
            from keyring.errors import KeyringError, NoKeyringError
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise CredentialStoreUnavailable("系统凭据库组件未安装。") from exc
        return keyring, (KeyringError, NoKeyringError)

    def get(self, key: str) -> str | None:
        keyring, errors = self._keyring()
        try:
            return keyring.get_password(self.service_name, key)
        except errors as exc:
            raise CredentialStoreUnavailable("系统凭据库不可用，请启用 Keychain、Credential Manager 或 Secret Service。") from exc

    def set(self, key: str, value: str) -> None:
        keyring, errors = self._keyring()
        try:
            keyring.set_password(self.service_name, key, value)
        except errors as exc:
            raise CredentialStoreUnavailable("系统凭据库不可用，未保存密钥。") from exc

    def delete(self, key: str) -> None:
        keyring, errors = self._keyring()
        try:
            keyring.delete_password(self.service_name, key)
        except errors as exc:
            # A missing entry is already the desired result; other errors are actionable.
            if exc.__class__.__name__ != "PasswordDeleteError":
                raise CredentialStoreUnavailable("系统凭据库不可用，未能删除密钥。") from exc


class MemoryCredentialStore(CredentialStore):
    """Only enabled by the test suite; production never falls back to memory."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)


credential_store: CredentialStore = MemoryCredentialStore() if os.getenv("AI_WORKBENCH_TEST_CREDENTIALS") == "1" else KeyringCredentialStore()
