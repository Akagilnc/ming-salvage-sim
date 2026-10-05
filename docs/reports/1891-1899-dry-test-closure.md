# #1891/#1899 DRY-C1／D1 + TEST-C1／T1 闭包回执（forward 修正）

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。
前次交卷：`a64094fd5336344d1932cf283fea4c2a9f430b65`（相对 `7ba04d226`）。
本轮：独立 forward 修正——补全可复跑消费者索引、撤回「越权不删」误留、全仓同形无消费者支持物清退、`git diff --check` 卫生。
法源：末份 `1891m-judge-7ba04d226.json` payload[4]、`1899c-judge-7ba04d226.json` payload[3]、`1891-1899-countersign-7ba04d226.json`；本轮用户明示授权=**类别全仓机械枚举**，不是 diff 名单。
Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。
临时根：`/tmp/1891-dry-fix2.SD3paj`。

## 七变量前缀

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
TMPROOT=/tmp/1891-dry-fix2.SD3paj
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
```

## 先前慢扫中止（不隐去）

前次施工（transcript `66d9afd1-…`）曾后台跑全仓 AST 枚举（pid `54098`），约两分钟无产出后判定过慢并 `kill 54098`（回执文案：「AST 扫描过慢，改成索引式重跑」）。

- **被杀命令形态**：对 COURT24／diff 内每个私有名调用 `consumer_hits(name)`，函数体内对**每一个** tracked `.py` 再 `ast.walk` 比对 `Name`／`Attribute`／`ImportFrom` —— 近似 **O(候选名 × 全仓 AST 节点)**，且种子列表写死 COURT24。
- **改法**：一次遍历建 `name → uses` 索引；消费者判定按 **(file, name)** 限定——同文件 `Name(Load)`／跨文件 `ImportFrom` 才算；**其它文件同名 `func_def` 不算消费者**；`ast.parse` 错误直接抛。
- 本轮命令为自包含 inline，不依赖 `/tmp` 脚本、不依赖庭列种子。

## 可复跑：全仓 AST + 消费者索引（自包含）

```bash
$PY - <<'PY'
import ast, subprocess
from pathlib import Path
from collections import defaultdict

files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
trees = {rel: ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel) for rel in files}
print(f'TRACKED_PYTHON_PARSED {len(files)} AST_ERRORS 0')

def mq(rel):
    return rel[:-3].replace('/', '.')

mod_defs, fixtures, qual_to_file = {}, set(), {mq(r): r for r in files}

def is_fixture(d):
    if isinstance(d, ast.Name) and d.id == 'fixture':
        return True
    if isinstance(d, ast.Attribute) and d.attr == 'fixture':
        return True
    if isinstance(d, ast.Call):
        return is_fixture(d.func)
    return False

for rel, tree in trees.items():
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mod_defs[(rel, node.name)] = {
                'lineno': node.lineno,
                'qual': f'{mq(rel)}.{node.name}',
                'priv': rel.startswith('tests/') and node.name.startswith('_'),
            }
            for dec in getattr(node, 'decorator_list', []):
                if is_fixture(dec):
                    fixtures.add((rel, node.name))

local_loads, import_cons, string_hits = defaultdict(list), defaultdict(list), defaultdict(list)
for rel, tree in trees.items():
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            target = qual_to_file.get(node.module)
            if target is None:
                cand = node.module.replace('.', '/') + '.py'
                if cand in trees:
                    target = cand
            for alias in node.names:
                if target and (target, alias.name) in mod_defs:
                    import_cons[(target, alias.name)].append((rel, node.lineno))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            local_loads[(rel, node.id)].append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_hits[node.value].append((rel, node.lineno))

orphans, dynamic, keep_fix, keep_cons = [], [], [], []
for (rel, name), meta in sorted(mod_defs.items()):
    if not meta['priv']:
        continue
    loads = [ln for ln in local_loads.get((rel, name), []) if ln != meta['lineno']]
    imps = import_cons.get((rel, name), [])
    strs = string_hits.get(name, [])
    if (rel, name) in fixtures:
        keep_fix.append(meta['qual']); continue
    if loads or imps:
        keep_cons.append((meta['qual'], [('name', rel, ln) for ln in loads[:5]] + [('import', f, ln) for f, ln in imps[:5]]))
        continue
    if strs:
        dynamic.append((meta['qual'], rel, meta['lineno'], strs[:5])); continue
    orphans.append((meta['qual'], rel, name, meta['lineno']))

print(f'TEST_PRIVATE_ORPHAN {len(orphans)} KEEP_FIXTURE {len(keep_fix)} KEEP_CONSUMED {len(keep_cons)} DYNAMIC_MAYBE {len(dynamic)}')
for q, rel, name, ln in orphans:
    print(f'ORPHAN {q} @ {rel}:{ln}')
for q, rel, ln, strs in dynamic:
    print(f'DYNAMIC {q} @ {rel}:{ln} samples={strs}')
# 非 Python 文本命中（docs/md）不得当代码消费者
PY
```

修前本轮实测：`TRACKED_PYTHON_PARSED 351 AST_ERRORS 0`；`TEST_PRIVATE_ORPHAN 23`；`DYNAMIC_MAYBE 0`。
修后复扫：`ORPHAN_COUNT 0 DYNAMIC 0`。

## 可复跑：DRY 结算调用／result 收尾形状（非点名计数）

```bash
$PY - <<'PY'
import ast, subprocess
from pathlib import Path

files = subprocess.check_output(['git', 'ls-files', '*.py'], text=True).splitlines()
trees = {rel: ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel) for rel in files}
print(f'TRACKED_PYTHON_PARSED {len(files)} AST_ERRORS 0')
rel = 'ming_sim/cli/terminal.py'
play = next(n for n in trees[rel].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'play_turn')

def const_str(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None

events = []
for node in ast.walk(play):
    if isinstance(node, ast.Compare):
        dump = ast.dump(node, include_attributes=False)
        if 'action' in dump and ('skip' in dump or 'issue' in dump or 'back' in dump):
            events.append(('COMPARE', node.lineno, dump))
    if isinstance(node, ast.Call):
        fdump = ast.dump(node.func, include_attributes=False)
        if any(s in fdump for s in ('advance_without_decree', 'resolve_turn', '_cli_write_gate', '_print_pending_action_failures', 'end_turn')):
            events.append(('CALL', node.lineno, fdump))
        if isinstance(node.func, ast.Name) and node.func.id == 'getattr' and len(node.args) >= 2:
            attr = const_str(node.args[1])
            if attr in ('awaiting', 'advanced', 'ended', 'report'):
                events.append(('GETATTR', node.lineno, attr))
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in ('report', 'awaiting', 'advanced', 'ended'):
        events.append(('ATTR', node.lineno, node.attr))

for e in sorted(events, key=lambda x: x[1]):
    print(e)
src = Path(rel).read_text(encoding='utf-8')
print('HAS_COMBINED', 'if action in ("skip", "issue")' in src)
print('WRITE_GATE_CALLS', sum(1 for e in events if e[0] == 'CALL' and '_cli_write_gate' in e[2]))
print('ADVANCE_CALLS', sum(1 for e in events if e[0] == 'CALL' and 'advance_without_decree' in e[2]))
print('RESOLVE_CALLS', sum(1 for e in events if e[0] == 'CALL' and 'resolve_turn' in e[2]))
print('AWAITING_CHECKS', sum(1 for e in events if e[0] == 'GETATTR' and e[2] == 'awaiting'))
print('ADVANCED_CHECKS', sum(1 for e in events if e[0] == 'GETATTR' and e[2] == 'advanced'))
print('ENDED_CHECKS', sum(1 for e in events if e[0] == 'GETATTR' and e[2] == 'ended'))
print('CROSS_REPO_SKIP_ISSUE_ACTION_COMPARES')
for rel2, tree2 in trees.items():
    for node in ast.walk(tree2):
        if isinstance(node, ast.Compare):
            dump = ast.dump(node, include_attributes=False)
            if "Constant(value='skip')" in dump and "Constant(value='issue')" in dump and 'action' in dump:
                print(f'  {rel2}:{node.lineno}')
PY
```

实测：`HAS_COMBINED True`；`WRITE_GATE_CALLS=1` `ADVANCE_CALLS=1` `RESOLVE_CALLS=1`；`AWAITING_CHECKS=1` `ADVANCED_CHECKS=1` `ENDED_CHECKS=1`；全仓 `action in (skip,issue)` 比较仅 `ming_sim/cli/terminal.py:651`。

## 庭列 24（前次已删；完整 qualified）

| # | qualified 成员 | 消费者 | 处置 |
| --- | --- | --- | --- |
| 1 | `tests.test_audience_background._assert_next_accepted` | 无 | 删 @ a64094fd5 |
| 2 | `tests.test_decree_dossiers_571._complete_session` | 无 | 删 |
| 3 | `tests.test_faction_brew_637._dual_brew_fn_factory` | 无 | 删 |
| 4 | `tests.test_faction_brew_637._relation_script` | 无 | 删 |
| 5 | `tests.test_fiscal_levy_effect._settled_land_by_region` | 无 | 删 |
| 6 | `tests.test_highlight_judge_544._restore_highlight_seams` | 无 | 删 |
| 7 | `tests.test_highlight_judge_544._drain` | 无 | 删 |
| 8 | `tests.test_month_loop_tracer_1468._install_canned_minister` | 无 | 删 |
| 9 | `tests.test_month_loop_tracer_1468._month_ord_of` | 无 | 删 |
| 10 | `tests.test_month_loop_tracer_1468._play_one_month` | 无 | 删 |
| 11 | `tests.test_month_loop_tracer_1468._setup_open_night_participant` | 无 | 删 |
| 12 | `tests.test_mutiny_actual_residence_659._pin_split_arrears` | 无 | 删 |
| 13 | `tests.test_mutiny_actual_residence_659._simulator_army_dicts` | 无（初扫曾误把 `tests.test_mutiny_third_strike_318._simulator_army_dicts` 的 func_def 当消费者） | 删 |
| 14 | `tests.test_pihong_dossier_1490._658_session` | 无 | 删 |
| 15 | `tests.test_pre_settle_transaction._drive_resolve_directives` | 无 | 删 |
| 16 | `tests.test_promulgation_seam_560._stage_policy_dossier` | 无 | 删 |
| 17 | `tests.test_rescript_draft_656._retire_existing_actors` | 无 | 删 |
| 18 | `tests.test_rescript_draft_656._valid_item` | 无 | 删 |
| 19 | `tests.test_rescript_draft_656._legal_item` | 无 | 删 |
| 20 | `tests.test_secret_order_monthly_progress_566._canned_monthly_settlement` | 无 | 删 |
| 21 | `tests.test_structured_decree_contract_1624._month_end_ctx` | 无 | 删 |
| 22 | `tests.test_structured_decree_contract_1624._army_none_legal_item` | 无 | 删 |
| 23 | `tests.test_structured_decree_contract_1624._executing_counts` | 无 | 删 |
| 24 | `tests.test_supervision_625._insert_staged` | 无 | 删 |

非 Python：`_drain`／`_insert_staged` 仅历史 docs／审计 md → **不是代码消费者**。

## 初轮 11（4 点名 + 7 级联；补全文件名）

| # | qualified 成员 | 依据 | 处置 |
| --- | --- | --- | --- |
| 1 | `tests.test_audience_background._EmptyAgent` | 无 Name/Import 消费者 | 删 @ a64094fd5 |
| 2 | `tests.test_chat_stream_failpaths_393._FailLeavingAgnoRunAgent` | 同上 | 删 |
| 3 | `tests.test_cli_play_turn._noop_atomic` | 同上 | 删 |
| 4 | `tests.test_web_chat_serialization_393._SecretOrderAgent` | 同上 | 删 |
| 5 | `tests.test_audience_background._wait_for_pending_writes_to_drain` | 删上列后二次扫描仍无消费者 | 删 |
| 6 | `tests.test_month_loop_tracer_1468._CannedExtractor` | 同上 | 删 |
| 7 | `tests.test_month_loop_tracer_1468._BoomExtractor` | 同上 | 删 |
| 8 | `tests.test_month_loop_tracer_1468._CannedMinisterAgent` | 同上 | 删 |
| 9 | `tests.test_month_loop_tracer_1468._resolve_decisions_via_stream` | 同上 | 删 |
| 10 | `tests.test_month_loop_tracer_1468._choices_from_decisions` | 同上 | 删 |
| 11 | `tests.test_structured_decree_contract_1624._army_single_bad_item` | 同上 | 删 |

## 本轮全仓其余候选（修前 ORPHAN 23；人工复核后全删）

授权=类别「退役／无消费者测试支持物」，**不以** `10e64fbef..HEAD` diff 豁免。每条：同文件无 `Name(Load)`、无 `ImportFrom` 消费者、非 `@pytest.fixture`、无动态字符串命中；阅读后确认非现役负向契约／协议定义。

| # | qualified 成员 | KEEP/删依据 |
| --- | --- | --- |
| 1 | `tests.test_adr0015_per_item_rejection._reports` | 无消费者 → 删 |
| 2 | `tests.test_advance_paths_atomic._ledger_count` | 无消费者 → 删 |
| 3 | `tests.test_audience_presence_500._session_double` | 无消费者 → 删 |
| 4 | `tests.test_audience_presence_500._tool_registry` | 无消费者 → 删 |
| 5 | `tests.test_court_break_player_lock_1727._CannedExtractor` | 无消费者（`_StreamFarewellAgent` 仍有消费者 → KEEP）→ 删本类 |
| 6 | `tests.test_dossier_endorsements_612._Agent` | 无消费者 → 删 |
| 7 | `tests.test_enter_settlement_period_1235._CannedExtractor` | 无消费者 → 删 |
| 8 | `tests.test_enter_settlement_period_1235._BoomExtractor` | 无消费者 → 删 |
| 9 | `tests.test_enter_settlement_period_1235._fake_settlement_llm` | 无消费者 → 删 |
| 10 | `tests.test_enter_settlement_period_1235._terminal_sse` | 无消费者 → 删 |
| 11 | `tests.test_faction_brew_637._faction_rows` | 无消费者（庭列删依赖后级联）→ 删 |
| 12 | `tests.test_faction_brew_637._eligible_dossier` | 同上 → 删 |
| 13 | `tests.test_mutiny_actual_residence_659._global_population` | 无消费者 → 删 |
| 14 | `tests.test_mutiny_actual_residence_659._executing_dossier` | 无消费者 → 删 |
| 15 | `tests.test_mutiny_third_strike_318._simulator_army_dicts` | 无消费者；**撤回**前次回执「越权不删」→ 删 |
| 16 | `tests.test_mutiny_third_strike_318._find_simulator_army` | 无消费者 → 删 |
| 17 | `tests.test_opening_gazette_delete_1356._session` | 无消费者；现役案直接用 `game` fixture → 删 |
| 18 | `tests.test_qa_b3_409_ux._ClosingNightDB` | 无消费者（案用 inline night dict）→ 删 |
| 19 | `tests.test_qa_c2_phase_settlement_mask_1374._null_cm` | 无消费者 → 删 |
| 20 | `tests.test_qa_h1_seed_data._bajiu_names` | 无消费者 → 删 |
| 21 | `tests.test_refugee_loop_652._reflux` | 无消费者 → 删 |
| 22 | `tests.test_relation_capture_633._module_of` | 无消费者 → 删 |
| 23 | `tests.test_transit_countdown_668._assert_ledger_match` | 无消费者（现役用 `_assert_transit_frame_equal`）→ 删 |

修后级联复扫：`ORPHAN_COUNT 0`（无新增死定义）。

## KEEP（真实消费者／注册；含撤回留痕）

| qualified | 保留依据 |
| --- | --- |
| `tests.test_web_court_visibility.test_zongfan_cannot_be_summoned_via_can_summon` | 现役 `GameSession.can_summon` 负向契约 |
| `tests.test_web_court_visibility._bare_session` | 同文件现役案 Name 调用 |
| `tests.test_web_court_visibility._materialized_prince` | 同文件其它可见性案调用 |
| `tests.test_court_break_player_lock_1727._StreamFarewellAgent` | 同文件现役 stream 案消费 |
| 生产 `session.can_summon`／`SCENE_CHAT_SPEAKER` | 真实入口，非旧专属测试 |
| ~~`tests.test_mutiny_third_strike_318._simulator_army_dicts`~~ | **撤回**：前次以「不在 10e64..HEAD diff」保留不成立；advisor／diff 边界非法源。本轮已删 |

## 旧范围排除错误撤回

`docs/reports/1891-inflight-test-readers.md` 保留全文；文首已有撤回注记（不得以 R2 豁免 `_require_active_minister` 专属测试）。本轮另撤回「outside diff → KEEP `_simulator_army_dicts`」——类别授权下全仓同形无消费者支持物须清退。

## 根因与修法（累计）

### DRY-C1／D1

根因：同一结算结果规则两份权威实现。
修法：`play_turn` 收拢为单一 `if action in ("skip", "issue")`；仅在 `session.advance_without_decree()`／`session.resolve_turn()` 处分派。不新增 helper／路由器／状态机制。

### TEST-C1／T1

根因：旧入口专属测试与无消费者私有支持物续命；前次误用 diff 名单收窄全仓同类。
修法：先红取证删三案 + `_stub_game` + 庭列 24 + 初轮 11；本轮全仓索引再删 23；触及文件 Ruff F401（fixture 导入 `game` 以 noqa 保留发现副作用）。不恢复 `_require_active_minister`，不迁旧证明入夹具，不另造永久缺席自证测试。

## 验证

| 步骤 | 输出 | 墙钟／pytest | 日志 |
| --- | --- | --- | --- |
| 修前全仓 orphan 索引 | `ORPHAN_COUNT 23`；`DYNAMIC 0` | ~2.5s | `$TMPROOT/prescan-orphans.txt` |
| DRY 形状枚举 | `HAS_COMBINED True`；门／advance／resolve／awaiting／advanced／ended 各 1；跨仓 skip+issue 唯 terminal:651 | <1s | `$TMPROOT/dry-settlement-shape.txt` |
| 修后 orphan 复扫 | `ORPHAN_COUNT 0 DYNAMIC 0` | ~2.5s | `$TMPROOT/postscan-orphans.txt` |
| 大文件 collect-only | `67 tests collected in 0.87s` | real 1.33s | `$TMPROOT/logs/collect-large.log` |
| 聚焦（短文件全跑 + 巨大案最小相关） | `112 passed in 2.29s` | real 2.70s | `$TMPROOT/logs/focus-main.log` |
| Ruff F401／F821（触及 `.py`） | `--fix` 后 `All checks passed!`（`game` fixture import noqa） | <1s | `$TMPROOT/logs/ruff-*.log` |
| `git diff --check 7ba04d226`（工作树） | 空（无 trailing／EOF blank） | — | — |

**不冒称 typecheck。** DRY 非功能故障，未造变异证明。
**不以符号缺席永久测试自证**——闭包依据为索引式 AST 消费者表 + 旧三案红取证 + 现役 KEEP 案绿。

Advisor 只读方向非正式庭审；diff 名单／advisor 意见非法源。

## 提交约束声明

本轮仅 forward `ak-roles:` 提交；不 amend／stash／reset／checkout 覆盖／rebase／squash／push／PR；不改宪法／Soul／宿主配置／席位表。
