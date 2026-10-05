#!/usr/bin/env bash
# #1847 w12 N11：人口单位旧档判别器退役后残余枚举（可回放）
set -euo pipefail
cd "$(dirname "$0")/../.."
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1

echo '=== A: py write/echo/API ==='
rg -n --glob '*.py' --glob '!evidence/**' \
  'POPULATION_UNIT_WAN|scale_content_population_to_save_unit|population_unit|save_meta|_mark_population_unit|_POPULATION_UNIT|POPULATION_UNIT_PERSONS' \
  ming_sim tests || true

echo '=== B: live contract docs + content meta ==='
rg -n 'population_unit|万人|无标|legacy.*人口|人口单位|随存档 population_unit' \
  docs/DELTA_SCHEMA.md ming_sim/constants.py content/regions.json || true

echo '=== C: ADR0088 (must remain untouched; cite only) ==='
rg -n 'population_unit|万人|legacy' \
  docs/adr/0088-population-unit-persons-aligned-with-manpower.md | head -20 || true
