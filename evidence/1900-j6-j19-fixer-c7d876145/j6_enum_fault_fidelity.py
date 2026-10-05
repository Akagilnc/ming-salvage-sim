#!/usr/bin/env python3
"""#1900 J6 enum: failure-path / original-fault fidelity contracts (raises-only included).

Predicate covers the current ticket class definition:
- necessary failure behavior and original-fault fidelity weakened or missed
  while cleaning wording locks / internal pseudo-proofs
- includes: pytest.raises without match, cause/context, persistent diagnosis,
  secondary failures (rollback / reload / error-pack write), async failures
- does NOT require mechanical identity asserts on every exception test

Outputs member tables for human semantic disposition. Does not mutate sources.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
from collections import Counter

ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "evidence/1900-j6-j19-fixer-c7d876145"


def tracked_test_paths() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    paths: list[str] = []
    seen: set[str] = set()
    for b in raw:
        if not b:
            continue
        s = b.decode()
        if s.startswith("evidence/") or "/__pycache__/" in s:
            continue
        keep = False
        if s.endswith(".py") and (
            s.startswith("tests/") or "/tests/" in s or s.endswith("_test.py")
        ):
            keep = True
        elif re.search(r"\.(test|spec)\.(ts|tsx)$", s):
            keep = True
        if keep and s not in seen:
            seen.add(s)
            paths.append(s)
    return paths


SECONDARY = re.compile(
    r"(rollback|reload|error_pack|write_error_pack|cleanup|delete_chat|"
    r"fail_chat|atomic_and_reload|call_failure|SettlementAbort|"
    r"pack_exc|cleanup_error|reload_exc|secondary)",
    re.I,
)
ASYNC = re.compile(
    r"(Thread|join|spawn|worker|asyncio|async |await |drain|background|"
    r"concurrent|Future|Executor)",
    re.I,
)
DIAG = re.compile(
    r"(call_failure|error_pack_path|failure\.get\(|\.message|__cause__|"
    r"__context__|\.args\b|excinfo|caught\.value|ei\.value)",
    re.I,
)
TYPE_ONLY = re.compile(
    r"pytest\.raises\([^,\n)]+\)\s*(as\s+\w+\s*)?:",
)
NONEMPTY = re.compile(
    r"str\([^)]*message[^)]*\)\.strip\(\)|"
    r"assert\s+.*message.*strip|"
    r"bool\([^)]*message|"
    r"assert\s+.*get\([\"']message[\"']\)",
    re.I,
)


class RaiseVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.stack: list[str] = []
        self.rows: list[dict] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _test(self) -> str:
        for name in reversed(self.stack):
            if name.startswith("test_"):
                return name
        return self.stack[-1] if self.stack else ""

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            call = item.context_expr
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = ""
            if isinstance(func, ast.Attribute) and func.attr == "raises":
                name = "pytest.raises"
            elif isinstance(func, ast.Name) and func.id == "raises":
                name = "raises"
            if not name:
                continue
            kw = {k.arg for k in call.keywords if k.arg}
            has_match = "match" in kw
            has_check = "check" in kw
            bound = item.optional_vars.id if isinstance(item.optional_vars, ast.Name) else ""
            body_src = ast.get_source_segment(self._src, node) or ""
            tags = ["RAISES"]
            if has_match:
                tags.append("HAS_MATCH")
            else:
                tags.append("RAISES_NO_MATCH")
            if has_check:
                tags.append("HAS_CHECK")
            if bound:
                tags.append("CAPTURED")
            else:
                tags.append("UNCAPTURED")
            if SECONDARY.search(body_src) or SECONDARY.search(self._test()):
                tags.append("SECONDARY_HINT")
            if ASYNC.search(body_src) or ASYNC.search(self._test()):
                tags.append("ASYNC_HINT")
            if DIAG.search(body_src):
                tags.append("DIAG_HINT")
            # post-assert identity signals inside with-body siblings handled later
            self.rows.append(
                {
                    "file": self.path,
                    "line": node.lineno,
                    "test": self._test(),
                    "tags": tags,
                    "bound": bound,
                    "snippet": body_src.split("\n", 1)[0][:160],
                }
            )
        self.generic_visit(node)


def scan_file(path: str) -> tuple[list[dict], list[dict]]:
    text = (ROOT / path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return (
            [
                {
                    "file": path,
                    "line": 0,
                    "test": "",
                    "tags": ["PARSE_ERROR"],
                    "bound": "",
                    "snippet": str(exc)[:160],
                }
            ],
            [],
        )
    v = RaiseVisitor(path)
    v._src = text
    v.visit(tree)

    # Function-level fidelity signals (cause/context/args/message)
    fidelity_rows: list[dict] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        src = ast.get_source_segment(text, node) or ""
        tags: list[str] = []
        if "__cause__" in src or "__context__" in src:
            tags.append("CAUSE_CONTEXT")
        if re.search(r"\.args\b", src):
            tags.append("ARGS_IDENTITY")
        if "call_failure" in src or "error_pack_path" in src:
            tags.append("PERSIST_DIAG")
        if SECONDARY.search(src):
            tags.append("SECONDARY_HINT")
        if ASYNC.search(src):
            tags.append("ASYNC_HINT")
        if TYPE_ONLY.search(src):
            tags.append("TYPE_ONLY_RAISES")
        if NONEMPTY.search(src) and "call_failure" in src:
            tags.append("NONEMPTY_DIAG")
        # weak: raises captured but no args/cause/message identity after
        has_raises = "pytest.raises" in src or "raises(" in src
        has_identity = any(
            x in src
            for x in (
                "__cause__",
                "__context__",
                ".args",
                "is ei.value",
                "is caught.value",
                "is excinfo.value",
            )
        )
        if has_raises and not has_identity and (
            SECONDARY.search(src) or "preserv" in src.lower() or "原" in src
        ):
            tags.append("FIDELITY_CONTRACT_CANDIDATE")
        if tags:
            fidelity_rows.append(
                {
                    "file": path,
                    "line": node.lineno,
                    "test": node.name,
                    "tags": tags,
                    "snippet": (node.body[0].value.s if False else "")[:1],
                }
            )
            fidelity_rows[-1]["snippet"] = src.split("\n", 1)[0][:120]
    return v.rows, fidelity_rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raises_rows: list[dict] = []
    fidelity_rows: list[dict] = []
    for path in tracked_test_paths():
        if not path.endswith(".py"):
            continue
        r, f = scan_file(path)
        raises_rows.extend(r)
        fidelity_rows.extend(f)

    (OUT / "j6-raises-raw.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in raises_rows),
        encoding="utf-8",
    )
    (OUT / "j6-fidelity-candidates.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in fidelity_rows),
        encoding="utf-8",
    )

    no_match = [r for r in raises_rows if "RAISES_NO_MATCH" in r["tags"]]
    secondary = [
        r
        for r in raises_rows
        if "SECONDARY_HINT" in r["tags"] or "ASYNC_HINT" in r["tags"]
    ]
    weak = [
        f
        for f in fidelity_rows
        if "FIDELITY_CONTRACT_CANDIDATE" in f["tags"]
        or "NONEMPTY_DIAG" in f["tags"]
        or ("TYPE_ONLY_RAISES" in f["tags"] and "SECONDARY_HINT" in f["tags"])
    ]

    summary = {
        "test_py_files": sum(1 for p in tracked_test_paths() if p.endswith(".py")),
        "raises_total": len(raises_rows),
        "raises_no_match": len(no_match),
        "raises_secondary_or_async_hint": len(secondary),
        "fidelity_function_hits": len(fidelity_rows),
        "weak_candidates": len(weak),
        "tag_counts": Counter(t for r in raises_rows for t in r["tags"]),
    }
    (OUT / "j6-enum-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    lines = [
        "# J6 inventory (auto) — NOT the disposition report",
        "",
        "Human semantic disposition lives in `j6-members.md` / `j6-disposition.jsonl`.",
        "This script only refreshes raise/fidelity inventory JSONL; it must not conclude KEEP.",
        "",
        f"- tracked test py files: {summary['test_py_files']}",
        f"- pytest.raises sites: {summary['raises_total']}（RAISES_NO_MATCH={summary['raises_no_match']}）",
        f"- secondary/async hint raises: {summary['raises_secondary_or_async_hint']}",
        f"- function-level fidelity hits: {summary['fidelity_function_hits']}",
        f"- weak candidates recalled: {summary['weak_candidates']}",
        "",
        "Weak recall list (inventory only):",
        "",
    ]
    for f in sorted(weak, key=lambda x: (x["file"], x["line"])):
        lines.append(f"- `{f['file']}::{f['test']}` @ {f['line']} ({', '.join(f['tags'])})")
    (OUT / "j6-inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
