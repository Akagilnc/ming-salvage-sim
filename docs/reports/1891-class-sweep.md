# #1891 三类整类修复回执附件

基线：`8ad1ee740`（#1891/#1899 组合现场，不是家族底座）。#1899 财政消费写口不改。本附件记录首轮 b1900c284；其枚举范围和 #1625 归因被退回，修正及本轮增量成员表见 [复审修理回执](1891-review-repair.md)。

## 枚举方法

候选不是结论：按实际供给、消费者与字段值域分类；测试不是现役消费者。

```sh
git ls-files '*.py' '*.ts' '*.tsx' '*.js' '*.sh'
# 对存在的上述文件逐个执行：
rg -n '\.(strip|rstrip|lstrip|trim|trimStart|trimEnd|slice|substring|substr|replace)\(|\[[^]]*:[^]]*\]|truncate|summari[sz]|shorten|clip|max_chars|max_length|char_limit' <files>
rg -n 'world_translate|world_continue|decree_continue|translate_exhaust_stops|continuation_ready|decree_continuations' ming_sim tests
```

退役枚举另用 Python `ast.parse` / `ast.walk` 遍历所有 tracked Python，覆盖顶层函数、类、类方法和嵌套闭包：收集现役源码的 Name(load)、Attribute、ImportFrom 和显式字符串标识符引用，反查供给/消费者，删空闭包后再迭代依赖。单次出现只是候选，另外复核声明的实际 SDK/协议消费者。跨文件 import/re-export 单独复核，真实消费者直连已有权威模块，不恢复兼容别名。成员表使用限定名，删除父闭包时子声明随之删除，不重复记账。

首轮全部 tracked Python 的 `from ming_sim.* import X` 真源绑定缺项为 `[]`，但声明候选扫描错误地只覆盖 ming_sim，漏了 web_app 等现役源码；「全作用域只剩九项」结论撤回。以下九项只是 ming_sim 子集的协议保留项，最终全仓结果见复审修理回执：

| 保留成员 | 实际消费者 |
| --- | --- |
| applier._SuspendableConnection.__enter__/__exit__ | Python with 协议 |
| cli_backend.CliChat.ainvoke/ainvoke_stream | Agno/OpenAIChat model 协议的异步 override |
| decree._PromulgationJudgeSession.__post_init__ | dataclass 初始化协议 |
| session_write_queue.ClassifiedWriteGate.__enter__/__exit__ | Python with 协议 |
| session_write_queue.TicketedWriteGate.__enter__/__exit__ | Python with 协议 |

现役注册回调、数据 schema 和方法依实际供给/消费者保留，不因 Name 计数缺项删除；手工核对不以样本名或单次出现计数代替类别结清。

## 类 1：完整续推段转译耗尽

| 成员 | 处置 |
| --- | --- |
| world_translate | 原统一逃生契约保留 |
| world_continue + world_continuation_ready | 完整未提交文转译耗尽计入同一逃生次数；逃生只清续推文/ready |
| decree_continue + decree_continuations[decree_ref] | 同契约；逃生只清对应旨意的续推缓存 |
| world_continue/decree_continue 尚无完整缓存 | 属生成失败，不误计完整段转译逃生 |
| 两类续推成功提交 | 清同一转译耗尽计数 |

奏疏、亲笔批语、问前实账、已提交世界/旨意效果均不在丢弃集合；恢复仍由原批红/月链入口承接，没有新重试器。

## 类 2：自由字段成员表

下列为实际传输、写库或诊断成员；验空使用副本，传输保留原串。已随类 3 消失的转译/票拟旧诊断、流式思考截断与旧密令内容拼装不另造替代版本。

| 文件 | 自由字段/操作 | 处置 |
| --- | --- | --- |
| assets.py | load_text_asset 文件正文 | 不 strip；显式模板变量替换保留 |
| audience_translate.py | target_grounding | 原串供给，副本验空 |
| cli_backend.py | player_message、军名；provider stdout/stderr 诊断 | 原串；去长度上限 |
| content.py | Event.category | 原样赋值 |
| covert_progress.py | kind、investigation_target、category、invalid | 原样构约/传输；副本验空；类别匹配不裁剪 |
| db.py | 新军 name；military_order station 入载荷/写核 | 原串写入，station_region ID 另处理 |
| db.py | progress_band 入奏报/读面/成批供给 | 原串；副本验空 |
| db.py | 案卷 tags 的自由文本条目 | 原串写入；空项只验空 |
| db.py | secret_order title/note/progress/sim_note 日志、坏 JSON 诊断 | 去长度上限 |
| db.py | reason_code 长度截断 | 去上限，闭集校验另存 |
| issues.py | legacy.name | 原串，空值才补默认 |
| issues.py | controller/title/sim_note 审计及日志 | 去 strip/长度上限；控制者身份核验保留 |
| llm_contract.py | raw 输出诊断 | 无长度上限 |
| agents.py | run_agent_text JSON 失败的 raw 输出 | 无长度上限 |
| llm_model.py / llm_transport.py | provider_message | 原错误串，副本验空才补缺省 |
| relation_brew.py / faction_brew.py | raw 输出诊断 | 无长度上限 |
| rescript_draft.py | 仍现役的 JSON 解析 raw 诊断 | 无长度上限 |
| rescript_actions.py / settlement_payload.py | decision.note/label；option label；已形成的请旨/拟批列表；军令 station | 原串；按原 label 精确绑定；删除 5 条请旨及 3 条拟批的旧截取上限 |
| session.py | source_label | 原串写入 |
| staged_commitment.py | stages_json 失败诊断 | 原始输入不截断 |
| web_app.py | 并发失败 reason 的 HTTP detail | 原串 |
| web/src/settleStream.ts | HTTP 服务端 detail/message | 原串 throw，副本验空 |
| web/src/components/edictModal.tsx | source/actor 展示串 | 原串，副本验空 |
| scripts/play_as_emperor.py | reasoning/input、prompt_hint、action/history | 去 strip、首行截取与 200 字上限；原串传递 |
| scripts/family_tail_acceptance_570.py | 原有邸报 existing | 副本验空，返回原串 |
| scripts/jisi_army_dispatch_probe.py / military_flow_probe.py | report_head/text | 完整记录/输出，键不变 |
| scripts/direct_decree_probe.py / agy_turn_probe.py | SQL、旨文、标题、选项、邸报诊断 | 无长度上限 |
| scripts/secret_order_probe2.py | 邸报输出 | 全文，不再按人名/措辞择段 |

### 非成员及保留依据

- `decision_key`/`decree_ref`/`origin_ref`/region、army、character 身份及路径、模型配置：机器身份；包括负责机关与官职的身份解析。没有把相同字段中的人读正文归入此例外。
- action/type/status/account/purpose/transaction_category、person reason/identity titles、数值、JSON/fence/SSE、显式请旨机标：封闭值域或形式语言解析。可用规范化副本核验，不裁剪内含自由字段。
- `station` 在 admission 的局部副本仅判是否需要期限；真正运输/入账已传原串。`station_region` 是 ID。
- `knowledge_source` 实际消费者是关系图里的单个人物身份，非密奏段落；`investigation_fact`/fact_key 是证据键。原自由调查范围另已保留。
- latest/history 排序、机械实体/身份集合选择、hash/UUID/文件名、TS highlighting 的无损分段：不是裁剪自由正文。已形成的请旨/拟批列表不适用此例外，旧截取已删；Agno failed-run rollback 是事务恢复，不是正文压缩。
- UTF-8/SSE/SQLite 的编码与控制序列协议处理、已冻结卷宗的统计，和明确作者模板变量：不是按文案择取。资源原文、错误正文和 LLM 消息仍不做长度裁剪。
- `scripts/gen_portraits.py` 的旧白底正文没有现役 prompt 真源且入口先退出：整段退役，仅保留既有废弃入口的明确报错。
- prototype/archive/evidence、测试夹具以及格式化已知机械财政表：不作为生产自由正文供给；未靠这些候选来宣称现役字段结清。

## 类 3：退役成员表

表按文件列出全部删除闭包的限定名（171 个生产函数、7 个类、59 个方法、3 个脚本声明、307 个测试/辅助声明）；内嵌 helper 随所属闭包删除。旧密令拆选链、候选快照标题猜绑及其专属测试均在表中；其余成员沿相同无供给/无消费者形状枚举，不收窄到样本。空测试文件和失效财政投影/写点清单模块一并删除。仍有值轴消费者的 `CENTRIFUGE_AXES` 留作常量契约。当前字段 normalization/typed month-chain 接缝不恢复旧批量生成入口。

| 文件 | 删除声明 |
| --- | --- |
| `ming_sim/action_clusters.py` | `cluster_effect`, `effective_field_allowed` |
| `ming_sim/action_materialize.py` | `_authorization_privilege`, `_authorization_scope_parts`, `_resolve_unique_active_authority`, `minister_speaker_role`, `stage_authorization_candidate`, `stage_grant_allocation_candidate`, `stage_referral_candidate`, `stage_revoke_authority_candidate` |
| `ming_sim/agents.py` | `create_rescript_draft_agent`, `run_agent_stream_text` |
| `ming_sim/applier.py` | `ApplyContext`, `RejectionCollector.has_player_visible_rejection` |
| `ming_sim/appointment_tenure.py` | `command_power_rank`, `execution_distortion_weight` |
| `ming_sim/audience_night.py` | `_command_entry_has_tag_enter`, `_night_direct_write_allowed_tables`, `audience_scene_recap`, `audit_night_direct_writes`, `find_prior_speaker_still_present`, `list_arrived_unsettled_summons`, `list_night_timeline`, `night_dossiers_ready`, `persons_entered_tonight`, `persons_present_tonight` |
| `ming_sim/audience_translate.py` | `apply_audience_turn_translation`, `run_audience_turn_translation` |
| `ming_sim/centrifuge_ledger.py` | `_abort`, `_accrue_centrifuge`, `_clamp`, `_load_namespace`, `_null_safe_eq`, `_optional_text`, `_payloads_match`, `_require_axis`, `_require_idem_base`, `_require_int_in_range`, `_require_positive_int`, `_require_target`, `_require_turn`, `_resolve_target_faction_identity`, `accrue_blood_debt`, `accrue_detection_wariness`, `rebuild_centrifuge_cache` |
| `ming_sim/cli/terminal.py` | `_fail_cli_chat_turn_scene` |
| `ming_sim/cli_backend.py` | `_choose_assignee`, `_cli_prompt`, `_cli_recommendation_call`, `_cli_stream_safe_prefix`, `_content_reflects_emperor_intent`, `_extract_imperative_assignee`, `_extract_secret_order`, `_is_institution_like_name`, `_merge_secret_content`, `_normalize_dossier_link_proposals`, `_secret_landing_gap_feature`, `_secret_metadata_from_command`, `_secret_prefix_needs_recent_context`, `assemble_secret_order_content`, `compose_decree_validation_recovery`, `compose_secret_order_landing_recovery`, `confirm_dossier_links` |
| `ming_sim/content.py` | `dict_of_string_lists`, `dict_of_strings` |
| `ming_sim/context.py` | `event_context`, `first_character`, `first_character_name`, `format_metric_delta`, `historical_anchor_for_month`, `parse_json_dict`, `state_context` |
| `ming_sim/covert_progress.py` | `_current_game_turn`, `build_secret_covert_effect_briefs`, `contract_axes_direction`, `parse_covert_exec_selections` |
| `ming_sim/db.py` | `GameDB._has_secret_order_period_line`, `GameDB._insert_rescript_draft_rows`, `GameDB._is_active_secret_order_assignee`, `GameDB._is_audience_chat_shared_channel`, `GameDB._primary_source_only_army_pay_container_total`, `GameDB.append_rescript_drafts`, `GameDB.army_detail`, `GameDB.attach_secret_oral_pin`, `GameDB.building_detail`, `GameDB.clear_directive_needs_clarification`, `GameDB.clear_pending_decisions`, `GameDB.clear_resolve_context`, `GameDB.complete_rescript_summon_scaffold_turn`, `GameDB.count_active_initiatives`, `GameDB.discard_pending_directives`, `GameDB.drop_pending_actions_for_minister`, `GameDB.executable_decree_dossier_ids`, `GameDB.faction_report`, `GameDB.flag_directive_needs_clarification`, `GameDB.get_faction_stance_summary`, `GameDB.get_message_highlights`, `GameDB.list_dossier_actual_progress`, `GameDB.list_dossier_actual_rail`, `GameDB.list_dossier_link_rejections`, `GameDB.list_dossiers_for_directive`, `GameDB.list_endorsed_dossier_candidates`, `GameDB.list_execution_liability_parties`, `GameDB.list_night_promulgated_directives`, `GameDB.list_office_effects_for_dossier`, `GameDB.list_office_vacancies`, `GameDB.list_open_grant_reconciliations`, `GameDB.list_promulgated_directives`, `GameDB.list_recent_issue_advances`, `GameDB.mark_chat_turn_failed`, `GameDB.read_credit_events_as_edges`, `GameDB.record_economy_moves`, `GameDB.record_monthly_supervision_facts`, `GameDB.reject_directive`, `GameDB.save_pending_promulgation_verdicts`, `GameDB.save_rescript_drafts`, `GameDB.settle_province_tick`, `GameDB.treasury_ledger`, `GameDB.turn_army_summary`, `GameDB.turn_economy_summary`, `GameDB.turn_power_summary`, `GameDB.turn_region_summary`, `GameDB.upsert_pending_directive`, `GameDB.upsert_secret_order` |
| `ming_sim/decree.py` | `_collect_compliant_promulgation_items`, `_dossier_ids_from_simulator_payload`, `_merge_compliant_promulgation_items`, `_open_affair_ids_from_payload`, `_promulgable_proposed_dossiers`, `execution_side_read_fields`, `resolve_executor_appointment_tenure` |
| `ming_sim/due_review.py` | `current_audience_scene` |
| `ming_sim/entities/affair/store.py` | `AffairStore.experiences`, `AffairStore.point_dossier`, `AffairStore.point_issue` |
| `ming_sim/entities/textual_fact/store.py` | `TextualFactStore.pointing_at` |
| `ming_sim/fiscal_fact_brief.py` | `_arrears_order_displacement_entries`, `_config_origin_ref`, `_current_turn`, `_due_order_displacement_entries`, `_fmt_num`, `_latest_provenance_origin`, `_ming_settle_bases`, `_pay_order_displacement_entries`, `_priority_override_origin`, `_priority_override_origin_for`, `_waterfall_allocate`, `build_fiscal_fact_brief`, `format_fiscal_fact_brief_tsv` |
| `ming_sim/flows.py` | `_fiscal_container_value`, `_province_collection_rate`, `_province_transport_ratio` |
| `ming_sim/issues.py` | `validate_delta_shape` |
| `ming_sim/knowledge.py` | `project_issue_materials` |
| `ming_sim/llm_contract.py` | `require_bool`, `require_int_range`, `require_non_empty_text` |
| `ming_sim/materials.py` | `MaterialsRoot`, `_character_gazette_rows`, `_handled_affair_lines`, `_materials_invocation_dir`, `_present_names`, `_spoken_this_scene`, `_visible_affair_lines`, `_write_army_detail_files`, `_write_recommendation_file`, `_write_region_detail_files`, `_write_secret_order_file`, `_write_textual_fact_files`, `_write_tree`, `character_materials_root`, `minimal_opening_context`, `prepare_character_materials`, `release_previous_material_tree` |
| `ming_sim/models.py` | `ChatResult`, `CourtContext` |
| `ming_sim/month_translate.py` | `stage_month_segment` |
| `ming_sim/pay_order.py` | `revoke_pay_order_decree` |
| `ming_sim/person_write_inventory.py` | `_call_name`, `_enclosing_function_name`, `_inventory_location`, `_is_sql_execute_argument`, `_write_locations_in_source`, `discover_character_write_sql_locations`, `person_write_locations_by_disposition` |
| `ming_sim/qualitative.py` | `disaster_severity_band`, `qualitative_character_attribute` |
| `ming_sim/relation_brew.py` | `run_month_end_relation_brew` |
| `ming_sim/relations.py` | `credit_event_to_edge`, `credit_events_as_edges` |
| `ming_sim/report.py` | `build_period_report`, `format_army_changes`, `format_power_changes`, `format_region_changes`, `status_delta`, `status_delta_from_delta` |
| `ming_sim/rescript_draft.py` | `RescriptOptionMissingFailure`, `RescriptOptionMissingFieldsBatch`, `_apply_option_heal`, `_assert_utf8`, `_board_issue_ids`, `_contract_exc_to_top_failure`, `_drop_options_by_failures`, `_explicit_heal_id`, `_failure_log_rows`, `_find_healed_unit_for_failure`, `_healed_options_by_id`, `_item_failure`, `_item_heal_id`, `_merge_healed_missing_options`, `_missing_field_heal_feedback`, `_option_failure_from_exc`, `_option_heal_id`, `_top_failure`, `_top_heal_id`, `_ungrounded_roster_person_failure`, `_with_heal_response_contract_failure`, `_write_degraded_note`, `generate_rescript_draft`, `select_triage_actor`, `validate_rescript_draft_items` |
| `ming_sim/session.py` | `GameSession.list_ministers`, `GameSession.write_decree`, `MinisterView`, `_target_active_officeholder` |
| `ming_sim/session_write_queue.py` | `ClassifiedWriteGate.holder_kind`, `SessionWriteQueue.is_sealed`, `SessionWriteQueue.run_exclusive`, `SessionWriteQueue.vacate` |
| `ming_sim/settlement_payload.py` | `bind_decisions_to_candidate_events` |
| `ming_sim/token_stats.py` | `record_stream_metrics` |
| `ming_sim/value_matrix.py` | `_loaded`, `axis_collision_stances`, `faction_axis_stance`, `matrix_snapshot`, `mean_aligned_stance`, `value_axes` |
| `scripts/gen_portraits.py` | `gen_one`, `main`, `parse_entries` |
| `tests/test_advance_paths_atomic.py` | `test_draft_mutators_frozen_at_front_half_done` |
| `tests/test_applier_contract.py` | `test_apply_context_holds_all_fields` |
| `tests/test_army_card_status_1501.py` | `test_shared_consumers_still_surface_status` |
| `tests/test_army_display_173.py` | `test_army_arrears_presentation_rounds_half_steps_up`, `test_army_public_exits_approx_arrears_and_hide_split_accounts` |
| `tests/test_army_firearms.py` | `test_army_public_exits_surface_firearm_and_cannon` |
| `tests/test_audience_continuous_507.py` | `test_present_roster_reflects_command_dismissal`, `test_qianqing_continuous_night_skeleton_runs`, `test_scene_recap_excludes_dialogue_before_person_entered`, `test_scene_recap_quotes_public_dialogue_within_presence_interval` |
| `tests/test_audience_night_498.py` | `test_close_night_crash_then_reopen_db_resumes_idempotent`, `test_cross_night_directive_reassigned_to_second_night`, `test_two_nights_isolated_and_timeline_alignable`, `test_write_decree_leaves_unacted_pending_unchanged` |
| `tests/test_audience_travel_gating_670.py` | `test_continuation_arrival_settles_origin_without_waiting`, `test_inactive_person_skips_continuation_and_retires_on_month`, `test_multi_origin_same_person_dedupes_consumer_projections_not_ledger`, `test_waiting_active_departure_settles_and_does_not_revive`, `test_waiting_inactive_retires_on_month` |
| `tests/test_audience_undo_506.py` | `test_attach_origin_bind_atomic_no_orphan_enter_on_midway_crash`, `test_audit_passes_whitelisted_and_catches_unwhitelisted_night_write`, `test_reject_pending_discards_inactive_office_summon_origin`, `test_undo_erases_round_from_night_ledger_and_presence`, `test_undo_full_reversal_survives_kill_and_reopen`, `test_undo_removes_unlisted_person_registration` |
| `tests/test_breach_plea_623.py` | `test_model_execution_verdict_lands_after_persist` |
| `tests/test_centrifuge_ledger_690.py` | `test_t10_partial_preinserted_key_aborts`, `test_t11_rebuild_clears_dirty_and_write_path_rolls_back`, `test_t12_restore_preserves_tables_and_rebuild`, `test_t14_reason_code_sets_and_reject_unrecognized`, `test_t1_confiscation_direct_anchors_via_public_api`, `test_t2_kinship_uses_unrounded_formula`, `test_t2b_legitimacy_uses_raw_for_amounts`, `test_t3_zero_delta_empty_namespace_is_legal_noop`, `test_t4_happy_path_and_forbidden_kwargs`, `test_t5_bastinado_overdraw_batch_and_non_bastinado`, `test_t6_bad_target_aborts_with_zero_write`, `test_t6b_non_int_identity_aborts_with_zero_write`, `test_t7_cross_faction_isolation`, `test_t8_detection_wariness_only_kinship`, `test_t9_idempotency_namespace_and_empty_planned` |
| `tests/test_character_knowledge_489.py` | `_office_archive_from_materials`, `test_central_ledgers_and_unbounded_household_history_reach_final_materials`, `test_current_state_facts_are_selected_by_content_domain_not_role_label`, `test_inner_court_materials_do_not_read_faction_report` |
| `tests/test_cli_backend.py` | `_patch_backend`, `_so_json`, `test_api_backend_streaming_emits_real_token_deltas`, `test_codex_streaming_runner_degrades_to_oneshot_final`, `test_extract_secret_order_preserves_long_title_without_formal_cap`, `test_luna_shaped_stream_keeps_content_when_reasoning_deltas_interleave`, `test_secret_content_assembly_is_emperor_plus_extractor_only`, `test_secret_exclusion_extracts_people_and_offices`, `test_secret_extract_traces_exactly_once` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_accepts_retry_reply_command` |
| `tests/test_decision_event_binding_389.py` | `test_ambiguous_title_remains_unbound`, `test_missing_event_id_binds_from_unique_title`, `test_no_snapshot_returns_decisions_unchanged`, `test_offsnapshot_echoed_event_id_does_not_win_over_snapshot`, `test_offsnapshot_id_with_no_title_match_is_unbound`, `test_valid_echoed_event_id_is_trusted_unchanged` |
| `tests/test_decree_dossiers_571.py` | `test_appointment_alias_uses_canonical_dossier_identity`, `test_cli_edit_replaces_text_and_mechanics_before_promulgation`, `test_pending_directive_only_enters_settlement_after_final_approval` |
| `tests/test_dossier_links_559.py` | `test_pending_rejection_does_not_follow_reused_rolled_back_source_id`, `test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited`, `test_unknown_target_link_is_rejected_and_audited` |
| `tests/test_draft_admission_resubmit_1769.py` | `_write_decree_capture_payloads`, `test_draft_admission_exhaust_keeps_draft_and_advances` |
| `tests/test_execution_joint_liability_565.py` | `test_assistant_row_delegator_gets_secondary_assistant_zero_mechanical`, `test_dual_role_lead_and_delegator_primary_wins`, `test_liability_query_excludes_knowers_but_keeps_delegator_fk` |
| `tests/test_execution_pressure_654.py` | `test_authorization_region_gets_single_locality`, `test_authorization_region_to_character_amendment_clears_single_locality`, `test_get_dossier_for_directive_existence_sentinel`, `test_grant_region_to_character_amendment_clears_single_locality`, `test_named_lead_bulk_single_region_syncs_executor`, `test_national_creates_one_row_idempotent`, `test_path2_pending_bad_roster_stays_draft_on_ensure_batch`, `test_path3_locality_fail_keeps_draft_no_text_in_rejection`, `test_validate_all_unknown_roster_name_zero_rows_before_insert` |
| `tests/test_execution_tenure_613.py` | `_live_exec_side`, `test_command_power_four_tier_strict_order_and_jianshu_not_collapsed`, `test_held_authority_privileges_reduce_distortion_weight`, `test_td8_same_office_four_tenures_live_assembly_chain` |
| `tests/test_faction_brew_637.py` | `test_any_endpoint_hit_selects_and_same_faction_dedups`, `test_authority_revoke_edge_reaches_holder_faction_with_emperor_target`, `test_both_endpoints_different_factions_both_selected`, `test_event_month_updates_stance_and_no_event_month_byte_identical`, `test_faction_apply_db_error_propagates_loudly_not_disguised`, `test_faction_brew_prompt_retry_month_does_not_label_old_events_as_current_month`, `test_faction_claim_db_error_propagates_loudly`, `test_failed_faction_brew_rebrews_once_via_existing_pending_seam`, `test_malformed_faction_output_degrades_and_keeps_old_summary_bytes`, `test_out_of_table_faction_and_unknown_person_never_projected`, `test_relation_and_faction_items_share_single_batch_in_parallel`, `test_zero_writes_to_factions_numeric_columns_across_all_seams` |
| `tests/test_fiscal_substrate_bridge.py` | `test_liaodong_primary_source_due_survives_fresh_db_pay_source_reconcile`, `test_liaodong_settle_tick_keeps_standalone_funnel_deficit_out_of_pay_rows`, `test_province_pay_shortfall_reduces_pure_province_army_morale`, `test_province_tick_derives_due_and_allocates_province_arrears_by_pay_source`, `test_settle_province_tick_nondict_fiscal_raises`, `test_settle_province_tick_persists_border_remainder_golden`, `test_settle_province_tick_persists_shaanxi_historical_shadow_golden`, `test_settle_province_tick_port_lock_no_persist_on_raise`, `test_settle_province_tick_qingzhang_action`, `test_settle_province_tick_unknown_region_raises`, `test_shadow_spine_uses_batch_bridge_without_per_region_reload`, `test_south_southwest_settle_tick_golden_and_bridge_persist`, `test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills`, `test_tusi_self_funded_army_skips_pay_morale_channel`, `test_zero_due_province_army_morale_short_circuits`, `test_zhongyuan_jingshi_settle_province_tick_golden` |
| `tests/test_gazette_author_1862.py` | `test_author_archives_own_title_and_same_run_advances` |
| `tests/test_highlight_judge_544.py` | `test_chat_nonstream_folds_judge_within_timeout`, `test_chat_nonstream_timeout_returns_reply_without_highlights`, `test_chat_stream_done_before_highlights_and_degrade`, `test_chat_stream_slow_success_attaches_after_done` |
| `tests/test_llm_channel_config.py` | `test_scene_and_rescript_entries_pass_default_headers_at_transport` |
| `tests/test_material_directory_1830.py` | `_active_minister`, `_agent_with_materials`, `_ctx`, `test_character_materials_exclude_legacy_raw_turn_report_and_keep_public_gazettes`, `test_material_tree_contains_only_structurally_related_world_details`, `test_opening_handled_matters_are_filtered_within_authorized_knowledge`, `test_prepare_fails_loud_when_dossier_read_breaks`, `test_prepare_writes_typed_tree_and_index`, `test_read_material_stays_inside_directory`, `test_same_requested_root_creates_independent_material_invocations`, `test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error` |
| `tests/test_menu_lifecycle_drain_396.py` | `test_drain_rejects_late_pending_write_before_gate_acquire` |
| `tests/test_month_loop_tracer_1468.py` | `_assert_court_break_closed` |
| `tests/test_month_translate_1840.py` | `test_pre_push_segment_translation_stages_declaration_without_world_writes`, `test_staged_month_declarations_settle_in_given_order_and_effects_are_idempotent`, `test_staged_month_effects_keep_input_reference_authority`, `test_unparseable_month_segment_does_not_stage_or_commit` |
| `tests/test_mutiny_actual_residence_659.py` | `test_redeploy_moves_fact_region_keeps_pay_source` |
| `tests/test_new_game_write_path_1749.py` | `test_load_save_close_fail_restores_writable_old_game` |
| `tests/test_on_scene_immediate_write_1839.py` | `test_undo_reverses_round_on_scene_writes` |
| `tests/test_pay_order_override_653.py` | `test_apply_score_extraction_accepts_llm_direction_with_fiscal_loss`, `test_bridge_applies_due_order_and_haircut_end_to_end`, `test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e`, `test_f23_region_logs_flow_sign_domain_repaid_negative`, `test_fact_brief_arrears_provenance_prefers_winning_scoped_over_nationwide`, `test_fact_brief_attributes_arrears_order_displacement_to_dossier`, `test_fact_brief_attributes_priority_displacement_to_dossier`, `test_fact_brief_central_haircut_floor_per_army_matches_real_accounting`, `test_fact_brief_levy_derives_regular_assessment_like_settle_tick`, `test_fact_brief_levy_uses_civil_arrears_breakdown_relation`, `test_fact_brief_long_term_stock_not_fed_as_turn_damage`, `test_fact_brief_per_source_windows_and_region_attribution`, `test_fact_brief_priority_provenance_falls_back_to_nationwide_scope`, `test_fact_brief_priority_provenance_ignores_later_noncausal_dossier`, `test_fact_brief_priority_provenance_prefers_winning_scoped_over_later_nationwide`, `test_fact_brief_province_auto_repaied_is_beneficiary_fact`, `test_fact_brief_unmet_relief_is_current_turn_damage`, `test_fact_brief_zero_need_army_region_attribution_not_gated`, `test_fiscal_fact_brief_bad_json_fails_loud`, `test_fiscal_fact_brief_haircut_and_relief_facts`, `test_fiscal_fact_brief_missing_settle_key_exits_dynamic_membership`, `test_fiscal_fact_brief_present_but_malformed_fails_loud`, `test_fiscal_fact_brief_pure_projection_deterministic_tsv`, `test_golden5_expiry_and_revoke_restore_byte_identical_default`, `test_lifecycle_promulgated_materializes_and_next_settlement_reads`, `test_turn_region_summary_claim_audit_rows_do_not_consume_limit` |
| `tests/test_person_delta_adapter.py` | `test_list_ministers_excludes_active_prince`, `test_registry_and_tools_court_roster_exclude_active_prince` |
| `tests/test_pihong_dossier_1490.py` | `_1778_generate`, `_1778_plant_and_follow`, `test_1621_http_follow_draft_uses_catalog_army_id`, `test_1682_late_grants_follow_policy_without_consuming_verdict_batch`, `test_1778_drafted_roster_rides_to_pihong_and_nails_the_dossier`, `test_1778_missing_roster_heals_then_error_pack_without_assigning_anyone`, `test_657_s10_http_five_actions_and_1490_no_regress`, `test_658_typed_target_and_backing_reject_bad_shapes`, `test_bind_preserves_dossier_event_id`, `test_bind_unbinds_dossier_prefix_without_capability_fields` |
| `tests/test_player_army_projection_321.py` | `test_four_chains_embed_situation_matrix` |
| `tests/test_power_section_rejections.py` | `test_power_change_formatter_skips_rejected_items` |
| `tests/test_pre_settle_transaction.py` | `test_write_decree_raises_at_awaiting_not_resolveresult` |
| `tests/test_promulgation_judge_561.py` | `test_run_resolve_arm_recovers_settled_verdicts_from_history` |
| `tests/test_promulgation_seam_560.py` | `test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row` |
| `tests/test_qa_1281_issue_audience_case_facts.py` | `_issue_paths`, `_issue_row`, `test_audience_supplement_grants_originating_issue_outside_knowledge`, `test_empty_audience_is_empty_supplement_not_knowledge_veto`, `test_event_audience_read_failure_escapes_material_preparation`, `test_issue_material_projection_does_not_pollute_durable_events_or_db`, `test_issue_materials_keep_knowledge_visibility_without_audience_veto`, `test_malformed_event_audience_fails_loud_from_material_entry`, `test_malformed_knowledge_issue_id_fails_loud_from_material_entry`, `test_tuple_audience_container_fails_loud_from_content_fallback` |
| `tests/test_qa_e1_numeric_presentation.py` | `test_army_pay_shortfall_reason_has_no_float_garbage`, `test_province_pay_split_reason_and_summary_have_no_float_garbage` |
| `tests/test_relation_brew_636.py` | `test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure`, `test_batch_of_five_relations_all_enter_call_seam_concurrently`, `test_brew_batch_runs_items_in_parallel_not_serialized`, `test_brew_fn_value_error_is_program_error_propagates_loudly`, `test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical`, `test_brew_program_error_propagates_loudly_not_degraded`, `test_duplicate_json_objects_rejected_not_first_object_picked`, `test_failed_month_degrades_to_pending_and_rebrews_next_month`, `test_flip_brew_input_must_contain_new_edge_events`, `test_founding_segment_survives_consecutive_brews_byte_identical`, `test_historical_events_alone_do_not_select_in_later_month`, `test_mark_failure_after_llm_failure_propagates_loudly`, `test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews`, `test_parse_seam_value_error_degrades_single_item`, `test_prepare_attaches_prior_events_only_via_history_seam`, `test_prepare_claim_db_error_propagates_loudly`, `test_unescaped_control_byte_rejected_not_stripped` |
| `tests/test_relation_store_632.py` | `test_credit_contract_fixture_reads_as_semantic_directed_edges` |
| `tests/test_rescript_draft_656.py` | `test_1620_validate_army_pay_grant_kind_maps_to_xiexang`, `test_657_validate_layer_a_roundtrip_capability`, `test_657_validate_rejects_label_hint_only_options`, `test_clear_pending_decisions_keeps_rescript_drafts`, `test_generate_combined_target_and_roster_failures_reported_together_then_land`, `test_generate_combined_target_roster_partial_heal_reports_remaining`, `test_generate_existing_offcourt_roster_character_lands`, `test_generate_military_order_region_target_heals_then_drops`, `test_generate_rejects_military_order_empty_assignee`, `test_generate_rescript_draft_degrades_loudly_without_raising`, `test_generate_rescript_draft_program_error_propagates`, `test_generate_ungrounded_army_heals_then_drops_sibling_kept`, `test_generate_ungrounded_region_heals_then_drops_sibling_kept`, `test_generate_unknown_delegator_heals_then_drops_sibling_kept`, `test_generate_unknown_roster_character_heals_with_legal_set_then_lands`, `test_r3_lone_surrogate_field_rejects_whole_batch`, `test_r3_strict_parse_degrades_via_generate`, `test_r3_top_level_unknown_field_rejects_whole_batch`, `test_save_rescript_drafts_overwrites_not_duplicates`, `test_triage_actor_absent_when_both_offices_vacant`, `test_triage_actor_duplicate_hits_deterministic_order`, `test_triage_actor_falls_back_to_eunuch_director`, `test_triage_actor_follows_reappointment`, `test_triage_actor_negative_yumajian_zhangyin_never_selected`, `test_triage_actor_prefers_first_assistant_over_eunuch_director`, `test_validate_and_persist_preserve_whitespace_verbatim`, `test_validate_items_accepts_optional_issue_id_binding_key`, `test_validate_items_binds_only_board_issue_ids`, `test_validate_items_empty_list_is_legal_headless_month`, `test_validate_items_empty_options_drops_item_keeps_siblings`, `test_validate_items_many_options_not_gated_or_truncated`, `test_validate_items_missing_required_field_fails_whole_batch`, `test_validate_items_no_count_cap_keeps_all_legal`, `test_validate_items_non_list_options_drops_item_keeps_siblings`, `test_validate_items_rejects_illegal_top_level`, `test_validate_items_rejects_unknown_item_field_whole_batch`, `test_validate_items_rejects_unknown_option_field_whole_batch`, `test_validate_items_single_option_is_legal` |
| `tests/test_rescript_heal_isolation_1801.py` | `_ctx`, `_field_map`, `_item`, `_items_json`, `_never_fix_llm`, `_opt`, `_parse_heal`, `test_1801_eight_items_all_pass_no_heal_no_trim`, `test_1801_item_utf8_heals_then_drops_only_bad_item`, `test_1801_top_unformed_heals_then_no_drafts`, `test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings`, `test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items`, `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` |
| `tests/test_rescript_option_field_heal_1746.py` | `test_amount_numeric_string_accepted_via_grant_shape`, `test_army_single_combo_heals_not_batch_redraw`, `test_contract_failure_heals_not_batch_reject`, `test_dual_missing_discriminator_heals_grant_action`, `test_first_draw_parse_failure_heals_then_degrades`, `test_heal_bad_identity_refuses_merge_then_drops`, `test_heal_response_contract_failure_consumes_attempt_keeps_siblings`, `test_missing_target_kind_only_heals_not_combo_batch`, `test_option_shape_failures_heal_not_batch`, `test_overflow_json_number_exhaust_drops_only_bad`, `test_overflow_json_number_heals_not_batch`, `test_provider_still_whole_batch_item_missing_heals_and_drops`, `test_typed_illegal_also_heals` |
| `tests/test_secret_dossier_participants_1252.py` | `test_s2_tracer_613_565_readers_see_appended_roster` |
| `tests/test_secret_order_isolation_883.py` | `test_976_pending_secret_pin_survives_partial_commit_same_minister`, `test_976_rt04_undo_chat_turn_secret_order_brief_consistent` |
| `tests/test_secret_order_monthly_progress_566.py` | `test_only_emperor_private_payload_shows_monthly_report` |
| `tests/test_secret_order_payoff_1504.py` | `test_4a_declaration_lands_actions_and_spoliation_through_month_chain`, `test_actual_progress_container_separate_from_reported_rail`, `test_invalid_declaration_stops_month_chain_and_marks_invalid`, `test_invalid_investigation_declaration_is_rejected_not_zero_effort`, `test_mid_month_restore_preserves_actual_progress`, `test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite`, `test_n_month_deadline_yields_exactly_n_ticks`, `test_offstage_minister_no_progress_no_world_effects` |
| `tests/test_secret_order_update.py` | `test_upsert_creates_then_updates`, `test_upsert_different_minister_creates_new` |
| `tests/test_section4_rejections.py` | `test_region_army_formatters_skip_rejected_items` |
| `tests/test_session_write_queue_1353.py` | `test_barrier_proceeds_after_worker_fail_vacate`, `test_fail_vacate_lets_barrier_through`, `test_run_exclusive_serializes_writes` |
| `tests/test_structured_decree_contract_1624.py` | `test_http_manual_directive_lands_beyond_fifteen_initiatives_1790`, `test_month_end_entry_owner_and_matrix_reject` |
| `tests/test_supervision_625.py` | `test_ac1_monthly_write_idempotent_readable_and_restore`, `test_ac2_paired_observation_slots_and_countermeasure_hard_gate`, `test_due_review_supervision_history_no_longer_hardcoded_empty` |
| `tests/test_value_matrix_691.py` | `test_target_aware_axis_collisions_route_only_the_target_faction_vitals`, `test_value_matrix_fails_closed_when_the_42_cell_closed_set_is_corrupt`, `test_value_matrix_matches_adr_0011_3` |
| `tests/test_web_audience_night_498.py` | `test_asgi_hanging_chat_issue_waits_for_worker_terminal`, `test_asgi_inflight_reply_lands_then_issue_closes_and_advances` |
| `tests/test_web_court_visibility.py` | `test_list_ministers_uses_db_power_id`, `test_real_court_ministers_not_collateral_damaged_by_1317`, `test_shi_kefa_not_in_summonable_court_roster` |

补充：删除 `fiscal_fact_brief.py`、`person_write_inventory.py` 无消费者的余壳；移除 family-tail 脚本已无真源的 `bind_agent_content` 调用。机标解析消费者直接 import `settlement_payload`，拨帑 locality 消费者直接 import `execution_pressure`，不恢复 re-export 兼容层。

旧写口只用于某些消费端测试的前置数据，不代表这些入口契约也退役。已恢复这些测试（含 #1625），改由现有 `tests/conftest.py` 的固定 SQL 输入构造提供合法已存奏疏，消费端仍走真实入口，不 mock 被测行为；密令前置数据用已有 `create_secret_order`。只删除退役生产 API 自身的测试与独占闭包。已存 rescript_draft 记录仍由现有读面消费，未删存量记录、未恢复票拟生成器或旧档转换。

夹具成本：固定 pending_decisions schema 的输入植入与两种明确的输入重置；不另造通用序列化/兼容层。仓内查了 conftest、dossier/directive_seed_helpers 和 pending row helpers，原共用写口已退役；语言用现有 sqlite3.execute 和 json.dumps，生态沿用 pytest fixtures，不引 ORM/工厂依赖。官方资料：`https://docs.python.org/3/library/sqlite3.html`（execute/placeholders）；仅保存临时资料，不为运行新增前提。

## 自验与诚实失败记录

全部游戏测试命令均先 export：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
```

- 原月链入口变异真跑：临时世界/旨意两案，旧逃生逻辑均在第二次耗尽 `escape_armed=False` 报红；恢复后两案绿（最终复验 2.59s）。第三次再调用原入口重新生成续推；原问题、decided 批语与已经提交的段仍保留。模型边界桩只证明结构化恢复行为，不冒充真模型。
- 最终核心聚焦 `test_month_call_recovery_1846.py test_month_chain_1847.py test_levy_petition_month_chain_1891.py test_cli_backend.py`：163 passed（35.51s）。
- 最终字段/消费端聚焦 `test_rescript_draft_656.py test_rescript_option_field_heal_1746.py test_structured_decree_contract_1624.py test_secret_order_update.py test_pihong_dossier_1490.py test_applier_contract.py test_rescript_choices_563.py -k 'not test_1625_inflight_phase2_does_not_advertise_resume'`：130 passed，1 deselected（17.34s）。
- 最后退役 credit-edge 旧读面后，聚焦 `test_recommendation_edges_635.py test_relation_read_640.py test_credit_events_628.py`：24 passed（1.32s）。一次聚焦命令误写了不存在的 `test_relations_speak.py`，0 案运行，不计通过；已纠正为上述真实文件。
- 首轮 #1625 单跑 1 failed（0.84s），终态 `resume_phase2=True`。将其当成组合之外基线项的归因错误，撤回：2f74dc641 将相位派生搬进 resolve_decisions_phase2，旧替身绕过新契约。复审已统一将成功替身移至下层月链，保留真实 phase2 相位派生及原断言；#1625 恢复绿，见复审回执的红绿变异记录。
- Web `tsc -p web/tsconfig.json --noEmit`：exit 0；Vitest `src/settleStream.test.ts src/components/modals.test.tsx --environment jsdom`：70 passed（875ms）。只在本树建临时 node_modules 链接指向既有依赖，结束已删。
- touched Python AST/syntax、Ruff `--target-version py313 --select F401,F821`、仓内 from-import 真源绑定复扫：通过。未配置 Python 静态类型工具，不把 lint 冒称 Python typecheck。
- touched 测试 collect-only：1390 tests collected（2.25s）；不是全量 suite。
- 中途同名 label 案仍锁旧空白归一，已改成真正同原串重复，保持拒绝前零写入；不锁异常措辞。中途 import 清理误删 re-export 导致 16 案红，错误包真因为 `_DECISION_RE` ImportError；共同消费者改接原权威模块后全部恢复为上述 98 绿，未删除失败案。

没有新增测试用例/重试机制/通用生产件。现有消费测试改用固定合法输入，必要成本见夹具条款；真实入口与结构化断言保留。新增生产行主要是原串与验空分离、已有逃生分支；大幅纯删除来自全类退役及专属测试，未拆成独立可留下旧闭包的半票。无 push、PR、stash、amend，无席位/宿主配置修改，无全量施工测试。
