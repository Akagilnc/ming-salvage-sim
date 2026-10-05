# J6 原故障保真 — 全仓枚举成员表

## 类定义（末份判词）
清理盯文、内部伪证及失效证明时，必要失败行为与原始故障保真被削弱或漏审。
按行为契约区分格式化措辞与原始异常／原始诊断的保真；不得仅凭类型、非空诊断或初始状态结清。

## 枚举命令
```
PYTHONDONTWRITEBYTECODE=1 python3 evidence/1900-j6-j19-fixer-c7d876145/j6_enum_fault_fidelity.py
```

- tracked test py files: 227
- pytest.raises sites: 538（其中 RAISES_NO_MATCH=538）
- secondary/async hint raises: 86
- function-level fidelity hits: 769
- weak candidates for semantic review: 125

## 弱候选（须语义逐项；非机械全加身份断言）

| file | line | test | tags |
|---|---|---|---|
| `tests/test_advance_paths_atomic.py` | 183 | `test_submit_decisions_does_not_overwrite_already_decided_rows` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_advances_section_rejections.py` | 101 | `test_advance_code_exception_propagates` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_affairs_1831.py` | 244 | `test_new_issue_affair_attach_failure_leaves_no_partial_product` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_night_498.py` | 223 | `test_dead_person_enter_rejected_with_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_night_498.py` | 267 | `test_write_decree_leaves_unacted_pending_unchanged` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_night_498.py` | 322 | `test_close_night_crash_then_reopen_db_resumes_idempotent` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_night_498.py` | 439 | `test_closing_cursor0_reopen_refuses_new_and_explicit_resume_commits` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_night_498.py` | 495 | `test_open_night_atomic_on_dead_roster_injection` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_restore_505.py` | 314 | `test_post_reply_failure_resumes_close_without_regenerating_reply` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_restore_505.py` | 407 | `test_failed_retry_rolls_back_side_effects_and_keeps_question` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_audience_travel_gating_670.py` | 445 | `test_arrived_summon_continuation_survives_failed_apply_across_months` | CAUSE_CONTEXT, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_audience_undo_506.py` | 295 | `test_undo_reversal_is_atomic_on_midway_crash` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 333 | `test_t6_bad_target_aborts_with_zero_write` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 358 | `test_t6b_non_int_identity_aborts_with_zero_write` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 485 | `test_t9_idempotency_namespace_and_empty_planned` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 606 | `test_t10_partial_preinserted_key_aborts` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 651 | `test_t11_rebuild_clears_dirty_and_write_path_rolls_back` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_centrifuge_ledger_690.py` | 828 | `test_t14_reason_code_sets_and_reject_unrecognized` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_chat_stream_failpaths_393.py` | 167 | `test_prologue_finally_does_not_release_foreign_gate_holder` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_chat_stream_failpaths_393.py` | 252 | `test_prologue_cleanup_failure_still_releases_gate_and_counter` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_cli_backend.py` | 774 | `test_clichat_invoke_error_traced_and_reraised` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_cli_play_turn.py` | 201 | `test_terminal_minister_chat_removes_user_message_when_session_chat_fails` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_cli_play_turn.py` | 250 | `test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_cli_play_turn.py` | 299 | `test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_cli_play_turn.py` | 329 | `test_terminal_minister_chat_reply_persist_failure_keeps_user_message` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_close_issues_section_rejections.py` | 159 | `test_close_issue_code_exception_propagates` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_declaration_dispatch_1835.py` | 173 | `test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_decree_dossiers_571.py` | 1343 | `test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_error_pack.py` | 36 | `test_write_error_pack_inside_atomic_is_rejected` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_error_pack.py` | 108 | `test_web_issue_endpoint_returns_structured_abort` | PERSIST_DIAG, SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_event_chain_cascade.py` | 207 | `test_contradictory_positive_terminal_state_gate_fails_loud` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_event_chain_cascade.py` | 222 | `test_cascade_rolls_back_owned_transaction_on_later_write_failure` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_event_chain_cascade.py` | 353 | `test_event_dependency_cycle_fails_loud` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_event_trigger_gate.py` | 3641 | `test_apply_score_extraction_appointment_rolls_back_with_outer_transaction` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_execution_pressure_654.py` | 43 | `test_mapper_rejects_contradictory_locality_scope_without_overwrite` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_executor_routing_721.py` | 83 | `test_existing_delegated_lead_is_preserved_not_demoted` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_executor_routing_721.py` | 350 | `test_rolled_back_collector_reuse_does_not_mirror_orphan` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_executor_routing_721.py` | 378 | `test_directive_routing_rejection_rolls_back_with_outer_owner` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_levy_effect.py` | 669 | `test_fiscal_levy_existing_terminal_reason_is_whitelist_validated` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_levy_effect.py` | 736 | `test_fiscal_levy_outcome_label_outside_closed_set_aborts` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_levy_effect.py` | 787 | `test_fiscal_levy_pending_choice_waits_for_event_window` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_levy_effect.py` | 1038 | `test_jiao_stop_definition_missing_fails_loud` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4400 | `test_cutover_pay_source_errors_abort_fixed_flows` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_fiscal_substrate_bridge.py` | 4432 | `test_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4459 | `test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4486 | `test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_fiscal_substrate_bridge.py` | 4537 | `test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4559 | `test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_fiscal_substrate_bridge.py` | 4585 | `test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4609 | `test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4638 | `test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4685 | `test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_fiscal_substrate_bridge.py` | 4858 | `test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_gazette_author_1862.py` | 463 | `test_gazette_failure_retries_report_only` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_llm_channel_config.py` | 638 | `test_verify_llm_available_api_empty_content_error_status_raises` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_material_directory_1830.py` | 258 | `test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_mechanical_tail_1845.py` | 150 | `test_exhausted_mechanical_tail_fails_and_blocks_next_month` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_mechanical_tail_1845.py` | 186 | `test_real_brew_failure_reaches_tail_failure_and_retry` | PERSIST_DIAG, SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_mechanical_tail_1845.py` | 283 | `test_non_exhausted_tail_failure_stays_pending_and_retries` | PERSIST_DIAG, SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 81 | `test_month_entry_world_push_follows_audience_transport_policy` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 144 | `test_forecast_exhaustion_does_not_overwrite_prior_ending` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 210 | `test_world_text_exhaustion_stops_month_keeps_settled_edicts` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 255 | `test_world_translate_exhaustion_keeps_text_resume_retries_translate_only` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 323 | `test_escape_hatch_discards_world_segment_only_on_second_player_retry` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 397 | `test_settlement_recovery_projects_month_call_failure` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, NONEMPTY_DIAG, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 463 | `test_code_exception_during_world_commit_keeps_phase_and_settled_edicts` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 508 | `test_world_commit_failure_after_alongside_retries_uncommitted_segment` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_call_recovery_1846.py` | 602 | `test_edict_settle_code_exception_stops_at_month_entry_and_retries_once` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_month_call_recovery_1846.py` | 657 | `test_error_pack_failure_keeps_original_fault_and_retry_phase` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, NONEMPTY_DIAG |
| `tests/test_month_chain_1843.py` | 70 | `test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge` | CAUSE_CONTEXT, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_month_chain_1843.py` | 287 | `test_player_entry_recovers_ending_after_interrupted_segment` | CAUSE_CONTEXT, PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_month_chain_1843.py` | 367 | `test_failed_declaration_commit_reloads_memory_from_db` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1843.py` | 497 | `test_missing_world_model_stops_before_world_commit` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 1010 | `test_midzhi_verdict_and_metadata_roll_back_together` | CAUSE_CONTEXT, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_month_chain_1847.py` | 1384 | `test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 1455 | `test_step_4a_crash_recovery_resumes_without_re_running_supply` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 1563 | `test_step_4a_missing_covert_fidelity_records_inline_rejection` | PERSIST_DIAG, SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 1692 | `test_settle_edicts_persists_pending_disclosures_in_same_transaction` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 1806 | `test_step_4a_non_validation_failure_keeps_product_on_retry` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_month_chain_1847.py` | 2199 | `test_pending_disclosures_share_commit_boundary_with_effects` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_new_game_write_path_1749.py` | 439 | `test_new_game_construct_failure_keeps_old_writable` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_new_issues_section_rejections.py` | 305 | `test_new_issue_insert_code_exception_propagates` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_new_issues_section_rejections.py` | 358 | `test_new_issue_event_pool_insert_exception_propagates` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_override_breach_costs_564.py` | 372 | `test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_override_breach_costs_564.py` | 445 | `test_commit_false_breach_rolls_back_with_later_cancellation_failure` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_person_delta_adapter.py` | 1962 | `test_create_secret_order_rejects_vassal_prince_by_alias` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_person_delta_adapter.py` | 2000 | `test_create_secret_order_rejects_foreign_power` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_person_delta_adapter.py` | 2015 | `test_create_secret_order_rejects_foreign_power_by_alias` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_pihong_dossier_1490.py` | 563 | `test_657_p6_mapper_deliberate_preserve_free_text` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_pihong_dossier_1490.py` | 923 | `test_657_abi_mapper_matrix_a1_a12` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_power_section_rejections.py` | 78 | `test_power_deltas_code_exception_aborts_settlement` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_pre_settle_transaction.py` | 416 | `test_placeholder_save_crash_rolls_back_settling` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_recommendation_batch_snapshot_1583.py` | 120 | `test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_refugee_loop_652.py` | 122 | `test_outer_atomic_rolls_back_surcharge_and_absorption` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_refugee_loop_652.py` | 422 | `test_recovery_shared_pool_advances_once_after_empty_effect_month` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_rejection_wiring.py` | 57 | `test_rollback_leaves_no_rows_and_no_jsonl` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_rejection_wiring.py` | 108 | `test_nested_atomic_success_path_does_not_orphan_jsonl` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_relation_capture_633.py` | 281 | `test_settlement_edge_origin_rejects_missing_and_non_string` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_relation_capture_633.py` | 475 | `test_writer_stores_whitespace_context_byte_identical` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_relation_seed_638.py` | 260 | `test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_secret_order_monthly_progress_566.py` | 293 | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | SECONDARY_HINT, ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_section4_rejections.py` | 373 | `test_region_deltas_code_exception_aborts_settlement` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_section4_rejections.py` | 388 | `test_army_deltas_code_exception_aborts_settlement` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_section4_rejections.py` | 403 | `test_create_armies_code_exception_aborts_settlement` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_section4_rejections.py` | 731 | `test_required_field_historical_strictness_on_issue_path` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_settlement_write_guard_393.py` | 229 | `test_direct_db_write_refused_when_gate_held` | ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 110 | `test_pre_settle_self_reloads_memory_on_rollback` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 148 | `test_rollback_purges_content_character_ghost` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 191 | `test_reload_skipped_inside_nested_atomic` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 235 | `test_rollback_restores_existing_character_attributes` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 296 | `test_atomic_and_reload_reloads_and_reraises_at_depth0` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 311 | `test_atomic_and_reload_skips_reload_when_nested` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_state_reload.py` | 335 | `test_atomic_and_reload_chains_reload_failure` | CAUSE_CONTEXT, SECONDARY_HINT, TYPE_ONLY_RAISES |
| `tests/test_state_reload.py` | 351 | `test_atomic_and_reload_runs_on_error_before_reload` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_structured_decree_contract_1624.py` | 130 | `test_shared_validate_rejects_region_id_and_category_holes` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_surcharge_causal_chain_650.py` | 335 | `test_levy_ledger_corruption_fails_loud` | SECONDARY_HINT, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 214 | `test_atomic_reraises_original_exception` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 262 | `test_connection_context_inside_atomic_rolls_back` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 292 | `test_swallowed_inner_exception_forces_outer_rollback` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 327 | `test_connection_rollback_attempts_all_runtime_callbacks` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 387 | `test_swallowed_conn_context_exception_forces_outer_rollback` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 440 | `test_commit_failure_in_conn_context_rolls_back` | TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 509 | `test_ddl_after_swallowed_conn_context_does_not_escape` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_transaction_boundary.py` | 536 | `test_ddl_after_explicit_midatomic_rollback_does_not_escape` | SECONDARY_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |
| `tests/test_web_llm_runtime_config.py` | 249 | `test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception` | ASYNC_HINT, TYPE_ONLY_RAISES, FIDELITY_CONTRACT_CANDIDATE |

## 次生失败 / 持久诊断 / cause 契约抽样源

完整 raises 清单见 `j6-raises-raw.jsonl`；函数级见 `j6-fidelity-candidates.jsonl`。

## 语义处置（同类契约逐项；非机械全加身份断言）

官方能力依据：
- [pytest assertions about expected exceptions](https://docs.pytest.org/en/stable/how-to/assert.html#assertions-about-expected-exceptions)（`raises` + `ExceptionInfo.value`）
- [Python exception chaining](https://docs.python.org/3/tutorial/errors.html#exception-chaining)（`__cause__`）

| 成员 | 契约 | 处置 |
|---|---|---|
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | 双故障：chat 主故障 vs 回滚次生；类型同为 RuntimeError | **FIX**：`args` + `__cause__.args` 保真 |
| `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase` | 写包次生不得顶替结算诊断；非空诊断不足以辨别 | **FIX**：`SettlementAbort.args` + `call_failure.message` + cause.args |
| `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` | reload 次生挂链，主诊断仍为 body | **FIX**：主/`cause` `.args` |
| `tests/test_transaction_boundary.py::test_atomic_reraises_original_exception` | 原异常对象 `is sentinel` | **KEEP**（已有对象身份） |
| `tests/test_relation_seed_638.py::test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | 写口不调 rollback；次生为 AssertionError 不同类型 | **KEEP**（类型已可辨别；契约是「不调用 rollback」） |
| `tests/test_chat_stream_failpaths_393.py::test_prologue_cleanup_failure_still_releases_gate_and_counter` | 闸释放，非原故障保真 | **KEEP**（不同契约） |
| `tests/test_month_call_recovery_1846.py::test_settlement_recovery_projects_month_call_failure` | 已断言可见原文诊断进 recovery | **KEEP** |
| `tests/test_month_call_recovery_1846.py::test_edict_settle_code_exception_stops_at_month_entry_and_retries_once` | 单故障停住重试；cause 类型 | **KEEP**（非双故障顶替契约） |
| `tests/test_cli_play_turn.py` 其它 chat 失败案 | 外部结果（删消息等），非原故障保真 | **KEEP** |
| `tests/test_state_reload.py` 其它 reload 案 | 是否 reload / 顺序 | **KEEP** |
| 已结归档 worker / 持闸 / J17 来源闸案 | 前判已结 | **不重开** |
| AST 弱候选中其余 TYPE_ONLY_RAISES | 无「主故障被次生替换仍绿」的双故障保真契约 | **不机械加身份断言** |

## 上轮枚举纠正
旧冻结 `evidence/1900-j20-j19-j6-fixer-bbd34c025-rescan/j6_full_enum.py` 仅收集带 `match` 的 raises，漏 raises-only；本轮谓词显式覆盖 RAISES_NO_MATCH / cause / 持久诊断 / 次生失败 / 异步 hint。旧卷不改写。
