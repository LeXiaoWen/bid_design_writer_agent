import json
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache
def get_app_version() -> str:
    frozen_dir = getattr(sys, "_MEIPASS", None)
    candidates = []
    if frozen_dir:
        candidates.append(Path(frozen_dir) / "build" / "package.json")
    candidates.append(Path(__file__).resolve().parents[2] / "package.json")

    for path in candidates:
        try:
            version = json.loads(path.read_text(encoding="utf-8")).get("version")
            if isinstance(version, str) and version:
                return version
        except (OSError, json.JSONDecodeError):
            continue
    return "0.0.0"
