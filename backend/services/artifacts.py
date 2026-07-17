import io
import re
import zipfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List


@dataclass(frozen=True)
class MarkdownSection:
    heading: str
    title: str
    body: str
    start: int
    end: int


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


def find_markdown_section(text: str, title: str) -> MarkdownSection:
    expected = title.strip()
    if not expected:
        raise ValueError("请输入要修改的章节标题。")
    matches = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        if match.group(2).strip() != expected:
            continue
        level = len(match.group(1))
        end = len(text)
        for next_match in matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        return MarkdownSection(
            heading=match.group(0).strip(),
            title=match.group(2).strip(),
            body=text[match.end() : end].strip(),
            start=match.start(),
            end=end,
        )
    raise ValueError(f"未找到标题为“{expected}”的 Markdown 章节。")


def replace_markdown_section(text: str, section: MarkdownSection, body: str) -> str:
    rewritten_body = body.strip()
    if not rewritten_body:
        raise ValueError("模型未返回章节正文，请重试。")
    replacement = f"{section.heading}\n\n{rewritten_body}"
    return f"{text[:section.start]}{replacement}{text[section.end:]}"


def markdown_line_diff(base_content: str, compare_content: str) -> list[dict[str, str]]:
    base_lines = base_content.splitlines()
    compare_lines = compare_content.splitlines()
    lines: list[dict[str, str]] = []
    for operation, base_start, base_end, compare_start, compare_end in SequenceMatcher(None, base_lines, compare_lines).get_opcodes():
        if operation == "equal":
            lines.extend({"kind": "unchanged", "content": line} for line in base_lines[base_start:base_end])
        elif operation in {"replace", "delete"}:
            lines.extend({"kind": "removed", "content": line} for line in base_lines[base_start:base_end])
        if operation in {"replace", "insert"}:
            lines.extend({"kind": "added", "content": line} for line in compare_lines[compare_start:compare_end])
    return lines


def has_confirmed_content(section: str) -> bool:
    unknown_values = {"未提及", "无", "待确认", "不适用", "-"}
    table_headers = {"检查项", "内容", "要求", "出处", "章节", "页码", "状态"}

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"\|?(?:\s*:?-+:?\s*\|)+", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) > 1:
            if all(cell in table_headers for cell in cells):
                continue
            values = cells[1:]
        else:
            values = [line.split("：", 1)[-1].split(":", 1)[-1].strip(" -")]
        if any(value and value not in unknown_values for value in values):
            return True
    return False


def build_output_files(extracted_markdown: str, design_proposal: str) -> Dict[str, str]:
    project_name = infer_project_name(extracted_markdown)
    drawing_prompts = extract_section(design_proposal, ["图文证据", "绘图提示词", "专业图纸需求", "图纸需求清单", "图纸清单"])
    bid_specs = extract_section(extracted_markdown, ["标书制作规范", "制作规范"])

    files = {
        f"{project_name}_招标文件信息提取.md": extracted_markdown,
        f"{project_name}_设计方案.md": design_proposal,
    }
    if drawing_prompts:
        files[f"{project_name}_图文证据与图纸需求.md"] = drawing_prompts
    if has_confirmed_content(bid_specs):
        files[f"{project_name}_标书制作规范.md"] = bid_specs
    return files


def make_zip(files: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()
