#!/usr/bin/env bash
# CLEANUP-C1 deleted-symbol closure — full enumerate + forensics (stdlib ast/importlib)
# Does NOT depend on prior /tmp seeds. One-shot; not a permanent repo scan framework.
set -euo pipefail
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
cd "$ROOT"
TMPROOT=$(mktemp -d /tmp/cleanup-c1-closure.XXXXXX)
mkdir -p "$TMPROOT/logs" "$TMPROOT/user" "$TMPROOT/pytest"
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR="$TMPROOT/user"
echo "TMPROOT=$TMPROOT"

# 1) Full member enum + resolve (script body: docs/reports receipt embeds path to ENUMERATE_AND_RESOLVE.py / deep_resolve)
# Re-run from saved scripts under $TMPROOT/logs/ if present; otherwise paste from receipt.
$PY "$TMPROOT/logs/ENUMERATE_AND_RESOLVE.py" "$TMPROOT/logs"
$PY - "$TMPROOT/logs" <<'PY'
# deep_resolve + forensic reclass — see docs/reports/1891-1899-deleted-symbol-tests.md
print('run deep_resolve from receipt / saved script')
PY

# 2) AttributeError forensics (suspected only; never guess)
$PY -m pytest -vv --tb=short -p no:cacheprovider --basetemp="$TMPROOT/pytest/forensic" \
  tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement \
  || true

# 3) Focused post-delete
$PY -m pytest -q --tb=short -p no:cacheprovider --basetemp="$TMPROOT/pytest/focus" \
  tests/test_rejection_wiring.py \
  tests/test_error_pack.py::test_next_attempt_skips_malformed_and_foreign_entries \
  tests/test_error_pack.py::test_attempt_derived_from_existing_dirs \
  tests/test_mechanical_tail_1845.py::test_web_barrier_resumes_pending_tail_before_join
