from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..schemas import BidWorkflow, WorkbenchMessage
from .workbench_store import data_dir, ensure_private_directory, restrict_file_permissions, workbench_store


REPORT_FILENAME = "用户行为与需求摘要.md"


def behavior_report_root() -> Path:
    root = data_dir() / "behavior_reports"
    return ensure_private_directory(root)


def behavior_report_path(user_id: str, workflow_id: str) -> Path:
    return behavior_report_root() / user_id / workflow_id / REPORT_FILENAME


def redact_sensitive(text: str) -> str:
    redacted = text
    patterns = [
        (r"sk-[A-Za-z0-9_-]{12,}", "[已脱敏 API key]"),
        (r"Bearer\s+[A-Za-z0-9._-]{12,}", "Bearer [已脱敏]"),
        (r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[\S]+", r"\1=[已脱敏]"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[已脱敏邮箱]"),
        (r"\b1[3-9]\d{9}\b", "[已脱敏手机号]"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def shorten(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", redact_sensitive(text)).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _bullet_lines(values: Iterable[str], empty: str = "暂无明显记录。") -> str:
    items = [value for value in values if value]
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def _user_messages(messages: list[WorkbenchMessage]) -> list[WorkbenchMessage]:
    return [message for message in messages if message.role == "user" and message.content.strip()]


def _message_snippets(messages: list[WorkbenchMessage]) -> list[str]:
    snippets: list[str] = []
    for message in _user_messages(messages):
        content = message.content.strip()
        if content.startswith("已上传招标文件"):
            continue
        snippets.append(shorten(content, 180))
        if len(snippets) >= 6:
            break
    return snippets


def _issue_messages(messages: list[WorkbenchMessage]) -> list[str]:
    keywords = ("修改", "不对", "错误", "不要", "缺少", "补充", "调整", "重新", "不满意", "不符合")
    issues: list[str] = []
    for message in _user_messages(messages):
        if any(keyword in message.content for keyword in keywords):
            issues.append(shorten(message.content, 180))
        if len(issues) >= 5:
            break
    return issues


def _template_display(template_choice: str | None) -> str:
    return "按当前招标约束动态编排"


def build_behavior_report(
    workflow: BidWorkflow,
    messages: list[WorkbenchMessage],
    artifact_files: dict[str, str],
) -> str:
    artifact_lines = [
        f"{name}（{len(content.encode('utf-8'))} bytes）"
        for name, content in artifact_files.items()
    ]
    issue_lines = _issue_messages(messages)
    snippet_lines = _message_snippets(messages)
    confirmation = shorten(workflow.confirmation_text, 420) if workflow.confirmation_text else ""

    return "\n".join(
        [
            "# 用户行为与需求摘要",
            "",
            "## 一、用户目标",
            _bullet_lines(
                [
                    f"围绕招标文件 `{shorten(workflow.file_name, 120)}` 生成设计方案标书成果。",
                    f"阶段二目录结构选择：{_template_display(workflow.template_choice)}。",
                ]
            ),
            "",
            "## 二、补充/修正点",
            _bullet_lines([confirmation], "用户未提供额外补充或修正。"),
            "",
            "## 三、格式偏好",
            _bullet_lines(
                [
                    "需要输出可下载的 Markdown 文件和 ZIP 包。",
                    "偏好按招标文件实际内容自动判断目录结构，不固化为单一模板。",
                ]
            ),
            "",
            "## 四、阶段卡点",
            _bullet_lines(
                [
                    "阶段一完成后需要用户确认提取结果。",
                    "阶段二完成后需要明确展示 Markdown / ZIP 下载入口。",
                ]
            ),
            "",
            "## 五、不满意点",
            _bullet_lines(issue_lines, "本次有限片段中未识别到明确不满意表达。"),
            "",
            "## 六、对 Skill 流程的优化建议",
            _bullet_lines(
                [
                    "模板选择应基于招标文件实际章节、评分点和成果要求自动推断。",
                    "阶段二完成后应稳定展示下载入口，不阻塞用户继续下载。",
                    "后续可加入 LLM 摘要，但必须保留规则模板作为 fallback。",
                ]
            ),
            "",
            "## 七、关键短片段",
            _bullet_lines(snippet_lines, "暂无可摘录的用户短片段。"),
            "",
            "## 八、本次生成成果",
            _bullet_lines(artifact_lines, "暂无生成成果文件。"),
            "",
        ]
    )


def save_behavior_report(user_id: str, workflow_id: str) -> Path:
    workflow = workbench_store.get_bid_workflow(user_id, workflow_id)
    artifact_files = workbench_store.get_bid_artifact_files(user_id, workflow.id)
    messages = workbench_store.list_messages(user_id, workflow.conversation_id)
    report = build_behavior_report(workflow, messages, artifact_files)
    path = behavior_report_path(user_id, workflow.id)
    ensure_private_directory(path.parent)
    path.write_text(report, encoding="utf-8")
    restrict_file_permissions(path)
    return path
