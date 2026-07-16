from backend.services.credentials import KeyringCredentialStore


def test_keyring_store_caches_credential_reads(monkeypatch):
    class FakeKeyring:
        def __init__(self):
            self.values = {"provider:user:profile": "secret"}
            self.get_calls = 0

        def get_password(self, service_name: str, key: str) -> str | None:
            assert service_name == "bid-design-writer-desktop"
            self.get_calls += 1
            return self.values.get(key)

        def set_password(self, service_name: str, key: str, value: str) -> None:
            self.values[key] = value

        def delete_password(self, service_name: str, key: str) -> None:
            self.values.pop(key, None)

    keyring = FakeKeyring()
    store = KeyringCredentialStore()
    monkeypatch.setattr(store, "_keyring", lambda: (keyring, (RuntimeError,)))

    assert store.get("provider:user:profile") == "secret"
    assert store.get("provider:user:profile") == "secret"
    assert keyring.get_calls == 1

    store.set("provider:user:profile", "updated-secret")
    assert store.get("provider:user:profile") == "updated-secret"
    assert keyring.get_calls == 1

    store.delete("provider:user:profile")
    assert store.get("provider:user:profile") is None
    assert keyring.get_calls == 2
