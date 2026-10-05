"""One-shot CLEANUP-C1 closure audit: full member table + skip resolution.
stdlib ast + importlib only. No permanent repo scan framework.
Does NOT seed candidates from judgment word lists.
"""
from __future__ import annotations
import ast, json, sys, importlib, inspect, types, csv, re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path('.').resolve()
TESTS = ROOT / 'tests'
OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

PROD_PREFIXES = ('ming_sim', 'web_app')
PROD_ROOT_MODS = {'main', 'launcher', 'spike_settle_tick', 'web_app'}

# ---------- helpers ----------

def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        b = dotted(node.value)
        return f'{b}.{node.attr}' if b else None
    return None

def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None

def try_import(modname):
    try:
        return importlib.import_module(modname), None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'

BUILTIN_OK = set(dir(object)) | set(dir(type)) | {
    '__dict__', '__module__', '__doc__', '__weakref__', '__slots__', '__annotations__'
}

def has_attr_runtime(obj, attr):
    if attr is None:
        return None, 'attr_not_const'
    try:
        if hasattr(obj, attr):
            return True, 'hasattr'
    except Exception as e:
        return None, f'hasattr_raised:{type(e).__name__}:{e}'
    if inspect.isclass(obj):
        for c in obj.__mro__:
            if attr in getattr(c, '__dict__', {}):
                return True, f'mro:{c.__name__}'
        if attr in BUILTIN_OK:
            return True, 'builtin_type_attr'
    return False, 'absent'

def resolve_object(hint: str):
    if not hint:
        return None, None, 'empty hint'
    parts = hint.split('.')
    last_err = None
    for i in range(len(parts), 0, -1):
        modname = '.'.join(parts[:i])
        mod, err = try_import(modname)
        if mod is not None:
            obj = mod
            for p in parts[i:]:
                if not hasattr(obj, p):
                    return None, modname, f'missing_intermediate:{p}'
                obj = getattr(obj, p)
            return obj, modname, None
        last_err = err
    return None, None, last_err or 'unimportable'

def is_prod_hint(hint: str) -> bool:
    if not hint:
        return False
    if hint.startswith(PROD_PREFIXES):
        return True
    return hint.split('.')[0] in PROD_ROOT_MODS

# ---------- fixture / scope inference from AST (no word-list seed) ----------

def collect_fixture_defs():
    """Map fixture name -> inferred production type hint from return/yield annotations or unpacking.
    Also map (file, func_param) via type comments when present.
    """
    fixtures = {}  # name -> {file, line, source_kind, inferred_hint, evidence}
    # Scan tests/** for @pytest.fixture defs
    for path in sorted(TESTS.rglob('*.py')):
        rel = str(path.relative_to(ROOT))
        try:
            src = path.read_text(encoding='utf-8')
            tree = ast.parse(src, filename=rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_fix = False
            for dec in node.decorator_list:
                d = dotted(dec) or ''
                if d.endswith('fixture') or (isinstance(dec, ast.Call) and (dotted(dec.func) or '').endswith('fixture')):
                    is_fix = True
                    break
            if not is_fix:
                continue
            # Infer from return annotation
            hint = None
            source_kind = None
            evidence = None
            if node.returns is not None:
                ann = dotted(node.returns) or (const_str(node.returns) if isinstance(node.returns, ast.Constant) else None)
                if ann:
                    hint = ann
                    source_kind = 'return_annotation'
                    evidence = f'{rel}:{node.lineno}'
            # Infer from yield/return of known constructors / imports in body
            if hint is None:
                # look for aliases in this file
                aliases = {}
                for n in ast.walk(tree):
                    if isinstance(n, ast.Import):
                        for a in n.names:
                            aliases[a.asname or a.name.split('.')[0]] = a.name
                    elif isinstance(n, ast.ImportFrom):
                        mod = n.module or ''
                        for a in n.names:
                            if a.name == '*':
                                continue
                            aliases[a.asname or a.name] = f'{mod}.{a.name}' if mod else a.name
                for n in ast.walk(node):
                    if isinstance(n, ast.Return) and n.value is not None:
                        # GameDB(...) / ClassName(...)
                        if isinstance(n.value, ast.Call):
                            c = dotted(n.value.func)
                            if c and c in aliases and is_prod_hint(aliases[c]):
                                hint = aliases[c]
                                source_kind = 'return_call_aliased'
                                evidence = f'{rel}:{n.lineno}'
                                break
                            if c and '.' in c:
                                base = c.split('.')[0]
                                if base in aliases and is_prod_hint(aliases[base]):
                                    hint = aliases[base] + '.' + '.'.join(c.split('.')[1:])
                                    source_kind = 'return_call_attr'
                                    evidence = f'{rel}:{n.lineno}'
                                    break
                        # tuple unpack game → (db, state, content)
                        if isinstance(n.value, (ast.Tuple, ast.List)):
                            # record as composite; handled per-element later
                            pass
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield) and n.value.value is not None:
                        yv = n.value.value
                        if isinstance(yv, ast.Call):
                            c = dotted(yv.func)
                            if c and c in aliases and is_prod_hint(aliases[c]):
                                hint = aliases[c]
                                source_kind = 'yield_call_aliased'
                                evidence = f'{rel}:{n.lineno}'
                                break
                        if isinstance(yv, (ast.Tuple, ast.List)):
                            # game fixture often yields (db, state, content)
                            el_hints = []
                            for el in yv.elts:
                                if isinstance(el, ast.Name):
                                    # look for assignment to that name earlier in fixture
                                    el_hints.append(el.id)
                            fixtures[node.name] = {
                                'file': rel, 'line': node.lineno,
                                'source_kind': 'yield_tuple_names',
                                'inferred_hint': None,
                                'tuple_names': el_hints,
                                'evidence': f'{rel}:{n.lineno}',
                            }
                            hint = '__TUPLE__'
                            break
            if node.name not in fixtures:
                fixtures[node.name] = {
                    'file': rel, 'line': node.lineno,
                    'source_kind': source_kind or 'fixture_def_untyped',
                    'inferred_hint': hint if hint != '__TUPLE__' else None,
                    'evidence': evidence or f'{rel}:{node.lineno}',
                }
    return fixtures

def infer_local_bindings(path: Path, tree: ast.AST, aliases: dict):
    """Per-function: param names that are fixtures; assignments from game unpack; etc."""
    out = {}  # func_name -> {local_name: {hint, source_kind, evidence}}
    # Also module-level aliases already known
    for node in tree.body if hasattr(tree, 'body') else []:
        pass

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            locals_map = {}
            # params = potential fixtures
            for arg in list(n.args.args) + list(n.args.kwonlyargs):
                locals_map[arg.arg] = {
                    'hint': None,
                    'source_kind': 'fixture_param',
                    'evidence': f'{path.name}:{n.lineno}:param:{arg.arg}',
                    'fixture_name': arg.arg,
                }
            # assignments: db, state, content = game
            for st in ast.walk(n):
                if isinstance(st, ast.Assign) and isinstance(st.value, ast.Name):
                    src = st.value.id
                    if isinstance(st.targets[0], ast.Tuple):
                        for i, el in enumerate(st.targets[0].elts):
                            if isinstance(el, ast.Name):
                                locals_map[el.id] = {
                                    'hint': None,
                                    'source_kind': 'unpack_from_name',
                                    'evidence': f'{path.name}:{st.lineno}:unpack[{i}]<-{src}',
                                    'unpack_source': src,
                                    'unpack_index': i,
                                }
                    elif isinstance(st.targets[0], ast.Name):
                        locals_map[st.targets[0].id] = {
                            'hint': None,
                            'source_kind': 'assign_from_name',
                            'evidence': f'{path.name}:{st.lineno}:<-{src}',
                            'assign_source': src,
                        }
                # db = game[0] style rare; skip
                # from X import Y as local already in aliases — if Name used as target of setattr that's alias
            out[n.name] = locals_map
            self.generic_visit(n)
        visit_AsyncFunctionDef = visit_FunctionDef
    V().visit(tree)
    return out

# Known structural unpack of `game` fixture from conftest — derived by reading conftest, not word list.
# We'll parse conftest game fixture body for the yield tuple element types.

def resolve_game_tuple_hints(fixtures, conftest_path: Path):
    """Read tests/conftest.py game fixture and map unpack indices to types via assignments."""
    try:
        src = conftest_path.read_text(encoding='utf-8')
        tree = ast.parse(src)
    except Exception:
        return {}
    aliases = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ''
            for a in n.names:
                if a.name != '*':
                    aliases[a.asname or a.name] = f'{mod}.{a.name}' if mod else a.name
        elif isinstance(n, ast.Import):
            for a in n.names:
                aliases[a.asname or a.name.split('.')[0]] = a.name
    index_hints = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != 'game':
            continue
        # Find names assigned from GameDB / load_content / etc before yield
        name_to_hint = {}
        for st in ast.walk(node):
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                nm = st.targets[0].id
                if isinstance(st.value, ast.Call):
                    c = dotted(st.value.func)
                    if c in aliases and is_prod_hint(aliases[c]):
                        name_to_hint[nm] = aliases[c]
                    elif c and c.startswith('GameDB'):
                        name_to_hint[nm] = aliases.get('GameDB', 'ming_sim.db.GameDB')
                    elif c == 'GameDB':
                        name_to_hint[nm] = aliases.get('GameDB', 'ming_sim.db.GameDB')
                elif isinstance(st.value, ast.Name) and st.value.id in name_to_hint:
                    name_to_hint[nm] = name_to_hint[st.value.id]
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
                nm = st.target.id
                if isinstance(st.value, ast.Call):
                    c = dotted(st.value.func)
                    if c in aliases:
                        name_to_hint[nm] = aliases[c]
        for st in ast.walk(node):
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Yield) and st.value.value is not None:
                yv = st.value.value
                if isinstance(yv, (ast.Tuple, ast.List)):
                    for i, el in enumerate(yv.elts):
                        if isinstance(el, ast.Name) and el.id in name_to_hint:
                            index_hints[i] = {
                                'hint': name_to_hint[el.id],
                                'name': el.id,
                                'evidence': f'tests/conftest.py:game:yield[{i}]={el.id}->{name_to_hint[el.id]}',
                            }
    return index_hints

# ---------- site collection ----------

sites = []
from_imports = []
test_files = sorted(TESTS.rglob('*.py'))
file_aliases = {}
file_locals = {}

for path in test_files:
    rel = str(path.relative_to(ROOT))
    try:
        src = path.read_text(encoding='utf-8')
        tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        print('SYNTAX', rel, e, file=sys.stderr)
        continue
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split('.')[0]] = ('mod', a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            for a in node.names:
                if a.name == '*':
                    continue
                local = a.asname or a.name
                aliases[local] = ('from', f'{mod}.{a.name}' if mod else a.name, mod, a.name)
                if is_prod_hint(mod) or (mod and mod.split('.')[0] in PROD_ROOT_MODS):
                    from_imports.append({
                        'file': rel, 'line': node.lineno, 'module': mod,
                        'name': a.name, 'local': local,
                    })
    file_aliases[rel] = aliases
    file_locals[rel] = infer_local_bindings(path, tree, aliases)

    parent_fn = []
    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            parent_fn.append(n.name); self.generic_visit(n); parent_fn.pop()
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_Call(self, node):
            fn = parent_fn[-1] if parent_fn else '<module>'
            d = dotted(node.func) or ''
            if d.endswith('setattr'):
                if len(node.args) >= 2:
                    t0, t1 = node.args[0], node.args[1]
                    attr = const_str(t1)
                    raising = True
                    for kw in node.keywords:
                        if kw.arg == 'raising' and isinstance(kw.value, ast.Constant):
                            raising = bool(kw.value.value)
                    # also setattr(target, name=..., value=...) form
                    if attr is None:
                        for kw in node.keywords:
                            if kw.arg == 'name':
                                attr = const_str(kw.value)
                    hint = None
                    hint_source = None
                    if isinstance(t0, ast.Constant) and isinstance(t0.value, str):
                        # monkeypatch.setattr("ming_sim.foo.bar", ...)
                        hint = t0.value
                        hint_source = 'string_target'
                        sites.append({
                            'kind': 'monkeypatch.setattr_string',
                            'file': rel, 'line': node.lineno, 'func': fn,
                            'target_expr': hint, 'hint': hint, 'hint_source': hint_source,
                            'attr': hint.rsplit('.', 1)[-1] if '.' in hint else hint,
                            'target_path': hint,
                            'raising': raising,
                            'raw': (ast.get_source_segment(src, node) or '')[:240],
                        })
                        self.generic_visit(node)
                        return
                    if isinstance(t0, ast.Name) and t0.id in aliases:
                        hint = aliases[t0.id][1]
                        hint_source = f'import_alias:{aliases[t0.id][0]}'
                    elif isinstance(t0, ast.Attribute):
                        dd = dotted(t0)
                        if isinstance(t0.value, ast.Name) and t0.value.id in aliases:
                            hint = f'{aliases[t0.value.id][1]}.{t0.attr}'
                            hint_source = 'attr_on_import_alias'
                        else:
                            hint = dd
                            hint_source = 'attr_expr_unresolved'
                    sites.append({
                        'kind': 'monkeypatch.setattr',
                        'file': rel, 'line': node.lineno, 'func': fn,
                        'target_expr': dotted(t0) or '',
                        'hint': hint, 'hint_source': hint_source,
                        'attr': attr, 'raising': raising,
                        'raw': (ast.get_source_segment(src, node) or '')[:240],
                    })
            if d.endswith('patch') and not d.endswith('patch.object'):
                if node.args:
                    s = const_str(node.args[0])
                    if s and is_prod_hint(s):
                        create = False
                        for kw in node.keywords:
                            if kw.arg == 'create' and isinstance(kw.value, ast.Constant):
                                create = bool(kw.value.value)
                        sites.append({
                            'kind': 'patch_string',
                            'file': rel, 'line': node.lineno, 'func': fn,
                            'target_expr': s, 'target_path': s, 'attr': None,
                            'hint': s, 'hint_source': 'patch_string_literal',
                            'create': create, 'raising': True,
                            'raw': (ast.get_source_segment(src, node) or '')[:240],
                        })
            if d.endswith('patch.object'):
                if len(node.args) >= 2:
                    attr = const_str(node.args[1])
                    t0 = node.args[0]
                    create = False; raising = True
                    for kw in node.keywords:
                        if kw.arg == 'create' and isinstance(kw.value, ast.Constant):
                            create = bool(kw.value.value)
                        if kw.arg == 'raising' and isinstance(kw.value, ast.Constant):
                            raising = bool(kw.value.value)
                    hint = None; hint_source = None
                    if isinstance(t0, ast.Name) and t0.id in aliases:
                        hint = aliases[t0.id][1]
                        hint_source = f'import_alias:{aliases[t0.id][0]}'
                    elif isinstance(t0, ast.Attribute):
                        if isinstance(t0.value, ast.Name) and t0.value.id in aliases:
                            hint = f'{aliases[t0.value.id][1]}.{t0.attr}'
                            hint_source = 'attr_on_import_alias'
                    sites.append({
                        'kind': 'patch.object',
                        'file': rel, 'line': node.lineno, 'func': fn,
                        'target_expr': dotted(t0) or '',
                        'hint': hint, 'hint_source': hint_source,
                        'attr': attr, 'create': create, 'raising': raising,
                        'raw': (ast.get_source_segment(src, node) or '')[:240],
                    })
            self.generic_visit(node)
        def visit_Attribute(self, node):
            if isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name):
                if node.value.id in aliases:
                    kind, *rest = aliases[node.value.id]
                    resolved = rest[0]
                    if is_prod_hint(resolved):
                        sites.append({
                            'kind': 'direct_attr_ref',
                            'file': rel, 'line': node.lineno,
                            'func': parent_fn[-1] if parent_fn else '<module>',
                            'target_expr': node.value.id,
                            'hint': resolved, 'hint_source': f'import_alias:{kind}',
                            'attr': node.attr, 'import_kind': kind,
                            'raw': (ast.get_source_segment(src, node) or '')[:240],
                        })
            self.generic_visit(node)
    V().visit(tree)

print(f'PHASE1 sites={len(sites)} from_imports={len(from_imports)} files={len(test_files)}', flush=True)

fixtures = collect_fixture_defs()
game_tuple = resolve_game_tuple_hints(fixtures, TESTS / 'conftest.py')
print(f'PHASE1b fixtures={len(fixtures)} game_tuple_indices={game_tuple}', flush=True)

# ---------- resolve each site ----------

def resolve_fixture_hint(rel, func, target_expr, fixtures, file_locals, game_tuple):
    """Return (hint, source_kind, evidence) for a local/fixture target."""
    if not target_expr or '.' in target_expr:
        # type(db) → resolve db first
        if target_expr.startswith('type(') and target_expr.endswith(')'):
            inner = target_expr[5:-1].strip()
            h, sk, ev = resolve_fixture_hint(rel, func, inner, fixtures, file_locals, game_tuple)
            if h:
                return h, f'type_of:{sk}', ev
        return None, 'unresolved_expr', None
    locals_map = file_locals.get(rel, {}).get(func, {})
    info = locals_map.get(target_expr)
    if info is None:
        # bare name might still be a fixture used without being in this func map if module-level
        if target_expr in fixtures:
            fx = fixtures[target_expr]
            return fx.get('inferred_hint'), f'fixture_registry:{fx.get("source_kind")}', fx.get('evidence')
        return None, 'no_local_binding', None
    # unpack from game
    if info.get('source_kind') == 'unpack_from_name' and info.get('unpack_source') == 'game':
        idx = info.get('unpack_index')
        if idx in game_tuple:
            gt = game_tuple[idx]
            return gt['hint'], 'game_unpack_conftest', gt['evidence']
    if info.get('source_kind') == 'fixture_param':
        fx_name = info.get('fixture_name')
        if fx_name == 'game':
            return 'tests.conftest.game_fixture_tuple', 'fixture_param_game_composite', info['evidence']
        fx = fixtures.get(fx_name)
        if fx and fx.get('inferred_hint'):
            return fx['inferred_hint'], f'fixture_param->{fx["source_kind"]}', fx.get('evidence')
        # special: game unpack not yet done — leave for second pass note
        if fx_name in fixtures:
            return None, f'fixture_param_untyped:{fx_name}', fixtures[fx_name].get('evidence')
        return None, f'fixture_param_unknown:{fx_name}', info['evidence']
    if info.get('source_kind') == 'assign_from_name':
        src = info.get('assign_source')
        return resolve_fixture_hint(rel, func, src, fixtures, file_locals, game_tuple)
    return None, info.get('source_kind') or 'local', info.get('evidence')

results = []
for s in sites:
    hint = s.get('hint')
    attr = s.get('attr')
    kind = s['kind']
    hint_source = s.get('hint_source')

    # string forms already have hint
    if kind == 'monkeypatch.setattr_string':
        path = s['target_path']
        parts = path.split('.')
        resolved = False
        for i in range(len(parts), 0, -1):
            modname = '.'.join(parts[:i])
            mod, err = try_import(modname)
            if mod is not None:
                obj = mod
                missing = None
                for p in parts[i:]:
                    ok, how = has_attr_runtime(obj, p)
                    if not ok:
                        missing = p
                        break
                    obj = getattr(obj, p)
                if missing:
                    results.append({**s, 'verdict': 'MISSING', 'detail': f'string path missing {missing}', 'modname': modname,
                                    'resolved_hint': path, 'resolved_source': 'string_target'})
                else:
                    results.append({**s, 'verdict': 'OK', 'detail': 'string path resolves', 'modname': modname,
                                    'resolved_hint': path, 'resolved_source': 'string_target'})
                resolved = True
                break
        if not resolved:
            results.append({**s, 'verdict': 'UNIMPORTABLE_MODULE', 'detail': err,
                            'resolved_hint': path, 'resolved_source': 'string_target'})
        continue

    if kind == 'patch_string':
        path = s['target_path']
        parts = path.split('.')
        for i in range(len(parts), 0, -1):
            modname = '.'.join(parts[:i])
            mod, err = try_import(modname)
            if mod is not None:
                obj = mod
                missing = None
                for p in parts[i:]:
                    ok, how = has_attr_runtime(obj, p)
                    if not ok:
                        missing = p
                        break
                    obj = getattr(obj, p)
                if missing:
                    verdict = 'MISSING_BUT_CREATE_TRUE' if s.get('create') else 'MISSING'
                    results.append({**s, 'verdict': verdict, 'detail': f'patch path missing {missing}', 'modname': modname,
                                    'resolved_hint': path, 'resolved_source': 'patch_string_literal'})
                else:
                    results.append({**s, 'verdict': 'OK', 'detail': 'path resolves', 'modname': modname,
                                    'resolved_hint': path, 'resolved_source': 'patch_string_literal'})
                break
        else:
            results.append({**s, 'verdict': 'UNIMPORTABLE_MODULE', 'detail': err,
                            'resolved_hint': path, 'resolved_source': 'patch_string_literal'})
        continue

    # Try import-alias hint first
    if not hint:
        # resolve via fixture/local scope
        rh, rsk, rev = resolve_fixture_hint(s['file'], s['func'], s.get('target_expr') or '', fixtures, file_locals, game_tuple)
        if rh and is_prod_hint(rh):
            hint = rh
            hint_source = rsk
            s = {**s, 'resolved_via': 'fixture_scope', 'scope_evidence': rev}
        elif rh and rh.startswith('tests.'):
            results.append({**s, 'verdict': 'skip_non_prod', 'detail': f'composite/non-prod hint {rh}',
                            'resolved_hint': rh, 'resolved_source': rsk, 'scope_evidence': rev})
            continue
        else:
            # still unresolved — record loudly with scope read evidence
            results.append({
                **s, 'verdict': 'skip_unresolved_target',
                'detail': f'scope_read:{rsk}',
                'resolved_hint': rh, 'resolved_source': rsk, 'scope_evidence': rev,
            })
            continue

    if not is_prod_hint(hint):
        results.append({**s, 'verdict': 'skip_non_prod', 'detail': hint,
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias'})
        continue

    if attr is None and kind in ('monkeypatch.setattr', 'patch.object'):
        results.append({**s, 'verdict': 'skip_dynamic_attr', 'detail': 'non-const attr name',
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias',
                        'modname': hint.split('.')[0]})
        continue

    obj, modname, err = resolve_object(hint)
    if obj is None:
        results.append({**s, 'verdict': 'MISSING_TARGET_OBJECT', 'detail': err, 'modname': modname,
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias'})
        continue

    ok, how = has_attr_runtime(obj, attr) if attr else (None, 'no attr')
    if attr is None:
        results.append({**s, 'verdict': 'skip_dynamic_attr', 'detail': 'non-const attr name', 'modname': modname,
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias'})
    elif ok:
        results.append({**s, 'verdict': 'OK', 'detail': how, 'modname': modname,
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias',
                        'obj_type': type(obj).__name__})
    else:
        verdict = 'MISSING'
        if s.get('raising') is False:
            verdict = 'MISSING_BUT_RAISING_FALSE'
        if s.get('create') is True:
            verdict = 'MISSING_BUT_CREATE_TRUE'
        results.append({**s, 'verdict': verdict, 'detail': how, 'modname': modname,
                        'resolved_hint': hint, 'resolved_source': hint_source or 'import_alias',
                        'obj_type': type(obj).__name__, 'obj_repr': repr(obj)[:160]})

# Second pass: try harder on unresolved — type(db) and common fixture class from conftest imports
# Build class map from conftest by reading assignments in fixture bodies more carefully
# For remaining unresolved monkeypatch.setattr on bare names, check if target is type(X)

still = [r for r in results if r['verdict'] == 'skip_unresolved_target']
print(f'PHASE2 unresolved_before_deep={len(still)}', flush=True)

# Deep resolve: for each unresolved, read the test function source and find what the name is
# Also handle type(db) patterns that were stored as target_expr

def deep_resolve_unresolved(results):
    new_results = []
    for r in results:
        if r['verdict'] != 'skip_unresolved_target':
            new_results.append(r)
            continue
        te = r.get('target_expr') or ''
        attr = r.get('attr')
        rel = r['file']
        func = r['func']
        # type(db) / type(x)
        m = re.fullmatch(r'type\((\w+)\)', te)
        inner = m.group(1) if m else None
        name = inner or te
        # game unpack
        rh, rsk, rev = resolve_fixture_hint(rel, func, name, fixtures, file_locals, game_tuple)
        if rh and is_prod_hint(rh):
            obj, modname, err = resolve_object(rh)
            if obj is not None:
                # if type(db), check on class
                check_obj = obj if not inner else (obj if inspect.isclass(obj) else type(obj))
                # if hint is class already, fine; if hint is module.Class and we have instance protocol,
                # hasattr on class works for methods
                if not inspect.isclass(check_obj) and inner:
                    check_obj = type(check_obj)
                ok, how = has_attr_runtime(check_obj, attr) if attr else (None, 'attr_not_const')
                if attr is None:
                    new_results.append({**r, 'verdict': 'skip_dynamic_attr', 'detail': 'non-const after deep',
                                        'resolved_hint': rh, 'resolved_source': rsk, 'scope_evidence': rev, 'modname': modname})
                elif ok:
                    new_results.append({**r, 'verdict': 'OK', 'detail': f'deep:{how}', 'resolved_hint': rh,
                                        'resolved_source': rsk, 'scope_evidence': rev, 'modname': modname,
                                        'obj_type': type(check_obj).__name__})
                else:
                    new_results.append({**r, 'verdict': 'MISSING', 'detail': f'deep:{how}', 'resolved_hint': rh,
                                        'resolved_source': rsk, 'scope_evidence': rev, 'modname': modname,
                                        'obj_type': type(check_obj).__name__})
                continue
        # fixture param typed via registry
        if name in fixtures and fixtures[name].get('inferred_hint') and is_prod_hint(fixtures[name]['inferred_hint']):
            rh = fixtures[name]['inferred_hint']
            obj, modname, err = resolve_object(rh)
            if obj is not None and attr:
                ok, how = has_attr_runtime(obj, attr)
                verdict = 'OK' if ok else 'MISSING'
                new_results.append({**r, 'verdict': verdict, 'detail': f'fixture_reg:{how}',
                                    'resolved_hint': rh, 'resolved_source': 'fixture_registry',
                                    'scope_evidence': fixtures[name].get('evidence'), 'modname': modname})
                continue
        # Read raw line for type(db) already handled; keep unresolved with loud evidence
        new_results.append(r)
    return new_results

results = deep_resolve_unresolved(results)

# from-import checks
fi_results = []
seen_fi = set()
for fi in from_imports:
    key = (fi['module'], fi['name'])
    if key in seen_fi:
        continue
    seen_fi.add(key)
    mod, err = try_import(fi['module'])
    if mod is None:
        fi_results.append({**fi, 'verdict': 'UNIMPORTABLE_MODULE', 'detail': err})
        continue
    ok, how = has_attr_runtime(mod, fi['name'])
    fi_results.append({**fi, 'verdict': 'OK' if ok else 'MISSING', 'detail': how})

# ---------- emit full tables ----------
verdict_counts = dict(Counter(r['verdict'] for r in results))
fi_counts = dict(Counter(r['verdict'] for r in fi_results))

# Full members JSON
members_path = OUT / 'all_sites_members.json'
members_path.write_text(json.dumps({
    'head': __import__('subprocess').check_output(['git','rev-parse','HEAD'], text=True).strip(),
    'scope': {
        'parsed_files': 'tests/**/*.py (helpers included; docs/raw excluded by being outside tests/)',
        'test_files': len(test_files),
        'kinds': ['monkeypatch.setattr', 'monkeypatch.setattr_string', 'patch_string', 'patch.object', 'direct_attr_ref'],
        'false_positive_exclusions_loud': [
            'HTTP client.patch / non-unittest.mock patch without ming_sim|web_app string — not collected',
            'raising=False / create=True missing kept as distinct verdicts, not auto-OK',
            'non-const attr names → skip_dynamic_attr (protocol sites; listed)',
            'non-prod hints → skip_non_prod (listed)',
            'OK uses runtime hasattr/MRO — not static ClassDef body membership alone',
        ],
    },
    'sites_total': len(sites),
    'results_total': len(results),
    'verdict_counts': verdict_counts,
    'from_import_counts': fi_counts,
    'game_tuple_index_hints': game_tuple,
    'fixtures_indexed': {k: v for k, v in fixtures.items()},
    'members': results,
    'from_imports': fi_results,
}, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

# TSV
tsv_path = OUT / 'all_sites_members.tsv'
fields = ['verdict', 'kind', 'file', 'line', 'func', 'target_expr', 'attr', 'resolved_hint', 'resolved_source',
          'hint_source', 'detail', 'modname', 'raising', 'scope_evidence', 'obj_type', 'raw']
with tsv_path.open('w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter='\t', extrasaction='ignore')
    w.writeheader()
    for r in sorted(results, key=lambda x: (x.get('verdict',''), x.get('file',''), x.get('line',0) or 0)):
        row = {k: ('' if r.get(k) is None else r.get(k)) for k in fields}
        if isinstance(row.get('raising'), bool):
            row['raising'] = str(row['raising'])
        # sanitize tabs/newlines in raw
        for k in row:
            if isinstance(row[k], str):
                row[k] = row[k].replace('\t', ' ').replace('\n', ' ')
        w.writerow(row)

# Bucket annexes
def dump_bucket(name, pred):
    rows = [r for r in results if pred(r)]
    (OUT / f'{name}.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    return rows

unresolved = dump_bucket('unresolved', lambda r: r['verdict'] == 'skip_unresolved_target')
nonprod = dump_bucket('nonprod', lambda r: r['verdict'] == 'skip_non_prod')
dynamic = dump_bucket('dynamic', lambda r: r['verdict'] == 'skip_dynamic_attr')
missing = dump_bucket('missing', lambda r: str(r['verdict']).startswith('MISSING'))

# Per-unresolved resolution card (item-by-item)
cards = []
for r in unresolved:
    cards.append({
        'file': r['file'], 'line': r['line'], 'func': r['func'],
        'target_expr': r.get('target_expr'), 'attr': r.get('attr'),
        'raw': r.get('raw'),
        'scope_detail': r.get('detail'),
        'scope_evidence': r.get('scope_evidence'),
        'resolved_hint': r.get('resolved_hint'),
        'resolved_source': r.get('resolved_source'),
        'disposition': 'KEEP_SCOPE_LOCAL' if not r.get('resolved_hint') else 'NEEDS_RUNTIME',
        'reason': 'Target is fixture/local without production import alias; not a deleted production symbol site until target object is production-typed. Scope read recorded; not guessed as db/cc.',
    })
(OUT / 'unresolved_item_cards.json').write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding='utf-8')

# nonprod cards
np_cards = []
for r in nonprod:
    np_cards.append({
        'file': r['file'], 'line': r['line'], 'func': r['func'],
        'hint': r.get('resolved_hint') or r.get('hint') or r.get('detail'),
        'attr': r.get('attr'), 'raw': r.get('raw'),
        'disposition': 'NONPROD',
        'reason': 'Resolved target module/object is outside production prefixes (ming_sim/web_app/main/launcher/spike_settle_tick).',
    })
(OUT / 'nonprod_item_cards.json').write_text(json.dumps(np_cards, indent=2, ensure_ascii=False), encoding='utf-8')

# dynamic cards — read source for protocol
dyn_cards = []
for r in dynamic:
    dyn_cards.append({
        'file': r['file'], 'line': r['line'], 'func': r['func'],
        'target_expr': r.get('target_expr'), 'resolved_hint': r.get('resolved_hint') or r.get('hint'),
        'raw': r.get('raw'),
        'disposition': 'DYNAMIC_PROTOCOL',
        'reason': 'Attribute name is non-constant (variable/field loop); active registration protocol site, not a fixed deleted-symbol patch.',
    })
(OUT / 'dynamic_item_cards.json').write_text(json.dumps(dyn_cards, indent=2, ensure_ascii=False), encoding='utf-8')

summary = {
    'sites_total': len(sites),
    'results_total': len(results),
    'verdict_counts': verdict_counts,
    'from_import_counts': fi_counts,
    'missing_count': len(missing),
    'unresolved_count': len(unresolved),
    'nonprod_count': len(nonprod),
    'dynamic_count': len(dynamic),
    'missing_sites': missing,
    'artifacts': {
        'all_sites_members.json': str(members_path),
        'all_sites_members.tsv': str(tsv_path),
        'unresolved.json': str(OUT / 'unresolved.json'),
        'nonprod.json': str(OUT / 'nonprod.json'),
        'dynamic.json': str(OUT / 'dynamic.json'),
        'missing.json': str(OUT / 'missing.json'),
    },
}
(OUT / 'runtime.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

print('=== VERDICT COUNTS ===')
for k, v in sorted(verdict_counts.items()):
    print(f'  {k}: {v}')
print('=== FROM-IMPORT ===')
for k, v in sorted(fi_counts.items()):
    print(f'  {k}: {v}')
print(f'MISSING={len(missing)} unresolved={len(unresolved)} nonprod={len(nonprod)} dynamic={len(dynamic)}')
print('MISSING detail:')
for r in missing:
    print(f"  {r['verdict']}\t{r['file']}:{r['line']}::{r['func']}\thint={r.get('resolved_hint') or r.get('hint')}\tattr={r.get('attr')}\t{r.get('detail')}")
print('DYNAMIC detail:')
for r in dynamic:
    print(f"  {r['file']}:{r['line']}::{r['func']}\thint={r.get('resolved_hint') or r.get('hint')}\traw={r.get('raw')}")
print('NONPROD detail:')
for r in nonprod:
    print(f"  {r['file']}:{r['line']}::{r['func']}\thint={r.get('resolved_hint') or r.get('hint') or r.get('detail')}\tattr={r.get('attr')}")
print(f'Wrote {members_path} and {tsv_path}')
