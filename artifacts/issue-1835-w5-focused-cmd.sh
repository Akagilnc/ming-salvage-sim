#!/bin/sh
# issue-1835-w5 conflict-focused test command (do not use /tmp for the file list)
cd "$(dirname "$0")/.." || exit 1
MING_SIM_AGY_BIN=/usr/bin/false \
CODEX_BIN=/usr/bin/false \
CLAUDE_BIN=/usr/bin/false \
CURSOR_BIN=/usr/bin/false \
KIMI_BIN=/usr/bin/false \
GROK_BIN=/usr/bin/false \
PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line \
  $(cat artifacts/issue-1835-w5-conflict-tests.txt)
