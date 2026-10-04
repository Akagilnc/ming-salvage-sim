# #1889 修内司回执：K1 / K2（末份判词）

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10813-895f-7b5f-a223-2e7879189496@fixer/fix-packet.md`  
判词附件（payloads **末份**为准）：`attachments/01-1889-judge-11da7ae74.json`  
施工前 HEAD：`11da7ae74`；分支：`ak-roles/1889-k1-k2-cleanup`  
本文件是施工证据，不另立 authority。

官方方向（删简 / 复用，不造轮）：
- [Vulture](https://github.com/jendrikseipp/vulture)：静态未引用只是线索；隐式调用会产生误报，不能不经消费者/职责复核一概删。
- [pytest Anatomy of a test](https://docs.pytest.org/en/stable/explanation/anatomy.html)：断言行为结果，不锁实现内部形状。

未结类（末份原文）：
1. **K1**「已退役入口的持久碎片与重复定义未随删简清退」— 成立。阻断的是具体残留职责与重复实现；尚待家族接线但仍对应票面职责的未调用接口，不因静态未引用一概删。
2. **K2**「测试仍锁定退役实现及内部退役形状」— 成立。清理无必要行为价值的测试成本；保留现役可见边界/拒收/失败负向；不以红灯要求补功能。

---

## 枚举命令（可重跑）

工作目录：仓库根。

### K1 谓词（覆盖类定义全文，不收窄到判词样本）

```sh
python3 - <<'PY'
"""K1: retired persistence fragments + duplicate defs + old-layout DROP."""
from pathlib import Path
import re, ast
from collections import defaultdict

ROOT = Path('.').resolve()
PROD = list(ROOT.joinpath('ming_sim').rglob('*.py'))
ALL_PY = PROD + list(ROOT.joinpath('tests').rglob('*.py'))
if (ROOT / 'web_app.py').exists():
    ALL_PY.append(ROOT / 'web_app.py')

RETIRED_ENTRY_NAMES = {
    'faction_report', 'building_detail', 'treasury_ledger', 'list_office_vacancies',
    'turn_army_summary', 'turn_region_summary', 'turn_building_summary',
    'turn_power_summary', 'turn_faction_summary', 'turn_character_summary',
    'turn_economy_summary',
}
SHAPE = re.compile(
    r'^(read_)?(faction_report|building_detail_?|treasury_ledger|list_office_vacancies|'
    r'turn_\w+_summary)$|^list_rollback_items_for_turn$|^delete_by_name$'
)

attr_refs = defaultdict(list)
for path in ALL_PY:
    rel = str(path.relative_to(ROOT))
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr_refs[node.attr].append((rel, getattr(node, 'lineno', 0)))

print('=== K1A store methods matching retired-entry / summary/detail/ledger/vacancies/dup ===')
for path in PROD:
    if 'entities' not in str(path) and not str(path).endswith('store.py'):
        continue
    try:
        src = path.read_text(encoding='utf-8'); tree = ast.parse(src)
    except SyntaxError:
        continue
    rel = str(path.relative_to(ROOT))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.name.endswith('Store'):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = item.name
            if not (SHAPE.match(name) or name in {
                'read_faction_report', 'read_building_detail', 'read_building_detail_',
                'read_treasury_ledger', 'read_list_office_vacancies',
                'read_turn_army_summary', 'read_turn_region_summary',
                'read_turn_power_summary', 'read_turn_economy_summary',
                'list_rollback_items_for_turn', 'delete_by_name',
                '_chat_turn_rollback_items',
            }):
                continue
            external = [r for r in attr_refs.get(name, []) if r[0] != rel]
            print(f'{name} @ {rel}:{item.lineno} {node.name} ext={len(external)} {external[:5]}')

print('=== K1B DROP TABLE / old-layout (no CREATE peer) ===')
create = set()
drop_re = re.compile(r'DROP\s+TABLE\s+IF\s+EXISTS\s+(\w+)', re.I)
create_re = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', re.I)
for path in PROD:
    text = path.read_text(encoding='utf-8', errors='replace')
    create.update(create_re.findall(text))
for path in PROD:
    text = path.read_text(encoding='utf-8', errors='replace')
    rel = str(path.relative_to(ROOT))
    for i, line in enumerate(text.splitlines(), 1):
        m = drop_re.search(line)
        if m:
            print(f'{rel}:{i}: DROP {m.group(1)}; CREATE_EXISTS={m.group(1) in create}')

print('=== K1C population unit dual definition ===')
for path in PROD:
    rel = str(path.relative_to(ROOT))
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if re.match(r'(POPULATION_UNIT_PERSONS|_POPULATION_UNIT_KEY)\s*=', line.strip()):
            print(f'{rel}:{i}: {line.strip()}')

print('=== K1D identical method bodies within same Store/GameDB class ===')
for path in list(Path('ming_sim/entities').rglob('store.py')) + [Path('ming_sim/db.py')]:
    src = path.read_text(); tree = ast.parse(src); rel = str(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bodies = {}
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            body = ast.get_source_segment(src, item)
            if not body:
                continue
            norm = re.sub(rf'def\s+{re.escape(item.name)}\s*\(', 'def __NAME__(', body, count=1)
            bodies.setdefault(norm, []).append((item.name, item.lineno))
        for names in bodies.values():
            if len(names) >= 2:
                print(f'{rel} {node.name}: {names}')
PY
```

### K2 谓词

```sh
python3 - <<'PY'
"""K2: tests locking retired impl hooks / internal retired shapes."""
from pathlib import Path
import re, ast

RETIRED_HOOKS = [
    'faction_report', 'building_detail', 'treasury_ledger', 'list_office_vacancies',
    'turn_army_summary', 'turn_region_summary', 'turn_power_summary', 'turn_economy_summary',
]
db_methods = set()
tree = ast.parse(Path('ming_sim/db.py').read_text())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'GameDB':
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                db_methods.add(item.name)
mp = re.compile(r'monkeypatch\.setattr\(\s*db\s*,\s*[\'\"](\w+)[\'\"]')
print('=== monkeypatch db.<missing GameDB method> ===')
for path in Path('tests').rglob('*.py'):
    for i, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
        for m in mp.finditer(line):
            if m.group(1) not in db_methods:
                print(f'{path}:{i}: missing={m.group(1)} :: {line.strip()[:120]}')
print('=== standalone-in-_meta retired-shape asserts ===')
for path in Path('tests').rglob('*.py'):
    for i, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
        if re.search(r'assert not any\(.*"standalone"|assert not any\(.*\'standalone\'', line):
            print(f'{path}:{i}: {line.strip()}')
print('=== test defs / calls named after retired turn_*_summary entry ===')
for path in Path('tests').rglob('*.py'):
    for i, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
        if re.search(r'def test_.*turn_(army|region|power|economy)_summary|turn_region_summary_claim', line):
            print(f'{path}:{i}: {line.strip()}')
        for h in RETIRED_HOOKS:
            if h in line and not line.lstrip().startswith(('#', '-', '*')):
                if 'monkeypatch' in line or 'setattr' in line or line.lstrip().startswith('def '):
                    print(f'{path}:{i}: hook={h} :: {line.strip()[:120]}')
PY
```

---

## K1 全员表与逐项去留

施工前枚举命中如下（判词点名仅为样本；谓词覆盖同形退役读口碎片、同体重复、旧布局 DROP、双真源常量）。

| 成员 | 位置 | 消费者/职责核 | 处置 | 理由 |
|---|---|---|---|---|
| `FactionStore.read_faction_report` | `faction/store.py:152` | GameDB `faction_report` 已删；全仓零调用 | **删** | 退役入口查询碎片 |
| `ArmyStore.read_turn_army_summary` | `army/store.py:148` | `turn_army_summary` 已删；零调用 | **删** | 同上 |
| `RegionStore.read_turn_region_summary` | `region/store.py:158` | `turn_region_summary` 已删；零调用 | **删** | 同上 |
| `PowerStore.read_turn_power_summary` | `power/store.py:110` | `turn_power_summary` 已删；零调用 | **删** | 同上 |
| `ReignStateStore.read_turn_economy_summary` | `reign_state/store.py:244` | `turn_economy_summary` 已删；零调用 | **删** | 同上 |
| `ReignStateStore.read_treasury_ledger` | `reign_state/store.py:247` | `treasury_ledger` 已删；零调用 | **删** | 同上 |
| `BuildingStore.read_building_detail` | `building/store.py:101` | `building_detail` 已删；零调用 | **删** | 同上 |
| `BuildingStore.read_building_detail_` | `building/store.py:110` | 零调用；trailing `_` 迁移残片 | **删** | 同上 |
| `CharacterStore.read_list_office_vacancies` | `character/store.py:460` | `list_office_vacancies` 已删；零调用 | **删** | 退役读口；VIEW `office_vacancies` 仍在 schema（派生视图保留，不据此留无主调用读口） |
| `ReignStateStore.list_rollback_items_for_turn` | `reign_state/store.py:590` | 与 `_chat_turn_rollback_items` 同体；后者被 `db.py` 三处调用，本方法零引用 | **删** | 重复定义；保留有调用的那份 |
| `CharacterStore.delete_by_name` | `character/store.py:228` | 与 `delete` 同 SQL；零调用；现役路径走 `delete` | **删** | 重复删除原语 |
| `db.py` `DROP TABLE IF EXISTS dossier_progress_reports` | `db.py:936` | 生产无 CREATE；旧布局兼容处置 | **删** | 不延续旧表迁移；无历史包袱 |
| `POPULATION_UNIT_PERSONS` / `_POPULATION_UNIT_KEY` 双定义 | `db.py:108–109` 与 `reign_state/store.py:20–21` | save_meta 写在 reign；属性读在 GameDB | **合并** | 真源留 `reign_state/store.py`；`db.py` 改为 import `POPULATION_UNIT_PERSONS` |
| `ReignStateStore._chat_turn_rollback_items` | `reign_state/store.py:404` | `db.py` 5545/14680/14745 调用 | **留** | 现役回滚读口 |
| `CharacterStore.delete` | `character/store.py:106` | `db.py` / `issues.py` 调用 | **留** | 现役删除原语 |
| `BuildingStore.read_buildings_report` / `read_buildings_report_` | `building/store.py` | `db.buildings_report` 调用 | **留** | 现役奏报入口，非退役 |
| `ArmyStore.read_army_report` / `read_army_detail` 等有外部引用的 report/detail | 各 store | `db.py` 等仍调 | **留** | 消费者未删 |
| `ReignStateStore._ledger_exclusions` | 同文件内部 | `ledger_totals` / `recent_ledger` 内用 | **留** | 非退役碎片 |
| `office_vacancies` VIEW（schema） | `schema.py` | 派生视图；无本轮删 VIEW 授权需求 | **留** | 不是无主的查询方法碎片；删的是无调用 Store 读口 |
| 票面待接线、有现役职责但静态未引用的其它 Store API | 多处 | 非「消费者已删的退役入口」同形 | **留** | 判词：不因静态未引用一概删 |

未在本轮谓词命中、故不扩权处理：`turn_building/faction/character_summary` 等方法定义本身已不存在（枚举 defs=0）。

---

## K2 全员表与逐项去留

| 成员 | 位置 | 性质 | 处置 | 理由 |
|---|---|---|---|---|
| `monkeypatch.setattr(db, "faction_report", …)` ×2 | `tests/test_character_knowledge_489.py:41,61` | 钩退役实现；进行为前 AttributeError | **删钩子** | 保留 `world` 结构化边界断言与 `prepare_character_materials` 真入口 |
| `test_inner_court_materials_do_not_read_faction_report` | 同上 | 用例名锁退役 API | **改名**为 `test_inner_court_materials_exclude_court_world_slice` | 现役契约=内廷无 `court` 世界切片 |
| `assert not any("standalone" in k for k in after["_meta"])` ×2 | `tests/test_fiscal_substrate_bridge.py:3495,3545` | 内部退役形状（`_meta` 键名） | **删断言** | 同案已有建军/省欠/Due 外部行为断言 |
| `test_turn_region_summary_claim_audit_rows_do_not_consume_limit` | `tests/test_pay_order_override_653.py:486` | 名锁退役 `turn_region_summary`；无断言的 INSERT 残段为旧 LIMIT 形状成本 | **改名+删死 INSERT** | 保留 settle→`region_logs` 官俸欠/宗禄欠外部行为断言；新名 `test_province_tick_writes_salary_and_stipend_claim_audit_rows` |
| `test_office_slice_does_not_read_unrelated_sensitive_reports` 对 `army_report`/`treasury_report` 的 monkeypatch | `test_character_knowledge_489.py` | 钩子目标仍是现役 GameDB 方法 | **留** | 现役可见边界负向契约 |
| `test_*` 中对 `personnel`/`military`/`treasury`/`court` 的 world 结构化断言 | 同上等 | 现役公私可见边界 | **留** | 判词要求保留 |
| `dossier_progress_reports` 作为 extractor/delta 字段的测试夹具 | `test_month_chain_1847.py` 等 | 现役声明字段名，不是 DROP 表处置 | **留** | 非退役实现钩；与 K1 旧表 DROP 不同物 |
| `test_qa_e1_numeric_presentation.py` 模块头注释提及 `turn_army_summary` | 注释 | 非断言、不锁行为 | **留** | 文档叙事，非测试成本 |
| `test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone` 等名含 standalone 的现役财政案 | fiscal 测试 | 测现役 shadow/standalone 流程名，非 `_meta` 退役键证明 | **留** | 非本类「内部退役形状」 |

---

## 复扫结果（施工后实测）

命令：同上方枚举脚本 + 缺方法 monkeypatch / standalone 断言复扫。

| 检查项 | 结果 |
|---|---|
| K1A 退役形 Store defs | **NONE** |
| K1B DROP TABLE | **NONE** |
| K1C `POPULATION_UNIT*` 赋值点 | 仅 `reign_state/store.py:20–21` |
| K1D 同体重复方法 | **DUP_COUNT 0** |
| K2 missing GameDB monkeypatch | **NONE** |
| K2 standalone-in-`_meta` 断言 | **NONE** |
| K2 非注释退役钩子行 | **0** |

---

## 聚焦测试（七 BIN=/usr/bin/false）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  python3 -m pytest -q \
    tests/test_character_knowledge_489.py::test_inner_court_materials_exclude_court_world_slice \
    tests/test_character_knowledge_489.py::test_current_state_facts_are_selected_by_content_domain_not_role_label \
    tests/test_character_knowledge_489.py::test_office_slice_does_not_read_unrelated_sensitive_reports \
    tests/test_fiscal_substrate_bridge.py::test_liaodong_and_dongjiang_carry_no_army_less_pay_ledger \
    tests/test_fiscal_substrate_bridge.py::test_liaodong_pay_source_rows_are_the_only_pay_ledger \
    tests/test_fiscal_substrate_bridge.py::test_province_tick_shortfall_lands_fully_on_real_army_rows \
    tests/test_fiscal_substrate_bridge.py::test_new_dongjiang_army_makes_province_due_exactly_its_row_due \
    tests/test_fiscal_substrate_bridge.py::test_dismissal_keeps_archived_office_title_as_history \
    tests/test_pay_order_override_653.py::test_province_tick_writes_salary_and_stipend_claim_audit_rows \
    tests/test_new_game_smoke.py
```

实测：`15 passed in 2.29s`（`/usr/bin/time -p` → real **2.78s**）

追加：

```sh
# 同上七 BIN 前缀
python3 -m pytest -q \
  tests/test_character_knowledge_489.py::test_turn_zero_knowledge_is_role_specific_and_restores \
  tests/test_character_knowledge_489.py::test_restored_knowledge_uses_current_db_office_after_transfer \
  tests/test_qa_a3_seed_data.py -k 'vacancy or office or seed or opening'
```

实测：`9 passed, 1 deselected in 0.99s`（real **1.43s**）

人口单位合并触及面：

```sh
# 同上七 BIN 前缀
python3 -m pytest -q tests/test_population_unit_648.py tests/test_population_transfers_649.py
```

实测：`21 passed in 1.39s`（real **1.83s**）

未跑全量（派单禁止）。

---

## 真实未结项

- 本切片未宣称 #1889 / #1812 merge 或关票。
- 功能缺口与测试红灯仍归 **#1873**（末份判词 J7/J9 处置），本轮不送修。
- 家族收尾整体复杂度对比仍呈 owner（#1812 验收第 2 条）；本轮只清 K1/K2。
- `office_vacancies` VIEW 与其它静态未引用但非「退役入口碎片」的 Store API：保留待家族接线判断，不在本回收窄扩删。
