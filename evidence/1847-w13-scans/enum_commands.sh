#!/usr/bin/env bash
# #1847 w14 mechanical enumeration (replay)
# Predicates: general legacy/compat/migrate/backfill/identity + idle/duplicate test flows.
# Roots: git ls-files executable (py/ts/tsx/js), not fiscal point-name dirs only.
set -euo pipefail
cd "$(dirname "$0")/../.."
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD

echo '=== class mechanical enum (enum_members.py via git ls-files) ==='
python3 evidence/1847-w13-scans/enum_members.py

echo '=== class A supplemental rg (general compat/migrate/backfill) ==='
rg -n --glob '*.py' --glob '*.ts' --glob '*.tsx' --glob '*.js' \
  '缺省兼容|兼容旧|旧客户端|旧档|旧存档|保留兼容|compatibility alias|cutover|backfill|_migrate_|ensure_column|existing saves stay on legacy|__fiscal_engine|__army_pay_source_cutover|population_unit|test_old_save|test_legacy_' \
  ming_sim tests web_app.py main.py launcher.py spike_settle_tick.py scripts web/src \
  || true

echo '=== class B supplemental: remaining idle/duplicate helper defs ==='
rg -n --glob 'tests/**/*.py' 'def _run_exclusive|def _ledger_count|def _null_cm|def _pay_source|def _click_before|def _pop\(|def _add_edge|def _forbid_extractor' tests || true
