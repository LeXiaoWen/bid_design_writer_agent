import io
import asyncio
import zipfile

import pytest
from docx import Document

from backend.schemas import ApiConfig, WebSearchConfig
from backend.services.artifacts import build_output_files, extract_section, infer_project_name, make_zip
from backend.services.document_parser import parse_document
from backend.services.llm import create_agent
from backend.services.skill_loader import build_stage1_instructions, build_stage2_instructions, skill_source_label
from backend.services.web_search import WebSearchNotConfiguredError, build_search_context, tavily_search


def make_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def test_parse_txt_document():
    assert parse_document("招标.txt", "项目名称：测试项目".encode("utf-8")) == "项目名称：测试项目"


def test_parse_docx_document():
    parsed = parse_document("招标.docx", make_docx_bytes("项目名称：DOCX 项目"))
    assert "DOCX 项目" in parsed


def test_empty_file_error():
    with pytest.raises(ValueError, match="文件为空"):
        parse_document("empty.txt", b"")


def test_unsupported_file_error():
    with pytest.raises(ValueError, match="仅支持"):
        parse_document("old.doc", b"abc")


def test_project_name_sanitizes_illegal_chars():
    assert infer_project_name("项目名称：A/B:C*D?E") == "ABCDE"


def test_artifacts_and_zip_generation():
    files = build_output_files(
        "项目名称：测试项目\n## 四、标书制作规范\n字体要求",
        "## 方案正文\n内容\n## 绘图提示词 + 专业图纸需求清单\n提示词",
    )
    assert "测试项目_设计方案.md" in files
    zipped = make_zip(files)
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        assert "测试项目_设计方案.md" in archive.namelist()


def test_extract_section_accepts_numbered_heading():
    section = extract_section("一、方案正文\n内容\n二、绘图提示词 + 专业图纸需求清单\n图纸内容", ["绘图提示词"])
    assert "图纸内容" in section


def test_extract_section_keeps_child_headings():
    section = extract_section(
        "## 方案正文\n内容\n## 绘图提示词 + 专业图纸需求清单\n说明\n### 一、绘图提示词\n提示词正文\n### 二、专业图纸需求清单\n清单正文\n## 标书制作规范\n规范",
        ["绘图提示词"],
    )
    assert "提示词正文" in section
    assert "清单正文" in section
    assert "标书制作规范" not in section


def test_drawing_artifact_has_fallback_content():
    files = build_output_files(
        "项目名称：测试项目\n项目概况：公共建筑\n设计范围：方案设计\n成果提交：总平面图、效果图、分析图",
        "## 方案正文\n功能分区、交通组织、景观节点设计。",
    )
    drawing = files["测试项目_绘图提示词_图纸需求清单.md"]
    assert "模型未单独输出" not in drawing
    assert "专业图纸需求清单" in drawing
    assert "总平面设计图" in drawing
    assert "成果提交：总平面图、效果图、分析图" in drawing


def test_openai_compatible_agent_accepts_base_url():
    agent = create_agent(
        ApiConfig(
            provider="DeepSeek",
            base_url="https://api.deepseek.com",
            api_key="test-key",
            model="deepseek-v4-pro",
        ),
        "test",
    )
    assert agent is not None
    assert agent.model.role_map["system"] == "system"


def write_test_skill(root):
    references = root / "references"
    references.mkdir()
    (root / "SKILL.md").write_text("# 外部测试 Skill\n", encoding="utf-8")
    (references / "extraction-checklist.md").write_text("外部阶段一清单", encoding="utf-8")
    (references / "proposal-format.md").write_text("外部格式规范", encoding="utf-8")
    (references / "设计标书大纲模板参考.md").write_text("外部 12 章模板", encoding="utf-8")
    (references / "设计标书大纲模板参考-全过程咨询标.md").write_text("外部 5 章模板", encoding="utf-8")


def test_skill_loader_uses_bundled_skill_by_default(monkeypatch):
    monkeypatch.delenv("BID_DESIGN_WRITER_SKILL_DIR", raising=False)

    assert skill_source_label() == "bundled:bid_design_writer"
    instructions = build_stage1_instructions()
    assert "招标设计方案编写助手" in instructions
    assert "阶段一补充提取清单" in instructions


def test_skill_loader_accepts_explicit_external_override(tmp_path, monkeypatch):
    write_test_skill(tmp_path)
    monkeypatch.setenv("BID_DESIGN_WRITER_SKILL_DIR", str(tmp_path))

    assert skill_source_label() == str(tmp_path)
    assert "外部测试 Skill" in build_stage1_instructions()
    assert "外部 12 章模板" in build_stage2_instructions("12-chapter")


def test_skill_loader_invalid_external_override_does_not_fallback(tmp_path, monkeypatch):
    missing = tmp_path / "missing-skill"
    monkeypatch.setenv("BID_DESIGN_WRITER_SKILL_DIR", str(missing))

    with pytest.raises(FileNotFoundError, match="外部覆盖路径"):
        build_stage1_instructions()


def test_skill_loader_reads_all_supported_templates(monkeypatch):
    monkeypatch.delenv("BID_DESIGN_WRITER_SKILL_DIR", raising=False)

    assert "12 章设计标模板参考" in build_stage2_instructions("auto")
    assert "用户选择的模板参考" in build_stage2_instructions("12-chapter")
    assert "用户选择的模板参考" in build_stage2_instructions("5-chapter")


def test_tavily_search_requires_api_key(monkeypatch):
    monkeypatch.setattr("backend.services.web_search.workbench_store.resolve_tavily_api_key", lambda: None)
    monkeypatch.setattr("backend.services.web_search.workbench_store.get_web_search_config", lambda: WebSearchConfig())

    with pytest.raises(WebSearchNotConfiguredError, match="TAVILY_API_KEY"):
        asyncio.run(tavily_search("AI workbench"))


def test_tavily_search_calls_api_and_builds_context(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "Result A", "url": "https://example.com/a", "content": "A summary"},
                    {"title": "Result B", "url": "https://example.com/b", "content": "B summary"},
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 20

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("backend.services.web_search.workbench_store.resolve_tavily_api_key", lambda: "test-key")
    monkeypatch.setattr(
        "backend.services.web_search.workbench_store.get_web_search_config",
        lambda: WebSearchConfig(has_key=True, source="keychain", max_results=2, search_depth="basic"),
    )
    monkeypatch.setattr("backend.services.web_search.httpx.AsyncClient", FakeClient)

    results = asyncio.run(tavily_search("AI workbench"))
    context = build_search_context(results)

    assert captured["endpoint"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["query"] == "AI workbench"
    assert captured["json"]["max_results"] == 2
    assert results[0].title == "Result A"
    assert "[1] Result A" in context
    assert "https://example.com/b" in context
