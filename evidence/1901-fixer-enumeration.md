# #1901 fixer — 三未结类全仓枚举回执

只记扫描事实与成员处置；不复制宪法。  
工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1901-w5`  
解释器：`../Ming_LLM/.venv/bin/python`  
本文件先前仅有「单值 PATHS 残余脚手架」窄扫；**不冒称**此前已写入两类诊断全仓枚举或财政原始双路扫描。下列命令均为本回执补齐时实际执行。

冻结判词附件（fix-packet 三份）：

1. `诊断验收仍绑定 JSON 呈现形状`（sealed1）
2. `诊断验收仍依赖非契约序列化形状`（sealed2；处方含内部实现路径依赖）
3. `迁出的军饷模块仍保留退役财政兼容路径`（sealed3）

原始 JSON：`/tmp/1901-fixer-evidence/full_enum.json`、`/tmp/1901-fixer-evidence/classified.json`。

---

## 类 A+B：诊断验收呈现形状 / 非契约序列化 / 内部实现路径

### 类定义（不得收窄到判词点名符号）

票面/判词：诊断验收仍绑定 JSON 呈现形状；仍依赖非契约序列化形状；必要诊断事实应保留，旧混合日志形状不应继续成为兼容负担。  
**全类谓词**（合并 sealed1+sealed2）：

1. 测试以非契约呈现验收 dump 事实：默认 `json.dumps(...)` 子串、空格/键序、混合散文定位（`raw_decode` / 首个 `{` index）、标签字符串锁；
2. 测试绑定内部实现路径：对编码器/私有清洗函数做 wraps spy、反射签名/源码、mock 序列化结果当验收；
3. 生产唯一 dump 接缝与其文档/启动开关是本类处置面（可替换落盘格式，不承担旧混合文字兼容）。

判词点名 `json.dumps(vars(metrics)) in text` 只是样本。

### 实际执行命令

```bash
# 修前对照（判词底座 d3ebf7e0f，非本工作树冒称「早已扫过」）
git grep -n 'json.dumps(vars(metrics)' d3ebf7e0f -- tests
git grep -n '_dump_llm_messages\|\[usage/metrics\]\|raw_decode\|MING_SIM_DUMP_LLM\|llm_dump_' d3ebf7e0f -- \
  ming_sim tests start.sh docs/CHANGELOG_cli_backend.md

# 当前 HEAD 全仓 tracked 扫描（脚本落 /tmp/1901-fixer-evidence）
PYTHONDONTWRITEBYTECODE=1 ../Ming_LLM/.venv/bin/python <<'PY'
# 谓词：dump 接缝 + 测试对 dump 事实的呈现/实现路径依赖
# （见 classified.json：c12_members_base / c12_members_now / c12_line_hits_now_dump_focused）
from pathlib import Path
import ast, json, re, subprocess
ROOT = Path('.').resolve()
tracked = subprocess.check_output(['git','ls-files'], text=True).splitlines()
DUMP_RE = re.compile(
    r'_dump_llm_messages|_dump_jsonable|_json_default|MING_SIM_DUMP_LLM|llm_dump_|'
    r'\[usage/metrics\]|\[finish_reason\]|json\.dumps\(vars\(metrics\)|raw_decode|'
    r'wraps\s*=\s*json\.dumps'
)
hits=[]
for rel in tracked:
    if not rel.endswith(('.py','.md','.sh','.ts','.tsx')): continue
    text=(ROOT/rel).read_text(encoding='utf-8', errors='ignore')
    for i,line in enumerate(text.splitlines(),1):
        if DUMP_RE.search(line):
            hits.append({"file":rel,"line":i,"snippet":line.strip()[:220]})
members=[]
for rel in tracked:
    if not (rel.startswith('tests/') and rel.endswith('.py')): continue
    src=(ROOT/rel).read_text(encoding='utf-8')
    try: tree=ast.parse(src)
    except Exception: continue
    for node in ast.walk(tree):
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) or not node.name.startswith('test_'):
            continue
        body=ast.get_source_segment(src,node) or ''
        if not any(k in body for k in ('_dump_llm_messages','llm_dump','[usage/metrics]',
                                        'json.dumps(vars(metrics)','raw_decode')):
            continue
        kinds=[]
        if re.search(r'json\.dumps\(.+?\)\s+in\b', body): kinds.append('JSON_DUMPS_SUBSTRING')
        if 'raw_decode' in body or "text.index" in body or ".index('{')" in body:
            kinds.append('MIXED_PROSE_LOCATE')
        if '_dump_llm_messages' in body: kinds.append('TOUCHES_DUMP')
        if 'wraps' in body and 'json.dumps' in body: kinds.append('ENCODER_WRAP')
        if 'json.loads' in body and ('usage' in body or 'finish_reason' in body or 'reasoning' in body):
            kinds.append('STRUCTURED_JSONL_FIELD')
        members.append({"file":rel,"test":node.name,"line":node.lineno,"kinds":kinds})
print(json.dumps({"hit_count":len(hits),"members":members}, ensure_ascii=False, indent=2))
PY
```

另对 `d3ebf7e0f` 用同构 AST 读 `git show` 得到修前成员（`classified.json` → `c12_members_base`）。

### 修前成员表（d3ebf7e0f）

| # | 成员 | kinds | 处置 | 删除/改写来源 |
|---|------|-------|------|----------------|
| 1 | `tests/test_deepseek_thinking_disable_1797.py::test_dump_llm_messages_records_reasoning_usage_finish_reason` | `JSON_DUMPS_SUBSTRING`, `TOUCHES_DUMP` | **修**：混合散文/默认 JSON 子串 → JSONL 结构化字段断言（保留 usage 四字段、两路 reasoning、finish_reason 实值/缺席） | `411ceafab`（JSONL+结构化断言）；`66d6282bb`（`_json_default` 取代递归 `_dump_jsonable`，去掉编码器探测路径） |
| 2 | `tests/test_run_agent_text_transport_1465.py::test_run_agent_text_final_text_from_terminal_not_chunk_join` | `TOUCHES_DUMP` | **保留**：仅 `monkeypatch` 关掉 dump 旁路，不验收呈现形状 | — |
| 3 | `tests/test_run_agent_text_transport_1465.py::test_run_agent_text_history_backed_drops_empty_completed_before_retry` | `TOUCHES_DUMP` | **保留**：同上 | — |
| 4 | 生产 `ming_sim/agents.py::_dump_llm_messages` 混合文本（`[usage/metrics]` 散文行） | 接缝 | **修**：唯一落盘改为 JSONL 一行一对象；文档/`start.sh` 同步 `.jsonl` | `411ceafab` / `66d6282bb` |

先前轮次曾删的同类呈现依赖（不在 d3ebf7e0f 仍存活，但属本类历史成员，来源供追溯）：

| 历史形状 | 来源提交（git log） |
|----------|-------------------|
| 混合 dump `raw_decode` / 首 `{` 定位 | 已见于 `6c2cd77a7` 前序修理；d3ebf7e0f 时转为 `json.dumps` 子串 |
| `wraps=json.dumps` 编码器 spy（repair 回执曾记） | `docs/evidence/issue-1901-j3-j11-w5-repair.md` 描述的临时观测，未作为永久生产钩子保留 |
| 内部调用绑定（判词经过：`6c2cd77a7`→`d3ebf7e0f` 删除） | `d3ebf7e0f` |

### 修后成员表（当前 HEAD）

| # | 成员 | kinds | 现行处置 |
|---|------|-------|----------|
| 1 | `test_dump_llm_messages_records_reasoning_usage_finish_reason` | `TOUCHES_DUMP`, `STRUCTURED_JSONL_FIELD` | **保留**：读 JSONL 记录字段；不锁空格/键序 |
| 2–3 | `test_run_agent_text_transport_1465` 两案 | `TOUCHES_DUMP` | **保留**：noop dump，非形状验收 |
| 4 | `ming_sim/agents.py` JSONL dump + `_json_default` | 接缝 | **保留为现役唯一落盘**；`JSON_DUMPS_SUBSTRING` / `MIXED_PROSE_LOCATE` / `ENCODER_WRAP` 在 tests 中 **0** |

扫描附带命中（文档/历史证据/非 dump 验收）：`docs/evidence/issue-1797/*`、`docs/evidence/issue-1901-j3*`、`docs/CHANGELOG_cli_backend.md`、`start.sh` 开关说明——记入扫描事实，不改机制。

**完整性**：本类在「dump 验收」子集上已无呈现/编码器路径依赖。未把全仓一切 `json.dumps`/`json.loads`（邸报 payload、批红 body 等）扩进本类；若大理寺认定更宽，须另开谓词，不在此冒称已扫尽一切序列化。

---

## 类 C：迁出军饷模块的退役财政兼容路径（整体）

### 类定义（不得收窄到单值 PATHS 脚手架）

票面/判词：迁出的军饷计算仍并存现役与退役财政路径；问题是退役路径仍被维护。  
**全类谓词**（sealed3 + #1812 第1条，军饷计算及消费者范围）：

1. 生产：`settle_legacy_army_pay` / `fiscal_engine()=="legacy"` 军饷结算分支 / 仅为旧路维护的标量欠饷直写双轨；
2. 测试：仅证明旧军饷路行为的用例；`PATHS`/`fiscal_path` 双路或死单值矩阵/三元；关 cutover 种旧 scalar 军饷反事实；
3. 消费者夹具仍为旧兼容而分支的军饷结算入口。

**不含**：省级 substrate shadow 隔离、DB `apply_army_deltas` adapter 事实矩阵、非军饷结算的 `legacy` 引擎拒收案（加派/折发等，属他票世界记录边界）。

### 实际执行命令

```bash
# —— 财政原始扫描（修前底座 d3ebf7e0f；本回执新跑，非沿用旧证据）——
git grep -n 'settle_legacy_army_pay' d3ebf7e0f -- ming_sim tests
git grep -n 'PATHS\s*=' d3ebf7e0f -- 'tests/test_mutiny*.py' 'tests/test_player_army*.py'
git grep -n 'fiscal_engine()=="legacy"\|fiscal_path\|_use_legacy_fiscal\|test_legacy_.*pay\|across_paths\|跨财政路径' \
  d3ebf7e0f -- ming_sim tests

# 劳务进程申报的 AST 结果见 classified.json；本文件未提供其完整脚本，
# 不将原来的 print 占位段作为可复执行的枚举证据。

# 中间态（411ceafab 后退役 settle_legacy 后、仍留单值 PATHS）
git grep -n 'PATHS\s*=' 411ceafab -- 'tests/test_mutiny*.py' 'tests/test_player_army*.py'
git grep -n 'settle_legacy_army_pay' 411ceafab -- ming_sim tests || echo 'settle_legacy gone'

# 当前 HEAD 实际复扫（本席执行；首条无输出）
git grep -n -E 'settle_legacy_army_pay|fiscal_path|PATHS[[:space:]]*=' -- ming_sim tests || true
# 广义军饷消费候选文件，不将所有命中自动判作兼容路径：
git grep -n -E 'army_pay|arrears|军饷|补饷' -- ming_sim tests | cut -d: -f1 | sort -u
```

### 修前原始成员表（d3ebf7e0f，双路财政）

**生产**

| # | 位置 | 事实 | 处置 | 来源 |
|---|------|------|------|------|
| P1 | `ming_sim/army_pay.py:307` `settle_legacy_army_pay` | 完整旧结算 | **删** | `411ceafab` |
| P2 | `ming_sim/flows.py` import + `fiscal_engine()=="legacy"` → `settle_legacy_army_pay` | 结算双路 | **删**旧路；现役只在 hub 分支调 `settle_hub_*` | `411ceafab` |
| P3 | `army_pay` 标量欠饷直写与分源双维护 | 旧兼容分支 | **删**标量旧路，分源为现役 | `411ceafab` |

**测试（军饷消费者 / 仅旧路）**

| # | 成员 | 处置 | 删除来源 |
|---|------|------|----------|
| T1 | `test_army_salary_44.py::test_legacy_full_pay_grants_morale_bonus_unless_old_arrears_remain` | **删**；士气分档改纯函数 `test_army_pay_morale_delta_tiers` | `411ceafab` |
| T2 | `test_army_salary_44.py::test_legacy_salary_tick_preserves_fractional_opening_arrears` | **删** | `411ceafab` |
| T3 | `test_army_maintenance_retire_173.py::test_legacy_new_army_needs_only_manpower`（关 cutover 种旧路） | **删** | `411ceafab` |
| T4 | `test_fiscal_substrate_bridge.py::test_fixed_flows_legacy_engine_keeps_global_army_pay_route` | **删** | `411ceafab` |
| T5 | `test_junxin_monthly_tick_314.py` 双路 parametrize 轨迹案（`test_arrears_monthly_trajectory_*` / `test_full_pay_month_*` / `test_clamp_*` / `test_fractional_*` / `test_powder_keg_*` 等） | **删或改写**为 hub 单路 + 纯函数分档 | `411ceafab`；豁免军字段清零续于 `66d6282bb` |
| T6–T11 | `test_mutiny_{latch,progression,redemption,third_strike,noop_whitelist}_*.py`、`test_player_army_projection_321.py`：`PATHS=("legacy","substrate_hub")` + `fiscal_path` 参数/三元 | 先于 `411ceafab` 收成单值 `("substrate_hub",)`，再于 `c399a9dfb` **删尽** PATHS/参数/三元 | `411ceafab`（去 legacy 臂）；`c399a9dfb`（去单值脚手架） |
| T12 | `test_player_army_projection_321.py::test_restore_five_columns_and_player_tier_across_paths` | **改名** `...survives_reopen`（去 across_paths） | `c399a9dfb` |
| T13 | `test_effect_origin_558.py` 关 cutover=0「test legacy no-op」 | **改**现役 cutover=1 + 分源欠饷种子 | `c399a9dfb` |
| T14 | `test_mutiny_redemption_317.py` 「跨财政路径」措辞 | **删措辞** | `c399a9dfb` |

### 中间态（411ceafab / 66d6282bb）：单值 PATHS 残余

`PATHS = ("substrate_hub",)` 仍在 6 个军饷消费者测试中，并带死 `fiscal_path` 参数/三元——属全类谓词第2条残余，**不是**「原始双路已扫完」的替代证据。窄扫 AST 与逐文件处置见本文件前版段落；已并入上表 T6–T14，来源 `c399a9dfb`。

### 当前 HEAD 复扫成员表

| # | 文件/符号 | 扫描命中 | 分类 |
|---|-----------|----------|------|
| R1 | `settle_legacy_army_pay` | **0** | 已清 |
| R2 | `PATHS_ASSIGN` / `PARAMETRIZE_FISCAL_PATH` / `TERNARY_FISCAL_PATH` / `FUNC_PARAM_FISCAL_PATH`（军饷消费者） | **0** | 已清 |
| R3 | `tests/test_mutiny_third_strike_318.py` `parametrize("cutover",(0,1))` ×3 | 命中 | **保留**：DB `apply_army_deltas` adapter 事实，非结算财政 path 兼容（docstring 已标明） |
| R4 | `tests/test_fiscal_substrate_bridge.py` `_disable_army_pay_source_cutover` | 命中 | **保留扫描记录**：省级 substrate shadow 隔离坏基座，非种旧 scalar 军饷反事实；**不属本军饷结算退役类** |
| R5 | `ming_sim/flows.py` / `db.py` `is_substrate_hub_fiscal_engine_enabled` / `is_army_pay_source_cutover_enabled` | 命中 | **现役 hub/shadow 世界记录门**；军饷结算调用只在 hub 真分支。不在本票另造迁移删引擎门（#1889） |
| R6 | `test_pay_order_override_653.py::test_legacy_engine_pay_order_materialize_fails_loud_not_fulfilled` | 关 `__fiscal_engine` | **划出本类**：折发/物化拒收，非军饷 settle 双路 |
| R7 | `test_surcharge_causal_chain_650.py::test_legacy_fiscal_engine_rejects_surcharge_*` | 关引擎 | **划出本类**：加派消费边界，非军饷 settle |
| R8 | `test_fiscal_substrate_bridge.py::test_substrate_hub_dual_track_sanity_keeps_legacy_calc_as_reference` | 名含 legacy | **保留**：对照省级 calc 参考值，不是启用 `settle_legacy_army_pay` |

**完整性**：军饷 settle 退役双路与消费者 PATHS/fiscal_path 脚手架在 HEAD 为 0。不宣布「全仓一切 legacy 字样 / 一切 fiscal_engine 门」已删——那会越权扩到 #1889 与他域存档迁移。R5 保留依据供复裁核对；若归类错误仍由本票修复，不将已有全类授权推作需要另票。

---

## 聚焦测试（七环境变量前缀）

触及面 = 诊断 dump 案 + 军饷消费者/军心/士气案（复用原入口，未造新案；不全量）。

```bash
MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1901-fixer-evidence/focused \
  tests/test_deepseek_thinking_disable_1797.py \
  tests/test_run_agent_text_transport_1465.py \
  tests/test_mutiny_latch_315.py \
  tests/test_mutiny_progression_316.py \
  tests/test_mutiny_redemption_317.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_player_army_projection_321.py \
  tests/test_junxin_monthly_tick_314.py \
  tests/test_effect_origin_558.py \
  tests/test_army_salary_44.py
```

### 最终状态聚焦结果

```
........................................................................ [ 45%]
........................................................................ [ 91%]
..............                                                           [100%]
158 passed in 3.22s
real 3.88
user 2.63
sys 0.62
```

完整输出：`/tmp/1901-fixer-evidence/focused-out.txt`。复用原入口用例，未造新案；不全量。

---

## 说明

- 禁止 amend / stash / push / PR；不改席位或宿主配置。
- 自查二连：同类型（枚举谓词是否收窄）+ 引入 bug（是否把 shadow/adapter/他域 legacy 误删）。
- 不冒称三类均已「大理寺结清」；本回执只交机械枚举、成员处置与聚焦绿证据。
