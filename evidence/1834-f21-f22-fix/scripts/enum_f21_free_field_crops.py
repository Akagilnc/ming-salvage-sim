#!/usr/bin/env python3
"""One-shot #1834 F21 free-field crop candidate enum (temporary AST/text).

Does NOT auto-KEEP. Emits assign/append/return/map sites where strip/trim/replace/
slice may rewrite values, for human chase along input→write→read→materialize→feed→UI.

Predicate covers production+scripts+web/src (no test specs as sole set).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("MING_ENUM_ROOT", ".")).resolve()
OUT = Path(
    os.environ.get(
        "MING_ENUM_OUT",
        str(ROOT / "evidence/1834-f21-f22-fix/enum_out"),
    )
).resolve()
OUT.mkdir(parents=True, exist_ok=True)

CROP_ATTRS = {"strip", "lstrip", "rstrip", "trim", "trimStart", "trimEnd", "replace", "split", "join", "substring", "slice"}
# Free-field-ish names commonly carrying human-readable prose (chase candidates; not KEEP filter)
FREEISH = {
    "station",
    "highlight",
    "highlights",
    "phrase",
    "phrases",
    "criterion",
    "spoken",
    "decree_text",
    "content",
    "answer",
    "body",
    "prose",
    "hint",
    "title",
    "summary",
    "context",
    "description",
    "message",
    "text",
    "opening_text",
    "situation",
    "resolve_condition",
    "fail_condition",
    "reason",
    "note",
    "label",
    "report",
    "narrative",
    "display",
    "displayContent",
    "matchedPhrases",
}


def git_ls(*globs: str) -> list[str]:
    raw = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--", *globs])
    return [p.decode() for p in raw.split(b"\0") if p]


def git_py_under(*prefixes: str) -> list[str]:
    raw = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--", *prefixes])
    return [p.decode() for p in raw.split(b"\0") if p and p.decode().endswith(".py")]


def git_ts_under(*prefixes: str) -> list[str]:
    raw = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--", *prefixes])
    out = []
    for p in raw.split(b"\0"):
        if not p:
            continue
        rel = p.decode()
        if rel.endswith(".ts") or rel.endswith(".tsx"):
            out.append(rel)
    return out


def _call_is_crop(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr in CROP_ATTRS:
        return True
    return False


def _expr_has_crop(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if _call_is_crop(n):
            return True
        if isinstance(n, ast.Subscript):
            # slice [:N]
            sl = n.slice
            if isinstance(sl, ast.Slice) and (sl.upper is not None or sl.lower is not None):
                return True
    return False


def collect_py(rel: str) -> list[dict]:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as e:
        print(f"WARN {rel}: {e}", file=sys.stderr)
        return []
    hits: list[dict] = []
    lines = text.splitlines()

    class V(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign):
            if _expr_has_crop(node.value):
                targets = []
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t.id)
                    elif isinstance(t, ast.Attribute):
                        targets.append(t.attr)
                    elif isinstance(t, ast.Subscript):
                        targets.append("<sub>")
                freeish = any(t in FREEISH for t in targets)
                hits.append(
                    {
                        "path": rel,
                        "line": node.lineno,
                        "shape": "assign",
                        "targets": targets,
                        "freeish_name": freeish,
                        "src": lines[node.lineno - 1].strip()[:240],
                    }
                )
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign):
            if node.value is not None and _expr_has_crop(node.value):
                tname = node.target.id if isinstance(node.target, ast.Name) else (
                    node.target.attr if isinstance(node.target, ast.Attribute) else "?"
                )
                hits.append(
                    {
                        "path": rel,
                        "line": node.lineno,
                        "shape": "ann_assign",
                        "targets": [tname],
                        "freeish_name": tname in FREEISH,
                        "src": lines[node.lineno - 1].strip()[:240],
                    }
                )
            self.generic_visit(node)

        def visit_Return(self, node: ast.Return):
            if node.value is not None and _expr_has_crop(node.value):
                hits.append(
                    {
                        "path": rel,
                        "line": node.lineno,
                        "shape": "return",
                        "targets": [],
                        "freeish_name": False,
                        "src": lines[node.lineno - 1].strip()[:240],
                    }
                )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            # out.append(x.strip()) / payload[...] =
            if isinstance(node.func, ast.Attribute) and node.func.attr == "append" and node.args:
                if _expr_has_crop(node.args[0]):
                    hits.append(
                        {
                            "path": rel,
                            "line": node.lineno,
                            "shape": "append",
                            "targets": ["<append>"],
                            "freeish_name": True,  # append of cropped value is suspicious for free lists
                            "src": lines[node.lineno - 1].strip()[:240],
                        }
                    )
            # keyword args with crop
            for kw in node.keywords:
                if kw.arg and _expr_has_crop(kw.value):
                    hits.append(
                        {
                            "path": rel,
                            "line": node.lineno,
                            "shape": "kwarg",
                            "targets": [kw.arg],
                            "freeish_name": kw.arg in FREEISH,
                            "src": lines[node.lineno - 1].strip()[:240],
                        }
                    )
            self.generic_visit(node)

    V().visit(tree)
    return hits


# TS/JS: line-based assign/map with trim/replace/slice
TS_HIT_RE = re.compile(
    r"(?P<lhs>[A-Za-z_][A-Za-z0-9_]*|\w+\[[^\]]+\])\s*=\s*.*\.(?:trim|trimStart|trimEnd|replace|slice|substring|split)\("
    r"|\.map\s*\(\s*(?:\([^)]*\)|[A-Za-z_][A-Za-z0-9_]*)\s*=>\s*[^)]*\.(?:trim|replace|slice)\("
    r"|push\([^)]*\.(?:trim|replace|slice)\("
)


def collect_ts(rel: str) -> list[dict]:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if not TS_HIT_RE.search(line) and not re.search(r"\.(trim|replace|slice|substring)\(", line):
            continue
        # only keep write-ish lines
        if not re.search(r"(=|\.map\(|\.push\(|return\s+)", line):
            continue
        lhs = []
        m = re.match(r"\s*(?:const|let|var)?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            lhs = [m.group(1)]
        freeish = any(x in FREEISH for x in lhs) or any(k in line for k in ("phrase", "highlight", "content", "spoken", "body", "title", "station"))
        hits.append(
            {
                "path": rel,
                "line": i,
                "shape": "ts_line",
                "targets": lhs,
                "freeish_name": freeish,
                "src": line.strip()[:240],
            }
        )
    return hits


def main() -> int:
    py_files = git_py_under(
        "ming_sim",
        "web_app.py",
        "main.py",
        "launcher.py",
        "spike_settle_tick.py",
        "scripts",
    )
    ts_files = [
        f
        for f in git_ts_under("web/src")
        if not f.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    ]
    all_hits: list[dict] = []
    for rel in py_files:
        all_hits.extend(collect_py(rel))
    for rel in ts_files:
        all_hits.extend(collect_ts(rel))
    all_hits.sort(key=lambda h: (h["path"], h["line"]))
    freeish = [h for h in all_hits if h.get("freeish_name")]

    (OUT / "f21_all_crop_write_shapes.jsonl").write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in all_hits) + "\n", encoding="utf-8"
    )
    (OUT / "f21_freeish_crop_candidates.jsonl").write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in freeish) + "\n", encoding="utf-8"
    )

    lines = [
        "# F21 freeish crop-write candidates (NOT auto-KEEP; chase dataflow)",
        f"ALL_CROP_WRITE_SHAPES={len(all_hits)} FREEISH_NAME_CANDIDATES={len(freeish)}",
        "",
        "| path:line | shape | targets | src |",
        "|---|---|---|---|",
    ]
    for h in freeish:
        lines.append(
            f"| `{h['path']}:{h['line']}` | {h['shape']} | {','.join(h['targets']) or '—'} | `{h['src'].replace('|','/')}` |"
        )
    (OUT / "f21_freeish_crop_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "all_crop_write_shapes": len(all_hits),
        "freeish_name_candidates": len(freeish),
        "py_files": len(py_files),
        "ts_files": len(ts_files),
    }
    (OUT / "f21_enum_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
