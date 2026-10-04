#!/usr/bin/env python3
"""F2-R10-2 full-repo mechanical enumeration (all tests incl. web).

Class: 合并恢复非契约源码／措辞锁、内部结构测试及重复测试
Predicate (full class definition):
  Enumerate every test (tests/** + web/**) for:
    - source / file-content assertions (not only inspect.getsource)
    - wording locks on prompt/prose
    - helper / private-method direct calls
    - internal attribute / mock call_count / identity-only
    - same-contract duplicate tests
  Then classify each candidate with DELETE or RETAIN + real contract rationale.
  Retain necessary structured negatives; retain deterministic HUD contracts.
  Do not add in-repo scanners.

Outputs under /tmp/1843-f2-r10c/
"""
from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5")
OUT = Path("/tmp/1843-f2-r10c")
OUT.mkdir(parents=True, exist_ok=True)


def py_tests() -> list[Path]:
    files = list((ROOT / "tests").rglob("*.py")) if (ROOT / "tests").exists() else []
    return [p for p in files if p.name.startswith("test_") or p.name.endswith("_test.py") or "/tests/" in p.as_posix()]


def web_tests() -> list[Path]:
    web = ROOT / "web"
    if not web.exists():
        return []
    out = []
    for p in web.rglob("*"):
        if p.suffix in {".ts", ".tsx", ".js", ".jsx"} and (
            ".test." in p.name or ".spec." in p.name
        ):
            out.append(p)
    return out


candidates: list[dict] = []


# ---------- Python tests ----------
SOURCE_READ_PATTERNS = [
    r"inspect\.getsource",
    r"inspect\.getsourcelines",
    r"Path\(.*\)\.read_text",
    r"open\([^\)]*\)\.read",
    r"read_text\(",
    r"\.read_bytes\(",
]

WORDING_HINTS = [
    r"定性",
    r"措辞",
    r"prompt",
    r"rescript_draft",
    r"content/prompts",
    r"断言.*说法",
]

for path in sorted(py_tests()):
    rel = path.relative_to(ROOT).as_posix()
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        candidates.append(
            {
                "file": rel,
                "test": "<SYNTAX_ERROR>",
                "lineno": 0,
                "flags": ["syntax_error"],
                "detail": str(e),
            }
        )
        continue

    # module-level imports of private helpers
    private_imports = []
    for node in tree.body:
        if isinstance(node, (ast.ImportFrom,)):
            for alias in node.names:
                name = alias.name
                if name.startswith("_"):
                    private_imports.append(name)

    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")):
            continue
        try:
            seg = ast.get_source_segment(src, node) or ""
        except Exception:
            seg = ""
        flags: list[str] = []
        detail: dict = {}

        # 1) source / file content assertions
        src_hits = [p for p in SOURCE_READ_PATTERNS if re.search(p, seg)]
        # also: assert "literal" in Path.read / open result patterns already covered
        # assert substring of getsource
        if src_hits:
            flags.append("source_or_file_read")
            detail["source_patterns"] = src_hits
        # assert that a .md / .py file content contains specific strings
        if re.search(r"content/prompts/|\.md[\"']|read_text\(", seg) and re.search(
            r"assert .+ in |assert .+ not in |assert .+==", seg
        ):
            if "source_or_file_read" not in flags:
                flags.append("source_or_file_read")
            flags.append("file_content_assert")

        # 2) wording locks (Chinese prompt phrases / exact instruction strings)
        if re.search(r"定性说法|定性表述|零数值|不要显示数值|奏疏口吻", seg):
            flags.append("wording_lock")
        if re.search(r"content/prompts/", seg) and re.search(r"assert .*[\"'].*[\"']", seg):
            flags.append("wording_lock_candidate")

        # 3) helper / private method direct calls
        priv_calls = re.findall(r"\b(_[A-Za-z0-9_]+)\s*\(", seg)
        # filter common false positives
        priv_calls = [c for c in priv_calls if c not in {"_"} and not c.startswith("__")]
        # also from private imports used
        used_priv_imports = [n for n in private_imports if re.search(rf"\b{re.escape(n)}\b", seg)]
        if priv_calls or used_priv_imports:
            flags.append("helper_or_private_call")
            detail["private_calls"] = sorted(set(priv_calls))[:20]
            detail["private_imports_used"] = used_priv_imports

        # 4) internal attribute / mock call_count / identity-only
        if re.search(r"\bhasattr\s*\(", seg) or re.search(r"\bgetattr\s*\([^,]+,\s*[\"']_", seg):
            flags.append("internal_attr")
        if re.search(r"call_count|assert_called|assert_not_called|call_args_list|mock_calls", seg):
            flags.append("mock_call_count")
        if re.search(r"\bis not\b.*original_|\bis\b.*original_|id\(", seg) or re.search(
            r"assert .+ is not .+", seg
        ):
            # refine: identity of copied snapshots
            if re.search(r"is not original_|is original_|id\(", seg) or (
                "snapshot" in seg.lower() and re.search(r"\bis not\b", seg)
            ):
                flags.append("identity_only")

        # 5) duplicate markers: same external contract phrases as known retained tests
        if re.search(r"preserves_persisted_fiscal_snapshots|advance_through_fixed_flows", seg):
            detail["external_contract_anchor"] = True
        if re.search(r"shadow_tlog|Observable shadow|batch_bridge_without_per_region", node.name + seg):
            flags.append("possible_dup_of_external_contract")

        # HUD keyset + engineering tokens (retain per G1)
        if re.search(r"\{['\"]name['\"].*['\"]amount['\"]\}|engineering|budget_key|player_budget", seg):
            detail["hud_related"] = True

        if flags:
            candidates.append(
                {
                    "file": rel,
                    "test": node.name,
                    "lineno": node.lineno,
                    "flags": sorted(set(flags)),
                    "detail": detail,
                }
            )


# ---------- Web tests (TS/TSX) — same class predicates adapted ----------
WEB_SOURCE_PATTERNS = [
    r"fs\.readFileSync",
    r"readFileSync",
    r"readFile\(",
    r"import\.meta\.url",
    r"toMatchSnapshot",
    r"toMatchInlineSnapshot",
]
WEB_INTERNAL_PATTERNS = [
    r"\.mock\.",
    r"toHaveBeenCalledTimes",
    r"toHaveBeenCalled",
    r"toHaveBeenCalledWith",
    r"vi\.spyOn",
    r"jest\.spyOn",
]

for path in sorted(web_tests()):
    rel = path.relative_to(ROOT).as_posix()
    src = path.read_text(encoding="utf-8", errors="replace")
    # crude split on test(/it(/describe blocks with string names
    # find test("name" or it("name"
    for m in re.finditer(
        r"(?:(?:test|it|test\.only|it\.only)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]\s*,\s*(?:async\s*)?\()",
        src,
    ):
        name = m.group(1)
        start = m.start()
        # take a window of 80 lines or until next test(
        window = src[start : start + 4000]
        flags = []
        detail = {}
        if any(re.search(p, window) for p in WEB_SOURCE_PATTERNS):
            flags.append("source_or_file_read")
        if re.search(r"toContain\(|toMatch\(|toBe\([`'\"][^`'\"]{8,}", window) and re.search(
            r"readFile|prompt|文案|措辞", window
        ):
            flags.append("wording_lock_candidate")
        if any(re.search(p, window) for p in WEB_INTERNAL_PATTERNS):
            # mock call count alone isn't always illegal; flag for semantic pass
            if re.search(r"toHaveBeenCalledTimes|mock\.calls\.length", window):
                flags.append("mock_call_count")
            else:
                flags.append("mock_usage")
        # private / internal: accessing underscore props
        if re.search(r"\.[_][A-Za-z]", window):
            flags.append("internal_attr")
        if flags:
            # approximate lineno
            lineno = src[:start].count("\n") + 1
            candidates.append(
                {
                    "file": rel,
                    "test": name,
                    "lineno": lineno,
                    "flags": sorted(set(flags)),
                    "detail": detail,
                }
            )


(OUT / "r10b-f2-candidates-raw.json").write_text(
    json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
)

# summary counts by flag
by_flag = defaultdict(int)
by_file = defaultdict(int)
for c in candidates:
    by_file[c["file"]] += 1
    for f in c["flags"]:
        by_flag[f] += 1

summary = {
    "total_candidates": len(candidates),
    "py_test_files": len(py_tests()),
    "web_test_files": len(web_tests()),
    "by_flag": dict(sorted(by_flag.items())),
    "files_with_candidates": len(by_file),
}
(OUT / "r10b-f2-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("wrote", OUT / "r10b-f2-candidates-raw.json")
