import io
import re
import zipfile
from typing import Dict, List

from ..schemas import ArtifactInfo


def infer_project_name(text: str) -> str:
    patterns = [
        r"项目名称[：:]\s*([^\n\r|]+)",
        r"#\s+(.+?)[—-]\s*招标文件信息提取",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = sanitize_filename(match.group(1).strip())
            if name and name not in {"未提及", "无"}:
                return name[:60]
    return "设计标书"


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "设计标书"


def extract_section(text: str, heading_keywords: List[str]) -> str:
    heading_pattern = re.compile(
        r"^(?:(?P<hash>#{1,6})\s+(?P<hash_title>.+)|"
        r"(?P<numbered>(?:第[一二三四五六七八九十0-9]+[章节部分]|[一二三四五六七八九十]+|[0-9]+)[、.．]\s*)(?P<numbered_title>.+)|"
        r"\*\*(?P<bold_title>.+?)\*\*)\s*$",
        flags=re.MULTILINE,
    )
    headings = []
    for match in heading_pattern.finditer(text):
        if match.group("hash"):
            level = len(match.group("hash"))
            title = match.group("hash_title")
        elif match.group("numbered"):
            marker = match.group("numbered")
            level = 2 if marker.startswith("第") else 3
            title = match.group("numbered_title")
        else:
            level = 4
            title = match.group("bold_title")
        headings.append((match, level, title.strip()))

    for index, heading in enumerate(headings):
        match, level, title = heading
        if any(keyword in title for keyword in heading_keywords):
            start = match.start()
            end = len(text)
            for next_heading, next_level, _ in headings[index + 1 :]:
                if next_level <= level:
                    end = next_heading.start()
                    break
            return text[start:end].strip()
    return ""


def _first_match(text: str, patterns: List[str], default: str = "未提及") -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            if value:
                return value[:120]
    return default


def _keyword_excerpts(text: str, keywords: List[str], limit: int = 8) -> List[str]:
    excerpts: List[str] = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.strip(" -\t|")
        if not line or len(line) < 6:
            continue
        if not any(keyword in line for keyword in keywords):
            continue
        normalized = re.sub(r"\s+", " ", line)
        if normalized in seen:
            continue
        seen.add(normalized)
        excerpts.append(normalized[:180])
        if len(excerpts) >= limit:
            break
    return excerpts


def _table_cell(value: str) -> str:
    return value.replace("|", " / ").replace("\n", " ").strip()


def build_drawing_requirements_fallback(extracted_markdown: str, design_proposal: str) -> str:
    project_name = infer_project_name(extracted_markdown)
    project_type = _first_match(
        extracted_markdown,
        [
            r"(?:项目类型|项目性质|工程类型)[：:]\s*([^\n\r|]+)",
            r"(?:建设内容|项目概况)[：:]\s*([^\n\r|]+)",
        ],
    )
    design_scope = _first_match(
        extracted_markdown,
        [
            r"(?:设计范围|服务范围|招标范围)[：:]\s*([^\n\r|]+)",
            r"(?:工作内容|服务内容)[：:]\s*([^\n\r|]+)",
        ],
    )
    deliverable_excerpts = _keyword_excerpts(
        extracted_markdown,
        ["图纸", "成果", "提交", "展板", "文本", "效果图", "总平面", "鸟瞰", "流线", "分析图", "设计深度"],
    )
    proposal_excerpts = _keyword_excerpts(
        design_proposal,
        ["总平面", "功能", "流线", "交通", "景观", "节点", "效果图", "立面", "空间", "策略"],
        limit=6,
    )

    basis_lines = deliverable_excerpts or proposal_excerpts or ["招标文件未明确列出图纸成果名称，以下清单按设计方案表达和常规建筑设计标书成果组织。"]
    drawing_rows = [
        ("01", "项目区位与现状分析图", "说明项目背景与基地条件", "区位关系、周边界面、现状资源、限制条件"),
        ("02", "总平面设计图", "作为方案总体表达核心图纸", "功能布局、空间结构、主要出入口、道路与开放空间"),
        ("03", "功能分区与业态组织图", "回应任务书和评分项中的功能要求", "核心功能、配套功能、公共空间、运营关系"),
        ("04", "交通组织与流线分析图", "说明人车流线和到达系统", "车行、人行、消防、后勤、停车及慢行系统"),
        ("05", "景观与开放空间系统图", "表达环境品质和公共空间策略", "景观轴线、节点空间、绿化系统、活动场地"),
        ("06", "重点节点效果图", "增强评审可读性和方案感染力", "入口界面、核心公共空间、特色节点、夜景或人视角"),
        ("07", "建筑形象或立面意向图", "说明建筑风貌与材料策略", "立面秩序、材料色彩、天际线、界面控制"),
        ("08", "专项分析图", "补充回应招标文件重点要求", "低碳节能、海绵城市、无障碍、消防或实施分期等"),
    ]

    prompt_lines = [
        f"以“{project_name}”为对象，生成建筑设计投标方案图纸，整体风格专业、清晰、适合评标汇报。",
        f"项目类型/建设内容：{project_type}；设计范围：{design_scope}。",
        "图面应突出总平面逻辑、功能组织、交通流线、景观节点、建筑形象和评分响应关系。",
        "表达方式采用建筑竞标文本风格，版式干净，标注清晰，避免营销化渲染和无依据夸张表达。",
    ]

    return "\n".join(
        [
            "## 绘图提示词 + 专业图纸需求清单",
            "",
            "### 生成依据",
            "",
            *[f"- {line}" for line in basis_lines],
            "",
            "### 绘图提示词",
            "",
            *[f"- {line}" for line in prompt_lines],
            "",
            "### 专业图纸需求清单",
            "",
            "| 序号 | 图纸名称 | 用途 | 主要表达内容 |",
            "| --- | --- | --- | --- |",
            *[f"| {number} | {_table_cell(name)} | {_table_cell(purpose)} | {_table_cell(content)} |" for number, name, purpose, content in drawing_rows],
            "",
            "### 使用说明",
            "",
            "- 若招标文件已明确成果图纸名称、比例、数量或深度要求，应以招标文件为准。",
            "- 未明确要求的图纸可作为方案表达建议，后续应结合项目类型、设计深度和投标页数进行取舍。",
        ]
    )


def build_output_files(extracted_markdown: str, design_proposal: str) -> Dict[str, str]:
    project_name = infer_project_name(extracted_markdown)
    drawing_prompts = extract_section(design_proposal, ["绘图提示词", "专业图纸需求", "图纸需求清单", "图纸清单"])
    bid_specs = extract_section(extracted_markdown, ["标书制作规范", "制作规范"])

    if not drawing_prompts:
        drawing_prompts = build_drawing_requirements_fallback(extracted_markdown, design_proposal)
    if not bid_specs:
        bid_specs = "## 标书制作规范\n\n阶段一提取结果中未找到独立的标书制作规范章节，请回看完整信息提取文件。"

    return {
        f"{project_name}_招标文件信息提取.md": extracted_markdown,
        f"{project_name}_设计方案.md": design_proposal,
        f"{project_name}_绘图提示词_图纸需求清单.md": drawing_prompts,
        f"{project_name}_标书制作规范.md": bid_specs,
    }


def list_artifacts(files: Dict[str, str]) -> List[ArtifactInfo]:
    infos = []
    for name, content in files.items():
        if "信息提取" in name:
            kind = "extraction"
        elif "设计方案" in name:
            kind = "proposal"
        elif "绘图提示词" in name:
            kind = "drawing"
        elif "标书制作规范" in name:
            kind = "spec"
        else:
            kind = "file"
        infos.append(ArtifactInfo(name=name, size=len(content.encode("utf-8")), kind=kind))
    return infos


def make_zip(files: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()
