import os
from functools import lru_cache
from pathlib import Path

from .config import TEMPLATE_FILES

BUNDLED_SKILL_NAME = "bid_design_writer"
BUNDLED_SKILL_DISPLAY = f"bundled:{BUNDLED_SKILL_NAME}"


def bundled_skill_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "bundled_skills" / BUNDLED_SKILL_NAME


def resolve_skill_dir() -> Path:
    override = os.getenv("BID_DESIGN_WRITER_SKILL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return bundled_skill_dir()


def skill_source_label() -> str:
    if os.getenv("BID_DESIGN_WRITER_SKILL_DIR", "").strip():
        return str(resolve_skill_dir())
    return BUNDLED_SKILL_DISPLAY


@lru_cache(maxsize=16)
def _load_skill_file(skill_dir: str, relative_path: str) -> str:
    path = Path(skill_dir) / relative_path
    if not path.exists():
        source = "外部覆盖路径" if os.getenv("BID_DESIGN_WRITER_SKILL_DIR", "").strip() else "内置资源"
        raise FileNotFoundError(f"未找到 bid-design-writer Skill {source}文件：{path}")
    return path.read_text(encoding="utf-8")


def load_skill_file(relative_path: str) -> str:
    return _load_skill_file(str(resolve_skill_dir()), relative_path)


def build_stage1_instructions() -> str:
    skill_md = load_skill_file("SKILL.md")
    checklist = load_skill_file("references/extraction-checklist.md")
    return f"""
{skill_md}

以下为阶段一补充提取清单：

{checklist}

当前运行在桌面应用中：
- 不要声称已经调用本地 Write 工具保存文件，后端会生成可下载成果。
- 输出必须使用 Markdown。
- 若文件信息缺失，标注“未提及”，不要猜测。
"""


def build_stage2_instructions(template_choice: str) -> str:
    skill_md = load_skill_file("SKILL.md")
    proposal_format = load_skill_file("references/proposal-format.md")
    if template_choice == "auto":
        design_template = load_skill_file(f"references/{TEMPLATE_FILES['12-chapter']}")
        consulting_template = load_skill_file(f"references/{TEMPLATE_FILES['5-chapter']}")
        template_section = f"""
以下为可参考的通用模板。请先根据阶段一提取结果判断：
- 如果招标文件明确规定目录结构，必须严格按招标文件目录组织，不使用通用模板替代。
- 如果招标文件未明确目录，纯设计标参考 12 章设计标模板；全过程咨询标参考 5 章全过程咨询标模板。
- 如果项目不是建筑工程类，应根据评分项和招标要求自定义目录，不机械套用 12 章或 5 章。

【12 章设计标模板参考】
{design_template}

【5 章全过程咨询标模板参考】
{consulting_template}
"""
    elif template_choice in TEMPLATE_FILES:
        template = load_skill_file(f"references/{TEMPLATE_FILES[template_choice]}")
        template_section = f"""
以下为用户选择的模板参考：

{template}
"""
    else:
        raise ValueError("模板选择无效，请使用 auto、12-chapter 或 5-chapter。")
    return f"""
{skill_md}

{template_section}

以下为标书格式规范参考：

{proposal_format}

当前运行在桌面应用中：
- 不要声称已经调用本地 Write 工具保存文件，后端会生成可下载成果。
- 输出必须使用 Markdown。
- 先输出章节级内容大纲，再输出正文。
- 单独保留“绘图提示词 + 专业图纸需求清单”章节，方便生成下载文件。
"""
