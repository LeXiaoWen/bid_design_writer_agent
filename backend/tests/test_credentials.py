import json
import logging
import sys

from backend.services.credentials import KeyringCredentialStore
from backend.services.logging_config import JsonFormatter


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


def test_json_logs_redact_managed_credentials_from_messages_and_exceptions():
    formatter = JsonFormatter()
    logger = logging.getLogger("bid-design-writer-test")
    secret = "sk-log-secret-1234567890"

    try:
        raise RuntimeError(f"Bearer {secret}")
    except RuntimeError:
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            __file__,
            1,
            "模型请求失败 api_key=%s",
            (secret,),
            sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))
    assert secret not in json.dumps(payload, ensure_ascii=False)
    assert payload["message"] == "模型请求失败 api_key=[已脱敏]"
    assert "Bearer [已脱敏]" in payload["exception"]
