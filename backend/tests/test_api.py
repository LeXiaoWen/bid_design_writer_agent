import io
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ["AI_WORKBENCH_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"ai-workbench-test-{uuid4()}.db")
os.environ["AI_WORKBENCH_ALLOW_MEMORY_CREDENTIALS"] = "true"
os.environ["APP_AUTH_SECRET"] = "test-app-secret"

from backend.main import app
from backend.schemas import BidWorkflowStatus, ProviderModel
from backend.services import behavior_report_email as behavior_report_email_service
from backend.services.behavior_report_email import REPORT_FILENAME, send_behavior_report_email
from backend.services.workbench_store import workbench_store


client = TestClient(app)
auth_response = client.post("/api/v1/auth/setup", json={"username": "tester", "password": "test-password"})
assert auth_response.status_code == 200
client.headers.update(
    {
        "Authorization": f"Bearer {auth_response.json()['token']}",
        "X-App-Auth-Secret": "test-app-secret",
    }
)


def test_health_identifies_ai_workbench_backend():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["app"] == "ai-workbench-desktop"
    assert payload["legacy_app"] == "bid-design-writer-desktop"
    assert "database" in payload
    assert "presets" in payload


def test_v1_routes_require_app_secret_and_login():
    bare_client = TestClient(app)
    no_secret = bare_client.get("/api/v1/projects")
    assert no_secret.status_code == 403

    no_token = bare_client.get("/api/v1/projects", headers={"X-App-Auth-Secret": "test-app-secret"})
    assert no_token.status_code == 401

    status = bare_client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json()["setup_required"] is False
    assert status.json()["authenticated"] is False


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


def test_create_project_and_missing_file_guard():
    created = client.post("/api/projects")
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    fetched = client.get(f"/api/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == project_id

    response = client.post(
        f"/api/projects/{project_id}/extract",
        json={
            "api_config": {
                "provider": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test",
                "model": "gpt-4o",
            }
        },
    )
    assert response.status_code == 400
    assert "请先上传" in response.json()["detail"]


def test_upload_txt_and_artifact_guard():
    created = client.post("/api/projects")
    project_id = created.json()["project_id"]

    upload = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("招标.txt", "项目名称：测试项目".encode("utf-8"), "text/plain")},
    )
    assert upload.status_code == 200
    assert upload.json()["stage"] == "uploaded"

    artifacts = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json() == []

    export = client.get(f"/api/projects/{project_id}/export.zip")
    assert export.status_code == 404


def test_confirm_before_extract_is_rejected():
    created = client.post("/api/projects")
    project_id = created.json()["project_id"]
    response = client.post(f"/api/projects/{project_id}/confirm", json={"text": "确认"})
    assert response.status_code == 400
    assert "阶段一" in response.json()["detail"]


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

    async def fake_fetch(profile_id_arg: str):
        assert profile_id_arg == profile_id
        return [
            ProviderModel(id="deepseek-chat", name="deepseek-chat"),
            ProviderModel(id="deepseek-reasoner", name="deepseek-reasoner"),
        ]

    monkeypatch.setattr("backend.main.fetch_provider_models", fake_fetch)

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
        conversation_id=conversation_id,
        provider_profile_id=profile_id,
        file_name="招标文件.txt",
        file_text="项目名称：测试标书项目",
    )

    assert workflow.project_id == project_id
    assert workflow.status == BidWorkflowStatus.UPLOADED
    assert workflow.file_name == "招标文件.txt"
    assert workbench_store.get_active_bid_workflow(conversation_id).id == workflow.id

    with pytest.raises(ValueError, match="已有未完成"):
        workbench_store.create_bid_workflow(
            conversation_id=conversation_id,
            provider_profile_id=profile_id,
            file_name="另一个招标文件.txt",
            file_text="项目名称：另一个项目",
        )

    extracting = workbench_store.update_bid_workflow_status(workflow.id, BidWorkflowStatus.EXTRACTING)
    assert extracting.status == BidWorkflowStatus.EXTRACTING

    extracted = workbench_store.save_bid_extraction(workflow.id, "# 测试标书项目 — 招标文件信息提取")
    assert extracted.status == BidWorkflowStatus.EXTRACTION_READY
    assert "信息提取" in extracted.extracted_markdown

    confirmed = workbench_store.save_bid_confirmation(workflow.id, "确认，并补充企业优势。")
    assert confirmed.confirmation_text == "确认，并补充企业优势。"

    templated = workbench_store.save_bid_template_choice(workflow.id, "12-chapter")
    assert templated.template_choice == "12-chapter"

    artifacts = workbench_store.save_bid_artifacts(
        workflow.id,
        {
            "测试标书项目_招标文件信息提取.md": extracted.extracted_markdown,
            "测试标书项目_设计方案.md": "# 设计方案",
        },
    )
    completed = workbench_store.get_bid_workflow(workflow.id)

    assert completed.status == BidWorkflowStatus.COMPLETED
    assert workbench_store.get_active_bid_workflow(conversation_id) is None
    assert [artifact.kind for artifact in artifacts] == ["extraction", "proposal"]
    assert workbench_store.get_bid_artifact_content(workflow.id, "测试标书项目_设计方案.md") == "# 设计方案"


def test_bid_workflow_v1_full_chain(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        monkeypatch.delenv(key, raising=False)

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

    def fake_run_agent(api_config, instructions, prompt):
        seen_models.append(api_config.model)
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
    assert workflow["status"] == "extraction_ready"
    assert "信息提取" in workflow["extracted_markdown"]

    confirm = client.post(f"/api/v1/bid-workflows/{workflow_id}/confirm", json={"text": "确认，并补充企业优势。"})
    assert confirm.status_code == 200
    assert "补充企业优势" in confirm.json()["workflow"]["confirmation_text"]

    generate = client.post(
        f"/api/v1/bid-workflows/{workflow_id}/generate",
        json={"template_choice": "auto", "extra_context": "采用低碳设计策略。"},
    )
    assert generate.status_code == 200

    completed = client.get(f"/api/v1/bid-workflows/{workflow_id}").json()
    assert completed["status"] == "completed"
    assert completed["template_choice"] == "auto"
    assert len(completed["artifacts"]) == 4
    assert seen_models == ["deepseek-chat", "deepseek-chat"]

    listed = client.get("/api/v1/bid-workflows", params={"conversation_id": conversation_id})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == workflow_id
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

    email_status = client.get(f"/api/v1/bid-workflows/{workflow_id}/report-email-status")
    assert email_status.status_code == 200
    assert email_status.json()[0]["status"] == "not_configured"
    assert "SMTP" in email_status.json()[0]["error"]

    search = client.get("/api/v1/search", params={"q": "信息提取"})
    assert search.status_code == 200
    assert any(item["conversation_id"] == conversation_id for item in search.json())


def _create_completed_bid_workflow() -> str:
    created_project = client.post("/api/v1/projects", json={"title": "邮件报告项目"})
    project_id = created_project.json()["id"]
    created_conversation = client.post("/api/v1/conversations", json={"project_id": project_id, "title": "邮件报告对话"})
    conversation_id = created_conversation.json()["id"]
    created_profile = client.post(
        "/api/v1/provider-profiles",
        json={
            "provider": "OpenAI",
            "display_name": "OpenAI 邮件报告",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key": "secret",
        },
    )
    workflow = workbench_store.create_bid_workflow(
        conversation_id=conversation_id,
        provider_profile_id=created_profile.json()["id"],
        file_name="邮件招标文件.txt",
        file_text="原始招标文件全文不应进入行为报告。项目名称：邮件测试项目。",
    )
    workbench_store.add_message(conversation_id, "user", "请补充低碳策略，api_key=sk-1234567890abcdef")
    workbench_store.save_bid_extraction(workflow.id, "# 邮件测试项目 — 招标文件信息提取")
    workbench_store.save_bid_confirmation(workflow.id, "确认，并补充低碳策略。token=sk-1234567890abcdef")
    workbench_store.save_bid_template_choice(workflow.id, "auto")
    workbench_store.save_bid_artifacts(
        workflow.id,
        {
            "邮件测试项目_招标文件信息提取.md": "# 信息提取",
            "邮件测试项目_设计方案.md": "# 设计方案",
        },
    )
    return workflow.id


def test_behavior_report_email_sends_zip_and_is_idempotent(monkeypatch):
    sent_messages = []

    class FakeSmtp:
        def __init__(self, host, port, timeout=None):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 20

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, user, password):
            assert user == "sender@example.com"
            assert password == "auth-code"

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "auth-code")
    monkeypatch.setenv("SMTP_FROM", "sender@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("BEHAVIOR_REPORT_RECIPIENTS", "ops@example.com")
    monkeypatch.setattr(behavior_report_email_service.smtplib, "SMTP", FakeSmtp)

    workflow_id = _create_completed_bid_workflow()
    records = send_behavior_report_email(workflow_id)

    assert records[0].status == "sent"
    assert records[0].recipient == "ops@example.com"
    assert records[0].zip_size > 0
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "ops@example.com"
    assert sent_messages[0]["Subject"].startswith("标书方案助手行为摘要 - 邮件招标文件.txt - ")

    attachment = list(sent_messages[0].iter_attachments())[0]
    assert attachment.get_filename().startswith(f"行为摘要与标书成果_{workflow_id[:8]}")
    with zipfile.ZipFile(io.BytesIO(attachment.get_payload(decode=True))) as archive:
        names = archive.namelist()
        report = archive.read(REPORT_FILENAME).decode("utf-8")
        assert REPORT_FILENAME in names
        assert "邮件测试项目_设计方案.md" in names
        assert "用户行为与需求摘要" in report
        assert "原始招标文件全文不应进入行为报告" not in report
        assert "sk-1234567890abcdef" not in report
        assert "已脱敏" in report

    duplicate = send_behavior_report_email(workflow_id)
    assert duplicate[0].status == "sent"
    assert len(sent_messages) == 1


def test_behavior_report_email_rejects_oversized_zip(monkeypatch):
    sent_messages = []

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, user, password):
            return None

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "auth-code")
    monkeypatch.setenv("SMTP_FROM", "sender@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("BEHAVIOR_REPORT_RECIPIENTS", "ops@example.com")
    monkeypatch.setattr(behavior_report_email_service.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(behavior_report_email_service, "MAX_ATTACHMENT_BYTES", 16)

    records = send_behavior_report_email(_create_completed_bid_workflow())

    assert records[0].status == "failed"
    assert "附件过大" in records[0].error
    assert sent_messages == []


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
        conversation_id=conversation_id,
        provider_profile_id=created_profile.json()["id"],
        file_name="取消阶段一.txt",
        file_text="项目名称：取消阶段一项目",
    )
    workbench_store.update_bid_workflow_status(workflow.id, BidWorkflowStatus.EXTRACTING)

    def fake_run_agent(api_config, instructions, prompt):
        workbench_store.update_bid_workflow_status(workflow.id, BidWorkflowStatus.CANCELLED)
        return "# 迟到的阶段一结果"

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)

    from backend.main import run_bid_extraction_task

    run_bid_extraction_task(workflow.id)
    cancelled = workbench_store.get_bid_workflow(workflow.id)
    assert cancelled.status == BidWorkflowStatus.CANCELLED
    assert cancelled.extracted_markdown == ""


def test_bid_workflow_cancel_prevents_late_generation_save(monkeypatch):
    workflow_id = _create_completed_bid_workflow()
    workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.GENERATING)

    def fake_run_agent(api_config, instructions, prompt):
        workbench_store.update_bid_workflow_status(workflow_id, BidWorkflowStatus.CANCELLED)
        return "## 迟到的设计方案"

    monkeypatch.setattr("backend.main.run_agent", fake_run_agent)

    from backend.main import run_bid_generation_task

    run_bid_generation_task(workflow_id)
    cancelled = workbench_store.get_bid_workflow(workflow_id)
    assert cancelled.status == BidWorkflowStatus.CANCELLED
    assert workbench_store.get_bid_artifact_content(workflow_id, "邮件测试项目_设计方案.md") == "# 设计方案"


def test_bid_workflow_cancel_endpoint_rejects_completed_workflow():
    workflow_id = _create_completed_bid_workflow()
    response = client.post(f"/api/v1/bid-workflows/{workflow_id}/cancel")
    assert response.status_code == 400
    assert "已完成" in response.json()["detail"]


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
