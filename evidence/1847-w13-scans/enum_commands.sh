#!/usr/bin/env bash
# #1847 w13 mechanical enumeration (replay)
set -euo pipefail
cd "$(dirname "$0")/../.."
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
python3 evidence/1847-w13-scans/enum_members.py
