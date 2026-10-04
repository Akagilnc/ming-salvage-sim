# #1835 w5 C1/C3 补扫全表处置（situation_drift / displaced_population / issues）

纠正上轮「AST 无 def/reexport」收窄：上轮谓词盯点名旧核符号，未对三模块**全部顶层与嵌套 def**做同名跨仓消费者全表。

## 枚举命令（真实执行）

```sh
python3 <<'PY'
# AST walk FunctionDef/AsyncFunctionDef (top+nested) in:
#   ming_sim/situation_drift.py
#   ming_sim/displaced_population.py
#   ming_sim/issues.py
# Consumers: Name/Attribute Load + ImportFrom across ming_sim+tests+web_app.py
# Plus module-level KINDS/ALLCAPS/_CONST assigns in the three files
# Plus cross-repo same-name check for _commitment_bar_value vs commitment_display
PY
```

原始输出：`enumeration-raw.txt`（修前）+ `enumeration-post.txt`（修后，DEFS=98）。

## 本轮删除（修前枚举命中）

| 路径 | 成员 | 分类 | 处置依据 |
|---|---|---|---|
| `situation_drift.py` | `default_situation_shape` | C3 零消费者 | AST total=0；与 `event_to_issue` 内联 kind 表同形死副本 |
| `situation_drift.py` | `_commitment_bar_value` | C1 同形重复零调用 | 本模块内无 Name 调用；唯一 Attribute 调用方指向 `commitment_display._commitment_bar_value` |
| `issues.py` | `_situation_terminal_effects` | C1/C3 单调用转接壳 | 唯一调用在 `event_to_issue`；体为 lazy-import+return；已改为调用点直接接 `situation_drift.situation_terminal_effects` |
| `issues.py` | `_COLLAPSIBLE_KINDS` | C3 零引用常量 | 原壳附属；真源 `COLLAPSIBLE_SITUATION_KINDS` |

## 修后全表：defs

| 路径:行 | 成员 | nested | same | cross | 处置 | 依据 |
|---|---|---|---|---|---|---|
| `ming_sim/situation_drift.py:47` | `situation_terminal_effects` | False | 0 | 2 | 保留 | 真源；`issues.event_to_issue` 直接 ImportFrom+调用（#1901） |
| `ming_sim/situation_drift.py:60` | `_metrics` | True | 2 | 0 | 保留 | 嵌套于 `situation_terminal_effects`；局部 helper |
| `ming_sim/situation_drift.py:73` | `_commitment_ongoing_effects_for_settlement` | False | 1 | 0 | 保留 | 仅被 apply_situation_monthly_drift / 既有承诺测消费 |
| `ming_sim/situation_drift.py:106` | `_resolve_commitment_issue` | False | 2 | 2 | 保留 | 仅被 apply_situation_monthly_drift / 既有承诺测消费 |
| `ming_sim/situation_drift.py:151` | `_expire_commitment_issue` | False | 1 | 3 | 保留 | 仅被 apply_situation_monthly_drift / 既有承诺测消费 |
| `ming_sim/situation_drift.py:195` | `apply_situation_monthly_drift` | False | 0 | 25 | 保留 | month_chain 唯一世界漂移接线；多测直接调用 |
| `ming_sim/displaced_population.py:32` | `surcharge_population_pool_members` | False | 1 | 0 | 保留 | month_chain levy 接线 / 模块内互调（#1901） |
| `ming_sim/displaced_population.py:42` | `apply_levy_driven_transfers` | False | 0 | 2 | 保留 | month_chain levy 接线 / 模块内互调（#1901） |
| `ming_sim/issues.py:64` | `_issue_condition_text` | False | 1 | 3 | 保留 | 同文件1+跨文件3 真实消费者 |
| `ming_sim/issues.py:74` | `_normalize_commitment_kind` | False | 0 | 3 | 保留 | 同文件0+跨文件3 真实消费者 |
| `ming_sim/issues.py:81` | `_validate_commitment_stop_condition` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:109` | `bind_content` | False | 0 | 200 | 保留 | 同文件0+跨文件200 真实消费者 |
| `ming_sim/issues.py:115` | `_ctx` | False | 11 | 46 | 保留 | 同文件11+跨文件46 真实消费者 |
| `ming_sim/issues.py:121` | `_canonical_issue_origin` | False | 0 | 7 | 保留 | 同文件0+跨文件7 真实消费者 |
| `ming_sim/issues.py:133` | `commitment_condition_role` | False | 0 | 2 | 保留 | 同文件0+跨文件2 真实消费者 |
| `ming_sim/issues.py:148` | `_legacy_commitment_stop_gate` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:156` | `_commitment_stop_gate` | False | 2 | 10 | 保留 | 同文件2+跨文件10 真实消费者 |
| `ming_sim/issues.py:168` | `_commitment_remaining_from_gate` | False | 0 | 2 | 保留 | 同文件0+跨文件2 真实消费者 |
| `ming_sim/issues.py:203` | `_latest_commitment_paid_total` | False | 0 | 2 | 保留 | 同文件0+跨文件2 真实消费者 |
| `ming_sim/issues.py:221` | `_commitment_gate_references_arrears` | False | 0 | 7 | 保留 | 同文件0+跨文件7 真实消费者 |
| `ming_sim/issues.py:225` | `_commitment_arrears_gate_army_ids` | False | 0 | 3 | 保留 | 同文件0+跨文件3 真实消费者 |
| `ming_sim/issues.py:239` | `_monthly_person_rating_changes` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:257` | `_invalid_monthly_person_rating_reason` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:275` | `_person_change_has_unsupported_monthly_work` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:288` | `_unsupported_monthly_ongoing_fields` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:304` | `_monthly_ongoing_effects_has_work` | False | 0 | 7 | 保留 | 同文件0+跨文件7 真实消费者 |
| `ming_sim/issues.py:321` | `_ack_due_commitment_issue` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:355` | `_event_issue_refs` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:363` | `_event_trigger_refs` | False | 2 | 1 | 保留 | 同文件2+跨文件1 真实消费者 |
| `ming_sim/issues.py:367` | `_event_terminal_states` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:376` | `_event_terminal_records` | False | 4 | 0 | 保留 | 同文件4+跨文件0 真实消费者 |
| `ming_sim/issues.py:415` | `_normalize_event_terminal_reason` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:426` | `_fiscal_levy_normalized_terminal_reason_or_abort` | False | 2 | 2 | 保留 | 同文件2+跨文件2 真实消费者 |
| `ming_sim/issues.py:442` | `_canonicalize_existing_fiscal_levy_terminal_reason` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:463` | `_as_float` | False | 11 | 0 | 保留 | 同文件11+跨文件0 真实消费者 |
| `ming_sim/issues.py:475` | `_is_stored_number` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:479` | `_fiscal_levy_liao_seed` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:488` | `_fiscal_levy_base_transport` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:506` | `_fiscal_levy_event_by_id` | False | 3 | 4 | 保留 | 同文件3+跨文件4 真实消费者 |
| `ming_sim/issues.py:510` | `_fiscal_levy_event_approved` | False | 3 | 0 | 保留 | 同文件3+跨文件0 真实消费者 |
| `ming_sim/issues.py:521` | `_fiscal_levy_stopped` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:532` | `_fiscal_levy_land_share_amount` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:542` | `_fiscal_levy_land_denominator` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:559` | `_load_region_fiscal_for_fiscal_levy` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:578` | `_fiscal_levy_share_seed` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:591` | `_validate_fiscal_levy_share_meta` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:601` | `_fiscal_levy_mark_provisional` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:615` | `_jiao_levy_in_force` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:630` | `_apply_fiscal_levy_targets` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:765` | `apply_historical_fiscal_rates` | False | 0 | 41 | 保留 | 同文件0+跨文件41 真实消费者 |
| `ming_sim/issues.py:781` | `run_fiscal_levy_pass` | True | 2 | 0 | 保留 | 嵌套于 `apply_historical_fiscal_rates`；局部 helper |
| `ming_sim/issues.py:818` | `_numeric_predicate_accepts` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:832` | `_event_triggered_numeric_dependency_kind` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:845` | `_event_dependency_ids` | False | 3 | 0 | 保留 | 同文件3+跨文件0 真实消费者 |
| `ming_sim/issues.py:857` | `_validate_event_dependency_graph_acyclic` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:872` | `dfs` | True | 2 | 0 | 保留 | 嵌套于 `_validate_event_dependency_graph_acyclic`；局部 helper |
| `ming_sim/issues.py:895` | `_event_chain_impossible_reason` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:901` | `_format_values` | True | 4 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:904` | `allow_states` | True | 2 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:922` | `allow_state` | True | 2 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:925` | `allow_outcomes` | True | 1 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:943` | `forbid_state` | True | 1 | 0 | 保留 | 嵌套于 `_event_chain_impossible_reason`；局部 helper |
| `ming_sim/issues.py:1013` | `apply_event_cascading_invalidations` | False | 4 | 17 | 保留 | 同文件4+跨文件17 真实消费者 |
| `ming_sim/issues.py:1031` | `run_cascade` | True | 2 | 0 | 保留 | 嵌套于 `apply_event_cascading_invalidations`；局部 helper |
| `ming_sim/issues.py:1067` | `_spawned_event_refs` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:1073` | `_event_window_open` | False | 6 | 2 | 保留 | 同文件6+跨文件2 真实消费者 |
| `ming_sim/issues.py:1091` | `_event_outcome_label` | False | 2 | 5 | 保留 | 同文件2+跨文件5 真实消费者 |
| `ming_sim/issues.py:1100` | `_merge_first_event_outcome` | False | 0 | 6 | 保留 | 同文件0+跨文件6 真实消费者 |
| `ming_sim/issues.py:1125` | `apply_petition_event_outcome` | False | 0 | 8 | 保留 | 同文件0+跨文件8 真实消费者 |
| `ming_sim/issues.py:1190` | `gather_fiscal_levy_petitions` | False | 0 | 7 | 保留 | 同文件0+跨文件7 真实消费者 |
| `ming_sim/issues.py:1215` | `petition_outcome_is_admissible` | False | 0 | 4 | 保留 | 同文件0+跨文件4 真实消费者 |
| `ming_sim/issues.py:1239` | `_closed_outcome_labels` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:1246` | `strategic_event_outcome_labels` | False | 0 | 5 | 保留 | 同文件0+跨文件5 真实消费者 |
| `ming_sim/issues.py:1259` | `_event_window_expired` | False | 7 | 0 | 保留 | 同文件7+跨文件0 真实消费者 |
| `ming_sim/issues.py:1272` | `_dead_person_core_subjects` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:1284` | `_person_core_avoided_reason` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:1347` | `_gate_sql_field` | False | 2 | 2 | 保留 | 同文件2+跨文件2 真实消费者 |
| `ming_sim/issues.py:1358` | `_eval_gate_key` | False | 3 | 0 | 保留 | 同文件3+跨文件0 真实消费者 |
| `ming_sim/issues.py:1452` | `_eval_gate_key_str` | False | 2 | 0 | 保留 | 同文件2+跨文件0 真实消费者 |
| `ming_sim/issues.py:1476` | `_gate_passed` | False | 8 | 35 | 保留 | 同文件8+跨文件35 真实消费者 |
| `ming_sim/issues.py:1517` | `gather_impeachment_surge_candidates` | False | 0 | 18 | 保留 | 同文件0+跨文件18 真实消费者 |
| `ming_sim/issues.py:1646` | `gather_candidate_events` | False | 0 | 69 | 保留 | 同文件0+跨文件69 真实消费者 |
| `ming_sim/issues.py:1696` | `apply_event_terminal_states` | False | 0 | 16 | 保留 | 同文件0+跨文件16 真实消费者 |
| `ming_sim/issues.py:1708` | `run_terminal_state_pass` | True | 2 | 0 | 保留 | 嵌套于 `apply_event_terminal_states`；局部 helper |
| `ming_sim/issues.py:1751` | `auto_trigger_seed_issues` | False | 0 | 23 | 保留 | 同文件0+跨文件23 真实消费者 |
| `ming_sim/issues.py:1765` | `_auto_trigger_seed_issues_in_atomic` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:1850` | `_bar_ascii` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:1856` | `_format_inertia` | False | 1 | 0 | 保留 | 同文件1+跨文件0 真实消费者 |
| `ming_sim/issues.py:1864` | `show_active_issues` | False | 0 | 2 | 保留 | 同文件0+跨文件2 真实消费者 |
| `ming_sim/issues.py:1873` | `_print_row` | True | 2 | 0 | 保留 | 嵌套于 `show_active_issues`；局部 helper |
| `ming_sim/issues.py:1895` | `event_to_issue` | False | 1 | 6 | 保留 | 同文件1+跨文件6 真实消费者 |
| `ming_sim/issues.py:1997` | `_normalize_cancellable` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:2012` | `_compute_inertia` | False | 0 | 1 | 保留 | 同文件0+跨文件1 真实消费者 |
| `ming_sim/issues.py:2031` | `_content_population_effect_for_save` | False | 4 | 2 | 保留 | 同文件4+跨文件2 真实消费者 |
| `ming_sim/issues.py:2072` | `neutralize_covert_fiscal_effects` | False | 0 | 2 | 保留 | 同文件0+跨文件2 真实消费者 |
| `ming_sim/issues.py:2157` | `record_secret_order_disclosure` | False | 0 | 4 | 保留 | 同文件0+跨文件4 真实消费者 |
| `ming_sim/issues.py:2209` | `clear_gated_legacies` | False | 0 | 3 | 保留 | 同文件0+跨文件3 真实消费者 |
| `ming_sim/issues.py:2230` | `sync_opening_legacies` | False | 0 | 6 | 保留 | 同文件0+跨文件6 真实消费者 |

## 修后全表：三模块顶层常量（KINDS/ALLCAPS/_CONST）

| 路径:行 | 成员 | same | cross | 处置 | 依据 |
|---|---|---|---|---|---|
| `ming_sim/situation_drift.py:42` | `COLLAPSIBLE_SITUATION_KINDS` | 1 | 0 | 保留 | situation_terminal_effects 真源集合 |
| `ming_sim/displaced_population.py:29` | `SETTLE_META_JIAPIAI_KEY` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:56` | `_content` | 2 | 5 | 保留 | 同文件2+跨文件5 引用 |
| `ming_sim/issues.py:58` | `COMMITMENT_KIND_UNTIL_STOP` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:59` | `_FISCAL_LEVY_TARGET_ABS_TOL` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:390` | `FISCAL_LEVY_EVENT_CATEGORY` | 4 | 6 | 保留 | 同文件4+跨文件6 引用 |
| `ming_sim/issues.py:391` | `_LIAO_LEVY_RISE_EVENT_ID` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:392` | `_LIAN_LEVY_START_EVENT_ID` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:393` | `_LIAO_LEVY_RISE_FACTOR` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:394` | `_JIAO_LEVY_START_EVENT_ID` | 3 | 0 | 保留 | 同文件3+跨文件0 引用 |
| `ming_sim/issues.py:395` | `_JIAO_LEVY_STOP_EVENT_ID` | 3 | 0 | 保留 | 同文件3+跨文件0 引用 |
| `ming_sim/issues.py:396` | `_JIAO_LEVY_NATIONAL_MONTHLY` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:397` | `_LIAN_LEVY_NATIONAL_MONTHLY` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:398` | `_SETTLE_META_BASE_TRANSPORT_KEY` | 5 | 0 | 保留 | 同文件5+跨文件0 引用 |
| `ming_sim/issues.py:399` | `_SETTLE_META_LIAO_SEED_KEY` | 5 | 0 | 保留 | 同文件5+跨文件0 引用 |
| `ming_sim/issues.py:400` | `_SETTLE_META_JIAO_SEED_KEY` | 5 | 0 | 保留 | 同文件5+跨文件0 引用 |
| `ming_sim/issues.py:401` | `_SETTLE_META_LIAN_SEED_KEY` | 5 | 0 | 保留 | 同文件5+跨文件0 引用 |
| `ming_sim/issues.py:402` | `_SETTLE_META_LAND_DENOMINATOR_KEY` | 6 | 0 | 保留 | 同文件6+跨文件0 引用 |
| `ming_sim/issues.py:406` | `_FISCAL_LEVY_PROVISIONAL_KEYS` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:815` | `_EVENT_GATE_KEY_RE` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:854` | `_EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:1302` | `_GATE_AGG_FUNCS` | 2 | 3 | 保留 | 同文件2+跨文件3 引用 |
| `ming_sim/issues.py:1310` | `_CHARACTER_NUMERIC_GATE_FIELDS` | 1 | 0 | 保留 | 同文件1+跨文件0 引用 |
| `ming_sim/issues.py:1322` | `_GATE_NUMERIC_SQL_FIELDS` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |
| `ming_sim/issues.py:1332` | `_GATE_TEXT_SQL_FIELDS` | 3 | 0 | 保留 | 同文件3+跨文件0 引用 |
| `ming_sim/issues.py:1339` | `_GATE_SQL_FIELDS` | 2 | 0 | 保留 | 同文件2+跨文件0 引用 |

## 跨仓同名核对（C1）

| 符号 | 定义点 | 调用点 | 处置 |
|---|---|---|---|
| `_commitment_bar_value` | `commitment_display.py:146`（唯一存活） | `situation_drift.apply_situation_monthly_drift` → `commitment_display._commitment_bar_value` | **保留**真源；situation_drift 同形副本已删 |
| `situation_terminal_effects` | `situation_drift.py` | `issues.event_to_issue` 直接 import | **保留**真源；issues 转接壳已删 |
| `default_situation_shape` | （已删） | 无 | 开局形状以 `event_to_issue` 内联为准 |

## 注释/空白清理

| 文件 | 处置 |
|---|---|
| `entities/affair/store.py` | 模块 docstring 去掉退役 `declare_closed` 词面 |
| `materials.py` | 可见事务 docstring 去掉退役 `declare_closed` 词面 |
| `constants.py` | `COURT_BREAK_COMMANDS` 注释去掉「今日且到此」退役叙事 |
| `settlement/registry.py` | EOF 多余空行收成单换行 |
| `evidence/issue-1835/w5-fixer-report.md` | 行尾空白清除（6 处） |

## 修后闸

- 顶层 def 零引用残留：0
- 常量零引用残留：0

