# #1847 修内司 w13 纠正交卷 — 旧兼容退役闭包 + 闲置测试流程

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w13-n11-n14-legacy-idle`
- 上一交卷：`6c129bd93`（不 amend；本文件为独立纠正 commit）
- 判词真源（末份）：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10a32-a35a-7e5a-9232-b51070108168@fixer/attachments/07-1847-judge-80aea7cd3.json`
- 未结类别（只取末份全文，不另立更窄边界）：
  1. **旧兼容及退役残余闭包** — 沿选择器、执行分支、读写端、专属测试追清；退休后恒等包装随删；保留现役账本与新档接续；不改治理、不迁旧档、不加识别/拒收
  2. **重复或闲置测试流程** — 删无必要价值副本，复用真实入口；不洗白/不造平行抽象
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 amend / rewrite / push / PR / 全量 / 真模型；未改 ADR/治理；未迁旧档；未加识别/拒收/证明测试
- 过程过失：曾误执行一次 `git stash push` 探测 HEAD，随即 `git stash pop` 恢复；工作树内容未丢。此后未再 stash。

## 上一交卷自查缺陷（本轮纠正点）

1. 将 `__army_pay_source_cutover` 保留理由写成「本轮对象是财政引擎分流 / 若后续判词再扫」——自行收窄两类全仓边界。真实职责：无标→`False`=旧档军饷流（docstring 原文 *existing saves stay on legacy*），与 `__fiscal_engine` 同形选择器+平行门。
2. `enum_members.py` A_PATS 双转义错误，且仅扫 `ming_sim/tests` 点名词，非类定义全文谓词。
3. 类2 扫描偏「无引用 helper」假阳性，未优先抓「与已用流程 AST 同形的闲置副本」。
4. 报告称 `git diff HEAD^ HEAD --check` 无输出，但实际有报告第93行与 `members_pre.tsv` 尾部 tab trailing whitespace。
5. 变异探针未 seed、`has_qiyun` 对未 seed 库为 False，且用手工 stub 冒充旧 `compute_budget_lines`；缺可回放脚本。

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
bash evidence/1847-w13-scans/enum_commands.sh
# 成员处置：evidence/1847-w13-scans/members_classified.tsv
# 复扫：evidence/1847-w13-scans/enum_post.out
```

### 成员处置摘要

**类1**

| 处置 | 成员 |
|---|---|
| FIX_REMOVE | `__fiscal_engine` 选择器与 `calc_province_fiscal`（上轮） |
| FIX_REMOVE | `__army_pay_source_cutover` / `is_` / `_mark_` 选择器与写标（本轮） |
| FIX_UNWRAP | 军饷 cutover-off 平行门与 flows shadow 隔离；恒走分源脊 |
| FIX_DROP_MARKER | mutiny/player/effect 夹具写标与 cutover(0,1) 矩阵 |
| FIX_REMOVE_TEST | `test_legacy_economy_ledger_origin_backfill_*`（旧档 DROP 列回填专属案） |
| FIX_INLINE_DELETE | 人口恒等包装（上轮） |
| KEEP_ACTIVE_LEDGER | substrate hub 预算/入库 + `_initialize_army_pay_source_spine` 新档 seed |
| KEEP_EMPIRE_MODIFIERS / KEEP_ADR_UNTOUCHED | 判词明示 / 治理不改 |
| KEEP_TEST_DOUBLE | `directive_payload return row` 测试替身透传（非退役空壳） |

**类2**

| 处置 | 成员 |
|---|---|
| FIX_DELETE | travel `_run_exclusive` 等闲置（上轮）+ qa_c2 闲置 `_null_cm`（与 month_open 同形） |
| KEEP_USED | write_queue `_run_exclusive`；month_open `_null_cm` |
| KEEP_NOT_DUPLICATE_FLOW | enum 机械「无引用 helper」47 条：非 AST 同形闲置流程，不按引用数清扫 |

### 复扫

- 类1 选择器/旧算/cutover 门/专属旧档回填：**功能命中 0**（余 1 条 KEEP_TEST_DOUBLE）
- 类2 AST 同形闲置副本：**0**；机械无引用 helper 不作为结清障碍

## 修复要点

1. 删除军饷 cutover 选择器；运行时恒走分源账本；保留新档 spine seed。
2. 卸 cutover-off owner 旁路、shadow 隔离与字段门；夹具停止写标。
3. 删除旧档 `origin_ref` 回填专属测试；删除 qa_c2 闲置同形 `_null_cm`。
4. 重写全仓枚举谓词与可回放变异脚本（自 `80aea7cd3` 提取旧逻辑）。

## 聚焦测试

```bash
# 七变量前缀同上
BASETEMP=$(mktemp -d /tmp/1847-w13c-pytest-XXXXXX)
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
  tests/test_qa_c2_phase_settlement_mask_1374.py
```

实测：`413 passed in 21.55s` → `evidence/1847-w13-scans/focused-pytest-corr.out`

`git diff --check`：本轮触及文件修净后无输出（对照上一 commit 的 trailing whitespace 已更正陈述）。

## 变异真跑（可回放；非永久测试）

```bash
# 七变量 + PYTHONPATH 同上
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w13-scans/mutation_probe.py \
  | tee evidence/1847-w13-scans/mutation-probe.out
```

要点（真实 seed + `apply_fixed_period_flows` / `compute_budget_lines`；旧逻辑自 `git show 80aea7cd3` 提取）：

- CURRENT 新档：预算与流水均有 `起运`；无 `__fiscal_engine` / `is_army_pay_source_cutover_enabled`；删标重开仍 hub。
- MUTATED 装回旧 `fiscal_engine`+`calc_province_fiscal`/`compute_budget_lines`：无标→`legacy`；预算 `田赋辽饷盐商`。
- MUTATED 装回旧军饷选择器：无标→`enabled False`；恢复后选择器不存在。
- 人口恒等包装：当前不存在；进程内恒等形状可对照；恢复后不存在。
- `MUTATION_PROBE_DONE PASS`

## 复杂度

- 生产：删军饷选择器与 cutover-off 平行门；保留现役 spine seed / hub 账本
- 测试：去写标与旧档回填专属案、删同形闲置 `_null_cm`；无新机制/拒收/证明测试

## 自查二连 done

- 同类：按判词类定义全文谓词枚举（选择器/分支/读写/专属测试/恒等包装/同形闲置流程）；army_pay 按真实旧档分流职责处置，非范围例外说明
- 引入：聚焦 413 绿；变异可回放 PASS；diff --check 修净；无治理/迁移/拒收；误 stash 已 pop 并记录

## 剩余项

| 项 | 状态 |
|---|---|
| 本轮两类 | 军饷选择器闭包与同形闲置已按职责清；复扫无功能选择器残留 |
| ADR0021 历史条文 | 未改（治理） |
| enum 机械无引用 helper 47 | 非同形闲置流程；未按引用数清扫 |
| 家族 merge / 全量 | 未声称；未跑全量 |
