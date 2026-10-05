# #1847 修内司 w8 证据报告（N11 / N13 / N14 / N15）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w8-n11-n13-n14-n15`
- 底座 HEAD（动手前）：`209e682d38ecb31d5a7814609666bb42f531e243`
- 本轮续修基线：`8a67279c52e89ddeabce3887e6230020325e2dd4`（上轮报告谓词过窄，本轮纠正）
- 判词真源：末份 payload（`04-1847-judge-209e682d3.json` 最后一项 `status=continue`）
- 派单：`fix-packet.md`（未结类 N11/N13/N14/N15）
- 官方文档先查：Python `BaseException.add_note` / PEP 678（notes 不进 `str(error)`）；PEP 3134（`raise ... from` 保留因果）；Pty/subprocess 软终止不升级 SIGKILL
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- 禁止项遵守：未 stash / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改宪法、Soul、席位、宿主配置

## 枚举谓词如何覆盖类定义全文

| 类 | 判词类定义全文 | 本轮枚举谓词（不得收窄） |
|---|---|---|
| N11 退役闭包 | 按真实消费者清除旧兼容、死生产支链及专属测试；保留现役共享接缝 | 全仓 AST 枚举 `ming_sim/**`+`web_app.py` 全部 FunctionDef；对名称/限定名含 migrate/backfill/legacy/compat/recovery/stay_attend/ambiguous/secret_order_assignee/grant_target/cli_prompt/recommendation/court_break 等关键词者，及全部 `_migrate_*`/`_backfill_*`，做生产+测试引用图；按行为分类：仅旧档兼容 / 现役初始化 ensure / 现役共享消费者 / 领域「遗产」机制（非退役）/ 死零引用 / 仅测试。开库自调用**不**自动算现役共享——须读函数体判定。能拆则拆、能删则删 |
| N13 失败传播 | 沿收尾到实际消费者处理复合失败，保留原失败与收尾真因；不靠底层 notes / 仅内存 `__cause__` 宣告结清；不添强杀或监管层 | 扫 `_iter_cli_process_lines` 软终止、`raise ... from`、`classify_transport_failure`、`run_with_transport`、`_run_backend_for_config`/`CliChat.invoke` 的既有 `trace.error` / `provider_message` 出口；探针必须落到持久 `trace.error` 字符串含两真因 |
| N14 测试质量 | 删除纯 helper、重复及自同值证明；复用已有真实入口行为案；不造证明性测试 | 全仓 `tests/test_*.py` AST：`inspect.getsource`、helper↔helper 等值、生产私有 helper 直接断言、`"k": row["k"]` 自同值字典、before/after 不变式；语义分类 KEEP_PAYLOAD / KEEP_TEST_FIXTURE / DELETE_* |
| N15 已撤销口令旁路 | 删除被明确撤销的两句机械分支、独占残余与错误豁免；交普通场景及转译；不新增识别器 | 扫两句字面量 / `STAY_ATTEND_*` / `AMBIGUOUS_CLOSE_*` / `stay_attend_in_audience`；**证明**必须走真实 `scene_chat`→场景 agent→`_apply_scene_turn_translation`，不只 `recognize_audience_command` |

独立可核对清单：

- N11：`evidence/1847-w8-n11-members.tsv`（58 行含表头）
- N14：`evidence/1847-w8-n14-members.tsv`（643 行含表头；处置计数见下）

## N11 退役闭包

### 枚举命令

```bash
# 全仓 AST FunctionDef + 关键词/_migrate_/_backfill_ 引用图
# 七变量前缀 + PYTHONDONTWRITEBYTECODE=1 + PYTHONPATH=$PWD
# /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python <<'PY'  （内联 AST/引用扫描）
# 产出写入 evidence/1847-w8-n11-members.tsv；命令轨迹 /tmp/1847-w8-rework/
```

### 处置摘要（完整行见 TSV）

| disposition | 计数 | 含义 |
|---|---:|---|
| CLEAR | 29 | 已删符号复扫零命中（含上轮点名 + 本轮续删） |
| KEEP_ACTIVE_ENSURE | 2 | `_migrate_character_identity_seed` / `_backfill_bandit_power_split`：拆掉旧兼容改写，仅留 `INSERT OR IGNORE` 现役 ensure |
| KEEP_LIVE_SHARED | 1 | `_backfill_healed_participant_refs`：cli_backend 现役调用 |
| KEEP_DOMAIN_LEGACY | 17 | 领域「遗产」机制（`insert_legacy` / `legacy_modifiers` 等），不是退役兼容闭包 |
| KEEP_LIVE | 8 | 其它有生产消费者的 live 符号（含 humanize_legacy 呈现等） |

### 本轮按行为拆/删的旧兼容与死支链（样本≠白名单；谓词覆盖后的成员）

| 成员 | 行为判定 | 处置 |
|---|---|---|
| `_backfill_salary_rate` + 开库 gate + 3 专属测试 | 仅 salary_rate 列首次 ADD 旧档回填；新 CREATE 已含列，新军走 coerce/army_needed | DELETE |
| `_migrate_arrears_unit_to_silver` | version 门控旧分数→万两 | DELETE |
| `_migrate_building_logs_to_durable_audit` | CREATE 已无 FK；仅旧表有 FK 时 reshape | DELETE |
| `_migrate_next_audience_todos_drop_issue_fk` | CREATE 已无 issues FK；仅旧表 | DELETE |
| `_migrate_character_location_aliases` | 旧别名→canonical | DELETE |
| `_backfill_person_core_character_static_fields` | 旧空字段补丁 | DELETE |
| `_backfill_event_triggers_from_event_pool_issues` | legacy issues→triggers | DELETE |
| `_migrate_offsets_to_float_precision` | 旧 offset 精度一次修 | DELETE |
| `_migrate_missing_fiscal_engine_from_pay_source_cutover` | 旧 cutover 缺 key 补丁 | DELETE |
| `_migrate_character_identity_seed` | 混有 INSERT OR IGNORE + 旧 identity/别名补丁 | 拆：只留 ensure |
| `_backfill_bandit_power_split` | 混有 INSERT OR IGNORE + 旧 leader/power_id 改写 | 拆：只留 ensure |
| `_cli_prompt` / `_cli_stream_safe_prefix` / `_cli_recommendation_call` + consts | 死生产定义，零消费者 | DELETE |
| `_grant_target` | 死生产定义 | DELETE |
| `_is_audience_chat_shared_channel` / `_is_active_secret_order_assignee` | 死/仅测试 | DELETE + 去掉独占断言 |
| `web_app._open_night_court_break` | 死方法 | DELETE |
| 上轮已 CLEAR：severity 迁移、break_rank 回填、decree_validation_*、stay/ambiguous 旁路 | — | 维持 CLEAR |

复扫：上述 DELETE 符号在生产+测试非注释命中 = **CLEAR**（见 TSV）。

### 授权边界

- 保留：现役 ensure（名册/流寇 powers）、`_backfill_healed_participant_refs`、领域遗产机制、`api_secret_orders` HTTP 路由（有装饰器出口，非死定义）、0055/案头/中旨现役接缝。
- 不在本轮以「文件名含 legacy」误删遗产玩法。
- 其它 DEAD_ZERO 私有函数若非本类关键词谓词命中且无退役证据，未作一律清场（见「剩余范围」）。

## N13 失败传播

### 根因

软终止失败若只 `add_note` 或仅内存 `__cause__`，则：

1. `str(error)` / 旧 `provider_message` 看不到 notes（PEP 678）
2. `run_with_transport` 按可重试 idle 再成功 → `trace.error=null`，收尾真因被洗掉
3. 即便 `raise cleanup from idle`，若 trace 仍 `error=str(exc)`，持久包仍可能只见 TimeoutError 一层

### 修法（复用现有出口，不加字段/监管/重试层）

1. `_iter_cli_process_lines`：`raise cleanup_err from body_err`（PEP 3134）
2. `llm_transport._exception_text_with_causes`：把因果链写入既有 `provider_message` / `ClassifiedFailure.message`
3. `_run_backend_for_config` / `CliChat.invoke`：既有 `trace.error` 改写为同一因果链文本

### 实测探针（持久包）

命令：七变量 + `PYTHONPATH=$PWD` 跑 `/tmp/1847-w8-rework` 内联探针（输出存 `n13_persistent.out`）。

```text
classified llm_error False
classified_provider_message wait timed out (soft terminate fail) | caused by: idle > 0.05s
consumer_exc TimeoutError wait timed out (soft terminate fail) | caused by: idle > 0.05s
runner_exc TimeoutError
runner_exc_text wait timed out (soft terminate fail) | caused by: idle > 0.05s
trace_error wait timed out (soft terminate fail) | caused by: idle > 0.05s
N13_PERSISTENT_PROBE PASS
```

### 变异（临时，旧 notes 路径 vs 当前）

```text
OLD_washed ok ['llm_idle_timeout', 'ok'] first_msg idle > 0.05s
NEW_surfaces TimeoutError attempts 1 text wait timed out (soft terminate fail) | caused by: idle > 0.05s
NEW_classified llm_error False wait timed out (soft terminate fail) | caused by: idle > 0.05s
```

## N14 测试质量

### 枚举命令

全仓 `tests/test_*.py` AST 扫描 → `evidence/1847-w8-n14-members.tsv`。

### 处置计数（复扫后）

| disposition | 计数 |
|---|---:|
| KEEP_TEST_FIXTURE_HELPER | 563 |
| KEEP_PAYLOAD_CONSTRUCTION | 78 |
| KEEP_BEFORE_AFTER_INVARIANT | 1 |
| DELETE_* | 0 |

### 本轮删除/改写的证明性成员

| 成员 | 处置 |
|---|---|
| `test_leverage_multiplier_uses_canonical_office_rank_table_only`（上轮） | DELETE |
| `test_one_tokenizer_...`（上轮） | DELETE |
| `test_person_delta_adapter` 自同值 `reason_code: old_row["reason_code"]`（上轮） | 改为操作前 `before_reason` |
| `test_recognizable_archive_title_...` 内 `_is_substantive_office` 纯 helper 断言 | DELETE 该断言；保留 dossier 入口行为断言 |
| 宽扫 `"id": row["id"]` 等 | KEEP_PAYLOAD_CONSTRUCTION |
| 测试夹具 `_snapshot`/`_sat` 等 | KEEP_TEST_FIXTURE_HELPER |

未新增证明性测试。

## N15 已撤销口令旁路

### 生产清除（维持/复扫）

| 成员 | 处置 |
|---|---|
| `STAY_ATTEND_COMMANDS` / `AMBIGUOUS_CLOSE_COMMANDS` | DELETE |
| `recognize_audience_command` 两句分支 | DELETE |
| `stay_attend_in_audience` / `TAG_STAY_ATTEND` / `CMD_*` | DELETE |
| `session` 留侍／含糊早退 | DELETE |
| `cli/terminal` 留侍旁路 | DELETE |
| `test_scene_stay_attend_...` | DELETE |
| `human_n6.tsv` 误列 | `DELETE_REVOKED_COMMAND_BYPASS` |
| `COURT_BREAK_COMMANDS`（退朝等） | KEEP |

### 真实入口变异（非 recognize-only）

入口：`GameContent.load`→`seed_static_data`→`scene_chat`；桩 `create_scene_agent` + `_apply_scene_turn_translation`（临时，不落库为证明测试）。

```text
CURRENT_stay {'scene_calls': 1, 'translate_calls': 1, 'court_action': '', 'answer': '王绍徽叩答：臣在侧听候。', 'scene_prompt': ['留下听着'], 'translate_message': '留下听着'}
CURRENT_close_phrase {'scene_calls': 1, 'translate_calls': 1, 'court_action': ''}
MUTATED_stay {'scene_calls': 0, 'translate_calls': 0, 'court_action': 'stay_attend', 'answer': ''}
N15_SCENE_CHAT_MUTATION PASS
tmpdir_cleaned True
```

「留下听着」「今日就到这里吧」当前均进入普通场景+转译；旧旁路变异则 scene/translate 皆 0。

## 验证命令与实测输出

```text
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1847-w8-rework/pytest \
  tests/test_month_chain_1847.py tests/test_pihong_dossier_1490.py \
  tests/test_cli_backend.py tests/test_advance_paths_atomic.py \
  tests/test_audience_translate_1837.py tests/test_office_rank_562.py \
  tests/test_override_breach_costs_564.py tests/test_scene_llm_1836.py \
  tests/test_army_salary_44.py \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change
```

输出：`231 passed in 12.46s`；墙钟约 `ELAPSED_SEC=13`（未跑全量）。

### testEvidence（本轮修复记录）

| 项 | 值 |
|---|---|
| 契约 | 聚焦文件覆盖 N11 删迁移/死支、N13 transport/trace、N14 office_rank、N15 scene_chat/translate；七 false 防真模型 |
| 最小成本 | 聚焦 10 个路径 / 单测点名 1；禁全量 |
| 实测耗时 | pytest 12.46s；墙钟 ~13s；N13 持久探针 <1s；N15 scene 探针 ~1.8s |

开库冒烟（删迁移后）：`seed_ok 1627 10 chars 111`。

## 剩余范围 / 据实未结项

1. **N11**：关键词谓词外仍可能存在其它死私有函数（AST `DEAD_ZERO_REFS` 宽扫曾列出大量模块内私有 helper）。本轮只清退役兼容/点名闭包/零消费者死支；未宣称「全仓一切死代码结清」。
2. **N11 KEEP_DOMAIN_LEGACY**：遗产玩法保留；若未来按 #1812 整废「遗产」机制，须另轮按玩法票面裁，不在本 N11 退役闭包偷换。
3. **N14**：全仓枚举后 DELETE 类已空；夹具 helper / 载荷构造 KEEP。不排除其它文件存在未入谓词的盯文案——本轮谓词已覆盖判词定义的三类（纯 helper / 重复自同 / 自同值），未另造证明测试。
4. **N13**：持久 `trace.error` 与 `provider_message` 已含两真因；未新增平行诊断字段。未跑全量 transport 全家桶。
5. **N15**：scene_chat→场景→转译已证；其它合法固定口令（退朝等）保留。未改 ADR/宪法；N6 本轮判词不重送。
6. 未 push、未开 PR、未宣告 merge/关票。

## 自查二连

1. 同类：四类均按判词定义全文重枚举；N11 不以开库调用冒充现役共享；N13 查到持久 trace；N15 查到 scene_chat 入口；N14 全仓 AST。
2. 引入：聚焦 231 绿；开库 seed 冒烟通过；无 SIGKILL/监管层/新识别器/新证明性测试；报告无 trailing whitespace（交卷前 `git diff --check`）。
