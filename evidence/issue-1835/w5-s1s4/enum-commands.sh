#!/usr/bin/env bash
# #1835 S1–S4 全仓机械枚举谓词（本局施工前扫描；不得收窄类定义）
set -euo pipefail
cd "$(dirname "$0")/../../.."
PY="${MING_SIM_PYTHON:-/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python}"

echo "=== S1 typed 段旧 dict/旧响应消费 ==="
"$PY" - <<'PY'
import ast
from pathlib import Path
KEYS = {
    "applied", "rejected", "advances", "new_issues", "closes", "cancels",
    "applied_person_changes",
}
TYPED_HINTS = ("summary", "section", "result", "outcome", "bundle", "issue")
hits = []
for p in Path(".").rglob("*.py"):
    if p.parts[0] in {".git", "web", "node_modules", "evidence"} or ".venv" in p.parts:
        continue
    try:
        src = p.read_text()
        tree = ast.parse(src)
    except Exception:
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value in KEYS:
            tgt = n.value
            nm = tgt.id if isinstance(tgt, ast.Name) else (tgt.attr if isinstance(tgt, ast.Attribute) else None)
            if nm and any(h in nm.lower() for h in TYPED_HINTS):
                hits.append((str(p), n.lineno, "sub", nm, n.slice.value, ast.get_source_segment(src, n)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args:
            a0 = n.args[0]
            if isinstance(a0, ast.Constant) and a0.value in KEYS:
                tgt = n.func.value
                nm = tgt.id if isinstance(tgt, ast.Name) else (tgt.attr if isinstance(tgt, ast.Attribute) else None)
                if nm and any(h in nm.lower() for h in TYPED_HINTS):
                    hits.append((str(p), n.lineno, "get", nm, a0.value, ast.get_source_segment(src, n)))
for h in hits:
    print(f"{h[0]}:{h[1]}\t{h[2]}\t{h[3]}[{h[4]!r}]\t{h[5]}")
print(f"TOTAL={len(hits)}")
PY

echo "=== S2 预检影子数量公式 / 独立 stages 捕获 ==="
rg -n 'max\(0, min\(|city_level\) \* 8|min\(12,' ming_sim/settlement/preflight.py || true
rg -n 'def _region_noop_error|def _army_noop_error|def capture_commitment_stages|def stages_to_json' -g '*.py' -g '!evidence/**' || true
rg -n 'capture_commitment_stages\(|stages_to_json\(' -g '*.py' -g '!evidence/**' || true

echo "=== S3 旧停止条件兼容链 / 无效测 / 死夹具 ==="
rg -n '_legacy_commitment_stop_gate|_commitment_stop_gate|legacy_resolve|resolve_condition.*=.*stop_condition|whitespace_resolve_condition|legacy_character_resolve' -g '*.py' -g '!evidence/**' || true
rg -n '_seed_province_pay_split_scenario|reports_no_legacy_person_response_keys|accepts_flat_faction_scalar' -g '*.py' -g '!evidence/**' || true

echo "=== S4 政治收益默认值 / 保活测 ==="
rg -n 'resolve_eff = \{"metrics": \{"民心": 1\}\}|initiative_floor|floor 在 try|绝不入空壳' -g '*.py' -g '!evidence/**' || true
