#!/usr/bin/env python3
"""#1847 w8 N14 — enumerate ALL test functions (not only private-helper asserts).

For every FunctionDef in tests/test_*.py whose name starts with test_:
  - collect assert Call targets (private/public helpers, production attrs)
  - flag inspect.getsource / helper↔helper / self-same dict field / tautology
  - classify KEEP_REAL_ENTRY / KEEP_TEST_FIXTURE / KEEP_PAYLOAD /
    DELETE_PURE_HELPER / DELETE_DUP_PROOF / DELETE_SELF_SAME / REVIEW

Replay:
  MING_SIM_AGY_BIN=/usr/bin/false ... \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w8-scans/scan_n14_all_test_fns.py

Writes evidence/1847-w8-n14-members.tsv and evidence/1847-w8-scans/n14_all_test_fns.tsv
"""
from __future__ import annotations

import ast
import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MEMBERS = ROOT / "evidence" / "1847-w8-n14-members.tsv"
TESTS = ROOT / "tests"

SELF_SAME = re.compile(r"""['\"](\w+)['\"]\s*:\s*(\w+)\[['\"]\1['\"]\]""")


def call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        parts = []
        cur: ast.AST = f
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def is_private_call(node: ast.AST) -> bool:
    name = call_name(node)
    if not name:
        return False
    leaf = name.split(".")[-1]
    return leaf.startswith("_")


def is_prodish_attr(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    base = node.func.value
    if isinstance(base, ast.Name) and base.id in {
        "db",
        "dbmod",
        "game",
        "session",
        "client",
        "web_app",
        "cb",
        "an",
        "issues",
        "flows",
        "month_chain",
    }:
        return True
    return False


def classify_test(fn: ast.FunctionDef, src: str, lines: list[str]) -> dict:
    kinds: set[str] = set()
    snippets: list[str] = []
    entry_calls: list[str] = []
    private_asserts = 0
    public_helper_asserts = 0
    helper_eq_helper = 0
    self_same = 0
    getsource = 0

    # line-level self-same / getsource inside function span
    for i in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
        if i < 1 or i > len(lines):
            continue
        s = lines[i - 1].strip()
        if s.startswith("#"):
            continue
        if "inspect.getsource" in s:
            getsource += 1
            kinds.add("inspect_getsource")
            snippets.append(f"{i}:getsource:{s[:100]}")
        if SELF_SAME.search(s):
            self_same += 1
            kinds.add("self_same_dict_field")
            snippets.append(f"{i}:self_same:{s[:100]}")

    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            t = node.test
            if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(
                t.ops[0], (ast.Eq, ast.Is)
            ):
                left, right = t.left, t.comparators[0]
                ln = getattr(node, "lineno", 0)
                snip = lines[ln - 1].strip()[:120] if 0 < ln <= len(lines) else ""
                if is_private_call(left) and is_private_call(right):
                    helper_eq_helper += 1
                    kinds.add("helper_eq_helper")
                    snippets.append(f"{ln}:helper_eq:{snip}")
                elif is_private_call(left) or is_private_call(right):
                    private_asserts += 1
                    kinds.add("private_helper_assert")
                    snippets.append(f"{ln}:priv:{snip}")
                else:
                    # public helper call on either side
                    for side in (left, right):
                        cn = call_name(side)
                        if cn and not cn.split(".")[-1].startswith("test"):
                            if is_prodish_attr(side) or (
                                isinstance(side, ast.Call)
                                and isinstance(side.func, ast.Name)
                                and not side.func.id.startswith("_")
                            ):
                                public_helper_asserts += 1
                                kinds.add("public_helper_assert")
                                entry_calls.append(cn)
                                snippets.append(f"{ln}:pub:{snip}")
        # any call that looks like real entry
        if isinstance(node, ast.Call):
            cn = call_name(node)
            if not cn:
                continue
            leaf = cn.split(".")[-1]
            if leaf in {
                "scene_chat",
                "dispatch_month_segment",
                "apply_score_extraction",
                "run_player_month_chain",
                "issue_decree",
                "settle_ming_province_substrate_ticks",
                "apply_dossier_promulgation",
                "recognize_audience_command",
                "run_with_transport",
                "accrue_blood_debt",
                "apply_fixed_period_flows",
                "settle_province_tick",
                "run_month_end_relation_brew",
                "resolve_relation_edge_events_from_extraction",
                # common test-local wrappers that still hit production apply seams
                "_apply",
                "_apply_extraction",
                "_apply_score",
            } or is_prodish_attr(node):
                entry_calls.append(cn)

    # disposition
    if getsource or helper_eq_helper:
        disposition = "DELETE_PURE_HELPER"
    elif self_same and not entry_calls:
        disposition = "DELETE_SELF_SAME"
    elif private_asserts and not entry_calls:
        disposition = "DELETE_PURE_HELPER"
    elif entry_calls:
        # Public helper asserts that still touch db/game/session/client = real entry
        # by business contract (structured result via live owner), not pure helper proof.
        disposition = "KEEP_REAL_ENTRY"
    elif public_helper_asserts:
        disposition = "DELETE_PUBLIC_HELPER_PROOF"
    elif self_same:
        disposition = "KEEP_PAYLOAD_CONSTRUCTION"
    else:
        disposition = "KEEP_BEHAVIOR_OR_FIXTURE"

    return {
        "file": "",
        "line": fn.lineno,
        "test": fn.name,
        "disposition": disposition,
        "kinds": ",".join(sorted(kinds)) if kinds else "none",
        "entry_calls": ";".join(sorted(set(entry_calls))[:8]),
        "private_asserts": private_asserts,
        "public_helper_asserts": public_helper_asserts,
        "helper_eq_helper": helper_eq_helper,
        "self_same": self_same,
        "getsource": getsource,
        "snippet": " | ".join(snippets[:3]),
    }


def main() -> None:
    rows: list[dict] = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            rows.append(
                {
                    "file": path.name,
                    "line": 0,
                    "test": "<syntax_error>",
                    "disposition": "REVIEW",
                    "kinds": "syntax_error",
                    "entry_calls": "",
                    "private_asserts": 0,
                    "public_helper_asserts": 0,
                    "helper_eq_helper": 0,
                    "self_same": 0,
                    "getsource": 0,
                    "snippet": str(exc)[:120],
                }
            )
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                row = classify_test(node, text, lines)
                row["file"] = path.name
                rows.append(row)
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                        row = classify_test(item, text, lines)
                        row["file"] = path.name
                        row["test"] = f"{node.name}.{item.name}"
                        rows.append(row)

    fields = list(rows[0].keys()) if rows else []
    full = OUT / "n14_all_test_fns.tsv"
    with full.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else str(v)).rstrip() for k, v in r.items()})
    with MEMBERS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else str(v)).rstrip() for k, v in r.items()})

    c = Counter(r["disposition"] for r in rows)
    print("TOTAL_TEST_FNS", len(rows))
    print("BY_DISPOSITION")
    for k, v in c.most_common():
        print(f"  {v}\t{k}")
    deleteish = [r for r in rows if r["disposition"].startswith("DELETE") or r["disposition"].startswith("REVIEW")]
    print("DELETE_OR_REVIEW", len(deleteish))
    for r in deleteish[:60]:
        print(f"  {r['disposition']}\t{r['file']}:{r['line']}\t{r['test']}\t{r['kinds']}")
    if len(deleteish) > 60:
        print(f"  ... +{len(deleteish)-60}")
    print("Wrote", full)
    print("Wrote", MEMBERS)


if __name__ == "__main__":
    main()
