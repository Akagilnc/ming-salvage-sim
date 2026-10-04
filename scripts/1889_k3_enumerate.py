#!/usr/bin/env python3
"""#1889 K3 one-shot AST enum. Candidates → system temp only.

Reuse stdlib ast + TypeScript compiler AST; do not invent a disposition engine.
Py: every assert / comparison / pytest.raises(match=) / string op / bare pass.
TS: expect / DOM / string selection. Classification stays in the receipt, not here.
"""
from __future__ import annotations
import ast, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRM = "startswith endswith find index split match search fullmatch sub replace strip count join".split()


def lit(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "${}"
            for v in n.values
        )
    return ""


def gfiles(*pats):
    out = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", *pats], text=True)
    return [ROOT / p for p in out.splitlines() if p]


def scan_py(path: Path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    rel, rows = str(path.relative_to(ROOT)), []

    def add(kind, node, literal="", text=""):
        rows.append({"lang": "py", "kind": kind, "file": rel,
                     "line": getattr(node, "lineno", 0),
                     "literal": literal[:120], "text": text[:200]})

    for node in ast.walk(tree):
        if isinstance(node, ast.Pass):
            add("pass", node, text="pass")
        if isinstance(node, (ast.Assert, ast.Compare)):
            add(type(node).__name__, node, text=ast.get_source_segment(src, node) or "")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in STRM:
                add(f"strmethod_{fn.attr}", node, lit(node.args[0]) if node.args else "",
                    ast.get_source_segment(src, node) or "")
            if (isinstance(fn, ast.Attribute) and fn.attr == "raises") or (isinstance(fn, ast.Name) and fn.id == "raises"):
                for kw in node.keywords:
                    if kw.arg == "match":
                        add("raises_match", node, lit(kw.value), ast.get_source_segment(src, node) or "")
    return rows


_TS = r"""
const ts=require('typescript'),fs=require('fs');
const paths=JSON.parse(fs.readFileSync(0,'utf8')),out=[];
const EXP=new Set(['expect','toContain','toHaveTextContent','toMatch','toEqual','toBe','toStrictEqual','toMatchSnapshot','toHaveAccessibleName','toHaveAttribute','toHaveDisplayValue']);
const DOM=new Set(['getByText','findByText','queryByText','getByRole','findByRole','queryByRole','getByLabelText','findByLabelText','queryByLabelText','querySelector','querySelectorAll']);
for (const file of paths){
  const src=fs.readFileSync(file,'utf8'),sf=ts.createSourceFile(file,src,ts.ScriptTarget.Latest,true);
  (function v(n){if(ts.isCallExpression(n)){let name='';const t=n.expression;
    if(ts.isPropertyAccessExpression(t))name=t.name.text;else if(ts.isIdentifier(t))name=t.text;
    const a=n.arguments&&n.arguments[0],lit=(a&&(ts.isStringLiteral(a)||ts.isNoSubstitutionTemplateLiteral(a)))?a.text:'';
    const line=sf.getLineAndCharacterOfPosition(n.getStart()).line+1;
    if(EXP.has(name)||name.startsWith('to')||name==='expect')out.push({lang:'js',kind:'expect_'+name,file,line,literal:lit,text:n.getText().slice(0,200)});
    if(DOM.has(name)||/^(get|find|query)(All)?By/.test(name)||['includes','startsWith','endsWith','match','test','find','filter','getAttribute'].includes(name))out.push({lang:'js',kind:'selection_'+name,file,line,literal:lit,text:n.getText().slice(0,200)});
  }ts.forEachChild(n,v)})(sf);
}
process.stdout.write(JSON.stringify(out));
"""


def scan_ts(files):
    if not files:
        return []
    abs_paths = [str(p) for p in files]
    proc = subprocess.run(["node", "-e", _TS], input=json.dumps(abs_paths),
                          capture_output=True, text=True, cwd=str(ROOT / "web"), check=True)
    rows = json.loads(proc.stdout)
    for r in rows:
        r["file"] = str(Path(r["file"]).resolve().relative_to(ROOT))
        r["literal"] = str(r.get("literal") or "")[:120]
        r["text"] = str(r.get("text") or "")[:200]
    return rows


def main():
    tracked = gfiles()
    py = [p for p in tracked if p.suffix == '.py' and
          ('tests' in p.parts or p.name.startswith('test_') or p.name.endswith('_test.py'))]
    js = [p for p in tracked if any(mark in p.name for mark in ('.test.', '.spec.'))
          and p.suffix in ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')]
    rows = [r for p in py for r in scan_py(p)] + scan_ts(js)
    out = Path(tempfile.mkdtemp(prefix="1889-k3-enum-")) / "candidates.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    by = {}
    for r in rows:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print(json.dumps({"out": str(out), "files_scanned": len(py) + len(js),
                      "py": sum(1 for r in rows if r["lang"] == "py"),
                      "js": sum(1 for r in rows if r["lang"] == "js"),
                      "total": len(rows), "by_kind": by}, ensure_ascii=False, indent=2))
    print(f"CANDIDATES={out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
