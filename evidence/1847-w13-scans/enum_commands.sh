#!/usr/bin/env bash
# #1847 w13/w13-corr mechanical enumeration (replay)
# Predicates cover class-definition full text: selectors / unmarked legacy exec /
# R-W ends / dedicated tests / identity wrappers / idle-or-identical test flows.
# Not limited to fiscal point-names.
set -euo pipefail
cd "$(dirname "$0")/../.."
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD

echo '=== class mechanical enum (enum_members.py) ==='
python3 evidence/1847-w13-scans/enum_members.py

echo '=== class A supplemental rg (cutover / fiscal / wrapper) ==='
rg -n --glob '*.py' \
  'is_army_pay_source_cutover_enabled|_ARMY_PAY_SOURCE_CUTOVER|__army_pay_source_cutover|_mark_army_pay_source_cutover|fiscal_engine|__fiscal_engine|calc_province_fiscal|_content_population_effect_for_save|existing saves stay on legacy' \
  ming_sim tests web_app.py cli scripts || true

echo '=== class B supplemental: identical unused _run_exclusive / _ledger_count shapes ==='
rg -n --glob 'tests/**/*.py' 'def _run_exclusive|def _ledger_count|def _run_months|def _pop\(|def _global_population' tests || true
