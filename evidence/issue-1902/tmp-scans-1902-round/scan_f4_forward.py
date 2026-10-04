#!/usr/bin/env python3
"""F4: full-warehouse pure-forward thin wrappers (AST)."""
from __future__ import annotations
import ast, json, sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
# full production surface: ming_sim + web_app + web python if any
paths = list(ROOT.joinpath("ming_sim").rglob("*.py")) + [ROOT/"web_app.py"]

def strip_doc_body(body):
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body

def call_arg_names(call: ast.Call):
    names = set()
    for a in call.args:
        if isinstance(a, ast.Name):
            names.add(a.id)
        elif isinstance(a, ast.Starred) and isinstance(a.value, ast.Name):
            names.add(a.value.id)
        else:
            return None  # non-name / complex → not pure forward
    for kw in call.keywords:
        if kw.arg is None and isinstance(kw.value, ast.Name):
            names.add(kw.value.id)
        elif kw.arg is not None and isinstance(kw.value, ast.Name) and kw.value.id == kw.arg:
            names.add(kw.arg)
        elif kw.arg is not None and isinstance(kw.value, ast.Name):
            # keyword=othername still forwarding a param
            names.add(kw.value.id)
        else:
            return None
    return names

candidates = []
for path in paths:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception as e:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = strip_doc_body(node.body)
        if len(body) != 1:
            continue
        stmt = body[0]
        call = None
        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
        if call is None:
            continue
        # skip if calling self method with extra logic markers
        arg_names = call_arg_names(call)
        if arg_names is None:
            continue
        params = []
        for a in node.args.args:
            params.append(a.arg)
        for a in node.args.posonlyargs:
            params.append(a.arg)
        for a in node.args.kwonlyargs:
            params.append(a.arg)
        if node.args.vararg:
            params.append(node.args.vararg.arg)
        if node.args.kwarg:
            params.append(node.args.kwarg.arg)
        # drop typical self/cls
        param_set = set(params)
        if "self" in param_set:
            param_set = param_set - {"self"}
            arg_names = arg_names - {"self"}
        if "cls" in param_set:
            param_set = param_set - {"cls"}
            arg_names = arg_names - {"cls"}
        if not arg_names.issubset(param_set):
            continue
        # callee name
        if isinstance(call.func, ast.Name):
            callee = call.func.id
        elif isinstance(call.func, ast.Attribute):
            callee = ast.unparse(call.func) if hasattr(ast, "unparse") else call.func.attr
        else:
            callee = "<expr>"
        # exclude dunder / property-like trivial if same name recursion
        if callee == node.name:
            continue
        candidates.append({
            "file": str(path.relative_to(ROOT)),
            "line": node.lineno,
            "name": node.name,
            "callee": callee,
            "params": params,
            "forwarded": sorted(arg_names),
            "src": ast.get_source_segment(src, node) or "",
        })

out = {"candidate_count": len(candidates), "candidates": candidates}
Path("/tmp/ming1902-f1f4-rescand/f4_forward_scan.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"f4_pure_forward_candidates={len(candidates)}")
for c in candidates:
    print(f"{c['file']}:{c['line']}\t{c['name']} -> {c['callee']}")
