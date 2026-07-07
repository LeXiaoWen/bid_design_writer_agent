#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
python3 -m uvicorn backend.main:app --host "${AGENT_HOST:-127.0.0.1}" --port "${AGENT_PORT:-8765}" --reload
