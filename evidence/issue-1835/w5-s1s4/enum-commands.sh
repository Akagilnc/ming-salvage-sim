#!/usr/bin/env bash
# #1835 S1–S4 全仓机械枚举（类定义全文；不以变量名/键名/文件/点名符号收窄候选）
# 谓词实现见同目录 full_enum.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
PY="${MING_SIM_PYTHON:-/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python}"
OUT_MODE="${1:-pre}"
"$PY" "$ROOT/evidence/issue-1835/w5-s1s4/full_enum.py" "$OUT_MODE"
