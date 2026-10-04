# #1897 修内司 R1–R4 回执（整类自检修订·机械证据）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-r1-r4-fixer-20261005-053204`
- 底座 HEAD（施工前）：`64b899a0e1682b30bc74d18688380237773251ce`
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a1089b-50c9-7dac-ab41-8ba86b05e2c6@fixer/fix-packet.md`
- 冻结判词：同 run `attachments/01-1897-judge-64b899a0e.json` 末 payload（`status=continue`）；先前 `converged` 卷仅参考
- 状态：本轮新独立提交；**未 push、未开 PR、未 amend、未 stash**
- **未声称 reviewer 放行**（R2=P1，`reviewGate` 要求新 HEAD 全范围复审）

## 授权核验

- 派单 + 用户明示「同树 #1897 自检并修完」→ 代码修改授权
- 类边界 = 判词 R1–R4 全文；点名仅为样本
- Event/Future 确定性握手按 Correctness C5 **保留**
- 未改 Soul/宪法/宿主配置

## 本轮相对前回执的续清

| 前回执缺陷 | 本轮处置 |
|---|---|
| R3/R4/变异命令块仅注释占位 | 改为完整可运行 Python；变异输出为本轮实测 JSON |
| R4 称 helper-only=`none` 但 payoff 仍留 helper-only 测 | **整类删除** 5 个 helper-only（见 R4），非只删末定义 |
| 硬编码 27 文件白名单 | 全仓 `tests/test_*.py` AST → 以 imports/调用/#1897 接缝符号定位授权相关文件（本轮 40） |
| `contract_axes_direction` / `build_secret_covert_effect_briefs` 以「非旧形状」保留 | 机械：零生产消费者；属未消费替身/附属物 → **删除** |
| 盯文：结构化键豁免自由文本值 | 复核 `declaration_dispatch` `payload["text"]`：属输入原文等值落账（#1897 AC），保留并写理由；非生成散文锁 |
| R1 变异非 materials 路径 / 伪红绿 | 改为 `prepare_character_materials` 结构化路径观察 + 旧 `text_log_json` 读口对照；明确非入口红断言 |
| R2 旧谓词未真实 create 改 facts | 装回旧谓词后真实 `create_secret_order` → truth_keys/fact_lanes 变 true |

## R1：旧密令正文账轨仍参与现役接缝（P2）

**类定义**：密令记录及其读取、更新接缝上的重复可写真源 / 旧正文账轨。

### 全仓枚举命令（已跑）

```bash
rg -n --no-heading -g '*.py' \
  'text_log_json|_has_secret_order_period_line|_append_secret_order_line|_write_secret_order_body|_read_secret_order_body_before_write|_load_secret_order_body_row|_secret_order_body_log|_secret_order_period_recorded|_project_secret_order_bodies|_secret_order_kept_body|_secret_order_record_body|_SECRET_ORDER_BODY_COLUMNS'
```

**复扫结果（本轮 HEAD）**：无匹配（CLEARED）。

### 施工前成员表（相对 64b899a0e，git show / 先前枚举）

| 成员 | 位置 | 处置 |
|---|---|---|
| `_SECRET_ORDER_BODY_COLUMNS` | `ming_sim/db.py`（旧） | 删 |
| `_secret_order_kept_body` / `_secret_order_record_body` / `_secret_order_body_log` | `db.py` | 删 |
| `text_log_json` 列与读写 | `db.py` schema+读口 | 删 |
| `_secret_order_period_recorded` / `_project_secret_order_bodies` | `db.py` | 删 |
| `_read_secret_order_body_before_write` / `_has_secret_order_period_line` / `_load_secret_order_body_row` / `_append_secret_order_line` | `db.py` | 删 |
| `materials.py` 现役读口 | `ming_sim/materials.py:755,794-796` | **改读** `order["dossier_progress"]`；标签串仍为 UI 呈现 |

### 保留（非旧账轨）

| 成员 | 位置 | 理由 |
|---|---|---|
| `dossier_progress_json` / `list_dossier_progress` / `record_dossier_progress` | db | #566/#883 权威月报轨 |
| `secret_order_briefs.body` / `update_secret_order_by_id` title/content | db | 密令要旨原文，非 progress 双真源 |
| `materials.py:796`「本月已推进/尚未推进」 | materials | UI 标签；判定轴是 dossier_progress 结构化字段 |

### R1 变异探针（本轮实测；对照观察，非入口红断言）

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python <<'PY'
from __future__ import annotations
import json, tempfile, shutil
from pathlib import Path
from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB
from ming_sim.materials import prepare_character_materials, release_material_tree, list_materials
from ming_sim.covert_progress import build_covert_task_contract

content = GameContent.load(); ctx_bind(content); issues_mod.bind_content(content)
tmpdir = tempfile.mkdtemp(prefix='1897-r1-mut-')
db = GameDB(str(Path(tmpdir)/'probe.db'), content)
db.seed_static_data(); state = db.load_state(); issues_mod.sync_opening_legacies(db, state)
minister = db.conn.execute(
    "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
).fetchone()['name']
contract = build_covert_task_contract(
    kind='补发饷银', axes=['既得利益'], direction=1,
    delivery_unit='万两', delivery_target_units=1, effect_sign=-1,
    purpose='其它', category='密令差务', account='内库',
)
oid = db.create_secret_order(
    state, minister, 'R1探针密令', '结构化月报观察', [],
    deadline_months=2, covert_task=contract,
)
ok = db.update_secret_order_progress(oid, '本月已推进（特征观察，不作断言）')
dossier = db.get_dossier_for_secret_order(oid)
progress = db.list_dossier_progress(int(dossier['id']))
turns = [int(p.get('turn') or 0) for p in progress]
bands = [str(p.get('progress_band') or '') for p in progress]
origins = [str(p.get('origin') or p.get('report_origin') or '') for p in progress]
advanced_struct = (int(state.turn) in turns) and bool(progress)
prepared = prepare_character_materials(db, state, content.characters[minister])
try:
    mats = list_materials(prepared.root)
    path_present = '密令/进行中.txt' in mats
    body = (Path(prepared.root)/'密令'/'进行中.txt').read_text(encoding='utf-8') if path_present else ''
    mentions_advanced = ('本月已推进' in body) or ('已推进' in body)
    mentions_not_advanced = '尚未推进' in body
finally:
    release_material_tree(prepared.root)
cols = {r[1] for r in db.conn.execute('PRAGMA table_info(secret_orders)').fetchall()}
old_text_log_period_line = False
old_err = None
try:
    row = db.conn.execute('SELECT text_log_json FROM secret_orders WHERE id=?', (int(oid),)).fetchone()
    log = json.loads((row['text_log_json'] if row is not None else None) or '[]')
    if isinstance(log, list):
        for item in log:
            if isinstance(item, dict) and int(item.get('turn') or 0) == int(state.turn):
                old_text_log_period_line = True
except Exception as e:
    old_err = f'{type(e).__name__}:{e}'
    old_text_log_period_line = False
ok2 = db.update_secret_order_by_id(state, oid, 'R1探针密令·改', '结构化月报观察')
print(json.dumps({
    'progress_update_ok': bool(ok),
    'list_dossier_progress_turns': turns,
    'bands': bands,
    'origins': origins,
    'advanced_struct': advanced_struct,
    'material_path_密令进行中': path_present,
    'free_text_feature_mentions_advanced': mentions_advanced,
    'free_text_feature_mentions_not_advanced': mentions_not_advanced,
    'text_log_column_present': 'text_log_json' in cols,
    'old_text_log_period_line': old_text_log_period_line,
    'old_period_reader_error': old_err,
    'divergence_struct_vs_old_reader': bool(advanced_struct) and (not old_text_log_period_line),
    'legal_update_secret_order_by_id_ok': bool(ok2),
    'note': 'contrast observation only; not entry red assertion; free text feature print only',
}, ensure_ascii=False, indent=2))
db.close(); shutil.rmtree(tmpdir, ignore_errors=True)
PY
```

**本轮实测输出**：

```json
{
  "progress_update_ok": true,
  "list_dossier_progress_turns": [1],
  "bands": ["进展"],
  "origins": ["dossier-report:monthly_errand"],
  "advanced_struct": true,
  "material_path_密令进行中": true,
  "free_text_feature_mentions_advanced": true,
  "free_text_feature_mentions_not_advanced": false,
  "text_log_column_present": false,
  "old_text_log_period_line": false,
  "old_period_reader_error": "OperationalError:no such column: text_log_json",
  "divergence_struct_vs_old_reader": true,
  "legal_update_secret_order_by_id_ok": true,
  "note": "contrast observation only; not entry red assertion; free text feature print only"
}
```

说明：结构化轴 = `list_dossier_progress` turns/bands/origin + 材料路径存在；自由文本仅特征打印。旧 period reader 因列已删报 `OperationalError`，与当前合法 `update_secret_order_by_id` 成功对照——**不是**入口红绿断言。

## R2：说明文字及解析失败被提升为真实罪证（P1）

**类定义**：结构化罪情→实证集合→开案 lane；散文/坏形状不得造罪。

### 全仓枚举命令（已跑）

```bash
rg -n --no-heading -g '*.py' \
  'seed_guilt_counts_as_debt|seed_guilt|live_investigation_fact_keys|fact_lanes|FACT_LANES_KEY|truth_keys|罪情|severity|_DEBT_SEVERITIES|seed_investigation_fact_lanes'
```

### 精确位置与处置

| 成员 | 位置 | 处置 |
|---|---|---|
| `_DEBT_SEVERITIES` | `ming_sim/covert_progress.py:149` | 保留白名单 `{轻,中,重}` |
| `seed_guilt_counts_as_debt` | `covert_progress.py:152-171`；消费者 `live_investigation_fact_keys` @`:813` | **已恢复**：仅 severity∈白名单；解析失败/非对象→False |
| `live_investigation_fact_keys` | `:799+` | 保留 |
| `seed_investigation_fact_lanes` / db `create_secret_order` | db≈21912 | 保留真实开案写口 |
| `content.py` seed_guilt 装载校验 | content | 保留（装载契约） |
| helper-only `test_seed_guilt_*` | 旧 | **已删** |
| `test_create_secret_order_fact_lanes_follow_structured_severity_only` | `tests/test_secret_order_payoff_1504.py:225` | **保留**：真实 `_issue`/`create` 负向 |

### R2 变异探针（本轮实测）

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python <<'PY'
from __future__ import annotations
import json, tempfile, shutil
from pathlib import Path
from typing import Mapping
from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB
from ming_sim import covert_progress as cp
from ming_sim.covert_progress import live_investigation_fact_keys, FACT_LANES_KEY, build_covert_task_contract

content = GameContent.load(); ctx_bind(content); issues_mod.bind_content(content)
tmpdir = tempfile.mkdtemp(prefix='1897-r2-mut-')
db = GameDB(str(Path(tmpdir)/'probe.db'), content)
db.seed_static_data(); state = db.load_state(); issues_mod.sync_opening_legacies(db, state)
targets = ['吴三桂', '温体仁', '洪承畴']
present = [n for n in targets if db.conn.execute('SELECT 1 FROM characters WHERE name=?', (n,)).fetchone()]
minister = db.conn.execute(
    "SELECT name FROM characters WHERE status='active' AND name NOT IN (%s) ORDER BY name LIMIT 1"
    % (','.join('?'*len(present)) if present else '?'),
    present or ['__none__'],
).fetchone()['name']

def lane_keys(oid):
    d = db.get_dossier_for_secret_order(oid)
    payload = json.loads(d.get('payload_json') or '{}') if d else {}
    raw = payload.get(FACT_LANES_KEY) or []
    if isinstance(raw, list):
        return [str(x.get('fact_key') or '') for x in raw if isinstance(x, dict)]
    return list(raw.keys()) if isinstance(raw, dict) else []

def issue(target):
    frozen = build_covert_task_contract(covert_task={
        'kind': '查核', 'axes': ['既得利益'], 'direction': 1,
        'investigation_target': target,
        'delivery': {'target_units': 1.0, 'effect_sign': 1},
    })
    return db.create_secret_order(
        state, minister, f'查{target}', 'R2探针', [],
        deadline_months=1, covert_task=frozen,
    )

for name in present:
    db.conn.execute(
        'UPDATE characters SET seed_guilt=? WHERE name=?',
        (json.dumps({'crime': '查无实据', 'severity': '无'}, ensure_ascii=False), name),
    )
db.conn.commit()
current = []
for name in present:
    in_keys = name in live_investigation_fact_keys(db, name)
    oid = issue(name)
    in_lanes = name in lane_keys(oid)
    current.append({'name': name, 'name_in_truth_keys': in_keys, 'name_in_fact_lanes': in_lanes})
    db.conn.execute("UPDATE secret_orders SET status='closed' WHERE id=?", (oid,))
    db.conn.commit()

def old_seed_guilt_counts_as_debt(seed_guilt: object) -> bool:
    if isinstance(seed_guilt, Mapping):
        guilt = seed_guilt
    else:
        text = str(seed_guilt or '').strip()
        if not text:
            return False
        try:
            guilt = json.loads(text)
        except Exception:
            return True
    if not isinstance(guilt, Mapping):
        return True
    crime = str(guilt.get('crime') or '').strip()
    severity = str(guilt.get('severity') or '').strip()
    if crime and crime != '无':
        return True
    if severity and severity != '无':
        return True
    return False

cp.seed_guilt_counts_as_debt = old_seed_guilt_counts_as_debt
prose_cases = []
for name in present:
    seed = json.dumps({'crime': '查无实据', 'severity': '无'}, ensure_ascii=False)
    db.conn.execute('UPDATE characters SET seed_guilt=? WHERE name=?', (seed, name))
    db.conn.commit()
    in_keys = name in live_investigation_fact_keys(db, name)
    oid = issue(name)
    in_lanes = name in lane_keys(oid)
    prose_cases.append({
        'name': name, 'name_in_truth_keys': in_keys, 'name_in_fact_lanes': in_lanes,
        'facts_changed': bool(in_keys or in_lanes),
    })
    db.conn.execute("UPDATE secret_orders SET status='closed' WHERE id=?", (oid,))
    db.conn.commit()
print(json.dumps({
    'current_severity_none': current,
    'old_predicate_prose_create': prose_cases,
    'facts_changed_under_old_predicate': any(c['facts_changed'] for c in prose_cases),
    'all_current_clean': all((not c['name_in_truth_keys'] and not c['name_in_fact_lanes']) for c in current),
}, ensure_ascii=False, indent=2))
db.close(); shutil.rmtree(tmpdir, ignore_errors=True)
PY
```

**本轮实测摘要**：`all_current_clean=true`；装回旧谓词后三名均 `name_in_truth_keys=true` 且 `name_in_fact_lanes=true`，`facts_changed_under_old_predicate=true`。

## R3：退休领域机制及未消费替身未清退（P2）

**类定义**：搬迁后被替代代码及其附属物；优先删除，不补常量、不重接调用。

### 全仓枚举命令（已跑；完整可运行）

```bash
rg -n --no-heading -g '*.py' \
  'terminal_report_facade|latest_monthly_memorial|target_progress_units|read_substantiated_legal_reason_code|_substantiate_lane|advance_investigation_lanes|mark_investigation_fact_used|DEFAULT_SUBSTANTIATION|_TERMINAL_REPORT_FACADE|parse_covert_exec_selections|contract_axes_direction|build_secret_covert_effect_briefs'
```

本轮复扫：**无匹配**。

全模块定义 + 消费者计数（本轮实测，输出存 `artifacts/1897-r3-covert-progress-consumers.txt`）：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 <<'PY'
import ast
from pathlib import Path
ROOT = Path('.').resolve()
mod_path = ROOT / 'ming_sim' / 'covert_progress.py'
tree = ast.parse(mod_path.read_text(encoding='utf-8'))
defs = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        defs.append((type(node).__name__, node.name, node.lineno))
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                defs.append(('Assign', t.id, node.lineno))
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        defs.append(('AnnAssign', node.target.id, node.lineno))
names = sorted({n for _, n, _ in defs if not n.startswith('__')})
py_files = [p for p in ROOT.rglob('*.py') if '.venv' not in p.parts and 'node_modules' not in p.parts]
cons = {n: {'prod': set(), 'test': set(), 'self_loads': 0} for n in names}
for node in ast.walk(tree):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in cons:
        cons[node.id]['self_loads'] += 1
for p in py_files:
    if p.resolve() == mod_path.resolve():
        continue
    rel = str(p.relative_to(ROOT))
    bucket = 'test' if rel.startswith('tests/') else 'prod'
    try:
        t = ast.parse(p.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        continue
    used = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in cons:
            used.add(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in cons:
            used.add(node.attr)
    for n in used:
        cons[n][bucket].add(rel)
print(f'DEFS\t{len(defs)}')
for kind, name, lineno in defs:
    c = cons[name]
    if c['prod']:
        flag = 'HAS_PROD'
    elif c['test']:
        flag = 'TEST_ONLY'
    elif c['self_loads'] > 0:
        flag = 'INTERNAL_ONLY'
    else:
        flag = 'NO_EXTERNAL_OR_INTERNAL_LOAD'
    print(
        f'{name}\t{mod_path.name}:{lineno}\t{flag}\t'
        f'prod={len(c["prod"])}\ttest={len(c["test"])}\tself_loads={c["self_loads"]}\t'
        f'prod_files={sorted(c["prod"])}\ttest_files={sorted(c["test"])}'
    )
PY
```

本轮：`DEFS=95`；全表见 `artifacts/1897-r3-covert-progress-consumers.txt`。

### 成员裁定（含点名孤儿）

| 成员 | 机械结果 | 处置 | 依据 |
|---|---|---|---|
| `target_progress_units` / progress·reason_code·used 旧形状 / `terminal_report_facade` / `latest_monthly_memorial` / `parse_covert_exec_selections` | 此前已删；复扫无匹配 | 维持删除 | 判词 R3 |
| `contract_axes_direction` | 施工前零外部引用；非现役生产消费者 | **本轮删除** | 未消费替身/附属物；不能以「非旧 progress 形状」豁免 |
| `build_secret_covert_effect_briefs` | 仅测试一行断言；无生产消费者 | **本轮删除**；测试改靠 `apply_monthly_covert_actual_progress` 发令月跳过 | 未消费 internal 简报建造器；#883 私密输入若需重建须有真实生产接线后再议 |
| `decide_secret_order_settlement` | INTERNAL_ONLY；`settle_due_secret_orders` @≈2101 调用 | **保留** | 现役结案裁定；生产路径经 `settle_due_secret_orders`→`month_chain` |
| `seed_guilt_counts_as_debt` | INTERNAL_ONLY via `live_investigation_fact_keys` | **保留** | R2 权威谓词 |
| `globally_used_fact_keys` | INTERNAL | **保留** | #1896 mastered 去重，非旧 `used` 字段 |
| 模块内常量/私有 helper（FIDELITY 等） | INTERNAL_ONLY | **保留** | 现行函数体依赖，非搬迁替代物 |

## R4：测试覆盖、权威与成本失真（P2）

**类定义**：授权改动对应的测试体系——删重复/失效 helper/盯文/内部结构断言；保留必要真实入口结构化负向；Event/Future 不删。

### 全仓 AST 枚举 + 授权定位（已跑；非 27 文件白名单）

授权谓词：全仓 `tests/test_*.py` AST；文件进入授权集当且仅当（imports∪调用）触及 #1897 接缝符号（`create_secret_order` / `covert_progress` / `dispatch_declaration` / `dossier_progress` / `settle_due_secret_orders` / `seed_guilt*` / `prepare_character_materials` 等）**或** stem 直接锚定密令/声明/due_review/execution_pressure/monthly_progress/dossier_reported/deformation/staged_assignment/audience_translate_1837_reopen。

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 <<'PY'
import ast
from pathlib import Path
from collections import defaultdict
ROOT = Path('.')
CHANGE_SYMS = {
    'create_secret_order','update_secret_order_by_id','update_secret_order_progress',
    'list_dossier_progress','record_dossier_progress','prepare_character_materials',
    'seed_guilt_counts_as_debt','live_investigation_fact_keys','settle_due_secret_orders',
    'apply_monthly_covert_actual_progress','dispatch_declaration','build_covert_task_contract',
    'decide_secret_order_settlement','read_covert_task_contract','CovertContractError',
    'FACT_LANES_KEY','dossier_progress','secret_order',
}
REAL_ENTRY = {
    'create_secret_order','update_secret_order_by_id','update_secret_order_progress',
    'prepare_character_materials','run_player_month_chain','settle_due_secret_orders',
    'apply_monthly_covert_actual_progress','dispatch_declaration','_issue',
}
HELPER_ONLY_CALLEES = {
    'seed_guilt_counts_as_debt','decide_secret_order_settlement',
    'build_covert_task_contract','build_secret_covert_effect_briefs',
    'contract_axes_direction','target_progress_units',
}
STEM_KEYS = (
    'secret_order','covert','declaration_dispatch','due_review','execution_pressure',
    'monthly_progress','dossier_reported','deformation_dual','audience_translate_1837_reopen',
    'staged_assignment_identity',
)
auth=[]; helper_only=[]; dups=[]
for tf in sorted(ROOT.glob('tests/test_*.py')):
    src = tf.read_text(encoding='utf-8', errors='replace')
    try: tree = ast.parse(src)
    except SyntaxError: continue
    imports=set(); calls_file=set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module: imports.add(node.module)
            for a in node.names: imports.add(a.name)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name): calls_file.add(node.func.id)
            elif isinstance(node.func, ast.Attribute): calls_file.add(node.func.attr)
    touch = bool(imports & CHANGE_SYMS) or bool(calls_file & CHANGE_SYMS) \
        or any(k in tf.stem for k in STEM_KEYS) or 'covert_progress' in ''.join(imports)
    if not touch: continue
    auth.append(str(tf))
    by_name=defaultdict(list); funcs=[]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
            by_name[node.name].append(node.lineno); funcs.append(node)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                    by_name[item.name].append(item.lineno); funcs.append(item)
    for name, lines in by_name.items():
        if len(lines) > 1: dups.append((str(tf), name, lines))
    for fn in funcs:
        calls=set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name): calls.add(n.func.id)
                elif isinstance(n.func, ast.Attribute): calls.add(n.func.attr)
        if (calls & HELPER_ONLY_CALLEES) and not (calls & REAL_ENTRY) and '_issue' not in calls:
            helper_only.append((str(tf), fn.lineno, fn.name, sorted(calls & HELPER_ONLY_CALLEES)))
print('AUTHORIZED_FILES', len(auth))
for f in auth: print('AUTH', f)
print('DUPS', dups or 'none')
print('HELPER_ONLY', helper_only or 'none')
PY
```

**本轮结果**：`AUTHORIZED_FILES=40`；`DUPS=none`；删后 `HELPER_ONLY=none`。

### helper-only / 盯文 / spy 逐条

| 成员 | 处置 | 一行理由（必要契约 / 最小成本） |
|---|---|---|
| `test_decide_settlement_delivery_gap_bidirectional` | **删** | 仅调 `decide_secret_order_settlement`；结案契约已由 `settle_due_*` 真实入口覆盖 |
| `test_task_specific_contract_from_explicit_fields_not_tags` | **删** | 仅调 `build_covert_task_contract`；显式字段落库已由 `test_confirm_persists_*` 覆盖 |
| `test_task_specific_contract_rejects_tags_without_explicit_fields` | **删** | helper-only 拒收；`test_create_secret_order_rejects_missing_contract` 真实入口负向已在 |
| `test_confirmation_rejects_incomplete_delivery_identity` | **删** | helper-only 参数化；不另造平行测 |
| `test_non_investigation_contract_keeps_its_delivery_account` | **删** | 仅 build helper；筹饷交付已由 create+settle 路径覆盖 |
| payoff 三组同名（旧 232/2765 等） | 已删末覆盖 | AST dups=none |
| monthly `memorial_text` 字符串锁 / `read_fields` spy | 先前已去 | 改结构化 turn/band + 材料路径 |
| execution_pressure `payload["text"]` 等值散文 | 先前已去 | 现为非空结构化字段存在性 |
| declaration_dispatch `payload["text"] ==` 输入原文（:68,:112,:166） | **保留** | 真实 `dispatch_declaration` 入口：输入原文等值落账（#1897 正文原样转运 AC）。结构化键不豁免盯文，但此处比对的是**输入身份**而非生成散文；删之会丢掉「禁 strip/裁剪」唯一负向 |
| `secret_order_update` content 等值 | **保留** | 要旨原文写读契约；非 progress 双真源盯文 |
| Event/Future 握手（declaration_landing ≈112–120、297–307） | **保留** | 判词 C5 |
| `test_create_secret_order_fact_lanes_follow_structured_severity_only` | **保留** | R2 真实入口结构化负向 |
| `test_settle_due_close_follows_surviving_memorial_and_actual` | **保留** | 真实结案契约 |
| monkeypatch fail-injection（month rollback / supply 隔离） | **保留** | 故障注入控序，非退休 helper 内部结构 spy |

## 判词 finding 对照

| 来源 | 处置 |
|---|---|
| C1→R1 | 旧账轨清空；materials 读 dossier_progress；变异 divergence 对照 |
| C2→R2 | severity 白名单；真实 create 负向；旧谓词装回造罪 |
| C3/C4→R3 | 退休机制删除；本轮删 `contract_axes_direction` / `build_secret_covert_effect_briefs` |
| C4/C3→R4 | 整类删 helper-only；盯文复核；握手保留 |
| C5 Event/Future | 驳回维持 |
| 事件结局三失败 | 转 #1873 |
| 名册拒收 | 不沿用旧卷称未修 |

## 聚焦测试

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  ../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_secret_order_declaration_landing_1897.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_secret_order_section_rejections.py \
  tests/test_execution_pressure_654.py \
  tests/test_audience_translate_1837_reopen.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_staged_assignment_identity_1890.py \
  tests/test_due_review_621.py \
  tests/test_dossier_reported_progress_619.py \
  tests/test_deformation_dual_rail_622.py \
  -q -p no:cacheprovider --basetemp=/private/tmp/1897-fixer-r1-r4-pytest3 --tb=line
```

本轮实测：`252 passed in 6.90s`（`/usr/bin/time -p`：real 7.53 / user 5.31 / sys 1.83）。未跑全量。basetemp 已删。

## 质量 / 合法性自检

- 以删除为主；未新增兼容层、恢复协议、生产测试钩子、平行证明测试
- 自查二连：同类型整类扫完；引入面（删孤儿、删 helper-only、材料/罪情契约）已核
- `git diff --check`：本轮代码 diff 无 whitespace 报错

## 剩余项 / 依法阻断

1. **须在新 HEAD 上全范围复审**（R2=P1）。本回执不声称 reviewer 放行。
2. 事件结局功能缺口按 #1873，本片不恢复。
3. 提交仅在工作树分支，尚未 merge。
