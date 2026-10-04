#!/usr/bin/env python3
"""F3 enumerator for #1902 fix round — not a permanent CI scanner."""
from __future__ import annotations
import ast, json, re, subprocess, sys
from pathlib import Path
ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
PRED = r'(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx)$)'
paths = subprocess.check_output(["bash","-lc", f"cd {ROOT} && git ls-files | rg -i '{PRED}'"], text=True).splitlines()

def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")

flags_by_path, setattr_hits, prose_hits, cap_hits = {}, [], [], []
for rel in paths:
    text = read_text(ROOT / rel)
    flags = []
    if re.search(r"setattr\([^;\n]*['_\\\"]_run_backend['_\\\"]", text):
        flags.append("setattr_run_backend")
    if re.search(r'assert\s+[\'"].+[\'"]\s+in\s+\w+', text):
        flags.append("assert_substr_in")
    if re.search(r"assert\s+.+\s+in\s+\w+\s+or\s+\w+", text):
        flags.append("weak_or_source")
    if "CLI_REASONING_STRENGTH_RUNNERS" in text and ("==" in text or "frozenset" in text or "set(" in text):
        flags.append("lock_internal_capability_set")
    if "validate_all" in text and ("list_rescript_drafts" in text or "_adjudicate_cli_decisions" in text):
        flags.append("helper_plus_land_db")
    if re.search(r"def test_.*(helper|pure|predicate|internal)", text):
        flags.append("named_helper_or_pure")
    flags_by_path[rel] = {"flags": sorted(set(flags))}
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except Exception:
            tree = None
        if tree:
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "setattr":
                    if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value in {"_run_backend", "_run_backend_for_config"}:
                        setattr_hits.append({"file": rel, "line": n.lineno, "target": n.args[1].value})
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r'assert\s+[\'"][^\'"]+[\'"]\s+in\s+(reason|text|roster|detail|report|body|message)\b', line):
                prose_hits.append({"file": rel, "line": i, "text": line.strip()[:140]})
            if "CLI_REASONING_STRENGTH_RUNNERS" in line and ("==" in line or "set(" in line or "frozenset" in line):
                cap_hits.append({"file": rel, "line": i, "text": line.strip()[:160]})

out = {"path_count": len(paths), "paths": paths, "flags_by_path": flags_by_path,
       "setattr_hits": setattr_hits, "prose_hits": prose_hits, "cap_hits": cap_hits}
Path("/tmp/ming1902-f1f4-rescand/f3_test_scan.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"test_paths={len(paths)} suspects={sum(1 for v in flags_by_path.values() if v['flags'])} cap_locks={len(cap_hits)}")
