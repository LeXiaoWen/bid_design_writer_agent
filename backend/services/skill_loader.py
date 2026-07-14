import os
from functools import lru_cache
from pathlib import Path

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
    return f"""
{skill_md}

当前运行在桌面应用中：
- 不要声称已经调用本地 Write 工具保存文件，后端会生成可下载成果。
- 输出必须使用 Markdown。
- 若文件信息缺失，标注“未提及”，不要猜测。
"""


def build_stage2_instructions() -> str:
    skill_md = load_skill_file("SKILL.md")
    reusable_modules = load_skill_file("references/可复用模块卡片.md")
    return f"""
{skill_md}

以下为候选模块卡片。它们不是默认目录、图纸清单或承诺来源；仅在当前招标条款、当前项目资料和责任边界同时匹配时调用其中的去项目化方法：

{reusable_modules}

当前运行在桌面应用中：
- 不要声称已经调用本地 Write 工具保存文件，后端会生成可下载成果。
- 输出必须使用 Markdown。
- 按当前招标约束动态编排，不使用预设章节模板；未被当前条款触发的图文、附表和文件不得输出。
"""
