# #1835 w5 C1/C3 证据复核全表（situation_drift / displaced_population / issues）

纠正上轮证据缺口：
1. 枚举命令 heredoc 仅注释、不可运行；
2. 「跨仓同名」只点名 3 个符号，未证明对三模块全部顶层/嵌套 def（98）做跨仓同名核对；
3. 消费者计数把未解析同名 Attribute 当准确消费者。

本轮调查脚本（非测试、不设生产约束）放在本目录，实际 AST 遍历全仓 `FunctionDef`/`AsyncFunctionDef`。

## 枚举命令（真实可运行）

```sh
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5
python3 evidence/issue-1835/c1c3-resweep/ast_c1c3_resweep_enum.py \
  2>&1 | tee evidence/issue-1835/c1c3-resweep/enum-run-stdout.txt
```

脚本：`evidence/issue-1835/c1c3-resweep/ast_c1c3_resweep_enum.py`

原始输出：

- `enum-run-stdout.txt` — 脚本 stdout（含 SUMMARY / C1·C3 review 列表）
- `enumeration-resolved.txt` — 98 def 全表：CROSS_DEF + RESOLVED_PROD/TEST + SAME + UNCERTAIN
- `cross-name-candidates.txt` — 98 条每人一项的跨模块同名定义路径（无则 `CROSS_DEF (none)`）
- `review-flags.txt` — 零生产消费者 / 转发壳 / 跨名索引机读摘要

### stdout 摘要（实跑）

```
wrote evidence/issue-1835/c1c3-resweep/enumeration-resolved.txt
wrote evidence/issue-1835/c1c3-resweep/cross-name-candidates.txt
wrote evidence/issue-1835/c1c3-resweep/review-flags.txt
TARGET_DEFS=98 WITH_CROSS=2
TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME=0
TOPLEVEL_FORWARDERS=0

--- C3 review: toplevel zero resolved_prod AND zero same_module ---
  (none)

--- C1/C3 review: toplevel forwarder flag ---
  (none)

--- C1 review: cross-module same-name names ---
  bind_content: [('ming_sim/issues.py', 109), ('ming_sim/agents.py', 48), ('ming_sim/context.py', 64)]
  _ctx: [('ming_sim/issues.py', 115), ('ming_sim/agents.py', 53), ('ming_sim/context.py', 69), ('tests/test_rescript_heal_isolation_1801.py', 23), ('tests/test_rescript_option_field_heal_1746.py', 20)]
```

## 消费者判定规则（本轮）

- **resolved**：`from <target_module> import <name>`（含函数内 import）+ 随后 Name Load；或 Attribute 基座解析到 `target_module`（含 `import ming_sim.issues as issues` → `issues.foo`）。
- **same_module**：定义文件内 Name Load（模块内互调）。
- **uncertain**：同名 Attribute 但基座无法解析到 target_module — **不计为准确消费者**，表内单独列。
- 生产 / 测试：`tests/` 前缀为测试，其余为生产（含 `scripts/`）。

## 既有删除（上轮修内已落，本轮复核确认仍成立）

| 路径 | 成员 | 分类 | 依据 |
|---|---|---|---|
| `situation_drift.py` | `default_situation_shape` | C3 零消费者 | 修前 AST total=0；开局形状真源=`event_to_issue` 内联 |
| `situation_drift.py` | `_commitment_bar_value` | C1 同形重复零调用 | 真源=`commitment_display._commitment_bar_value`；本模块无 Name 调用 |
| `issues.py` | `_situation_terminal_effects` | C1/C3 单调用转发壳 | 已改为 `event_to_issue` 直接接 `situation_drift.situation_terminal_effects` |
| `issues.py` | `_COLLAPSIBLE_KINDS` | C3 零引用常量 | 真源=`COLLAPSIBLE_SITUATION_KINDS` |

本轮复核闸：`TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME=0`，`TOPLEVEL_FORWARDER_FLAG=0`。

### 本轮生产删码（C1 DRY 归一）

| 路径 | 成员 | 分类 | 依据 |
|---|---|---|---|
| `settlement/preflight.py` | `_event_outcome_label`（副本） | C1 字面同形平行核 | 与 `issues._event_outcome_label` **BYTE_IDENTICAL**（实证比对函数体）；真源=`ming_sim.issues._event_outcome_label`；preflight 两处调用点改为 `from ming_sim.issues import _event_outcome_label`（函数内 import，避 issues↔preflight 环）。**有消费者仍须单一权威实现**——不以「双侧有生产消费者」保留重复。 |

## 跨仓同名核对（完整 98：有 CROSS_DEF 的 2 名 + 其余 96 名无跨模块同名定义）

机械枚举证明：`cross-name-candidates.txt` 对每个 TARGET def 写出全部 `CROSS_DEF`；`WITH_CROSS_MODULE_SAME_NAME=2`（DRY 后 `_event_outcome_label` 已无第二定义点）。

### 有跨模块同名定义的候选（逐项语义）

| 符号 | 定义点 | 语义核对 | 处置 |
|---|---|---|---|
| `bind_content` | `ming_sim/issues.py:109`；`ming_sim/agents.py:48`；`ming_sim/context.py:64` | **不重复（非 C1 平行核）** — 各模块私有 `_content` 注入口：`agents`/`context` 为纯赋值；`issues` 另跑 `_validate_strategic_foreign_node_outcome_targets`。同名只因注入约定，不是局势/财政双持核。双侧/三侧均有真实生产 ImportFrom 消费者 → **保留全部**。 | **保留** |
| `_ctx` | `ming_sim/issues.py:115`；`ming_sim/agents.py:53`；`ming_sim/context.py:69`；`tests/test_rescript_heal_isolation_1801.py:23`；`tests/test_rescript_option_field_heal_1746.py:20` | **不重复（非 C1 平行核）** — 各模块读取本模块 `_content` 的访问器；错误文案挂本模块名。同形但闭包目标不同（issues/agents/context 各自全局）。测试文件内另有同名 helper（夹具）≠ 生产 issues._ctx。→ **保留全部**。 | **保留** |

### 已归一的原跨名同形（本轮 DRY）

| 符号 | 定义点（现） | 语义核对 | 处置 |
|---|---|---|---|
| `_event_outcome_label` | **仅** `ming_sim/issues.py:1091`（`preflight` 副本已删） | **C1 字面同形已归一** — 删前与 `preflight` 函数体 BYTE_IDENTICAL；删后 `CROSS_DEF (none)`；preflight `_strategic_event_outcome_label_or_error` / `_preflight_declared_event_groups` 直接 ImportFrom `ming_sim.issues`。resolved_prod=6（含两处 preflight import + Name Load + declaration_dispatch）。 | **保留 issues 真源；删 preflight 副本** |

### 无跨模块同名定义的 TARGET defs（96）

下列每人在 `cross-name-candidates.txt` 均为 `CROSS_DEF (none)` — 已机械核对，无第二定义点，故无 C1 同名碰撞可删项。

计数：96 / 98。

<details><summary>展开 95 个无跨模块同名 def 路径</summary>

```
ming_sim/situation_drift.py:47 situation_terminal_effects
ming_sim/situation_drift.py:60 _metrics
ming_sim/situation_drift.py:73 _commitment_ongoing_effects_for_settlement
ming_sim/situation_drift.py:106 _resolve_commitment_issue
ming_sim/situation_drift.py:151 _expire_commitment_issue
ming_sim/situation_drift.py:195 apply_situation_monthly_drift
ming_sim/displaced_population.py:32 surcharge_population_pool_members
ming_sim/displaced_population.py:42 apply_levy_driven_transfers
ming_sim/issues.py:64 _issue_condition_text
ming_sim/issues.py:74 _normalize_commitment_kind
ming_sim/issues.py:81 _validate_commitment_stop_condition
ming_sim/issues.py:121 _canonical_issue_origin
ming_sim/issues.py:133 commitment_condition_role
ming_sim/issues.py:148 _legacy_commitment_stop_gate
ming_sim/issues.py:156 _commitment_stop_gate
ming_sim/issues.py:168 _commitment_remaining_from_gate
ming_sim/issues.py:203 _latest_commitment_paid_total
ming_sim/issues.py:221 _commitment_gate_references_arrears
ming_sim/issues.py:225 _commitment_arrears_gate_army_ids
ming_sim/issues.py:239 _monthly_person_rating_changes
ming_sim/issues.py:257 _invalid_monthly_person_rating_reason
ming_sim/issues.py:275 _person_change_has_unsupported_monthly_work
ming_sim/issues.py:288 _unsupported_monthly_ongoing_fields
ming_sim/issues.py:304 _monthly_ongoing_effects_has_work
ming_sim/issues.py:321 _ack_due_commitment_issue
ming_sim/issues.py:355 _event_issue_refs
ming_sim/issues.py:363 _event_trigger_refs
ming_sim/issues.py:367 _event_terminal_states
ming_sim/issues.py:376 _event_terminal_records
ming_sim/issues.py:415 _normalize_event_terminal_reason
ming_sim/issues.py:426 _fiscal_levy_normalized_terminal_reason_or_abort
ming_sim/issues.py:442 _canonicalize_existing_fiscal_levy_terminal_reason
ming_sim/issues.py:463 _as_float
ming_sim/issues.py:475 _is_stored_number
ming_sim/issues.py:479 _fiscal_levy_liao_seed
ming_sim/issues.py:488 _fiscal_levy_base_transport
ming_sim/issues.py:506 _fiscal_levy_event_by_id
ming_sim/issues.py:510 _fiscal_levy_event_approved
ming_sim/issues.py:521 _fiscal_levy_stopped
ming_sim/issues.py:532 _fiscal_levy_land_share_amount
ming_sim/issues.py:542 _fiscal_levy_land_denominator
ming_sim/issues.py:559 _load_region_fiscal_for_fiscal_levy
ming_sim/issues.py:578 _fiscal_levy_share_seed
ming_sim/issues.py:591 _validate_fiscal_levy_share_meta
ming_sim/issues.py:601 _fiscal_levy_mark_provisional
ming_sim/issues.py:615 _jiao_levy_in_force
ming_sim/issues.py:630 _apply_fiscal_levy_targets
ming_sim/issues.py:765 apply_historical_fiscal_rates
ming_sim/issues.py:781 run_fiscal_levy_pass
ming_sim/issues.py:818 _numeric_predicate_accepts
ming_sim/issues.py:832 _event_triggered_numeric_dependency_kind
ming_sim/issues.py:845 _event_dependency_ids
ming_sim/issues.py:857 _validate_event_dependency_graph_acyclic
ming_sim/issues.py:872 dfs
ming_sim/issues.py:895 _event_chain_impossible_reason
ming_sim/issues.py:901 _format_values
ming_sim/issues.py:904 allow_states
ming_sim/issues.py:922 allow_state
ming_sim/issues.py:925 allow_outcomes
ming_sim/issues.py:943 forbid_state
ming_sim/issues.py:1013 apply_event_cascading_invalidations
ming_sim/issues.py:1031 run_cascade
ming_sim/issues.py:1067 _spawned_event_refs
ming_sim/issues.py:1073 _event_window_open
ming_sim/issues.py:1091 _event_outcome_label
ming_sim/issues.py:1100 _merge_first_event_outcome
ming_sim/issues.py:1125 apply_petition_event_outcome
ming_sim/issues.py:1190 gather_fiscal_levy_petitions
ming_sim/issues.py:1215 petition_outcome_is_admissible
ming_sim/issues.py:1239 _closed_outcome_labels
ming_sim/issues.py:1246 strategic_event_outcome_labels
ming_sim/issues.py:1259 _event_window_expired
ming_sim/issues.py:1272 _dead_person_core_subjects
ming_sim/issues.py:1284 _person_core_avoided_reason
ming_sim/issues.py:1347 _gate_sql_field
ming_sim/issues.py:1358 _eval_gate_key
ming_sim/issues.py:1452 _eval_gate_key_str
ming_sim/issues.py:1476 _gate_passed
ming_sim/issues.py:1517 gather_impeachment_surge_candidates
ming_sim/issues.py:1646 gather_candidate_events
ming_sim/issues.py:1696 apply_event_terminal_states
ming_sim/issues.py:1708 run_terminal_state_pass
ming_sim/issues.py:1751 auto_trigger_seed_issues
ming_sim/issues.py:1765 _auto_trigger_seed_issues_in_atomic
ming_sim/issues.py:1850 _bar_ascii
ming_sim/issues.py:1856 _format_inertia
ming_sim/issues.py:1864 show_active_issues
ming_sim/issues.py:1873 _print_row
ming_sim/issues.py:1895 event_to_issue
ming_sim/issues.py:1997 _normalize_cancellable
ming_sim/issues.py:2012 _compute_inertia
ming_sim/issues.py:2031 _content_population_effect_for_save
ming_sim/issues.py:2072 neutralize_covert_fiscal_effects
ming_sim/issues.py:2157 record_secret_order_disclosure
ming_sim/issues.py:2209 clear_gated_legacies
ming_sim/issues.py:2230 sync_opening_legacies
```

</details>

## 修后全表：defs（98）— 解析后消费者

| 路径:行 | 成员 | nested | cross_defs | prod | test | same | unc | 处置 | 依据 |
|---|---|---|---|---|---|---|---|---|---|
| `ming_sim/situation_drift.py:47` | `situation_terminal_effects` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/situation_drift.py:60` | `_metrics` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `situation_terminal_effects`；局部 helper |
| `ming_sim/situation_drift.py:73` | `_commitment_ongoing_effects_for_settlement` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/situation_drift.py:106` | `_resolve_commitment_issue` | False | 0 | 0 | 2 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/situation_drift.py:151` | `_expire_commitment_issue` | False | 0 | 0 | 3 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/situation_drift.py:195` | `apply_situation_monthly_drift` | False | 0 | 2 | 23 | 0 | 0 | 保留 | resolved prod=2 test=23 same=0 |
| `ming_sim/displaced_population.py:32` | `surcharge_population_pool_members` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/displaced_population.py:42` | `apply_levy_driven_transfers` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:64` | `_issue_condition_text` | False | 0 | 3 | 0 | 1 | 0 | 保留 | resolved prod=3 test=0 same=1 |
| `ming_sim/issues.py:74` | `_normalize_commitment_kind` | False | 0 | 3 | 0 | 0 | 0 | 保留 | resolved prod=3 test=0 same=0 |
| `ming_sim/issues.py:81` | `_validate_commitment_stop_condition` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:109` | `bind_content` | False | 2 | 19 | 178 | 0 | 0 | 保留 | 跨名语义：不重复（非 C1 平行核） |
| `ming_sim/issues.py:115` | `_ctx` | False | 4 | 7 | 3 | 11 | 0 | 保留 | 跨名语义：不重复（非 C1 平行核） |
| `ming_sim/issues.py:121` | `_canonical_issue_origin` | False | 0 | 7 | 0 | 0 | 0 | 保留 | resolved prod=7 test=0 same=0 |
| `ming_sim/issues.py:133` | `commitment_condition_role` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:148` | `_legacy_commitment_stop_gate` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:156` | `_commitment_stop_gate` | False | 0 | 10 | 0 | 2 | 0 | 保留 | resolved prod=10 test=0 same=2 |
| `ming_sim/issues.py:168` | `_commitment_remaining_from_gate` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:203` | `_latest_commitment_paid_total` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:221` | `_commitment_gate_references_arrears` | False | 0 | 7 | 0 | 0 | 0 | 保留 | resolved prod=7 test=0 same=0 |
| `ming_sim/issues.py:225` | `_commitment_arrears_gate_army_ids` | False | 0 | 3 | 0 | 0 | 0 | 保留 | resolved prod=3 test=0 same=0 |
| `ming_sim/issues.py:239` | `_monthly_person_rating_changes` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:257` | `_invalid_monthly_person_rating_reason` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:275` | `_person_change_has_unsupported_monthly_work` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:288` | `_unsupported_monthly_ongoing_fields` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:304` | `_monthly_ongoing_effects_has_work` | False | 0 | 7 | 0 | 0 | 0 | 保留 | resolved prod=7 test=0 same=0 |
| `ming_sim/issues.py:321` | `_ack_due_commitment_issue` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:355` | `_event_issue_refs` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:363` | `_event_trigger_refs` | False | 0 | 0 | 1 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:367` | `_event_terminal_states` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:376` | `_event_terminal_records` | False | 0 | 0 | 0 | 4 | 0 | 保留 | 模块内互调 same=4（内联 helper） |
| `ming_sim/issues.py:415` | `_normalize_event_terminal_reason` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:426` | `_fiscal_levy_normalized_terminal_reason_or_abort` | False | 0 | 2 | 0 | 2 | 0 | 保留 | resolved prod=2 test=0 same=2 |
| `ming_sim/issues.py:442` | `_canonicalize_existing_fiscal_levy_terminal_reason` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:463` | `_as_float` | False | 0 | 0 | 0 | 11 | 0 | 保留 | 模块内互调 same=11（内联 helper） |
| `ming_sim/issues.py:475` | `_is_stored_number` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:479` | `_fiscal_levy_liao_seed` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:488` | `_fiscal_levy_base_transport` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:506` | `_fiscal_levy_event_by_id` | False | 0 | 2 | 2 | 3 | 0 | 保留 | resolved prod=2 test=2 same=3 |
| `ming_sim/issues.py:510` | `_fiscal_levy_event_approved` | False | 0 | 0 | 0 | 3 | 0 | 保留 | 模块内互调 same=3（内联 helper） |
| `ming_sim/issues.py:521` | `_fiscal_levy_stopped` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:532` | `_fiscal_levy_land_share_amount` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:542` | `_fiscal_levy_land_denominator` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:559` | `_load_region_fiscal_for_fiscal_levy` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:578` | `_fiscal_levy_share_seed` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:591` | `_validate_fiscal_levy_share_meta` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:601` | `_fiscal_levy_mark_provisional` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:615` | `_jiao_levy_in_force` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:630` | `_apply_fiscal_levy_targets` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:765` | `apply_historical_fiscal_rates` | False | 0 | 2 | 39 | 0 | 0 | 保留 | resolved prod=2 test=39 same=0 |
| `ming_sim/issues.py:781` | `run_fiscal_levy_pass` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `apply_historical_fiscal_rates`；局部 helper |
| `ming_sim/issues.py:818` | `_numeric_predicate_accepts` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:832` | `_event_triggered_numeric_dependency_kind` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:845` | `_event_dependency_ids` | False | 0 | 0 | 0 | 3 | 0 | 保留 | 模块内互调 same=3（内联 helper） |
| `ming_sim/issues.py:857` | `_validate_event_dependency_graph_acyclic` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:872` | `dfs` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `_validate_event_dependency_graph_acyclic`；局部 helper |
| `ming_sim/issues.py:895` | `_event_chain_impossible_reason` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:901` | `_format_values` | True | 0 | 0 | 0 | 4 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:904` | `allow_states` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:922` | `allow_state` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:925` | `allow_outcomes` | True | 0 | 0 | 0 | 1 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:943` | `forbid_state` | True | 0 | 0 | 0 | 1 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:1013` | `apply_event_cascading_invalidations` | False | 0 | 3 | 14 | 4 | 0 | 保留 | resolved prod=3 test=14 same=4 |
| `ming_sim/issues.py:1031` | `run_cascade` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `apply_event_cascading_invalidations`；局部 helper |
| `ming_sim/issues.py:1067` | `_spawned_event_refs` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:1073` | `_event_window_open` | False | 0 | 0 | 2 | 6 | 0 | 保留 | 模块内互调 same=6（内联 helper） |
| `ming_sim/issues.py:1091` | `_event_outcome_label` | False | 0 | 6 | 0 | 2 | 0 | 保留真源 | C1 DRY：preflight 副本已删；CROSS_DEF=none；resolved_prod=6 |
| `ming_sim/issues.py:1100` | `_merge_first_event_outcome` | False | 0 | 6 | 0 | 0 | 0 | 保留 | resolved prod=6 test=0 same=0 |
| `ming_sim/issues.py:1125` | `apply_petition_event_outcome` | False | 0 | 2 | 6 | 0 | 0 | 保留 | resolved prod=2 test=6 same=0 |
| `ming_sim/issues.py:1190` | `gather_fiscal_levy_petitions` | False | 0 | 4 | 3 | 0 | 0 | 保留 | resolved prod=4 test=3 same=0 |
| `ming_sim/issues.py:1215` | `petition_outcome_is_admissible` | False | 0 | 4 | 0 | 0 | 0 | 保留 | resolved prod=4 test=0 same=0 |
| `ming_sim/issues.py:1239` | `_closed_outcome_labels` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:1246` | `strategic_event_outcome_labels` | False | 0 | 2 | 3 | 0 | 0 | 保留 | resolved prod=2 test=3 same=0 |
| `ming_sim/issues.py:1259` | `_event_window_expired` | False | 0 | 0 | 0 | 7 | 0 | 保留 | 模块内互调 same=7（内联 helper） |
| `ming_sim/issues.py:1272` | `_dead_person_core_subjects` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:1284` | `_person_core_avoided_reason` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:1347` | `_gate_sql_field` | False | 0 | 2 | 0 | 2 | 0 | 保留 | resolved prod=2 test=0 same=2 |
| `ming_sim/issues.py:1358` | `_eval_gate_key` | False | 0 | 0 | 0 | 3 | 0 | 保留 | 模块内互调 same=3（内联 helper） |
| `ming_sim/issues.py:1452` | `_eval_gate_key_str` | False | 0 | 0 | 0 | 2 | 0 | 保留 | 模块内互调 same=2（内联 helper） |
| `ming_sim/issues.py:1476` | `_gate_passed` | False | 0 | 3 | 32 | 8 | 0 | 保留 | resolved prod=3 test=32 same=8 |
| `ming_sim/issues.py:1517` | `gather_impeachment_surge_candidates` | False | 0 | 4 | 14 | 0 | 0 | 保留 | resolved prod=4 test=14 same=0 |
| `ming_sim/issues.py:1646` | `gather_candidate_events` | False | 0 | 10 | 59 | 0 | 0 | 保留 | resolved prod=10 test=59 same=0 |
| `ming_sim/issues.py:1696` | `apply_event_terminal_states` | False | 0 | 4 | 12 | 0 | 0 | 保留 | resolved prod=4 test=12 same=0 |
| `ming_sim/issues.py:1708` | `run_terminal_state_pass` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `apply_event_terminal_states`；局部 helper |
| `ming_sim/issues.py:1751` | `auto_trigger_seed_issues` | False | 0 | 4 | 19 | 0 | 0 | 保留 | resolved prod=4 test=19 same=0 |
| `ming_sim/issues.py:1765` | `_auto_trigger_seed_issues_in_atomic` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:1850` | `_bar_ascii` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:1856` | `_format_inertia` | False | 0 | 0 | 0 | 1 | 0 | 保留 | 模块内互调 same=1（内联 helper） |
| `ming_sim/issues.py:1864` | `show_active_issues` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:1873` | `_print_row` | True | 0 | 0 | 0 | 2 | 0 | 保留 | 嵌套于 `show_active_issues`；局部 helper |
| `ming_sim/issues.py:1895` | `event_to_issue` | False | 0 | 3 | 3 | 1 | 0 | 保留 | resolved prod=3 test=3 same=1 |
| `ming_sim/issues.py:1997` | `_normalize_cancellable` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:2012` | `_compute_inertia` | False | 0 | 1 | 0 | 0 | 0 | 保留 | resolved prod=1 test=0 same=0 |
| `ming_sim/issues.py:2031` | `_content_population_effect_for_save` | False | 0 | 2 | 0 | 4 | 0 | 保留 | resolved prod=2 test=0 same=4 |
| `ming_sim/issues.py:2072` | `neutralize_covert_fiscal_effects` | False | 0 | 2 | 0 | 0 | 0 | 保留 | resolved prod=2 test=0 same=0 |
| `ming_sim/issues.py:2157` | `record_secret_order_disclosure` | False | 0 | 4 | 0 | 0 | 0 | 保留 | resolved prod=4 test=0 same=0 |
| `ming_sim/issues.py:2209` | `clear_gated_legacies` | False | 0 | 3 | 0 | 0 | 0 | 保留 | resolved prod=3 test=0 same=0 |
| `ming_sim/issues.py:2230` | `sync_opening_legacies` | False | 0 | 2 | 4 | 0 | 0 | 保留 | resolved prod=2 test=4 same=0 |

## C1/C3 删简闸（本轮实查）

| 闸 | 结果 |
|---|---|
| 顶层 resolved_prod=0 且 same_module=0 | **0** |
| 顶层单调用转发壳（forwarder） | **0**（`return any/set(...)` 已排除为 builtin，不记壳） |
| 仅 uncertain Attribute、无 resolved/same | **0** |
| 跨模块同名且语义重复（C1 平行核） | **本轮已处置 1**：`_event_outcome_label` 删 preflight 副本，保留 issues 真源（有消费者仍 DRY） |
| 跨模块同名且语义**不**重复 | **2**（`bind_content` / `_ctx` — 保留） |

## 修后闸

- TARGET_DEFS=98
- WITH_CROSS_MODULE_SAME_NAME=2
- TOPLEVEL_ZERO_RESOLVED_PROD_AND_SAME=0
- TOPLEVEL_FORWARDER_FLAG=0
- 本轮生产删码：`settlement/preflight.py` `_event_outcome_label` 副本（C1 DRY）；上轮四处删除仍成立
