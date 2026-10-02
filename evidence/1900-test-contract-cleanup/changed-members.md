# #1900 complete changed-member table

Baseline: f21ce4d05; current working tree. Occurrence distinguishes shadowed duplicate definitions.

| File | Member | Occurrence | Disposition | Before lines | After lines |
|---|---|---:|---|---|---|
| `tests/test_advance_paths_atomic.py` | `test_draft_mutators_frozen_at_front_half_done` | 1 | modified | 463-482 | 438-456 |
| `tests/test_advance_paths_atomic.py` | `test_recovery_replay_blocked_by_pending_directives` | 1 | modified | 422-439 | 419-436 |
| `tests/test_advance_paths_atomic.py` | `test_skip_refused_at_front_half_done` | 1 | removed | 441-461 | — |
| `tests/test_advance_paths_atomic.py` | `test_submit_decisions_does_not_overwrite_already_decided_rows` | 1 | modified | 185-255 | 182-252 |
| `tests/test_advance_without_edict_report_1345.py` | `test_advance_without_edict_shell_absent` | 1 | removed | 88-92 | — |
| `tests/test_applier_contract.py` | `test_apply_context_holds_all_fields` | 1 | removed | 106-113 | — |
| `tests/test_applier_contract.py` | `test_provenance_enum_values` | 1 | removed | 16-22 | — |
| `tests/test_applier_contract.py` | `test_provenance_from_string` | 1 | removed | 25-28 | — |
| `tests/test_applier_contract.py` | `test_rejected_item_constructs_with_fields` | 1 | removed | 50-55 | — |
| `tests/test_applier_contract.py` | `test_rejected_item_fields` | 1 | removed | 35-47 | — |
| `tests/test_applier_contract.py` | `test_section_result_holds_applied_and_rejected` | 1 | removed | 66-70 | — |
| `tests/test_applier_contract.py` | `test_section_result_merge` | 1 | removed | 73-79 | — |
| `tests/test_applier_contract.py` | `test_section_result_merge_empty` | 1 | removed | 82-88 | — |
| `tests/test_army_card_status_1501.py` | `test_army_report_keeps_row_status` | 1 | removed | 178-186 | — |
| `tests/test_army_display_173.py` | `test_army_arrears_presentation_rounds_half_steps_up` | 1 | removed | 93-113 | — |
| `tests/test_army_display_173.py` | `test_army_payload_exposes_approx_arrears_text_not_raw` | 1 | removed | 116-139 | — |
| `tests/test_army_display_173.py` | `test_army_public_exits_approx_arrears_and_hide_split_accounts` | 1 | removed | 56-90 | — |
| `tests/test_army_display_173.py` | `test_army_report_shows_actual_charge` | 1 | removed | 33-53 | — |
| `tests/test_army_firearms.py` | `test_apply_army_delta_sets_firearm` | 1 | modified | 55-67 | 43-57 |
| `tests/test_army_firearms.py` | `test_armies_table_has_firearm_columns` | 1 | removed | 34-38 | — |
| `tests/test_army_firearms.py` | `test_army_public_exits_surface_firearm_and_cannon` | 1 | removed | 121-175 | — |
| `tests/test_army_firearms.py` | `test_score_fields_include_firearm_and_cannon` | 1 | removed | 29-31 | — |
| `tests/test_army_maintenance_retire_173.py` | `test_armies_table_has_no_maintenance_column` | 1 | removed | 42-45 | — |
| `tests/test_army_maintenance_retire_173.py` | `test_drop_maintenance_column_removes_and_idempotent` | 1 | removed | 48-58 | — |
| `tests/test_army_maintenance_retire_173.py` | `test_existing_save_drops_maintenance_column_on_open` | 1 | modified | 61-86 | 46-69 |
| `tests/test_army_salary_44.py` | `test_coerce_new_salary_rate_blocks_freeload` | 1 | removed | 310-319 | — |
| `tests/test_army_salary_44.py` | `test_non_finite_salary_rate_anchored_not_crash` | 1 | removed | 322-336 | — |
| `tests/test_audience_background.py` | `test_chat_reload_exposes_retryable_failed_secret_order` | 1 | modified | 192-212 | 186-205 |
| `tests/test_audience_night_498.py` | `test_old_save_migration_night_id_index_order` | 1 | modified | 533-592 | 529-580 |
| `tests/test_audience_night_498.py` | `test_write_decree_leaves_unacted_pending_unchanged` | 1 | modified | 269-290 | 268-286 |
| `tests/test_audience_scroll_539.py` | `test_history_projection_handlers_are_sync_for_sqlite_access` | 1 | removed | 521-526 | — |
| `tests/test_audience_travel_gating_670.py` | `test_arrived_summon_continuation_survives_failed_apply_across_months` | 1 | modified | 458-538 | 445-518 |
| `tests/test_audience_travel_gating_670.py` | `test_cli_initial_selection_records_remote_summon_without_returning_minister` | 1 | modified | 138-157 | 132-147 |
| `tests/test_audience_travel_gating_670.py` | `test_cli_initial_selection_rejects_unknown_unregistered_person` | 1 | modified | 160-186 | 150-173 |
| `tests/test_audience_travel_gating_670.py` | `test_cli_midflow_summon_consumes_admission_without_entering` | 1 | modified | 694-717 | 674-693 |
| `tests/test_audience_travel_gating_670.py` | `test_cli_midflow_summon_rejects_unknown_unregistered_person` | 1 | modified | 720-748 | 696-720 |
| `tests/test_audience_travel_gating_670.py` | `test_summon_recorder_default_body_is_empty_and_tags_carry_facts` | 1 | modified | 770-788 | 743-757 |
| `tests/test_audience_undo_506.py` | `test_night_direct_write_whitelist_enumerates_authorized_items` | 1 | removed | 156-164 | — |
| `tests/test_audience_undo_506.py` | `test_undo_survives_db_created_before_undone_at_column` | 1 | modified | 550-575 | 541-560 |
| `tests/test_authority_ledger_611.py` | `test_production_path_grant_restore_revoke_impression_tracer` | 1 | modified | 64-177 | 64-176 |
| `tests/test_authority_ledger_611.py` | `test_promulgation_judge_instructions_cover_held_authority_modifiers` | 1 | removed | 492-510 | — |
| `tests/test_centrifuge_ledger_690.py` | `test_t12_restore_preserves_tables_and_rebuild` | 1 | modified | 750-814 | 749-800 |
| `tests/test_character_knowledge_489.py` | `test_delete_chat_messages_removes_chat_derived_knowledge_from_context` | 1 | modified | 250-266 | 250-267 |
| `tests/test_character_knowledge_489.py` | `test_knowledge_projects_mixed_archive_from_durable_source_scope` | 1 | modified | 820-857 | 821-855 |
| `tests/test_character_knowledge_489.py` | `test_knowledge_projects_public_events_without_leaking_private_matters` | 1 | modified | 786-818 | 789-818 |
| `tests/test_character_knowledge_489.py` | `test_long_knowledge_bodies_survive_storage_without_brief_card_cap` | 1 | modified | 465-476 | 466-477 |
| `tests/test_character_knowledge_489.py` | `test_turn_report_counterpart_never_uses_aggregate_when_sources_exist` | 1 | modified | 917-941 | 917-939 |
| `tests/test_character_knowledge_489.py` | `test_turn_report_keeps_source_specific_secret_exclusion_boundary` | 1 | modified | 158-180 | 159-178 |
| `tests/test_character_knowledge_489.py` | `test_turn_report_projects_public_and_secret_items_per_character` | 1 | modified | 182-201 | 181-198 |
| `tests/test_character_knowledge_489.py` | `test_undo_chat_turn_removes_chat_derived_knowledge_from_context` | 1 | modified | 218-247 | 216-247 |
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_deterministic_4xx_no_retry` | 1 | modified | 794-819 | 784-808 |
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_error_status_run_output_system_layer_not_diegetic` | 1 | modified | 1099-1130 | 1088-1115 |
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_run_error_event_sse_system_layer_no_retry` | 1 | modified | 651-678 | 643-669 |
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_three_transient_exhausted_system_fail_then_resend` | 1 | modified | 683-763 | 674-753 |
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_typed_429_preserved` | 1 | modified | 846-876 | 835-864 |
| `tests/test_chat_stream_failpaths_393.py` | `test_worker_cleanup_double_failure_emits_original_error_end_and_logs` | 1 | modified | 325-376 | 325-370 |
| `tests/test_cli_backend.py` | `test_codex_final_text_handles_item_completed_shape` | 1 | removed | 470-477 | — |
| `tests/test_cli_backend.py` | `test_gate_llm_config_api_requires_key_and_url` | 1 | modified | 1244-1254 | 1211-1221 |
| `tests/test_cli_backend.py` | `test_gate_llm_config_cli_requires_runner` | 1 | modified | 1238-1241 | 1205-1208 |
| `tests/test_cli_backend.py` | `test_luna_shaped_stream_keeps_content_when_reasoning_deltas_interleave` | 1 | modified | 430-467 | 408-444 |
| `tests/test_cli_backend.py` | `test_secret_content_assembly_is_emperor_plus_extractor_only` | 1 | removed | 104-125 | — |
| `tests/test_cli_model_choices.py` | `test_choices_cover_all_supported_runners` | 1 | removed | 17-21 | — |
| `tests/test_cli_model_choices.py` | `test_choices_returns_independent_copies` | 1 | removed | 91-96 | — |
| `tests/test_cli_model_choices.py` | `test_claude_offers_haiku_and_sonnet_tiers` | 1 | removed | 78-81 | — |
| `tests/test_cli_model_choices.py` | `test_cli_runner_choices_cover_all_supported_runners` | 1 | removed | 24-31 | — |
| `tests/test_cli_model_choices.py` | `test_cli_runner_choices_returns_independent_copies` | 1 | removed | 34-38 | — |
| `tests/test_cli_model_choices.py` | `test_codex_offers_spark_fast_tier` | 1 | removed | 73-75 | — |
| `tests/test_cli_model_choices.py` | `test_curated_values_are_lowercase_known_ids` | 1 | removed | 84-88 | — |
| `tests/test_cli_model_choices.py` | `test_each_runner_has_default_escape_option_first` | 1 | removed | 41-52 | — |
| `tests/test_cli_play_turn.py` | `test_cli_write_gate_canonical_session_attr` | 1 | removed | 645-654 | — |
| `tests/test_cli_play_turn.py` | `test_play_turn_reports_default_approval_secret_order_failure` | 1 | modified | 396-455 | 383-443 |
| `tests/test_cli_play_turn.py` | `test_play_turn_reports_secret_order_failure_when_settlement_aborts` | 1 | modified | 513-563 | 501-551 |
| `tests/test_cli_play_turn.py` | `test_terminal_failure_printer_preserves_zero_id` | 1 | removed | 382-392 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_chat_answer_path_typed_failure_keeps_scroll_clean` | 1 | removed | 145-161 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_clichat_normal_reply_still_returns` | 1 | modified | 72-89 | 38-47 |
| `tests/test_cli_runner_error_typed_1299.py` | `test_clichat_runner_exit_raises_typed_llm_unavailable` | 1 | modified | 49-69 | 22-35 |
| `tests/test_cli_runner_error_typed_1299.py` | `test_extract_agent_text_error_enum_status_raises` | 1 | removed | 113-118 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_extract_agent_text_error_status_raises_typed_not_leaks_banner` | 1 | removed | 95-110 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_extract_agent_text_normal_reply_passes` | 1 | removed | 121-124 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_extract_agent_text_plain_string_still_works` | 1 | removed | 137-139 | — |
| `tests/test_cli_runner_error_typed_1299.py` | `test_extract_agent_text_preserves_leading_trailing_whitespace` | 1 | removed | 127-134 | — |
| `tests/test_commitment_backlash_626.py` | `test_ac1_breach_verdict_triggers_commitment_backlash` | 1 | modified | 152-200 | 147-194 |
| `tests/test_commitment_backlash_626.py` | `test_ac5_hook_idempotent_no_gate_table_expansion` | 1 | modified | 757-802 | 751-781 |
| `tests/test_commitment_display_348.py` | `TestCommitmentTimedBarValue.test_timed_bar_percentage_clamp_and_none_cases` | 1 | removed | 154-187 | — |
| `tests/test_commitment_display_348.py` | `TestNonTimedDisplayCases.test_arrears_goal_open_types_remain_distinct_and_unbarred` | 1 | removed | 116-145 | — |
| `tests/test_commitment_display_348.py` | `TestPassiveTimedDisplayText.test_no_absolute_month_in_passive_text` | 1 | removed | 90-93 | — |
| `tests/test_commitment_display_348.py` | `TestPassiveTimedDisplayText.test_passive_timed_exposes_duration_and_differs_from_active` | 1 | removed | 95-107 | — |
| `tests/test_commitment_display_348.py` | `TestTimedBarIntegration.test_bar_tracks_elapsed_via_wall_clock` | 1 | modified | 196-232 | 7-30 |
| `tests/test_commitment_display_348.py` | `TestTimedBarIntegration.test_origin_turn_unset_falls_back_to_state_turn` | 1 | removed | 235-259 | — |
| `tests/test_commitment_display_348.py` | `TestTimedDisplayText.test_no_absolute_month_in_text` | 1 | removed | 55-62 | — |
| `tests/test_commitment_display_348.py` | `TestTimedDisplayText.test_timed_text_exposes_relative_duration_elapsed_remaining` | 1 | removed | 64-81 | — |
| `tests/test_credit_events_628.py` | `test_fulfill_back_and_urge_three_decisions` | 1 | modified | 175-368 | 175-367 |
| `tests/test_db_broad_except_surface.py` | `test_legacy_modifiers_corrupt_json_skips_and_surfaces` | 1 | modified | 78-99 | 78-99 |
| `tests/test_db_broad_except_surface.py` | `test_pending_decisions_corrupt_choice_json_returns_none_and_surfaces` | 1 | modified | 41-57 | 41-57 |
| `tests/test_db_broad_except_surface.py` | `test_pending_decisions_corrupt_options_json_falls_back_and_surfaces` | 1 | modified | 21-39 | 21-39 |
| `tests/test_db_broad_except_surface.py` | `test_resolve_context_corrupt_payload_falls_back_and_surfaces` | 1 | modified | 59-75 | 59-75 |
| `tests/test_decision_event_binding_389.py` | `test_ambiguous_title_remains_unbound` | 1 | removed | 48-56 | — |
| `tests/test_decision_event_binding_389.py` | `test_candidate_binding_at_player_prewrite` | 1 | added | — | 16-36 |
| `tests/test_decision_event_binding_389.py` | `test_missing_event_id_binds_from_unique_title` | 1 | removed | 17-21 | — |
| `tests/test_decision_event_binding_389.py` | `test_no_snapshot_returns_decisions_unchanged` | 1 | removed | 59-64 | — |
| `tests/test_decision_event_binding_389.py` | `test_offsnapshot_echoed_event_id_does_not_win_over_snapshot` | 1 | removed | 31-36 | — |
| `tests/test_decision_event_binding_389.py` | `test_offsnapshot_id_with_no_title_match_is_unbound` | 1 | removed | 39-45 | — |
| `tests/test_decision_event_binding_389.py` | `test_valid_echoed_event_id_is_trusted_unchanged` | 1 | removed | 24-28 | — |
| `tests/test_decree_commitment_creation_136.py` | `test_commitment_rejects_string_numeric_person_loyalty_ongoing_effect` | 1 | modified | 732-769 | 673-709 |
| `tests/test_decree_commitment_creation_136.py` | `test_decree_commitment_same_account_alias_miss_emits_residual_signal` | 1 | removed | 185-242 | — |
| `tests/test_decree_commitment_creation_136.py` | `test_decree_commitment_same_account_distinct_key_create_lands` | 1 | added | — | 184-236 |
| `tests/test_decree_commitment_creation_136.py` | `test_decree_commitment_unrelated_account_no_residual_signal` | 1 | removed | 245-285 | — |
| `tests/test_decree_commitment_creation_136.py` | `test_future_one_shot_commitment_shape_rejects_without_explicit_marker` | 1 | modified | 548-574 | 494-519 |
| `tests/test_decree_commitment_creation_136.py` | `test_has_stop_condition_handles_preparsed_and_json_whitespace` | 1 | removed | 1101-1108 | — |
| `tests/test_decree_commitment_creation_136.py` | `test_legacy_resolve_condition_person_commitment_rejects_without_marker` | 1 | modified | 635-670 | 578-612 |
| `tests/test_decree_commitment_creation_136.py` | `test_limited_duration_commitment_shape_rejects_without_explicit_marker` | 1 | modified | 327-363 | 277-312 |
| `tests/test_decree_commitment_creation_136.py` | `test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn` | 1 | modified | 366-404 | 315-352 |
| `tests/test_decree_commitment_creation_136.py` | `test_limited_duration_ongoing_commitment_rejects_past_end_turn` | 1 | modified | 407-447 | 355-394 |
| `tests/test_decree_commitment_creation_136.py` | `test_open_ended_ongoing_commitment_shape_rejects_without_explicit_marker` | 1 | modified | 519-545 | 466-491 |
| `tests/test_decree_commitment_creation_136.py` | `test_stop_condition_only_commitment_shape_rejects_without_explicit_marker` | 1 | modified | 577-603 | 522-547 |
| `tests/test_decree_commitment_creation_136.py` | `test_string_stop_condition_only_with_origin_ref_rejects_without_explicit_marker` | 1 | modified | 606-632 | 550-575 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_rejects_non_dict_stop_condition` | 1 | modified | 772-799 | 712-738 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_rejects_one_shot_entity_creation_as_monthly_work` | 1 | modified | 920-952 | 855-886 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_rejects_semantically_empty_ongoing_effects` | 1 | modified | 890-917 | 826-852 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_rejects_stop_condition_without_table_prefix` | 1 | modified | 802-829 | 741-767 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_requires_initiative_kind` | 1 | modified | 673-700 | 615-641 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_requires_ongoing_effects` | 1 | modified | 861-887 | 798-823 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_requires_origin_ref` | 1 | modified | 832-858 | 770-795 |
| `tests/test_decree_commitment_creation_136.py` | `test_until_stop_commitment_shape_rejects_without_explicit_marker` | 1 | modified | 288-324 | 239-274 |
| `tests/test_decree_commitment_schema_136.py` | `test_effect_dict_has_work_ignores_malformed_person_loyalty` | 1 | removed | 117-118 | — |
| `tests/test_decree_commitment_schema_136.py` | `test_effect_dict_has_work_ignores_metadata_only_payloads` | 1 | removed | 53-54 | — |
| `tests/test_decree_commitment_schema_136.py` | `test_effect_dict_has_work_recognizes_schema_effects` | 1 | removed | 74-75 | — |
| `tests/test_decree_commitment_schema_136.py` | `test_existing_issues_table_gets_commitment_columns_idempotently` | 1 | modified | 219-272 | 157-212 |
| `tests/test_decree_commitment_schema_136.py` | `test_issues_schema_has_commitment_deadline_columns` | 1 | removed | 26-36 | — |
| `tests/test_decree_commitment_settlement_229.py` | `test_commitment_progress_contexts_are_structured` | 1 | removed | 534-564 | — |
| `tests/test_decree_commitment_settlement_229.py` | `test_due_one_shot_commitment_ack_closes_review_loop_without_effects` | 1 | modified | 1400-1462 | 1364-1425 |
| `tests/test_decree_dossiers_571.py` | `test_allocation_rejects_unknown_economy_account_before_dossier_birth` | 1 | modified | 1635-1657 | 1620-1641 |
| `tests/test_decree_dossiers_571.py` | `test_cli_dossiered_directive_is_not_listed_editable_or_deletable` | 1 | modified | 1223-1250 | 1209-1235 |
| `tests/test_decree_dossiers_571.py` | `test_dossier_append_is_idempotent_only_for_identical_character_entry` | 1 | modified | 147-171 | 144-168 |
| `tests/test_decree_dossiers_571.py` | `test_dossier_roster_rejects_unknown_character_references_at_write_boundary` | 1 | modified | 67-90 | 64-87 |
| `tests/test_decree_dossiers_571.py` | `test_dossier_roster_write_boundary_rejects_invalid_delegator` | 1 | modified | 95-121 | 92-118 |
| `tests/test_decree_dossiers_571.py` | `test_final_decree_edit_path_removed_no_bypass` | 1 | modified | 1189-1221 | 1183-1207 |
| `tests/test_decree_dossiers_571.py` | `test_inner_treasury_admission_uses_actual_once_and_preserves_surface` | 1 | modified | 2030-2068 | 2008-2045 |
| `tests/test_decree_dossiers_571.py` | `test_manual_directive_capture_rejects_malformed_roster` | 1 | modified | 1071-1124 | 1068-1119 |
| `tests/test_decree_dossiers_571.py` | `test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes` | 1 | modified | 1131-1187 | 1126-1181 |
| `tests/test_decree_dossiers_571.py` | `test_mechanical_directive_missing_target_fails_loudly_at_real_entry` | 1 | modified | 1740-1765 | 1722-1743 |
| `tests/test_decree_dossiers_571.py` | `test_rejection_contract_rejects_numeric_contamination_without_history` | 1 | modified | 2324-2339 | 2297-2312 |
| `tests/test_decree_dossiers_571.py` | `test_rejection_runtime_contract_rejects_each_missing_field` | 1 | modified | 2270-2279 | 2243-2252 |
| `tests/test_decree_dossiers_571.py` | `test_rejection_runtime_contract_rejects_unknown_references` | 1 | modified | 2287-2296 | 2260-2269 |
| `tests/test_decree_dossiers_571.py` | `test_rejection_snapshot_rejects_malformed_typed_values` | 1 | modified | 2305-2314 | 2278-2287 |
| `tests/test_decree_dossiers_571.py` | `test_secret_authorization_rejects_missing_assignee_without_grant` | 1 | modified | 2124-2149 | 2101-2122 |
| `tests/test_decree_dossiers_571.py` | `test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled` | 1 | modified | 1685-1706 | 1668-1688 |
| `tests/test_decree_dossiers_571.py` | `test_underfunded_in_transit_allocation_closes_from_execution_state` | 1 | modified | 1659-1683 | 1643-1666 |
| `tests/test_deepseek_thinking_disable_1797.py` | `test_dump_llm_messages_records_reasoning_usage_finish_reason` | 1 | removed | 169-249 | — |
| `tests/test_deformation_dual_rail_622.py` | `test_coerce_beyond_intent_flag_closed_affirmative_world` | 1 | removed | 303-322 | — |
| `tests/test_deformation_dual_rail_622.py` | `test_decide_due_review_malformed_beyond_intent_stays_fulfilled` | 1 | removed | 325-338 | — |
| `tests/test_dossier_endorsements_612.py` | `test_endorsement_write_boundary_rejects_unknown_or_illegal_forms` | 1 | modified | 125-172 | 123-170 |
| `tests/test_dossier_reported_progress_619.py` | `test_execution_surface_dossier_can_record_and_list_full_history` | 1 | modified | 78-120 | 78-111 |
| `tests/test_dossier_reported_progress_619.py` | `test_origin_namespace_minimum_closed_set_and_open_append` | 1 | modified | 175-207 | 168-200 |
| `tests/test_dossier_reported_progress_619.py` | `test_production_terminal_sidepath_records_degraded_transformed_only` | 1 | modified | 210-254 | 203-243 |
| `tests/test_dossier_reported_progress_619.py` | `test_short_and_one_shot_dossiers_have_no_empty_monthly_shell` | 1 | modified | 153-172 | 146-165 |
| `tests/test_dossier_reported_progress_619.py` | `test_terminal_surface_dossier_rejects_reported_progress` | 1 | modified | 313-340 | 303-330 |
| `tests/test_draft_admission_resubmit_1769.py` | `test_draft_admission_mixed_good_and_bad_independent` | 1 | modified | 379-417 | 379-415 |
| `tests/test_due_review_621.py` | `test_executing_outcome_rejects_close_true` | 1 | modified | 503-510 | 502-509 |
| `tests/test_due_review_621.py` | `test_five_module_extractor_fanout_is_retired` | 1 | removed | 552-555 | — |
| `tests/test_due_review_621.py` | `test_input_closed_set_degrades_when_sources_missing` | 1 | modified | 582-601 | 577-595 |
| `tests/test_enrich_list_guards.py` | `test_apply_economy_list_non_list_no_crash` | 1 | removed | 29-33 | — |
| `tests/test_enrich_list_guards.py` | `test_apply_economy_list_skips_non_dict_items` | 1 | removed | 66-71 | — |
| `tests/test_enrich_list_guards.py` | `test_apply_economy_list_valid_still_works` | 1 | removed | 36-41 | — |
| `tests/test_enrich_list_guards.py` | `test_apply_metric_faction_class_dict_non_dict_no_crash` | 1 | removed | 74-84 | — |
| `tests/test_enrich_list_guards.py` | `test_enrich_buildings_non_list_no_crash` | 1 | modified | 18-26 | 10-17 |
| `tests/test_enrich_list_guards.py` | `test_inertia_ongoing_non_dict_no_crash` | 1 | modified | 54-63 | 20-46 |
| `tests/test_enrich_list_guards.py` | `test_loads_effect_dict_coerces_non_dict` | 1 | removed | 44-51 | — |
| `tests/test_enter_settlement_period_1235.py` | `test_advance_http_reject_after_accept_exits_display` | 1 | modified | 423-466 | 418-459 |
| `tests/test_enter_settlement_period_1235.py` | `test_concurrent_advance_noncreator_must_not_clear_owner_snapshot` | 1 | modified | 469-508 | 462-499 |
| `tests/test_enter_settlement_period_1235.py` | `test_true_failure_issue_exits_display` | 1 | modified | 283-332 | 279-327 |
| `tests/test_enter_settlement_period_1235.py` | `test_true_failure_pending_translation_exits_display` | 1 | modified | 226-280 | 223-276 |
| `tests/test_enter_settlement_period_1235.py` | `test_web_entry_captures_before_await_close` | 1 | modified | 175-220 | 174-217 |
| `tests/test_event_chain_cascade.py` | `test_conjunctive_positive_terminal_state_predicates_are_intersected` | 1 | modified | 195-211 | 191-206 |
| `tests/test_event_chain_cascade.py` | `test_negative_dependency_invalidates_when_upstream_fired_forbidden_outcome` | 1 | modified | 287-303 | 282-296 |
| `tests/test_event_chain_cascade.py` | `test_numeric_triggered_gt_zero_dependency_invalidates_when_upstream_expires` | 1 | modified | 83-98 | 83-97 |
| `tests/test_event_chain_cascade.py` | `test_numeric_triggered_lt_one_dependency_invalidates_when_upstream_triggers` | 1 | modified | 101-116 | 100-114 |
| `tests/test_event_chain_cascade.py` | `test_terminal_state_expired_dependency_invalidates_when_upstream_obsolete` | 1 | modified | 139-154 | 137-151 |
| `tests/test_event_chain_cascade.py` | `test_terminal_state_in_expired_or_obsolete_invalidates_when_upstream_triggered` | 1 | modified | 157-172 | 154-168 |
| `tests/test_event_trigger_gate.py` | `test_army_numeric_gate_preserves_fractional_arrears_tail` | 1 | modified | 732-742 | 722-741 |
| `tests/test_event_trigger_gate.py` | `test_character_gate_rejects_malformed_field_before_sql` | 1 | modified | 745-752 | 744-756 |
| `tests/test_event_trigger_gate.py` | `test_character_numeric_field_text_gate_raises_clear` | 1 | modified | 755-762 | 759-771 |
| `tests/test_event_trigger_gate.py` | `test_character_numeric_gate_supports_aggregation` | 1 | modified | 719-729 | 700-719 |
| `tests/test_event_trigger_gate.py` | `test_character_numeric_gate_supports_comparison` | 1 | modified | 707-716 | 679-697 |
| `tests/test_event_trigger_gate.py` | `test_character_text_gate_key_passes_content_validation` | 1 | removed | 797-802 | — |
| `tests/test_event_trigger_gate.py` | `test_character_text_gate_rejects_numeric_character_field` | 1 | removed | 812-816 | — |
| `tests/test_event_trigger_gate.py` | `test_character_text_gate_rejects_serialized_list_field` | 1 | removed | 805-809 | — |
| `tests/test_event_trigger_gate.py` | `test_character_text_gate_supports_equality` | 1 | modified | 765-774 | 774-792 |
| `tests/test_event_trigger_gate.py` | `test_character_text_typo_field_gate_raises_clear` | 1 | modified | 787-794 | 810-822 |
| `tests/test_event_trigger_gate.py` | `test_character_typo_field_gate_raises_clear` | 1 | modified | 777-784 | 795-807 |
| `tests/test_event_trigger_gate.py` | `test_event_content_rejects_falsy_person_core_subjects` | 1 | modified | 857-881 | 869-893 |
| `tests/test_event_trigger_gate.py` | `test_gate_cond_form_error_numeric_and_text` | 1 | removed | 489-496 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_cond_numeric_neq_rejected_text_neq_ok` | 1 | removed | 615-623 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_key_form_error_accepts_valid_forms` | 1 | removed | 468-477 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_key_form_error_rejects_typo_metric_table_structure` | 1 | removed | 480-486 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_key_rejects_empty_class_name` | 1 | removed | 645-651 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_key_rejects_empty_region_after_at` | 1 | removed | 687-693 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_key_rejects_empty_segments` | 1 | removed | 626-632 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_passed_tolerates_none` | 1 | removed | 436-441 | — |
| `tests/test_event_trigger_gate.py` | `test_gate_passed_tolerates_nonstring_cond` | 1 | removed | 444-450 | — |
| `tests/test_event_trigger_gate.py` | `test_load_event_fail_loud_on_bad_gate_key` | 1 | removed | 499-508 | — |
| `tests/test_event_trigger_gate.py` | `test_load_event_gate_grammar` | 1 | added | — | 500-512 |
| `tests/test_event_trigger_gate.py` | `test_load_event_rejects_default_terminal_reason_outside_labels` | 1 | modified | 511-523 | 515-527 |
| `tests/test_event_trigger_gate.py` | `test_load_event_rejects_latest_before_earliest` | 1 | modified | 569-581 | 573-585 |
| `tests/test_event_trigger_gate.py` | `test_load_event_rejects_month_out_of_range` | 1 | modified | 590-602 | 594-606 |
| `tests/test_event_trigger_gate.py` | `test_load_event_rejects_non_boolean_open_window` | 1 | modified | 540-552 | 544-556 |
| `tests/test_event_trigger_gate.py` | `test_load_event_rejects_strategic_foreign_situation` | 1 | modified | 555-566 | 559-570 |
| `tests/test_event_trigger_gate.py` | `test_load_event_requires_latest_or_open_window` | 1 | modified | 526-537 | 530-541 |
| `tests/test_event_trigger_gate.py` | `test_load_fail_loud_on_text_cond_multi_id_key` | 1 | modified | 665-674 | 647-656 |
| `tests/test_event_trigger_gate.py` | `test_numeric_cond_on_text_field_raises_clear` | 1 | modified | 696-704 | 663-676 |
| `tests/test_event_trigger_gate.py` | `test_strategic_foreign_classification_requires_outcome_targets` | 1 | modified | 1989-1996 | 1983-1990 |
| `tests/test_event_trigger_gate.py` | `test_text_cond_field_must_be_text_field` | 1 | removed | 677-684 | — |
| `tests/test_event_trigger_gate.py` | `test_text_cond_requires_text_capable_key` | 1 | removed | 654-662 | — |
| `tests/test_event_trigger_gate.py` | `test_typo_field_gate_raises_clear_not_operationalerror` | 1 | modified | 605-612 | 609-621 |
| `tests/test_event_trigger_gate.py` | `test_typo_field_text_gate_raises_clear` | 1 | modified | 635-642 | 628-640 |
| `tests/test_event_trigger_gate.py` | `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | 1 | removed | 1413-1428 | — |
| `tests/test_execution_joint_liability_565.py` | `test_assistant_row_delegator_gets_secondary_assistant_zero_mechanical` | 1 | modified | 256-300 | 251-291 |
| `tests/test_execution_joint_liability_565.py` | `test_dead_liable_party_skips_satisfaction_but_enters_note` | 1 | modified | 187-210 | 184-205 |
| `tests/test_execution_joint_liability_565.py` | `test_dual_role_lead_and_delegator_primary_wins` | 1 | modified | 303-342 | 294-329 |
| `tests/test_execution_joint_liability_565.py` | `test_terminal_outcomes_charge_lead_and_downgraded_delegator` | 1 | modified | 90-134 | 90-131 |
| `tests/test_execution_pressure_654.py` | `test_cli_backend_invalid_target_kind_fail_loud` | 1 | removed | 473-479 | — |
| `tests/test_execution_pressure_654.py` | `test_cli_capture_rejects_bad_target_or_scope` | 1 | added | — | 372-388 |
| `tests/test_execution_pressure_654.py` | `test_cli_target_kinds_accepts_canonical_eight` | 1 | removed | 754-766 | — |
| `tests/test_execution_pressure_654.py` | `test_locality_fail_create_decree_dossiers_zero_rows` | 1 | modified | 733-751 | 642-668 |
| `tests/test_execution_pressure_654.py` | `test_location_canonical_seed_and_write_seam` | 1 | modified | 883-966 | 787-870 |
| `tests/test_execution_pressure_654.py` | `test_mapper_rejects_contradictory_locality_scope_without_overwrite` | 1 | removed | 43-113 | — |
| `tests/test_execution_pressure_654.py` | `test_normalize_locality_scope` | 1 | removed | 34-35 | — |
| `tests/test_execution_pressure_654.py` | `test_normalize_locality_scope_rejects_unknown` | 1 | removed | 38-40 | — |
| `tests/test_execution_pressure_654.py` | `test_path1_conversational_draft_bad_roster_marks_failed` | 1 | modified | 615-664 | 524-572 |
| `tests/test_execution_pressure_654.py` | `test_region_id_column_and_composite_indexes` | 1 | removed | 207-226 | — |
| `tests/test_execution_pressure_654.py` | `test_validate_all_unknown_roster_name_zero_rows_before_insert` | 1 | modified | 503-528 | 412-437 |
| `tests/test_execution_tenure_613.py` | `test_authority_command_relief_single_source_from_privileges` | 1 | removed | 48-52 | — |
| `tests/test_execution_tenure_613.py` | `test_command_power_four_tier_strict_order_and_jianshu_not_collapsed` | 1 | removed | 33-46 | — |
| `tests/test_execution_tenure_613.py` | `test_held_authority_privileges_reduce_distortion_weight` | 1 | removed | 54-59 | — |
| `tests/test_executor_routing_721.py` | `test_canonical_owner_precedes_legacy_with_history_fallback` | 1 | removed | 193-202 | — |
| `tests/test_executor_routing_721.py` | `test_existing_delegated_lead_is_preserved_not_demoted` | 1 | modified | 123-148 | 114-139 |
| `tests/test_executor_routing_721.py` | `test_restore_malformed_durable_json_fails_loud` | 1 | modified | 471-476 | 452-457 |
| `tests/test_executor_routing_721.py` | `test_transaction_category_vocabulary_still_comes_from_duty_routes` | 1 | removed | 71-77 | — |
| `tests/test_executor_routing_721.py` | `test_unnamed_assignment_gets_no_lead_from_code` | 1 | modified | 88-99 | 79-90 |
| `tests/test_faction_brew_637.py` | `test_authority_revoke_edge_reaches_holder_faction_with_emperor_target` | 1 | modified | 428-482 | 427-480 |
| `tests/test_faction_brew_637.py` | `test_faction_brew_prompt_retry_month_does_not_label_old_events_as_current_month` | 1 | removed | 605-666 | — |
| `tests/test_faction_brew_637.py` | `test_faction_brew_retry_preserves_event_dates` | 1 | added | — | 603-641 |
| `tests/test_faction_denunciation_627.py` | `test_ac5_zero_template_exposure_and_622` | 1 | modified | 458-546 | 355-421 |
| `tests/test_faction_denunciation_627.py` | `test_fork_predicate_pure_and_single_source_expression` | 1 | removed | 179-208 | — |
| `tests/test_faction_denunciation_627.py` | `test_no_intensity_quota_template_symbols` | 1 | removed | 224-258 | — |
| `tests/test_faction_denunciation_627.py` | `test_veracity_derivation_mechanical_and_origin_marks` | 1 | removed | 211-221 | — |
| `tests/test_faction_leverage_9.py` | `test_all_court_allowed_types_have_leverage_weight` | 1 | removed | 660-675 | — |
| `tests/test_faction_leverage_9.py` | `test_jundadou_deputy_ouster_impact_is_half_of_principal` | 1 | removed | 609-620 | — |
| `tests/test_faction_leverage_9.py` | `test_legacy_save_calibrates_offset_on_open` | 1 | modified | 810-842 | 675-707 |
| `tests/test_faction_leverage_9.py` | `test_neiting_has_leverage_weight_like_other_court_eunuchs` | 1 | removed | 643-657 | — |
| `tests/test_faction_leverage_9.py` | `test_office_rank_aux_titles_audit_offices_json` | 1 | removed | 578-606 | — |
| `tests/test_faction_leverage_9.py` | `test_office_rank_deputy_titles_not_inflated_to_principal` | 1 | removed | 545-575 | — |
| `tests/test_faction_leverage_9.py` | `test_office_weight_takes_highest_domain_across_joint_offices` | 1 | removed | 529-542 | — |
| `tests/test_faction_leverage_9.py` | `test_xingbu_has_leverage_weight_like_other_ministries` | 1 | removed | 623-640 | — |
| `tests/test_featured_dossiers_494.py` | `test_every_active_seven_faction_minister_has_featured_dossier` | 1 | removed | 40-47 | — |
| `tests/test_featured_dossiers_494.py` | `test_north_star_ministers_have_distinct_featured_voices` | 1 | removed | 66-79 | — |
| `tests/test_featured_dossiers_494.py` | `test_seven_faction_dossiers_are_objective_and_identity_scoped` | 1 | removed | 50-63 | — |
| `tests/test_fiscal_beyond_intent_1260.py` | `test_s2_decide_due_review_shape_unchanged_with_helper` | 1 | removed | 461-485 | — |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_bad_region_does_not_redistribute_jiao_lian_targets` | 1 | modified | 337-378 | 332-373 |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass` | 1 | modified | 437-476 | 432-471 |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_existing_terminal_reason_is_whitelist_validated` | 1 | modified | 578-599 | 573-594 |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_shadow_skips_bad_settle_shape_without_blocking_other_regions` | 1 | modified | 276-304 | 271-299 |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_shadow_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass` | 1 | modified | 250-266 | 249-265 |
| `tests/test_fiscal_levy_effect.py` | `test_jiao_stop_definition_missing_fails_loud` | 1 | modified | 919-930 | 914-925 |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | 1 | modified | 4749-4794 | 4642-4686 |
| `tests/test_fiscal_substrate_bridge.py` | `test_all_ming_settle_substrates_advance_into_ledger` | 1 | added | — | 4844-4881 |
| `tests/test_fiscal_substrate_bridge.py` | `test_all_ming_settle_substrates_advance_with_observable_shadow_tlog` | 1 | removed | 5026-5102 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_apply_fixed_period_flows_malformed_fiscal_container_isolated` | 1 | modified | 4826-4852 | 4719-4741 |
| `tests/test_fiscal_substrate_bridge.py` | `test_apply_fixed_period_flows_malformed_fiscal_json_isolated` | 1 | modified | 4876-4904 | 4744-4766 |
| `tests/test_fiscal_substrate_bridge.py` | `test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated` | 1 | modified | 4911-4943 | 4776-4803 |
| `tests/test_fiscal_substrate_bridge.py` | `test_armies_provision_empty_mutiny_status_flag` | 1 | modified | 2333-2347 | 2280-2288 |
| `tests/test_fiscal_substrate_bridge.py` | `test_army_delta_owner_power_to_ming_requires_same_delta_pay_source` | 1 | modified | 2666-2714 | 2600-2647 |
| `tests/test_fiscal_substrate_bridge.py` | `test_army_delta_rejects_pay_source_without_ming_settle_substrate` | 1 | modified | 2751-2779 | 2684-2711 |
| `tests/test_fiscal_substrate_bridge.py` | `test_army_pay_morale_formula_clamps_shortfall_and_old_arrears_gate` | 1 | removed | 2469-2475 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | 1 | modified | 4670-4693 | 4566-4586 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | 1 | modified | 4598-4645 | 4494-4541 |
| `tests/test_fiscal_substrate_bridge.py` | `test_fixed_flow_loader_accepts_already_decoded_fiscal_dict` | 1 | removed | 4946-4954 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_fixed_flow_loader_rejects_decoded_non_dict_payloads` | 1 | removed | 4975-4985 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_fixed_flow_loader_rejects_non_finite_numeric_values` | 1 | removed | 4958-4971 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_new_ming_army_rejects_non_ming_pay_source_region` | 1 | modified | 3314-3338 | 3245-3268 |
| `tests/test_fiscal_substrate_bridge.py` | `test_new_ming_army_requires_valid_pay_source_under_cutover` | 1 | modified | 3297-3311 | 3229-3242 |
| `tests/test_fiscal_substrate_bridge.py` | `test_pay_source_conservation_rejects_per_army_derived_arrears_drift` | 1 | modified | 2638-2648 | 2572-2582 |
| `tests/test_fiscal_substrate_bridge.py` | `test_primary_source_army_pay_due_rejects_dirty_annual_amount` | 1 | modified | 4061-4066 | 3979-3984 |
| `tests/test_fiscal_substrate_bridge.py` | `test_province_pay_shortfall_reduces_pure_province_army_morale` | 1 | modified | 2198-2292 | 2192-2277 |
| `tests/test_fiscal_substrate_bridge.py` | `test_region_loader_expands_shared_settle_meta_defaults` | 1 | modified | 399-433 | 398-426 |
| `tests/test_fiscal_substrate_bridge.py` | `test_region_loader_rejects_bad_plain_settle_meta` | 1 | modified | 3410-3417 | 3340-3347 |
| `tests/test_fiscal_substrate_bridge.py` | `test_region_loader_rejects_bad_settle_meta_defaults` | 1 | modified | 3445-3453 | 3375-3383 |
| `tests/test_fiscal_substrate_bridge.py` | `test_region_loader_rejects_bad_shared_settle_meta_defaults_container` | 1 | modified | 3399-3407 | 3329-3337 |
| `tests/test_fiscal_substrate_bridge.py` | `test_shaanxi_seed_is_relabelled_to_historical_shadow_scale` | 1 | modified | 3835-3865 | 3755-3783 |
| `tests/test_fiscal_substrate_bridge.py` | `test_shadow_spine_uses_batch_bridge_without_per_region_reload` | 1 | removed | 5105-5138 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_standalone_army_pay_container_total_rejects_malformed_region_shapes` | 1 | modified | 4108-4119 | 4026-4037 |
| `tests/test_fiscal_substrate_bridge.py` | `test_standalone_army_pay_funnel_rejects_malformed_settle_shapes` | 1 | modified | 4078-4085 | 3996-4003 |
| `tests/test_fiscal_substrate_bridge.py` | `test_substrate_malformed_fiscal_container_is_logged_not_prefiltered` | 1 | removed | 4497-4515 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_substrate_malformed_fiscal_json_is_logged_not_prefiltered` | 1 | removed | 4855-4873 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_substrate_malformed_settle_shape_is_logged_not_prefiltered` | 1 | modified | 4470-4494 | 4388-4411 |
| `tests/test_fiscal_substrate_bridge.py` | `test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills` | 1 | removed | 2295-2330 | — |
| `tests/test_fiscal_substrate_bridge.py` | `test_zhongyuan_jingshi_primary_source_refinement` | 1 | modified | 3621-3666 | 3551-3586 |
| `tests/test_fiscal_tick.py` | `test_fiscal_fail_loud` | 1 | modified | 146-149 | 146-148 |
| `tests/test_highlight_judge_544.py` | `test_chat_nonstream_folds_judge_within_timeout` | 1 | modified | 281-314 | 274-306 |
| `tests/test_highlight_judge_544.py` | `test_chat_nonstream_timeout_returns_reply_without_highlights` | 1 | modified | 317-368 | 309-359 |
| `tests/test_highlight_judge_544.py` | `test_chat_stream_done_before_highlights_and_degrade` | 1 | modified | 205-230 | 200-224 |
| `tests/test_highlight_judge_544.py` | `test_chat_stream_slow_success_attaches_after_done` | 1 | modified | 233-278 | 227-271 |
| `tests/test_highlight_judge_544.py` | `test_parse_highlight_judge_bad_output_is_empty` | 1 | removed | 29-34 | — |
| `tests/test_highlight_judge_544.py` | `test_parse_highlight_judge_valid_phrases` | 1 | removed | 37-40 | — |
| `tests/test_highlight_judge_544.py` | `test_run_highlight_judge_success_returns_phrases` | 1 | modified | 74-84 | 69-79 |
| `tests/test_history_decree_text_1843_reopen.py` | `test_history_turn_reads_decree_text_from_resolve_context` | 1 | modified | 6-30 | 6-23 |
| `tests/test_hitl_quota_delete_1467.py` | `test_hitl_quota_mechanism_fully_deleted` | 1 | removed | 42-72 | — |
| `tests/test_identity_seed_488.py` | `test_identity_and_seed_guilt_never_enter_minister_context` | 1 | removed | 110-117 | — |
| `tests/test_identity_seed_488.py` | `test_identity_and_seed_guilt_survive_restore` | 1 | modified | 32-47 | 32-47 |
| `tests/test_identity_seed_488.py` | `test_roster_rejects_alias_colliding_with_other_faction_name` | 1 | modified | 129-134 | 121-126 |
| `tests/test_identity_seed_488.py` | `test_roster_rejects_duplicate_canonical_name` | 1 | modified | 137-144 | 129-135 |
| `tests/test_identity_seed_488.py` | `test_seed_schema_rejects_invalid_values` | 1 | modified | 155-160 | 146-151 |
| `tests/test_initiative_resolve_pairing.py` | `test_emit_preparsed_dict_ongoing_no_false_warn` | 1 | removed | 174-185 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_emit_preparsed_list_tags_still_warns` | 1 | removed | 157-171 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_fiscal_account_not_applied_by_flows_warns` | 1 | removed | 88-91 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_fiscal_invalid_economy_shell_warns` | 1 | removed | 61-71 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_fiscal_numeric_string_delta_no_warn` | 1 | removed | 94-97 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_fiscal_recurring_initiative_without_economy_warns` | 1 | removed | 35-38 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_fiscal_recurring_with_ongoing_economy_no_warn` | 1 | removed | 41-45 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_malformed_pairing_shape_warns` | 1 | removed | 108-113 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_military_effect_with_only_legacy_office_changes_warns` | 1 | removed | 53-58 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_military_initiative_with_new_armies_no_warn` | 1 | removed | 22-25 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_military_initiative_with_office_change_no_warn` | 1 | removed | 28-32 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_military_initiative_without_army_warns` | 1 | removed | 15-19 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_move_with_only_army_still_warns` | 1 | removed | 81-85 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_neutral_initiative_no_warn` | 1 | removed | 48-50 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_nonlist_economy_no_crash_warns` | 1 | removed | 100-105 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_raise_with_only_person_change_still_warns` | 1 | removed | 74-78 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_resolve_surfaces_pairing_warning_in_result` | 1 | removed | 116-132 | — |
| `tests/test_initiative_resolve_pairing.py` | `test_resolve_with_new_armies_no_warning_in_result` | 1 | removed | 135-154 | — |
| `tests/test_issue_decree_token_1277.py` | `test_double_issue_same_token_second_is_409_turn_plus_one` | 1 | modified | 76-111 | 75-109 |
| `tests/test_issue_entities.py` | `test_apply_score_extraction_accepts_flat_faction_scalar` | 1 | modified | 325-334 | 325-337 |
| `tests/test_issue_entities.py` | `test_apply_score_extraction_rejects_unknown_top_level_key` | 1 | modified | 359-370 | 364-375 |
| `tests/test_issue_entities.py` | `test_apply_score_extraction_tolerates_null_field` | 1 | modified | 351-356 | 354-361 |
| `tests/test_issue_entities.py` | `test_issue_person_change_effect_rejects_malformed_shape` | 1 | modified | 265-269 | 265-269 |
| `tests/test_issue_entities.py` | `test_legacy_issue_status_change_uses_person_transition_matrix` | 1 | modified | 71-91 | 71-91 |
| `tests/test_issue_entities.py` | `test_resolve_rejects_bad_unified_person_change_effect` | 1 | modified | 251-261 | 251-261 |
| `tests/test_junxin_monthly_tick_314.py` | `test_loyalty_tick_delta_tiers` | 1 | removed | 101-102 | — |
| `tests/test_junxin_monthly_tick_314.py` | `test_loyalty_tick_delta_zero_needed_no_div_zero` | 1 | removed | 105-106 | — |
| `tests/test_llm_channel_config.py` | `test_cli_reasoning_strength_runners_single_source_in_cli_backend` | 1 | removed | 819-830 | — |
| `tests/test_llm_channel_config.py` | `test_cli_supports_reasoning_strength_matrix` | 1 | removed | 812-816 | — |
| `tests/test_llm_channel_config.py` | `test_config_constants_single_source_in_models` | 1 | removed | 696-719 | — |
| `tests/test_llm_channel_config.py` | `test_create_chat_model_never_injects_max_tokens` | 1 | modified | 207-233 | 207-232 |
| `tests/test_llm_channel_config.py` | `test_gate_evidence_config_omits_max_tokens` | 1 | modified | 915-924 | 838-846 |
| `tests/test_llm_channel_config.py` | `test_web_runtime_cli_no_saved_timeout_uses_cli_default` | 1 | removed | 733-747 | — |
| `tests/test_llm_key_helpers.py` | `test_is_real_api_key_accepts_real_key_trimmed` | 1 | removed | 31-33 | — |
| `tests/test_llm_key_helpers.py` | `test_is_real_api_key_rejects_keep_sentinel` | 1 | removed | 24-28 | — |
| `tests/test_llm_key_helpers.py` | `test_is_real_api_key_rejects_none_empty_placeholder_whitespace` | 1 | removed | 16-21 | — |
| `tests/test_llm_key_helpers.py` | `test_real_api_key_or_empty_normalizes_falsy_and_placeholder_to_empty` | 1 | removed | 36-40 | — |
| `tests/test_llm_key_helpers.py` | `test_real_api_key_or_empty_returns_trimmed_real_key` | 1 | removed | 43-45 | — |
| `tests/test_manual_directive_institution_normalize_1279.py` | `test_adr0053_unknown_person_still_rejected_at_capture` | 1 | modified | 228-246 | 212-226 |
| `tests/test_manual_directive_institution_normalize_1279.py` | `test_non_person_filter_does_not_use_institution_substring_class` | 1 | removed | 210-225 | — |
| `tests/test_material_directory_1830.py` | `test_material_tree_contains_only_structurally_related_world_details` | 1 | modified | 110-155 | 99-138 |
| `tests/test_material_directory_1830.py` | `test_read_material_stays_inside_directory` | 1 | modified | 216-246 | 199-228 |
| `tests/test_mechanical_tail_1845.py` | `test_chapter_memory_retired_from_three_readers` | 1 | modified | 449-515 | 447-507 |
| `tests/test_mechanical_tail_1845.py` | `test_mechanical_tail_missing_llm_config_surfaces_retry` | 1 | modified | 518-574 | 510-565 |
| `tests/test_menu_lifecycle_drain_396.py` | `test_drain_waits_for_queued_chat_stream_not_just_gate_holder` | 1 | modified | 567-640 | 561-633 |
| `tests/test_mindreading_491.py` | `test_attendant_is_selected_by_office_not_name` | 1 | removed | 8-19 | — |
| `tests/test_mindreading_491.py` | `test_only_exact_attendant_slots_are_identified` | 1 | removed | 22-29 | — |
| `tests/test_month_chain_1843.py` | `test_held_dossier_settlement_failure_retry_and_reentry_isolation` | 1 | modified | 500-583 | 496-578 |
| `tests/test_month_open_snapshot_1234.py` | `test_oracle_normal_phase_clears_via_startup_hook` | 1 | modified | 180-204 | 180-202 |
| `tests/test_month_open_snapshot_1234.py` | `test_web_advance_entry_awaiting_keeps_phase_and_decisions` | 1 | modified | 405-464 | 402-460 |
| `tests/test_month_open_snapshot_1234.py` | `test_web_advance_entry_exposes_settlement_display` | 1 | modified | 357-402 | 355-399 |
| `tests/test_mutiny_actual_residence_659.py` | `test_fresh_seed_station_region_and_class_slices` | 1 | modified | 145-163 | 142-157 |
| `tests/test_mutiny_latch_315.py` | `test_derive_mutiny_state_boundaries_and_latch` | 1 | removed | 127-130 | — |
| `tests/test_mutiny_latch_315.py` | `test_mutiny_latch_uses_strict_four_month_arrears_boundary` | 1 | removed | 152-159 | — |
| `tests/test_mutiny_progression_316.py` | `test_old_save_migrates_and_mutiny_progress_survives_reopen` | 1 | modified | 124-160 | 124-158 |
| `tests/test_mutiny_redemption_317.py` | `test_redemption_progress_migrates_and_survives_reopen` | 1 | modified | 131-163 | 131-161 |
| `tests/test_mutiny_third_strike_318.py` | `test_single_production_owner_power_updater_exists` | 1 | removed | 588-600 | — |
| `tests/test_mutiny_third_strike_318.py` | `test_single_production_zero_manpower_clear_callsite` | 1 | removed | 571-585 | — |
| `tests/test_named_characters_seed_484.py` | `test_r4_loader_rejects_seed_guilt_list` | 1 | modified | 101-125 | 101-125 |
| `tests/test_named_characters_seed_484.py` | `test_r5_loader_rejects_nested_seed_guilt_crime_list` | 1 | modified | 157-161 | 157-161 |
| `tests/test_named_characters_seed_484.py` | `test_r5_loader_rejects_nested_seed_guilt_severity_object` | 1 | modified | 164-168 | 164-168 |
| `tests/test_new_game_smoke.py` | `test_unknown_event_id_fails_without_synthesizing_parent` | 1 | modified | 81-88 | 81-88 |
| `tests/test_new_game_smoke.py` | `test_unknown_office_type_fails_without_synthesizing_parent` | 1 | modified | 91-100 | 91-100 |
| `tests/test_no_edict_full_settlement_1274.py` | `test_no_edict_fast_path_branch_is_dead` | 1 | modified | 77-103 | 76-95 |
| `tests/test_office_inference.py` | `test_office_type_from_table` | 1 | removed | 48-49 | — |
| `tests/test_office_inference.py` | `test_runtime_cli_unknown_office_uses_configured_runner_without_env` | 1 | modified | 78-101 | 58-80 |
| `tests/test_office_inference.py` | `test_后宫_current_type_short_circuits` | 1 | removed | 52-53 | — |
| `tests/test_office_rank_562.py` | `test_cabinet_titles_keep_nominal_ming_rank_instead_of_political_importance` | 1 | removed | 184-191 | — |
| `tests/test_office_rank_562.py` | `test_concurrent_cabinet_office_uses_the_genuinely_higher_title` | 1 | removed | 194-198 | — |
| `tests/test_office_rank_562.py` | `test_historical_military_commands_and_cabinet_fallback_use_nominal_bands` | 1 | removed | 240-242 | — |
| `tests/test_office_rank_562.py` | `test_leverage_multiplier_uses_canonical_office_rank_table_only` | 1 | removed | 209-222 | — |
| `tests/test_office_rank_562.py` | `test_leverage_uses_min_modifiers_within_title_and_max_across_offices` | 1 | removed | 253-257 | — |
| `tests/test_office_rank_562.py` | `test_one_tokenizer_preserves_real_concurrent_offices_and_drops_only_pollution` | 1 | removed | 245-250 | — |
| `tests/test_office_rank_562.py` | `test_qualified_titles_match_the_requested_axis_not_an_institutional_stem` | 1 | removed | 201-206 | — |
| `tests/test_office_rank_562.py` | `test_rank_table_covers_every_office_type_and_pins_ming_direction` | 1 | removed | 38-48 | — |
| `tests/test_office_rank_562.py` | `test_seed_archives_clean_historical_office_for_dismissed_ministers` | 1 | modified | 393-421 | 307-333 |
| `tests/test_office_rank_562.py` | `test_title_stems_keep_distinct_ming_bands_inside_same_office_type` | 1 | removed | 160-181 | — |
| `tests/test_on_scene_immediate_write_1839.py` | `test_kill_lands_status_and_next_materials_show_it` | 1 | removed | 69-106 | — |
| `tests/test_on_scene_immediate_write_1839.py` | `test_kill_lands_status_in_world_ledger` | 1 | added | — | 69-91 |
| `tests/test_opening_gazette_delete_1356.py` | `test_state_payload_t0_previous_summary_empty` | 1 | modified | 130-160 | 129-159 |
| `tests/test_override_breach_costs_564.py` | `test_force_rejects_malformed_judge_reactions_before_any_cost` | 1 | modified | 406-422 | 398-414 |
| `tests/test_override_breach_costs_564.py` | `test_force_rejects_missing_or_stale_judge_reactions_before_any_cost` | 1 | modified | 390-403 | 382-395 |
| `tests/test_override_breach_costs_564.py` | `test_force_rejects_old_only_judge_reactions_atomically` | 1 | modified | 425-440 | 417-432 |
| `tests/test_override_breach_costs_564.py` | `test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently` | 1 | modified | 315-367 | 315-359 |
| `tests/test_override_breach_costs_564.py` | `test_public_apply_rejects_invalid_mode_decision_reaction_shape_before_writes` | 1 | modified | 268-285 | 268-285 |
| `tests/test_pay_order_override_653.py` | `test_arrears_order_resolution_default_and_override` | 1 | removed | 215-220 | — |
| `tests/test_pay_order_override_653.py` | `test_central_hub_tier_order_and_old_arrears_unchanged_by_haircut` | 1 | removed | 1330-1348 | — |
| `tests/test_pay_order_override_653.py` | `test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e` | 1 | modified | 1656-1713 | 1552-1604 |
| `tests/test_pay_order_override_653.py` | `test_expired_only_keys_return_none_fast_path` | 1 | removed | 223-229 | — |
| `tests/test_pay_order_override_653.py` | `test_fiscal_fact_brief_bad_json_fails_loud` | 1 | modified | 1064-1069 | 977-982 |
| `tests/test_pay_order_override_653.py` | `test_fiscal_fact_brief_present_but_malformed_fails_loud` | 1 | modified | 1056-1061 | 969-974 |
| `tests/test_pay_order_override_653.py` | `test_fiscal_fact_brief_pure_projection_deterministic_tsv` | 1 | removed | 680-699 | — |
| `tests/test_pay_order_override_653.py` | `test_golden1_pay_order_reversal_breakdown` | 1 | added | — | 181-196 |
| `tests/test_pay_order_override_653.py` | `test_golden1_pay_order_reversal_breakdown_tsv` | 1 | removed | 234-252 | — |
| `tests/test_pay_order_override_653.py` | `test_golden5_expiry_and_revoke_restore_byte_identical_default` | 1 | modified | 314-356 | 258-299 |
| `tests/test_pay_order_override_653.py` | `test_haircut_value_domain_fail_loud` | 1 | modified | 98-101 | 97-102 |
| `tests/test_pay_order_override_653.py` | `test_legacy_engine_pay_order_materialize_fails_loud_not_fulfilled` | 1 | modified | 890-908 | 803-821 |
| `tests/test_pay_order_override_653.py` | `test_lifecycle_promulgated_materializes_and_next_settlement_reads` | 1 | modified | 1132-1153 | 1045-1065 |
| `tests/test_pay_order_override_653.py` | `test_override_key_illegal_shapes_fail_loud` | 1 | modified | 92-94 | 88-93 |
| `tests/test_pay_order_override_653.py` | `test_override_key_legal_shapes` | 1 | modified | 74-75 | 68-71 |
| `tests/test_pay_order_override_653.py` | `test_precedence_region_beats_bare_and_full_order` | 1 | removed | 195-206 | — |
| `tests/test_pay_order_override_653.py` | `test_priority_tie_breaks_on_default_baseline_stable` | 1 | removed | 209-212 | — |
| `tests/test_pay_order_override_653.py` | `test_priority_value_domain_rejects_non_int` | 1 | modified | 104-109 | 106-111 |
| `tests/test_pay_order_override_653.py` | `test_proposed_revoke_does_not_restore_override` | 1 | modified | 397-437 | 339-379 |
| `tests/test_pay_order_override_653.py` | `test_r3_central_side_scope_resolution` | 1 | removed | 157-177 | — |
| `tests/test_pay_order_override_653.py` | `test_r4_golden1_region_source_specificity_wins` | 1 | removed | 140-154 | — |
| `tests/test_pay_order_override_653.py` | `test_r4_golden2_expiry_falls_back_to_next_specific` | 1 | modified | 180-192 | 146-168 |
| `tests/test_pay_order_override_653.py` | `test_real_revoke_decree_restores_override_and_clears_expiry` | 1 | modified | 359-394 | 302-336 |
| `tests/test_pay_order_override_653.py` | `test_rejected_revoke_does_not_restore_override` | 1 | modified | 440-483 | 382-425 |
| `tests/test_pay_order_override_653.py` | `test_revoke_provincial_falls_back_to_nationwide` | 1 | modified | 803-833 | 725-746 |
| `tests/test_pay_order_override_653.py` | `test_stale_until_cleared_by_permanent_overwrite` | 1 | modified | 1187-1210 | 1099-1127 |
| `tests/test_pay_order_override_extraction_653.py` | `test_relative_deadline_cannot_stage_llm_computed_expired_turn` | 1 | modified | 55-70 | 50-65 |
| `tests/test_pay_order_override_extraction_653.py` | `test_single_pay_order_capture_grounds_relative_deadline_at_current_turn` | 1 | modified | 8-52 | 8-46 |
| `tests/test_person_archive_schema.py` | `test_characters_table_has_person_archive_fields` | 1 | removed | 20-37 | — |
| `tests/test_person_archive_schema.py` | `test_old_save_schema_is_upgraded_for_person_archive_fields` | 1 | modified | 155-195 | 96-143 |
| `tests/test_person_archive_schema.py` | `test_person_logs_table_records_person_archive_audit_chain` | 1 | removed | 40-77 | — |
| `tests/test_person_archive_schema.py` | `test_reload_restores_complete_transit_ledger_from_db` | 1 | modified | 135-152 | 76-93 |
| `tests/test_person_delta_adapter.py` | `test_add_character_non_canonical_office_type_still_raises` | 1 | modified | 1753-1760 | 1661-1668 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_does_not_release_non_ming_when_derived_appointment_is_rejected` | 1 | modified | 1417-1474 | 1324-1382 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_does_not_release_when_derived_appointment_is_invalid` | 1 | modified | 1121-1171 | 1027-1078 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_dead_status_outbound` | 1 | modified | 1899-1921 | 1808-1831 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_invalid_loyalty_assessment` | 1 | modified | 298-324 | 201-228 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_invalid_person_travel` | 1 | modified | 2125-2159 | 2035-2071 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_malformed_power_move_backlash_before_writing` | 1 | modified | 518-561 | 422-466 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_person_change_power_move_without_way` | 1 | modified | 165-189 | 67-92 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_unknown_person_change` | 1 | modified | 1875-1896 | 1783-1805 |
| `tests/test_person_delta_adapter.py` | `test_apply_score_extraction_rejects_unknown_person_travel_region` | 1 | modified | 2162-2186 | 2074-2099 |
| `tests/test_person_delta_adapter.py` | `test_empty_new_person_change_key_does_not_shadow_legacy_normalization` | 1 | removed | 2371-2381 | — |
| `tests/test_person_delta_adapter.py` | `test_legacy_office_pollution_migrated_on_load` | 1 | modified | 2613-2638 | 2515-2540 |
| `tests/test_person_delta_adapter.py` | `test_legacy_office_pollution_resolves_transit_to_region_id` | 1 | removed | 2641-2658 | — |
| `tests/test_person_delta_adapter.py` | `test_legacy_status_change_rejects_non_active_target_before_transition_matrix` | 1 | modified | 564-612 | 469-518 |
| `tests/test_person_delta_adapter.py` | `test_normalize_legacy_person_changes_preserves_origin` | 1 | removed | 120-123 | — |
| `tests/test_person_delta_adapter.py` | `test_normalize_person_changes_ignores_non_item_shapes` | 1 | removed | 126-133 | — |
| `tests/test_person_delta_adapter.py` | `test_normalize_person_changes_keeps_new_key_items` | 1 | removed | 29-50 | — |
| `tests/test_person_delta_adapter.py` | `test_normalize_person_changes_translates_legacy_keys_in_replay_order` | 1 | removed | 53-108 | — |
| `tests/test_person_transit_write_667.py` | `test_departure_rejects_nonfinite_distance_before_ledger_write` | 1 | modified | 17-51 | 17-51 |
| `tests/test_pihong_dossier_1490.py` | `test_1620_generate_money_grant_admission` | 1 | added | — | 1707-1734 |
| `tests/test_pihong_dossier_1490.py` | `test_1620_layer_a_money_grant_requires_positive_amount` | 1 | removed | 1807-1836 | — |
| `tests/test_pihong_dossier_1490.py` | `test_1621_http_follow_draft_uses_catalog_army_id` | 2 | removed | 3029-3092 | — |
| `tests/test_pihong_dossier_1490.py` | `test_1682_phase2_surfaces_ambiguous_stored_choice` | 1 | modified | 1976-1990 | 1873-1887 |
| `tests/test_pihong_dossier_1490.py` | `test_657_abi_mapper_matrix_a1_a12` | 1 | modified | 926-1167 | 892-1129 |
| `tests/test_pihong_dossier_1490.py` | `test_657_appointment_name_target_id_conflict_batch_reject` | 1 | modified | 2017-2027 | 1914-1924 |
| `tests/test_pihong_dossier_1490.py` | `test_657_c1_decided_mismatch_rejects_and_cas0` | 1 | modified | 548-564 | 516-532 |
| `tests/test_pihong_dossier_1490.py` | `test_657_c1_validate_rejects_stale_capability_and_desk_outsider` | 1 | modified | 537-546 | 505-514 |
| `tests/test_pihong_dossier_1490.py` | `test_657_clear_revise_anchor_corrupt_json_fails_loud` | 1 | modified | 1992-2004 | 1889-1901 |
| `tests/test_pihong_dossier_1490.py` | `test_657_five_actions_domain_writes` | 1 | modified | 690-754 | 658-720 |
| `tests/test_pihong_dossier_1490.py` | `test_657_illegal_summon_target_http_zero_writes` | 1 | modified | 1717-1738 | 1610-1630 |
| `tests/test_pihong_dossier_1490.py` | `test_657_midzhi_persists_decision_key_and_llm_label` | 1 | modified | 1861-1879 | 1759-1777 |
| `tests/test_pihong_dossier_1490.py` | `test_657_mixed_batch_follow_plus_decision_and_no_context_copy` | 1 | modified | 1467-1520 | 1363-1415 |
| `tests/test_pihong_dossier_1490.py` | `test_657_p6_mapper_deliberate_preserve_free_text` | 1 | modified | 566-620 | 534-588 |
| `tests/test_pihong_dossier_1490.py` | `test_657_prewrite_failure_zero_db_writes` | 1 | modified | 905-924 | 871-890 |
| `tests/test_pihong_dossier_1490.py` | `test_657_s6_http_present_target_gets_unique_origin_entry` | 1 | modified | 1619-1646 | 1514-1540 |
| `tests/test_pihong_dossier_1490.py` | `test_657_summon_missing_tag_enter_blocks_phase2_then_retry` | 1 | modified | 1901-1951 | 1799-1848 |
| `tests/test_pihong_dossier_1490.py` | `test_657_web_http_hitl_lock_boundary_same_gate` | 1 | modified | 1649-1715 | 1543-1608 |
| `tests/test_pihong_dossier_1490.py` | `test_658_candidates_require_active_status` | 1 | modified | 2553-2567 | 2450-2464 |
| `tests/test_pihong_dossier_1490.py` | `test_658_deliberate_backed_and_stalled_dossier_first` | 1 | modified | 2450-2499 | 2347-2396 |
| `tests/test_pihong_dossier_1490.py` | `test_658_endorsement_provenance_xor` | 1 | modified | 2535-2551 | 2432-2448 |
| `tests/test_pihong_dossier_1490.py` | `test_658_free_decree_capture_target_dossier_real_entry` | 1 | modified | 2569-2652 | 2466-2549 |
| `tests/test_pihong_dossier_1490.py` | `test_658_mixed_ordinary_triad_and_target_rejected` | 1 | modified | 2816-2831 | 2713-2728 |
| `tests/test_pihong_dossier_1490.py` | `test_bind_preserves_dossier_event_id` | 1 | removed | 332-338 | — |
| `tests/test_pihong_dossier_1490.py` | `test_bind_unbinds_dossier_prefix_without_capability_fields` | 1 | removed | 340-347 | — |
| `tests/test_pihong_dossier_1490.py` | `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | 1 | modified | 357-382 | 339-363 |
| `tests/test_pihong_dossier_1490.py` | `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | 1 | modified | 293-330 | 293-329 |
| `tests/test_pihong_dossier_1490.py` | `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | 1 | modified | 422-470 | 391-439 |
| `tests/test_pihong_dossier_1490.py` | `test_ordinary_event_with_hallucinated_capability_submits` | 1 | modified | 472-504 | 441-472 |
| `tests/test_pihong_dossier_1490.py` | `test_parse_rescript_capability_pair_rejects_non_positive_and_unknown` | 1 | removed | 409-420 | — |
| `tests/test_player_army_projection_321.py` | `test_army_state_and_map_payloads_project_situation` | 1 | added | — | 204-254 |
| `tests/test_player_army_projection_321.py` | `test_four_chains_embed_situation_matrix` | 1 | removed | 239-331 | — |
| `tests/test_player_army_projection_321.py` | `test_player_army_situation_six_tier_truth_table` | 1 | removed | 103-116 | — |
| `tests/test_population_transfers_649.py` | `test_mutation_oracle_four_mutations_all_bitten` | 1 | removed | 382-417 | — |
| `tests/test_population_transfers_649.py` | `test_section_non_list_rejects_section_rest_lands` | 1 | modified | 219-236 | 217-234 |
| `tests/test_population_transfers_649.py` | `test_unknown_top_level_key_now_per_section_rejection_not_abort` | 1 | removed | 289-300 | — |
| `tests/test_population_transfers_662.py` | `test_mutation_oracle_bites_disaster_war_mutations` | 1 | removed | 79-122 | — |
| `tests/test_pre_settle_transaction.py` | `test_advance_without_edict_refused_after_settling` | 1 | modified | 220-240 | 220-234 |
| `tests/test_pre_settle_transaction.py` | `test_advance_without_edict_refused_at_awaiting` | 1 | modified | 318-352 | 312-340 |
| `tests/test_pre_settle_transaction.py` | `test_due_secret_order_submission_rolls_back_on_pre_settle_crash` | 1 | modified | 86-113 | 86-113 |
| `tests/test_pre_settle_transaction.py` | `test_enter_review_does_not_clobber_settling` | 1 | modified | 199-217 | 199-217 |
| `tests/test_pre_settle_transaction.py` | `test_write_decree_raises_at_awaiting_not_resolveresult` | 1 | modified | 410-425 | 398-413 |
| `tests/test_production_person_key_contract_558.py` | `test_initiative_enrichment_guidance_only_names_canonical_person_writer` | 1 | removed | 12-27 | — |
| `tests/test_promulgation_judge_561.py` | `test_appointment_rejection_check_requires_faction_gate_structure` | 1 | removed | 609-637 | — |
| `tests/test_promulgation_judge_561.py` | `test_appointment_text_is_pure_gatekeeper_transfer_without_land_confiscation` | 1 | removed | 600-606 | — |
| `tests/test_promulgation_judge_561.py` | `test_gate_extracts_actual_cli_judge_payload_and_rejects_ambiguous_capture` | 1 | removed | 178-205 | — |
| `tests/test_promulgation_judge_561.py` | `test_gate_second_verdict_reads_pending_or_applied_history_strictly` | 1 | removed | 453-463 | — |
| `tests/test_promulgation_judge_561.py` | `test_leader_only_mutation_changes_faction_posture_not_roster` | 1 | modified | 668-731 | 565-615 |
| `tests/test_promulgation_judge_561.py` | `test_non_gatekeeper_character_cannot_be_named_as_gatekeeper` | 1 | modified | 887-903 | 771-787 |
| `tests/test_promulgation_judge_561.py` | `test_ordinary_class_all_promulgated_covers_planted_ordinary_only` | 1 | removed | 640-665 | — |
| `tests/test_promulgation_judge_561.py` | `test_ordinary_rejection_cannot_claim_midzhi_unpromulgatable` | 1 | modified | 906-918 | 790-802 |
| `tests/test_promulgation_judge_561.py` | `test_promulgation_verdict_list_shape_has_one_canonical_authority` | 1 | modified | 208-211 | 179-182 |
| `tests/test_promulgation_judge_561.py` | `test_promulgation_verdict_rejects_unknown_fields` | 1 | modified | 215-230 | 186-201 |
| `tests/test_promulgation_judge_561.py` | `test_rejected_exact_keys_accept_only_empty_legal_reason_slot` | 1 | modified | 788-805 | 672-689 |
| `tests/test_promulgation_judge_561.py` | `test_rejected_snapshot_must_equal_the_prepared_judge_input` | 1 | modified | 856-869 | 740-753 |
| `tests/test_promulgation_judge_561.py` | `test_rejected_verdict_still_requires_full_rejection_contract` | 1 | modified | 322-336 | 293-306 |
| `tests/test_promulgation_seam_560.py` | `test_injected_promulgation_batch_cannot_silently_omit_a_dossier` | 1 | modified | 20-27 | 20-27 |
| `tests/test_qa_a3_seed_data.py` | `test_liaodong_stage_text_arrears_months_match_opening_gazette` | 1 | removed | 69-79 | — |
| `tests/test_qa_a3_seed_data.py` | `test_liaodong_stage_text_does_not_name_bajiu_offstage_as_active_petitioners` | 1 | removed | 34-66 | — |
| `tests/test_qa_b3_409_ux.py` | `test_closing_night_rejects_chat_before_any_write` | 1 | added | — | 24-46 |
| `tests/test_qa_b3_409_ux.py` | `test_closing_player_message_is_diegetic_without_bare_night_id` | 1 | removed | 36-55 | — |
| `tests/test_qa_b3_409_ux.py` | `test_favorite_write_rejected_in_front_half_done_phases` | 1 | added | — | 49-73 |
| `tests/test_qa_b3_409_ux.py` | `test_resolve_decisions_stream_phase_precheck_before_lock` | 1 | modified | 195-215 | 165-183 |
| `tests/test_qa_b3_409_ux.py` | `test_serialized_web_write_awaiting_decision_says_waiting_for_rescript` | 1 | removed | 60-72 | — |
| `tests/test_qa_b3_409_ux.py` | `test_serialized_web_write_phase_messages_cover_front_half_done` | 1 | removed | 88-103 | — |
| `tests/test_qa_b3_409_ux.py` | `test_serialized_web_write_settling_keeps_settlement_in_progress_copy` | 1 | removed | 75-85 | — |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_capture_drops_dachen_generic_no_409` | 1 | modified | 21-57 | 22-58 |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_capture_unknown_person_still_409` | 1 | modified | 60-86 | 61-83 |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_default_time_of_day_is_shichen_not_cishi` | 1 | removed | 137-142 | — |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_is_non_person_covers_generics_and_collectives` | 1 | removed | 90-97 | — |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_night_archive_involved_people_drops_non_persons` | 1 | modified | 103-134 | 90-118 |
| `tests/test_qa_d1_decree_normalize_1274.py` | `test_patch_decree_route_removed_and_directives_remain` | 1 | modified | 148-165 | 124-140 |
| `tests/test_qa_e1_numeric_presentation.py` | `test_army_pay_shortfall_reason_has_no_float_garbage` | 1 | removed | 27-45 | — |
| `tests/test_qa_e1_numeric_presentation.py` | `test_army_payload_arrears_text_is_approximate_not_raw` | 1 | removed | 263-283 | — |
| `tests/test_qa_e1_numeric_presentation.py` | `test_army_payload_omits_raw_arrears` | 1 | added | — | 99-112 |
| `tests/test_qa_e1_numeric_presentation.py` | `test_player_budget_payload_strips_engineering_notes` | 1 | modified | 128-167 | 87-96 |
| `tests/test_qa_e1_numeric_presentation.py` | `test_province_pay_split_reason_and_summary_have_no_float_garbage` | 1 | removed | 239-260 | — |
| `tests/test_qa_e1_numeric_presentation.py` | `test_renaming_army_pay_budget_line_does_not_double_debit` | 1 | modified | 94-125 | 56-84 |
| `tests/test_qa_e1_numeric_presentation.py` | `test_substrate_budget_splits_proposals_without_treasury_cap` | 1 | modified | 54-90 | 17-53 |
| `tests/test_qa_h1_seed_data.py` | `test_deficit_stage_text_aligns_with_opening_treasury_and_hubu` | 1 | removed | 176-203 | — |
| `tests/test_qa_h1_seed_data.py` | `test_guanning_commander_not_bajiu_offstage_yuan` | 1 | modified | 50-72 | 33-49 |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | `test_gazette_header_cross_year_december_report_under_january_state` | 1 | removed | 66-82 | — |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | `test_gazette_header_uses_report_own_month_not_current_turn` | 1 | removed | 24-63 | — |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | `test_require_active_minister_uses_can_summon_copy_no_yi_shangwei` | 1 | removed | 132-174 | — |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | `test_state_payload_projects_previous_reign_period_label` | 1 | removed | 85-129 | — |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_dispatch_exception_after_persist_retains_reply_recovery` | 1 | modified | 561-585 | 554-577 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_production_seam_post_barrier_ticket_ordered` | 1 | modified | 373-426 | 367-420 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_resolve_turn_write_gate_held_by_caller_no_reenter` | 1 | modified | 602-645 | 594-637 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_stream_post_reply_exception_preserves_phase_and_recovers_original_turn` | 1 | modified | 527-557 | 521-550 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | `test_ticketed_write_gate_rejects_none` | 1 | modified | 518-522 | 512-516 |
| `tests/test_region_cannon_delta.py` | `test_cannon_has_chinese_display_label` | 1 | removed | 17-19 | — |
| `tests/test_region_citydefense.py` | `test_regions_have_city_level_and_cannon` | 1 | removed | 15-19 | — |
| `tests/test_region_citydefense_display.py` | `test_region_detail_surfaces_city_level_and_cannon` | 1 | removed | 33-55 | — |
| `tests/test_region_citydefense_display.py` | `test_region_report_surfaces_cannon_count` | 1 | removed | 18-30 | — |
| `tests/test_reign_period_label.py` | `test_1627_november_stays_tianqi` | 1 | removed | 21-23 | — |
| `tests/test_reign_period_label.py` | `test_1628_boundary_is_chongzhen_first_year` | 1 | removed | 26-29 | — |
| `tests/test_reign_period_label.py` | `test_1629_plus_uses_chinese_ordinal_not_arabic` | 1 | removed | 32-37 | — |
| `tests/test_reign_period_label.py` | `test_opening_1627_is_tianqi_seventh_year_tenth_month` | 1 | removed | 16-18 | — |
| `tests/test_reign_period_label.py` | `test_pre_tianqi_year_uses_honest_calendar_fallback` | 1 | removed | 12-13 | — |
| `tests/test_relation_brew_636.py` | `test_build_brew_input_projects_prior_event_fields` | 1 | removed | 241-261 | — |
| `tests/test_relation_brew_636.py` | `test_merge_founding_segment_append_only_and_dedup` | 1 | removed | 408-414 | — |
| `tests/test_relation_brew_636.py` | `test_merge_founding_segment_exact_old_entry_re_report_appended_verbatim` | 1 | removed | 433-442 | — |
| `tests/test_relation_brew_636.py` | `test_merge_founding_segment_never_infers_by_lines` | 1 | removed | 445-452 | — |
| `tests/test_relation_brew_636.py` | `test_merge_founding_segment_preserves_bytes_exactly` | 1 | removed | 417-430 | — |
| `tests/test_relation_brew_636.py` | `test_relation_dimension_marks_emperor_edges` | 1 | removed | 577-580 | — |
| `tests/test_relation_capture_633.py` | `test_missing_or_forged_provenance_rejected_with_trace_no_edges` | 1 | modified | 221-250 | 217-250 |
| `tests/test_relation_capture_633.py` | `test_non_string_actor_target_context_shapes_rejected` | 1 | modified | 188-218 | 184-214 |
| `tests/test_relation_capture_633.py` | `test_settlement_edge_origin_rejects_missing_and_non_string` | 1 | removed | 275-288 | — |
| `tests/test_relation_capture_633.py` | `test_shape_garbage_rejected_per_existing_extractor_contract` | 1 | modified | 150-185 | 146-181 |
| `tests/test_relation_capture_633.py` | `test_whitespace_padded_noncanonical_origins_rejected_no_strip_rescue` | 1 | modified | 253-272 | 253-272 |
| `tests/test_relation_read_640.py` | `test_dto_shape_summary_plus_recent_context_with_backref` | 1 | removed | 120-133 | — |
| `tests/test_relation_read_640.py` | `test_judge_face_reads_edges_invisible_to_role_view` | 1 | modified | 161-171 | 116-124 |
| `tests/test_relation_read_640.py` | `test_td7_local_marker_negative_assertion` | 1 | removed | 200-222 | — |
| `tests/test_relation_read_640.py` | `test_updated_at_period_is_era_label_not_bare_turn` | 1 | removed | 136-144 | — |
| `tests/test_relation_seed_638.py` | `test_existing_save_is_never_touched_by_seed_import` | 1 | modified | 428-468 | 364-400 |
| `tests/test_relation_seed_638.py` | `test_fresh_seed_summary_is_readable_with_seed_event_clock` | 1 | removed | 120-132 | — |
| `tests/test_relation_seed_638.py` | `test_invalid_bundled_seed_rolls_back_new_save_and_can_retry` | 1 | modified | 234-257 | 164-198 |
| `tests/test_relation_seed_638.py` | `test_issue_639_seed_owner_audit_corrections` | 1 | modified | 487-612 | 419-526 |
| `tests/test_relation_seed_638.py` | `test_pre_tianqi_seed_event_projects_honest_calendar_label` | 1 | removed | 349-360 | — |
| `tests/test_relation_seed_638.py` | `test_pre_tianqi_seed_event_retains_structured_clock` | 1 | added | — | 286-296 |
| `tests/test_relation_seed_638.py` | `test_pregame_turn_scale_matches_load_state_mapping` | 1 | removed | 166-174 | — |
| `tests/test_relation_seed_638.py` | `test_reverse_chronological_seed_keeps_latest_event_readable` | 1 | modified | 329-346 | 270-283 |
| `tests/test_relation_seed_638.py` | `test_seed_document_validation_is_fail_closed` | 1 | removed | 51-117 | — |
| `tests/test_relation_seed_638.py` | `test_seed_failure_rolls_back_new_save_and_retry_imports` | 1 | modified | 284-312 | 225-253 |
| `tests/test_relation_seed_638.py` | `test_seeded_pair_flows_into_month_end_brew_selection` | 1 | modified | 135-163 | 50-79 |
| `tests/test_relation_store_632.py` | `test_credit_contract_fixture_reads_as_semantic_directed_edges` | 1 | removed | 77-131 | — |
| `tests/test_relation_store_632.py` | `test_edge_event_kind_and_evidence_are_fail_closed` | 1 | modified | 38-74 | 37-73 |
| `tests/test_release_bundle_assets.py` | `test_pyinstaller_spec_does_not_duplicate_vite_public_assets` | 1 | removed | 39-46 | — |
| `tests/test_rescript_choices_563.py` | `test_657_canonical_choice_stable_key_order` | 1 | removed | 199-219 | — |
| `tests/test_rescript_choices_563.py` | `test_657_capability_revalidate_on_follow` | 1 | modified | 389-424 | 367-402 |
| `tests/test_rescript_choices_563.py` | `test_rejected_midzhi_and_force_promulgation_are_idempotent` | 1 | modified | 163-177 | 162-176 |
| `tests/test_rescript_draft_656.py` | `test_1620_generate_army_pay_kind_maps_and_rejects_conflicting_shapes` | 1 | added | — | 1050-1080 |
| `tests/test_rescript_draft_656.py` | `test_1620_generate_army_pay_rejects_bad_typed_shape` | 1 | added | — | 1102-1113 |
| `tests/test_rescript_draft_656.py` | `test_1620_internal_canonical_xiexang_renormalizes_without_kind` | 1 | removed | 1268-1277 | — |
| `tests/test_rescript_draft_656.py` | `test_1620_layer_a_army_pay_rejects_bad_typed_shape` | 1 | removed | 1258-1266 | — |
| `tests/test_rescript_draft_656.py` | `test_1620_layer_a_reward_with_army_target_stays_reward` | 1 | removed | 1219-1237 | — |
| `tests/test_rescript_draft_656.py` | `test_1620_validate_army_pay_grant_kind_maps_to_xiexang` | 1 | removed | 1180-1217 | — |
| `tests/test_rescript_draft_656.py` | `test_657_s1_derive_draft_capability_stable_and_sensitive` | 1 | removed | 1047-1076 | — |
| `tests/test_rescript_draft_656.py` | `test_657_s1_option_shape_stamps_draft_capability` | 1 | removed | 1123-1158 | — |
| `tests/test_rescript_draft_656.py` | `test_657_s1_rescript_emitted_set_subset_of_dossier` | 1 | removed | 1034-1045 | — |
| `tests/test_rescript_draft_656.py` | `test_657_s1_schema_columns_and_no_banned_fields` | 1 | removed | 1015-1032 | — |
| `tests/test_rescript_draft_656.py` | `test_657_validate_rejects_label_hint_only_options` | 1 | modified | 1078-1088 | 985-994 |
| `tests/test_rescript_draft_656.py` | `test_generate_missing_required_field_isolates_failed_item_or_option` | 1 | added | — | 725-736 |
| `tests/test_rescript_draft_656.py` | `test_generate_rescript_draft_degrades_loudly_without_raising` | 1 | modified | 817-831 | 820-832 |
| `tests/test_rescript_draft_656.py` | `test_generate_unknown_item_field_drops_the_item` | 1 | added | — | 799-803 |
| `tests/test_rescript_draft_656.py` | `test_generate_unknown_top_field_requests_repair_before_exhaustion` | 1 | added | — | 944-955 |
| `tests/test_rescript_draft_656.py` | `test_prompt_zero_numeric_instruction_is_positive_qualitative` | 1 | removed | 669-679 | — |
| `tests/test_rescript_draft_656.py` | `test_r3_lone_surrogate_field_rejects_whole_batch` | 1 | modified | 984-1003 | 970-974 |
| `tests/test_rescript_draft_656.py` | `test_r3_strict_parse_concatenated_objects_raises_contract_error` | 1 | removed | 963-969 | — |
| `tests/test_rescript_draft_656.py` | `test_r3_strict_parse_control_char_raises_contract_error` | 1 | removed | 954-961 | — |
| `tests/test_rescript_draft_656.py` | `test_r3_strict_parse_degrades_via_generate` | 1 | modified | 971-982 | 960-968 |
| `tests/test_rescript_draft_656.py` | `test_r3_top_level_unknown_field_rejects_whole_batch` | 1 | removed | 942-952 | — |
| `tests/test_rescript_draft_656.py` | `test_validate_items_accepts_optional_issue_id_binding_key` | 1 | modified | 810-815 | 813-818 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_binds_only_board_issue_ids` | 1 | modified | 685-694 | 691-699 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_empty_list_is_legal_headless_month` | 1 | modified | 779-781 | 785-787 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_empty_options_drops_item_keeps_siblings` | 1 | modified | 752-764 | 758-769 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_many_options_not_gated_or_truncated` | 1 | modified | 741-750 | 747-756 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_missing_required_field_fails_whole_batch` | 1 | removed | 724-730 | — |
| `tests/test_rescript_draft_656.py` | `test_validate_items_no_count_cap_keeps_all_legal` | 1 | modified | 702-712 | 707-713 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_non_list_options_drops_item_keeps_siblings` | 1 | modified | 766-777 | 772-782 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_rejects_illegal_top_level` | 1 | modified | 783-787 | 789-791 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_rejects_unknown_item_field_whole_batch` | 1 | removed | 796-801 | — |
| `tests/test_rescript_draft_656.py` | `test_validate_items_rejects_unknown_option_field_whole_batch` | 1 | modified | 803-808 | 805-811 |
| `tests/test_rescript_draft_656.py` | `test_validate_items_single_option_is_legal` | 1 | modified | 732-739 | 738-745 |
| `tests/test_secret_order_monthly_progress_566.py` | `test_character_terminal_status_closes_secret_orders_through_canonical_progress_rail` | 1 | modified | 155-197 | 154-194 |
| `tests/test_secret_order_monthly_progress_566.py` | `test_missing_bad_unknown_and_duplicate_reports_are_rejected` | 1 | modified | 365-387 | 362-384 |
| `tests/test_secret_order_monthly_progress_566.py` | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | 1 | modified | 278-362 | 275-359 |
| `tests/test_secret_order_payoff_1504.py` | `test_actual_units_share_originated_quantity` | 1 | removed | 237-241 | — |
| `tests/test_secret_order_payoff_1504.py` | `test_confirmation_rejects_incomplete_delivery_identity` | 1 | modified | 229-234 | 177-187 |
| `tests/test_secret_order_payoff_1504.py` | `test_decide_settlement_delivery_gap_bidirectional` | 1 | removed | 169-185 | — |
| `tests/test_secret_order_payoff_1504.py` | `test_seed_guilt_structured_clean_vs_debt` | 1 | removed | 160-166 | — |
| `tests/test_secret_order_payoff_1504.py` | `test_target_units_min_one_when_due` | 1 | removed | 188-191 | — |
| `tests/test_secret_order_payoff_1504.py` | `test_task_specific_contract_from_explicit_fields_not_tags` | 1 | modified | 194-214 | 155-162 |
| `tests/test_secret_order_payoff_1504.py` | `test_zero_target_is_not_delivered` | 1 | modified | 630-635 | 578-582 |
| `tests/test_session_write_queue_1353.py` | `test_get_session_write_queue_wiring_fail_loud_no_broad_swallow` | 1 | modified | 494-529 | 475-494 |
| `tests/test_session_write_queue_1353.py` | `test_no_elapsed_timeout_api_on_barrier` | 1 | removed | 476-491 | — |
| `tests/test_six_sciences_seed_608.py` | `test_fresh_seed_contains_sourced_six_sciences_censors` | 1 | modified | 20-54 | 12-45 |
| `tests/test_six_sciences_seed_608.py` | `test_six_sciences_offices_infer_to_own_category` | 1 | removed | 12-17 | — |
| `tests/test_structured_decree_contract_1624.py` | `test_combo_correction_preserves_first_draw_roster` | 1 | modified | 532-626 | 519-600 |
| `tests/test_structured_decree_contract_1624.py` | `test_generate_option_admission_contract` | 1 | added | — | 487-516 |
| `tests/test_structured_decree_contract_1624.py` | `test_http_manual_directive_lands_beyond_fifteen_initiatives_1790` | 1 | modified | 391-466 | 404-479 |
| `tests/test_structured_decree_contract_1624.py` | `test_manual_owner_example_seal_advances` | 1 | modified | 334-374 | 347-387 |
| `tests/test_structured_decree_contract_1624.py` | `test_normalize_rescript_layer_a_option_contract` | 1 | removed | 469-529 | — |
| `tests/test_structured_decree_contract_1624.py` | `test_shared_validate_rejects_region_id_and_category_holes` | 1 | modified | 129-192 | 128-205 |
| `tests/test_style_temperament_641.py` | `test_apply_score_extraction_rejects_invalid_temperament` | 1 | modified | 244-271 | 241-269 |
| `tests/test_style_temperament_641.py` | `test_apply_score_extraction_writes_temperament_style_and_log` | 1 | modified | 87-120 | 85-117 |
| `tests/test_style_temperament_641.py` | `test_character_context_with_db_reads_own_style_and_viewer_ledger` | 1 | modified | 274-312 | 272-310 |
| `tests/test_style_temperament_641.py` | `test_inertia_natural_resolve_applies_temperament_style` | 1 | modified | 48-84 | 47-82 |
| `tests/test_supervision_625.py` | `test_ac1_presence_exposure_schema_pragma_and_no_dulling_cols` | 1 | removed | 191-219 | — |
| `tests/test_supervision_625.py` | `test_decide_due_review_verdict_unchanged_by_supervision` | 1 | removed | 584-606 | — |
| `tests/test_supervision_625.py` | `test_derive_consecutive_months_and_faction_relation` | 1 | removed | 167-173 | — |
| `tests/test_supervision_625.py` | `test_origin_mark_compose_parse_roundtrip` | 1 | removed | 176-185 | — |
| `tests/test_supervision_625.py` | `test_owner_identity_single_source_shared_with_tenure` | 1 | removed | 522-545 | — |
| `tests/test_supervision_625.py` | `test_unpack_supervision_surface_empty_form_is_constant` | 1 | removed | 548-554 | — |
| `tests/test_surcharge_causal_chain_650.py` | `test_surcharge_schema_only_teaches_effect_eligible_dossiers` | 1 | removed | 85-92 | — |
| `tests/test_textual_facts_1828.py` | `test_sun_chuanting_injury_then_recovery_both_readable_by_month` | 1 | modified | 13-38 | 13-37 |
| `tests/test_textual_facts_1828.py` | `test_textual_facts_survive_reopen` | 1 | modified | 133-162 | 132-160 |
| `tests/test_transaction_boundary.py` | `test_atomic_rejects_plain_connection` | 1 | modified | 488-496 | 488-496 |
| `tests/test_transaction_boundary.py` | `test_connection_commit_attempts_all_runtime_callbacks` | 1 | modified | 351-372 | 351-372 |
| `tests/test_transaction_boundary.py` | `test_executescript_inside_atomic_fails_loud` | 1 | modified | 375-380 | 375-380 |
| `tests/test_transit_countdown_668.py` | `test_removed_symbols_have_no_live_residues` | 1 | removed | 230-248 | — |
| `tests/test_urge_lever_624.py` | `test_deadline_unreasonable_and_dare_speak` | 1 | removed | 213-218 | — |
| `tests/test_urge_lever_624.py` | `test_distortion_modulated_by_integrity_ac2` | 1 | removed | 157-170 | — |
| `tests/test_urge_lever_624.py` | `test_distortion_modulated_by_opportunity_ac4` | 1 | removed | 190-200 | — |
| `tests/test_urge_lever_624.py` | `test_distortion_modulated_by_supervision_consume_only_ac3` | 1 | removed | 173-187 | — |
| `tests/test_urge_lever_624.py` | `test_due_review_whitelist_is_staged_only` | 1 | removed | 571-572 | — |
| `tests/test_urge_lever_624.py` | `test_grace_truth_two_forms_ac6_pure` | 1 | removed | 221-231 | — |
| `tests/test_urge_lever_624.py` | `test_opportunity_band_from_durable_effects` | 1 | removed | 203-210 | — |
| `tests/test_urge_lever_624.py` | `test_payload_json_corrupt_read_is_loud` | 1 | modified | 842-855 | 764-777 |
| `tests/test_urge_lever_624.py` | `test_person_integrity_archetype_three_way` | 1 | removed | 151-154 | — |
| `tests/test_value_matrix_691.py` | `test_target_aware_axis_collisions_route_only_the_target_faction_vitals` | 1 | removed | 24-45 | — |
| `tests/test_value_matrix_691.py` | `test_value_matrix_matches_adr_0011_3` | 1 | removed | 20-21 | — |
| `tests/test_web_chat_serialization_393.py` | `test_nonstream_chat_rejects_when_session_draining` | 1 | modified | 367-387 | 364-382 |
| `tests/test_web_issue_condition_display.py` | `test_humanize_character_location_condition_uses_field_label_and_value_label` | 1 | removed | 87-94 | — |
| `tests/test_web_issue_condition_display.py` | `test_humanize_character_low_loyalty_condition_hides_machine_threshold` | 1 | removed | 97-102 | — |
| `tests/test_web_issue_condition_display.py` | `test_humanize_character_loyalty_condition_hides_machine_threshold` | 1 | removed | 39-44 | — |
| `tests/test_web_issue_condition_display.py` | `test_humanize_character_loyalty_condition_variants` | 1 | removed | 56-61 | — |
| `tests/test_web_issue_condition_display.py` | `test_humanize_character_status_condition_hides_machine_key` | 1 | removed | 76-84 | — |
| `tests/test_web_issue_condition_display.py` | `test_humanize_non_character_condition_keeps_existing_region_translation` | 1 | removed | 64-73 | — |
| `tests/test_web_issue_condition_display.py` | `test_no_token_catches_cjk_adjacent_machine_tokens` | 1 | removed | 27-36 | — |
| `tests/test_web_llm_runtime_config.py` | `test_1271_cli_supports_reasoning_strength_has_no_literal_set` | 1 | removed | 1022-1031 | — |
| `tests/test_web_llm_runtime_config.py` | `test_game_start_rejects_placeholder_api_key` | 1 | added | — | 1219-1228 |
| `tests/test_web_llm_runtime_config.py` | `test_llm_config_from_runtime_api_channel_drops_placeholder_key` | 1 | removed | 1307-1326 | — |
| `tests/test_web_llm_runtime_config.py` | `test_runtime_api_reasoning_strength_builds_llm_config` | 1 | removed | 84-107 | — |
| `tests/test_web_llm_runtime_config.py` | `test_runtime_cli_slot_builds_cli_llm_config_without_backend_env` | 1 | removed | 17-43 | — |
| `tests/test_web_llm_runtime_config.py` | `test_runtime_env_legacy_advanced_thinking_builds_reasoning_strength` | 1 | removed | 110-128 | — |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App must-face wiring（settlement_display 真链）" / "#1620 settling recovery：重开后按持久恢复投影选入口"` | 1 | modified | 1072-1130 | 1055-1113 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App must-face wiring（settlement_display 真链）" / "#1852 写成即推进：本面邸报落位；朕知道了只关阅读；刷新不自动弹"` | 1 | modified | 1132-1235 | 1115-1217 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App must-face wiring（settlement_display 真链）" / "#1852 真实页面：服务端已推进但载入新月失败时邸报可读可关、旧月入口不可提交"` | 1 | modified | 1350-1461 | 1332-1442 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App must-face wiring（settlement_display 真链）" / "settling 恢复：长错误包路径下统一横幅可点；刷新重挂后仍在"` | 1 | removed | 1809-1853 | — |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App readonly zero mid-course leak（逐面审计）" / "#1726 非核账：奏疏模态呈真实奏疏正文，不借局势议题"` | 1 | modified | 2627-2684 | 2547-2604 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App readonly zero mid-course leak（逐面审计）" / "gazette：核账期上月邸报经木牌可读；正文=状态口 previous_summary（#1852 不自动弹）"` | 1 | modified | 2515-2555 | 2442-2479 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App readonly zero mid-course leak（逐面审计）" / "phase=awaiting_decision：核账门控唯一谓词=settlement_display，同样隐藏半程结算三项"` | 1 | modified | 2490-2513 | 2419-2440 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App readonly zero mid-course leak（逐面审计）" / "只读组逐面可达且吃月初叠影；关闭组不可达且半程面不泄漏"` | 1 | modified | 2277-2488 | 2213-2417 |
| `web/src/appDurableWiring.test.tsx` | `"#1236 App readonly zero mid-course leak（逐面审计）" / "月完后 settlement_display=false：关闭组入口恢复；递话条收；局势半程面重现"` | 1 | modified | 2584-2625 | 2508-2545 |
| `web/src/appDurableWiring.test.tsx` | `"App 持久投影 wiring（#499 真实 App 挂载 durable-race tracer）" / "#1716 retry 即时加 pending_directive_count、undo 即时减，拟诏台不待 refresh/reload"` | 1 | modified | 484-646 | 474-636 |
| `web/src/appDurableWiring.test.tsx` | `"App 持久投影 wiring（#499 真实 App 挂载 durable-race tracer）" / "#1853 重试后的记录连续读失败在原轮告知，恢复不重复已成功的 POST"` | 1 | modified | 648-723 | 638-713 |
| `web/src/chatFailures.test.ts` | `"#670 streamChat 成功记召退出错误通道" / "done+end 携带 admission 机面码时不抛错、不走 error 事件"` | 1 | modified | 97-138 | 97-137 |
| `web/src/cliRunners.test.ts` | `"cliRunnerOptions" / "fallback includes grok/cursor/kimi (anchor _CLI_BACKENDS)"` | 1 | removed | 28-34 | — |
| `web/src/cliRunners.test.ts` | `"cliRunnerOptions" / "falls back to anchored constant when backend list missing/empty"` | 1 | removed | 19-26 | — |
| `web/src/cliRunners.test.ts` | `"cliRunnerOptions" / "returns backend list when provided (single source wins)"` | 1 | removed | 5-17 | — |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "#657 midzhi projects non-assignment §C.4 closed-set keys from selected option"` | 1 | modified | 592-656 | 456-518 |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "disables the seal only when no pick and handwritten note is empty; either path enables"` | 1 | modified | 312-342 | 234-260 |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "keeps the three-state invariant for listed picks without sealing the handwritten-only path"` | 1 | modified | 420-471 | 285-335 |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "makes the unique decision-confirm the seal button with no parallel decorative seal"` | 1 | removed | 290-310 | — |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal #1202 seal-is-confirm first screen + pick affordance" / "mechanically distinguishes hover, focus ring, and is-picked styles"` | 1 | removed | 366-418 | — |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal" / "assembles each decision as ordered sections of one red-seal document"` | 1 | removed | 189-208 | — |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal" / "exposes a modal dialog and keeps keyboard focus inside the red-seal page"` | 1 | modified | 84-125 | 49-90 |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal" / "rejects the whole batch when any item is not a valid PendingDecision (reject-whole-batch guard)"` | 1 | modified | 276-286 | 220-230 |
| `web/src/components/decisionModal.test.tsx` | `"DecisionModal" / "uses a non-main full-screen container inside the app landmark"` | 1 | modified | 75-82 | 41-47 |
| `web/src/components/drawers.test.tsx` | `"ArmyDrawer presentation" / "#1501 does not render static army status sentence"` | 1 | removed | 200-231 | — |
| `web/src/components/drawers.test.tsx` | `"ArmyDrawer presentation" / "does not render fractional arrears_text or raw 12.5"` | 1 | removed | 173-198 | — |
| `web/src/components/drawers.test.tsx` | `"ArmyDrawer presentation" / "keeps world facts and never renders situation three-key strings"` | 1 | removed | 141-171 | — |
| `web/src/components/drawers.test.tsx` | `"RegionDrawer #648 population (P7: LLM 长文，无 UI 模板)" / "never renders fixed population strings (约N万口 / 不足一万口)"` | 1 | removed | 235-240 | — |
| `web/src/components/gameMenu.test.tsx` | `"#1732 GameMenu · 就地消解" / "不再提供「重开新局」页签"` | 1 | modified | 739-752 | 721-731 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "clears the legacy thinking_level shadow on save so the unified selector owns reasoning (#358 cmr)"` | 1 | modified | 271-317 | 256-301 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "labels codex off reasoning as the codex low floor"` | 1 | modified | 175-200 | 160-185 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "loads channel=cli from server and shows CLI fields"` | 1 | modified | 163-173 | 151-158 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "offers grok in the CLI runner dropdown and enables reasoning for it (#1271)"` | 1 | modified | 202-238 | 187-223 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "refreshes reasoning support from the save response before trusting the saved backend snapshot"` | 1 | modified | 601-653 | 584-635 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "restores API fields when channel is switched back to api"` | 1 | modified | 135-161 | 126-149 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "shows API fields and hides CLI fields when channel=api (initial render)"` | 1 | modified | 97-110 | 97-105 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "shows CLI fields and hides API fields when channel is switched to cli"` | 1 | modified | 112-133 | 107-124 |
| `web/src/components/gameMenu.test.tsx` | `"LLMConfigTab — channel-gated field rendering" / "trusts backend reasoning_supported over local API model heuristics"` | 1 | modified | 477-494 | 461-477 |
| `web/src/components/map.test.tsx` | `"NodeIntel #1352 garrison layout / army-list口径" / "驻军表兵力全数呈现且月饷带万，表头仅世界事实列"` | 1 | removed | 139-156 | — |
| `web/src/components/map.test.tsx` | `"NodeIntel #648 population (P7: LLM 长文，无 UI 模板)" / "never renders fixed population strings (约N万口 / 不足一万口)"` | 1 | removed | 76-81 | — |
| `web/src/components/map.test.tsx` | `"NodeIntel monthly tax display" / "shows tax_per_turn=1 as 1万/月, not rounded quarterly 0"` | 1 | removed | 85-91 | — |
| `web/src/components/menuPage.test.tsx` | `"#1732 MenuPage · 就地消解" / "有主进度时「开始新游戏」展开就地卡；取消零请求；确认后 POST new_game"` | 1 | modified | 981-1027 | 975-1020 |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "disables reasoning strength for unsupported CLI runners ($runner)"` | 1 | added | — | 291-357 |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "disables reasoning strength for unsupported CLI runners"` | 1 | removed | 307-361 | — |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "does not expose or save a separate advanced thinking selector"` | 1 | modified | 492-565 | 488-560 |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "labels codex off reasoning as the codex low floor"` | 1 | modified | 363-420 | 359-416 |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "offers grok in the CLI runner dropdown and enables reasoning for it (#1271)"` | 1 | modified | 422-490 | 418-486 |
| `web/src/components/menuPage.test.tsx` | `"ApiSettingsModal reasoning strength" / "trusts backend reasoning_supported over local API model heuristics"` | 1 | modified | 861-915 | 856-909 |
| `web/src/components/menuPage.test.tsx` | `"MenuPage continue SSE stages (#1195)" / "replaces busy label when stage events arrive mid-stream"` | 1 | modified | 188-244 | 188-244 |
| `web/src/components/menuPage.test.tsx` | `"MenuPage continue SSE stages (#1195)" / "shows initial 载入上次进度 label immediately on click before first chunk"` | 1 | modified | 246-286 | 246-287 |
| `web/src/components/menuPage.test.tsx` | `"MenuPage subtitle" / "does not show incorrect era year 崇祯元年 in subtitle"` | 1 | removed | 290-303 | — |
| `web/src/components/modals.test.tsx` | `"#1480 / #1499 FullscreenModal modal-layout-bare 只随 hideTitle" / "hideTitle 挂 modal-layout-bare；起居注有可见标题栏不挂"` | 1 | modified | 1312-1347 | 1272-1306 |
| `web/src/components/modals.test.tsx` | `"AudienceArchiveModal — read-only scene archive" / "#671 attendant-only 月档列表标签为递话、不冒充奏报"` | 1 | modified | 1637-1680 | 1625-1660 |
| `web/src/components/modals.test.tsx` | `"AudienceArchiveModal — read-only scene archive" / "selects closed scenes through the shared scroll endpoint without a composer"` | 1 | modified | 1469-1506 | 1428-1495 |
| `web/src/components/modals.test.tsx` | `"AudienceArchiveModal — read-only scene archive" / "史册 filters out scene rows and keeps the public-document boundary"` | 1 | modified | 1508-1520 | 1497-1508 |
| `web/src/components/modals.test.tsx` | `"ChatModal — #1370 empty audience chrome" / "空对话区呈等候/引导 chrome，带稳定 chat-stage 标记，不代笔开场白"` | 1 | modified | 441-457 | 429-443 |
| `web/src/components/modals.test.tsx` | `"ChatModal — #545 final composer contract" / "#1278 召对收夜钮称散夜，仍走 chat 口令「退朝」seam，不与拟诏台退朝撞名"` | 1 | modified | 461-482 | 447-464 |
| `web/src/components/modals.test.tsx` | `"ChatModal — cancel button during busy (issue #353)" / "shows an observer-exit button when busy and onCancel is provided"` | 1 | modified | 1695-1705 | 1664-1673 |
| `web/src/components/modals.test.tsx` | `"ChatModal — elapsed timer during thinking (issue #353)" / "shows elapsed time in the thinking indicator while busy"` | 1 | removed | 1743-1755 | — |
| `web/src/components/modals.test.tsx` | `"ChatModal — one-night audience scroll (#1849)" / "names an empty-scaffold night without relying on projected messages"` | 1 | modified | 982-990 | 941-950 |
| `web/src/components/modals.test.tsx` | `"ChatModal — one-night audience scroll (#1849)" / "names the live scroll from its persisted container"` | 1 | modified | 971-980 | 929-939 |
| `web/src/components/modals.test.tsx` | `"ChatModal — placeholder switches on character type" / "consort placeholder has meaningful length"` | 1 | removed | 523-527 | — |
| `web/src/components/modals.test.tsx` | `"ChatModal — placeholder switches on character type" / "does NOT show 大臣 or 他 in placeholder for consorts"` | 1 | removed | 516-521 | — |
| `web/src/components/modals.test.tsx` | `"ChatModal — placeholder switches on character type" / "shows #505 system-layer reply retry control when replyRetry is set"` | 1 | removed | 529-553 | — |
| `web/src/components/modals.test.tsx` | `"ChatModal — placeholder switches on character type" / "shows audience commands in placeholder for ministers"` | 1 | removed | 509-514 | — |
| `web/src/components/modals.test.tsx` | `"ChatModal — reply recovery controls" / "shows #505 system-layer reply retry control when replyRetry is set"` | 1 | added | — | 491-513 |
| `web/src/components/modals.test.tsx` | `"ChatModal — single night-scroll authority (#539)" / "does not flash old minister chat while the night scroll is loading or failed"` | 1 | modified | 750-763 | 708-721 |
| `web/src/components/modals.test.tsx` | `"ChatModal — single night-scroll authority (#539)" / "does not merge personal history while the canonical scroll refresh is delayed"` | 1 | modified | 814-856 | 772-815 |
| `web/src/components/modals.test.tsx` | `"ChatModal — single night-scroll authority (#539)" / "keeps the last-known scroll without importing personal history when refresh fails"` | 1 | modified | 860-890 | 818-848 |
| `web/src/components/modals.test.tsx` | `"ChatModal — soft scenes and selected-minister lens (#543 / #1511)" / "keeps a side interjection in the selected minister segment without window bleed"` | 1 | modified | 618-671 | 578-629 |
| `web/src/components/modals.test.tsx` | `"ChatModal — thinking/loading text switches on character type (gemini cmr r1)" / "shows 大臣思索中 while a minister is thinking"` | 1 | removed | 1687-1690 | — |
| `web/src/components/modals.test.tsx` | `"EdictModal — #1431 placeholder 去失实具名" / "御笔 placeholder 不含毕自严等现任错位具名"` | 1 | removed | 288-296 | — |
| `web/src/components/modals.test.tsx` | `"ReportModal — narrative settlement bulletin" / "#1356 报头吃报文自身月 periodLabel，不吃当前 turn 月"` | 1 | modified | 1786-1805 | 1736-1751 |
| `web/src/components/modals.test.tsx` | `"ReportModal — narrative settlement bulletin" / "#1356 空邸报态不崩：卷轴壳复用 pre + 朕知道了可关闭（无固定空注）"` | 1 | modified | 1807-1822 | 1753-1766 |
| `web/src/components/modals.test.tsx` | `"ReportModal — narrative settlement bulletin" / "renders narrative without an account page"` | 1 | modified | 1759-1768 | 1711-1718 |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 GameHud face gates eat settlement_display" / "#1323 awaiting_decision：递话/角标文案为有本待批；锁面机制仍关"` | 1 | modified | 206-236 | 194-223 |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 GameHud face gates eat settlement_display" / "关闭组点击触发戏内理由回调"` | 1 | modified | 178-204 | 165-192 |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 GameHud face gates eat settlement_display" / "核账期：王承恩递话条出现；关闭组导航 aria-disabled；密令角标清零；半程局势藏、上月已结只读可达"` | 1 | modified | 88-145 | 83-132 |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 GameHud face gates eat settlement_display" / "非核账：递话条隐藏；关闭组恢复可达；角标恢复"` | 1 | modified | 147-176 | 134-163 |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 roster chat entry stripped in settlement_display" / "#1323 awaiting：MinisterCardList title 吃 settlementClosedReason(phase)"` | 1 | removed | 268-291 | — |
| `web/src/components/settlementFaces.test.tsx` | `"#1236 roster chat entry stripped in settlement_display" / "MinisterCardList disables onOpenChat when chatEntryEnabled=false"` | 1 | modified | 240-266 | 227-253 |
| `web/src/components/settlementFaces.test.tsx` | `"QA A-1 #1276/#1282/#1285 GameHud HUD 对齐" / "#1276 邸报木牌 caption/动作对齐 gazette，不再挂起居注"` | 1 | modified | 368-384 | 331-339 |
| `web/src/components/settlementFaces.test.tsx` | `"QA A-1 #1276/#1282/#1285 GameHud HUD 对齐" / "#1282 owner 先隐：礼木牌不渲染；政仍走朝堂；礼部槽位资源保留待立项"` | 1 | modified | 386-397 | 341-349 |
| `web/src/components/settlementFaces.test.tsx` | `"QA A-1 #1276/#1282/#1285 GameHud HUD 对齐" / "#1726 奏疏 badge/副文接未读奏报数；与局势 issues 脱钩；木牌打开 state 槽"` | 1 | modified | 399-418 | 351-369 |
| `web/src/components/situation.test.tsx` | `"#1726 StateModal 奏疏收件箱" / "呈真实奏疏正文与上疏人；不借局势 issues；不渲染结构化字段"` | 1 | modified | 204-232 | 151-178 |
| `web/src/components/situation.test.tsx` | `"#1726 StateModal 奏疏收件箱" / "无奏疏时示空态，不因有局势而填充"` | 1 | removed | 234-239 | — |
| `web/src/components/situation.test.tsx` | `"commitment progress display" / "does not show fallback progress for ordinary issues"` | 1 | removed | 82-87 | — |
| `web/src/components/situation.test.tsx` | `"commitment progress display" / "shows commitment progress in the situation hover tooltip"` | 1 | modified | 97-121 | 84-108 |
| `web/src/components/situation.test.tsx` | `"commitment progress display" / "uses a styled fallback when a commitment has progress but no text"` | 1 | removed | 75-80 | — |
| `web/src/components/situation.test.tsx` | `"empty bar label presentation (#626)" / "detail modal keeps parentheses when bar meanings are present"` | 1 | removed | 146-154 | — |
| `web/src/components/situation.test.tsx` | `"empty bar label presentation (#626)" / "detail modal omits empty parentheses when bar meanings are blank"` | 1 | removed | 134-144 | — |
| `web/src/components/situation.test.tsx` | `"empty bar label presentation (#626)" / "issue board progress ends stay blank rather than showing empty labels"` | 1 | removed | 156-162 | — |
| `web/src/decisionRouting.test.tsx` | `"decision routing — retry (routeRetryDecisions: stale-phase vs still-corrupted)" / "#1307 settling retry keeps quiet intermediate — empty pending is not 重新拉取 error"` | 1 | modified | 138-143 | 131-136 |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "empty-speaker scene still binds the soft stretch to the turn principal"` | 1 | removed | 148-158 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "具名 divider 段内后续他臣正式 turn：前臣窗移除、后臣窗完整、无 turn 殿侧插话仍随软段"` | 1 | removed | 167-203 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "切回有记录大臣：该臣语义轮完整（朕问/回话/递话/scene 同进）"` | 1 | removed | 54-63 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "半轮 claim：无 minister 气泡的 user 问话按 claimedTurnId 留在本窗"` | 1 | removed | 205-220 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "同一归档轮有两名正式发言人时，两人都能回看整轮"` | 1 | removed | 111-119 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "场景/divider 软段 + 殿侧他臣插话：不串窗且不误删本段上下文"` | 1 | removed | 121-146 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "归属反例：本臣轮内非本臣 speaker 保留；他臣轮不泄漏；无主不泛留"` | 1 | removed | 65-93 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "无锚轮按 chat_turn_id 绑定具名 minister，整轮同进同退"` | 1 | removed | 95-109 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "未转译的无主轮保留为中性记录，不将他臣具名轮归给当前臣"` | 1 | removed | 233-244 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "现行单场景轮按参与臣过滤时保留殿上正式对话"` | 1 | removed | 222-231 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "许誉卿场景：无记录大臣空白开场，不见他臣密令整卷"` | 1 | removed | 45-52 | — |
| `web/src/ministerScrollLens.test.ts` | `"filterScrollForSelectedMinister (#1511 lens)" / "镜头键是 selected minister 参数，不从卷轴推导 currentMinister"` | 1 | removed | 160-165 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "does not hardcode codex/claude when the capability list is empty (#1271)"` | 1 | removed | 68-80 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "falls back to API heuristics when the backend snapshot is stale"` | 1 | removed | 22-28 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "falls back to CLI runner support when the backend snapshot is stale"` | 1 | removed | 40-52 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "falls back to true for grok when the capability list includes grok (#1271)"` | 1 | removed | 54-66 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "trims edited API fields before applying fallback heuristics"` | 1 | removed | 30-38 | — |
| `web/src/reasoningSupport.test.ts` | `"resolveReasoningSupported" / "uses backend reasoning_supported while the backend snapshot is current"` | 1 | removed | 14-20 | — |
| `web/src/settlementPresentation.test.ts` | `"#1236 T3 settlement face gates (唯一谓词 settlement_display)" / "isSettlementDisplay reads only the server flag"` | 1 | removed | 85-90 | — |
| `web/src/settlementPresentation.test.ts` | `"#1236 T3 settlement face gates (唯一谓词 settlement_display)" / "mechanical roster covers every face key exactly once"` | 1 | removed | 76-83 | — |
| `web/src/settlementPresentation.test.ts` | `"#1236 T3 settlement face gates (唯一谓词 settlement_display)" / "一开一关矩阵：非核账 open（excluded 除外）；核账返回组归属"` | 1 | removed | 92-112 | — |
| `web/src/settlementPresentation.test.ts` | `"settlement presentation routing" / "#1234 year-month label is driven only by server settlement_display"` | 1 | removed | 33-37 | — |
| `web/src/settlementPresentation.test.ts` | `"settlement presentation routing" / "#1323 awaiting_decision 文案层：年月标 ·待批；递话/关闭理由分口吻"` | 1 | removed | 39-60 | — |
| `web/src/settlementPresentation.test.ts` | `"settlement presentation routing" / "auto-opens only for a report produced by the just-settled month"` | 1 | removed | 22-27 | — |
| `web/src/settlementPresentation.test.ts` | `"settlement presentation routing" / "does not auto-open closed issue progress after settlement"` | 1 | removed | 29-31 | — |
| `web/src/styles.test.ts` | `"#1342 朝堂抽屉不得挡底栏命令" / "drawer-scrim / court-drawer 底部留出命令安全区"` | 1 | removed | 24-32 | — |
| `web/src/styles.test.ts` | `"#1352 地图驻军表头不拆字" / "garrison intel 表头 nowrap / keep-all"` | 1 | removed | 56-58 | — |
| `web/src/styles.test.ts` | `"#1387 邸报可滚完" / "gazette-document 在 modal 内 min-height:0 + overflow-y auto"` | 1 | removed | 62-66 | — |
| `web/src/styles.test.ts` | `"#1398 邸报朕知道了视口常显" / "gazette-shell 分栏：document 可滚、dismiss 不随文滚走"` | 1 | removed | 70-76 | — |
| `web/src/styles.test.ts` | `"#1454 拟诏台不得挡底栏拟诏木牌" / "#1458 安全区跟随 hud2-stage 实际底边，方/竖视口不盖收起木牌"` | 1 | removed | 44-52 | — |
| `web/src/styles.test.ts` | `"#1454 拟诏台不得挡底栏拟诏木牌" / "edict-safe-cmd 层底部留出命令安全区（修 desk-footer 遮挡）"` | 1 | removed | 36-42 | — |
| `web/src/styles.test.ts` | `"#1475 召对顶栏回收版面" / "chat 大横幅轨不压过 modal-header-bare（hideTitle 时高度归零）"` | 1 | removed | 96-106 | — |
| `web/src/styles.test.ts` | `"#1480 / #1499 hideTitle 单行 1fr 不误伤有标题栏 modal-bg-chat" / "单行 minmax(0,1fr) 只挂 .modal-layout-bare；裸 modal-bg-chat.fullscreen-modal 不得单行"` | 1 | removed | 110-126 | — |
| `web/src/styles.test.ts` | `"#1480 / #1499 hideTitle 单行 1fr 不误伤有标题栏 modal-bg-chat" / "基础 .fullscreen-modal 正向钉两行网格 auto + minmax(0,1fr)"` | 1 | removed | 128-140 | — |
| `web/src/styles.test.ts` | `"#1486 邸报底栏不与卷轴末行混层" / "modal-bg-gazette 下 dismiss 有实底，压过 * transparent"` | 1 | removed | 80-92 | — |
| `web/src/styles.test.ts` | `"窄屏召见布局" / "保留两列并让左栏滚动，避免密令被立绘裁掉"` | 1 | removed | 11-20 | — |
| `web/src/useSettlementFlow.test.tsx` | `"#1234 useSettlementFlow — 同会话 awaiting 停窗消费状态口" / "decisions 分支 await loadState：·待批出现（#1323）+ 四键为月初值，且不 reload"` | 1 | modified | 551-591 | 548-586 |
| `web/src/useSettlementFlow.test.tsx` | `"#1433 useSettlementFlow — 退朝 awaiting 消费面（禁盲 reload hop）" / "advance 回 awaiting_decision 时消费 decisions + loadState，不 reload"` | 1 | modified | 437-485 | 435-482 |
