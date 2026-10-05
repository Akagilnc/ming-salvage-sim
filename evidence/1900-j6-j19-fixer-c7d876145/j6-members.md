# J6 原故障保真 — 成员处置（全类边界）

## 类定义（末份判词）
清理盯文、内部伪证及失效证明时，**必要失败行为被吞**与**原始故障／原诊断保真被削弱或漏审**同属本类。
按行为契约区分格式化措辞与原异常／原诊断保真；不得仅凭类型、非空诊断、初始状态或「无双故障」默认结清。

## 枚举（库存，非结清证明）
弱候选库存来自既有 `j6-fidelity-candidates.jsonl`（raises／次生／异步词面仅作召回）。
本表为**逐函数对照生产失败契约**的语义处置；不新增枚举框架，不以 TYPE_ONLY 自动保留。

- weak candidates reviewed: 125
- disposition counts: FIX_DONE=3, KEEP_ABORT_PACK_STRUCTURE=11, KEEP_AUDIENCE_CONTROL=8, KEEP_EXTERNAL_CHAT_RESULT=3, KEEP_EXTERNAL_OR_CONTROL=71, KEEP_MONTH_PHASE=6, KEEP_NO_SWALLOW_SEAM=1, KEEP_OBJECT_IDENTITY=1, KEEP_OTHER_CONTRACT=1, KEEP_PERSIST_MSG=1, KEEP_RELOAD_CONTROL=7, KEEP_ROLLBACK_EFFECT=3, KEEP_SINGLE_FAULT_RETRY=1, KEEP_SINGLE_FAULT_TYPE=8

## 本轮 FIX

| 成员 | 生产契约 | 处置 |
|---|---|---|
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | 双故障原诊断保真 | **FIX_DONE**：生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |
| `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase` | 双故障原诊断保真 | **FIX_DONE**：生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |
| `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` | 双故障原诊断保真 | **FIX_DONE**：生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |

## 语义处置（125 项；按契约族汇总，细目见 j6-disposition.jsonl）

官方能力：
- [pytest ExceptionInfo](https://docs.pytest.org/en/stable/how-to/assert.html#assertions-about-expected-exceptions)
- [exception chaining](https://docs.python.org/3/tutorial/errors.html#exception-chaining)

| disposition | n | 语义含义 |
|---|---|---|
| `KEEP_EXTERNAL_OR_CONTROL` | 71 | 外部零写／拒收／控制流（已读函数确认无吞失败／无诊断顶替假绿） |
| `KEEP_ABORT_PACK_STRUCTURE` | 11 | 错误包／code 结构 |
| `KEEP_AUDIENCE_CONTROL` | 8 | 召对控制流落账 |
| `KEEP_SINGLE_FAULT_TYPE` | 8 | 单故障类型冒出 |
| `KEEP_RELOAD_CONTROL` | 7 | reload 控制流 |
| `KEEP_MONTH_PHASE` | 6 | 月链相位落账 |
| `FIX_DONE` | 3 | 本轮已修原诊断保真 |
| `KEEP_EXTERNAL_CHAT_RESULT` | 3 | 聊天落库外部结果 |
| `KEEP_ROLLBACK_EFFECT` | 3 | 外层回滚效果可核 |
| `KEEP_NO_SWALLOW_SEAM` | 1 | 不吞写错／不擅自 rollback |
| `KEEP_OBJECT_IDENTITY` | 1 | 已有对象身份 |
| `KEEP_OTHER_CONTRACT` | 1 | 闸释放等其它必要失败行为（已结实例不重开） |
| `KEEP_PERSIST_MSG` | 1 | 持久诊断已对注入原文 |
| `KEEP_SINGLE_FAULT_RETRY` | 1 | 单故障重试相位 |

## 抽样细目（吞失败／异步／双故障相邻；其余见 jsonl）

| 成员 | disposition | 可核理由 |
|---|---|---|
| `tests/test_chat_stream_failpaths_393.py::test_prologue_finally_does_not_release_foreign_gate_holder` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写、快照不变、拒收结构或控制流结果为契约；已逐函数对照生产失败分支，未见必要失败被吞或原诊断被替换仍绿 |
| `tests/test_chat_stream_failpaths_393.py::test_prologue_cleanup_failure_still_releases_gate_and_counter` | `KEEP_OTHER_CONTRACT` | 契约为写闸／计数释放（drain 不永久挂起），断言落在 _assert_write_path_free；非原诊断身份案，不重开已结 failpath 实例 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | `FIX_DONE` | 生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |
| `tests/test_month_call_recovery_1846.py::test_settlement_recovery_projects_month_call_failure` | `KEEP_PERSIST_MSG` | 持久 call_failure／recovery 诊断已对注入原文或结构化字段 |
| `tests/test_month_call_recovery_1846.py::test_edict_settle_code_exception_stops_at_month_entry_and_retries_once` | `KEEP_SINGLE_FAULT_RETRY` | 单故障停住与重试相位；cause 类型辅助，主契约是相位与 settled 状态 |
| `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase` | `FIX_DONE` | 生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |
| `tests/test_relation_seed_638.py::test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | `KEEP_NO_SWALLOW_SEAM` | 契约为写口不得自行 rollback；execute 故障须以 RuntimeError 冒出——若被吞或改走 rollback，断言／期望类型即破 |
| `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` | `FIX_DONE` | 生产双故障路径上的原异常／原诊断保真；本轮以注入异常对象／str 为期望，并用真实分支变异证明强断言红、弱断言假绿 |
| `tests/test_transaction_boundary.py::test_atomic_reraises_original_exception` | `KEEP_OBJECT_IDENTITY` | 已断言原异常对象身份（is sentinel／注入对象），失败行为经真实入口冒出 |
| `tests/test_transaction_boundary.py::test_swallowed_inner_exception_forces_outer_rollback` | `KEEP_ROLLBACK_EFFECT` | 契约为外层事务回滚或 DDL 不逃逸；夹具内故意吞异常是为验证外层仍回滚，外部 kv／表结果可核 |
| `tests/test_transaction_boundary.py::test_swallowed_conn_context_exception_forces_outer_rollback` | `KEEP_ROLLBACK_EFFECT` | 契约为外层事务回滚或 DDL 不逃逸；夹具内故意吞异常是为验证外层仍回滚，外部 kv／表结果可核 |
| `tests/test_transaction_boundary.py::test_ddl_after_swallowed_conn_context_does_not_escape` | `KEEP_ROLLBACK_EFFECT` | 契约为外层事务回滚或 DDL 不逃逸；夹具内故意吞异常是为验证外层仍回滚，外部 kv／表结果可核 |

## 全量 125 项处置索引

| file | test | disposition |
|---|---|---|
| `tests/test_advance_paths_atomic.py` | `test_submit_decisions_does_not_overwrite_already_decided_rows` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_advances_section_rejections.py` | `test_advance_code_exception_propagates` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_affairs_1831.py` | `test_new_issue_affair_attach_failure_leaves_no_partial_product` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_audience_night_498.py` | `test_dead_person_enter_rejected_with_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_audience_night_498.py` | `test_write_decree_leaves_unacted_pending_unchanged` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_night_498.py` | `test_close_night_crash_then_reopen_db_resumes_idempotent` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_night_498.py` | `test_closing_cursor0_reopen_refuses_new_and_explicit_resume_commits` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_night_498.py` | `test_open_night_atomic_on_dead_roster_injection` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_restore_505.py` | `test_post_reply_failure_resumes_close_without_regenerating_reply` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_restore_505.py` | `test_failed_retry_rolls_back_side_effects_and_keeps_question` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_travel_gating_670.py` | `test_arrived_summon_continuation_survives_failed_apply_across_months` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_audience_undo_506.py` | `test_undo_reversal_is_atomic_on_midway_crash` | `KEEP_AUDIENCE_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t6_bad_target_aborts_with_zero_write` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t6b_non_int_identity_aborts_with_zero_write` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t9_idempotency_namespace_and_empty_planned` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t10_partial_preinserted_key_aborts` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t11_rebuild_clears_dirty_and_write_path_rolls_back` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_centrifuge_ledger_690.py` | `test_t14_reason_code_sets_and_reject_unrecognized` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_chat_stream_failpaths_393.py` | `test_prologue_finally_does_not_release_foreign_gate_holder` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_chat_stream_failpaths_393.py` | `test_prologue_cleanup_failure_still_releases_gate_and_counter` | `KEEP_OTHER_CONTRACT` |
| `tests/test_cli_backend.py` | `test_clichat_invoke_error_traced_and_reraised` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_removes_user_message_when_session_chat_fails` | `KEEP_EXTERNAL_CHAT_RESULT` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted` | `KEEP_EXTERNAL_CHAT_RESULT` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | `FIX_DONE` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_reply_persist_failure_keeps_user_message` | `KEEP_EXTERNAL_CHAT_RESULT` |
| `tests/test_close_issues_section_rejections.py` | `test_close_issue_code_exception_propagates` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_declaration_dispatch_1835.py` | `test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_decree_dossiers_571.py` | `test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_error_pack.py` | `test_write_error_pack_inside_atomic_is_rejected` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_error_pack.py` | `test_web_issue_endpoint_returns_structured_abort` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_event_chain_cascade.py` | `test_contradictory_positive_terminal_state_gate_fails_loud` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_event_chain_cascade.py` | `test_cascade_rolls_back_owned_transaction_on_later_write_failure` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_event_chain_cascade.py` | `test_event_dependency_cycle_fails_loud` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_event_trigger_gate.py` | `test_apply_score_extraction_appointment_rolls_back_with_outer_transaction` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_execution_pressure_654.py` | `test_mapper_rejects_contradictory_locality_scope_without_overwrite` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_executor_routing_721.py` | `test_existing_delegated_lead_is_preserved_not_demoted` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_executor_routing_721.py` | `test_rolled_back_collector_reuse_does_not_mirror_orphan` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_executor_routing_721.py` | `test_directive_routing_rejection_rolls_back_with_outer_owner` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_existing_terminal_reason_is_whitelist_validated` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_outcome_label_outside_closed_set_aborts` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_pending_choice_waits_for_event_window` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_levy_effect.py` | `test_jiao_stop_definition_missing_fails_loud` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_pay_source_errors_abort_fixed_flows` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack` | `KEEP_ABORT_PACK_STRUCTURE` |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_gazette_author_1862.py` | `test_gazette_failure_retries_report_only` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_llm_channel_config.py` | `test_verify_llm_available_api_empty_content_error_status_raises` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_material_directory_1830.py` | `test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_mechanical_tail_1845.py` | `test_exhausted_mechanical_tail_fails_and_blocks_next_month` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_mechanical_tail_1845.py` | `test_real_brew_failure_reaches_tail_failure_and_retry` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_mechanical_tail_1845.py` | `test_non_exhausted_tail_failure_stays_pending_and_retries` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_call_recovery_1846.py` | `test_month_entry_world_push_follows_audience_transport_policy` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_forecast_exhaustion_does_not_overwrite_prior_ending` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_world_text_exhaustion_stops_month_keeps_settled_edicts` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_world_translate_exhaustion_keeps_text_resume_retries_translate_only` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_escape_hatch_discards_world_segment_only_on_second_player_retry` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_settlement_recovery_projects_month_call_failure` | `KEEP_PERSIST_MSG` |
| `tests/test_month_call_recovery_1846.py` | `test_code_exception_during_world_commit_keeps_phase_and_settled_edicts` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_month_call_recovery_1846.py` | `test_world_commit_failure_after_alongside_retries_uncommitted_segment` | `KEEP_MONTH_PHASE` |
| `tests/test_month_call_recovery_1846.py` | `test_edict_settle_code_exception_stops_at_month_entry_and_retries_once` | `KEEP_SINGLE_FAULT_RETRY` |
| `tests/test_month_call_recovery_1846.py` | `test_error_pack_failure_keeps_original_fault_and_retry_phase` | `FIX_DONE` |
| `tests/test_month_chain_1843.py` | `test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1843.py` | `test_player_entry_recovers_ending_after_interrupted_segment` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1843.py` | `test_failed_declaration_commit_reloads_memory_from_db` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1843.py` | `test_missing_world_model_stops_before_world_commit` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_midzhi_verdict_and_metadata_roll_back_together` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_step_4a_crash_recovery_resumes_without_re_running_supply` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_step_4a_missing_covert_fidelity_records_inline_rejection` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_settle_edicts_persists_pending_disclosures_in_same_transaction` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_step_4a_non_validation_failure_keeps_product_on_retry` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_month_chain_1847.py` | `test_pending_disclosures_share_commit_boundary_with_effects` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_new_game_write_path_1749.py` | `test_new_game_construct_failure_keeps_old_writable` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_new_issues_section_rejections.py` | `test_new_issue_insert_code_exception_propagates` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_new_issues_section_rejections.py` | `test_new_issue_event_pool_insert_exception_propagates` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_override_breach_costs_564.py` | `test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_override_breach_costs_564.py` | `test_commit_false_breach_rolls_back_with_later_cancellation_failure` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_person_delta_adapter.py` | `test_create_secret_order_rejects_vassal_prince_by_alias` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_person_delta_adapter.py` | `test_create_secret_order_rejects_foreign_power` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_person_delta_adapter.py` | `test_create_secret_order_rejects_foreign_power_by_alias` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_pihong_dossier_1490.py` | `test_657_p6_mapper_deliberate_preserve_free_text` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_pihong_dossier_1490.py` | `test_657_abi_mapper_matrix_a1_a12` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_power_section_rejections.py` | `test_power_deltas_code_exception_aborts_settlement` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_pre_settle_transaction.py` | `test_placeholder_save_crash_rolls_back_settling` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_recommendation_batch_snapshot_1583.py` | `test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_refugee_loop_652.py` | `test_outer_atomic_rolls_back_surcharge_and_absorption` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_refugee_loop_652.py` | `test_recovery_shared_pool_advances_once_after_empty_effect_month` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_rejection_wiring.py` | `test_rollback_leaves_no_rows_and_no_jsonl` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_rejection_wiring.py` | `test_nested_atomic_success_path_does_not_orphan_jsonl` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_relation_capture_633.py` | `test_settlement_edge_origin_rejects_missing_and_non_string` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_relation_capture_633.py` | `test_writer_stores_whitespace_context_byte_identical` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_relation_seed_638.py` | `test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | `KEEP_NO_SWALLOW_SEAM` |
| `tests/test_secret_order_monthly_progress_566.py` | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_section4_rejections.py` | `test_region_deltas_code_exception_aborts_settlement` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_section4_rejections.py` | `test_army_deltas_code_exception_aborts_settlement` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_section4_rejections.py` | `test_create_armies_code_exception_aborts_settlement` | `KEEP_SINGLE_FAULT_TYPE` |
| `tests/test_section4_rejections.py` | `test_required_field_historical_strictness_on_issue_path` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_settlement_write_guard_393.py` | `test_direct_db_write_refused_when_gate_held` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_state_reload.py` | `test_pre_settle_self_reloads_memory_on_rollback` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_rollback_purges_content_character_ghost` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_reload_skipped_inside_nested_atomic` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_rollback_restores_existing_character_attributes` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_atomic_and_reload_reloads_and_reraises_at_depth0` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_atomic_and_reload_skips_reload_when_nested` | `KEEP_RELOAD_CONTROL` |
| `tests/test_state_reload.py` | `test_atomic_and_reload_chains_reload_failure` | `FIX_DONE` |
| `tests/test_state_reload.py` | `test_atomic_and_reload_runs_on_error_before_reload` | `KEEP_RELOAD_CONTROL` |
| `tests/test_structured_decree_contract_1624.py` | `test_shared_validate_rejects_region_id_and_category_holes` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_surcharge_causal_chain_650.py` | `test_levy_ledger_corruption_fails_loud` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_transaction_boundary.py` | `test_atomic_reraises_original_exception` | `KEEP_OBJECT_IDENTITY` |
| `tests/test_transaction_boundary.py` | `test_connection_context_inside_atomic_rolls_back` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_transaction_boundary.py` | `test_swallowed_inner_exception_forces_outer_rollback` | `KEEP_ROLLBACK_EFFECT` |
| `tests/test_transaction_boundary.py` | `test_connection_rollback_attempts_all_runtime_callbacks` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_transaction_boundary.py` | `test_swallowed_conn_context_exception_forces_outer_rollback` | `KEEP_ROLLBACK_EFFECT` |
| `tests/test_transaction_boundary.py` | `test_commit_failure_in_conn_context_rolls_back` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_transaction_boundary.py` | `test_ddl_after_swallowed_conn_context_does_not_escape` | `KEEP_ROLLBACK_EFFECT` |
| `tests/test_transaction_boundary.py` | `test_ddl_after_explicit_midatomic_rollback_does_not_escape` | `KEEP_EXTERNAL_OR_CONTROL` |
| `tests/test_web_llm_runtime_config.py` | `test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception` | `KEEP_EXTERNAL_OR_CONTROL` |

## 已结实例（不重开）与同契约覆盖
- 持闸真实月链分支、归档 worker 等待、J17 来源闸：前判已结实例不重开。
- 同契约其它遗漏：本表对弱候选逐项覆盖；闸释放案保留为 `KEEP_OTHER_CONTRACT`（必要失败行为=释放，不是诊断身份）。

## 上轮纠正
- 旧冻结 enum 仅收集带 match 的 raises：已弃用该漏召回路径。
- **禁止**「无双故障默认 KEEP」收窄全类；吞失败与原诊断保真同属范围。
- 旧 `mutations.log` 整入口替换证明：**弃用**；有效证明见 `mutations-valid.log`。
