#!/usr/bin/env python3
"""One-shot #1834 F22 full-repo def/export + reference enumeration.

Temporary stdlib AST (+ optional node/typescript) — NOT a permanent classifier layer.
Emits zero-real-consumer candidates for human responsibility chase.

Coverage:
- Python: FunctionDef / AsyncFunctionDef / ClassDef (+ dataclass AnnAssign fields)
  from ming_sim/**, web_app.py, main.py, launcher.py, spike_settle_tick.py, scripts/**
- TS/TSX: exported const/function/class/type/interface/enum from web/src/**
- References: whole-repo word-boundary hits in ming_sim, web_app, main, launcher,
  spike, scripts, web/src, tests (evidence/archive/docs excluded from DEF collection;
  evidence hits do not count as live consumers)

Outputs under OUT_DIR (default: evidence/1834-f21-f22-fix/enum_out).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(os.environ.get("MING_ENUM_ROOT", ".")).resolve()
OUT = Path(
    os.environ.get(
        "MING_ENUM_OUT",
        str(ROOT / "evidence/1834-f21-f22-fix/enum_out"),
    )
).resolve()
OUT.mkdir(parents=True, exist_ok=True)

SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".tox"}
DUNDER_KEEP = {"__init__", "__call__", "__enter__", "__exit__", "__iter__", "__next__", "__aenter__", "__aexit__"}


def git_ls(*globs: str) -> list[str]:
    cmd = ["git", "-C", str(ROOT), "ls-files", "-z", "--", *globs]
    raw = subprocess.check_output(cmd)
    return [p.decode() for p in raw.split(b"\0") if p]


def skipped(rel: str) -> bool:
    return any(p in SKIP_PARTS for p in Path(rel).parts)


def git_py_under(*prefixes: str) -> list[str]:
    """List tracked .py files under prefixes (avoid ** glob missing top-level)."""
    raw = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--", *prefixes])
    out = []
    for p in raw.split(b"\0"):
        if not p:
            continue
        rel = p.decode()
        if rel.endswith(".py") and not skipped(rel):
            out.append(rel)
    return out


def git_ts_under(*prefixes: str) -> list[str]:
    raw = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--", *prefixes])
    out = []
    for p in raw.split(b"\0"):
        if not p:
            continue
        rel = p.decode()
        if (rel.endswith(".ts") or rel.endswith(".tsx")) and not skipped(rel):
            out.append(rel)
    return out


def is_test_path(rel: str) -> bool:
    return (
        rel.startswith("tests/")
        or "/test_" in rel
        or rel.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def index_hits(shorts: list[str], corpus: dict[str, str]) -> dict[str, list[tuple[str, int, str, bool]]]:
    """short -> list of (rel, line, snippet, is_test)."""
    wanted = {s for s in shorts if len(s) >= 2 and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s)}
    hits: dict[str, list[tuple[str, int, str, bool]]] = {s: [] for s in wanted}
    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    nfiles = len(corpus)
    for fi, (rel, text) in enumerate(corpus.items(), 1):
        if fi % 100 == 0:
            print(f"  index {fi}/{nfiles}", flush=True)
        test = is_test_path(rel)
        for i, line in enumerate(text.splitlines(), 1):
            found = set(ident.findall(line)) & wanted
            if not found:
                continue
            snip = line.strip()[:160]
            for s in found:
                hits[s].append((rel, i, snip, test))
    return hits


@dataclass
class DefRec:
    kind: str  # py_func|py_async|py_class|py_method|py_field|ts_export|ts_type
    qualname: str
    short: str
    path: str
    line: int
    end_line: int
    is_private: bool
    parent: str = ""


def collect_py_defs(rel: str) -> list[DefRec]:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as e:
        print(f"WARN syntax {rel}: {e}", file=sys.stderr)
        return []
    out: list[DefRec] = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []
            self.class_stack: list[ast.ClassDef] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            q = ".".join(self.stack + [node.name]) if self.stack else node.name
            out.append(
                DefRec(
                    kind="py_class",
                    qualname=q,
                    short=node.name,
                    path=rel,
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    is_private=node.name.startswith("_"),
                )
            )
            # dataclass / NamedTuple fields
            decorators = []
            for d in node.decorator_list:
                if isinstance(d, ast.Name):
                    decorators.append(d.id)
                elif isinstance(d, ast.Attribute):
                    decorators.append(d.attr)
                elif isinstance(d, ast.Call):
                    if isinstance(d.func, ast.Name):
                        decorators.append(d.func.id)
                    elif isinstance(d.func, ast.Attribute):
                        decorators.append(d.func.attr)
            is_dc = "dataclass" in decorators
            for b in node.bases:
                if isinstance(b, ast.Name) and b.id == "NamedTuple":
                    is_dc = True
                if isinstance(b, ast.Attribute) and b.attr == "NamedTuple":
                    is_dc = True
            if is_dc:
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        fname = stmt.target.id
                        if fname.startswith("_") and fname.endswith("_"):
                            continue
                        fq = f"{q}.{fname}"
                        out.append(
                            DefRec(
                                kind="py_field",
                                qualname=fq,
                                short=fname,
                                path=rel,
                                line=stmt.lineno,
                                end_line=stmt.lineno,
                                is_private=fname.startswith("_"),
                                parent=q,
                            )
                        )
            self.stack.append(node.name)
            self.class_stack.append(node)
            self.generic_visit(node)
            self.class_stack.pop()
            self.stack.pop()

        def _visit_fn(self, node: ast.AST, kind: str):
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            name = node.name
            if name.startswith("__") and name.endswith("__") and name not in DUNDER_KEEP:
                # skip most dunders; still record __init__/__call__ etc.
                self.generic_visit(node)
                return
            in_class = bool(self.class_stack)
            q = ".".join(self.stack + [name]) if self.stack else name
            out.append(
                DefRec(
                    kind="py_method" if in_class else kind,
                    qualname=q,
                    short=name,
                    path=rel,
                    line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    is_private=name.startswith("_"),
                    parent=".".join(self.stack) if self.stack else "",
                )
            )
            self.stack.append(name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._visit_fn(node, "py_func")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._visit_fn(node, "py_async")

    V().visit(tree)
    return out


TS_EXPORT_RE = re.compile(
    r"(?m)^export\s+(?:async\s+)?(?:default\s+)?"
    r"(?:(?:const|let|var|function|class|enum|type|interface)\s+)"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)
TS_EXPORT_LIST_RE = re.compile(
    r"(?m)^export\s*\{([^}]+)\}"
)
TS_EXPORT_TYPE_LIST_RE = re.compile(
    r"(?m)^export\s+type\s*\{([^}]+)\}"
)


def collect_ts_exports(rel: str) -> list[DefRec]:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    out: list[DefRec] = []
    seen: set[tuple[str, int]] = set()

    def add(name: str, line: int, kind: str):
        key = (name, line)
        if key in seen:
            return
        seen.add(key)
        out.append(
            DefRec(
                kind=kind,
                qualname=name,
                short=name,
                path=rel,
                line=line,
                end_line=line,
                is_private=name.startswith("_"),
            )
        )

    for i, line in enumerate(lines, 1):
        m = TS_EXPORT_RE.match(line)
        if m:
            kind = "ts_type" if re.search(r"\b(type|interface|enum)\b", line) else "ts_export"
            add(m.group(1), i, kind)
            continue
        for rx, kind in ((TS_EXPORT_LIST_RE, "ts_export"), (TS_EXPORT_TYPE_LIST_RE, "ts_type")):
            m2 = rx.match(line)
            if not m2:
                continue
            for part in m2.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                # handle `foo as bar`
                if " as " in part:
                    part = part.split(" as ")[-1].strip()
                name = part.split(":")[0].strip()
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                    add(name, i, kind)
    return out


def load_corpus() -> dict[str, str]:
    files = []
    files.extend(git_py_under("ming_sim", "web_app.py", "main.py", "launcher.py", "spike_settle_tick.py", "scripts", "tests"))
    files.extend(git_ts_under("web/src", "tests"))
    # root-level singles already in prefixes if passed as files
    for extra in ("web_app.py", "main.py", "launcher.py", "spike_settle_tick.py"):
        if (ROOT / extra).exists() and extra not in files:
            # ensure tracked
            tracked = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "--", extra],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if tracked:
                files.append(extra)
    files = sorted({f for f in files if not skipped(f)})
    corpus = {}
    for rel in files:
        try:
            corpus[rel] = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return corpus


def main() -> int:
    py_files = [
        f
        for f in git_py_under(
            "ming_sim",
            "web_app.py",
            "main.py",
            "launcher.py",
            "spike_settle_tick.py",
            "scripts",
        )
        if not f.startswith("tests/") and "/test_" not in Path(f).name
    ]
    ts_files = [
        f
        for f in git_ts_under("web/src")
        if not f.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    ]

    defs: list[DefRec] = []
    for rel in py_files:
        defs.extend(collect_py_defs(rel))
    for rel in ts_files:
        defs.extend(collect_ts_exports(rel))

    print(f"DEF_COUNT {len(defs)} py_files={len(py_files)} ts_files={len(ts_files)}", flush=True)
    corpus = load_corpus()
    print(f"CORPUS_FILES {len(corpus)}", flush=True)

    unique_shorts = sorted({d.short for d in defs})
    print(f"UNIQUE_SHORTS {len(unique_shorts)}", flush=True)
    hit_index = index_hits(unique_shorts, corpus)

    rows = []
    zero_candidates = []
    for d in defs:
        hits = hit_index.get(d.short, [])
        total = len(hits)
        prod = sum(1 for _r, _i, _s, t in hits if not t)
        outside_hits = [
            (rel, i, snip, test)
            for rel, i, snip, test in hits
            if not (rel == d.path and d.line <= i <= d.end_line)
        ]
        outside = len(outside_hits)
        outside_prod = sum(1 for _r, _i, _s, t in outside_hits if not t)
        outside_samples = [f"{rel}:{i}:{snip}" for rel, i, snip, _t in outside_hits[:8]]

        rec = {
            **asdict(d),
            "refs_total_incl_def": total,
            "refs_prod_incl_def": prod,
            "refs_outside_def": outside,
            "refs_outside_prod": outside_prod,
            "samples_outside": outside_samples,
        }
        rows.append(rec)
        if outside == 0:
            zero_candidates.append(rec)
        elif outside_prod == 0 and outside > 0:
            rec2 = dict(rec)
            rec2["zero_kind"] = "prod_zero_test_only"
            zero_candidates.append(rec2)

    # Mark pure zero
    for z in zero_candidates:
        z.setdefault("zero_kind", "absolute_zero")

    # Sort
    rows.sort(key=lambda r: (r["path"], r["line"], r["qualname"]))
    zero_candidates.sort(key=lambda r: (r["zero_kind"], r["path"], r["line"], r["qualname"]))

    (OUT / "f22_all_defs.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    (OUT / "f22_zero_consumer_candidates.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in zero_candidates) + "\n",
        encoding="utf-8",
    )

    # Human-readable table
    lines = [
        f"# F22 zero-real-consumer candidates (machine enum)",
        f"DEF_COUNT={len(defs)} ZERO_ABS={sum(1 for z in zero_candidates if z.get('zero_kind')=='absolute_zero')} "
        f"ZERO_PROD_TEST_ONLY={sum(1 for z in zero_candidates if z.get('zero_kind')=='prod_zero_test_only')}",
        "",
        "| zero_kind | kind | qualname | path:line | private | samples |",
        "|---|---|---|---|---|---|",
    ]
    for z in zero_candidates:
        samp = "<br>".join(z.get("samples_outside") or []) or "(none)"
        lines.append(
            f"| {z.get('zero_kind')} | {z['kind']} | `{z['qualname']}` | `{z['path']}:{z['line']}` | {z['is_private']} | {samp} |"
        )
    (OUT / "f22_zero_consumer_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "def_count": len(defs),
        "py_files": len(py_files),
        "ts_files": len(ts_files),
        "corpus_files": len(corpus),
        "unique_shorts": len(unique_shorts),
        "zero_abs": sum(1 for z in zero_candidates if z.get("zero_kind") == "absolute_zero"),
        "zero_prod_test_only": sum(
            1 for z in zero_candidates if z.get("zero_kind") == "prod_zero_test_only"
        ),
        "by_kind_zero_abs": defaultdict(int),
    }
    for z in zero_candidates:
        if z.get("zero_kind") == "absolute_zero":
            summary["by_kind_zero_abs"][z["kind"]] += 1
    summary["by_kind_zero_abs"] = dict(summary["by_kind_zero_abs"])
    (OUT / "f22_enum_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
