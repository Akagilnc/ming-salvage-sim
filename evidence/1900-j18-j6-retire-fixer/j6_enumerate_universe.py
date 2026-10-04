#!/usr/bin/env python3
"""#1900 J6 冻结分析：全仓测试声明全集枚举（非生产机制）。

范围（本工作树核实，排除 .git/.baseline/node_modules/evidence）：
  - tests/**/test_*.py、tests/**/*_test.py
  - web/src/**/*.test.ts(x)
未发现 web/tests/、scripts/ 测试、根目录 test_*.py、ming_sim/tests。

用法（工作树根）：
  python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py

产出：
  evidence/1900-j18-j6-retire-fixer/j6-universe.jsonl
  evidence/1900-j18-j6-retire-fixer/j6-universe-summary.json

本脚本只枚举声明全集，不产 retain/delete 语义结论。
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = pathlib.Path(__file__).resolve().parent
SKIP_PARTS = {
    ".git", ".baseline", "node_modules", ".venv", "venv",
    "evidence", "__pycache__", ".pytest_cache",
}

NODE_PROGRAM = r"""
const ts = require(process.cwd() + '/web/node_modules/typescript');
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sf = ts.createSourceFile(
  input.path, input.source, ts.ScriptTarget.Latest, true,
  input.path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
const out = [];
function rootName(expr) {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) return rootName(expr.expression);
  if (ts.isCallExpression(expr)) return rootName(expr.expression);
  return '';
}
function visit(node, groups) {
  let next = groups;
  if (ts.isCallExpression(node)) {
    const root = rootName(node.expression);
    const callback = node.arguments.some(a => ts.isArrowFunction(a) || ts.isFunctionExpression(a));
    if (callback && ['it', 'test', 'describe'].includes(root)) {
      const label = node.arguments[0]?.getText(sf) || '<unnamed>';
      if (root === 'describe') next = groups.concat(label);
      else out.push({
        name: groups.concat(label).join(' / '),
        line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
        end: sf.getLineAndCharacterOfPosition(node.end).line + 1,
        source: node.getText(sf),
      });
    }
  }
  ts.forEachChild(node, child => visit(child, next));
}
visit(sf, []);
process.stdout.write(JSON.stringify(out));
"""


def _skip(path: pathlib.Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def discover_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or _skip(path.relative_to(ROOT)):
            continue
        name = path.name
        rel = path.relative_to(ROOT)
        if name.startswith("test_") and name.endswith(".py"):
            files.append(rel)
        elif name.endswith("_test.py"):
            files.append(rel)
        elif ".test." in name and name.endswith((".ts", ".tsx", ".js", ".jsx")):
            files.append(rel)
        elif name.endswith((".spec.ts", ".spec.tsx")):
            files.append(rel)
    return sorted(files)


def enumerate_py(path: pathlib.Path, source: str) -> list[dict]:
    result = []

    def visit(node, scope):
        is_scope = isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        name = scope + [node.name] if is_scope else scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            seg = ast.get_source_segment(source, node) or ""
            result.append({
                "name": ".".join(name),
                "line": node.lineno,
                "end": node.end_lineno,
                "sha256": hashlib.sha256(seg.encode()).hexdigest()[:16],
            })
        for child in ast.iter_child_nodes(node):
            visit(child, name)

    visit(ast.parse(source), [])
    return result


def enumerate_web(path: pathlib.Path, source: str) -> list[dict]:
    raw = subprocess.check_output(
        ["node", "-e", NODE_PROGRAM],
        input=json.dumps({"path": str(path), "source": source}),
        text=True,
        cwd=ROOT,
    )
    items = json.loads(raw)
    out = []
    for item in items:
        seg = item.pop("source", "")
        out.append({
            "name": item["name"],
            "line": item["line"],
            "end": item["end"],
            "sha256": hashlib.sha256(seg.encode()).hexdigest()[:16],
        })
    return out


def main() -> int:
    files = discover_files()
    rows = []
    roots = sorted({str(pathlib.Path(p).parts[0]) if p.parts else "." for p in files})
    for rel in files:
        source = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        kind = "web" if str(rel).startswith("web/") else "py"
        try:
            members = enumerate_web(rel, source) if kind == "web" else enumerate_py(rel, source)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {rel}: {exc}", file=sys.stderr)
            return 1
        for member in members:
            rows.append({
                "file": str(rel),
                "kind": kind,
                **member,
            })

    summary = {
        "total_members": len(rows),
        "python_members": sum(1 for r in rows if r["kind"] == "py"),
        "web_members": sum(1 for r in rows if r["kind"] == "web"),
        "source_files": len(files),
        "roots": roots,
        "note": "universe only; not J6 class membership; not retain disposition",
    }
    universe_path = OUT_DIR / "j6-universe.jsonl"
    with universe_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (OUT_DIR / "j6-universe-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {universe_path.relative_to(ROOT)} ({len(rows)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
