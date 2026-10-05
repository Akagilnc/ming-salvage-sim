"""#1900 J6 FULL enum: all Assert + unittest assert* + stub/mock/helper/wait + full TS asserts."""
from __future__ import annotations
import ast, json, re, subprocess, pathlib
from collections import Counter
root = pathlib.Path('.').resolve()
out_dir = root / 'evidence/1900-j20-j19-j6-fixer-bbd34c025-rescan'
files = subprocess.check_output(['git','ls-files','-z'], cwd=root).split(b'\0')
paths=[]; seen=set()
for b in files:
    if not b: continue
    s=b.decode()
    if s.startswith('evidence/') or '/__pycache__/' in s: continue
    keep=False
    if s.endswith('.py') and (s.startswith('tests/') or '/tests/' in s or s.endswith('_test.py') or '/test_' in s.split('/')[-1]):
        keep=True
    elif re.search(r'\.(test|spec)\.(ts|tsx)$', s) or '/__tests__/' in s:
        keep=True
    elif s.startswith('web/') and re.search(r'\.(test|spec)\.(ts|tsx)$', s):
        keep=True
    if keep and s not in seen:
        seen.add(s); paths.append(s)
ASSERT_FUNCS={
    'assertEqual','assertEquals','assertNotEqual','assertIn','assertNotIn',
    'assertTrue','assertFalse','assertIs','assertIsNot','assertIsNone','assertIsNotNone',
    'assertRegex','assertNotRegex','assertCountEqual','assertListEqual','assertDictEqual',
    'assertRaisesRegex','assertWarnsRegex','assertAlmostEqual','assertGreater','assertLess',
    'assertGreaterEqual','assertLessEqual','assertIsInstance','assertRaises','assertWarns',
}
MOCK_ATTRS={
    'assert_called','assert_called_once','assert_called_with','assert_called_once_with',
    'assert_any_call','assert_has_calls','assert_not_called','call_count','called',
    'mock_calls','method_calls',
}
TEXT_HINT=re.compile(
    r'(prompt|opening|night_said|answer|content|body|title|text|message|reply|memorial|'
    r'gazette|print|stdout|stderr|chunk|narrative|prose|utter|saying|draft|marker|leak|'
    r'承旨|遵旨|钦此|赴京|禁模板|后轮|LEAK|固定)', re.I
)
ORACLE_HINT=re.compile(r'(oracle|call_count|call_oracle|fixed_translate|direction_|power_band|_strictly_before)', re.I)
SUSPECT_INITIAL=re.compile(
    r'(closed\s*==\s*\[\]|spawned\s*==\s*\[\]|assert\s+not\s+spawned|len\(spawned\)\s*==\s*0|'
    r'wait_until\(.*attempt|_attempts|len\(night_said\)|unissued_draft|'
    r'call_count\s*==\s*0|assert_not_called)', re.I
)
class V(ast.NodeVisitor):
    def __init__(self, path):
        self.path=path; self.rows=[]; self.stack=[]
    def visit_FunctionDef(self,n):
        self.stack.append(n.name); self.generic_visit(n); self.stack.pop()
    visit_AsyncFunctionDef=visit_FunctionDef
    def _test(self):
        return next((x for x in reversed(self.stack) if x.startswith('test_')), self.stack[-1] if self.stack else '')
    def _add(self, node, tags, snippet):
        self.rows.append({'file':self.path,'line':getattr(node,'lineno',0),'test':self._test(),
                          'tags':sorted(set(tags)),'snippet':snippet[:200].replace('\n',' ')})
    def _const_tags(self, part, tags):
        if isinstance(part, ast.Constant):
            v=part.value
            if isinstance(v,str):
                tags.append('STR_LITERAL')
                if TEXT_HINT.search(v): tags.append('GEN_TEXT_HINT')
            elif isinstance(v,bool): tags.append('BOOL_LITERAL')
            elif isinstance(v,(int,float)): tags.append('NUM_LITERAL')
            elif v is None: tags.append('NONE_LITERAL')
        elif isinstance(part, ast.Name) and TEXT_HINT.search(part.id):
            tags.append('GEN_TEXT_NAME')
        elif isinstance(part, ast.Attribute) and TEXT_HINT.search(part.attr):
            tags.append('GEN_TEXT_ATTR')
        elif isinstance(part,(ast.List,ast.Tuple,ast.Set)) and not part.elts:
            tags.append('EMPTY_COLLECTION')
        elif isinstance(part, ast.Subscript):
            tags.append('INDEX_ACCESS')
    def visit_Assert(self,n):
        tags=['ASSERT']
        for sub in ast.walk(n.test):
            if isinstance(sub, ast.Compare):
                for op in sub.ops:
                    if isinstance(op,(ast.Eq,ast.NotEq)): tags.append('ASSERT_EQ')
                    elif isinstance(op,(ast.In,ast.NotIn)): tags.append('ASSERT_IN')
                    elif isinstance(op,(ast.Lt,ast.LtE,ast.Gt,ast.GtE)): tags.append('ASSERT_ORDER')
                    elif isinstance(op,(ast.Is,ast.IsNot)): tags.append('ASSERT_IS')
                for part in [sub.left, *sub.comparators]:
                    self._const_tags(part, tags)
            if isinstance(sub, ast.UnaryOp) and isinstance(sub.op, ast.Not):
                tags.append('ASSERT_NOT')
            if isinstance(sub, ast.Call):
                fn=sub.func; name=''
                if isinstance(fn, ast.Name): name=fn.id
                elif isinstance(fn, ast.Attribute): name=fn.attr
                if name in ('match','search','fullmatch','findall') or name.startswith('assertRegex'):
                    tags.append('REGEX')
                if name in MOCK_ATTRS or name.startswith('assert_called'):
                    tags.append('MOCK_CALL')
                if name=='len': tags.append('LEN_CALL')
        try: sn=ast.unparse(n)
        except Exception: sn=ast.dump(n.test)[:120]
        if SUSPECT_INITIAL.search(sn): tags.append('SUSPECT_INITIAL')
        self._add(n, tags, sn)
        self.generic_visit(n)
    def visit_Call(self,n):
        fn=n.func; name=''
        if isinstance(fn, ast.Name): name=fn.id
        elif isinstance(fn, ast.Attribute): name=fn.attr
        tags=[]
        if name in ASSERT_FUNCS or (isinstance(name,str) and name.startswith('assert') and name!='assert'):
            tags.append('UNITTEST_ASSERT')
            if name in MOCK_ATTRS or name.startswith('assert_called'):
                tags.append('MOCK_CALL')
            for a in list(n.args)+[kw.value for kw in n.keywords]:
                self._const_tags(a, tags)
        if name in MOCK_ATTRS or (isinstance(name,str) and name.startswith('assert_called')):
            tags.append('MOCK_CALL')
        if name=='wait_until':
            tags.append('WAIT_UNTIL')
            try: sn=ast.unparse(n)
            except Exception: sn=name
            if 'attempt' in sn.lower() or 'len(' in sn: tags.append('INITIAL_OR_ATTEMPT')
            if SUSPECT_INITIAL.search(sn): tags.append('SUSPECT_INITIAL')
            self._add(n, tags, sn); self.generic_visit(n); return
        if name=='raises' or (isinstance(fn,ast.Attribute) and fn.attr=='raises'):
            for kw in n.keywords:
                if kw.arg=='match':
                    tags.append('RAISES_MATCH')
                    try: sn=ast.unparse(n)
                    except Exception: sn='raises(match=)'
                    self._add(n, tags, sn)
        if ORACLE_HINT.search(name or ''):
            tags.append('ORACLE_HELPER')
            try: sn=ast.unparse(n)
            except Exception: sn=name
            self._add(n, tags+[name], sn)
        if tags and 'RAISES_MATCH' not in tags and 'ORACLE_HELPER' not in tags:
            try: sn=ast.unparse(n)
            except Exception: sn=name
            if SUSPECT_INITIAL.search(sn): tags.append('SUSPECT_INITIAL')
            self._add(n, tags, sn)
        if isinstance(fn, ast.Attribute) and fn.attr=='setattr':
            try: sn=ast.unparse(n)
            except Exception: sn='setattr'
            if any(x in sn for x in ('Thread','wait_until','translate','supply','run_','Fake','MagicMock','stub','oracle','helper')):
                self._add(n, ['BOUNDARY_STUB'], sn)
        if name and (name.startswith('_assert') or 'oracle' in name.lower() or name.endswith('_helper')):
            try: sn=ast.unparse(n)
            except Exception: sn=name
            self._add(n, ['HELPER_CALL', name], sn)
        self.generic_visit(n)
py_rows=[]; ts_hits=[]
for rel in paths:
    p=root/rel
    if rel.endswith('.py'):
        try: tree=ast.parse(p.read_text(encoding='utf-8'), filename=rel)
        except Exception as e:
            py_rows.append({'file':rel,'line':0,'test':'','tags':['PARSE_FAIL'],'snippet':str(e)[:120]}); continue
        v=V(rel); v.visit(tree); py_rows.extend(v.rows)
    else:
        text=p.read_text(encoding='utf-8', errors='replace')
        for i,line in enumerate(text.splitlines(),1):
            tags=[]; stripped=line.strip()
            if re.search(r'\b(expect\(|assert\()', stripped): tags.append('TS_ASSERT')
            if re.search(r'\.(toHaveBeenCalled(?:With|Times|Once)?|not\.toHaveBeenCalled)\b', stripped): tags.append('MOCK_CALL')
            if re.search(r'\b(vi\.spyOn|jest\.spyOn|vi\.fn|jest\.fn|mockImplementation|mockReturnValue|mockResolvedValue)\b', stripped): tags.append('MOCK_STUB')
            if re.search(r'\.(toContain|toMatch|toEqual|toBe|toStrictEqual|toBeTruthy|toBeFalsy|toBeNull|toBeUndefined|toHaveLength|toBeGreaterThan|toBeLessThan)\b', stripped):
                tags.append('TS_MATCHER')
                if re.search(r'[\'\"][^\'\"]{2,}[\'\"]', stripped): tags.append('STR_ASSERT')
                if re.search(r'\b(toBe\((?:true|false|null|undefined|\d+)|toHaveLength\(\d+|toBeNull|toBeUndefined|toBeTruthy|toBeFalsy)', stripped): tags.append('SCALAR_ASSERT')
            if tags:
                ts_hits.append({'file':rel,'line':i,'test':'','tags':sorted(set(tags)),'snippet':stripped[:200]})
raw={'python_files':len([p for p in paths if p.endswith('.py')]),'ts_files':len([p for p in paths if not p.endswith('.py')]),
     'python_candidates':len(py_rows),'ts_candidates':len(ts_hits),'paths_sample':paths[:20],'path_count':len(paths),
     'enum_mode':'FULL_NO_NUMERIC_DROP'}
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir/'j6-ast-summary.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
with (out_dir/'j6-ast-candidates.jsonl').open('w',encoding='utf-8') as f:
    for r in py_rows+ts_hits: f.write(json.dumps(r,ensure_ascii=False)+'\n')
print('paths',len(paths),'py',len(py_rows),'ts',len(ts_hits))
c=Counter()
for r in py_rows:
    for t in r['tags']: c[t]+=1
print('tag_hist',dict(c.most_common(25)))
print('SUSPECT_INITIAL',sum(1 for r in py_rows if 'SUSPECT_INITIAL' in r['tags']))
