# #1847 修内司 w13 交卷 — 旧兼容退役闭包 + 闲置测试流程

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w13-n11-n14-legacy-idle`（自 `80aea7cd3` 新开）
- 判词真源（末份 payload）：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10a32-a35a-7e5a-9232-b51070108168@fixer/attachments/07-1847-judge-80aea7cd3.json`
- 未结类别（只取末份）：
  1. **旧兼容及退役残余闭包**（N11-R5）
  2. **重复或闲置测试流程**（N14-R4）
- 票面：`gh issue view 1812/1847`（#1812 重构验收第1项；#1847 旧档专属路径退役；Out of Scope 不授权删既存存档）
- 互联网资料：SQLite/legacy path 删除先例（pluts 绿场删兼容迁移）；Python 恒等包装应 inline 后删除（redundant-wrappers 指南）
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`
- 禁止项：未 stash / amend / rewrite / push / PR / 全量 / 真模型；未改 ADR/治理；未迁旧档；未删既存存档；未加识别/拒收/监管/抽象/证明测试

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
# 谓词覆盖票面/判词类定义全文（选择器·执行分支·读写端·专属测试·恒等包装 /
# 闲置或同形无消费者测试流程），不限点名符号
bash evidence/1847-w13-scans/enum_commands.sh
# 成员处置表：evidence/1847-w13-scans/members_classified.tsv
# 复扫：evidence/1847-w13-scans/enum_post.out / members_post.tsv
```

### 成员处置摘要

完整表见 `evidence/1847-w13-scans/members_classified.tsv`（含保留依据）。

**类1 旧兼容及退役残余闭包**

| 处置 | 成员 |
|---|---|
| FIX_REMOVE | `fiscal_engine` / `_FISCAL_ENGINE_*` / `_mark_substrate_hub_*` 选择器与写标 |
| FIX_REMOVE | `calc_province_fiscal` 及旧固定税收 helper 闭包 |
| FIX_UNWRAP | flows/db/issues/displaced_population/pay_order 上 hub/legacy 平行门 |
| FIX_INLINE_DELETE | `_content_population_effect_for_save` 恒等包装及 7 处调用 |
| FIX_REMOVE_TEST | dual-track / legacy reject / `_disable_*` shadow 隔离专属案 |
| KEEP_ACTIVE_LEDGER | substrate hub 预算·入库·军饷现役账本 |
| KEEP_EMPIRE_MODIFIERS | `legacy_modifiers` 帝国修正（判词明示非旧档兼容） |
| KEEP_ADR_UNTOUCHED | ADR0021 等治理文件未改 |
| KEEP_ARMY_PAY_CUTOVER | `__army_pay_source_cutover` 军饷脊保留（本轮对象是财政引擎分流） |

**类2 重复或闲置测试流程**

| 处置 | 成员 |
|---|---|
| FIX_DELETE | `test_audience_travel_gating_670._run_exclusive`（闲置同形副本） |
| FIX_DELETE | `test_junxin_monthly_tick_314._run_months`（全仓无引用） |
| FIX_DELETE | advance/state_reload 闲置 `_ledger_count`；mutiny 闲置 `_pop/_global_population` |
| KEEP_USED | `test_session_write_queue_1353._run_exclusive` 真实队列案 |
| KEEP_IMPORTED | conftest/`section_rejection_helpers` 跨文件 import（复扫假阳性，非闲置） |

### 复扫

- 类1 功能命中（选择器/旧算/专属旧引擎测试/恒等包装）**= 0**（`CLEAR_A_functional True`）
- 类2 闲置同形/闲置流程删除候选 **= 0**；仅余 2 条 KEEP_IMPORTED
- 未为扫描新增生产消费者或证明测试

## 修复要点

1. 删除 `__fiscal_engine` 选择器：无标/缺标不再落入 legacy；预算与固定财政恒走 substrate hub。
2. 删除 `calc_province_fiscal` 旧税收闭包及专属 shadow/legacy 测试。
3. 卸掉加派/流民入池/偿还序上的 legacy 平行门；不另造拒收层。
4. 人口换算恒等包装 inline 删除。
5. 删除闲置测试流程副本；复用既有 write-queue 真实入口案。

## 聚焦测试

```bash
# 七变量前缀同上
BASETEMP=$(mktemp -d /tmp/1847-w13-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_month_chain_1847.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_pay_order_override_653.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_session_write_queue_1353.py \
  tests/test_population_unit_648.py \
  tests/test_junxin_monthly_tick_314.py \
  tests/test_advance_paths_atomic.py \
  tests/test_state_reload.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_qa_e1_numeric_presentation.py
```

实测：`340 passed in 18.68s`（real ~19.09s）→ `evidence/1847-w13-scans/focused-pytest.out`  
`git diff --check`：无输出。未跑全量。

## 变异真跑（临时入口探针，非新增证明测试）

`evidence/1847-w13-scans/mutation-probe.out`：

- CURRENT 新档预算收入：`起运/盐税/商税`；删 `__fiscal_engine` 后重开仍同。
- MUTATED 装回旧 `fiscal_engine`：无标→`legacy`；预算走 `田赋辽饷盐商`。
- CURRENT `_content_population_effect_for_save` 不存在；MUTATED 恒等包装 `is` 原对象；恢复后仍不存在。
- 探针临时目录已清理。

## 复杂度

- 触及 20 文件：`+233 / -776`（净删约 543 行）
- 删选择器+旧算闭包+平行门+闲置测试；无新机制/适配/拒收/证明测试

## 自查二连 done

- 同类：两类按票面全文谓词枚举→逐成员处置→复扫；点名样本非白名单
- 引入：聚焦 340 绿；变异对照；无治理改动；无存档删除；无 stash/amend/push

## 剩余项

| 项 | 状态 |
|---|---|
| 本轮两类 | 生产闭包与闲置副本已清；复扫仅 KEEP |
| `__army_pay_source_cutover` 军饷脊 | 保留；若后续判词并入同类再扫 |
| ADR0021 历史旧档例外条文 | 未改（治理） |
| 家族 merge / 全量 | 未声称；未跑全量 |
