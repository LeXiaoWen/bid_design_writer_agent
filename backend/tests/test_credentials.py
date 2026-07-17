import json
import logging
import sqlite3
import stat
import sys

import pytest

from backend.services.logging_config import JsonFormatter, redact_log_text
from backend.services.auth import _hash_token, logout_token
from backend.services.workbench_store import CredentialVaultLocked, WorkbenchStore, data_dir, restrict_file_permissions, utc_now


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
    store.change_user_password_and_rotate_credential_vault(user.id, "test-password", "new-password", "new-password-hash")
    store.lock_credential_vault(user.id)
    store.unlock_credential_vault(user.id, "new-password")
    assert store.get_credential(user.id, credential_name) == secret


def test_password_change_rolls_back_vault_when_password_hash_update_fails(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path / "password-change.db")
    user = store.create_user("password-change-user", "old-password-hash")
    credential_name = f"provider:{user.id}:profile"
    store.unlock_credential_vault(user.id, "old-password")
    store.set_credential(user.id, credential_name, "vault-secret-value")
    before_vault = store._execute("SELECT salt FROM credential_vaults WHERE user_id = ?", (user.id,)).fetchone()
    before_credential = store._execute(
        "SELECT nonce, ciphertext FROM encrypted_credentials WHERE user_id = ? AND credential_key = ?",
        (user.id, credential_name),
    ).fetchone()
    original_execute = store._execute

    def fail_password_hash_update(sql, params=()):
        if "UPDATE users SET password_hash" in sql:
            raise sqlite3.OperationalError("simulated write failure")
        return original_execute(sql, params)

    monkeypatch.setattr(store, "_execute", fail_password_hash_update)
    with pytest.raises(sqlite3.OperationalError, match="simulated write failure"):
        store.change_user_password_and_rotate_credential_vault(user.id, "old-password", "new-password", "new-password-hash")

    after_vault = original_execute("SELECT salt FROM credential_vaults WHERE user_id = ?", (user.id,)).fetchone()
    after_credential = original_execute(
        "SELECT nonce, ciphertext FROM encrypted_credentials WHERE user_id = ? AND credential_key = ?",
        (user.id, credential_name),
    ).fetchone()
    assert bytes(after_vault["salt"]) == bytes(before_vault["salt"])
    assert bytes(after_credential["nonce"]) == bytes(before_credential["nonce"])
    assert bytes(after_credential["ciphertext"]) == bytes(before_credential["ciphertext"])
    assert original_execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()["password_hash"] == "old-password-hash"


def test_legacy_secret_migration_keeps_plaintext_when_vault_write_fails(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path / "legacy-secret.db")
    user = store.create_user("legacy-secret-user", "password-hash")
    profile_id = "legacy-profile"
    now = utc_now()
    with store._lock, store._connection:
        store._execute(
            """
            INSERT INTO provider_profiles (id, owner_user_id, provider, display_name, base_url, model, credential_key, has_key, api_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (profile_id, user.id, "OpenAI", "旧配置", "https://api.openai.com/v1", "gpt-4o", "legacy-key", 1, "legacy-secret", now, now),
        )
    store.unlock_credential_vault(user.id, "password")
    original_execute = store._execute

    def fail_credential_insert(sql, params=()):
        if "INSERT INTO encrypted_credentials" in sql:
            raise sqlite3.OperationalError("simulated vault write failure")
        return original_execute(sql, params)

    monkeypatch.setattr(store, "_execute", fail_credential_insert)
    with pytest.raises(sqlite3.OperationalError, match="simulated vault write failure"):
        store.migrate_legacy_secrets_on_login(user.id, "password")

    row = original_execute("SELECT api_key, credential_key FROM provider_profiles WHERE id = ?", (profile_id,)).fetchone()
    assert row["api_key"] == "legacy-secret"
    assert row["credential_key"] == "legacy-key"
    assert original_execute("SELECT 1 FROM encrypted_credentials WHERE user_id = ?", (user.id,)).fetchone() is None


def test_successful_legacy_secret_migration_removes_recovery_backup(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.workbench_store.data_dir", lambda: tmp_path / "data")
    store = WorkbenchStore(tmp_path / "legacy-success.db")
    user = store.create_user("legacy-success-user", "password-hash")
    now = utc_now()
    with store._lock, store._connection:
        store._execute(
            """
            INSERT INTO provider_profiles (id, owner_user_id, provider, display_name, base_url, model, credential_key, has_key, api_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-success-profile", user.id, "OpenAI", "旧配置", "https://api.openai.com/v1", "gpt-4o", "legacy-key", 1, "legacy-secret", now, now),
        )
    store.unlock_credential_vault(user.id, "password")

    store.migrate_legacy_secrets_on_login(user.id, "password")

    assert store._recovery_backup_paths(user.id) == []


def test_password_change_removes_legacy_recovery_backups(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.workbench_store.data_dir", lambda: tmp_path / "data")
    store = WorkbenchStore(tmp_path / "password-backup.db")
    user = store.create_user("password-backup-user", "old-password-hash")
    store.unlock_credential_vault(user.id, "old-password")
    store._write_recovery_backup(user.id, "old-password", {"provider:legacy": "legacy-secret"})

    store.change_user_password_and_rotate_credential_vault(user.id, "old-password", "new-password", "new-password-hash")

    assert store._recovery_backup_paths(user.id) == []


def test_credential_restore_rolls_back_when_profile_update_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.services.workbench_store.data_dir", lambda: tmp_path / "data")
    store = WorkbenchStore(tmp_path / "restore.db")
    user = store.create_user("restore-user", "password-hash")
    profile_id = "restore-profile"
    now = utc_now()
    with store._lock, store._connection:
        store._execute(
            """
            INSERT INTO provider_profiles (id, owner_user_id, provider, display_name, base_url, model, credential_key, has_key, api_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (profile_id, user.id, "OpenAI", "待恢复配置", "https://api.openai.com/v1", "gpt-4o", "old-key", 0, None, now, now),
        )
    store.unlock_credential_vault(user.id, "password")
    store._write_recovery_backup(user.id, "password", {f"provider:{profile_id}": "restore-secret"})
    original_execute = store._execute

    def fail_profile_update(sql, params=()):
        if "UPDATE provider_profiles SET credential_key" in sql:
            raise sqlite3.OperationalError("simulated profile update failure")
        return original_execute(sql, params)

    monkeypatch.setattr(store, "_execute", fail_profile_update)
    with pytest.raises(sqlite3.OperationalError, match="simulated profile update failure"):
        store.restore_latest_legacy_secrets(user.id, "password")

    profile = original_execute("SELECT credential_key, has_key FROM provider_profiles WHERE id = ?", (profile_id,)).fetchone()
    assert profile["credential_key"] == "old-key"
    assert profile["has_key"] == 0
    assert original_execute("SELECT 1 FROM encrypted_credentials WHERE user_id = ?", (user.id,)).fetchone() is None
    assert store._recovery_backup_paths(user.id)


def test_sensitive_local_data_paths_have_private_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_WORKBENCH_DATA_DIR", str(tmp_path / "data"))
    directory = data_dir()
    directory.chmod(0o755)
    assert stat.S_IMODE(data_dir().stat().st_mode) == 0o700

    store = WorkbenchStore(directory / "app.db")
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    report = directory / "report.md"
    report.write_text("private report", encoding="utf-8")
    restrict_file_permissions(report)
    assert stat.S_IMODE(report.stat().st_mode) == 0o600


def test_logout_locks_the_vault_even_when_another_session_remains(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path / "logout.db")
    user = store.create_user("logout-user", "password-hash")
    store.unlock_credential_vault(user.id, "password")
    token = "logout-token"
    stale_token = "stale-token"
    store.create_auth_session(user.id, _hash_token(token), "2099-01-01T00:00:00+00:00")
    store.create_auth_session(user.id, _hash_token(stale_token), "2099-01-01T00:00:00+00:00")

    monkeypatch.setattr("backend.services.auth.workbench_store", store)
    logout_token(token)

    assert not store.credential_vault_is_unlocked(user.id)


def test_expired_auth_sessions_are_pruned_without_touching_active_sessions(tmp_path):
    store = WorkbenchStore(tmp_path / "sessions.db")
    user = store.create_user("session-user", "password-hash")
    with store._lock, store._connection:
        store._execute(
            "INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
            ("expired-session", user.id, "expired-token", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
        )
    with store._lock, store._connection:
        store._execute(
            "INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
            ("active-session", user.id, "active-token", "2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"),
        )

    removed = store.prune_expired_auth_sessions("2026-01-01T00:00:00+00:00")

    assert removed == 1
    assert store._execute("SELECT token_hash FROM auth_sessions").fetchone()["token_hash"] == "active-token"


def test_new_auth_session_prunes_expired_sessions(tmp_path):
    store = WorkbenchStore(tmp_path / "login-sessions.db")
    user = store.create_user("login-session-user", "password-hash")
    store.create_auth_session(user.id, "expired-token", "2020-01-01T00:00:00+00:00")

    store.create_auth_session(user.id, "new-token", "2099-01-01T00:00:00+00:00")

    assert store._execute("SELECT token_hash FROM auth_sessions").fetchone()["token_hash"] == "new-token"


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
