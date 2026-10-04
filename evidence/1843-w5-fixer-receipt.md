# #1843 修内司回执（w5 / F2-R11 apply 全表逐案核）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r11-f2`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10914-924d-782f-befd-de9d9e61b59b@fixer/fix-packet.md`
末判真源：附件 `03-1843-judge-fab71100c.json` **最后一份 payload**（F2-R11-1 / F2-R11-2）
未 push、未 PR、未 amend、未 stash；未声称合并或关票。

## 顾问审视（动手前）

- CLI `advisor` / `gstack-advisor` **不可用**；**未获得任何外部 advisor 意见**，不得冒称。

## 本局任务边界（相对上轮交卷问题）

上轮回执承认「B 信号候选仍约 569 待逐案契约核」并以之为未结——**不得**再作交卷停止理由。本局对已枚举 A/B 成员**全部逐名处置**（DELETE / RETAIN / OOC_*），成员表无 `CANDIDATE` / `REMAINING_RETAIN` 状态。

机械信号命中 ≠ 未处置：`post2` 复扫仍会报 `class_b_candidates=562`（信号谓词），但 `class-b-members.tsv` 已对每一信号项给出契约结论。

## 未结两类（末判原文）

1. **F2-R11-1** 旧结算／simulator 独占支持树与旧档兼容路径漏退役。
2. **F2-R11-2** 非契约文字／内部结构／重复测试未清，并以弱化断言代替行为验证。

## 机械枚举（可复现；临时扫描，非生产机制）

| 用途 | 路径 |
|---|---|
| 枚举命令 | `evidence/1843-w5-fixer-enum-commands.txt` |
| 闭包脚本副本 | `evidence/1843-w5-fixer-closure_enum.py.txt` |
| 清洗退役名集 | `evidence/1843-w5-fixer-retired-cleaned.txt`（301） |
| pre2 / post2 摘要 | `evidence/1843-w5-fixer-pre2-enum-summary.json`；`evidence/1843-w5-fixer-post-enum-summary.json`（label=post2） |
| A/B 成员处置表 | `evidence/1843-w5-fixer-class-a-members.tsv`；`evidence/1843-w5-fixer-class-b-members.tsv` |
| 删除复扫 | `evidence/1843-w5-fixer-class-b-rescan.tsv`（21 项均为 `DELETED_ABSENT`） |
| 本局聚焦测 | `evidence/1843-w5-fixer-pytest-focused-r13.txt` |

施工命令：

```bash
MING_SIM_*_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1843-f2-r12/closure_enum.py \
  /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5 /tmp/1843-f2-r12 post2 \
  /tmp/1843-f2-r12/retired-cleaned.txt
```

post2 实核：`retired_names_input=301`；A CANDIDATE=72 + OOC_PROBE=42；B 信号=562 / OUT_OF_SIGNAL=2282；`hasattr_private_internal` 已随无断言案删除从 flag 计数消失；`helper_internal_signal` 143→137。

## 逐类处置摘要

### F2-R11-1（A 表 116 行，全处置）

| 处置 | 数 | 说明 |
|---|---|---|
| RETAIN / DISPOSED* | 43 | 现役生产消费位点写入 `final_reason`（非「prod_n=N」空话）；LIVE_SEAM 维持 |
| FALSE_POSITIVE / OOC_NAME_COLLISION | 4 | `ARMY_SALARY_PRIORITY` / `rescript_*` / `simulator_payload` 同名模块碰撞 |
| OOC_F3 | 1 | `complete_rescript_summon_scaffold_turn`：零调用；retirement.md 标 F3 批红脚手架；**消费链不属 F2**，上呈不删 |
| OOC_PROBE | 42 | 零引用下划线夹具壳；未挂退役闭包，不得仅因零引用删 |
| OOC_CLOSURE_NOISE / OOC | 24 | 闭包从通用符号扩出的 content/测试夹具；非独占支持 |
| FIXED | 2 | 胡廷宴 seed 洗净（上轮） |

末判点名旧档迁移 `_migrate_legacy_reaction_severity`、`_1778_*` 死夹具、`startswith('#259')` 弱化：**现行树已不存在**（前轮已删；本局复扫零命中）。

**不声称**外部判官已结清 F2-R11-1；本局执行面：枚举成员均已按消费链定性。

### F2-R11-2（B 表 583 行 = 569 信号项 ∪ 上轮 14 已删）

本局新删 7（复扫全 `DELETED_ABSENT`）：

| 成员 | 理由 |
|---|---|
| `test_character_numeric_gate_supports_aggregation` | 纯 `_gate_passed` 布尔；旁有 gather 入口 |
| `test_army_numeric_gate_preserves_fractional_arrears_tail` | 纯 `_gate_passed` 布尔 |
| `test_character_text_gate_supports_equality` | 纯 `_gate_passed` 布尔 |
| `test_issue_tracker_rollback_removes_dynamic_character_attrs` | rollback 后无断言；hasattr 仅清测试注入属性 |
| `test_rollback_snapshot_restores_leverage_offset` | 直测 `_snapshot/_restore_person_write_state` |
| `test_provider_fault_becomes_typed_brew_failure` | 直测 `_brew_fn_for_session`；旁有 `run_month_end_relation_brew`+LLMUnavailable |
| `test_displaced_holder_transit_to_cleared` | 直测 `_displace_duplicate_offices`；旁有 `apply_score_extraction` 顶替结构化 |

上轮已删 14 维持 `DELETED_PRIOR`。闸语言 `pytest.raises` 负向、`pre_settle→secret_orders.result` 结构化负向、economy/person 生产写口→DB、#1471 HUD 负向等 **RETAIN**，理由写在 `final_reason`（入口/结构化输出，非同一句搪塞）。

**不声称**外部判官已结清；**声称**已枚举信号项在成员表上已全处置（562 RETAIN + 21 DELETE）。未新增证明性测试或生产扫描机制。

## 复杂度（实际 query）

相对 `4d66f09ca`（本局动手前 HEAD）工作树（含 evidence）：

```text
git diff --numstat HEAD -- . ':(exclude)evidence'
→ code_paths 4  +0  -125
```

生产闭包未扩；本局仅删测试。evidence 表重写为逐名具体理由。

## 聚焦测试

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_event_trigger_gate.py \
  tests/test_faction_leverage_9.py \
  tests/test_relation_brew_636.py \
  tests/test_person_delta_adapter.py
```

实测（`evidence/1843-w5-fixer-pytest-focused-r13.txt`）：**300 passed in 3.60s**（`/usr/bin/time -p` → real 4.01s）。只跑本局触及文件；未改通过文件不重跑；非全量。

`git diff --check`：通过（无输出）。

## 自查二连

- 同类型：不以「信号候选数」当未完成；逐名写入口/结构化/OOC 消费链；F3 scaffold 据消费链标类外。
- 引入 bug：未删 LIVE_SEAM / 闸类负向 / economy·person 生产写口→DB 案；未误删 travel `_apply_person_changes` 候见结清行为案。

## 法律阻断

无。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：`c2556e6fbe46f3fc7956926e4e2c9bda906a7cd7`
- 未 push；未合并；未关票。
