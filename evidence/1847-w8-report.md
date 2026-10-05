# #1847 修内司 w8 证据报告（N11 / N13 / N14 / N15）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w8-n11-n13-n14-n15`
- 底座 HEAD（动手前）：`209e682d38ecb31d5a7814609666bb42f531e243`
- 判词真源：末份 payload（`04-1847-judge-209e682d3.json` 最后一项 `status=continue`）
- 派单：`fix-packet.md`（未结类 N11/N13/N14/N15）
- 官方文档先查：Python `BaseException.add_note` / PEP 678（notes 不进 `str(error)`）；PEP 3134（`raise ... from` 保留因果）；Pty/subprocess 软终止不升级 SIGKILL
- 环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`
- 禁止项遵守：未 stash / amend / rewrite / push / PR / SIGKILL / 全量 / 真模型；未改宪法、Soul、席位、宿主配置

## 枚举谓词如何覆盖类定义全文

| 类 | 判词类定义全文 | 本轮枚举谓词（不得收窄） |
|---|---|---|
| N11 退役闭包 | 按真实消费者清除旧兼容、死生产支链及专属测试；保留现役共享接缝 | 全仓扫 `_migrate_*` / `_backfill_*` / `compose_decree_validation_recovery` / `decree_validation_failure`；对每个符号做生产+测试引用图；**无真实消费者或仅旧档兼容+专属测试 → DELETE**；**现役共享写/读口 → KEEP** |
| N13 失败传播 | 沿收尾到实际消费者处理复合失败，保留原失败与收尾真因；不靠底层 notes 存在就宣告结清；不添强杀或监管层 | 扫 `add_note` / soft terminate / `classify_transport_failure` / `run_with_transport` 消费链；探针：idle+收尾失败后重试成功是否洗掉真因 |
| N14 测试质量 | 删除纯 helper、重复及自同值证明；复用已有真实入口行为案；不造证明性测试 | 扫 `inspect.getsource`、helper↔helper 等值、`reason_code: old_row["reason_code"]` 自同值；对照既有任命/行为案 |
| N15 已撤销口令旁路 | 删除被明确撤销的两句机械分支、独占残余与错误豁免；交普通场景及转译；不新增识别器；不一刀切其它合法口令 | 扫 `留下听着` / `今日就到这里吧` / `STAY_ATTEND_*` / `AMBIGUOUS_CLOSE_*` / `stay_attend_in_audience`；保留 `COURT_BREAK`（退朝等） |

完整成员表：`evidence/1847-w8-n11-members.tsv`（N11）；N13/N14/N15 见下节。

## N11 退役闭包

### 枚举命令

```bash
rg -n --glob '*.py' '_migrate_legacy|_backfill_proposed|compose_decree_validation_recovery|decree_validation_failure'
# 另：全仓符号引用图（临时 /tmp/1847-w8-probe/enum_n11.py）
```

### 完整成员表与处置

| 成员 | 处置 | 理由 |
|---|---|---|
| `db._migrate_legacy_reaction_severity` + `_migrate_reaction_value` | DELETE | 仅开库自调用；旧 severity→direction/intensity 兼容 |
| `db._backfill_proposed_appointment_break_ranks` | DELETE | pre-#562 回填；新写入已在 `create_decree_dossier` 产 `break_rank` |
| `cli_backend.compose_decree_validation_recovery` | DELETE | 定义无任何生产调用 |
| `session.ChatTurnResult.decree_validation_failure` + `web_app` 空投影 | DELETE | 无生产赋值；前端零消费者 |
| 专属测试 `test_existing_proposed_appointment_...backfill` | DELETE | 维护退役残余 |
| 专属测试 `test_legacy_persisted_reaction_severity_...` | DELETE | 维护退役迁移 |
| 其余开库 `_migrate_*` / `_backfill_*`（薪饷、财政单位、人物种子、贼势拆分等） | KEEP | 现役 schema/substrate 共享接缝；`person_write_inventory` / `army_pay` 仍引用；`_backfill_healed_participant_refs` 有现役调用 |

### 复扫

修后生产+测试对 DELETE 符号命中 = **CLEAR**（见 `/tmp/1847-w8-verify/rescan.out`）。

## N13 失败传播

### 根因

软终止失败曾 `body_err.add_note(...)` 后仍抛出 `TransportIdleTimeout`。`str(error)` / `classify_transport_failure` 看不到 notes（官方 PEP 678）；`run_with_transport` 按可重试 idle 再试成功 → `trace.error=null`，收尾真因被洗掉。

### 修法（最简现成方案）

收尾失败时 `raise cleanup_err from body_err`（PEP 3134 因果链）。复合失败不再是纯 idle，分类为不可重试 `llm_error`，消费者立刻看见 TimeoutError，`__cause__` 保留原 idle。不添监管、重试层、平行诊断字段、不恢复 SIGKILL。

### 反馈环

修前探针：`N13_PROBE FAIL`（成功且 `provider_message='idle > 0.05s'`，notes 丢失）。  
修后探针：`raised TimeoutError cause TransportIdleTimeout`；consumer 首次即上浮，`N13_PROBE PASS`。

### 变异

- 旧路径（idle+add_note）：`washed_success=True`，attempts=`llm_idle_timeout, ok`
- 新路径（raise from）：`surfaces_composite=True`，首次失败不上第二 attempt 成功

## N14 测试质量

| 成员 | 处置 |
|---|---|
| `test_leverage_multiplier_uses_canonical_office_rank_table_only`（helper↔helper） | DELETE |
| `test_one_tokenizer_splits_concurrent_offices_by_formal_separators_only`（tokenizer/内部 band） | DELETE |
| `test_person_delta_adapter` 自同值 `reason_code: old_row["reason_code"]` | 改为操作前采样 `before_reason` 再断言（真实 before/after） |
| 宽扫命中的 fixture 字典 `"id": row["id"]` 等 | KEEP；属构造载荷，非自同值证明 |

未新增证明性测试；任命行为案仍在 `test_office_rank_562` / `test_faction_leverage_9`。

## N15 已撤销口令旁路

| 成员 | 处置 |
|---|---|
| `STAY_ATTEND_COMMANDS` / `AMBIGUOUS_CLOSE_COMMANDS` | DELETE |
| `recognize_audience_command` 两句分支 | DELETE |
| `stay_attend_in_audience` / `TAG_STAY_ATTEND` / `CMD_STAY_ATTEND` / `CMD_AMBIGUOUS_CLOSE` | DELETE（独占闭包） |
| `session` 留侍／含糊早退 + `_ambiguous_close_confirm_cue` | DELETE |
| `cli/terminal` 留侍旁路 | DELETE |
| `test_scene_stay_attend_...` | DELETE |
| `human_n6.tsv` 误列 `KEEP_FORM_LANGUAGE` | 改为 `DELETE_REVOKED_COMMAND_BYPASS` |
| `COURT_BREAK_COMMANDS`（退朝等） | KEEP（合法固定口令） |

复扫：两句 → `CMD_NONE`；`退朝` → `CMD_CLOSE_NIGHT`。

## 验证命令与实测输出

```text
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/1847-w8-verify/pytest \
  tests/test_month_chain_1847.py tests/test_pihong_dossier_1490.py \
  tests/test_cli_backend.py tests/test_advance_paths_atomic.py \
  tests/test_audience_translate_1837.py tests/test_office_rank_562.py \
  tests/test_override_breach_costs_564.py \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change
```

输出：`207 passed in 11.63s`（未跑全量）。

## 变异结果摘要

| 类 | 旧逻辑 | 当前 |
|---|---|---|
| N13 | idle+notes → 重试成功洗掉收尾真因 | `TimeoutError from TransportIdleTimeout`，不可重试上浮 |
| N15 | 「留下听着」→ stay_attend 旁路 | → `CMD_NONE`，走普通场景 |
| N11 | 符号/专属测试存在 | 符号 CLEAR；专属测试 collect 不到 |
| N14 | helper/自同值案存在 | 已删/已改为 before↔after |

## 剩余范围 / 据实记录

- 其它开库 migrate/backfill（薪饷、财政单位、人物种子等）本轮 **KEEP** 并附消费者理由；若后续按 #1812「不考虑旧存档兼容」继续清，需另轮按同一谓词再裁，避免误伤现役 substrate。
- 未 push、未开 PR、未宣告 merge/关票。
- 未改 ADR/宪法；N6 本轮判词不重送，未动原文运输案面。
- 临时探针仅在 `/tmp/1847-w8-*`，未清他人目录。

## 自查二连

1. 同类：四类均按定义全文枚举+复扫，非只修点名样本。  
2. 引入：聚焦 207 绿；N13 变异旧红新绿；无 SIGKILL/监管层/新识别器/证明性测试。
