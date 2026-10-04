#!/usr/bin/env python3
"""F2: full-warehouse effective runtime config projection candidates."""
from __future__ import annotations
import ast, json, re, sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
PATTERNS = [
    r"normalize_reasoning_strength",
    r"cli_model_from_env",
    r"llm_config_from_runtime",
    r"cli_reasoning_strength",
    r"api_reasoning_strength",
    r"reasoning_strength",
    r"cli_runner",
    r"channel\s*=\s*str\(runtime",
    r"load_runtime_llm",
    r"effective.*(?:channel|runner|model|reasoning)",
]
rx = re.compile("|".join(f"({p})" for p in PATTERNS))

rows = []
for path in list(ROOT.joinpath("ming_sim").rglob("*.py")) + [ROOT/"web_app.py"]:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if rx.search(line):
            rows.append({"file": str(path.relative_to(ROOT)), "line": i, "text": line.strip()[:160]})

# also web/src TS/TSX
for path in ROOT.joinpath("web/src").rglob("*"):
    if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        continue
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r"reasoning_strength|cli_runner|llm_config|channel.*cli|thinking_level", line):
            rows.append({"file": str(path.relative_to(ROOT)), "line": i, "text": line.strip()[:160]})

out = {"hit_count": len(rows), "hits": rows}
Path("/tmp/ming1902-f1f4-rescand/f2_config_scan.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"f2_hits={len(rows)}")
# group by file
from collections import Counter
c = Counter(r["file"] for r in rows)
for f, n in c.most_common():
    print(f"  {n:4d}  {f}")
