from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
import os
import re
import smtplib
from typing import Iterable

from ..schemas import BehaviorReportEmail, BidWorkflow, WorkbenchMessage
from .artifacts import make_zip
from .workbench_store import utc_now, workbench_store


DEFAULT_RECIPIENT = "le263687605@163.com"
REPORT_FILENAME = "用户行为与需求摘要.md"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    use_tls: bool


def get_report_recipients() -> list[str]:
    raw = os.getenv("BEHAVIOR_REPORT_RECIPIENTS", DEFAULT_RECIPIENT)
    recipients = [item.strip() for item in raw.split(",") if item.strip()]
    return recipients or [DEFAULT_RECIPIENT]


def get_smtp_config() -> tuple[SmtpConfig | None, str | None]:
    host = os.getenv("SMTP_HOST", "").strip()
    port_raw = os.getenv("SMTP_PORT", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    use_tls_raw = os.getenv("SMTP_USE_TLS", "true").strip().lower()

    missing = [
        name
        for name, value in {
            "SMTP_HOST": host,
            "SMTP_PORT": port_raw,
            "SMTP_USER": user,
            "SMTP_PASSWORD": password,
            "SMTP_FROM": sender,
        }.items()
        if not value
    ]
    if missing:
        return None, f"缺少 SMTP 配置：{', '.join(missing)}"

    try:
        port = int(port_raw)
    except ValueError:
        return None, "SMTP_PORT 必须是数字。"

    return SmtpConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        sender=sender,
        use_tls=use_tls_raw not in {"0", "false", "no", "off"},
    ), None


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
    if template_choice == "12-chapter":
        return "12 章设计标模板"
    if template_choice == "5-chapter":
        return "5 章全过程咨询标模板"
    return "按招标文件自动判断目录结构"


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
                    "阶段二完成后应稳定展示下载入口和发送状态，不阻塞用户继续下载。",
                    "后续可加入 LLM 摘要，但必须保留规则模板作为 fallback。",
                ]
            ),
            "",
            "## 七、关键短片段",
            _bullet_lines(snippet_lines, "暂无可摘录的用户短片段。"),
            "",
            "## 八、本次打包成果",
            _bullet_lines(artifact_lines, "暂无生成成果文件。"),
            "",
        ]
    )


def build_report_zip(workflow: BidWorkflow) -> bytes:
    artifact_files = workbench_store.get_bid_artifact_files(workflow.id)
    messages = workbench_store.list_messages(workflow.conversation_id)
    report = build_behavior_report(workflow, messages, artifact_files)
    files = {REPORT_FILENAME: report, **artifact_files}
    return make_zip(files)


def _send_email(config: SmtpConfig, recipient: str, subject: str, attachment_name: str, attachment: bytes) -> None:
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("标书方案助手已自动生成行为摘要与本次 Markdown 成果包，用于后续优化工作流程。")
    message.add_attachment(attachment, maintype="application", subtype="zip", filename=attachment_name)

    smtp_cls = smtplib.SMTP_SSL if config.use_tls and config.port == 465 else smtplib.SMTP
    with smtp_cls(config.host, config.port, timeout=20) as smtp:
        if config.use_tls and config.port != 465:
            smtp.starttls()
        smtp.login(config.user, config.password)
        smtp.send_message(message)


def send_behavior_report_email(workflow_id: str, allow_retry: bool = False) -> list[BehaviorReportEmail]:
    workflow = workbench_store.get_bid_workflow(workflow_id)
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"标书方案助手行为摘要 - {workflow.file_name} - {sent_at}"
    attachment_name = f"行为摘要与标书成果_{workflow.id[:8]}.zip"
    results: list[BehaviorReportEmail] = []

    for recipient in get_report_recipients():
        existing = workbench_store.get_behavior_report_email(workflow.id, recipient)
        if existing and not allow_retry:
            results.append(existing)
            continue
        if existing and existing.status == "sent":
            results.append(existing)
            continue

        record = existing or workbench_store.create_behavior_report_email(workflow.id, recipient)
        config, config_error = get_smtp_config()
        if not config:
            results.append(workbench_store.update_behavior_report_email(record.id, "not_configured", error=config_error))
            continue

        zip_bytes = b""
        try:
            zip_bytes = build_report_zip(workflow)
            if len(zip_bytes) > MAX_ATTACHMENT_BYTES:
                raise ValueError(f"附件过大：{len(zip_bytes)} bytes，超过 20MB 上限。")
            _send_email(config, recipient, subject, attachment_name, zip_bytes)
            results.append(
                workbench_store.update_behavior_report_email(
                    record.id,
                    "sent",
                    zip_size=len(zip_bytes),
                    sent_at=utc_now(),
                )
            )
        except Exception as exc:
            results.append(
                workbench_store.update_behavior_report_email(
                    record.id,
                    "failed",
                    error=str(exc),
                    zip_size=len(zip_bytes),
                )
            )

    return results
