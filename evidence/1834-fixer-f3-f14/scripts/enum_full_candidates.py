#!/usr/bin/env python3
"""#1834 F3/F14 pre-commit enum expansion — mechanical candidates only.

Predicate (owner): do NOT narrow by length/CJK/filename/prose heuristics.
- Python: ALL git ls-files *.py ast.Assert (no text/name filter)
- JS/TS tests/probes: ALL expect/assert/check call sites + tests with zero asserts
- F14: full-repo stage/close/restore declaration candidates (not 8-label whitelist)

Outputs under OUT_DIR. Does not dispose production; does not rewrite historical probe stdout.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("MING_ENUM_ROOT", ".")).resolve()
OUT = Path(os.environ.get("MING_ENUM_OUT", "/tmp/1834-fixer-f3-f14-enum-expand")).resolve()
OUT.mkdir(parents=True, exist_ok=True)

SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".tox"}

EXPECT_RE = re.compile(
    r"\b(?:expect|assert|assertEqual|assert\.|check)\s*(?:\(|\.)"
)
# broader F14 stage/close/restore tokens — not limited to eight OPEN_/CLOSED_ labels
F14_TOKEN_RE = re.compile(
    r"(?:"
    r"\bOPEN_WORLD\b|\bOPEN_PUBLIC\b|\bCLOSED_WORLD\b|\bCLOSED_PUBLIC\b|"
    r"\bCALENDAR_ADVANCED_WORLD\b|\bCALENDAR_ADVANCED_PUBLIC\b|"
    r"\bRESTORE_WORLD\b|\bRESTORE_PUBLIC\b|"
    r"\bCLOSED\b|\bclosed\b|\bclose\b|\bCLOSE\b|"
    r"关闭|关库|恢复|开放|事务已关闭|affair_status\s*=\s*['\"]closed['\"]|"
    r"declare_closed|CALENDAR_ADVANCED"
    r")"
)


def git_ls_files(*globs: str) -> list[str]:
    cmd = ["git", "-C", str(ROOT), "ls-files", "-z", "--"] + list(globs)
    raw = subprocess.check_output(cmd)
    return [p.decode() for p in raw.split(b"\0") if p]


def is_skipped(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in SKIP_PARTS for p in parts)


def lane_for(rel: str) -> str:
    """historical/archived vs current live code — mechanical path lane only."""
    if rel.startswith("evidence/"):
        # historical execution outputs under evidence stay archival
        if any(
            rel.endswith(s)
            for s in (
                "/probe.txt",
                "/probe-old.txt",
                "/probe-old-f12.txt",
                "/probe-current.txt",
            )
        ) or "/probe" in Path(rel).name:
            # probe-current under newer evidence dir is current evidence of live label;
            # still mark HISTORICAL_OUTPUT for pre-relabel CLOSED_* files by content later
            if "1834-fixer-f9-f12-f3" in rel and Path(rel).name in {
                "probe.txt",
                "probe-old.txt",
                "probe-old-f12.txt",
                "probe-current.txt",
            }:
                return "HISTORICAL_OR_PRIOR_ROUND_OUTPUT"
            if "1834-fixer-f3-f14" in rel and Path(rel).name == "probe-current.txt":
                return "CURRENT_EVIDENCE_LIVE_LABEL"
            return "EVIDENCE_ARTIFACT"
        if "/scripts/" in rel:
            return "EVIDENCE_SCRIPT_LIVE"
        return "EVIDENCE_DOC"
    if rel.startswith("scripts/"):
        return "REPO_SCRIPT"
    if rel.startswith("tests/") or "/test_" in rel or rel.endswith((".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx")):
        return "TEST_CURRENT"
    if rel.startswith("web/"):
        return "WEB_CURRENT"
    if rel.startswith(("ming_sim/", "content/", "docs/")):
        return "PROD_OR_DOCS"
    return "OTHER"


# ---------- F3 Python: all Assert ----------
class AssertCollector(ast.NodeVisitor):
    def __init__(self):
        self.hits: list[dict] = []
        self._func_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assert(self, node: ast.Assert):
        try:
            detail = ast.unparse(node.test)
        except Exception:
            detail = type(node.test).__name__
        self.hits.append(
            {
                "line": node.lineno,
                "kind": "ast.Assert",
                "detail": detail[:300],
                "in_func": self._func_stack[-1] if self._func_stack else None,
            }
        )
        self.generic_visit(node)


def scan_py_asserts(rel: str) -> list[dict]:
    path = ROOT / rel
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [{"line": 0, "kind": "read_error", "detail": str(e), "in_func": None}]
    try:
        tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        return [{"line": e.lineno or 0, "kind": "syntax_error", "detail": str(e), "in_func": None}]
    c = AssertCollector()
    c.visit(tree)
    return c.hits


def scan_py_no_assert_tests(rel: str) -> list[dict]:
    """pytest-style test_* with zero ast.Assert and no unittest assert* / pytest.raises."""
    path = ROOT / rel
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=rel)
    except Exception:
        return []
    out = []
    for node in tree.body:
        _walk_tests(node, rel, src, out, class_name=None)
    return out


def _walk_tests(node, rel, src, out, class_name):
    if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
        for ch in node.body:
            _walk_tests(ch, rel, src, out, class_name=node.name)
        return
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return
    if not node.name.startswith("test_"):
        return
    asserts = 0
    calls = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            asserts += 1
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                calls.add(f.id)
            elif isinstance(f, ast.Attribute):
                calls.add(f.attr)
    proof = {
        "raises",
        "warns",
        "fail",
        "xfail",
        "assertEqual",
        "assertTrue",
        "assertFalse",
        "assertIn",
        "assertIs",
        "assertIsNone",
        "assertIsNotNone",
        "assertRaises",
        "assertAlmostEqual",
        "assertDictEqual",
        "assertListEqual",
        "assertCountEqual",
        "assertRegex",
        "assertGreater",
        "assertLess",
        "assertGreaterEqual",
        "assertLessEqual",
        "assertNotEqual",
        "assertNotIn",
    }
    if asserts == 0 and not (calls & proof):
        out.append(
            {
                "path": rel,
                "line": node.lineno,
                "kind": "py_test_no_assert",
                "detail": f"{class_name + '::' if class_name else ''}{node.name}",
                "lane": lane_for(rel),
                "calls_sample": sorted(calls)[:12],
            }
        )


# ---------- JS/TS expect/assert/check ----------
JS_TEST_GLOBS = [
    "web/**/*.test.ts",
    "web/**/*.test.tsx",
    "web/**/*.test.js",
    "web/**/*.test.jsx",
    "web/**/*.spec.ts",
    "web/**/*.spec.tsx",
    "web/**/*probe*.ts",
    "web/**/*probe*.tsx",
    "web/**/*probe*.js",
    "scripts/**/*.{js,ts,mjs,cjs}",
    "evidence/**/*.{js,ts,mjs,cjs}",
]

CALL_SITE_RE = re.compile(
    r"""(?P<kind>\bexpect\s*\(|\bassert\s*\(|\bassert\s*\.|\bcheck\s*\()"""
)
IT_RE = re.compile(
    r"""(?:\b(?:it|test|describe)\s*\(\s*(['"`]).*?\1)"""
)


def list_js_candidates() -> list[str]:
    # git ls-files doesn't expand braces the same way; pull broadly then filter
    files = git_ls_files("web", "scripts", "evidence")
    out = []
    for rel in files:
        if is_skipped(rel):
            continue
        p = Path(rel)
        suf = p.suffix.lower()
        if suf not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
            continue
        name = p.name.lower()
        under_test = (
            ".test." in name
            or ".spec." in name
            or "probe" in name
            or rel.startswith("scripts/")
            or (rel.startswith("evidence/") and "/scripts/" in rel)
        )
        if under_test:
            out.append(rel)
    return out


def scan_js_calls(rel: str) -> tuple[list[dict], list[dict]]:
    path = ROOT / rel
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return ([{"line": 0, "kind": "read_error", "detail": str(e), "lane": lane_for(rel)}], [])
    hits = []
    for i, line in enumerate(lines, 1):
        for m in CALL_SITE_RE.finditer(line):
            kind = m.group("kind").strip()
            if kind.startswith("expect"):
                k = "js_expect"
            elif kind.startswith("check"):
                k = "js_check"
            else:
                k = "js_assert"
            hits.append(
                {
                    "path": rel,
                    "line": i,
                    "kind": k,
                    "detail": line.strip()[:300],
                    "lane": lane.for_(rel) if False else lane_for(rel),
                }
            )
    # no-assert tests: it(/test( blocks with no expect/assert/check inside until next it/test at same-ish level — approximate per-file
    no_assert = []
    # crude: find it/test callbacks by line and see if any expect between this and next
    starts = []
    for i, line in enumerate(lines, 1):
        if re.search(r"\b(?:it|test)\s*\(", line) and not re.search(r"\bdescribe\s*\(", line):
            starts.append(i)
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines) + 1
        chunk = "\n".join(lines[start - 1 : end - 1])
        if not CALL_SITE_RE.search(chunk):
            no_assert.append(
                {
                    "path": rel,
                    "line": start,
                    "kind": "js_test_no_assert",
                    "detail": lines[start - 1].strip()[:300],
                    "lane": lane_for(rel),
                }
            )
    return hits, no_assert


# ---------- F14 full-repo ----------
def scan_f14() -> list[dict]:
    files = git_ls_files()
    rows = []
    # skip self-feedback dumps from this expansion if already written into evidence
    skip_names = {
        "f14_stage_labels.jsonl",
        "f14_full_candidates.jsonl",
        "f3_full_bidirectional_disposition.jsonl",
        "f3_bidirectional_disposition.jsonl",
        "enum_f3_current.txt",
        "enum_f3_all_asserts.jsonl",
        "enum_f3.txt",
        "f3_disposition.jsonl",
        "f3_probe_enum.jsonl",
    }
    for rel in files:
        if is_skipped(rel):
            continue
        if Path(rel).name in skip_names:
            continue
        # binary-ish skip
        if Path(rel).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".db", ".sqlite", ".zip", ".gz", ".pyc"}:
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in F14_TOKEN_RE.finditer(line):
                tok = m.group(0)
                lane = lane_for(rel)
                # classify action mechanically by lane + token — final semantic note left to report
                if lane == "HISTORICAL_OR_PRIOR_ROUND_OUTPUT" and tok in {
                    "CLOSED_WORLD",
                    "CLOSED_PUBLIC",
                    "CLOSED",
                    "closed",
                }:
                    action = "HISTORICAL_OUTPUT_UNCHANGED"
                elif tok in {"CLOSED_WORLD", "CLOSED_PUBLIC"} and lane in {
                    "EVIDENCE_SCRIPT_LIVE",
                    "REPO_SCRIPT",
                    "TEST_CURRENT",
                    "WEB_CURRENT",
                    "CURRENT_EVIDENCE_LIVE_LABEL",
                }:
                    action = "LIVE_CLOSED_LABEL_CANDIDATE"
                elif tok in {"CALENDAR_ADVANCED_WORLD", "CALENDAR_ADVANCED_PUBLIC", "CALENDAR_ADVANCED"}:
                    action = "LIVE_CALENDAR_ADVANCED_LABEL"
                elif tok in {"OPEN_WORLD", "OPEN_PUBLIC", "RESTORE_WORLD", "RESTORE_PUBLIC"}:
                    action = "STAGE_OPEN_OR_RESTORE_LABEL"
                elif tok in {"关闭", "关库", "declare_closed"} or "affair_status" in line:
                    action = "CLOSE_DECLARATION_OR_STATUS_QUERY"
                elif tok in {"恢复", "开放"}:
                    action = "RESTORE_OR_OPEN_PROSE_MENTION"
                elif tok.lower() in {"closed", "close", "close"}:
                    action = "GENERIC_CLOSE_TOKEN"
                else:
                    action = "F14_TOKEN_HIT"
                rows.append(
                    {
                        "path": rel,
                        "line": i,
                        "token": tok,
                        "action": action,
                        "lane": lane,
                        "detail": line.strip()[:240],
                    }
                )
    return rows


def main() -> int:
    py_files = [p for p in git_ls_files("*.py") if not is_skipped(p)]
    py_assert_rows = []
    py_no_assert = []
    for rel in py_files:
        for h in scan_py_asserts(rel):
            py_assert_rows.append(
                {
                    "path": rel,
                    "line": h["line"],
                    "kind": h["kind"],
                    "detail": h["detail"],
                    "in_func": h.get("in_func"),
                    "lane": lane_for(rel),
                }
            )
        if rel.startswith("tests/") or rel.endswith("_test.py") or "/test_" in rel:
            py_no_assert.extend(scan_py_no_assert_tests(rel))

    js_files = list_js_candidates()
    js_rows = []
    js_no_assert = []
    for rel in js_files:
        hits, noa = scan_js_calls(rel)
        js_rows.extend(hits)
        js_no_assert.extend(noa)

    f14_rows = scan_f14()

    # write outputs
    def dump_jsonl(name: str, rows: list[dict]):
        path = OUT / name
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return path

    dump_jsonl("enum_f3_all_py_asserts.jsonl", py_assert_rows)
    dump_jsonl("enum_f3_py_no_assert_tests.jsonl", py_no_assert)
    dump_jsonl("enum_f3_js_expect_assert_check.jsonl", js_rows)
    dump_jsonl("enum_f3_js_no_assert_tests.jsonl", js_no_assert)
    dump_jsonl("f14_full_candidates.jsonl", f14_rows)

    summary = {
        "root": str(ROOT),
        "py_files_scanned": len(py_files),
        "py_ast_Assert_count": len(py_assert_rows),
        "py_ast_Assert_by_lane": dict(Counter(r["lane"] for r in py_assert_rows)),
        "py_no_assert_tests": len(py_no_assert),
        "js_files_scanned": len(js_files),
        "js_expect_assert_check": len(js_rows),
        "js_by_kind": dict(Counter(r["kind"] for r in js_rows)),
        "js_no_assert_tests": len(js_no_assert),
        "f14_candidate_hits": len(f14_rows),
        "f14_by_action": dict(Counter(r["action"] for r in f14_rows)),
        "f14_by_lane": dict(Counter(r["lane"] for r in f14_rows)),
        "note": "Mechanical candidates only; no is_prose/length/CJK/filename filter on Assert list. Disposition is separate.",
        "predicate_violation_fixed": "old enum_f3_free_text_asserts.py used is_prose+tests/web only; this scan uses git ls-files all *.py Assert + JS/TS test/probe expect/assert/check",
    }
    (OUT / "enum_scale_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
