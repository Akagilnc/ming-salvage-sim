#!/usr/bin/env python3
"""#1847 w8 N11 — full-repo production-def consumer graph (NO name keyword filter).

Production surface: git-tracked ming_sim/**/*.py + web_app.py.
Enums every module/class-level FunctionDef/AsyncFunctionDef (skips nested
locals). Counts word-boundary refs in prod / tests / other tracked py.
Classifies DEAD_ZERO_REFS / TEST_ONLY / OTHER_ONLY / HAS_PROD_REFS /
KEEP_INTERFACE (dunder / FastAPI route / property / abstractmethod / agno override).

Replay:
  MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \\
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \\
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \\
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w8-scans/scan_n11_all_prod_defs.py

Writes:
  evidence/1847-w8-scans/n11_all_prod_defs.tsv
  evidence/1847-w8-n11-members.tsv  (actionable subset + CLEAR residuals)
"""
from __future__ import annotations

import ast
import csv
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MEMBERS = ROOT / "evidence" / "1847-w8-n11-members.tsv"


def git_tracked() -> list[str]:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files"], text=True
    ).splitlines()


def is_prod(rel: str) -> bool:
    return rel == "web_app.py" or (rel.startswith("ming_sim/") and rel.endswith(".py"))


def is_test(rel: str) -> bool:
    return rel.startswith("tests/") and rel.endswith(".py")


def main() -> None:
    tracked = set(git_tracked())
    prod_files = sorted(r for r in tracked if is_prod(r))
    test_files = sorted(r for r in tracked if is_test(r))
    other_files = sorted(
        r
        for r in tracked
        if r.endswith(".py")
        and not is_prod(r)
        and not is_test(r)
        and not r.startswith(("evidence/", "docs/", "archive/", "."))
    )

    defs_by_name: dict[str, list[dict]] = defaultdict(list)
    for rel in prod_files:
        path = ROOT / rel
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            print("SYNTAX", rel, exc)
            continue

        class V(ast.NodeVisitor):
            def __init__(self) -> None:
                self.class_stack: list[str] = []
                self.fn_depth = 0

            def visit_ClassDef(self, n: ast.ClassDef) -> None:
                self.class_stack.append(n.name)
                self.generic_visit(n)
                self.class_stack.pop()

            def visit_FunctionDef(self, n: ast.FunctionDef) -> None:
                if self.fn_depth > 0:
                    self.fn_depth += 1
                    self.generic_visit(n)
                    self.fn_depth -= 1
                    return
                decos = [
                    ast.get_source_segment(src, d) or ast.dump(d)[:80]
                    for d in n.decorator_list
                ]
                qual = ".".join(self.class_stack + [n.name]) if self.class_stack else n.name
                defs_by_name[n.name].append(
                    {
                        "rel": rel,
                        "line": n.lineno,
                        "end": n.end_lineno or n.lineno,
                        "qual": qual,
                        "decos": decos,
                        "dunder": n.name.startswith("__") and n.name.endswith("__"),
                        "override": any(
                            "type: ignore[override]" in (ast.get_source_segment(src, n) or "")
                            for _ in [0]
                        )
                        or "ignore[override]"
                        in src.splitlines()[n.lineno - 1],
                    }
                )
                self.fn_depth += 1
                self.generic_visit(n)
                self.fn_depth -= 1

            visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        V().visit(tree)

    texts: dict[str, str] = {}
    for rel in prod_files + test_files + other_files:
        try:
            texts[rel] = (ROOT / rel).read_text(encoding="utf-8")
        except OSError:
            pass

    results: list[dict] = []
    for name, locs in defs_by_name.items():
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        def_keys = {(d["rel"], d["line"]) for d in locs}
        prod_hits: list[str] = []
        test_hits: list[str] = []
        other_hits: list[str] = []
        for rel, text in texts.items():
            if name not in text:
                continue
            for i, ln in enumerate(text.splitlines(), 1):
                if not pat.search(ln) or ln.strip().startswith("#"):
                    continue
                if (rel, i) in def_keys and re.search(
                    rf"^\s*(async\s+)?def\s+{re.escape(name)}\b", ln
                ):
                    continue
                hit = f"{rel}:{i}"
                if is_test(rel):
                    test_hits.append(hit)
                elif is_prod(rel):
                    prod_hits.append(hit)
                else:
                    other_hits.append(hit)

        for d in locs:
            keep_reason = ""
            if d["dunder"]:
                keep_reason = "dunder_protocol"
            elif d.get("override"):
                keep_reason = "method_interface_override"
            elif d["decos"]:
                joined = ";".join(d["decos"])
                if any(
                    x in joined
                    for x in (
                        "app.",
                        "router.",
                        "get(",
                        "post(",
                        "put(",
                        "delete(",
                        "patch(",
                        "websocket(",
                        "@property",
                        "staticmethod",
                        "classmethod",
                        "abstractmethod",
                        "overload",
                    )
                ):
                    keep_reason = f"decorator:{joined[:120]}"
                else:
                    keep_reason = f"decorator_other:{joined[:120]}"

            n_prod, n_test, n_other = len(prod_hits), len(test_hits), len(other_hits)
            if n_prod == 0 and n_test == 0 and n_other == 0:
                bucket = "DEAD_ZERO_REFS"
            elif n_prod == 0 and n_other > 0:
                bucket = "OTHER_ONLY"  # scripts/tooling consumers count
            elif n_prod == 0 and n_test > 0:
                bucket = "TEST_ONLY"
            else:
                bucket = "HAS_PROD_REFS"

            disposition = bucket
            if bucket in ("DEAD_ZERO_REFS", "TEST_ONLY", "OTHER_ONLY") and keep_reason:
                if (
                    d["dunder"]
                    or keep_reason == "method_interface_override"
                    or keep_reason.startswith("decorator:")
                ):
                    disposition = "KEEP_INTERFACE"

            results.append(
                {
                    "symbol": name,
                    "qual": d["qual"],
                    "loc": f"{d['rel']}:{d['line']}",
                    "bucket": bucket,
                    "disposition": disposition,
                    "prod_refs": n_prod,
                    "test_refs": n_test,
                    "other_refs": n_other,
                    "keep_reason": keep_reason,
                    "prod_sample": ",".join(prod_hits[:3]),
                    "test_sample": ",".join(test_hits[:3]),
                    "other_sample": ",".join(other_hits[:3]),
                    "name_collision_defs": len(locs),
                }
            )

    tsv = OUT / "n11_all_prod_defs.tsv"
    fields = list(results[0].keys()) if results else []
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in sorted(results, key=lambda x: (x["disposition"], x["loc"])):
            w.writerow({k: ("" if v is None else str(v)).rstrip() for k, v in r.items()})

    c = Counter(r["disposition"] for r in results)
    print("TOTAL_DEFS", len(results))
    print("BY_DISPOSITION")
    for k, v in c.most_common():
        print(f"  {v}\t{k}")
    print("Wrote", tsv)

    # Actionable members table: non-HAS_PROD + prior CLEAR symbols
    prior_clear = []
    if MEMBERS.exists():
        with MEMBERS.open(encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("disposition") == "CLEAR":
                    prior_clear.append(row)

    actionable = [
        r
        for r in results
        if r["disposition"]
        in (
            "DEAD_ZERO_REFS",
            "TEST_ONLY",
            "OTHER_ONLY",
            "KEEP_INTERFACE",
        )
        or (
            r["disposition"] == "HAS_PROD_REFS"
            and (
                r["symbol"].startswith("_migrate_")
                or r["symbol"].startswith("_backfill_")
                or "legacy" in r["symbol"].lower()
            )
        )
    ]
    with MEMBERS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "symbol",
                "qual",
                "loc",
                "disposition",
                "behavior",
                "prod_refs",
                "test_refs",
                "other_refs",
                "keep_reason",
                "notes",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        w.writeheader()
        for row in prior_clear:
            # refresh CLEAR residual check
            sym = row["symbol"]
            hits = 0
            for rel, text in texts.items():
                if sym in text:
                    for ln in text.splitlines():
                        if sym in ln and not ln.strip().startswith("#"):
                            if not re.search(rf"^\s*(async\s+)?def\s+{re.escape(sym)}\b", ln):
                                hits += 1
            w.writerow(
                {
                    "symbol": sym,
                    "qual": row.get("qual", "-"),
                    "loc": "ABSENT",
                    "disposition": "CLEAR" if hits == 0 else "RESIDUAL",
                    "behavior": "deleted",
                    "prod_refs": 0,
                    "test_refs": 0,
                    "other_refs": 0,
                    "keep_reason": "",
                    "notes": f"rescan_hits={hits}",
                }
            )
        for r in sorted(actionable, key=lambda x: (x["disposition"], x["loc"])):
            w.writerow(
                {
                    "symbol": r["symbol"],
                    "qual": r["qual"],
                    "loc": r["loc"],
                    "disposition": r["disposition"],
                    "behavior": r["bucket"],
                    "prod_refs": r["prod_refs"],
                    "test_refs": r["test_refs"],
                    "other_refs": r["other_refs"],
                    "keep_reason": r["keep_reason"],
                    "notes": f"P={r['prod_sample']};T={r['test_sample']};O={r['other_sample']}",
                }
            )
    print("Wrote", MEMBERS)


if __name__ == "__main__":
    main()
