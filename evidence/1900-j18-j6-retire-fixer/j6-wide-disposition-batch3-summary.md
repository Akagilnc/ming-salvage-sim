# J6 wide disposition batch3

Slice: `kind=py` files in last third alphabetically (70 files, from `tests/test_pre_settle_transaction.py` onward) + all `kind=web`.
Skipped **25** rows already in `j6-wide-disposition-prio.jsonl`.
**Total disposed:** 867 (reused named prior from private-helper / web / class-members: 89)

## Counts by action

- **delete**: 1
- **migrate**: 141
- **retain**: 725

## delete

- `tests/test_release_bundle_assets.py::test_spec_datas_puts_requirements_at_bundle_root` — AST 执行 Ming_LLM.spec 装配证明；发行打包内部非玩家/引擎契约

## migrate

- `tests/test_promulgation_judge_561.py::test_promulgation_context_routes_faction_leverage_through_power_band` — 去掉 power_band(42) 内部公式 oracle
- `tests/test_promulgation_judge_561.py::test_promulgation_verdict_rejects_unknown_fields` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_promulgated_verdict_strips_rejection_only_noise` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_promulgated_midzhi_strips_affected_parties_with_rejection_noise` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_promulgated_true_path_clean_verdict_passes` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_rejected_verdict_still_requires_full_rejection_contract` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_promulgation_verdict_accepts_exact_keys_for_each_mode` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_rejected_exact_keys_accept_only_empty_legal_reason_slot` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_default_promulgation_judge_uses_one_batch_and_existing_validator` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_rejected_snapshot_must_equal_the_prepared_judge_input` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_judge_561.py::test_ordinary_rejection_cannot_claim_midzhi_unpromulgatable` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_promulgation_seam_560.py::test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_public_sayings_1829.py::test_public_saying_survives_same_turn_archive_projection` — 拼装材料/提示词字面锁；非原文无损契约
- `tests/test_qa_1281_issue_audience_case_facts.py::test_issue_materials_keep_knowledge_visibility_without_audience_veto` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_b3_409_ux.py::test_directive_payload_authority_not_notes_alias` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_b3_409_ux.py::test_resolve_decisions_stream_phase_precheck_before_lock` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_b3_409_ux.py::test_resolve_decisions_stream_awaiting_still_submits_under_lock` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_c2_phase_settlement_mask_1374.py::test_resolve_stream_entry_failure_exits_display_when_not_front_half` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_c2_phase_settlement_mask_1374.py::test_resolve_stream_clear_throw_emits_error_not_done` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_success_clear_holds_write_gate_not_peer_txn` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_success_clear_throw_via_orphan_exits_display` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_refresh_turn_no_longer_clears_orphan` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_h1_seed_data.py::test_guanning_commander_not_bajiu_offstage_yuan` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_h1_seed_data.py::test_dongjiang_commander_is_active_mao_wenlong` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_h1_seed_data.py::test_seed_army_firearms_differentiated_within_p2_caps` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_t1_extraction_dual_source_1353.py::test_drain_fail_concurrent_heal_asks_retry_no_dual_source` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_t1_extraction_dual_source_1353.py::test_debt_exhausted_single_source_no_player_cta` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_u3_map_nodes_1401.py::test_map_nodes_no_double_army_hang` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_qa_u3_map_nodes_1401.py::test_map_nodes_no_nameless_nodes` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_recommendation_edges_635.py::test_real_entry_persists_raw_reason_verbatim` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_recommendation_edges_635.py::test_replay_same_event_with_changed_reason_stays_two_rows` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_recommendation_edges_635.py::test_appointment_without_recommendation_writes_no_edges` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_refugee_loop_652.py::test_non_recovery_grant_no_回流` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_refugee_loop_652.py::test_month_settle_with_disaster_and_executing_relief` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rejection_wiring.py::test_rejected_item_lands_in_reports_and_jsonl` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rejection_wiring.py::test_rollback_leaves_no_rows_and_no_jsonl` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rejection_wiring.py::test_issue_summary_nested_rejections_are_collected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rejection_wiring.py::test_nested_atomic_success_path_does_not_orphan_jsonl` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_relation_brew_636.py::test_prepare_claim_db_error_propagates_loudly` — 去掉与夹具自造字符串对齐的 match= 措辞锁
- `tests/test_relation_brew_636.py::test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure` — 去掉与夹具自造字符串对齐的 match= 措辞锁
- `tests/test_relation_brew_636.py::test_mark_failure_after_llm_failure_propagates_loudly` — 去掉与夹具自造字符串对齐的 match= 措辞锁
- `tests/test_relation_brew_636.py::test_brew_program_error_propagates_loudly_not_degraded` — 去掉与夹具自造字符串对齐的 match= 措辞锁
- `tests/test_relation_brew_636.py::test_brew_fn_value_error_is_program_error_propagates_loudly` — 去掉与夹具自造字符串对齐的 match= 措辞锁
- `tests/test_relation_capture_633.py::test_writer_stores_whitespace_context_byte_identical` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_relation_capture_633.py::test_writer_rejects_non_string_context` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_relation_capture_633.py::test_missing_endpoint_qualification_set_fails_loud` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_choices_563.py::test_predeclared_midzhi_promulgation_persists_stigma` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_choices_563.py::test_rejected_midzhi_and_force_promulgation_are_idempotent` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_choices_563.py::test_rejected_ordinary_force_promulgation_adds_rescript_stigma` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_triage_actor_prefers_first_assistant_over_eunuch_director` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_triage_actor_falls_back_to_eunuch_director` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_triage_actor_negative_yumajian_zhangyin_never_selected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_triage_actor_duplicate_hits_deterministic_order` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_triage_actor_absent_when_both_offices_vacant` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_repeated_overwrite_keeps_stable_synthetic_ids` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_and_persist_preserve_whitespace_verbatim` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_binds_only_board_issue_ids` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_no_count_cap_keeps_all_legal` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_generate_missing_required_field_isolates_failed_item_or_option` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_single_option_is_legal` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_many_options_not_gated_or_truncated` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_empty_options_drops_item_keeps_siblings` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_non_list_options_drops_item_keeps_siblings` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_generate_unknown_item_field_drops_the_item` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_rejects_unknown_option_field_whole_batch` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_validate_items_accepts_optional_issue_id_binding_key` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_r3_strict_parse_degrades_via_generate` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_r3_lone_surrogate_field_rejects_whole_batch` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_657_validate_layer_a_roundtrip_capability` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_1620_generate_army_pay_kind_maps_and_rejects_conflicting_shapes` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_rescript_draft_656.py::test_1620_generate_army_pay_rejects_bad_typed_shape` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_dossier_participants_1252.py::test_s1_public_projection_filter_unchanged` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_dossier_participants_1252.py::test_month_segment_dispatch_uses_secret_order_dossier_ids_authority` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_isolation_883.py::test_883_shared_write_seam_keeps_public_assignee_audience` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_isolation_883.py::test_976_pending_secret_pin_survives_partial_commit_same_minister` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_isolation_883.py::test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_isolation_883.py::test_976_rt03_late_chat_after_create_same_turn` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_monthly_progress_566.py::test_titles_do_not_classify_and_all_active_secret_orders_are_candidates` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_monthly_progress_566.py::test_only_an_existing_monthly_chain_gets_terminal_progress` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_monthly_progress_566.py::test_missing_bad_unknown_and_duplicate_reports_are_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_actual_progress_container_separate_from_reported_rail` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_mid_month_restore_preserves_actual_progress` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_submit_unlimited_keeps_frozen_target` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_rush_preserves_frozen_contract` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_1376_candidate_confirm_freezes_explicit_typed_contract` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_create_secret_order_rejects_missing_contract` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_payoff_1504.py::test_purpose_liaoxiang_canonicalizes_to_other_and_counts` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_section_rejections.py::test_update_nonint_order_id_invalid_enum` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_section_rejections.py::test_update_unknown_order_id_missing_ref` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_section_rejections.py::test_update_valid_active_order_applies_no_reject` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_secret_order_section_rejections.py::test_oversized_order_id_rejected_not_crash` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section4_rejections.py::test_region_deltas_code_exception_aborts_settlement` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section4_rejections.py::test_army_deltas_code_exception_aborts_settlement` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_remove_structural_sink_loss_rate_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_remove_central_human_loss_rate_rejected_as_loss_pair` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_remove_central_human_loss_rate_stem_rejected_as_loss_pair` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_unknown_key_rejected_good_change_lands` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_dirty_delta_rejected_sibling_lands` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_zero_delta_no_op_not_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_empty_key_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_structural_sink_loss_rate_below_floor_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_change_central_loss_rate_pair_above_100_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_falsy_dirty_delta_still_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_create_rate_only_sibling_collision_rejected_not_abort` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_empty_key_rejected_even_with_noop_delta` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_remove_missing_key_rejected` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_whitespace_only_key_rejected_at_applier` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_section_fiscal_rejections.py::test_garbage_key_category_consistent_across_sections` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_session_write_queue_1353.py::test_wait_pending_writes_fail_loud_on_false_and_exception` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_start_sh_deps_1721.py::test_start_sh_syncs_requirements_before_uvicorn` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_start_sh_deps_1721.py::test_start_sh_default_path_runs_pip_frontend_and_uvicorn_in_order` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_start_sh_deps_1721.py::test_start_sh_pip_failure_does_not_start_uvicorn` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_state_reload.py::test_reload_skipped_inside_nested_atomic` — 去掉 match=回滚 生产措辞锁
- `tests/test_state_reload.py::test_reload_passes_llm_config_to_content_rebuild` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_state_reload.py::test_atomic_and_reload_skips_reload_when_nested` — 去掉 match=回滚
- `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_state_reload.py::test_atomic_and_reload_runs_on_error_before_reload` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_structured_decree_contract_1624.py::test_combo_correction_preserves_first_draw_roster` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_structured_decree_contract_1624.py::test_batch_combo_correction_real_wrapper` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_supervision_625.py::test_ac1_settle_segment_writes_presence` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_supervision_625.py::test_ac2_paired_observation_slots_and_countermeasure_hard_gate` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_supervision_625.py::test_ac3_same_vs_enemy_origin_marks_on_reported_progress` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_supervision_625.py::test_ac4_exposure_history_delta_on_tendency_surface` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_supervision_625.py::test_due_review_supervision_history_no_longer_hardcoded_empty` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_surcharge_causal_chain_650.py::test_exact_levy_fact_stays_out_of_public_read_chain_and_free_report_enters_it` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_surcharge_causal_chain_650.py::test_e2e_surcharge_and_stop_share_month_open_snapshot` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_transaction_boundary.py::test_swallowed_inner_exception_forces_outer_rollback` — 去掉 match=回滚
- `tests/test_transaction_boundary.py::test_swallowed_conn_context_exception_forces_outer_rollback` — 去掉 match=回滚
- `tests/test_transaction_boundary.py::test_ddl_after_swallowed_conn_context_does_not_escape` — 去掉 match=回滚
- `tests/test_verify_llm_clocks_884.py::test_api_verify_hang_retries_then_exhausts_with_stage` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_verify_llm_clocks_884.py::test_api_verify_installs_sdk_attempt_clock` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_web_chat_serialization_393.py::test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_web_chat_serialization_393.py::test_identity_setup_failure_preserves_question_and_releases_pending_owner` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_web_chat_serialization_393.py::test_lightweight_stream_seam_reaches_done_without_durable_identity_or_night_signature` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_web_chat_serialization_393.py::test_nonstream_chat_rejects_when_session_draining` — 入口为私有 helper；契约有价值但需改公开入口
- `tests/test_web_llm_runtime_config.py::test_build_llm_config_switches_to_api_on_real_key_over_backend_env` — 入口为私有 helper；契约有价值但需改公开入口
- `web/src/appDurableWiring.test.tsx::"App 持久投影 wiring（#499 真实 App 挂载 durable-race tracer）" / "#1276 邸报木牌重开 gazette；史册头起居注另入口解析近臣像"` — 非菜单固定词的拼装材料字面锁
- `web/src/components/modals.test.tsx::"ReportModal — narrative settlement bulletin" / "#1356 报头吃报文自身月 periodLabel，不吃当前 turn 月"` — 非菜单固定词的拼装材料字面锁
- `web/src/useSettlementFlow.test.tsx::"#1845 background tail failure observation" / "refreshes a non-ending month while the tail runs, then stops on persisted failure"` — 真类成员：唯一断言是 loadState.toHaveBeenCalledTimes(1) 两次——纯协作轮询计数锁，无 host/hook failure 表面。需补 mechanical_tail_failure/alert 等可见结果

## Notes

- Retain rows require public/real entry + observable result per J6 gate negatives.
- Web: `fireEvent`/`userEvent` does not retain when only `toHaveBeenCalled` on internals.
- Full JSONL: `j6-wide-disposition-batch3.jsonl`
