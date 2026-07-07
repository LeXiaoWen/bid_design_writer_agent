import io
import zipfile

import pytest
from docx import Document

from backend.schemas import ApiConfig
from backend.services.artifacts import build_output_files, extract_section, infer_project_name, make_zip
from backend.services.document_parser import parse_document
from backend.services.llm import create_agent


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
