#!/usr/bin/env python3
"""F1 full-warehouse: every ExceptHandler in ming_sim + web_app; classify wash-to-normal."""
from __future__ import annotations
import ast
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
TARGETS = []
for p in sorted((ROOT / "ming_sim").rglob("*.py")):
    TARGETS.append(p)
web = ROOT / "web_app.py"
if web.exists():
    TARGETS.append(web)

def lineno(n):
    return getattr(n, "lineno", None)

def is_empty_const(n):
    if isinstance(n, ast.Constant):
        return n.value in ("", None, False, 0) or n.value == {} or n.value == []
    if isinstance(n, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return len(getattr(n, "elts", getattr(n, "keys", []))) == 0
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"dict", "list", "set", "tuple"}:
        return not n.args and not n.keywords
    return False

def returns_empty(n):
    return isinstance(n, ast.Return) and (n.value is None or is_empty_const(n.value))

def assigns_empty(n):
    if not isinstance(n, ast.Assign):
        return False
    return is_empty_const(n.value)

def looks_like_intent_none(n):
    # assign/return "无" or draft_action "无"
    if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value == "无":
        return True
    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value == "无":
        return True
    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict):
        for k, v in zip(n.value.keys, n.value.values):
            if isinstance(k, ast.Constant) and k.value in {"draft_action", "action"} and isinstance(v, ast.Constant) and v.value == "无":
                return True
    return False

def body_has_raise(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, (ast.Raise, ast.Assert)):
            return True
    return False

def body_has_log(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Call):
            f = n.func
            names = []
            if isinstance(f, ast.Name):
                names.append(f.id)
            elif isinstance(f, ast.Attribute):
                names.append(f.attr)
                if isinstance(f.value, ast.Name):
                    names.append(f.value.id)
            joined = ".".join(names).lower()
            if any(x in joined for x in ("log", "tlog", "logger", "warning", "error", "exception", "debug", "info")):
                return True
    return False

def fn_name(stack):
    for n in reversed(stack):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return n.name
    return "<module>"

rows = []
for path in TARGETS:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except Exception as e:
        rows.append({"file": str(path.relative_to(ROOT)), "error": str(e)})
        continue
    stack = []
    class V(ast.NodeVisitor):
        def generic_visit(self, node):
            stack.append(node)
            super().generic_visit(node)
            stack.pop()
        def visit_ExceptHandler(self, node: ast.ExceptHandler):
            stack.append(node)
            body = node.body or []
            wash_kinds = []
            if any(isinstance(s, ast.Pass) for s in body):
                wash_kinds.append("pass")
            if any(returns_empty(s) for s in body):
                wash_kinds.append("return_empty")
            if any(assigns_empty(s) for s in body):
                wash_kinds.append("assign_empty")
            if any(looks_like_intent_none(s) for s in body):
                wash_kinds.append("intent_wu")
            # continue after catch without raise (whole-handler wash)
            has_raise = body_has_raise(body)
            has_log = body_has_log(body)
            # also detect return of non-empty "success-shaped" after catch of ValueError/Exception
            returns_any = [s for s in body if isinstance(s, ast.Return)]
            types = []
            if node.type is None:
                types = ["bare"]
            elif isinstance(node.type, ast.Name):
                types = [node.type.id]
            elif isinstance(node.type, ast.Tuple):
                types = [e.id if isinstance(e, ast.Name) else ast.dump(e) for e in node.type.elts]
            else:
                types = [ast.dump(node.type)]
            rel = str(path.relative_to(ROOT))
            rows.append({
                "file": rel,
                "line": node.lineno,
                "fn": fn_name(stack[:-1]),
                "exc_types": types,
                "wash_kinds": wash_kinds,
                "has_raise": has_raise,
                "has_log": has_log,
                "returns_count": len(returns_any),
                "body_preview": ast.get_source_segment(src, body[0])[:80] if body else "",
            })
            # continue walk into body
            for child in body:
                self.visit(child)
            stack.pop()
            # don't double via generic
            return
    V().visit(tree)

# classify candidates: wash without re-raise
candidates = []
for r in rows:
    if r.get("error"):
        continue
    wash = r["wash_kinds"]
    if wash and not r["has_raise"]:
        candidates.append(r)
    elif (not r["has_raise"]) and r["returns_count"] and not wash:
        # return something after catch — potential wash-to-normal
        r2 = dict(r)
        r2["wash_kinds"] = ["return_after_catch"]
        candidates.append(r2)

out = {
    "except_total": len([r for r in rows if "error" not in r]),
    "wash_candidate_count": len(candidates),
    "all_except": rows,
    "wash_candidates": candidates,
}
out_path = Path("/tmp/ming1902-f1f4-rescand/f1_except_scan.json")
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"except_total={out['except_total']} wash_candidates={out['wash_candidate_count']}")
print(f"wrote {out_path}")
# print wash candidates compact
for c in candidates:
    print(f"{c['file']}:{c['line']}\t{c['fn']}\t{c['exc_types']}\twash={c['wash_kinds']}\tlog={c['has_log']}\t{c['body_preview']!r}")
