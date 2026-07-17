import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ["AI_WORKBENCH_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"ai-workbench-test-{uuid4()}.db")
os.environ["APP_AUTH_SECRET"] = "test-app-secret"
os.environ["AI_WORKBENCH_TEST_CREDENTIALS"] = "1"

from backend.main import app
from backend.schemas import BidWorkflowStatus, ProviderModel
from backend.services.behavior_report import REPORT_FILENAME, behavior_report_path, save_behavior_report
from backend.services.app_version import get_app_version
from backend.services.workbench_store import WorkbenchStore, workbench_store


APP_SECRET_HEADERS = {"X-App-Auth-Secret": "test-app-secret"}
client = TestClient(app)
auth_response = client.post("/api/v1/auth/register", headers=APP_SECRET_HEADERS, json={"username": "tester", "password": "test-password"})
assert auth_response.status_code == 200
TEST_USER_ID = client.get("/api/v1/me", headers={"Authorization": f"Bearer {auth_response.json()['token']}", **APP_SECRET_HEADERS}).json()["id"]
client.headers.update(
    {
        "Authorization": f"Bearer {auth_response.json()['token']}",
        "X-App-Auth-Secret": "test-app-secret",
    }
)


def register_tenant_client(username: str) -> tuple[TestClient, str]:
    tenant_client = TestClient(app)
    response = tenant_client.post(
        "/api/v1/auth/register",
        headers=APP_SECRET_HEADERS,
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200
    tenant_client.headers.update(
        {
            "Authorization": f"Bearer {response.json()['token']}",
            "X-App-Auth-Secret": "test-app-secret",
        }
    )
    return tenant_client, tenant_client.get("/api/v1/me").json()["id"]


def test_health_identifies_ai_workbench_backend():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["app"] == "ai-workbench-desktop"
    assert payload["version"] == get_app_version()
    assert "database" in payload
    assert "presets" in payload


def test_v1_routes_require_app_secret_and_login():
    bare_client = TestClient(app)
    no_secret = bare_client.get("/api/v1/projects")
    assert no_secret.status_code == 403

    no_token = bare_client.get("/api/v1/projects", headers={"X-App-Auth-Secret": "test-app-secret"})
    assert no_token.status_code == 401

    status_without_secret = bare_client.get("/api/v1/auth/status")
    assert status_without_secret.status_code == 403

    status = bare_client.get("/api/v1/auth/status", headers=APP_SECRET_HEADERS)
    assert status.status_code == 200
    assert status.json()["registration_allowed"] is True
    assert status.json()["authenticated"] is False


def test_auth_error_keeps_cors_headers_for_app_frontend():
    bare_client = TestClient(app)
    response = bare_client.patch(
        "/api/v1/web-search-config",
        headers={"Origin": "app://frontend"},
        json={"max_results": 5},
    )
    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == "app://frontend"
    assert response.json()["detail"] == "本机访问密钥无效。"


def test_legacy_project_routes_are_removed():
    bare_client = TestClient(app)
    response = bare_client.post("/api/projects")
    assert response.status_code == 404


def test_local_frontend_cors_allows_dynamic_dev_ports():
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-app-auth-secret,authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_app_frontend_cors_allows_private_network_preflight():
    response = client.options(
        "/api/v1/me",
        headers={
            "Origin": "app://frontend",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type,x-app-auth-secret,authorization",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://frontend"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_auth_login_logout_and_wrong_password_guard():
    bad_login = client.post("/api/v1/auth/login", json={"username": "tester", "password": "wrong-password"})
    assert bad_login.status_code == 401

    login = client.post("/api/v1/auth/login", json={"username": "tester", "password": "test-password"})
    assert login.status_code == 200
    token = login.json()["token"]

    temporary_client = TestClient(app)
    temporary_client.headers.update({"Authorization": f"Bearer {token}", "X-App-Auth-Secret": "test-app-secret"})
    me = temporary_client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["username"] == "tester"

    wrong_change = temporary_client.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "new-password"})
    assert wrong_change.status_code == 400

    logout = temporary_client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    after_logout = temporary_client.get("/api/v1/me")
    assert after_logout.status_code == 401


def test_auth_login_throttles_repeated_failures():
    temporary_client = TestClient(app)
    username = f"missing-{uuid4()}"
    for _ in range(5):
        response = temporary_client.post(
            "/api/v1/auth/login",
            headers=APP_SECRET_HEADERS,
            json={"username": username, "password": "wrong-password"},
        )
        assert response.status_code == 401

    throttled = temporary_client.post(
        "/api/v1/auth/login",
        headers=APP_SECRET_HEADERS,
        json={"username": username, "password": "wrong-password"},
    )
    assert throttled.status_code == 429


def test_auth_rejects_blank_username():
    response = client.post("/api/v1/auth/login", json={"username": "   ", "password": "wrong-password"})
    assert response.status_code == 422


def test_workbench_project_conversation_and_search():
    created_project = client.post("/api/v1/projects", json={"title": "Alpha 项目", "workspace_path": "/tmp/alpha-workspace"})
    assert created_project.status_code == 200
    project_id = created_project.json()["id"]
    assert created_project.json()["workspace_path"] == "/tmp/alpha-workspace"

    listed_projects = client.get("/api/v1/projects")
    assert listed_projects.status_code == 200
    assert any(project["id"] == project_id and project["workspace_path"] == "/tmp/alpha-workspace" for project in listed_projects.json())

    created_conversation = client.post(
        "/api/v1/conversations",
        json={"project_id": project_id, "title": "技术路线讨论"},
    )
    assert created_conversation.status_code == 200
    conversation_id = created_conversation.json()["id"]

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert messages.json() == []

    search = client.get("/api/v1/search", params={"q": "技术路线"})
    assert search.status_code == 200
    assert any(item["conversation_id"] == conversation_id for item in search.json())

    path_search = client.get("/api/v1/search", params={"q": "alpha-workspace"})
    assert path_search.status_code == 200
    assert any(item["project_id"] == project_id for item in path_search.json())


def test_provider_profile_does_not_echo_api_key():
    created = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["has_key"] is True
    assert "api_key" not in payload

    listed = client.get("/api/v1/provider-profiles")
    assert listed.status_code == 200
    assert any(profile["id"] == payload["id"] for profile in listed.json())


def test_users_are_isolated_across_projects_conversations_workflows_and_configs(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    user_a, user_a_id = register_tenant_client(f"tenant-a-{uuid4()}")
    user_b, _ = register_tenant_client(f"tenant-b-{uuid4()}")

    project = user_a.post("/api/v1/projects", json={"title": "用户 A 私有项目"}).json()
    conversation = user_a.post("/api/v1/conversations", json={"project_id": project["id"], "title": "用户 A 私有对话"}).json()
    profile = user_a.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "用户 A 私有模型",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "tenant-a-secret",
        },
    ).json()
    workflow = user_a.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation["id"], "provider_profile_id": profile["id"]},
        files={"file": ("a.txt", "用户 A 私有标书内容".encode("utf-8"), "text/plain")},
    ).json()

    assert user_b.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert user_b.get(f"/api/v1/conversations/{conversation['id']}").status_code == 404
    assert user_b.get(f"/api/v1/conversations/{conversation['id']}/messages").status_code == 404
    assert user_b.delete(f"/api/v1/provider-profiles/{profile['id']}").status_code == 404
    assert user_b.get(f"/api/v1/bid-workflows/{workflow['id']}").status_code == 404
    assert user_b.get(f"/api/v1/bid-workflows/{workflow['id']}/artifacts").status_code == 404
    assert all(item["id"] != project["id"] for item in user_b.get("/api/v1/projects").json())
    assert all(item["conversation_id"] != conversation["id"] for item in user_b.get("/api/v1/search", params={"q": "私有标书"}).json())

    user_a.patch("/api/v1/web-search-config", json={"api_key": "tvly-user-a", "max_results": 3})
    assert user_a.get("/api/v1/web-search-config").json()["has_key"] is True
    assert user_b.get("/api/v1/web-search-config").json()["has_key"] is False

    row = workbench_store._execute("SELECT api_key FROM provider_profiles WHERE id = ?", (profile["id"],)).fetchone()
    assert row["api_key"] is None
    assert workbench_store.resolve_api_key(user_a_id, profile["id"]) == "tenant-a-secret"


def test_legacy_database_migrates_existing_data_to_its_only_user(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy_path)
    connection.executescript(
        """
        CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT);
        CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT NOT NULL, workspace_path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE provider_profiles (id TEXT PRIMARY KEY, provider TEXT NOT NULL, display_name TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL, credential_key TEXT NOT NULL UNIQUE, has_key INTEGER NOT NULL DEFAULT 0, api_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO users VALUES ('legacy-user', 'legacy', 'hash', '2026-01-01', '2026-01-01', NULL);
        INSERT INTO projects VALUES ('legacy-project', '历史项目', NULL, '2026-01-01', '2026-01-01');
        INSERT INTO provider_profiles VALUES ('legacy-profile', 'OpenAI', '旧模型', 'https://api.openai.com/v1', 'gpt-4o', 'provider:legacy-profile', 1, 'legacy-secret', '2026-01-01', '2026-01-01');
        """
    )
    connection.commit()
    connection.close()

    migrated = WorkbenchStore(legacy_path)
    assert migrated.get_project("legacy-user", "legacy-project").title == "历史项目"
    migrated.migrate_legacy_secrets_on_login("legacy-user", "test-password")
    assert migrated.resolve_api_key("legacy-user", "legacy-profile") == "legacy-secret"
    assert migrated._execute("SELECT api_key FROM provider_profiles WHERE id = 'legacy-profile'").fetchone()["api_key"] is None
    assert any(item.project_id == "legacy-project" for item in migrated.search("legacy-user", "历史项目"))
    assert migrated.path.with_suffix(".db.pre-multitenant.bak").exists()
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_web_search_config_does_not_echo_tavily_key():
    initial = client.get("/api/v1/web-search-config")
    assert initial.status_code == 200
    assert "api_key" not in initial.json()

    updated = client.patch(
        "/api/v1/web-search-config",
        json={"api_key": "tvly-test-secret", "max_results": 3, "search_depth": "advanced"},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["provider"] == "tavily"
    assert payload["has_key"] is True
    assert payload["max_results"] == 3
    assert payload["search_depth"] == "advanced"
    assert "api_key" not in payload


def test_provider_models_can_be_listed(monkeypatch):
    created = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "DeepSeek",
            "display_name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "secret",
        },
    )
    profile_id = created.json()["id"]

    async def fake_fetch(user_id_arg: str, profile_id_arg: str):
        assert user_id_arg == TEST_USER_ID
        assert profile_id_arg == profile_id
        return [
            ProviderModel(id="deepseek-chat", name="deepseek-chat"),
            ProviderModel(id="deepseek-reasoner", name="deepseek-reasoner"),
        ]

    monkeypatch.setattr("backend.routers.config.fetch_provider_models", fake_fetch)

    response = client.get(f"/api/v1/provider-profiles/{profile_id}/models")
    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "deepseek-chat"


def test_provider_models_requires_api_key():
    created = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "DeepSeek",
            "display_name": "DeepSeek without key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
        },
    )
    profile_id = created.json()["id"]

    response = client.get(f"/api/v1/provider-profiles/{profile_id}/models")
    assert response.status_code == 400
    assert "API key" in response.json()["detail"]


def test_bid_workflow_store_persists_state_and_artifacts():
    created_project = client.post("/api/v1/projects", json={"title": "标书项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post(
        "/api/v1/conversations",
        json={"project_id": project_id, "title": "招标文件处理"},
    )
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI 标书",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    profile_id = created_profile.json()["id"]

    workflow = workbench_store.create_bid_workflow(
        TEST_USER_ID,
        conversation_id=conversation_id,
        provider_profile_id=profile_id,
        file_name="招标文件.txt",
        file_text="项目名称：测试标书项目",
    )

    assert workflow.project_id == project_id
    assert workflow.status == BidWorkflowStatus.UPLOADED
    assert workflow.file_name == "招标文件.txt"
    assert workbench_store.get_active_bid_workflow(TEST_USER_ID, conversation_id).id == workflow.id

    with pytest.raises(ValueError, match="已有未完成"):
        workbench_store.create_bid_workflow(
            TEST_USER_ID,
            conversation_id=conversation_id,
            provider_profile_id=profile_id,
            file_name="另一个招标文件.txt",
            file_text="项目名称：另一个项目",
        )

    extracting = workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow.id, BidWorkflowStatus.EXTRACTING)
    assert extracting.status == BidWorkflowStatus.EXTRACTING

    extracted = workbench_store.save_bid_extraction(TEST_USER_ID, workflow.id, "# 测试标书项目 — 招标文件信息提取")
    assert extracted.status == BidWorkflowStatus.EXTRACTION_READY
    assert "信息提取" in extracted.extracted_markdown

    confirmed = workbench_store.save_bid_confirmation(TEST_USER_ID, workflow.id, "确认，并补充企业优势。")
    assert confirmed.confirmation_text == "确认，并补充企业优势。"

    templated = workbench_store.save_bid_template_choice(TEST_USER_ID, workflow.id, "12-chapter")
    assert templated.template_choice == "12-chapter"

    artifacts = workbench_store.save_bid_artifacts(
        TEST_USER_ID,
        workflow.id,
        {
            "测试标书项目_招标文件信息提取.md": extracted.extracted_markdown,
            "测试标书项目_设计方案.md": "# 设计方案",
        },
    )
    completed = workbench_store.get_bid_workflow(TEST_USER_ID, workflow.id)

    assert completed.status == BidWorkflowStatus.COMPLETED
    assert workbench_store.get_active_bid_workflow(TEST_USER_ID, conversation_id) is None
    assert [artifact.kind for artifact in artifacts] == ["extraction", "proposal"]
    assert workbench_store.get_bid_artifact_content(TEST_USER_ID, workflow.id, "测试标书项目_设计方案.md") == "# 设计方案"


def test_bid_workflow_v1_full_chain(monkeypatch):
    created_project = client.post("/api/v1/projects", json={"title": "V1 标书项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post(
        "/api/v1/conversations",
        json={"project_id": project_id, "title": "V1 招标文件处理"},
    )
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "DeepSeek",
            "display_name": "DeepSeek 标书",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "secret",
        },
    )
    profile_id = created_profile.json()["id"]
    seen_models = []
    streamed_progress = []
    streamed_contents = []
    streamed_statuses = []

    def fake_run_agent(api_config, instructions, prompt, on_delta=None):
        seen_models.append(api_config.model)
        if on_delta:
            on_delta("模型响应" * 80)
            streamed_progress.append(workbench_store.get_bid_execution(workflow_id).progress)
            streamed_message = workbench_store.list_messages(TEST_USER_ID, conversation_id)[-1]
            streamed_contents.append(streamed_message.content)
            streamed_statuses.append(streamed_message.status)
        if "阶段二" in prompt:
            return "## 方案正文\n内容\n## 绘图提示词 + 专业图纸需求清单\n提示词"
        return "# 测试项目 — 招标文件信息提取\n\n## 四、标书制作规范\n字体要求"

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)

    created = client.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation_id, "provider_profile_id": profile_id},
        files={"file": ("招标.txt", "项目名称：测试项目".encode("utf-8"), "text/plain")},
    )
    assert created.status_code == 200
    assert "file_text" not in created.json()
    workflow_id = created.json()["id"]
    assert created.json()["status"] == "uploaded"
    assert created.json()["char_count"] > 0

    duplicate = client.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation_id, "provider_profile_id": profile_id},
        files={"file": ("另一个.txt", "项目名称：另一个".encode("utf-8"), "text/plain")},
    )
    assert duplicate.status_code == 400

    extract = client.post(f"/api/v1/bid-workflows/{workflow_id}/extract")
    assert extract.status_code == 200

    workflow = client.get(f"/api/v1/bid-workflows/{workflow_id}").json()
    assert "file_text" not in workflow
    assert workflow["status"] == "extraction_ready"
    assert "信息提取" in workflow["extracted_markdown"]

    confirm = client.post(f"/api/v1/bid-workflows/{workflow_id}/confirm", json={"text": "确认，并补充企业优势。"})
    assert confirm.status_code == 200
    assert "补充企业优势" in confirm.json()["workflow"]["confirmation_text"]

    generate = client.post(
        f"/api/v1/bid-workflows/{workflow_id}/generate",
        json={"extra_context": "采用低碳设计策略。"},
    )
    assert generate.status_code == 200

    completed = client.get(f"/api/v1/bid-workflows/{workflow_id}").json()
    assert completed["status"] == "completed"
    assert completed["template_choice"] == "auto"
    assert len(completed["artifacts"]) == 4
    assert seen_models == ["deepseek-chat", "deepseek-chat"]
    assert all(progress > 20 for progress in streamed_progress)
    assert all(content == "模型响应" * 80 for content in streamed_contents)
    assert streamed_statuses == ["streaming", "streaming"]
    skill_messages = [message for message in client.get(f"/api/v1/conversations/{conversation_id}/messages").json() if message.get("model") == "deepseek-chat"]
    assert len(skill_messages) == 2
    assert all(message["usage"]["usage_source"] == "estimated" for message in skill_messages)
    assert all(message["usage"]["context_estimated_tokens"] > 0 for message in skill_messages)
    assert all(message["usage"]["total_estimated_tokens"] >= message["usage"]["context_estimated_tokens"] for message in skill_messages)

    listed = client.get("/api/v1/bid-workflows", params={"conversation_id": conversation_id})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == workflow_id
    assert "file_text" not in listed.json()[0]
    assert len(listed.json()[0]["artifacts"]) == 4

    artifacts = client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts")
    assert artifacts.status_code == 200
    proposal = next(item for item in artifacts.json() if item["kind"] == "proposal")

    download = client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{quote(proposal['name'])}")
    assert download.status_code == 200
    assert "方案正文" in download.text

    exported = client.get(f"/api/v1/bid-workflows/{workflow_id}/export.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert proposal["name"] in archive.namelist()

    report_path = behavior_report_path(TEST_USER_ID, workflow_id)
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "用户行为与需求摘要" in report
    assert proposal["name"] in report

    search = client.get("/api/v1/search", params={"q": "信息提取"})
    assert search.status_code == 200
    assert any(item["conversation_id"] == conversation_id for item in search.json())


def _create_completed_bid_workflow() -> str:
    created_project = client.post("/api/v1/projects", json={"title": "行为摘要项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "行为摘要对话"})
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI 行为摘要",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    workflow = workbench_store.create_bid_workflow(
        TEST_USER_ID,
        conversation_id=conversation_id,
        provider_profile_id=created_profile.json()["id"],
        file_name="行为摘要招标文件.txt",
        file_text="原始招标文件全文不应进入行为报告。项目名称：行为摘要测试项目。",
    )
    workbench_store.add_message(TEST_USER_ID, conversation_id, "user", "请补充低碳策略，api_key=sk-1234567890abcdef")
    workbench_store.save_bid_extraction(TEST_USER_ID, workflow.id, "# 行为摘要测试项目 — 招标文件信息提取")
    workbench_store.save_bid_confirmation(TEST_USER_ID, workflow.id, "确认，并补充低碳策略。token=sk-1234567890abcdef")
    workbench_store.save_bid_template_choice(TEST_USER_ID, workflow.id, "auto")
    workbench_store.save_bid_artifacts(
        TEST_USER_ID,
        workflow.id,
        {
            "行为摘要测试项目_招标文件信息提取.md": "# 信息提取",
            "行为摘要测试项目_设计方案.md": "# 设计方案",
        },
    )
    return workflow.id


def test_bid_artifact_versions_are_immutable_and_restorable():
    workflow_id = _create_completed_bid_workflow()
    artifact_name = "行为摘要测试项目_设计方案.md"
    files = workbench_store.get_bid_artifact_files(TEST_USER_ID, workflow_id)
    files[artifact_name] = "# 修订版设计方案"
    workbench_store.save_bid_artifacts(TEST_USER_ID, workflow_id, files)

    encoded_name = quote(artifact_name, safe="")
    versions = client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/versions", params={"name": artifact_name})
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [2, 1]

    original = client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}/versions/1")
    assert original.status_code == 200
    assert original.json()["content"] == "# 设计方案"

    restored = client.post(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}/versions/1/restore")
    assert restored.status_code == 200
    assert client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}").text == "# 设计方案"

    versions_after_restore = client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/versions", params={"name": artifact_name})
    assert [item["version"] for item in versions_after_restore.json()] == [3, 2, 1]

    edited = client.patch(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}", json={"content": "# 手动编辑设计方案"})
    assert edited.status_code == 200
    assert edited.json()["size"] == len("# 手动编辑设计方案".encode("utf-8"))
    assert client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}/versions/4").json()["content"] == "# 手动编辑设计方案"
    assert client.get(f"/api/v1/bid-workflows/{workflow_id}/artifacts/{encoded_name}/versions/1").json()["content"] == "# 设计方案"


def test_behavior_report_saves_markdown_locally_and_redacts_sensitive():
    workflow_id = _create_completed_bid_workflow()
    path = save_behavior_report(TEST_USER_ID, workflow_id)
    duplicate = save_behavior_report(TEST_USER_ID, workflow_id)

    assert path == duplicate
    assert path.name == REPORT_FILENAME
    assert path.parent.name == workflow_id
    report = path.read_text(encoding="utf-8")
    assert "用户行为与需求摘要" in report
    assert "行为摘要测试项目_设计方案.md" in report
    assert "原始招标文件全文不应进入行为报告" not in report
    assert "sk-1234567890abcdef" not in report
    assert "已脱敏" in report


def test_bid_workflow_cancel_prevents_late_extraction_save(monkeypatch):
    created_project = client.post("/api/v1/projects", json={"title": "取消阶段一项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "取消阶段一"})
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI 取消阶段一",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    workflow = workbench_store.create_bid_workflow(
        TEST_USER_ID,
        conversation_id=conversation_id,
        provider_profile_id=created_profile.json()["id"],
        file_name="取消阶段一.txt",
        file_text="项目名称：取消阶段一项目",
    )
    workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow.id, BidWorkflowStatus.EXTRACTING)

    def fake_run_agent(api_config, instructions, prompt):
        workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow.id, BidWorkflowStatus.CANCELLED)
        return "# 迟到的阶段一结果"

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)

    from backend.main import run_bid_extraction_task

    run_bid_extraction_task(TEST_USER_ID, workflow.id)
    cancelled = workbench_store.get_bid_workflow(TEST_USER_ID, workflow.id)
    assert cancelled.status == BidWorkflowStatus.CANCELLED
    assert cancelled.extracted_markdown == ""


def test_bid_model_progress_updates_on_first_stream_chunk(monkeypatch):
    from backend.main import bid_model_progress

    updates = []
    monkeypatch.setattr("backend.main.workbench_store.update_bid_job", lambda job_id, **values: updates.append((job_id, values)))

    report, stop = bid_model_progress("job-1", "阶段一")
    try:
        report("首个分片")
    finally:
        stop()

    assert updates == [
        ("job-1", {"progress": 15, "message": "正在建立模型连接。"}),
        ("job-1", {"progress": 20, "message": "正在接收阶段一模型响应（4 字）。"}),
    ]


def test_bid_workflow_cancel_prevents_late_generation_save(monkeypatch):
    workflow_id = _create_completed_bid_workflow()
    workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow_id, BidWorkflowStatus.GENERATING)

    def fake_run_agent(api_config, instructions, prompt):
        workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow_id, BidWorkflowStatus.CANCELLED)
        return "## 迟到的设计方案"

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)

    from backend.main import run_bid_generation_task

    run_bid_generation_task(TEST_USER_ID, workflow_id)
    cancelled = workbench_store.get_bid_workflow(TEST_USER_ID, workflow_id)
    assert cancelled.status == BidWorkflowStatus.CANCELLED
    assert workbench_store.get_bid_artifact_content(TEST_USER_ID, workflow_id, "行为摘要测试项目_设计方案.md") == "# 设计方案"


def test_bid_workflow_cancel_endpoint_rejects_completed_workflow():
    workflow_id = _create_completed_bid_workflow()
    response = client.post(f"/api/v1/bid-workflows/{workflow_id}/cancel")
    assert response.status_code == 400
    assert "已完成" in response.json()["detail"]


def test_bid_generation_behavior_report_failure_does_not_fail_workflow(monkeypatch):
    workflow_id = _create_completed_bid_workflow()
    workbench_store.update_bid_workflow_status(TEST_USER_ID, workflow_id, BidWorkflowStatus.GENERATING)

    def fake_run_agent(api_config, instructions, prompt):
        return "## 方案正文\n内容"

    def fake_save_behavior_report(user_id_arg: str, workflow_id_arg: str):
        assert user_id_arg == TEST_USER_ID
        assert workflow_id_arg == workflow_id
        raise RuntimeError("disk full")

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)
    monkeypatch.setattr("backend.main.save_behavior_report", fake_save_behavior_report)

    from backend.main import run_bid_generation_task

    run_bid_generation_task(TEST_USER_ID, workflow_id)
    completed = workbench_store.get_bid_workflow(TEST_USER_ID, workflow_id)
    assert completed.status == BidWorkflowStatus.COMPLETED
    assert completed.error is None


def test_bid_workflow_v1_rejects_parse_error_and_missing_key():
    created_project = client.post("/api/v1/projects", json={"title": "错误标书项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "错误处理"})
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "DeepSeek",
            "display_name": "No Key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
        },
    )
    profile_id = created_profile.json()["id"]

    missing_key = client.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation_id, "provider_profile_id": profile_id},
        files={"file": ("招标.txt", "项目名称：测试项目".encode("utf-8"), "text/plain")},
    )
    assert missing_key.status_code == 400
    assert "API key" in missing_key.json()["detail"]

    keyed_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "DeepSeek",
            "display_name": "With Key",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "secret",
        },
    )
    keyed_profile_id = keyed_profile.json()["id"]
    parse_error = client.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation_id, "provider_profile_id": keyed_profile_id},
        files={"file": ("old.doc", b"abc", "application/msword")},
    )
    assert parse_error.status_code == 400
    assert "仅支持" in parse_error.json()["detail"]


def test_bid_workflow_upload_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr("backend.main.MAX_UPLOAD_BYTES", 8)
    created_project = client.post("/api/v1/projects", json={"title": "大文件项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "大文件"})
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI 大文件",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )

    response = client.post(
        "/api/v1/bid-workflows",
        data={"conversation_id": conversation_id, "provider_profile_id": created_profile.json()["id"]},
        files={"file": ("big.txt", b"0123456789", "text/plain")},
    )

    assert response.status_code == 400
    assert "上传文件不能超过" in response.json()["detail"]
