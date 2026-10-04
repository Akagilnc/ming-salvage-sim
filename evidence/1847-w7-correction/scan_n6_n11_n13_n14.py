#!/usr/bin/env python3
"""#1847 w7 full-repo mechanical enumeration for N6/N11/N13/N14.

Scans tracked production + tests (git ls-files). Archive/docs/evidence frozen
paths are listed as EXEMPT_STATIC, not dropped silently.

Mechanical only: buckets are POTENTIAL_*/ABSENT/DELETE_*/KEEP_LIVE_CONSUMER
(consumer-graph facts). Never invents KEEP_* from FREE_TEXT_NAMES, snip regex,
or display-slice heuristics. Human semantic disposition lives outside this script.
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
    # All read_text sites are candidates: human must decide if decoded text is
    # free-prose transport (newline/strip/replace after read) vs asset/config IO.
    for i, line in enumerate(lines, 1):
        if ".read_text(" in line or "read_text(" in line:
            kind = "read_text_transform" if (
                "newline" in line or "replace" in line or "splitlines" in line
                or ".strip(" in line
            ) else "read_text"
            rows.append({
                "file": rel, "line": i, "kind": kind,
                "detail": "read_text", "ctx": enclosing(tree, i),
                "snip": snip(lines, i),
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
    """LF-only TSV; empty cells as '-' (no trailing-tab whitespace)."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(fieldnames) + "\n")
        for r in rows:
            cells = []
            for k in fieldnames:
                v = r.get(k, "")
                if v is None or v == "":
                    cells.append("-")
                else:
                    cells.append(str(v).replace("\t", " ").replace("\n", " "))
            fh.write("\t".join(cells) + "\n")


def classify_n6(row: Dict[str, Any]) -> Tuple[str, str]:
    """Conservative mechanical bucket; human disposition needs source→sink.

    Never returns KEEP_* — empty-local / form / IO guesses stay POTENTIAL_*.
    """
    sn = row.get("snip") or ""
    kind = row.get("kind") or ""
    rel = row.get("file") or ""
    if "tests/" in rel:
        return "TEST_HIT", "test-side transform candidate; N14 owns identity proofs"
    if "read_text" in kind:
        return "POTENTIAL_READ_TEXT", "read_text — verify whether decoded text is free-prose transport"
    if kind.startswith("call.strip") or kind.startswith("ts.trim"):
        if re.search(r"if\s+.*\.(strip|trim)\s*\(", sn) or re.search(r"\.(strip|trim)\s*\(\s*\)\s*(?:else|or|and|==|!=|not\s)", sn):
            return "POTENTIAL_EMPTY_LOCAL", "strip/trim in condition — may be empty-local (verify transport)"
        if re.search(r"\w+\s*=\s*.*\.(strip|trim)\s*\(", sn):
            return "POTENTIAL_TRANSPORT_STRIP", "assignment from strip/trim — verify free-text transport sink"
        return "POTENTIAL_STRIP", "strip/trim call — verify free-text transport"
    if "replace" in kind:
        return "POTENTIAL_REPLACE", "replace on text — verify free-text transport"
    if "slice" in kind or "split" in kind:
        return "POTENTIAL_SLICE_SPLIT", "slice/split — verify free-text transport / display truncation"
    return "POTENTIAL_OTHER", f"{kind} text mutator — verify free-text transport"


# --- N11 retired-backend closure ---
# Start from judge-sample retired entrypoints + exclusive helpers known from that
# island's old consumer path (git-deleted extract/summon/landing island). Expand
# by def→callee exclusivity (callee prod refs ⊆ closure defs), not name_pattern.

N11_SEED = [
    # Judge sample entrypoints
    "rescript_summon_origin_ref",
    "rescript_summon_origin_consumed",
    "prepare_rescript_summon_scaffold",
    "RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES",
    "find_deliberation_dossier_by_decision_key",
    "_extract_secret_order",
    "assemble_secret_order_content",
    "confirm_dossier_links",
    "_so_json",
    # Exclusive helpers on the old extract/summon consumer path
    "_DRAFT_PREFIXES",
    "_SECRET_PREFIXES",
    "_CLAUSE_SPLIT",
    "_content_reflects_emperor_intent",
    "_choose_assignee",
    "_split_audience_context",
    "_merge_secret_content",
    "_secret_metadata_from_command",
    "_normalize_dossier_link_proposals",
    "compose_secret_order_landing_recovery",
    "_secret_landing_gap_feature",
    "_SECRET_LANDING_GAP_LABELS",
    # Live shared near the island — must stay if consumers remain
    "_ledger_by_origin_ref",
    "secret_order_can_land",
    "secret_order_landing_gaps",
]

# Builtins / noise never added by callee expansion.
N11_CALLEE_SKIP = frozenset({
    "str", "int", "float", "bool", "list", "dict", "set", "tuple", "len", "range",
    "enumerate", "isinstance", "getattr", "setattr", "hasattr", "print", "open",
    "Exception", "ValueError", "TypeError", "KeyError", "RuntimeError", "Optional",
    "List", "Dict", "Any", "Tuple", "Set", "None", "True", "False", "self", "cls",
})


def collect_defs_and_refs(py_files: List[Tuple[str, str]]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Collect function/class/module-constant defs + name refs.

    Local assigns (e.g. ``so = …`` inside a function) are NOT defs — otherwise
    consumer-graph closure floods with locals.
    """
    defs: Dict[str, List[str]] = defaultdict(list)
    refs: Dict[str, List[str]] = defaultdict(list)
    for rel, text in py_files:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[n.name].append(f"{rel}:{n.lineno}")
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and (t.id.isupper() or t.id.startswith("_")):
                        # Module-level constants / private module bindings only.
                        defs[t.id].append(f"{rel}:{n.lineno}")
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                if n.target.id.isupper() or n.target.id.startswith("_"):
                    defs[n.target.id].append(f"{rel}:{n.lineno}")
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                refs[n.id].append(f"{rel}:{getattr(n, 'lineno', 0)}")
            if isinstance(n, ast.Attribute):
                refs[n.attr].append(f"{rel}:{getattr(n, 'lineno', 0)}")
    return defs, refs


def _function_callees(text: str, func_name: str) -> Set[str]:
    """Names loaded inside a top-level function/assign binding (mechanical)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    out: Set[str] = set()
    for n in tree.body:
        target = None
        body_nodes: List[ast.AST] = []
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name:
            target = n
            body_nodes = list(n.body)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == func_name:
                    body_nodes = [n.value]
                    target = n
        if target is None:
            continue
        for sub in body_nodes:
            for m in ast.walk(sub):
                if isinstance(m, ast.Name) and isinstance(m.ctx, ast.Load):
                    if m.id not in N11_CALLEE_SKIP:
                        out.add(m.id)
                if isinstance(m, ast.Attribute) and isinstance(m.ctx, ast.Load):
                    if m.attr not in N11_CALLEE_SKIP:
                        out.add(m.attr)
    return out


def expand_n11_closure(
    py_files: List[Tuple[str, str]],
    defs: Dict[str, List[str]],
    refs: Dict[str, List[str]],
) -> Set[str]:
    """BFS exclusive-callee expansion from N11_SEED over current defs.

    A callee joins the closure only when it still has a def and every non-def
    production ref lives in a file that already defines a closure member
    (exclusive island file), or it has zero production consumers (orphan).
    """
    texts = {rel: text for rel, text in py_files}
    closure: Set[str] = set(N11_SEED)
    frontier = list(N11_SEED)
    while frontier:
        sym = frontier.pop()
        for loc in defs.get(sym, []):
            rel = loc.rsplit(":", 1)[0]
            text = texts.get(rel)
            if not text:
                continue
            for callee in _function_callees(text, sym):
                if callee in closure or callee in N11_CALLEE_SKIP:
                    continue
                if callee not in defs:
                    continue
                def_set = set(defs.get(callee, []))
                prod_refs = [
                    x for x in refs.get(callee, [])
                    if not x.startswith("tests/") and x not in def_set
                ]
                closure_files = {
                    d.rsplit(":", 1)[0]
                    for csym in closure
                    for d in defs.get(csym, [])
                }
                foreign = [
                    r for r in prod_refs
                    if r.rsplit(":", 1)[0] not in closure_files
                ]
                if not foreign:
                    closure.add(callee)
                    frontier.append(callee)
    return closure


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

    # Consumer-graph closure from retired-path seeds + exclusive callees.
    # mech_bucket only — human KEEP/DELETE lives in human_*.tsv.
    expanded = expand_n11_closure(py_files, defs, refs)

    n11_rows = []
    for name in sorted(expanded):
        dlist = defs.get(name, [])
        rlist = refs.get(name, [])
        prod_refs = [x for x in rlist if not x.startswith("tests/")]
        test_refs = [x for x in rlist if x.startswith("tests/")]
        def_set = set(dlist)
        live_prod = [x for x in prod_refs if x not in def_set]
        live_test = [x for x in test_refs if x not in def_set]
        if not dlist and not rlist:
            mech = "ABSENT"
            reason = "no def/ref in tracked prod+tests (already deleted or never present)"
        elif live_prod:
            mech = "KEEP_LIVE_CONSUMER"
            reason = f"production refs outside defs: {';'.join(live_prod[:8])}"
        elif dlist and not live_prod and not live_test:
            mech = "DELETE_ORPHAN_DEF"
            reason = f"definition with zero non-def refs: {';'.join(dlist[:5])}"
        elif dlist and not live_prod and live_test:
            mech = "DELETE_TEST_ONLY_ISLAND"
            reason = f"only test refs remain: {';'.join(live_test[:8])}"
        elif not dlist and (live_prod or live_test):
            mech = "POTENTIAL_DANGLING_REF"
            reason = "refs without def in scanned set"
        else:
            mech = "POTENTIAL"
            reason = "needs human consumer-closure check"
        n11_rows.append({
            "symbol": name,
            "mech_bucket": mech,
            "mech_reason": reason,
            "defs": ";".join(dlist[:20]) or "-",
            "prod_refs_nondef": ";".join(live_prod[:30]) or "-",
            "test_refs_nondef": ";".join(live_test[:30]) or "-",
            "def_count": len(dlist),
            "prod_ref_count": len(live_prod),
            "test_ref_count": len(live_test),
        })

    write_tsv(
        OUT / "n11_members_classified.tsv",
        ["symbol", "mech_bucket", "mech_reason", "def_count", "prod_ref_count",
         "test_ref_count", "defs", "prod_refs_nondef", "test_refs_nondef"],
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
        "n11_mech_buckets": dict(Counter(r["mech_bucket"] for r in n11_rows)),
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
