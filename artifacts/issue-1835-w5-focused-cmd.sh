#!/bin/sh
# issue-1835-w5 conflict-focused test command (do not use /tmp for the file list)
# Hard constraint: all seven MING_SIM_*_BIN prefixes must be set (not bare CODEX_BIN etc.).
cd "$(dirname "$0")/.." || exit 1
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line \
  $(cat artifacts/issue-1835-w5-conflict-tests.txt)
