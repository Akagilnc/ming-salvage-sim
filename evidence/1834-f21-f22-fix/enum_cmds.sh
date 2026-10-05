#!/bin/bash
# 1834 F21/F22 — actual executable enum commands (one-shot; no permanent classifier).
# Run from repo root. Outputs under evidence/1834-f21-f22-fix/enum_out/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/evidence/1834-f21-f22-fix/enum_out"
mkdir -p "$OUT"
export MING_ENUM_ROOT="$ROOT"
export MING_ENUM_OUT="$OUT"

echo "=== F21 CMD1: free-field crop write shapes (AST+TS line; not auto-KEEP) ==="
python3 evidence/1834-f21-f22-fix/scripts/enum_f21_free_field_crops.py | tee "$OUT/f21_run.stdout"
echo "F21_FREEISH_MD=$OUT/f21_freeish_crop_candidates.md"

echo "=== F21 CMD2: station/highlight/spoken preserve sites (dataflow confirm) ==="
rg -n --glob 'ming_sim/**/*.py' --glob 'web/src/**/*.{ts,tsx}' --glob '!web/src/**/*.{test,spec}.{ts,tsx}' \
  '人读 station|Free prose highlight|spoken if spoken\.strip|fromPayload\.trim\(\) \? fromPayload|out\.append\(item\)|payload\["station"\] = station'
echo "F21_CMD2_EXIT=$?"

echo "=== F22 CMD1: full-repo Python def + TS export + reference zero-consumer enum ==="
python3 evidence/1834-f21-f22-fix/scripts/enum_f22_full_defs_refs.py | tee "$OUT/f22_run.stdout"
echo "F22_ZERO_MD=$OUT/f22_zero_consumer_candidates.md"
echo "F22_ZERO_JSONL=$OUT/f22_zero_consumer_candidates.jsonl"
echo "F22_ALL_DEFS_JSONL=$OUT/f22_all_defs.jsonl"

echo "=== F22 CMD2: prove deleted symbols absent in live code ==="
for s in EN_VALUE_CN Suggestion ExtractionPendingStatus run_audience_turn_translation \
  stage_referral_candidate stage_revoke_authority_candidate season_option_contract_prompt \
  cluster_effect PromulgationHealEvidence release_previous_material_tree \
  _open_night_court_break apply_llm_config splitReportItems appointed_minister \
  registered_minister displaced_minister; do
  c=$(rg -n --glob '!evidence/**' --glob '!archive/**' --glob '!docs/**' "\\b${s}\\b" \
    ming_sim web_app.py web/src tests scripts main.py launcher.py spike_settle_tick.py 2>/dev/null | wc -l | tr -d ' ')
  echo "ABSENT_CHECK $s hits=$c"
done

echo "ENUM_DONE"
