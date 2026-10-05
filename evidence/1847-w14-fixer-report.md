# #1847 修内司 w14 纠正交卷 — 闲置/重复测试流程逐员清 + 类A全仓谓词

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w13-n11-n14-legacy-idle`
- 上一交卷：`6bd93c86c`（不 amend）
- 本轮纠正 commit：`3015b9ca5f29a796f0e968ef89e8374d42de4c94`
- 判词真源（末份）：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10a32-a35a-7e5a-9232-b51070108168@fixer/attachments/07-1847-judge-80aea7cd3.json` 末 payload
- 未结类别（只取末份全文，不另立更窄边界）：
  1. **旧兼容及退役残余闭包** — 沿选择器、执行分支、读写端、专属测试追清；退休后恒等包装随删；保留现役账本与新档接续；不改治理、不迁旧档、不加识别/拒收
  2. **重复或闲置测试流程** — 删无必要价值副本，复用真实入口；不洗白/不造平行抽象（「或」：闲置即删，不要求与已用 AST 同形）
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 stash / amend / rewrite / push / PR / 全量 / 真模型；未改 ADR/治理；未迁旧档；未加识别/拒收/证明测试
- 过程过失：w13 曾误 `git stash`（已 pop 记录）；**本轮未再 stash**

## 上一交卷自查缺陷（本轮纠正点）

1. `members_classified.tsv` 将 47 条 `idle_unused_helper` 合并 KEEP，理由「本轮只删同形闲置」——把用户「重复**或**闲置」收成 AND。须逐员读职责与调用：闲置即删；被用 fixture/替身须给消费者依据。
2. 类 A `SCAN_ROOTS`/`A_PATS` 仍偏财政人口点名词，未覆盖全仓受版本控制可执行代码，亦缺一般旧兼容/缺字段默认/迁移回填/读写端/专属测试/退役恒等谓词。
3. 扫描脚本偏大：本轮把枚举收成「`git ls-files` + 一条广义谓词 + AST 恒等包装/测试 helper」，不另造通用框架。

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
bash evidence/1847-w13-scans/enum_commands.sh
# 成员处置：evidence/1847-w13-scans/members_classified.tsv
# 复扫：evidence/1847-w13-scans/enum_post_w14.out
```

### 成员处置摘要

**类2（重复或闲置测试流程）**

| 处置 | 数量/成员 |
|---|---|
| FIX_DELETE | 51 条闲置 helper（原 47 + 级联 4：`_wait_for_pending_writes_to_drain` / `_resolve_decisions_via_stream` / `_army_single_bad_item` / `_choices_from_decisions`）。逐员：同文件无 Load、无 ImportFrom 消费者；同名命中均为他文件自有定义，不作免责 KEEP |
| FIX_REUSE_IMPORT | 19 组 AST 同形**已用**流程：删副本定义，从既有定义文件 import（不新建平行 helpers 模块；`_add_edge` 留在 `relation_brew` 以免与 faction 环依赖） |
| CLEAR | 复扫 `B_hits=0` |

**类1（旧兼容及退役残余闭包）**

| 处置 | 成员 |
|---|---|
| FIX_REMOVE_ALIAS | `IncompleteXiexangPayloadError.missing_fields`（无读者的兼容别名） |
| FIX_REMOVE_TEST | `test_old_save_schema_init_backfills_bandit_power_split`（锁已退役人物/leader 改写；案已红） |
| KEEP_ACTIVE_CONTENT_SYNC | `_migrate_character_identity_seed` / `_backfill_bandit_power_split` + 改名后的内容同步案：INSERT OR IGNORE 名册，非无标选引擎 |
| KEEP_ACTIVE_CLAMP / READ_DEFAULT | `monthly_amount`（去「旧调用点」措辞）；`normalize_appointment_tenure`（现役读端缺备兜底） |
| KEEP_EMPIRE_MODIFIERS | `sync_opening_legacies`（判词 conflicts） |
| KEEP_ACTIVE_TRANSPORT / API / HTTP | cli 参与人 heal；`expected_turn` 可选；非流式 `/api/decree/issue`（仍有同步 JSON 测试入口；UI 主路为 stream） |
| KEEP_EXCLUDED | `docs/`/`archive`/`evidence` 不入机械候选（治理/冻结史料） |
| KEEP_COMMENT | 「旧档…已退役」说明句机械命中，无活选择器 |

### 复扫

- 类2 idle + called_duplicate：**0**
- 类1 财政/军饷选择器、`calc_province_fiscal`、生产恒等包装：**功能命中 0**（与上轮一致）
- 类1 广义谓词仍有注释/现役 KEEP 行；逐员依据见 TSV，不以命中数宣称结清

## 修复要点

1. 闲置 helper：逐员核实后删除，禁止「非同形→KEEP」收窄。
2. 已用同形流程：优先删并 import 复用，不新增平行抽象。
3. 枚举改为 `git ls-files` 全仓可执行（py/ts/tsx/js）+ 一般 compat/migrate/backfill/缺省兼容谓词；排除 docs/archive/evidence/node_modules。
4. 清无读者兼容别名与旧档改写专属红案；内容名册同步与现役读端保留并给消费者依据。

## 聚焦测试

```bash
# 七变量前缀同上
BASETEMP=$(mktemp -d /tmp/1847-w14-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_month_chain_1847.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_pay_order_override_653.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_session_write_queue_1353.py \
  tests/test_junxin_monthly_tick_314.py \
  tests/test_advance_paths_atomic.py \
  tests/test_state_reload.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_mutiny_latch_315.py \
  tests/test_mutiny_progression_316.py \
  tests/test_mutiny_redemption_317.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_player_army_projection_321.py \
  tests/test_effect_origin_558.py \
  tests/test_qa_c2_phase_settlement_mask_1374.py \
  tests/test_bandit_power_model_190.py \
  tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py \
  tests/test_enter_settlement_period_1235.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_appointment_tenure_607.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_audience_background.py \
  tests/test_month_loop_tracer_1468.py
```

实测：`504 passed in 23.68s` → `evidence/1847-w13-scans/focused-pytest-w14.out`

`git diff --check`：触及文件 EOF 空白已修净。

## 变异真跑（可回放；非永久测试）

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w13-scans/mutation_probe.py \
  | tee evidence/1847-w13-scans/mutation-probe-w14.out
```

`MUTATION_PROBE_DONE PASS`（无标仍走 hub；装回旧选择器→legacy；人口恒等包装仍不存在）。

## 复杂度 / 不可拆理由

- **不可拆成「只删闲置」与「只扩枚举」两 commit**：成员表与复扫必须以同一 HEAD 的枚举脚本为准；先交 KEEP 收窄的表再扩谓词，会再次被自查打回「表谎言」。生产侧兼容别名/旧档专属红案与枚举谓词同一类 A 闭包，拆开会使复扫与处置表脱节。
- **未另造通用扫描框架**：只改既有 `enum_members.py` / `enum_commands.sh`（`git ls-files` + 单谓词 + AST）；未加插件式扫描器。
- 非流式颁诏口仍被多份同步 JSON 错路径案当作真入口；迁测删口会牵动 SSE 契约，超出本轮两类删简的最小切片，TSV 标 `KEEP_ACTIVE_HTTP_ENTRY` 并写明消费者，不假装已结。

## 自查二连 done

- 同类：类2 按「或」逐员删闲置 + 同形已用改 import；类A 全仓可执行枚举 + 一般谓词，保留项有消费者/判词依据，不以名字或引用数免责
- 引入：聚焦 504 绿；变异 PASS；diff --check 修净；无 stash/治理/迁移/拒收；无新平行抽象模块

## 剩余项

| 项 | 状态 |
|---|---|
| 类2 机械 idle/called_dup | 复扫 0 |
| 类1 广义注释/现役 KEEP | 见 TSV；非流式口等若续审要求删，需另迁测 |
| ADR/治理 | 未改 |
| 家族 merge / 全量 | 未声称；未跑全量 |
