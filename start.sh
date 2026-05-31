#!/usr/bin/env bash
# 前端 build + 启 web_app。
# 用法：./start.sh [--port 8010] [--host 127.0.0.1] [--no-build]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

HOST="127.0.0.1"
PORT="8010"
DO_BUILD=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-build) DO_BUILD=0; shift ;;
    -h|--help)
      echo "Usage: $0 [--host HOST] [--port PORT] [--no-build]"
      exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

# 1. 注入 .env
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "[warn] 未找到 .env，LLM 相关变量未注入" >&2
fi

# 1b. 网页版默认开 LLM dump（每次调用 system/user/assistant 全文落 scripts/runs/llm_dump_<pid>.log）。
#     不想要就在 .env 里设 MING_SIM_DUMP_LLM=0 覆盖。
export MING_SIM_DUMP_LLM="${MING_SIM_DUMP_LLM:-1}"

# 2. 选 python：优先 .venv
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

# 3. 前端 build
if [[ "$DO_BUILD" -eq 1 ]]; then
  if [[ ! -d web/node_modules ]]; then
    echo "[start] 安装前端依赖"
    (cd web && npm install)
  fi
  echo "[start] 构建前端"
  (cd web && npm run build)
else
  echo "[start] 跳过前端 build (--no-build)"
fi

# 4. 启 uvicorn
echo "[start] 启动 web_app at http://${HOST}:${PORT}"
exec "$PY" -m uvicorn web_app:app --host "$HOST" --port "$PORT"
