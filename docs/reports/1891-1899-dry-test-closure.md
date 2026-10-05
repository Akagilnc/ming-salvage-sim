# #1891/#1899 DRY-C1／D1 + TEST-C1／T1 闭包回执（docs-only forward）

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。
开工 BASE：`7ba04d2263793153383e5e2b95d9d58d54ac5456`。
代码交卷：`a64094fd5336344d1932cf283fea4c2a9f430b65`（DRY + 庭列24 + 初轮11 + 三案/stub）；
全仓 orphan 清退：`81560cb1b396b35339ca36693e7742bcb188e83b`（再删 23）。
**本轮：仅修本报告**——不改生产／测试代码；补真正可复跑全仓枚举、完整消费者依据、DRY 归一证明、测试命令史；收回夸大表述。

法源：末份 `1891m-judge-7ba04d226.json` payload[4]、`1899c-judge-7ba04d226.json` payload[3]、`1891-1899-countersign-7ba04d226.json`（原卷直读，本回执不自撰顾问／判词摘要冒称原话）。
Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。
历史临时根（仅日志指针，**复跑命令不依赖**）：初轮 `/tmp/1891-dry-test.e72Ys3`；orphan 轮 `/tmp/1891-dry-fix2.SD3paj`。

## 七变量前缀

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
BASE=7ba04d226
```

## 前次报告边界（诚实撤回夸大）

1. **消费者索引曾不完备**：只扫 `tree.body` 顶层 `ImportFrom` + 同文件 `Name(Load)`，**未**覆盖嵌套 `ImportFrom`、relative import、`import` 模块别名 + `Attribute`（`module.attr`）。因此不能把「索引零命中」写成「修前全仓绝对零引用」。
2. **DRY 曾过窄**：只找「同一 `Compare` 同时含 skip+issue」；**不能**据此声称「同形结算控制流全仓发现」。修前真相是 skip／issue **两分离分支**，需归一 session call 后 AST equal 才能证明可合并。
3. **死链**：BASE `tests/test_highlight_judge_544.py::_drain` 函数体内嵌套
   `from tests.test_audience_background import _wait_for_pending_writes_to_drain` 并调用——这是 `_wait_for_pending_writes_to_drain` 的**真实修前消费者**；该消费者自身（`_drain`）同批删除，故 HEAD **无存活外泄消费**。不得再说「修前完全零引用」。
4. **慢扫中止**（transcript `66d9afd1-…`）：曾 kill 过慢 O(名×全仓节点) 扫描；改索引式。本轮命令自包含 inline，读 `git show $BASE:path` + HEAD 工作树，不依赖 `/tmp` 种子脚本。

## 独立核对（主助手 + 只读 advisor）

| 角色 | 结论 | 性质 |
| --- | --- | --- |
| 主助手 | 62/62 BASE 顶层存在、HEAD 顶层消失；HEAD 对 62 个 `(file,name)` 存活消费者命中 **0**；无真实存活消费者误删 | 施工自核 |
| 只读 advisor（explore） | **PASS**（同口径） | **施工顾问非正式意见，非法庭审** |

advisor 原话完整文本若需核对，请读宿主原卷／该席位 transcript；**本回执不自撰摘要冒称原话**。仅记录其 VERDICT=PASS 与「非正式／非法庭审」边界。

**删除算术（顶层定义）**：62 = 59 私有（庭列 24 + 初轮 11 + orphan 23 + stub `_stub_game`）+ 3 退役公有案。
**判据范围**：模块 `tree.body` 顶层 `FunctionDef|AsyncFunctionDef|ClassDef`。**不主张**递归砍光嵌套私有函数／方法；嵌套仅额外扫描并语义区分。

## 可复跑：BASE×HEAD 全层消费者枚举（自包含）

下列命令一次输出：双 AST 解析、62 成员存活命中、同名他文件顶层定义区分、嵌套私有候选语义标签、顶层测试私有 orphan 复扫、DRY 归一 + 协议面 Compare／结算调用。

```bash
$PY - <<'PY'
import ast, copy, subprocess
from pathlib import Path
from collections import defaultdict, Counter

BASE = '7ba04d226'
files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
base_py = [f for f in subprocess.check_output(
    ['git', 'ls-tree', '-r', '--name-only', BASE], text=True).splitlines() if f.endswith('.py')]

def mq(rel):
    return rel[:-3].replace('/', '.')

def parse_ref(ref, rel):
    try:
        src = subprocess.check_output(['git', 'show', f'{ref}:{rel}'], text=True)
    except subprocess.CalledProcessError:
        return None, None
    return src, ast.parse(src, filename=rel)

def is_fixture(d):
    if isinstance(d, ast.Name) and d.id == 'fixture':
        return True
    if isinstance(d, ast.Attribute) and d.attr == 'fixture':
        return True
    if isinstance(d, ast.Call):
        return is_fixture(d.func)
    return False

def resolve_from(cur_rel, module, level):
    if level and level > 0:
        pkg = list(Path(cur_rel).with_suffix('').parts[:-1])
        if level - 1 > len(pkg):
            return None
        base = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
        if module:
            base = base + module.split('.')
        return '/'.join(base) + '.py'
    if not module:
        return None
    return module.replace('.', '/') + '.py'

def index_tree(rel, tree, known):
    top, nested = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            fx = any(is_fixture(d) for d in getattr(node, 'decorator_list', []))
            top[node.name] = {'lineno': node.lineno, 'fixture': fx, 'kind': type(node).__name__}
            for sub in ast.walk(node):
                if sub is node:
                    continue
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith('_'):
                    nested.append((node.name, sub.name, sub.lineno, 'nested_fn'))
                if isinstance(sub, ast.ClassDef):
                    for item in sub.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith('_'):
                            nested.append((f'{node.name}.{sub.name}', item.name, item.lineno, 'nested_method'))
    import_from, mod_alias = [], {}
    name_loads, attr_loads, strings = defaultdict(list), defaultdict(list), defaultdict(list)
    top_set = set(tree.body)
    for node in ast.walk(tree):
        nested_imp = node not in top_set
        if isinstance(node, ast.ImportFrom):
            target = resolve_from(rel, node.module, node.level or 0)
            for alias in node.names:
                import_from.append((target, alias.name, node.lineno, alias.asname, nested_imp, node.module, node.level or 0))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod_alias[alias.asname or alias.name.split('.')[0]] = alias.name
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name_loads[node.id].append(node.lineno)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            base = node.value.id if isinstance(node.value, ast.Name) else None
            attr_loads[(base, node.attr)].append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings[node.value].append(node.lineno)
    return dict(top=top, nested=nested, import_from=import_from, mod_alias=mod_alias,
                name_loads=name_loads, attr_loads=attr_loads, strings=strings)

head_ast, base_ast = {}, {}
for rel in files:
    head_ast[rel] = ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)
for rel in base_py:
    _, t = parse_ref(BASE, rel)
    if t is not None:
        base_ast[rel] = t
print(f'HEAD_PY {len(files)} HEAD_AST {len(head_ast)} BASE_PY {len(base_py)} BASE_AST {len(base_ast)}')

mm_h = {mq(r): r for r in head_ast}
mm_b = {mq(r): r for r in base_ast}
ix_h = {r: index_tree(r, t, head_ast) for r, t in head_ast.items()}
ix_b = {r: index_tree(r, t, base_ast) for r, t in base_ast.items()}

def resolve_target(target, module, mm, known):
    if target in known:
        return target
    if module and module in mm:
        return mm[module]
    return None

def consumers(idx_map, mm, known, def_rel, def_name, excl_ln=None):
    hits = []
    ix = idx_map.get(def_rel)
    if ix:
        for ln in ix['name_loads'].get(def_name, []):
            if excl_ln is not None and ln == excl_ln:
                continue
            hits.append(('name_load', def_rel, ln, 'same_file'))
        for ln in ix['strings'].get(def_name, []):
            hits.append(('string', def_rel, ln, 'same_file'))
        for (base, attr), lns in ix['attr_loads'].items():
            if attr == def_name:
                for ln in lns:
                    hits.append(('attr', def_rel, ln, f'base={base}'))
    for rel, ix in idx_map.items():
        for target, name, ln, asname, nested, module, level in ix['import_from']:
            rt = resolve_target(target, module, mm, known)
            if name == def_name and (rt == def_rel or module == mq(def_rel)):
                kind = 'import_from_nested' if nested else 'import_from_toplevel'
                hits.append((kind, rel, ln, f'module={module} level={level} as={asname}'))
                bind = asname or name
                for ln2 in ix['name_loads'].get(bind, []):
                    hits.append(('imported_name_use', rel, ln2, bind))
        for (base, attr), lns in ix['attr_loads'].items():
            if attr != def_name or base is None:
                continue
            mod = ix['mod_alias'].get(base)
            if mod and (mm.get(mod) == def_rel or mod == mq(def_rel)):
                for ln in lns:
                    hits.append(('module_attr', rel, ln, f'{base}.{attr}'))
        if rel != def_rel:
            for ln in ix['strings'].get(def_name, []):
                hits.append(('string', rel, ln, 'cross_file'))
    return hits

def same_name_other(idx_map, def_rel, def_name):
    return [(r, ix['top'][def_name]['lineno']) for r, ix in idx_map.items()
            if def_name in ix['top'] and r != def_rel]

DELETED = [
    ('tests/test_web_court_visibility.py', 'test_vassal_prince_chat_rejected', 'public_retired'),
    ('tests/test_web_court_visibility.py', 'test_active_consort_chat_not_rejected', 'public_retired'),
    ('tests/test_qa_s2_copy_prompts_1356_1402.py', 'test_require_active_minister_uses_can_summon_reason', 'public_retired'),
    ('tests/test_web_court_visibility.py', '_stub_game', 'stub'),
    ('tests/test_audience_background.py', '_assert_next_accepted', 'court24'),
    ('tests/test_decree_dossiers_571.py', '_complete_session', 'court24'),
    ('tests/test_faction_brew_637.py', '_dual_brew_fn_factory', 'court24'),
    ('tests/test_faction_brew_637.py', '_relation_script', 'court24'),
    ('tests/test_fiscal_levy_effect.py', '_settled_land_by_region', 'court24'),
    ('tests/test_highlight_judge_544.py', '_restore_highlight_seams', 'court24'),
    ('tests/test_highlight_judge_544.py', '_drain', 'court24'),
    ('tests/test_month_loop_tracer_1468.py', '_install_canned_minister', 'court24'),
    ('tests/test_month_loop_tracer_1468.py', '_month_ord_of', 'court24'),
    ('tests/test_month_loop_tracer_1468.py', '_play_one_month', 'court24'),
    ('tests/test_month_loop_tracer_1468.py', '_setup_open_night_participant', 'court24'),
    ('tests/test_mutiny_actual_residence_659.py', '_pin_split_arrears', 'court24'),
    ('tests/test_mutiny_actual_residence_659.py', '_simulator_army_dicts', 'court24'),
    ('tests/test_pihong_dossier_1490.py', '_658_session', 'court24'),
    ('tests/test_pre_settle_transaction.py', '_drive_resolve_directives', 'court24'),
    ('tests/test_promulgation_seam_560.py', '_stage_policy_dossier', 'court24'),
    ('tests/test_rescript_draft_656.py', '_retire_existing_actors', 'court24'),
    ('tests/test_rescript_draft_656.py', '_valid_item', 'court24'),
    ('tests/test_rescript_draft_656.py', '_legal_item', 'court24'),
    ('tests/test_secret_order_monthly_progress_566.py', '_canned_monthly_settlement', 'court24'),
    ('tests/test_structured_decree_contract_1624.py', '_month_end_ctx', 'court24'),
    ('tests/test_structured_decree_contract_1624.py', '_army_none_legal_item', 'court24'),
    ('tests/test_structured_decree_contract_1624.py', '_executing_counts', 'court24'),
    ('tests/test_supervision_625.py', '_insert_staged', 'court24'),
    ('tests/test_audience_background.py', '_EmptyAgent', 'round11'),
    ('tests/test_chat_stream_failpaths_393.py', '_FailLeavingAgnoRunAgent', 'round11'),
    ('tests/test_cli_play_turn.py', '_noop_atomic', 'round11'),
    ('tests/test_web_chat_serialization_393.py', '_SecretOrderAgent', 'round11'),
    ('tests/test_audience_background.py', '_wait_for_pending_writes_to_drain', 'round11'),
    ('tests/test_month_loop_tracer_1468.py', '_CannedExtractor', 'round11'),
    ('tests/test_month_loop_tracer_1468.py', '_BoomExtractor', 'round11'),
    ('tests/test_month_loop_tracer_1468.py', '_CannedMinisterAgent', 'round11'),
    ('tests/test_month_loop_tracer_1468.py', '_resolve_decisions_via_stream', 'round11'),
    ('tests/test_month_loop_tracer_1468.py', '_choices_from_decisions', 'round11'),
    ('tests/test_structured_decree_contract_1624.py', '_army_single_bad_item', 'round11'),
    ('tests/test_adr0015_per_item_rejection.py', '_reports', 'orphan23'),
    ('tests/test_advance_paths_atomic.py', '_ledger_count', 'orphan23'),
    ('tests/test_audience_presence_500.py', '_session_double', 'orphan23'),
    ('tests/test_audience_presence_500.py', '_tool_registry', 'orphan23'),
    ('tests/test_court_break_player_lock_1727.py', '_CannedExtractor', 'orphan23'),
    ('tests/test_dossier_endorsements_612.py', '_Agent', 'orphan23'),
    ('tests/test_enter_settlement_period_1235.py', '_CannedExtractor', 'orphan23'),
    ('tests/test_enter_settlement_period_1235.py', '_BoomExtractor', 'orphan23'),
    ('tests/test_enter_settlement_period_1235.py', '_fake_settlement_llm', 'orphan23'),
    ('tests/test_enter_settlement_period_1235.py', '_terminal_sse', 'orphan23'),
    ('tests/test_faction_brew_637.py', '_faction_rows', 'orphan23'),
    ('tests/test_faction_brew_637.py', '_eligible_dossier', 'orphan23'),
    ('tests/test_mutiny_actual_residence_659.py', '_global_population', 'orphan23'),
    ('tests/test_mutiny_actual_residence_659.py', '_executing_dossier', 'orphan23'),
    ('tests/test_mutiny_third_strike_318.py', '_simulator_army_dicts', 'orphan23'),
    ('tests/test_mutiny_third_strike_318.py', '_find_simulator_army', 'orphan23'),
    ('tests/test_opening_gazette_delete_1356.py', '_session', 'orphan23'),
    ('tests/test_qa_b3_409_ux.py', '_ClosingNightDB', 'orphan23'),
    ('tests/test_qa_c2_phase_settlement_mask_1374.py', '_null_cm', 'orphan23'),
    ('tests/test_qa_h1_seed_data.py', '_bajiu_names', 'orphan23'),
    ('tests/test_refugee_loop_652.py', '_reflux', 'orphan23'),
    ('tests/test_relation_capture_633.py', '_module_of', 'orphan23'),
    ('tests/test_transit_countdown_668.py', '_assert_ledger_match', 'orphan23'),
]
print('DELETED_COUNT', len(DELETED), 'BY', dict(Counter(b for *_, b in DELETED)))

missing_base = still_head = alive = 0
print('=== 62_MEMBER_SURVIVING_CONSUMER_AUDIT ===')
for rel, name, bucket in DELETED:
    bdef = ix_b.get(rel, {}).get('top', {}).get(name)
    hdef = ix_h.get(rel, {}).get('top', {}).get(name)
    if not bdef:
        missing_base += 1
    if hdef:
        still_head += 1
    bln = bdef['lineno'] if bdef else None
    h_hits = consumers(ix_h, mm_h, head_ast, rel, name, None)
    b_hits = consumers(ix_b, mm_b, base_ast, rel, name, bln)
    sn = same_name_other(ix_h, rel, name)
    notable_b = [h for h in b_hits if h[0] in ('import_from_nested', 'module_attr', 'imported_name_use', 'import_from_toplevel')]
    status = 'SURVIVING' if h_hits else 'NONE'
    if h_hits:
        alive += 1
    print(f'{status}\t{bucket}\t{mq(rel)}.{name}\tHEAD_HITS={len(h_hits)}\tSAME_NAME_OTHER={sn}\tBASE_NOTABLE={notable_b}')
print(f'SUMMARY BASE_MISSING_TOP={missing_base} HEAD_STILL={still_head} HEAD_SURVIVING_NONEMPTY={alive}')

print('=== FOCUS_DRAIN_WAIT ===')
for rel, name in [
    ('tests/test_highlight_judge_544.py', '_drain'),
    ('tests/test_audience_background.py', '_wait_for_pending_writes_to_drain'),
]:
    bln = ix_b[rel]['top'][name]['lineno']
    print(name, 'BASE', consumers(ix_b, mm_b, base_ast, rel, name, bln))
    print(name, 'HEAD', consumers(ix_h, mm_h, head_ast, rel, name, None))

print('=== NESTED_PRIVATE_EXTRA (tests/; 语义区分, 非递归全砍) ===')
nested = []
for rel, ix in ix_h.items():
    if not rel.startswith('tests/'):
        continue
    for owner, name, ln, kind in ix['nested']:
        # 语义粗标：owner 为 test_* → 案内闭包; 否则协议/夹具替身候选
        tag = 'test_local_closure' if owner.startswith('test_') else 'helper_nested'
        if any(is_fixture(d) for d in []):
            tag = 'fixture'
        nested.append((rel, owner, name, ln, kind, tag))
print('NESTED_PRIV_COUNT', len(nested))
deleted_names = {n for _, n, _ in DELETED}
shared = [n for n in nested if n[2] in deleted_names]
print('NESTED_SHARE_DELETED_NAME', len(shared))
for n in shared:
    print('NESTED_SHARED', n)

print('=== HEAD_TOPLEVEL_TEST_PRIVATE_ORPHAN_FULLIDX ===')
orphans, keep_fix, keep_cons, dynamic = [], [], [], []
for rel, ix in ix_h.items():
    if not rel.startswith('tests/'):
        continue
    for name, meta in ix['top'].items():
        if not name.startswith('_'):
            continue
        if meta['fixture']:
            keep_fix.append(f'{mq(rel)}.{name}'); continue
        hits = consumers(ix_h, mm_h, head_ast, rel, name, meta['lineno'])
        real = [h for h in hits if h[0] != 'string']
        strs = [h for h in hits if h[0] == 'string']
        if real:
            keep_cons.append(f'{mq(rel)}.{name}'); continue
        if strs:
            dynamic.append(f'{mq(rel)}.{name}'); continue
        orphans.append((f'{mq(rel)}.{name}', rel, meta['lineno']))
print(f'ORPHAN {len(orphans)} KEEP_FIXTURE {len(keep_fix)} KEEP_CONSUMED {len(keep_cons)} DYNAMIC {len(dynamic)}')
for o in orphans:
    print('ORPHAN', o)

# DRY: BASE skip/issue body normalize session calls → AST equal; HEAD combined; protocol compares
rel_t = 'ming_sim/cli/terminal.py'
bt = base_ast[rel_t]; ht = head_ast[rel_t]

def find_play(tree):
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'play_turn')

class Norm(ast.NodeTransformer):
    def visit_Call(self, n):
        self.generic_visit(n)
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in ('advance_without_decree', 'resolve_turn'):
            n.func = ast.Name(id='SESSION_CALL', ctx=ast.Load())
        return n

def eq_branch(play, value):
    for n in ast.walk(play):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            if len(n.test.ops) == 1 and isinstance(n.test.ops[0], ast.Eq):
                if (isinstance(n.test.left, ast.Name) and n.test.left.id == 'action'
                        and isinstance(n.test.comparators[0], ast.Constant)
                        and n.test.comparators[0].value == value):
                    return n.body, n.lineno
    return None, None

pb = find_play(bt)
sb, sl = eq_branch(pb, 'skip'); ib, il = eq_branch(pb, 'issue')
ns = [Norm().visit(copy.deepcopy(x)) for x in sb]
ni = [Norm().visit(copy.deepcopy(x)) for x in ib]
for n in ns + ni:
    ast.fix_missing_locations(n)
raw_eq = ast.dump(ast.Module(body=sb, type_ignores=[]), include_attributes=False) == \
         ast.dump(ast.Module(body=ib, type_ignores=[]), include_attributes=False)
norm_eq = ast.dump(ast.Module(body=ns, type_ignores=[]), include_attributes=False) == \
          ast.dump(ast.Module(body=ni, type_ignores=[]), include_attributes=False)
print(f'DRY_BASE_SKIP_IF {sl} ISSUE_IF {il} RAW_EQUAL {raw_eq} NORMALIZED_SESSION_AST_EQUAL {norm_eq}')
ph = find_play(ht)
for n in ast.walk(ph):
    if isinstance(n, ast.If):
        d = ast.dump(n.test, include_attributes=False)
        if "Constant(value='skip')" in d and "Constant(value='issue')" in d:
            print('DRY_HEAD_COMBINED_IF', n.lineno)

def surface_of(rel):
    if rel.startswith('tests/'):
        return 'tests'
    if rel.startswith('ming_sim/cli/'):
        return 'cli'
    if rel == 'web_app.py' or rel.startswith('web/'):
        return 'api_web'
    if rel.startswith('ming_sim/'):
        return 'ming_sim'
    return 'other'

SETTLE = ('advance_without_decree', 'resolve_turn', '_cli_write_gate', '_print_pending_action_failures', 'end_turn')
OUT = ('report', 'awaiting', 'advanced', 'ended')
settle_rows, compares = [], []
for rel, tree in head_ast.items():
    surf = surface_of(rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in SETTLE:
                settle_rows.append((surf, rel, node.lineno, 'CALL', node.func.attr))
            elif isinstance(node.func, ast.Name) and node.func.id in SETTLE:
                settle_rows.append((surf, rel, node.lineno, 'CALL', node.func.id))
            elif isinstance(node.func, ast.Name) and node.func.id == 'getattr' and len(node.args) >= 2:
                a1 = node.args[1]
                if isinstance(a1, ast.Constant) and a1.value in OUT:
                    settle_rows.append((surf, rel, node.lineno, 'GETATTR', a1.value))
        if isinstance(node, ast.Compare):
            dump = ast.dump(node, include_attributes=False)
            hs = "Constant(value='skip')" in dump
            hi = "Constant(value='issue')" in dump
            if (hs or hi) and 'action' in dump:
                compares.append((surf, rel, node.lineno, hs, hi, dump[:160]))
print('SETTLE_BY_SURFACE', dict(Counter((a, c, d) for a, _, _, c, d in settle_rows)))
print('ACTION_COMPARES')
for c in compares:
    klass = 'COMBINED' if c[3] and c[4] else ('SKIP_ONLY' if c[3] else 'ISSUE_ONLY')
    print(f'  {klass}\t{c[0]}\t{c[1]}:{c[2]}')
print('DONE')
PY
```

### 本轮主助手实测摘要（命令完整输出见交卷时复跑粘贴）

| 指标 | 值 |
| --- | --- |
| HEAD／BASE AST | 351／351，错误 0 |
| DELETED_COUNT | 62（public_retired 3 + stub 1 + court24 24 + round11 11 + orphan23 23） |
| BASE 缺顶层／HEAD 仍定义 | 0／0 |
| HEAD 存活消费者非空 | **0** |
| `_wait_for_pending_writes_to_drain` BASE 显著命中 | `import_from_nested` @ `test_highlight_judge_544.py:199` + `imported_name_use:201`（消费者=`_drain`，已同删） |
| `_drain` BASE Name 调用 | 无（自身无外调用；嵌套 import 是它对 wait 的消费） |
| HEAD 顶层测试私有 orphan | 0；KEEP_FIXTURE 9；KEEP_CONSUMED 679；DYNAMIC 0 |
| 嵌套私有（tests/） | 344；与已删同名共享 1：`test_mechanical_tail_1845` 案内 `_reports`（**嵌套专属闭包**，≠ 已删顶层 `test_adr0015…._reports` 的存活消费） |
| DRY BASE | skip@649／issue@680；RAW_EQUAL False；**NORMALIZED_SESSION_AST_EQUAL True** |
| DRY HEAD | combined `action in (skip,issue)` @651 |

## 附表 A：62 删除成员 × HEAD 存活消费者（完整）

凡行 `HEAD_SURVIVING=0`。`SAME_NAME_OTHER`＝其它文件仍存活的**同名顶层定义**（≠ 对本删除成员的消费）。

### A1 退役公有三案 + stub（4）

| # | qualified | bucket | HEAD 存活 | SAME_NAME_OTHER | 备注 |
| --- | --- | --- | --- | --- | --- |
| 1 | `tests.test_web_court_visibility.test_vassal_prince_chat_rejected` | public_retired | 0 | — | 修前红：`AttributeError: web_app._require_active_minister` |
| 2 | `tests.test_web_court_visibility.test_active_consort_chat_not_rejected` | public_retired | 0 | — | 同上 |
| 3 | `tests.test_qa_s2_copy_prompts_1356_1402.test_require_active_minister_uses_can_summon_reason` | public_retired | 0 | — | 同上 |
| 4 | `tests.test_web_court_visibility._stub_game` | stub | 0 | — | BASE 仅被上列两可见性案消费；随案删 |

### A2 庭列 24

| # | qualified | HEAD 存活 | 备注 |
| --- | --- | --- | --- |
| 1 | `tests.test_audience_background._assert_next_accepted` | 0 | |
| 2 | `tests.test_decree_dossiers_571._complete_session` | 0 | |
| 3 | `tests.test_faction_brew_637._dual_brew_fn_factory` | 0 | BASE 内嵌 `_brew` 随父消失，不计入 62 |
| 4 | `tests.test_faction_brew_637._relation_script` | 0 | |
| 5 | `tests.test_fiscal_levy_effect._settled_land_by_region` | 0 | |
| 6 | `tests.test_highlight_judge_544._restore_highlight_seams` | 0 | |
| 7 | `tests.test_highlight_judge_544._drain` | 0 | 自身无 Name 调用；**体内嵌套 import wait**（见死链） |
| 8–11 | `tests.test_month_loop_tracer_1468._{_install_canned_minister,_month_ord_of,_play_one_month,_setup_open_night_participant}` | 0 | 级联消费 round11 若干，均在本批删除集内 |
| 12–13 | `tests.test_mutiny_actual_residence_659._{_pin_split_arrears,_simulator_army_dicts}` | 0 | 初扫曾误把 third_strike 同名 func_def 当消费者 |
| 14 | `tests.test_pihong_dossier_1490._658_session` | 0 | BASE 内嵌类型随父消失 |
| 15 | `tests.test_pre_settle_transaction._drive_resolve_directives` | 0 | |
| 16 | `tests.test_promulgation_seam_560._stage_policy_dossier` | 0 | |
| 17–19 | `tests.test_rescript_draft_656._{_retire_existing_actors,_valid_item,_legal_item}` | 0 | |
| 20 | `tests.test_secret_order_monthly_progress_566._canned_monthly_settlement` | 0 | |
| 21–23 | `tests.test_structured_decree_contract_1624._{_month_end_ctx,_army_none_legal_item,_executing_counts}` | 0 | |
| 24 | `tests.test_supervision_625._insert_staged` | 0 | docs 命中≠代码消费者 |

### A3 初轮 11（4 点名 + 7 级联）

| # | qualified | HEAD 存活 | BASE 显著／级联 |
| --- | --- | --- | --- |
| 1 | `…_EmptyAgent` | 0 | |
| 2 | `…_FailLeavingAgnoRunAgent` | 0 | |
| 3 | `…_noop_atomic` | 0 | |
| 4 | `…_SecretOrderAgent` | 0 | |
| 5 | `tests.test_audience_background._wait_for_pending_writes_to_drain` | 0 | **BASE**：`test_highlight_judge_544.py:199` 嵌套 ImportFrom + `:201` 调用（消费者=`_drain`，已删） |
| 6–10 | month_loop `_{_CannedExtractor,_BoomExtractor,_CannedMinisterAgent,_resolve_decisions_via_stream,_choices_from_decisions}` | 0 | 消费者 ⊆ 庭列已删集 |
| 11 | `…_army_single_bad_item` | 0 | ← `_army_none_legal_item`（已删） |

### A4 orphan 23（全仓顶层私有无消费者；含撤回 third_strike）

| # | qualified | HEAD 存活 | SAME_NAME_OTHER（他文件独立定义，≠ 消费者） |
| --- | --- | --- | --- |
| 1 | `tests.test_adr0015_per_item_rejection._reports` | 0 | —（HEAD 另有嵌套 `_reports`，见嵌套节） |
| 2 | `tests.test_advance_paths_atomic._ledger_count` | 0 | `test_pre_settle_transaction.py:25`；`test_state_reload.py:87` |
| 3–4 | `tests.test_audience_presence_500._{_session_double,_tool_registry}` | 0 | — |
| 5 | `tests.test_court_break_player_lock_1727._CannedExtractor` | 0 | —（同文件 `_StreamFarewellAgent` KEEP） |
| 6 | `tests.test_dossier_endorsements_612._Agent` | 0 | — |
| 7–10 | `tests.test_enter_settlement_period_1235._{_CannedExtractor,_BoomExtractor,_fake_settlement_llm,_terminal_sse}` | 0 | `_fake_settlement_llm` → `test_web_audience_night_498.py:81`（他定义） |
| 11–12 | `tests.test_faction_brew_637._{_faction_rows,_eligible_dossier}` | 0 | `_faction_rows`→`test_month_chain_1847.py:1543`；`_eligible_dossier`→`test_authority_ledger_611.py:18` |
| 13–14 | `tests.test_mutiny_actual_residence_659._{_global_population,_executing_dossier}` | 0 | 649／628／565 等他文件同名 |
| 15–16 | `tests.test_mutiny_third_strike_318._{_simulator_army_dicts,_find_simulator_army}` | 0 | **撤回**「outside diff → KEEP」；本类无消费者已删 |
| 17 | `tests.test_opening_gazette_delete_1356._session` | 0 | 多文件他定义 `_session` |
| 18–20 | `…_ClosingNightDB`／`_null_cm`／`_bajiu_names` | 0 | `_null_cm`→`test_month_open_snapshot_1234.py:62` |
| 21–23 | `…_reflux`／`_module_of`／`_assert_ledger_match` | 0 | — |

非 Python docs／审计 md 出现旧名 → **不是代码消费者**。

## 嵌套私有额外扫描（非递归全砍）

- **顶层支持物清退范围**：仅 `tree.body` 顶层；62 只计顶层。
- **额外扫描**：HEAD `tests/` 内嵌套 `_` 函数／方法共 **344**；与已删顶层同名共享 **1** 条：
  - `tests/test_mechanical_tail_1845.py` / `test_ending_summary_runs_in_mechanical_tail_after_advance` 内 `_reports` @395 → 标签 **test_local_closure**（案内专属），**不是**对已删 `test_adr0015…._reports` 的 ImportFrom／跨文件消费。
- BASE 随父删除的嵌套（举例，**不计入 62**）：`_dual_brew_fn_factory._brew`、`_EmptyAgent.run`、各类 `_CannedExtractor.run` 等。
- **禁止解读**：不得把「嵌套候选 344」写成「还应再删 344」；fixture／协议替身／实际调用／嵌套专属闭包须人工语义区分。

## 附表 B：本闭包相关 KEEP（候选，非全部 679 活 helpers）

全仓 `KEEP_CONSUMED≈679`／`KEEP_FIXTURE=9` 仅为索引基数；**本附件只列与本票相关的 KEEP 结论**。

| qualified | 保留依据（完整） |
| --- | --- |
| `tests.test_web_court_visibility.test_zongfan_cannot_be_summoned_via_can_summon` | 现役公有测试；pytest 发现执行；断言 `GameSession.can_summon` 负向（非 Name「消费者」模型，属协议案本身） |
| `tests.test_web_court_visibility._bare_session` | 同文件 Name 调用 @249／260／279 |
| `tests.test_web_court_visibility._materialized_prince` | 同文件 Name 调用 @100／138 |
| `tests.test_court_break_player_lock_1727._StreamFarewellAgent` | 同文件 Name 调用 @93（orphan 轮删的是同文件无消费者的 `_CannedExtractor`） |
| 生产 `session.can_summon`／场景入口 `SCENE_CHAT_SPEAKER` | 真实入口，非旧 `_require_active_minister` 专属测试 |
| 上表 SAME_NAME_OTHER 所列他文件同名顶层 | **各自文件的独立定义**；已区分，不得当「误删唯一实现」或「存活消费者」 |

~~`tests.test_mutiny_third_strike_318._simulator_army_dicts`~~：**撤回**前次「越权不删」；已删。

## DRY-C1／D1（证明合并；原形状脚本降格为事后核对）

### 修前（BASE `play_turn`）

- 分离分支：`action == "skip"` @649 与 `action == "issue"` @680，各 10 句。
- **原始** body AST **不相等**（仅 session 分派不同：`advance_without_decree` vs `resolve_turn`）。
- 将两处 Call 归一为占位 `SESSION_CALL` 后：`NORMALIZED_SESSION_AST_EQUAL True` → 证明可在单一分支内按 action 分派 session call。

### 修后（HEAD）

- `if action in ("skip", "issue")` @651；块内 `_cli_write_gate`／`advance_without_decree`／`resolve_turn`／`getattr(…, awaiting|advanced|ended)` 各 1。
- `@659` 的 `action == "skip"` 为三元分派，**不是**第二套结算控制流。

### 全仓协议面（各表面自有协议；不把 CLI combined 冒称唯一世界协议）

`action` 相关 Compare（HEAD）：

| 类 | 表面 | 位置 | 读法 |
| --- | --- | --- | --- |
| COMBINED | cli | `ming_sim/cli/terminal.py:651` | 本票合并后的结算控制流 |
| SKIP_ONLY | cli | `ming_sim/cli/terminal.py:659` | 同上块内 session 分派 |
| ISSUE_ONLY | tests | `tests/test_cli_play_turn.py:111` | 测试断言协议（期望 call 名），非平行实现 |
| SKIP_ONLY | tests | `tests/test_cli_play_turn.py:442` | 同上 |

结算业务调用／结果消费（HEAD 粗计数，按表面；API／CLI／测试**各有协议**，不得合并解释为「只剩一处」）：

| 表面 | 代表位点 | 说明 |
| --- | --- | --- |
| cli | `terminal.py` play_turn：`advance_without_decree`/`resolve_turn`/`_cli_write_gate`/outcome getattr | 本票 DRY 对象 |
| api_web | `web_app.py`：`advance_without_decree`@5529；`resolve_turn`@5651／5750；`end_turn` 多处 | HTTP／ASGI 自有入口，**非** CLI `action in (skip,issue)` 同形 |
| tests | 大量 `resolve_turn`／outcome ATTR | 契约断言，不是第二套 CLI 实现 |
| ming_sim | 引擎内 outcome／少量 `resolve_turn` | 领域核，非 CLI 菜单协议 |

**事后核对**（降格）：旧「找同一 Compare 含 skip+issue」脚本仅用于确认 HEAD combined 仍在；**证明合并**的权威依据是上列 BASE 归一 AST equal，不是该窄扫描。

## 根因与修法（累计；代码已在前两提交，本轮不改）

### DRY-C1／D1

根因：同一结算结果规则两份权威实现。
修法：`play_turn` 收拢为单一 `if action in ("skip", "issue")`；仅在 session call 处分派。不新增 helper／路由器／状态机制。

### TEST-C1／T1

根因：旧入口专属测试与无消费者私有支持物续命；曾误用 diff 名单收窄。
修法：先红取证删三案 + `_stub_game` + 庭列 24 + 初轮 11；再全仓顶层索引删 23。不恢复 `_require_active_minister`，不迁旧证明入夹具，不另造永久缺席自证测试。

## 旧范围排除错误撤回

`docs/reports/1891-inflight-test-readers.md` 保留全文；文首已有撤回注记（不得以 R2 豁免 `_require_active_minister` 专属测试）。另撤回「outside diff → KEEP `_simulator_army_dicts`」。

## 验证史（完整实际命令 + selectors；不抹历史）

环境共性：七变量 BIN=`/usr/bin/false`；`MING_SIM_USER_DATA_DIR` 与 `--basetemp` 为当轮 `$TMPROOT` 子目录；`-p no:cacheprovider`；解释器同上。未跑全量／真实宿主／网络模型。**不冒称 typecheck。**

### 1) 旧三案红取证（删前；TMPROOT=`/tmp/1891-dry-test.e72Ys3`）

```bash
TMPROOT=/tmp/1891-dry-test.e72Ys3
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  MING_SIM_USER_DATA_DIR="$TMPROOT/user" \
  $PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/pytest-red" -q --tb=short \
  tests/test_web_court_visibility.py::test_vassal_prince_chat_rejected \
  tests/test_web_court_visibility.py::test_active_consort_chat_not_rejected \
  tests/test_qa_s2_copy_prompts_1356_1402.py::test_require_active_minister_uses_can_summon_reason
```

结果：`3 failed in 0.82s`（墙钟 1.330s）；三案均为 `AttributeError: module 'web_app' has no attribute '_require_active_minister'`。日志：`$TMPROOT/red-three.log`。

### 2) 初轮大文件 collect-only（不作聚焦）

```bash
$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/pytest-collect" --collect-only -q \
  tests/test_pihong_dossier_1490.py \
  tests/test_decree_dossiers_571.py \
  tests/test_month_loop_tracer_1468.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_audience_background.py \
  tests/test_supervision_625.py \
  tests/test_rescript_draft_656.py \
  tests/test_highlight_judge_544.py
```

结果：`249 tests collected in 1.00s`（墙钟 1.502s）。日志：`$TMPROOT/logs/collect-large.log`。

### 3) 初轮聚焦绿（164）

```bash
$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/pytest-focus" -q --tb=short \
  tests/test_cli_play_turn.py \
  tests/test_web_court_visibility.py::test_zongfan_cannot_be_summoned_via_can_summon \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_faction_brew_637.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_promulgation_seam_560.py \
  tests/test_pre_settle_transaction.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_month_loop_tracer_1468.py \
  tests/test_audience_background.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_supervision_625.py \
  tests/test_rescript_draft_656.py \
  tests/test_highlight_judge_544.py \
  tests/test_chat_stream_failpaths_393.py
```

结果：`164 passed, 1 skipped, 1 warning in 4.51s`（墙钟 5.070s）。日志：`$TMPROOT/logs/focus-main.log`。

### 4) 已删选择器 collect（确认消失）

```bash
$PY -m pytest -p no:cacheprovider --collect-only -q \
  tests/test_web_court_visibility.py::test_vassal_prince_chat_rejected \
  tests/test_web_court_visibility.py::test_active_consort_chat_not_rejected \
  tests/test_qa_s2_copy_prompts_1356_1402.py::test_require_active_minister_uses_can_summon_reason
```

结果：`ERROR: not found`×3；`no tests collected in 0.58s`。日志：`$TMPROOT/logs/collect-deleted.log`。

### 5) Ruff F401／F821 失败史 → fix（初轮）

```bash
# ruff 0.11.2；UV_TOOL_DIR/UV_CACHE_DIR 指向当轮临时
ruff check --target-version py313 --select F401,F821 -- $(git diff --name-only -- '*.py')
# 先：10 F401（例：wait_until／json／STANCE_KEY／VIEW_FACTION_STANCE 等）
ruff check --target-version py313 --select F401,F821 --fix -- $(git diff --name-only -- '*.py')
# 后：All checks passed!
```

日志：`$TMPROOT/ruff/f401-f821.log` → `f401-f821-fix.log` → `f401-f821-after.log`。

### 6) orphan 轮聚焦（112）+ Ruff 再史（TMPROOT=`/tmp/1891-dry-fix2.SD3paj`）

collect-only：

```bash
$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/pytest-collect" --collect-only -q \
  tests/test_enter_settlement_period_1235.py \
  tests/test_relation_capture_633.py \
  tests/test_refugee_loop_652.py \
  tests/test_dossier_endorsements_612.py \
  tests/test_transit_countdown_668.py
```

结果：`67 tests collected in 0.87s`。

聚焦（最终绿选择器含最小相关 nodeid）：

```bash
$PY -m pytest -p no:cacheprovider --basetemp="$TMPROOT/pytest-focus2" -q \
  tests/test_web_court_visibility.py \
  tests/test_cli_play_turn.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_adr0015_per_item_rejection.py \
  tests/test_advance_paths_atomic.py \
  tests/test_audience_presence_500.py \
  tests/test_court_break_player_lock_1727.py \
  tests/test_faction_brew_637.py \
  tests/test_qa_b3_409_ux.py \
  tests/test_qa_c2_phase_settlement_mask_1374.py \
  tests/test_qa_h1_seed_data.py \
  tests/test_enter_settlement_period_1235.py::test_web_entry_captures_before_await_close \
  tests/test_relation_capture_633.py::test_hallucinated_and_emperor_endpoints_rejected_per_item_zero_edges \
  tests/test_refugee_loop_652.py::test_standalone_absorption_is_durable_to_second_connection \
  tests/test_dossier_endorsements_612.py::test_endorsement_forms_persist_restore_and_judge_without_roster_join \
  tests/test_transit_countdown_668.py::test_mid_countdown_save_reopen_continues_identically
```

结果：`112 passed in 2.29s`（墙钟 2.70s）。

Ruff 史（orphan 轮）：先 18 F401 → `--fix`；随后 `game` fixture import 再报 1×F401 → `# noqa: F401  # pytest fixture discovery` 后 `All checks passed!`。日志：`$TMPROOT/logs/ruff*.log`。

### 7) `git diff --check`：第一次红 → forward 绿

- **红**（orphan 施工中、相对 `7ba04d226`）：回执 md trailing whitespace + 至少 3 个触及测试 EOF 多余空行（含 `tests/test_highlight_judge_544.py`、`tests/test_month_loop_tracer_1468.py` 等；见 transcript `fd3354ef-…` 修净过程）。
- **绿**（提交 `81560cb1b`）：`git diff --check 7ba04d226`／`7ba04d226..HEAD` 无输出。

本 docs-only 轮交卷前再跑：`git diff --check 7ba04d226`（预期空）。

### 验证表（累计）

| 步骤 | 实际命令（见上节 selectors） | 输出 | 日志 |
| --- | --- | --- | --- |
| 旧三案红 | §1 三 nodeid | `3 failed in 0.82s` | `/tmp/1891-dry-test.e72Ys3/red-three.log` |
| 初轮 collect-large | §2 | `249 collected` | `…/logs/collect-large.log` |
| 初轮聚焦 | §3 | `164 passed, 1 skipped` | `…/logs/focus-main.log` |
| 已删 collect | §4 | not found×3 | `…/logs/collect-deleted.log` |
| 初轮 Ruff | §5 | 10 F401 → fix → All checks passed | `…/ruff/` |
| orphan collect | §6 | `67 collected` | `/tmp/1891-dry-fix2.SD3paj/logs/collect-large.log` |
| orphan 聚焦 | §6 | `112 passed` | `…/logs/focus-main.log` |
| orphan Ruff | §6 | 18 F401 → fix；game F401 → noqa → passed | `…/logs/ruff*.log` |
| diff --check | §7 | 先红后绿 @81560cb1b | transcript `fd3354ef-…` |
| 本轮枚举 | 上文 inline | HEAD 存活 0；DRY norm equal | 交卷时 stdout |

**不以符号缺席永久测试自证**——闭包依据为全层 AST 消费者表 + 旧三案红取证 + 现役 KEEP 案绿 + BASE 死链说明。

## Advisor 边界

advisor PASS＝施工顾问非正式意见，**非法庭审**／非法源。diff 名单／advisor 意见均不得替代类别授权与枚举证据。原话以宿主原卷为准。

## 提交约束声明

本轮仅 forward `ak-roles:` **docs** 提交；不 amend／stash／reset／checkout 覆盖／rebase／squash／push／PR；不改生产／测试代码；不改宪法／Soul／宿主配置／席位表；不造通用机制或永久自证测试。
