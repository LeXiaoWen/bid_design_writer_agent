import json
import logging
import sys

import pytest

from backend.services.logging_config import JsonFormatter, redact_log_text
from backend.services.auth import _hash_token, logout_token
from backend.services.workbench_store import CredentialVaultLocked, WorkbenchStore


def test_local_credential_vault_encrypts_secrets_and_requires_unlock(tmp_path):
    store = WorkbenchStore(tmp_path / "vault.db")
    user = store.create_user("vault-user", "password-hash")
    credential_name = f"provider:{user.id}:profile"
    secret = "vault-secret-value"

    store.unlock_credential_vault(user.id, "test-password")
    store.set_credential(user.id, credential_name, secret)
    row = store._execute("SELECT nonce, ciphertext FROM encrypted_credentials WHERE user_id = ?", (user.id,)).fetchone()
    assert secret.encode("utf-8") not in bytes(row["ciphertext"])
    assert bytes(row["nonce"])

    store.lock_credential_vault(user.id)
    with pytest.raises(CredentialVaultLocked):
        store.get_credential(user.id, credential_name)

    store.unlock_credential_vault(user.id, "test-password")
    assert store.get_credential(user.id, credential_name) == secret
    store.rotate_credential_vault(user.id, "test-password", "new-password")
    store.lock_credential_vault(user.id)
    store.unlock_credential_vault(user.id, "new-password")
    assert store.get_credential(user.id, credential_name) == secret


def test_logout_locks_the_vault_after_its_last_session(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path / "logout.db")
    user = store.create_user("logout-user", "password-hash")
    store.unlock_credential_vault(user.id, "password")
    token = "logout-token"
    store.create_auth_session(user.id, _hash_token(token), "2099-01-01T00:00:00+00:00")

    monkeypatch.setattr("backend.services.auth.workbench_store", store)
    logout_token(token)

    assert not store.credential_vault_is_unlocked(user.id)


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


def test_redact_log_text_handles_json_and_authorization_values():
    secret = "sk-json-secret-1234567890"
    redacted = redact_log_text(f'{{"api_key":"{secret}"}} Authorization: Bearer {secret}')
    assert secret not in redacted
    assert "已脱敏" in redacted
