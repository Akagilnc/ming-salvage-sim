# #1843 修内司回执（w5 / F2-R11 apply 自查订正）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r11-f2`（自 `fab71100c`）
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10914-924d-782f-befd-de9d9e61b59b@fixer/fix-packet.md`
末判真源：附件 `03-1843-judge-fab71100c.json` **最后一份 payload**（F2-R11-1 / F2-R11-2）
未 push、未 PR、未 amend、未 stash；未声称合并或关票。

## 顾问审视（动手前）

- CLI `advisor` / `gstack-advisor` **不可用**；**未获得任何外部 advisor 意见**，不得冒称。
- 本进程独立笔记：`/tmp/1843-f2-r11/advisor-review.md`（仅本席自审，非外部顾问）。

## 上轮回执不实覆盖订正（主席核验）

1. `git diff --check fab71100c HEAD`：回执尾空格 + 两测试 EOF 多余空行 → 已修净。
2. 上轮 `/tmp/1843-f2-r11/enum_both.py` **实际谓词**过窄：A 仅 `migrate_legacy|_migrate_reaction` + 固定夹具名零引用；B 仅特定 `startswith`/`hasattr`/`army_pay`。与回执「覆盖类定义全文」不符。**不得以声明代替实际谓词**。本局以 `evidence/1843-w5-fixer-enum_full.py.txt` 重枚举。
3. 上轮 B 复扫仅 1 行空表头 ≠ 成员表；本局提交完整逐名 A/B 施工前+处置+复扫表。
4. 上轮 57 路径只跑约 17 测试文件；本局补跑此前未跑触及面（见测试节）。
5. 上轮变异「截断 4 字」不是旧逻辑；本局装回旧 `_migrate_reaction_value` 映射单元 + 装回旧 `startswith("#259")` 弱断言对照同值断言（见变异节）。
6. 上轮「0 残留 / 全部完成」在未完整追踪时过早；本局复扫仍列保留成员与逐名理由，**不声称类已 externally 结清**。

## 未结两类（末判原文边界）

1. **F2-R11-1**「旧结算／simulator 独占支持树与旧档兼容路径漏退役」— 沿历史已删消费者向下追闭包；全仓 migrate/backfill/purge/资源/装载/旧兼容路径清单 + 现役入口反核；旧迁移不因「schema 演化」名义保留。
2. **F2-R11-2**「非契约文字／内部结构／重复测试未清，并以弱化断言代替行为验证」— 全仓（含 web）枚举源码措辞、helper 内部、重复、传值弱化；保留结构化负向与输入同值传递。

## 机械枚举（可复现）

| 用途 | 路径 |
|---|---|
| 枚举命令 | `evidence/1843-w5-fixer-enum-commands.txt` |
| 谓词脚本（临时扫描，非生产） | `evidence/1843-w5-fixer-enum_full.py.txt` |
| 施工前 A | `evidence/1843-w5-fixer-class-a-pre.tsv`（93） |
| 施工前 B | `evidence/1843-w5-fixer-class-b-pre.tsv`（164） |
| A 处置表 | `evidence/1843-w5-fixer-class-a-members.tsv` |
| B 处置表 | `evidence/1843-w5-fixer-class-b-members.tsv` |
| A 复扫逐名 | `evidence/1843-w5-fixer-class-a-rescan.tsv`（55，均 RETAIN 附理由） |
| B 复扫逐名 | `evidence/1843-w5-fixer-class-b-rescan.tsv`（74，均 RETAIN 附理由；非空表） |
| 变异 | `evidence/1843-w5-fixer-mutation.json` |
| 补跑测试日志 | `evidence/1843-w5-fixer-pytest-missed.log` |

施工前命令：

```bash
git archive fab71100c | tar -x -C /tmp/1843-f2-r11b/fab71100c
MING_SIM_*_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  /tmp/1843-f2-r11b/enum_full.py /tmp/1843-f2-r11b/fab71100c /tmp/1843-f2-r11b pre
```

## 逐类处置摘要

### F2-R11-1

已删（含上轮 + 本局谓词补扫）：reaction severity 迁移链；office 污染 / identity / bandit / location 写回 / opening_gazette purge+资源；死夹具 `_month_end_ctx`/`_army_*`/`_1778_*`；以及本局补删：

| 成员 | 处置 | 依据 |
|---|---|---|
| `_migrate_building_logs_to_durable_audit` | 删 | CREATE 已无 FK；仅为旧表形 |
| `_migrate_next_audience_todos_drop_issue_fk` | 删 | CREATE 已无 issues FK |
| `_backfill_salary_rate` + 三专属测 | 删 | 显式旧档回填 |
| `_migrate_arrears_unit_to_silver` | 删 | 显式旧档分→两 |
| `_migrate_offsets_to_float_precision` + 专属测 | 删 | 显式旧整数 offset |
| `_migrate_missing_fiscal_engine…` + pre_s6 测 | 删 | 旧 cutover 存档 |
| `_backfill_event_triggers_from_event_pool_issues` + 专属测 | 删 | 旧 event_pool→triggers |
| `_backfill_proposed_appointment_break_ranks` + 专属测 | 删 | 旧 proposed 一次性 |
| `_reanchor_offsets_for_rank_rules_562` + legacy weight + 专属测 | 删 | 非 migrate 名但仍旧档一次重锚 |
| `characters.json` 胡廷宴 office | 洗净 | 删污染迁移后 seed 须自洽（`三边总督`+dismissed 事实） |

保留（逐名见复扫表）：`_backfill_healed_participant_refs`（现役纠错）；`test_legacy_character_executor_…`（现役 dossier 写口）；`test_old_dongjiang_…`（现役建军补 meta）；LLM config 两测（现役 kwargs 别名）；50 个零外部 Load 测试夹具壳（非旧结算种子）。

### F2-R11-2

上轮已清：字面 `match=`、日志/`#ticket` 前缀弱化、`hasattr` 缺席、纯公式、重复常量子集、`getsource`。
本局复扫仍命中 74 项，**逐名 RETAIN**：`match=param` 同值传递；结构性 `startswith`（affair-/materials/SSE）；helper+外部结果；中文结构化枚举；回滚属性观察。未盲删负向契约。#1471 HUD 负向维持末判 G1。

未新增证明性测试或生产扫描机制。

## 复杂度必要性（相对 fab71100c）

含 evidence 时约 **59 paths，+568 / −1938，net ≈ −1370**；剔 evidence 后生产+测试约 **53 paths，+143 / −1938，net ≈ −1795**。
上轮回执写「+421 / −1225 / 57 paths」是当时提交态；本局续删旧档迁移后删行进一步增加。
净减主要来自：`ming_sim/db.py` 旧档迁移方法/调用、专属旧档测试、死夹具；evidence 表变长是枚举/回执诚实化的必要成本，不是功能膨胀。
**复杂度下降看生产闭包变短，不看 evidence 行数。**

## 聚焦测试

此前已跑（上轮日志）：约 17 文件。
本局补跑此前未跑触及面 + 本局新改文件：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_advances_section_rejections.py \
  tests/test_affairs_1831.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translate_1837.py \
  tests/test_centrifuge_ledger_690.py \
  tests/test_cli_play_turn.py \
  tests/test_close_issues_section_rejections.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_decree_dossiers_571.py \
  tests/test_due_review_621.py \
  tests/test_event_chain_cascade.py \
  tests/test_faction_brew_637.py \
  tests/test_material_directory_1830.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_month_chain_1843.py \
  tests/test_month_chain_1847.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_new_game_write_path_1749.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_power_section_rejections.py \
  tests/test_pre_settle_transaction.py \
  tests/test_qa_1281_issue_audience_case_facts.py \
  tests/test_rejection_wiring.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_session_write_queue_1353.py \
  tests/test_state_reload.py \
  tests/test_transaction_boundary.py \
  tests/test_army_salary_44.py \
  tests/test_faction_leverage_9.py \
  tests/test_office_rank_562.py \
  tests/test_event_trigger_gate.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_executor_routing_721.py \
  tests/test_llm_channel_config.py
```

实测（`evidence/1843-w5-fixer-pytest-missed.log`）：初跑 2 failed（reanchor 专属测 + 胡廷宴 seed 污染）→ 删专属测并洗净 seed 后 `tests/test_office_rank_562.py` **16 passed**；整批补跑 **1100 passed, 2 skipped**（修复前）/ 修复后 office_rank 全绿。`/usr/bin/time -p` → **real 43.85s**。非全量。

## 变异证据（装回旧逻辑；源码已恢复）

见 `evidence/1843-w5-fixer-mutation.json`：

| 步骤 | 结果 |
|---|---|
| A1 从 fab71100c 装回 `_migrate_reaction_value` / `_migrate_legacy_reaction_severity` | `{"severity":"大怒"}` → `direction=negative,intensity=strong`（旧逻辑在） |
| A2 移除 | `hasattr(...)=False` |
| A3 `canonicalize_location_region_id`→恒等 | admit 别名案 **fail** |
| A4 恢复 | **pass** |
| B1 装回旧 `startswith("#259")` + 错误截断输出 `#259` | **pass**（旧弱断言放行错误输出） |
| B2 正确同值断言 + 同一错误截断 | **fail** |
| B3 同值基线 | **pass** |
| 末判 independentVerification | 旧前缀弱断言对照记录（非本席新造测） |

说明：截断输出只作「错误输出」对照，**不是**旧生产逻辑；旧生产逻辑的装回是 A1 的 severity 映射。

## 复扫实核（非「0 残留」空话）

- A 应删符号：处置表 `DELETED_ABSENT`；`DELETE_STILL_PRESENT=0`。
- A 复扫仍 **55** 候选：1 现役 backfill + 4 名含 migrate/legacy 但现役入口的测试 + 50 夹具壳 → 均附 RETAIN 理由。
- B 复扫仍 **74** 候选：全部按契约 RETAIN 逐名；**无**字面 match=/`#ticket` 弱化/getsource/hasattr 缺席/纯公式残留。
- 不声称大理寺已结清；只报告本局枚举与处置实核。

## 自查二连

- 同类型：纠正上轮谓词收窄与空复扫表；按类定义全文重枚举；补删 schema 名义下的旧档迁移。
- 引入 bug：删 reanchor 后专属测红 → 删测；删 office 污染迁移后胡廷宴 seed 未洗净 → 洗净 office 标题。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：
- 未 push；未合并；未关票。
