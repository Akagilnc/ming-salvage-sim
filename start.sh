#!/usr/bin/env bash
# Build the frontend and launch the package's loopback browser entry.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PORT=8010
DO_BUILD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-build) DO_BUILD=0; shift ;;
    -h|--help) echo "Usage: $0 [--port PORT] [--no-build]"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" -m pip install -r requirements-ming.txt
if [[ "$DO_BUILD" -eq 1 ]]; then
  if [[ ! -d web/node_modules ]]; then (cd web && npm ci); fi
  (cd web && npm run build)
fi
exec "$PY" -m ming.desktop --port "$PORT"
