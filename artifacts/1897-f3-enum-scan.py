#!/usr/bin/env python3
"""#1897 F3 审计枚举（非生产、不自动判合法）。

stdlib AST + 行扫 → /tmp 静态候选文本，供手工语义成员表。
用法：
  ../Ming_LLM/.venv/bin/python artifacts/1897-f3-enum-scan.py
"""
from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/1897-r4-f3-enum")
OUT.mkdir(parents=True, exist_ok=True)

CJK = re.compile(r"[\u4e00-\u9fff]")
CONSUMERS = {
    "character_context_with_db",
    "project_relation_ledger",
    "turn_region_summary",
    "bind_decisions_to_candidate_events",
    "minister_dossier",
    "faction_context_with_db",
    "prepare_character_materials",
    "prepare_world_materials",
}
FIELDISH = re.compile(
    r"(answer|reply|summary|style|memorial|note|context|label|narrative|"
    r"dialogue|speech|criterion|title|message|text|body|content|reason|"
    r"report|persona|temperament|transcript|gazette|prompt|response|"
    r"status_reason|world_segment|forecast|sim_note|execution_note|"
    r"progress_text|option_label|choice_label|actual_note|reported_note)",
    re.I,
)
WEB_ASSERT = re.compile(
    r"""(?:toBe|toEqual|toContain|toMatch)\s*\(\s*(?:`([^`]+)`|"([^"]*)"|'([^']*)'|([A-Z_][A-Z0-9_]*))"""
)
WEB_SURFACE = re.compile(
    r"textContent|innerText|innerHTML|\.content|message|answer|reply|"
    r"summary|style|narrative|dialogue|gazette|transcript|utterance|"
    r"question|speech|persona|temperament|label|title",
    re.I,
)


class PyVisit(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str]):
        self.rel = rel
        self.lines = lines
        self.cur = None
        self.asserts: list[dict] = []
        self.calls: list[dict] = []

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            old, self.cur = self.cur, node.name
            self.generic_visit(node)
            self.cur = old
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _line(self, lineno: int) -> str:
        return self.lines[lineno - 1].strip() if 0 < lineno <= len(self.lines) else ""

    def _collect(self, lineno: int, kind: str, node: ast.AST | None):
        if not self.cur:
            return
        text = self._line(lineno)
        lits = [
            n.value
            for n in (ast.walk(node) if node else [])
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value
        ]
        has_cjk = any(CJK.search(s) for s in lits) or bool(CJK.search(text))
        is_cmp = isinstance(node, ast.Compare) if node else ("==" in text or " in " in text)
        long_lit = any(len(s) >= 2 and not s.isidentifier() for s in lits)
        fieldish = bool(FIELDISH.search(text))
        if has_cjk or (is_cmp and long_lit) or (fieldish and ("==" in text or " in " in text)):
            self.asserts.append(
                {
                    "file": self.rel,
                    "lineno": lineno,
                    "test": self.cur,
                    "kind": kind,
                    "text": text[:240],
                    "has_cjk": has_cjk,
                    "fieldish": fieldish,
                }
            )

    def visit_Assert(self, node):
        self._collect(node.lineno, "assert", node.test)
        self.generic_visit(node)

    def visit_Call(self, node):
        if not self.cur:
            self.generic_visit(node)
            return
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name and name.startswith("assert"):
            self._collect(node.lineno, name, node)
        if name in CONSUMERS:
            self.calls.append(
                {
                    "file": self.rel,
                    "lineno": node.lineno,
                    "test": self.cur,
                    "fn": name,
                    "text": self._line(node.lineno)[:200],
                }
            )
        self.generic_visit(node)


py_cands: list[dict] = []
py_calls: list[dict] = []
for p in sorted(ROOT.glob("tests/**/*.py")):
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    v = PyVisit(str(p.relative_to(ROOT)), src.splitlines())
    v.visit(tree)
    py_cands.extend(v.asserts)
    py_calls.extend(v.calls)

web_cands: list[dict] = []
web_files = (
    list(ROOT.glob("web/**/*.test.ts"))
    + list(ROOT.glob("web/**/*.test.tsx"))
    + list(ROOT.glob("web/**/*.spec.ts"))
    + list(ROOT.glob("web/**/*.spec.tsx"))
)
for p in sorted(web_files):
    rel = str(p.relative_to(ROOT))
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not any(k in s for k in ("toBe(", "toEqual(", "toContain(", "toMatch(")):
            continue
        m = WEB_ASSERT.search(s)
        lit = ""
        if m:
            lit = next((g for g in m.groups() if g is not None), "") or ""
        surface = bool(WEB_SURFACE.search(s))
        if CJK.search(s) or CJK.search(lit) or surface:
            web_cands.append(
                {
                    "file": rel,
                    "lineno": i,
                    "text": s[:220],
                    "lit": lit[:100],
                    "has_cjk": bool(CJK.search(s) or CJK.search(lit)),
                    "surface": surface,
                }
            )

calls_by_test: dict[tuple[str, str], set[str]] = defaultdict(set)
for c in py_calls:
    calls_by_test[(c["file"], c["test"])].add(c["fn"])

(OUT / "python-prose-candidates.txt").write_text(
    "\n".join(
        f"{c['file']}:{c['lineno']}\t{c['test']}\tcjk={int(c['has_cjk'])}\t{c['text']}"
        for c in py_cands
    )
    + "\n",
    encoding="utf-8",
)
(OUT / "web-prose-candidates.txt").write_text(
    "\n".join(
        f"{c['file']}:{c['lineno']}\tcjk={int(c['has_cjk'])}\tsurf={int(c['surface'])}\t{c['text']}"
        for c in web_cands
    )
    + "\n",
    encoding="utf-8",
)
(OUT / "python-consumer-calls.txt").write_text(
    "\n".join(
        f"{c['file']}:{c['lineno']}\t{c['test']}\t{c['fn']}\t{c['text']}"
        for c in py_calls
    )
    + "\n",
    encoding="utf-8",
)
meta = {
    "python_candidates": len(py_cands),
    "python_cjk": sum(1 for c in py_cands if c["has_cjk"]),
    "web_candidates": len(web_cands),
    "web_cjk": sum(1 for c in web_cands if c["has_cjk"]),
    "consumer_calls": len(py_calls),
    "tests_with_consumers": len(calls_by_test),
    "note": "candidates only; legality requires hand semantic review",
}
(OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False, indent=1))
print("OUT", OUT)
