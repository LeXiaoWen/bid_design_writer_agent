from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from .workbench_store import data_dir


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("workflow_id", "kind", "user_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    logger = logging.getLogger("bid_design_writer")
    if logger.handlers:
        return
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    log_dir = data_dir() / "logs"
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "backend.jsonl", maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
