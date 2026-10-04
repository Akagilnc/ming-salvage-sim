#!/usr/bin/env python3
"""#1847 w7 full-repo mechanical enumeration for N6/N11/N13/N14.

Scans tracked production + tests (git ls-files). Archive/docs/evidence frozen
paths are listed as EXEMPT_STATIC, not dropped silently.

Outputs TSV member tables (full rows, no head truncation) under
evidence/1847-w7-correction/.
"""
from __future__ import annotations

import ast
import csv
import os
import pathlib
import re
import subprocess
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = pathlib.Path("/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5")
OUT = ROOT / "evidence" / "1847-w7-correction"
OUT.mkdir(parents=True, exist_ok=True)

EXEMPT_PREFIXES = (
    "docs/raw/",
    "docs/archive/",
    "evidence/",
    "archive/",
    "node_modules/",
    ".venv/",
)

PY_MUTATORS = {
    "strip", "lstrip", "rstrip", "replace", "split", "rsplit", "join",
    "sub", "subn", "findall", "search", "match", "fullmatch", "compile",
    "encode", "decode", "removeprefix", "removesuffix", "partition", "rpartition",
    "casefold", "lower", "upper", "title", "capitalize", "translate", "format",
    "format_map", "expandtabs", "zfill", "center", "ljust", "rjust",
    "slice", "substr", "substring",
}
# subscription / slice nodes handled separately

N13_PATTERNS = [
    (re.compile(r"force\s*=\s*True"), "force_True"),
    (re.compile(r"SIGKILL"), "SIGKILL_ref"),
    (re.compile(r"\.kill\s*\("), "kill_call"),
    (re.compile(r"os\.kill"), "os_kill"),
    (re.compile(r"terminate\s*\("), "terminate_call"),
    (re.compile(r"\.close\s*\("), "close_call"),
    (re.compile(r"except\s+Exception\s*:\s*(?:pass|\.\.\.)"), "except_pass"),
    (re.compile(r"except\s*:\s*(?:pass|\.\.\.)"), "bare_except_pass"),
    (re.compile(r"subprocess\.run\([^)]*timeout\s*="), "subprocess_run_timeout"),
]

N14_PATTERNS = [
    (re.compile(r"inspect\.getsource"), "getsource"),
    (re.compile(r"ast\.parse\(|ast\.literal_eval|ast\.get_source_segment"), "ast_source_proof"),
    (re.compile(r"str\s*\(\s*\w+\s*\)\s*(in|not in)"), "str_row_identity"),
    (re.compile(r"""['"].*['"]\s*(in|not in)\s*str\s*\("""), "str_contains_identity"),
    (re.compile(r"Path\(.*\)\.read_text|pathlib\.Path.*read_text|\.read_text\("), "read_text"),
    (re.compile(r"\\\\r\\\\n|\\r\\n|newline"), "newline_boundary"),
]


def git_tracked() -> List[str]:
    out = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files"], text=True
    )
    return [ln for ln in out.splitlines() if ln.strip()]


def is_exempt(rel: str) -> bool:
    return any(rel.startswith(p) or f"/{p}" in ("/" + rel) for p in EXEMPT_PREFIXES)


def enclosing(tree: ast.AST, lineno: int) -> str:
    best, best_ln = "", -1
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ln = getattr(n, "lineno", 10**9)
            if ln <= lineno and ln >= best_ln:
                best_ln, best = ln, n.name
    return best


def snip(lines: List[str], ln: int) -> str:
    if 1 <= ln <= len(lines):
        return lines[ln - 1].rstrip()[:240]
    return ""


def scan_n6_py(rel: str, text: str) -> List[Dict[str, Any]]:
    rows = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [{
            "file": rel, "line": 0, "kind": "syntax_error", "detail": str(exc),
            "ctx": "", "snip": "", " mechan_class": "SCAN_ERROR",
        }]
    lines = text.splitlines()

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in PY_MUTATORS:
                rows.append({
                    "file": rel, "line": node.lineno, "kind": f"call.{f.attr}",
                    "detail": f.attr, "ctx": enclosing(tree, node.lineno),
                    "snip": snip(lines, node.lineno),
                })
            if isinstance(f, ast.Name) and f.id in {"getattr"}:
                pass
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Slice):
                rows.append({
                    "file": rel, "line": node.lineno, "kind": "slice_sub",
                    "detail": "slice", "ctx": enclosing(tree, node.lineno),
                    "snip": snip(lines, node.lineno),
                })
            self.generic_visit(node)

        def visit_BinOp(self, node: ast.BinOp):
            # join-like via + is too broad; skip
            self.generic_visit(node)

    V().visit(tree)
    # also read_text newline transforms
    for i, line in enumerate(lines, 1):
        if "read_text" in line and ("newline" in line or "replace" in line or "splitlines" in line):
            rows.append({
                "file": rel, "line": i, "kind": "read_text_transform",
                "detail": "read_text", "ctx": "", "snip": snip(lines, i),
            })
    return rows


def scan_n6_ts(rel: str, text: str) -> List[Dict[str, Any]]:
    rows = []
    lines = text.splitlines()
    pats = [
        (re.compile(r"\.(trim|trimStart|trimEnd)\s*\("), "trim"),
        (re.compile(r"\.(replace|replaceAll)\s*\("), "replace"),
        (re.compile(r"\.(slice|substring|substr)\s*\("), "slice"),
        (re.compile(r"\.(split|join)\s*\("), "split_join"),
        (re.compile(r"\.normalize\s*\("), "normalize"),
    ]
    for i, line in enumerate(lines, 1):
        for rx, kind in pats:
            if rx.search(line):
                rows.append({
                    "file": rel, "line": i, "kind": f"ts.{kind}",
                    "detail": kind, "ctx": "", "snip": snip(lines, i),
                })
    return rows


def write_tsv(path: pathlib.Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def classify_n6(row: Dict[str, Any]) -> Tuple[str, str]:
    """Conservative mechanical bucket; human disposition needs source→sink."""
    sn = row.get("snip") or ""
    kind = row.get("kind") or ""
    rel = row.get("file") or ""
    # form-language / empty-local heuristics are NOT KEEP verdicts — mark POTENTIAL
    if "tests/" in rel:
        return "TEST_HIT", "test-side transform candidate; N14 owns identity proofs"
    if kind.startswith("call.strip") or kind.startswith("ts.trim"):
        if re.search(r"if\s+.*\.(strip|trim)\s*\(", sn) or re.search(r"\.(strip|trim)\s*\(\s*\)\s*(?:else|or|and|==|!=|not\s)", sn):
            return "POTENTIAL_EMPTY_LOCAL", "strip/trim in condition — may be empty-local (verify transport)"
        if re.search(r"\w+\s*=\s*.*\.(strip|trim)\s*\(", sn):
            return "POTENTIAL_TRANSPORT_STRIP", "assignment from strip/trim — verify free-text transport sink"
        return "POTENTIAL_STRIP", "strip/trim call — verify free-text transport"
    if "replace" in kind:
        return "POTENTIAL_REPLACE", "replace on text — verify free-text transport"
    if "slice" in kind or "split" in kind:
        return "POTENTIAL_SLICE_SPLIT", "slice/split — verify free-text transport"
    return "POTENTIAL_OTHER", f"{kind} text mutator — verify free-text transport"


# --- N11 retired-backend closure ---
# Seed symbols from last judge payload samples + prior deleted set; expand by
# definition/reference closure across tracked py files. Classification requires
# live consumer check — not name guessing.

N11_SEED = [
    "rescript_summon_origin_ref",
    "rescript_summon_origin_consumed",
    "prepare_rescript_summon_scaffold",
    "RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES",
    "find_deliberation_dossier_by_decision_key",
    "_extract_secret_order",
    "assemble_secret_order_content",
    "_DRAFT_PREFIXES",
    "_SECRET_PREFIXES",
    "_CLAUSE_SPLIT",
    "confirm_dossier_links",
    "_ledger_by_origin_ref",
    "_so_json",
]


def collect_defs_and_refs(py_files: List[Tuple[str, str]]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    defs: Dict[str, List[str]] = defaultdict(list)
    refs: Dict[str, List[str]] = defaultdict(list)
    for rel, text in py_files:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[n.name].append(f"{rel}:{n.lineno}")
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        defs[t.id].append(f"{rel}:{n.lineno}")
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                        defs[t.attr].append(f"{rel}:{n.lineno}")
            if isinstance(n, ast.Name):
                refs[n.id].append(f"{rel}:{getattr(n, 'lineno', 0)}")
            if isinstance(n, ast.Attribute):
                refs[n.attr].append(f"{rel}:{getattr(n, 'lineno', 0)}")
    return defs, refs


def main() -> int:
    tracked = git_tracked()
    exempt_rows = []
    prod_test_files: List[str] = []
    for rel in tracked:
        if is_exempt(rel):
            exempt_rows.append({"file": rel, "reason": "frozen_archive_or_evidence"})
            continue
        if rel.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
            prod_test_files.append(rel)

    # ---------- N6 ----------
    n6_raw: List[Dict[str, Any]] = []
    for rel in prod_test_files:
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            n6_raw.append({
                "file": rel, "line": 0, "kind": "read_error", "detail": str(exc),
                "ctx": "", "snip": "",
            })
            continue
        if rel.endswith(".py"):
            n6_raw.extend(scan_n6_py(rel, text))
        elif rel.endswith((".ts", ".tsx", ".js", ".jsx")):
            n6_raw.extend(scan_n6_ts(rel, text))

    n6_classified = []
    for r in n6_raw:
        bucket, reason = classify_n6(r)
        n6_classified.append({**r, "mech_bucket": bucket, "mech_reason": reason})

    write_tsv(
        OUT / "n6_candidates_raw.tsv",
        ["file", "line", "kind", "detail", "ctx", "snip"],
        n6_raw,
    )
    write_tsv(
        OUT / "n6_members_classified.tsv",
        ["file", "line", "kind", "detail", "ctx", "mech_bucket", "mech_reason", "snip"],
        n6_classified,
    )

    # ---------- N11 ----------
    py_files = []
    for rel in prod_test_files:
        if rel.endswith(".py"):
            try:
                py_files.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
            except Exception:
                pass
    defs, refs = collect_defs_and_refs(py_files)

    # Expand seed by same-file private helpers referenced only from seed defs (1-hop)
    expanded = set(N11_SEED)
    # Also scan for names containing retired markers — as POTENTIAL only
    for name in list(defs.keys()):
        low = name.lower()
        if any(k in low for k in ("rescript_summon", "secret_order", "legacy_", "_legacy")):
            expanded.add(name)

    n11_rows = []
    for name in sorted(expanded):
        dlist = defs.get(name, [])
        rlist = refs.get(name, [])
        prod_refs = [x for x in rlist if not x.startswith("tests/")]
        test_refs = [x for x in rlist if x.startswith("tests/")]
        # consumers = refs that are not the definition line itself
        def_set = set(dlist)
        live_prod = [x for x in prod_refs if x not in def_set]
        live_test = [x for x in test_refs if x not in def_set]
        if not dlist and not rlist:
            disposition = "ABSENT"
            reason = "no def/ref in tracked prod+tests (already deleted or never present)"
        elif live_prod:
            disposition = "KEEP_LIVE_CONSUMER"
            reason = f"production refs outside defs: {len(live_prod)}"
        elif dlist and not live_prod and not live_test:
            disposition = "DELETE_ORPHAN_DEF"
            reason = "definition with zero non-def refs"
        elif dlist and not live_prod and live_test:
            disposition = "DELETE_TEST_ONLY_ISLAND"
            reason = f"only test refs remain: {len(live_test)}"
        elif not dlist and (live_prod or live_test):
            disposition = "POTENTIAL_DANGLING_REF"
            reason = "refs without def in scanned set"
        else:
            disposition = "POTENTIAL"
            reason = "needs human consumer-closure check"
        n11_rows.append({
            "symbol": name,
            "disposition": disposition,
            "reason": reason,
            "defs": ";".join(dlist[:20]),
            "prod_refs_nondef": ";".join(live_prod[:30]),
            "test_refs_nondef": ";".join(live_test[:30]),
            "def_count": len(dlist),
            "prod_ref_count": len(live_prod),
            "test_ref_count": len(live_test),
        })

    write_tsv(
        OUT / "n11_members_classified.tsv",
        ["symbol", "disposition", "reason", "def_count", "prod_ref_count", "test_ref_count",
         "defs", "prod_refs_nondef", "test_refs_nondef"],
        n11_rows,
    )

    # ---------- N13 ----------
    n13_rows = []
    for rel in prod_test_files:
        if not rel.endswith(".py"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        # multiline except Exception: pass
        for m in re.finditer(r"except\s+Exception\s*:\n\s*pass", text):
            ln = text[: m.start()].count("\n") + 1
            n13_rows.append({
                "file": rel, "line": ln, "kind": "except_Exception_pass",
                "snip": snip(lines, ln), "mech_bucket": "POTENTIAL_SWALLOW",
            })
        for i, line in enumerate(lines, 1):
            for rx, kind in N13_PATTERNS:
                if rx.search(line):
                    bucket = "POTENTIAL_N13"
                    if kind == "SIGKILL_ref" and ".kill" not in line and "force" not in line:
                        bucket = "MECHANICAL_DOC"
                    if kind == "force_True":
                        bucket = "POTENTIAL_FORCE_TRUE"
                    if kind in ("kill_call", "os_kill"):
                        bucket = "POTENTIAL_KILL"
                    if "except" in kind:
                        bucket = "POTENTIAL_SWALLOW"
                    n13_rows.append({
                        "file": rel, "line": i, "kind": kind,
                        "snip": snip(lines, i), "mech_bucket": bucket,
                    })
    write_tsv(
        OUT / "n13_members_classified.tsv",
        ["file", "line", "kind", "mech_bucket", "snip"],
        n13_rows,
    )

    # ---------- N14 ----------
    n14_rows = []
    for rel in prod_test_files:
        if not rel.startswith("tests/") or not rel.endswith(".py"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        # same-value recheck: a == b right after both assigned from same expression pattern
        for i, line in enumerate(lines, 1):
            for rx, kind in N14_PATTERNS:
                if rx.search(line):
                    n14_rows.append({
                        "file": rel, "line": i, "kind": kind,
                        "snip": snip(lines, i), "mech_bucket": "POTENTIAL_N14",
                    })
            # note/body identity sentinels
            if re.search(r"""(note|body|opening|text)\s*(==|in|not in)|['"].{0,40}['"]\s+in\s+\w+\.(note|body)""", line):
                if "assert" in line or "in " in line:
                    n14_rows.append({
                        "file": rel, "line": i, "kind": "prose_identity_assert",
                        "snip": snip(lines, i), "mech_bucket": "POTENTIAL_IDENTITY_SENTINEL",
                    })
            if re.search(r"assert\s+.*=~?\s*.*\n", line):
                pass
            # same-value immediate recheck: assert x == y where y sampled same as x nearby
            if re.search(r"assert\s+(\w+)\s*==\s*(\w+)", line):
                n14_rows.append({
                    "file": rel, "line": i, "kind": "assert_same_name_eq",
                    "snip": snip(lines, i), "mech_bucket": "POTENTIAL_SAME_VALUE_RECHECK",
                })
        if tree:
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    if n.func.attr == "getsource":
                        n14_rows.append({
                            "file": rel, "line": n.lineno, "kind": "ast_getsource_call",
                            "snip": snip(lines, n.lineno), "mech_bucket": "FIX_OR_DELETE_GETSOURCE",
                        })
    write_tsv(
        OUT / "n14_members_classified.tsv",
        ["file", "line", "kind", "mech_bucket", "snip"],
        n14_rows,
    )

    write_tsv(OUT / "exempt_files.tsv", ["file", "reason"], exempt_rows)

    summary = {
        "tracked_files": len(tracked),
        "scanned_code_files": len(prod_test_files),
        "exempt": len(exempt_rows),
        "n6_raw": len(n6_raw),
        "n6_classified": len(n6_classified),
        "n6_buckets": dict(Counter(r["mech_bucket"] for r in n6_classified)),
        "n11_symbols": len(n11_rows),
        "n11_dispositions": dict(Counter(r["disposition"] for r in n11_rows)),
        "n13_hits": len(n13_rows),
        "n13_buckets": dict(Counter(r["mech_bucket"] for r in n13_rows)),
        "n14_hits": len(n14_rows),
        "n14_buckets": dict(Counter(r["mech_bucket"] for r in n14_rows)),
    }
    (OUT / "scan_summary.json").write_text(
        __import__("json").dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
