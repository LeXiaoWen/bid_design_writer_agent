import os
import tempfile
import uuid
from pathlib import Path

# 确保测试运行时优先使用这些固定值，避免本地 .env 中的空值影响测试。
os.environ["APP_AUTH_SECRET"] = "test-app-secret"
os.environ["AI_WORKBENCH_TEST_MODE"] = "1"
os.environ["AI_WORKBENCH_DB_PATH"] = str(Path(tempfile.gettempdir()) / f"ai-workbench-test-{uuid.uuid4()}.db")
