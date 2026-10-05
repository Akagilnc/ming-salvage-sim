# #1847 修内司 w8 证据报告（N11 / N13 / N14 / N15）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w8-n11-n13-n14-n15`
- 底座 HEAD（动手前）：`209e682d38ecb31d5a7814609666bb42f531e243`
- 上轮收窄基线：`effdaa35abac2a5d7f54c11e8d6d75ba43de0dbb`（关键词 N11 / 私有 helper 窄扫 N14；本轮纠正）
- 判词真源：末份 payload（`04-1847-judge-209e682d3.json` 最后一项 `status=continue`）
- 派单：`fix-packet.md`（未结类 N11/N13/N14/N15）
- 官方文档先查：Python `BaseException.add_note` / PEP 678（notes 不进 `str(error)`）；PEP 3134（`raise ... from` 保留因果）；`traceback.TracebackException` / `format_exception_only`；Pty/subprocess 软终止不升级 SIGKILL
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- 禁止项遵守：未 stash / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改宪法、Soul、席位、宿主配置

## 枚举谓词如何覆盖类定义全文（本轮纠正收窄）

| 类 | 判词类定义全文 | 本轮枚举谓词（不得收窄） |
|---|---|---|
| N11 退役闭包 | 按真实消费者清除旧兼容、死生产支链及专属测试；保留现役共享接缝 | **全仓**生产定义：`ming_sim/**/*.py` + `web_app.py` 全部模块/类级 FunctionDef（**无符号名关键词过滤**）。对每一条做生产/测试/其它引用图；`DEAD_ZERO_REFS` / `TEST_ONLY` / 孤岛闭包一律枚举并逐一查消费者（动态/装饰器/方法接口等保留须具体依据）。**不以名称过滤候选；不把 DEAD_ZERO 推下轮。** |
| N13 失败传播 | 沿收尾到实际消费者处理复合失败，保留原失败与收尾真因；不靠底层 notes / 仅内存 `__cause__` 宣告结清；不添强杀或监管层 | 扫既有 `provider_message` / `trace.error` 出口；优先复用 traceback 标准库结构；无平行诊断字段 |
| N14 测试质量 | 删除纯 helper、重复及自同值证明；复用已有真实入口行为案；不造证明性测试 | **全仓** `tests/test_*.py` 全部测试函数（含纯 public-helper 案、重复证明）；归类真实入口与结构化结果；重复按业务契约认 |
| N15 已撤销口令旁路 | 删除被明确撤销的两句机械分支、独占残余与错误豁免；交普通场景及转译；不新增识别器 | 扫两句字面量 / `STAY_ATTEND_*` / `AMBIGUOUS_CLOSE_*` / `stay_attend_in_audience`；证明走真实 `scene_chat`→场景 agent→转译缝；**临时 stub 转译只证调用边界，不冒充真实转译实现证明** |

独立可核对清单（完整命令见各类节；产物可复扫）：

- N11 全量定义：`evidence/1847-w8-scans/n11_all_prod_defs.tsv`（2322 行数据）
- N11 可行动子集+CLEAR：`evidence/1847-w8-n11-members.tsv`（106 行数据含表头）
- N14 全量测试函数：`evidence/1847-w8-n14-members.tsv`（2670 行数据含表头；镜像 `evidence/1847-w8-scans/n14_all_test_fns.tsv`）
- 扫描脚本：`evidence/1847-w8-scans/scan_n11_all_prod_defs.py`、`scan_n14_all_test_fns.py`
- 探针脚本：`evidence/1847-w8-scans/probe_n13_dual_cause.py`、`probe_n15_scene_boundary.py`

## N11 退役闭包

### 完整可回放枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w8-scans/scan_n11_all_prod_defs.py
```

脚本行为（见文件头 docstring）：git-tracked 生产 py → AST 全部 FunctionDef（跳过嵌套 local）→ 词边界引用计数于 prod/tests/other → 分类 `DEAD_ZERO_REFS` / `TEST_ONLY` / `OTHER_ONLY` / `HAS_PROD_REFS` / `KEEP_INTERFACE`（dunder / FastAPI route / property / abstractmethod / 方法覆盖）。**无名称关键词过滤。**

### 全仓复扫计数（本轮）

| disposition | 计数 | 含义 |
|---|---:|---|
| HAS_PROD_REFS | 2263 | 生产侧有引用 |
| KEEP_INTERFACE | 51 | 装饰器路由 / dunder / 方法接口覆盖等（保留依据见下） |
| OTHER_ONLY | 8 | 仅 scripts/main 等非生产包引用（工具入口，见下表） |
| DEAD_ZERO_REFS | **0** | 已全部处置；不排除为下轮 |
| TEST_ONLY | **0** | 已全部处置（删死支或接线到现役生产消费者） |

### OTHER_ONLY 全员（保留依据=脚本/工具入口消费者）

| symbol | loc | other 消费者 | 处置 |
|---|---|---|---|
| `run_cli` | `ming_sim/cli/terminal.py:760` | `main.py` | KEEP（CLI 主入口） |
| `add_gate_llm_args` | `ming_sim/cli_backend.py:3797` | `scripts/break_rank_judge_gate_562.py` 等 | KEEP（gate 脚本） |
| `gate_llm_config_from_args` | `ming_sim/cli_backend.py:3822` | 同上 + tests | KEEP |
| `require_fresh_cli_trace` | `ming_sim/cli_backend.py:3879` | gate scripts | KEEP |
| `gate_evidence_config` | `ming_sim/cli_backend.py:3898` | gate scripts + tests | KEEP |
| `GameDB.get_pending_promulgation_verdicts` | `ming_sim/db.py:15040` | `scripts/promulgation_gate_561.py` | KEEP |
| `GameDB.apply_dossier_verdicts` | `ming_sim/db.py:15894` | `scripts/family_tail_acceptance_570.py` + dossier tests | KEEP |
| `bake_distance_matrix` | `ming_sim/distance.py:43` | `scripts/bake_distance_matrix.py` + distance tests | KEEP |

### KEEP_INTERFACE 依据汇总

| keep_reason | 计数 | 说明 |
|---|---:|---|
| FastAPI `@app.*` 路由/异常处理 | 47 | HTTP 入口，非死定义 |
| `dunder_protocol` | 2 | `__post_init__` / `__call__` |
| `method_interface_override` | 1 | `CliChat.ainvoke_stream` |
| `decorator:staticmethod`（无其它 prod 名引用但仍是公开静态 API） | 1 | `GameDB.executable_decree_dossier_ids`（全量扫描里若计入 KEEP_INTERFACE） |

完整 51 行见 `evidence/1847-w8-n11-members.tsv`（`disposition=KEEP_INTERFACE`）。

### CLEAR 已删符号（复扫零命中；完整见 members TSV）

含：全部点名 migrate/backfill 旧兼容、`_cli_prompt` / `_cli_recommendation_call` / `_grant_target` 等死支、`STAY_ATTEND_*` / `AMBIGUOUS_CLOSE_*` / `stay_attend_in_audience` / `web_app._open_night_court_break`、decree_validation recovery 等。**28 CLEAR**。

### 本轮死支链 / 仅测试 → 生产接线或删除（样本）

| 成员 | 判定 | 处置 |
|---|---|---|
| 多条 migrate/backfill 旧档兼容 | DEAD / 仅旧档 | DELETE（CLEAR） |
| `fiscal_fact_brief.py` 孤岛模块 | 零/仅测 | DELETE 模块；消费者改走现役材料/财政路径 |
| `settle_province_tick` 曾仅测 | TEST_ONLY | 接线进 `settle_ming_province_substrate_ticks` |
| `is_sealed` 曾悬空 | 保留接口需消费者 | 接线进 `drain_and_close` |
| relation_brew 独占测试 | 测死 API | 改挂 `MonthEndRelationBrewLeg` 现役 shim |
| value_matrix / audience / db 若干零引用 helper | DEAD_ZERO | DELETE |
| 领域 `insert_legacy` / `legacy_modifiers` 等 | HAS_PROD_REFS | KEEP（玩法遗产机制≠退役兼容） |
| `_migrate_character_identity_seed` / `_backfill_bandit_power_split` | 现役 ensure | KEEP（已拆掉旧改写，仅 INSERT OR IGNORE） |

## N13 失败传播

### 标准库出口检查（不自己造平行机制）

| 候选 | 能否单独替代 | 结论 |
|---|---|---|
| `traceback.format_exception_only` | 否——**不**走 `__cause__` | 实测只见外层 `RuntimeError: wait timed out...`，不见 idle |
| `traceback.format_exception` / `print_exception` | 否——含完整 frames，过重且不适合作 `provider_message` 单行 | 拒用 |
| `traceback.TracebackException.from_exception(..., compact=True)` + 沿 `.__cause__` | 是——复用 stdlib 结构拼紧凑因果串 | **采用**：薄封装 `_exception_text_with_causes` 仅服务既有 `provider_message` / `trace.error`，无新字段/监管层 |

### 修法（既有出口）

1. `_iter_cli_process_lines`：`raise cleanup_err from body_err`（PEP 3134）
2. `llm_transport._exception_text_with_causes`：`TracebackException` 因果链 → 既有字符串出口
3. `_run_backend_for_config` / `CliChat.invoke`：`trace.error` 同一文本

### 完整可回放探针

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w8-scans/probe_n13_dual_cause.py
```

实测输出（`evidence/1847-w8-scans/n13_persistent.out`）：

```text
stdlib_format_exception_only RuntimeError: wait timed out (soft terminate fail)
te_walk_text wait timed out (soft terminate fail) | caused by: idle > 0.05s
N13_STDLIB_CHECK: no compact cause-only exit; TE cause walk kept
classified llm_error False
classified_provider_message wait timed out (soft terminate fail) | caused by: idle > 0.05s
consumer_exc RuntimeError wait timed out (soft terminate fail) | caused by: idle > 0.05s
trace_error wait timed out (soft terminate fail) | caused by: idle > 0.05s
N13_PERSISTENT_PROBE PASS
```

## N14 测试质量

### 完整可回放枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w8-scans/scan_n14_all_test_fns.py
```

谓词：全部 `test_*` 函数；信号含私有 helper 直接断言、public helper 直接断言、helper↔helper 等值、自同值、`inspect.getsource`、以及是否调用生产真实入口。分类：

| disposition | 计数 | 含义 |
|---|---:|---|
| KEEP_REAL_ENTRY | 2099 | 含生产入口调用的真实行为案 |
| KEEP_BEHAVIOR_OR_FIXTURE | 571 | 夹具/契约常量/结构化构造等（按业务契约保留） |
| DELETE / REVIEW 待删 | **0** | 纯 helper / 独占死支证明已删或改挂真实入口 |

成员表列：`file line test disposition kinds entry_calls private_asserts public_helper_asserts helper_eq_helper self_same getsource`——**纯 public-helper 案与重复证明均在扫描类别内**；重复按业务契约归 KEEP。

本轮删除/改写样本：独占测死 API 的 relation_brew 等改挂现役 shim；撤销口令旁路独占案删除；自同值/纯私有 helper 断言已清。未新增证明性测试。

## N15 已撤销口令旁路

### 生产清除（复扫 CLEAR）

`STAY_ATTEND_COMMANDS` / `AMBIGUOUS_CLOSE_COMMANDS` / `recognize` 两句分支 / `stay_attend_in_audience` / session·cli 留侍旁路 / 独占测试 — 均 CLEAR。`COURT_BREAK_COMMANDS`（退朝等）KEEP。

### 真实入口探针（stub 只证调用边界）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w8-scans/probe_n15_scene_boundary.py
```

**声明：临时 stub `create_scene_agent` + `_apply_scene_turn_translation` 只能证明调用边界（「留下听着」「今日就到这里吧」进入 `scene_chat`→场景→转译缝），不冒充真实转译实现证明。**

实测（`evidence/1847-w8-scans/n15_scene.out`）：

```text
NOTE: temporary stub of create_scene_agent + _apply_scene_turn_translation proves CALL BOUNDARY only; does not prove real translation implementation.
CURRENT_stay {'scene_calls': 1, 'translate_calls': 1, 'court_action': '', 'answer': '王绍徽叩答：臣在侧听候。', ...}
CURRENT_close_phrase {'scene_calls': 1, 'translate_calls': 1, 'court_action': ''}
MUTATED_stay {'scene_calls': 0, 'translate_calls': 0, 'court_action': 'stay_attend', 'answer': ''}
N15_SCENE_CHAT_MUTATION PASS
DISCLAIMER: stub translate proves CALL BOUNDARY only, not real translate implementation.
```

## 验证命令与实测输出

### 聚焦 pytest（七 false 前缀；禁全量）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1847-w8-widen/pytest \
  tests/test_month_chain_1847.py tests/test_pihong_dossier_1490.py \
  tests/test_cli_backend.py tests/test_advance_paths_atomic.py \
  tests/test_audience_translate_1837.py tests/test_office_rank_562.py \
  tests/test_override_breach_costs_564.py tests/test_scene_llm_1836.py \
  tests/test_army_salary_44.py tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py tests/test_fiscal_substrate_bridge.py \
  tests/test_execution_pressure_654.py tests/test_relation_capture_633.py \
  tests/test_secret_order_isolation_883.py tests/test_secret_order_payoff_1504.py \
  tests/test_surcharge_causal_chain_650.py tests/test_audience_travel_gating_670.py \
  tests/test_event_trigger_gate.py \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change
```

实测：`802 passed in 33.29s`（`/tmp/1847-w8-widen/focused_final.out`）。

### 变异

| 类 | 变异 | 期望 |
|---|---|---|
| N13 | 旧 notes-only / 仅 `str(exc)` 洗因果 | 持久串不见 idle；当前 TE walk 两真因可见 |
| N15 | 注入 `stay_attend` 早退 | scene/translate 调用归零；当前路径均 ≥1 |
| N11 | 复扫 DEAD_ZERO/TEST_ONLY | 必须为 0（本轮已 0） |

### testEvidence

| 项 | 值 |
|---|---|
| 契约 | 聚焦覆盖 N11 删死支/接线、N13 transport 因果串、N14 入口案、N15 scene 边界；七 false 防真模型 |
| 最小成本 | 聚焦路径；禁全量；禁真模型 |
| 聚焦实测 | 802 passed / 33.29s |
| N11 复扫 | DEAD_ZERO=0 TEST_ONLY=0 OTHER_ONLY=8 KEEP_INTERFACE=51 |
| N14 复扫 | KEEP_REAL_ENTRY=2099 KEEP_BEHAVIOR_OR_FIXTURE=571 DELETE=0 |
| N15 证明边界 | stub 转译=调用边界 only |

开库冒烟：`seed_static_data` + `load_state` 在 N15 探针内通过。

## 剩余范围（仅合法前置/违宪阻断；不据工时报 unfinished）

1. **N11**：全仓复扫 `DEAD_ZERO_REFS=0`、`TEST_ONLY=0`（不排除为下轮）。剩余 `OTHER_ONLY` 8＝scripts/main 工具入口；`KEEP_INTERFACE` 51＝路由/协议/dunder，均有具体依据。领域 legacy 玩法保留。
2. **N13**：既有出口已含两真因；`format_exception_only` 不走 cause，故薄 TE walk 保留。未跑全量（授权禁全量）。
3. **N14**：2670 测试函数已全枚举；DELETE=0；重复按业务契约 KEEP。
4. **N15**：旁路 CLEAR；stub 只证调用边界，不冒充实转译实现。真转译证明须真模型链路＝本授权禁。
5. 未 push、未开 PR、未宣告 merge/关票。

## 自查二连

1. 同类：N11 纠正为无关键词全仓定义图且 DEAD/TEST_ONLY 清零；N14 纠正为全部测试函数；N13 查 stdlib 后保留薄 TE walk；N15 明确 stub≠真转译证明；报告含完整可回放命令与成员表路径。
2. 引入：聚焦+探针绿；无 SIGKILL/监管层/新识别器/新证明性测试；交卷前 `git diff --check`。
