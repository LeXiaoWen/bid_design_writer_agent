from __future__ import annotations

import json
import os
import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Optional
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..schemas import (
    ArtifactInfo,
    AuthUser,
    BidExecutionState,
    BidWorkflowExecution,
    BidWorkflow,
    BidWorkflowStatus,
    ProviderProfile,
    ProviderProfileCreate,
    ProviderProfileUpdate,
    SearchResult,
    WebSearchConfig,
    WebSearchConfigUpdate,
    WorkbenchConversation,
    WorkbenchConversationCreate,
    WorkbenchConversationUpdate,
    WorkbenchMessage,
    WorkbenchProject,
    WorkbenchProjectCreate,
    WorkbenchProjectUpdate,
)
from .credentials import CredentialStoreUnavailable, credential_store
from .artifacts import markdown_line_diff
DEFAULT_PROJECT_TITLE = "默认项目"
MULTI_TENANT_SCHEMA_VERSION = 3
SCHEMA_VERSION = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def data_dir() -> Path:
    raw = os.getenv("AI_WORKBENCH_DATA_DIR")
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path.cwd() / ".data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    raw = os.getenv("AI_WORKBENCH_DB_PATH")
    if raw:
        path = Path(raw).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return data_dir() / "app.db"


class WorkbenchStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._backup_legacy_database_if_needed()
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    workspace_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    provider_profile_id TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT,
                    finish_reason TEXT,
                    usage_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_profiles (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    credential_key TEXT NOT NULL UNIQUE,
                    has_key INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bid_workflows (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    provider_profile_id TEXT REFERENCES provider_profiles(id) ON DELETE SET NULL,
                    file_name TEXT NOT NULL,
                    file_text TEXT NOT NULL,
                    extracted_markdown TEXT NOT NULL DEFAULT '',
                    confirmation_text TEXT NOT NULL DEFAULT '',
                    template_choice TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bid_artifacts (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES bid_workflows(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    path TEXT,
                    content TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bid_artifact_versions (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES bid_workflows(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(workflow_id, name, version)
                );

                CREATE TABLE IF NOT EXISTS bid_jobs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES bid_workflows(id) ON DELETE CASCADE,
                    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(workflow_id, kind)
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );

                CREATE INDEX IF NOT EXISTS idx_bid_workflows_conversation_status
                ON bid_workflows(conversation_id, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_bid_jobs_next ON bid_jobs(state, created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                    owner_user_id UNINDEXED,
                    kind,
                    source_id,
                    project_id,
                    conversation_id,
                    title,
                    content
                );
                """
            )
            self._migrate_schema()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, tuple(params))

    def _ensure_column(self, table: str, column: str, declaration: str) -> bool:
        columns = {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            return True
        return False

    def _migrate_schema(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        migrations = {
            1: self._migrate_to_v1,
            2: self._migrate_to_v2,
            3: self._migrate_to_v3,
            4: self._migrate_to_v4,
            5: self._migrate_to_v5,
        }
        while version < SCHEMA_VERSION:
            target_version = version + 1
            migrations[target_version]()
            self._connection.execute(f"PRAGMA user_version = {target_version}")
            version = target_version

    def _migrate_to_v1(self) -> None:
        self._ensure_column("projects", "workspace_path", "TEXT")

    def _migrate_to_v2(self) -> None:
        provider_has_key_added = self._ensure_column("provider_profiles", "has_key", "INTEGER NOT NULL DEFAULT 0")
        if provider_has_key_added:
            self._connection.execute("UPDATE provider_profiles SET has_key = 1")
        self._ensure_column("provider_profiles", "api_key", "TEXT")

    def _migrate_to_v3(self) -> None:
        self._ensure_column("projects", "owner_user_id", "TEXT")
        self._ensure_column("provider_profiles", "owner_user_id", "TEXT")
        self._connection.execute("DROP INDEX IF EXISTS idx_single_user")
        owner = self._execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
        if owner:
            owner_user_id = owner["id"]
            self._execute("UPDATE projects SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner_user_id,))
            self._execute("UPDATE provider_profiles SET owner_user_id = ? WHERE owner_user_id IS NULL", (owner_user_id,))
            self._migrate_legacy_credentials(owner_user_id)
        self._rebuild_search_index()

    def _migrate_to_v4(self) -> None:
        self._ensure_column("conversations", "context_summary", "TEXT NOT NULL DEFAULT ''")

    def _migrate_to_v5(self) -> None:
        self._connection.execute("DROP INDEX IF EXISTS idx_active_bid_workflows_per_conversation")
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_bid_workflows_conversation_status ON bid_workflows(conversation_id, status, updated_at DESC)"
        )

    def _backup_legacy_database_if_needed(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        has_existing_schema = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name IN ('users', 'projects') LIMIT 1"
        ).fetchone()
        backup_path = self.path.with_suffix(f"{self.path.suffix}.pre-multitenant.bak")
        if version >= MULTI_TENANT_SCHEMA_VERSION or not has_existing_schema or backup_path.exists():
            return
        backup = sqlite3.connect(backup_path)
        try:
            self._connection.backup(backup)
        finally:
            backup.close()

    def _migrate_legacy_credentials(self, user_id: str) -> None:
        profiles = self._execute("SELECT id, api_key FROM provider_profiles WHERE owner_user_id = ?", (user_id,)).fetchall()
        for profile in profiles:
            self._execute(
                "UPDATE provider_profiles SET credential_key = ?, has_key = ? WHERE id = ?",
                (f"db:{profile['id']}", 1 if profile["api_key"] else 0, profile["id"]),
            )
        tavily_key = self.get_setting("web_search.api_key")
        if tavily_key:
            self.set_user_setting(user_id, "web_search.api_key", tavily_key)
            self.set_user_setting(user_id, "web_search.has_key", "1")
            self._execute("DELETE FROM app_settings WHERE key IN ('web_search.api_key', 'web_search.has_key')")
        for key in ("web_search.max_results", "web_search.search_depth"):
            value = self.get_setting(key)
            if value is not None:
                self.set_user_setting(user_id, key, value)

    def migrate_legacy_secrets_on_login(self, user_id: str, password: str) -> None:
        """Move pre-v0.2 plaintext data to the OS vault and erase it from SQLite.

        A password-encrypted recovery blob is written before any destructive operation so
        a user can import it later if their desktop credential service was unavailable.
        """
        profiles = self._execute(
            "SELECT id, credential_key, api_key FROM provider_profiles WHERE owner_user_id = ? AND api_key IS NOT NULL AND api_key != ''",
            (user_id,),
        ).fetchall()
        tavily_key = self.get_user_setting(user_id, "web_search.api_key") or ""
        secrets_to_migrate = {
            **{f"provider:{row['id']}": row["api_key"] for row in profiles},
            **({"tavily": tavily_key} if tavily_key else {}),
        }
        if not secrets_to_migrate:
            return

        self._write_recovery_backup(user_id, password, secrets_to_migrate)
        try:
            for row in profiles:
                key = f"provider:{user_id}:{row['id']}"
                credential_store.set(key, row["api_key"])
                self._execute("UPDATE provider_profiles SET credential_key = ?, has_key = 1 WHERE id = ?", (key, row["id"]))
            if tavily_key:
                credential_store.set(self._tavily_credential_key(user_id), tavily_key)
        finally:
            # The runtime must never continue consuming plaintext data after v0.2.
            with self._lock, self._connection:
                self._execute("UPDATE provider_profiles SET api_key = NULL WHERE owner_user_id = ?", (user_id,))
                self.set_user_setting(user_id, "web_search.api_key", "")
                self.set_user_setting(user_id, "web_search.has_key", "1" if tavily_key else "0")

    def _write_recovery_backup(self, user_id: str, password: str, values: dict[str, str]) -> Path:
        salt = os.urandom(16)
        nonce = os.urandom(12)
        kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
        key = kdf.derive(password.encode("utf-8"))
        encrypted = AESGCM(key).encrypt(nonce, json.dumps(values, ensure_ascii=False).encode("utf-8"), user_id.encode("utf-8"))
        recovery_dir = data_dir() / "credential-recovery"
        recovery_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = recovery_dir / f"{user_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.json.enc"
        payload = {"version": 1, "user_id": user_id, "salt": urlsafe_b64encode(salt).decode(), "nonce": urlsafe_b64encode(nonce).decode(), "ciphertext": urlsafe_b64encode(encrypted).decode()}
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        target.chmod(0o600)
        return target

    def restore_latest_legacy_secrets(self, user_id: str, password: str) -> int:
        recovery_dir = data_dir() / "credential-recovery"
        candidates = sorted(recovery_dir.glob(f"{user_id}-*.json.enc"), reverse=True) if recovery_dir.exists() else []
        if not candidates:
            raise ValueError("未找到可恢复的旧密钥备份。")
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
        if payload.get("user_id") != user_id:
            raise ValueError("旧密钥备份与当前账号不匹配。")
        salt = urlsafe_b64decode(payload["salt"])
        nonce = urlsafe_b64decode(payload["nonce"])
        ciphertext = urlsafe_b64decode(payload["ciphertext"])
        try:
            key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))
            values = json.loads(AESGCM(key).decrypt(nonce, ciphertext, user_id.encode("utf-8")))
        except Exception as exc:
            raise ValueError("恢复密码错误或备份文件已损坏。") from exc
        restored = 0
        for name, secret in values.items():
            if name == "tavily":
                credential_store.set(self._tavily_credential_key(user_id), secret)
                self.set_user_setting(user_id, "web_search.has_key", "1")
                restored += 1
                continue
            if not name.startswith("provider:"):
                continue
            profile_id = name.removeprefix("provider:")
            row = self._execute("SELECT id FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
            if not row:
                continue
            credential_key = f"provider:{user_id}:{profile_id}"
            credential_store.set(credential_key, secret)
            self._execute("UPDATE provider_profiles SET credential_key = ?, has_key = 1, api_key = NULL WHERE id = ?", (credential_key, profile_id))
            restored += 1
        return restored

    def _rebuild_search_index(self) -> None:
        self._connection.execute("DROP TABLE IF EXISTS search_index")
        self._connection.execute(
            """
            CREATE VIRTUAL TABLE search_index USING fts5(
                owner_user_id UNINDEXED,
                kind,
                source_id,
                project_id,
                conversation_id,
                title,
                content
            )
            """
        )
        projects = self._execute("SELECT id, owner_user_id, title, workspace_path FROM projects WHERE owner_user_id IS NOT NULL").fetchall()
        for project in projects:
            self._upsert_search(project["owner_user_id"], "project", project["id"], project["id"], None, project["title"], f"{project['title']}\n{project['workspace_path'] or ''}".strip())
        conversations = self._execute(
            """
            SELECT conversations.*, projects.owner_user_id
            FROM conversations JOIN projects ON projects.id = conversations.project_id
            WHERE projects.owner_user_id IS NOT NULL
            """
        ).fetchall()
        for conversation in conversations:
            self._upsert_search(conversation["owner_user_id"], "conversation", conversation["id"], conversation["project_id"], conversation["id"], conversation["title"], conversation["title"])
        messages = self._execute(
            """
            SELECT messages.*, conversations.project_id, projects.owner_user_id
            FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            JOIN projects ON projects.id = conversations.project_id
            WHERE projects.owner_user_id IS NOT NULL
            """
        ).fetchall()
        for message in messages:
            self._upsert_search(message["owner_user_id"], "message", message["id"], message["project_id"], message["conversation_id"], message["role"], message["content"])

    def ensure_default_project(self, user_id: str) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects WHERE owner_user_id = ? ORDER BY created_at LIMIT 1", (user_id,)).fetchone()
        if row:
            return self._project_from_row(row)
        return self.create_project(user_id, WorkbenchProjectCreate(title=DEFAULT_PROJECT_TITLE))

    def list_projects(self, user_id: str) -> list[WorkbenchProject]:
        rows = self._execute("SELECT * FROM projects WHERE owner_user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._project_from_row(row) for row in rows]

    def create_project(self, user_id: str, request: WorkbenchProjectCreate) -> WorkbenchProject:
        project_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or DEFAULT_PROJECT_TITLE
        workspace_path = request.workspace_path.strip() if request.workspace_path else None
        with self._lock, self._connection:
            self._execute(
                "INSERT INTO projects (id, owner_user_id, title, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, user_id, title, workspace_path, now, now),
            )
            search_content = f"{title}\n{workspace_path or ''}".strip()
            self._upsert_search(user_id, "project", project_id, project_id, None, title, search_content)
        return self.get_project(user_id, project_id)

    def has_user(self) -> bool:
        row = self._execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def create_user(self, username: str, password_hash: str) -> AuthUser:
        now = utc_now()
        user_id = str(uuid4())
        try:
            with self._lock, self._connection:
                self._execute(
                    """
                    INSERT INTO users (id, username, password_hash, created_at, updated_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (user_id, username.strip(), password_hash, now, now),
                )
                legacy_resources = self._execute(
                    "SELECT 1 FROM projects WHERE owner_user_id IS NULL UNION ALL SELECT 1 FROM provider_profiles WHERE owner_user_id IS NULL LIMIT 1"
                ).fetchone()
                if legacy_resources:
                    self._execute("UPDATE projects SET owner_user_id = ? WHERE owner_user_id IS NULL", (user_id,))
                    self._execute("UPDATE provider_profiles SET owner_user_id = ? WHERE owner_user_id IS NULL", (user_id,))
                    self._migrate_legacy_credentials(user_id)
                    self._rebuild_search_index()
                self.ensure_default_project(user_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在。") from exc
        return self.get_user(user_id)

    def get_first_user(self) -> AuthUser | None:
        row = self._execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
        return self._user_from_row(row) if row else None

    def get_user(self, user_id: str) -> AuthUser:
        row = self._execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError(user_id)
        return self._user_from_row(row)

    def get_user_auth_record_by_username(self, username: str) -> sqlite3.Row | None:
        return self._execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()

    def update_user_password_hash(self, user_id: str, password_hash: str) -> AuthUser:
        now = utc_now()
        with self._lock, self._connection:
            self._execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (password_hash, now, user_id))
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
        return self.get_user(user_id)

    def update_user_last_login(self, user_id: str) -> AuthUser:
        now = utc_now()
        with self._lock, self._connection:
            self._execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
        return self.get_user(user_id)

    def create_auth_session(self, user_id: str, token_hash: str, expires_at: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (str(uuid4()), user_id, token_hash, now, expires_at),
            )

    def get_auth_session_user(self, token_hash: str, now: str) -> AuthUser | None:
        row = self._execute(
            """
            SELECT users.*
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ?
              AND auth_sessions.revoked_at IS NULL
              AND auth_sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        return self._user_from_row(row) if row else None

    def revoke_auth_session(self, token_hash: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (now, token_hash))

    def get_project(self, user_id: str, project_id: str) -> WorkbenchProject:
        row = self._execute("SELECT * FROM projects WHERE id = ? AND owner_user_id = ?", (project_id, user_id)).fetchone()
        if not row:
            raise KeyError(project_id)
        return self._project_from_row(row)

    def update_project(self, user_id: str, project_id: str, request: WorkbenchProjectUpdate) -> WorkbenchProject:
        project = self.get_project(user_id, project_id)
        title = request.title.strip() if request.title is not None else project.title
        workspace_path = request.workspace_path.strip() if request.workspace_path is not None and request.workspace_path.strip() else project.workspace_path
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE projects SET title = ?, workspace_path = ?, updated_at = ? WHERE id = ? AND owner_user_id = ?",
                (title or project.title, workspace_path, now, project_id, user_id),
            )
            search_title = title or project.title
            search_content = f"{search_title}\n{workspace_path or ''}".strip()
            self._upsert_search(user_id, "project", project_id, project_id, None, search_title, search_content)
        return self.get_project(user_id, project_id)

    def delete_project(self, user_id: str, project_id: str) -> None:
        self.get_project(user_id, project_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM projects WHERE id = ? AND owner_user_id = ?", (project_id, user_id))
            self._execute("DELETE FROM search_index WHERE project_id = ? AND owner_user_id = ?", (project_id, user_id))
        self.ensure_default_project(user_id)

    def list_conversations(self, user_id: str, project_id: str | None = None) -> list[WorkbenchConversation]:
        if project_id:
            self.get_project(user_id, project_id)
            rows = self._execute("SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)).fetchall()
        else:
            rows = self._execute(
                """
                SELECT conversations.* FROM conversations
                JOIN projects ON projects.id = conversations.project_id
                WHERE projects.owner_user_id = ?
                ORDER BY conversations.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def create_conversation(self, user_id: str, request: WorkbenchConversationCreate) -> WorkbenchConversation:
        project_id = request.project_id or self.ensure_default_project(user_id).id
        self.get_project(user_id, project_id)
        conversation_id = str(uuid4())
        now = utc_now()
        title = request.title.strip() or "新对话"
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO conversations (id, project_id, title, provider_profile_id, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, project_id, title, request.provider_profile_id, request.model, now, now),
            )
            self._touch_project(project_id, now)
            self._upsert_search(user_id, "conversation", conversation_id, project_id, conversation_id, title, title)
        return self.get_conversation(user_id, conversation_id)

    def get_conversation(self, user_id: str, conversation_id: str) -> WorkbenchConversation:
        row = self._execute(
            """
            SELECT conversations.* FROM conversations
            JOIN projects ON projects.id = conversations.project_id
            WHERE conversations.id = ? AND projects.owner_user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(conversation_id)
        return self._conversation_from_row(row)

    def update_conversation(self, user_id: str, conversation_id: str, request: WorkbenchConversationUpdate) -> WorkbenchConversation:
        conversation = self.get_conversation(user_id, conversation_id)
        title = request.title.strip() if request.title is not None else conversation.title
        provider_profile_id = request.provider_profile_id if request.provider_profile_id is not None else conversation.provider_profile_id
        model = request.model if request.model is not None else conversation.model
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE conversations
                SET title = ?, provider_profile_id = ?, model = ?, updated_at = ?
                WHERE id = ?
                """,
                (title or conversation.title, provider_profile_id, model, now, conversation_id),
            )
            self._touch_project(conversation.project_id, now)
            self._upsert_search(
                user_id,
                "conversation",
                conversation_id,
                conversation.project_id,
                conversation_id,
                title or conversation.title,
                title or conversation.title,
            )
        return self.get_conversation(user_id, conversation_id)

    def get_context_summary(self, user_id: str, conversation_id: str) -> str:
        self.get_conversation(user_id, conversation_id)
        row = self._execute("SELECT context_summary FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return str(row["context_summary"] or "") if row else ""

    def set_context_summary(self, user_id: str, conversation_id: str, summary: str) -> None:
        conversation = self.get_conversation(user_id, conversation_id)
        with self._lock, self._connection:
            self._execute("UPDATE conversations SET context_summary = ?, updated_at = ? WHERE id = ?", (summary, utc_now(), conversation_id))
            self._touch_project(conversation.project_id)

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        conversation = self.get_conversation(user_id, conversation_id)
        with self._lock, self._connection:
            self._execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self._execute("DELETE FROM search_index WHERE conversation_id = ? AND owner_user_id = ?", (conversation_id, user_id))
            self._touch_project(conversation.project_id)

    def create_bid_workflow(
        self,
        user_id: str,
        conversation_id: str,
        file_name: str,
        file_text: str,
        provider_profile_id: str | None = None,
    ) -> BidWorkflow:
        conversation = self.get_conversation(user_id, conversation_id)
        if provider_profile_id:
            self.get_provider_profile(user_id, provider_profile_id)
        workflow_id = str(uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO bid_workflows
                    (id, project_id, conversation_id, provider_profile_id, file_name, file_text,
                     extracted_markdown, confirmation_text, template_choice, status, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, '', '', NULL, ?, NULL, ?, ?)
                """,
                (
                    workflow_id,
                    conversation.project_id,
                    conversation_id,
                    provider_profile_id,
                    file_name,
                    file_text,
                    BidWorkflowStatus.UPLOADED.value,
                    now,
                    now,
                ),
            )
            self._touch_conversation(conversation_id, now)
            self._touch_project(conversation.project_id, now)
        return self.get_bid_workflow(user_id, workflow_id)

    def get_bid_workflow(self, user_id: str, workflow_id: str) -> BidWorkflow:
        row = self._execute(
            """
            SELECT bid_workflows.* FROM bid_workflows
            JOIN projects ON projects.id = bid_workflows.project_id
            WHERE bid_workflows.id = ? AND projects.owner_user_id = ?
            """,
            (workflow_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(workflow_id)
        return self._workflow_from_row(user_id, row)

    def get_active_bid_workflow(self, user_id: str, conversation_id: str) -> BidWorkflow | None:
        self.get_conversation(user_id, conversation_id)
        row = self._execute(
            """
            SELECT * FROM bid_workflows
            WHERE conversation_id = ?
              AND status IN ('uploaded', 'extracting', 'extraction_ready', 'generating', 'failed')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        return self._workflow_from_row(user_id, row) if row else None

    def list_bid_workflows(self, user_id: str, conversation_id: str | None = None) -> list[BidWorkflow]:
        if conversation_id:
            self.get_conversation(user_id, conversation_id)
            rows = self._execute(
                "SELECT * FROM bid_workflows WHERE conversation_id = ? ORDER BY updated_at DESC",
                (conversation_id,),
            ).fetchall()
        else:
            rows = self._execute(
                """
                SELECT bid_workflows.* FROM bid_workflows
                JOIN projects ON projects.id = bid_workflows.project_id
                WHERE projects.owner_user_id = ?
                ORDER BY bid_workflows.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._workflow_from_row(user_id, row) for row in rows]

    def update_bid_workflow_status(
        self,
        user_id: str,
        workflow_id: str,
        status: BidWorkflowStatus,
        error: str | None = None,
    ) -> BidWorkflow:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE bid_workflows SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status.value, error, now, workflow_id),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.get_bid_workflow(user_id, workflow_id)

    def enqueue_bid_job(self, user_id: str, workflow_id: str, kind: str) -> BidWorkflow:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO bid_jobs (id, workflow_id, owner_user_id, kind, state, progress, message, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, '等待执行。', 0, ?, ?)
                ON CONFLICT(workflow_id, kind) DO UPDATE SET state = excluded.state, progress = 0, message = excluded.message, updated_at = excluded.updated_at
                """,
                (str(uuid4()), workflow_id, user_id, kind, BidExecutionState.QUEUED.value, now, now),
            )
        return self.get_bid_workflow(user_id, workflow_id)

    def recover_bid_jobs(self) -> None:
        """Restart work interrupted by an application exit once; otherwise leave it failed."""
        now = utc_now()
        with self._lock, self._connection:
            rows = self._execute("SELECT workflow_id, owner_user_id, attempts FROM bid_jobs WHERE state = ?", (BidExecutionState.RUNNING.value,)).fetchall()
            for row in rows:
                if row["attempts"] < 1:
                    self._execute(
                        "UPDATE bid_jobs SET state = ?, attempts = attempts + 1, message = ?, updated_at = ? WHERE workflow_id = ?",
                        (BidExecutionState.QUEUED.value, "应用重启后正在恢复。", now, row["workflow_id"]),
                    )
                else:
                    self._execute(
                        "UPDATE bid_jobs SET state = ?, message = ?, updated_at = ?, completed_at = ? WHERE workflow_id = ?",
                        (BidExecutionState.FAILED.value, "应用中断后恢复失败，请手动重试。", now, now, row["workflow_id"]),
                    )
                    self._execute(
                        "UPDATE bid_workflows SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                        (BidWorkflowStatus.FAILED.value, "应用中断后恢复失败，请手动重试。", now, row["workflow_id"]),
                    )

    def claim_next_bid_job(self) -> dict[str, str] | None:
        now = utc_now()
        with self._lock, self._connection:
            row = self._execute(
                "SELECT * FROM bid_jobs WHERE state = ? ORDER BY created_at LIMIT 1",
                (BidExecutionState.QUEUED.value,),
            ).fetchone()
            if not row:
                return None
            cursor = self._execute(
                "UPDATE bid_jobs SET state = ?, progress = 5, message = ?, started_at = ?, updated_at = ? WHERE id = ? AND state = ?",
                (BidExecutionState.RUNNING.value, "正在准备任务。", now, now, row["id"], BidExecutionState.QUEUED.value),
            )
            if cursor.rowcount == 0:
                return None
            return {"id": row["id"], "workflow_id": row["workflow_id"], "owner_user_id": row["owner_user_id"], "kind": row["kind"]}

    def update_bid_job(self, job_id: str, state: BidExecutionState | None = None, progress: int | None = None, message: str | None = None) -> None:
        now = utc_now()
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [now]
        if state is not None:
            assignments.append("state = ?")
            values.append(state.value)
            if state in {BidExecutionState.COMPLETED, BidExecutionState.FAILED, BidExecutionState.CANCELLED}:
                assignments.append("completed_at = ?")
                values.append(now)
        if progress is not None:
            assignments.append("progress = ?")
            values.append(max(0, min(progress, 100)))
        if message is not None:
            assignments.append("message = ?")
            values.append(message)
        where = "id = ?"
        if state is None:
            where += " AND state = ?"
            values.append(job_id)
            values.append(BidExecutionState.RUNNING.value)
        else:
            values.append(job_id)
        with self._lock, self._connection:
            self._execute(f"UPDATE bid_jobs SET {', '.join(assignments)} WHERE {where}", values)

    def cancel_bid_jobs(self, workflow_id: str) -> None:
        self._execute(
            "UPDATE bid_jobs SET state = ?, message = ?, completed_at = ?, updated_at = ? WHERE workflow_id = ? AND state IN (?, ?)",
            (BidExecutionState.CANCELLED.value, "任务已取消。", utc_now(), utc_now(), workflow_id, BidExecutionState.QUEUED.value, BidExecutionState.RUNNING.value),
        )

    def get_bid_execution(self, workflow_id: str) -> BidWorkflowExecution | None:
        row = self._execute("SELECT state, kind, progress, message FROM bid_jobs WHERE workflow_id = ? ORDER BY updated_at DESC LIMIT 1", (workflow_id,)).fetchone()
        if not row:
            return None
        return BidWorkflowExecution(state=row["state"], phase=row["kind"], progress=row["progress"], message=row["message"])

    def save_bid_extraction(self, user_id: str, workflow_id: str, extracted_markdown: str) -> BidWorkflow:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE bid_workflows
                SET extracted_markdown = ?, status = ?, error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (extracted_markdown, BidWorkflowStatus.EXTRACTION_READY.value, now, workflow_id),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.get_bid_workflow(user_id, workflow_id)

    def save_bid_confirmation(self, user_id: str, workflow_id: str, confirmation_text: str) -> BidWorkflow:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE bid_workflows SET confirmation_text = ?, error = NULL, updated_at = ? WHERE id = ?",
                (confirmation_text, now, workflow_id),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.get_bid_workflow(user_id, workflow_id)

    def save_bid_template_choice(self, user_id: str, workflow_id: str, template_choice: str) -> BidWorkflow:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                "UPDATE bid_workflows SET template_choice = ?, error = NULL, updated_at = ? WHERE id = ?",
                (template_choice, now, workflow_id),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.get_bid_workflow(user_id, workflow_id)

    def save_bid_artifacts(self, user_id: str, workflow_id: str, files: dict[str, str]) -> list[ArtifactInfo]:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        now = utc_now()
        with self._lock, self._connection:
            next_versions = {
                row["name"]: int(row["version"]) + 1
                for row in self._execute(
                    "SELECT name, MAX(version) AS version FROM bid_artifact_versions WHERE workflow_id = ? GROUP BY name",
                    (workflow_id,),
                ).fetchall()
            }
            self._execute("DELETE FROM bid_artifacts WHERE workflow_id = ?", (workflow_id,))
            for name, content in files.items():
                self._execute(
                    "INSERT INTO bid_artifact_versions (id, workflow_id, name, version, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), workflow_id, name, next_versions.get(name, 1), content, now),
                )
                self._execute(
                    """
                    INSERT INTO bid_artifacts (id, workflow_id, name, kind, size, path, content, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        workflow_id,
                        name,
                        self._artifact_kind(name),
                        len(content.encode("utf-8")),
                        content,
                        now,
                        now,
                    ),
                )
            self._execute(
                "UPDATE bid_workflows SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
                (BidWorkflowStatus.COMPLETED.value, now, workflow_id),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return self.list_bid_artifacts(user_id, workflow_id)

    def list_bid_artifact_versions(self, user_id: str, workflow_id: str, name: str | None = None) -> list[dict[str, Any]]:
        self.get_bid_workflow(user_id, workflow_id)
        query = "SELECT name, version, length(content) AS size, created_at FROM bid_artifact_versions WHERE workflow_id = ?"
        params: list[Any] = [workflow_id]
        if name is not None:
            query += " AND name = ?"
            params.append(name)
        query += " ORDER BY name, version DESC"
        return [dict(row) for row in self._execute(query, params).fetchall()]

    def get_bid_artifact_version(self, user_id: str, workflow_id: str, name: str, version: int) -> dict[str, Any]:
        self.get_bid_workflow(user_id, workflow_id)
        row = self._execute(
            "SELECT name, version, content, length(content) AS size, created_at FROM bid_artifact_versions WHERE workflow_id = ? AND name = ? AND version = ?",
            (workflow_id, name, version),
        ).fetchone()
        if not row:
            raise KeyError(version)
        return dict(row)

    def get_bid_artifact_version_diff(self, user_id: str, workflow_id: str, name: str, base_version: int, compare_version: int) -> dict[str, Any]:
        if base_version == compare_version:
            raise ValueError("请选择两个不同的版本进行对比。")
        base = self.get_bid_artifact_version(user_id, workflow_id, name, base_version)
        compare = self.get_bid_artifact_version(user_id, workflow_id, name, compare_version)
        return {
            "name": name,
            "base_version": base_version,
            "compare_version": compare_version,
            "lines": markdown_line_diff(base["content"], compare["content"]),
        }

    def update_bid_artifact_content(self, user_id: str, workflow_id: str, name: str, content: str) -> ArtifactInfo:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        artifact = self._execute("SELECT id FROM bid_artifacts WHERE workflow_id = ? AND name = ?", (workflow_id, name)).fetchone()
        if not artifact:
            raise KeyError(name)
        now = utc_now()
        with self._lock, self._connection:
            next_version = self._execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM bid_artifact_versions WHERE workflow_id = ? AND name = ?",
                (workflow_id, name),
            ).fetchone()["version"]
            self._execute(
                "INSERT INTO bid_artifact_versions (id, workflow_id, name, version, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), workflow_id, name, next_version, content, now),
            )
            self._execute(
                "UPDATE bid_artifacts SET content = ?, size = ?, updated_at = ? WHERE id = ?",
                (content, len(content.encode("utf-8")), now, artifact["id"]),
            )
            self._touch_conversation(workflow.conversation_id, now)
            self._touch_project(workflow.project_id, now)
        return next(item for item in self.list_bid_artifacts(user_id, workflow_id) if item.name == name)

    def restore_bid_artifact_version(self, user_id: str, workflow_id: str, name: str, version: int) -> None:
        workflow = self.get_bid_workflow(user_id, workflow_id)
        row = self._execute(
            "SELECT content FROM bid_artifact_versions WHERE workflow_id = ? AND name = ? AND version = ?",
            (workflow_id, name, version),
        ).fetchone()
        if not row:
            raise KeyError(version)
        now = utc_now()
        with self._lock, self._connection:
            next_version = self._execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM bid_artifact_versions WHERE workflow_id = ? AND name = ?",
                (workflow_id, name),
            ).fetchone()["version"]
            self._execute(
                "INSERT INTO bid_artifact_versions (id, workflow_id, name, version, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), workflow_id, name, next_version, row["content"], now),
            )
            self._execute(
                "UPDATE bid_artifacts SET content = ?, size = ?, updated_at = ? WHERE workflow_id = ? AND name = ?",
                (row["content"], len(row["content"].encode("utf-8")), now, workflow_id, name),
            )
            self._touch_conversation(workflow.conversation_id, now)

    def list_bid_artifacts(self, user_id: str, workflow_id: str) -> list[ArtifactInfo]:
        self.get_bid_workflow(user_id, workflow_id)
        rows = self._execute(
            "SELECT * FROM bid_artifacts WHERE workflow_id = ? ORDER BY created_at ASC",
            (workflow_id,),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def get_bid_artifact_content(self, user_id: str, workflow_id: str, name: str) -> str:
        self.get_bid_workflow(user_id, workflow_id)
        row = self._execute(
            "SELECT content FROM bid_artifacts WHERE workflow_id = ? AND name = ?",
            (workflow_id, name),
        ).fetchone()
        if not row or row["content"] is None:
            raise KeyError(name)
        return row["content"]

    def get_bid_artifact_files(self, user_id: str, workflow_id: str) -> dict[str, str]:
        self.get_bid_workflow(user_id, workflow_id)
        rows = self._execute(
            "SELECT name, content FROM bid_artifacts WHERE workflow_id = ? ORDER BY created_at ASC",
            (workflow_id,),
        ).fetchall()
        return {row["name"]: row["content"] or "" for row in rows}

    def list_messages(self, user_id: str, conversation_id: str) -> list[WorkbenchMessage]:
        self.get_conversation(user_id, conversation_id)
        rows = self._execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        status: str = "completed",
        model: str | None = None,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
        message_id: str | None = None,
    ) -> WorkbenchMessage:
        conversation = self.get_conversation(user_id, conversation_id)
        message_id = message_id or str(uuid4())
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO messages
                    (id, conversation_id, role, content, status, model, finish_reason, usage_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    status,
                    model,
                    finish_reason,
                    json.dumps(usage) if usage else None,
                    error,
                    now,
                    now,
                ),
            )
            self._touch_conversation(conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search(user_id, "message", message_id, conversation.project_id, conversation_id, role, content)
        return self.get_message(user_id, message_id)

    def update_message(
        self,
        user_id: str,
        message_id: str,
        content: str,
        status: str,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> WorkbenchMessage:
        message = self.get_message(user_id, message_id)
        conversation = self.get_conversation(user_id, message.conversation_id)
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE messages
                SET content = ?, status = ?, finish_reason = ?, usage_json = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (content, status, finish_reason, json.dumps(usage) if usage else None, error, now, message_id),
            )
            self._touch_conversation(message.conversation_id, now)
            self._touch_project(conversation.project_id, now)
            self._upsert_search(user_id, "message", message_id, conversation.project_id, message.conversation_id, message.role, content)
        return self.get_message(user_id, message_id)

    def update_streaming_message(self, user_id: str, message_id: str, content: str) -> None:
        """Persist partial LLM output without repeatedly updating search indexes."""
        self.get_message(user_id, message_id)
        with self._lock, self._connection:
            self._execute(
                "UPDATE messages SET content = ?, updated_at = ? WHERE id = ? AND status = 'streaming'",
                (content, utc_now(), message_id),
            )

    def get_message(self, user_id: str, message_id: str) -> WorkbenchMessage:
        row = self._execute(
            """
            SELECT messages.* FROM messages
            JOIN conversations ON conversations.id = messages.conversation_id
            JOIN projects ON projects.id = conversations.project_id
            WHERE messages.id = ? AND projects.owner_user_id = ?
            """,
            (message_id, user_id),
        ).fetchone()
        if not row:
            raise KeyError(message_id)
        return self._message_from_row(row)

    def list_provider_profiles(self, user_id: str) -> list[ProviderProfile]:
        rows = self._execute("SELECT * FROM provider_profiles WHERE owner_user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._provider_from_row(row) for row in rows]

    def create_provider_profile(self, user_id: str, request: ProviderProfileCreate) -> ProviderProfile:
        profile_id = str(uuid4())
        now = utc_now()
        credential_key = f"provider:{user_id}:{profile_id}"
        api_key = request.api_key.strip() if request.api_key else None
        if api_key:
            credential_store.set(credential_key, api_key)
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO provider_profiles (id, owner_user_id, provider, display_name, base_url, model, credential_key, has_key, api_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    user_id,
                    request.provider,
                    request.display_name,
                    request.base_url,
                    request.model,
                    credential_key,
                    1 if api_key else 0,
                    None,
                    now,
                    now,
                ),
            )
        return self.get_provider_profile(user_id, profile_id)

    def get_provider_profile(self, user_id: str, profile_id: str) -> ProviderProfile:
        row = self._execute("SELECT * FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        if not row:
            raise KeyError(profile_id)
        return self._provider_from_row(row)

    def update_provider_profile(self, user_id: str, profile_id: str, request: ProviderProfileUpdate) -> ProviderProfile:
        profile = self.get_provider_profile(user_id, profile_id)
        row = self._execute("SELECT credential_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        now = utc_now()
        if request.api_key is not None:
            api_key = request.api_key.strip() if request.api_key else None
            has_key = 1 if api_key else 0
            credential_key = row["credential_key"] if row else f"provider:{user_id}:{profile_id}"
            if api_key:
                credential_store.set(credential_key, api_key)
            else:
                credential_store.delete(credential_key)
        else:
            has_key = int(profile.has_key)
        with self._lock, self._connection:
            self._execute(
                """
                UPDATE provider_profiles
                SET provider = ?, display_name = ?, base_url = ?, model = ?, has_key = ?, api_key = NULL, updated_at = ?
                WHERE id = ? AND owner_user_id = ?
                """,
                (
                    request.provider if request.provider is not None else profile.provider,
                    request.display_name if request.display_name is not None else profile.display_name,
                    request.base_url if request.base_url is not None else profile.base_url,
                    request.model if request.model is not None else profile.model,
                    has_key,
                    now,
                    profile_id,
                    user_id,
                ),
            )
        return self.get_provider_profile(user_id, profile_id)

    def get_setting(self, key: str) -> str | None:
        row = self._execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_user_setting(self, user_id: str, key: str) -> str | None:
        row = self._execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
        return row["value"] if row else None

    def set_user_setting(self, user_id: str, key: str, value: str) -> None:
        now = utc_now()
        self._execute(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (user_id, key, value, now),
        )

    def get_web_search_config(self, user_id: str) -> WebSearchConfig:
        max_results_raw = self.get_user_setting(user_id, "web_search.max_results")
        search_depth = self.get_user_setting(user_id, "web_search.search_depth") or os.getenv("TAVILY_SEARCH_DEPTH", "basic")
        try:
            max_results = int(max_results_raw or os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
        except ValueError:
            max_results = 5
        max_results = min(max(max_results, 1), 10)
        if search_depth not in {"basic", "advanced"}:
            search_depth = "basic"
        key, source = self._resolve_tavily_api_key_with_source(user_id)
        return WebSearchConfig(
            provider="tavily",
            has_key=key is not None,
            source=source,
            max_results=max_results,
            search_depth=search_depth,
        )

    def update_web_search_config(self, user_id: str, request: WebSearchConfigUpdate) -> WebSearchConfig:
        if request.api_key is not None:
            key = request.api_key.strip() or None
            credential_key = self._tavily_credential_key(user_id)
            if key:
                credential_store.set(credential_key, key)
            else:
                credential_store.delete(credential_key)
            self.set_user_setting(user_id, "web_search.api_key", "")
            self.set_user_setting(user_id, "web_search.has_key", "1" if key else "0")
        if request.max_results is not None:
            self.set_user_setting(user_id, "web_search.max_results", str(request.max_results))
        if request.search_depth is not None:
            self.set_user_setting(user_id, "web_search.search_depth", request.search_depth)
        return self.get_web_search_config(user_id)

    def delete_provider_profile(self, user_id: str, profile_id: str) -> None:
        row = self._execute("SELECT credential_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        self.get_provider_profile(user_id, profile_id)
        if row:
            credential_store.delete(row["credential_key"])
        with self._lock, self._connection:
            self._execute("DELETE FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id))

    def resolve_api_key(self, user_id: str, profile_id: str | None, inline_api_key: str | None = None) -> str | None:
        if inline_api_key:
            return inline_api_key
        if not profile_id:
            return None
        row = self._execute("SELECT credential_key, has_key FROM provider_profiles WHERE id = ? AND owner_user_id = ?", (profile_id, user_id)).fetchone()
        if not row:
            raise KeyError(profile_id)
        if not row["has_key"]:
            return None
        return credential_store.get(row["credential_key"])

    def resolve_tavily_api_key(self, user_id: str) -> str | None:
        """返回 Tavily API key。

        优先级：DB 中用户保存的 key > 环境变量（.env 部署默认）。
        """
        key, _ = self._resolve_tavily_api_key_with_source(user_id)
        return key

    def _resolve_tavily_api_key_with_source(self, user_id: str) -> tuple[str | None, str]:
        """返回 (api_key, source)，source 为 'system' / 'env' / 'none'。"""
        user_key = credential_store.get(self._tavily_credential_key(user_id))
        if user_key:
            return user_key, "system"
        env_key = os.getenv("TAVILY_API_KEY", "").strip()
        if env_key:
            return env_key, "env"
        return None, "none"

    def _tavily_credential_key(self, user_id: str) -> str:
        return f"tavily:{user_id}"

    def search(self, user_id: str, query: str, kind: str | None = None) -> list[SearchResult]:
        trimmed = query.strip()
        if not trimmed:
            return []
        normalized_kind = kind.strip() if kind else ""
        kind_clause = " AND kind = ?" if normalized_kind else ""
        search_params = [trimmed, user_id]
        if normalized_kind:
            search_params.append(normalized_kind)
        try:
            rows = self._execute(
                f"""
                SELECT kind, source_id, project_id, conversation_id, title, snippet(search_index, 5, '', '', '...', 12) AS excerpt
                FROM search_index
                WHERE search_index MATCH ? AND owner_user_id = ?{kind_clause}
                ORDER BY rank
                LIMIT 30
                """,
                search_params,
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            like_query = f"%{trimmed}%"
            fallback_params = [user_id, like_query, like_query]
            if normalized_kind:
                fallback_params.append(normalized_kind)
            rows = self._execute(
                f"""
                SELECT kind, source_id, project_id, conversation_id, title, content AS excerpt
                FROM search_index
                WHERE owner_user_id = ? AND (title LIKE ? OR content LIKE ?){kind_clause}
                ORDER BY title
                LIMIT 30
                """,
                fallback_params,
            ).fetchall()
        return [
            SearchResult(
                kind=row["kind"],
                id=row["source_id"],
                title=row["title"] or row["kind"],
                excerpt=row["excerpt"] or "",
                conversation_id=row["conversation_id"],
                project_id=row["project_id"],
            )
            for row in rows
        ]

    def _touch_project(self, project_id: str, when: str | None = None) -> None:
        self._execute("UPDATE projects SET updated_at = ? WHERE id = ?", (when or utc_now(), project_id))

    def _touch_conversation(self, conversation_id: str, when: str | None = None) -> None:
        self._execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (when or utc_now(), conversation_id))

    def _upsert_search(
        self,
        user_id: str,
        kind: str,
        source_id: str,
        project_id: str | None,
        conversation_id: str | None,
        title: str,
        content: str,
    ) -> None:
        self._execute("DELETE FROM search_index WHERE owner_user_id = ? AND kind = ? AND source_id = ?", (user_id, kind, source_id))
        self._execute(
            """
            INSERT INTO search_index (owner_user_id, kind, source_id, project_id, conversation_id, title, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, kind, source_id, project_id, conversation_id, title, content),
        )

    def _project_from_row(self, row: sqlite3.Row) -> WorkbenchProject:
        return WorkbenchProject(
            id=row["id"],
            title=row["title"],
            workspace_path=row["workspace_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _user_from_row(self, row: sqlite3.Row) -> AuthUser:
        return AuthUser(
            id=row["id"],
            username=row["username"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
        )

    def _conversation_from_row(self, row: sqlite3.Row) -> WorkbenchConversation:
        return WorkbenchConversation(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            provider_profile_id=row["provider_profile_id"],
            model=row["model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _message_from_row(self, row: sqlite3.Row) -> WorkbenchMessage:
        return WorkbenchMessage(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            status=row["status"],
            model=row["model"],
            finish_reason=row["finish_reason"],
            usage=json.loads(row["usage_json"]) if row["usage_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _provider_from_row(self, row: sqlite3.Row) -> ProviderProfile:
        return ProviderProfile(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            base_url=row["base_url"],
            model=row["model"],
            has_key=bool(row["has_key"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _workflow_from_row(self, user_id: str, row: sqlite3.Row) -> BidWorkflow:
        return BidWorkflow(
            id=row["id"],
            project_id=row["project_id"],
            conversation_id=row["conversation_id"],
            provider_profile_id=row["provider_profile_id"],
            file_name=row["file_name"],
            file_text=row["file_text"],
            extracted_markdown=row["extracted_markdown"],
            confirmation_text=row["confirmation_text"],
            template_choice=row["template_choice"],
            status=row["status"],
            error=row["error"],
            execution=self.get_bid_execution(row["id"]),
            artifacts=self._list_bid_artifacts_unchecked(user_id, row["id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _list_bid_artifacts_unchecked(self, user_id: str, workflow_id: str) -> list[ArtifactInfo]:
        rows = self._execute(
            "SELECT * FROM bid_artifacts WHERE workflow_id = ? ORDER BY created_at ASC",
            (workflow_id,),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def _artifact_from_row(self, row: sqlite3.Row) -> ArtifactInfo:
        return ArtifactInfo(name=row["name"], size=row["size"], kind=row["kind"])

    def _artifact_kind(self, name: str) -> str:
        if "信息提取" in name:
            return "extraction"
        if "设计方案" in name:
            return "proposal"
        if "绘图提示词" in name or "图文证据" in name:
            return "drawing"
        if "标书制作规范" in name:
            return "spec"
        return "file"


workbench_store = WorkbenchStore()
