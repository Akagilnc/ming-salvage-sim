#!/bin/bash
# F21/F22 mechanical enumeration commands (no auto-classifier layer)
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=evidence/1834-f21-f22-fix

echo "=== F21 CMD1: broad rewrite shapes (input/write/read/materialize/supply/frontend) ==="
rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' --glob 'web/src/**/*.{ts,tsx}' \
  --glob '!web/src/**/*.{test,spec}.{ts,tsx}' \
  '\.strip\(\)|\.lstrip\(\)|\.rstrip\(\)|\.trim\(\)|\.trimStart\(\)|\.trimEnd\(\)|re\.sub\(|\[:\s*\d+\s*\]' \
  > "$OUT/enum_f21_broad.txt" || true
wc -l "$OUT/enum_f21_broad.txt"

echo "=== F21 CMD2: assignment/return of strip|trim (high-signal rewrite) ==="
rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' --glob 'web/src/**/*.{ts,tsx}' \
  --glob '!web/src/**/*.{test,spec}.{ts,tsx}' \
  '(^=\s*.*\.strip\(\)|=\s*str\([^)]*\)\.strip\(\)|out\.append\([^)]*\.strip\(\)|return\s+.*\.strip\(\)|yield\s+.*\.strip\(\)|\.trim\(\)\s*[;,\)]|\.map\([^)]*\.trim)' \
  > "$OUT/enum_f21_assign_strip.txt" || true
wc -l "$OUT/enum_f21_assign_strip.txt"

echo "=== F21 CMD3: judge sample locs + station/highlights free-field rewrite ==="
rg -n 'station = str\(.*\)\.strip\(\)|dest = str\(station.*\)\.strip\(\)|out\.append\(item\.strip\(\)\)|highlights.*strip|item\.strip\(\)' \
  ming_sim/rescript_actions.py ming_sim/db.py web/src/highlights.ts \
  > "$OUT/enum_f21_samples.txt" || true

echo "=== F22 CMD1: retired / zero-consumer symbols from judge + expansion ==="
rg -n '_target_active_officeholder|night_dossiers_ready|directive_confirmation_ambiguous|DirectiveConfirmationAmbiguous' \
  ming_sim web_app.py web/src tests \
  > "$OUT/enum_f22_named.txt" || true

echo "=== F22 CMD2: defs with zero call sites (retired seam scan) ==="
# scan selected retired-looking defs; consumer proof via call-site rg
python3 - <<'PY'
from pathlib import Path
import re, subprocess
root = Path('.')
syms = [
    '_target_active_officeholder',
    'night_dossiers_ready',
    'directive_confirmation_ambiguous',
    'DirectiveConfirmationAmbiguous',
]
# also find nearby unused helpers named in prior KEEP-out-of-class
extra = subprocess.check_output([
    'rg','-n','^def (night_|_target_|_retired_|_legacy_)','ming_sim','--glob','*.py'
], text=True, stderr=subprocess.DEVNULL)
print(extra)
out=[]
for sym in syms:
    refs = subprocess.check_output(['rg','-n',sym,'ming_sim','web_app.py','web/src','tests'], text=True)
    calls = [ln for ln in refs.splitlines() if re.search(rf'{re.escape(sym)}\s*\(', ln) and 'def ' not in ln]
    defs = [ln for ln in refs.splitlines() if 'def ' in ln or f'{sym}:' in ln or f'{sym}?' in ln or f'{sym} =' in ln or 'Optional' in ln or 'Dict' in ln]
    out.append(f'### {sym}\nALL_REFS:\n{refs}\nCALL_SITES({len(calls)}):\n'+('\n'.join(calls) or '(none)')+'\n')
Path('evidence/1834-f21-f22-fix/enum_f22_consumer_proof.txt').write_text('\n'.join(out))
print('wrote enum_f22_consumer_proof.txt')
PY

echo "=== F22 CMD3: shared capabilities that MUST KEEP (consumer proof) ==="
for sym in secret_order_can_land secret_order_landing_gaps _canonical_minister_key _appointment_intent_is_current_office_noop; do
  echo "--- $sym ---"
  rg -n "$sym" ming_sim web_app.py web/src tests | head -20
done > "$OUT/enum_f22_keep_shared.txt"
