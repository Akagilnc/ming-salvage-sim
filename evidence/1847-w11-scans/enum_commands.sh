#!/usr/bin/env bash
# #1847 w11 correction — replayable full-class enum commands
set -euo pipefail
cd "$(dirname "$0")/../.."
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD

echo '=== N11 old-archive compat / CREATE+ALTER / index rebuild ==='
rg -n --glob '*.py' 'POPULATION_UNIT_WAN|scale_content_population_to_save_unit|population_unit|无标|万人' ming_sim tests || true
rg -n --glob '*.py' 'ensure_column|ALTER TABLE|CREATE TABLE|DROP INDEX|CREATE INDEX|_ensure_.*index|dossier_progress_reports' ming_sim || true
rg -n --glob '*.py' 'season_option|validate_season_option|season_option_fields' ming_sim tests || true

echo '=== N13 DB exception swallow-to-empty ==='
rg -n --glob '*.py' 'except[[:space:]]+(sqlite3\.)?OperationalError' ming_sim tests web_app.py || true
rg -n --glob '*.py' '_secret_origin_message_protection|_withhold_origin_chat_messages|release_held_audience_knowledge|_brief_origin_chat_message_ids|_latest_held_user_chat_message_id' ming_sim/db.py || true

echo '=== N10 body-keyword auth guess ==='
rg -n --glob '*.py' 'fail_if_llm_error|_AGY_AUTH_MARKERS|incorrect api key|authentication timed out|Authentication required|error_markers' ming_sim tests web_app.py || true

echo '=== N14 illegal wording / helper-only / duplicate flow ==='
rg -n --glob 'tests/**/*.py' 'pytest\.raises\([^\n]*match\s*=' tests || true
rg -n --glob 'tests/**/*.py' 'expected_log|office_rank_band|office_leverage_multiplier|run_month_end_relation_brew|_run_relation_brew' tests || true
rg -n --glob 'tests/test_relation_brew_636.py' 'leg\.prepare\(|leg\.brew\(|leg\.persist\(' tests || true

echo '=== N16 cross-campaign old-name purge ==='
rg -n --glob '*.py' 'legacy_auto|prune_auto_saves|AUTO_SAVE_PREFIX' ming_sim tests || true
