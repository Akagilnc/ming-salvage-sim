#!/usr/bin/env python3
"""#1897 F3: full tests/ AST enum — NO field-name vocabulary filter.

Enumerate every assert / assert_* / pytest.raises / match= / Compare.
Auth-related = seam symbol touch OR stem anchor (authorized test system).
Free-text CANDIDATE = assert/compare involves non-empty str literal or
whole-object/list literal with str values — membership NOT gated on attr names.
Semantic keep/clear is adjudicated after this dump (see member table).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5")
TESTS = ROOT / "tests"
OUT = Path("/tmp/1897-f1f3-corr5")

SEAM = {
    "create_secret_order",
    "update_secret_order",
    "update_secret_order_by_id",
    "update_secret_order_sim_note",
    "update_secret_order_progress",
    "list_secret_orders",
    "list_dossier_progress",
    "get_secret_order",
    "dispatch_declaration",
    "prepare_world_materials",
    "prepare_gazette_author_materials",
    "prepare_character_materials",
    "settle_due_secret_orders",
    "build_covert_task_contract",
    "record_secret_order_disclosure",
    "secret_order_dossier_ids",
    "apply_score_extraction",
    "dossier_progress",
    "_write_secret_actual_note_files",
    "apply_monthly_covert_actual_progress",
}
STEM = (
    "secret_order",
    "declaration",
    "due_review",
    "execution_pressure",
    "monthly_progress",
    "dossier_reported",
    "deformation",
    "staged_assignment",
    "audience_translate",
    "family_tail",
    "character_knowledge",
    "breach_plea",
    "month_chain",
    "isolation",
    "payoff",
    "gazette",
    "world_materials",
    "decree_dossiers",
    "section_rejection",
    "covert",
    "dossier",
    "pihong",
    "rescript",
    "person_delta",
    "pay_order",
    "urge_lever",
    "relation_capture",
    "authority_ledger",
)


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


def test_ranges(tree: ast.AST):
    r = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
            r.append((n.lineno, getattr(n, "end_lineno", n.lineno), n.name))
    return sorted(r)


def test_at(ranges, ln: int) -> str:
    name = "<module>"
    for a, b, n in ranges:
        if a <= ln <= b:
            name = n
        elif a > ln:
            break
    return name


def seams_in(src: str, tree: ast.AST):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                names.add(a.name)
    hit = sorted(names & SEAM)
    if not hit:
        hit = [s for s in SEAM if s in src]
    return hit


def str_consts_in(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value:
            out.append(n.value)
    return out


def has_collection_lit(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            return True
    return False


def is_raises_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    u = ast.unparse(node.func)
    return "raises" in u


def match_kw(node: ast.Call):
    for kw in node.keywords or []:
        if kw.arg == "match" and kw.value is not None:
            return kw.value
    return None


def classify_expr(expr: ast.AST):
    """Predicate features — NO field-name whitelist."""
    cats = set()
    strs = str_consts_in(expr)
    if any(has_cjk(s) for s in strs):
        cats.add("cjk_lit")
    if any(len(s) >= 2 for s in strs):
        cats.add("str_lit")
    if has_collection_lit(expr):
        cats.add("collection_lit")
    for n in ast.walk(expr):
        if isinstance(n, ast.Compare):
            ops = n.ops
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in ops):
                cats.add("in_op")
            if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in ops):
                cats.add("eq_op")
            if any(isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)) for op in ops):
                # length/limit compares involving str often title>80 style
                cats.add("ord_op")
    # Candidate for free-text mechanical dependency review:
    # any string literal in equality/containment/collection assert surface.
    if strs and (cats & {"eq_op", "in_op", "collection_lit", "str_lit"}):
        cats.add("STR_ASSERT_CANDIDATE")
    return sorted(cats), strs, ast.unparse(expr)[:220]


files = []
rows = []
dups = {}
func_index = []  # auth-related test functions for semantic pass

for path in sorted(TESTS.glob("test_*.py")):
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    files.append(path.name)
    bag = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
            bag.setdefault(n.name, []).append(n.lineno)
    for name, lns in bag.items():
        if len(lns) > 1:
            dups.setdefault(path.name, []).append({"name": name, "lines": lns})
    ranges = test_ranges(tree)
    seam = seams_in(src, tree)
    auth = bool(seam) or any(h in path.stem for h in STEM)

    # index auth test functions
    if auth:
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                func_index.append(
                    {
                        "file": path.name,
                        "line": n.lineno,
                        "test": n.name,
                        "seams": seam,
                        "doc": ast.get_docstring(n) or "",
                    }
                )

    for n in ast.walk(tree):
        ln = getattr(n, "lineno", None)
        if ln is None:
            continue
        tname = test_at(ranges, ln)

        if isinstance(n, ast.Assert):
            cats, strs, detail = classify_expr(n.test)
            rows.append(
                {
                    "file": path.name,
                    "line": ln,
                    "test": tname,
                    "kind": "assert",
                    "cats": cats,
                    "strs": strs[:8],
                    "detail": detail,
                    "auth_related": auth,
                    "seams": seam,
                }
            )
        elif isinstance(n, ast.With):
            for item in n.items:
                ctx = item.context_expr
                if is_raises_call(ctx):
                    mk = match_kw(ctx) if isinstance(ctx, ast.Call) else None
                    cats = ["raises"]
                    strs = str_consts_in(mk) if mk is not None else []
                    if strs:
                        cats.append("match_kw")
                        cats.append("STR_ASSERT_CANDIDATE")
                        if any(has_cjk(s) for s in strs):
                            cats.append("cjk_lit")
                    rows.append(
                        {
                            "file": path.name,
                            "line": ln,
                            "test": tname,
                            "kind": "pytest.raises",
                            "cats": cats,
                            "strs": strs[:8],
                            "detail": ast.unparse(ctx)[:220],
                            "auth_related": auth,
                            "seams": seam,
                        }
                    )
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            a = n.func.attr
            if a.startswith("assert") or a in (
                "assert_called",
                "assert_called_once",
                "assert_called_with",
                "assert_called_once_with",
                "assert_any_call",
                "assert_has_calls",
                "assert_not_called",
            ):
                cats, strs, detail = classify_expr(n)
                kind = "assert_star" if a.startswith("assert") and not a.startswith("assert_called") and a != "assert_not_called" else "mock_assert"
                # unittest-style assertEqual etc.
                if a.startswith("assert") and a not in (
                    "assert_called",
                    "assert_called_once",
                    "assert_called_with",
                    "assert_called_once_with",
                    "assert_any_call",
                    "assert_has_calls",
                    "assert_not_called",
                ):
                    kind = "assert_star"
                if strs and kind in ("assert_star", "mock_assert"):
                    cats = list(set(cats) | {"STR_ASSERT_CANDIDATE"})
                rows.append(
                    {
                        "file": path.name,
                        "line": ln,
                        "test": tname,
                        "kind": kind,
                        "cats": sorted(set(cats)),
                        "strs": strs[:8],
                        "detail": detail,
                        "auth_related": auth,
                        "seams": seam,
                    }
                )
            # pytest.raises as bare call (rare)
            if a == "raises" and isinstance(n.func.value, ast.Name) and n.func.value.id == "pytest":
                mk = match_kw(n)
                cats = ["raises"]
                strs = str_consts_in(mk) if mk is not None else []
                if strs:
                    cats += ["match_kw", "STR_ASSERT_CANDIDATE"]
                rows.append(
                    {
                        "file": path.name,
                        "line": ln,
                        "test": tname,
                        "kind": "pytest.raises",
                        "cats": cats,
                        "strs": strs[:8],
                        "detail": ast.unparse(n)[:220],
                        "auth_related": auth,
                        "seams": seam,
                    }
                )

cand = [r for r in rows if "STR_ASSERT_CANDIDATE" in r.get("cats", [])]
cand_auth = [r for r in cand if r["auth_related"]]
by = {}
for r in rows:
    by[r["kind"]] = by.get(r["kind"], 0) + 1
auth_files = sorted({r["file"] for r in rows if r["auth_related"]})

summary = {
    "ALL_TEST_FILES": len(files),
    "AUTH_RELATED_FILES": len(auth_files),
    "AUTH_RELATED_FILE_LIST": auth_files,
    "ASSERT_ROWS_ALL": len(rows),
    "BY_KIND": by,
    "DUPS": dups or None,
    "STR_ASSERT_CANDIDATE_ALL": len(cand),
    "STR_ASSERT_CANDIDATE_AUTH": len(cand_auth),
    "AUTH_TEST_FUNCS": len(func_index),
    "NOTE": "No TEXT_ATTRS/field whitelist; STR_ASSERT_CANDIDATE is pre-semantic.",
}

(OUT / "f3_full_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "f3_all_asserts.tsv").write_text(
    "\n".join(
        f"{r['file']}:{r['line']}\t{r['kind']}\tauth={int(r['auth_related'])}\t{r['test']}\t{','.join(r['cats'])}\t{r['detail']}"
        for r in rows
    ),
    encoding="utf-8",
)
(OUT / "f3_str_cand_all.tsv").write_text(
    "\n".join(
        f"{r['file']}:{r['line']}\tauth={int(r['auth_related'])}\t{r['test']}\t{','.join(r['cats'])}\t{json.dumps(r['strs'], ensure_ascii=False)}\t{r['detail']}"
        for r in cand
    ),
    encoding="utf-8",
)
(OUT / "f3_str_cand_auth.tsv").write_text(
    "\n".join(
        f"{r['file']}:{r['line']}\t{r['test']}\t{','.join(r['cats'])}\t{json.dumps(r['strs'], ensure_ascii=False)}\t{r['detail']}"
        for r in cand_auth
    ),
    encoding="utf-8",
)
(OUT / "f3_auth_funcs.tsv").write_text(
    "\n".join(f"{r['file']}:{r['line']}\t{r['test']}\t{','.join(r['seams'])}" for r in func_index),
    encoding="utf-8",
)

print(json.dumps({k: summary[k] for k in (
    "ALL_TEST_FILES", "AUTH_RELATED_FILES", "ASSERT_ROWS_ALL", "BY_KIND",
    "DUPS", "STR_ASSERT_CANDIDATE_ALL", "STR_ASSERT_CANDIDATE_AUTH", "AUTH_TEST_FUNCS", "NOTE"
)}, ensure_ascii=False, indent=2))
print("AUTH_RELATED_FILES:")
for f in auth_files:
    print(f)
