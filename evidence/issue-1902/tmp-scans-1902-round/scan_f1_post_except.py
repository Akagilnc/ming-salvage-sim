#!/usr/bin/env python3
"""F1 supplement: ExceptHandler that does not re-raise, then function later returns success-shaped value.
Also flag draft_action '无' / empty dict returns near extract functions.
"""
from __future__ import annotations
import ast, json, sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
paths = list((ROOT/'ming_sim').rglob('*.py')) + [ROOT/'web_app.py']

def has_raise(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Raise):
            return True
    return False

def has_log(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Call):
            f=n.func
            names=[]
            if isinstance(f,ast.Name): names.append(f.id)
            elif isinstance(f,ast.Attribute): names.append(f.attr)
            if any(x in '.'.join(names).lower() for x in ('log','tlog','logger','warning','error','exception')):
                return True
    return False

rows=[]
post_continue=[]
intent_wu_returns=[]

for path in paths:
    src=path.read_text(encoding='utf-8')
    try: tree=ast.parse(src)
    except Exception: continue
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            # find try/except without raise in function
            for n in ast.walk(node):
                if isinstance(n, ast.Try):
                    for h in n.handlers:
                        if has_raise(h.body):
                            continue
                        # if try is not the last statement, or handler doesn't return, continuation possible
                        handler_returns = any(isinstance(s,ast.Return) for s in h.body)
                        if handler_returns:
                            continue
                        post_continue.append({
                            'file': str(path.relative_to(ROOT)),
                            'fn': node.name,
                            'except_line': h.lineno,
                            'has_log': has_log(h.body),
                            'body_preview': (ast.get_source_segment(src,h.body[0]) or '')[:100] if h.body else '',
                        })
            # intent 无 returns
            for n in ast.walk(node):
                if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
                    for k,v in zip(n.value.keys, n.value.values):
                        if isinstance(k,ast.Constant) and k.value=='draft_action' and isinstance(v,ast.Constant) and v.value=='无':
                            intent_wu_returns.append({
                                'file': str(path.relative_to(ROOT)),
                                'fn': node.name,
                                'line': n.lineno,
                                'preview': (ast.get_source_segment(src,n) or '')[:120],
                            })

# Focus extract-ish
focus_fn = ('extract','draft','affair','declaration','enrich','intent','secret','token','stalled','resubmit','catch_up')
focus_post=[r for r in post_continue if any(k in r['fn'].lower() or k in r['file'] for k in focus_fn) or 'cli_backend' in r['file'] or 'token_stats' in r['file']]
focus_wu=[r for r in intent_wu_returns if any(k in r['fn'].lower() for k in focus_fn) or 'cli_backend' in r['file']]

out={
    'post_except_continue_total': len(post_continue),
    'post_except_continue_focus': focus_post,
    'draft_action_wu_returns_focus': focus_wu,
    'post_except_continue_all': post_continue,
}
Path('/tmp/ming1902-f1f4-rescand/f1_post_except_scan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('post_except_continue', len(post_continue), 'focus', len(focus_post))
print('draft_action_wu focus', len(focus_wu))
for r in focus_post:
    print(f"POST {r['file']}:{r['except_line']} {r['fn']} log={r['has_log']} {r['body_preview']!r}")
print('--- wu ---')
for r in focus_wu:
    print(f"WU {r['file']}:{r['line']} {r['fn']} {r['preview']!r}")
