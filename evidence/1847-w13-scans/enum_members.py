#!/usr/bin/env python3
"""Replay scanner for #1847 w13 two classes. See members_classified.tsv for dispositions."""
from __future__ import annotations
import ast, re
from pathlib import Path
from collections import Counter
ROOT = Path(__file__).resolve().parents[2]
SKIP={'.git','.venv','node_modules','evidence','__pycache__'}

def py_files(roots):
    for r in roots:
        p = ROOT/r
        if not p.exists():
            continue
        for f in p.rglob('*.py'):
            if any(x in SKIP for x in f.parts):
                continue
            yield f

A_PATS = [
    (r'def fiscal_engine\\b|is_substrate_hub_fiscal_engine_enabled|_FISCAL_ENGINE_|_mark_substrate_hub_fiscal_engine', 'selector_or_marker'),
    (r'calc_province_fiscal\\s*\\(', 'legacy_exec_branch'),
    (r'__fiscal_engine', 'marker_rw'),
    (r'test legacy engine|_disable_army_pay_source_cutover|fiscal_engine\\(\\)\\s*==\\s*[\'\"]legacy|keeps_legacy_calc|test_legacy_fiscal', 'dedicated_legacy_test'),
]
members=[]
for f in py_files(['ming_sim','tests']):
    rel=str(f.relative_to(ROOT)); src=f.read_text(encoding='utf-8')
    for i,line in enumerate(src.splitlines(),1):
        for pat,kind in A_PATS:
            if re.search(pat, line):
                members.append(('旧兼容及退役残余闭包', kind, rel, i, line.strip()[:140])); break
print('A_hits', len([m for m in members if m[0].startswith('旧')]), Counter(m[1] for m in members))
for m in members:
    print('\t'.join(map(str,m)))
