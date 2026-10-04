# J6 wide disposition batch2 (middle-third py slice)

Source: `j6-structural-candidates.jsonl`, `kind=py`, alphabetical middle third (70 files). Skipped **73** rows in `j6-wide-disposition-prio.jsonl`.
Actions seeded from `j6-wide-candidate-disposition.jsonl` + semantic overrides (candidate-disposition, class-members, private-helper, expanded assert-calls); retain rows enriched from segment + `j6-candidate-analysis.jsonl` where needed.
**Total:** 793

## Counts by action

- **delete**: 0
- **migrate**: 76
- **retain**: 717

## delete


## migrate

- `tests/test_executor_routing_721.py::test_directive_routing_rejection_rolls_back_with_outer_owner`
- `tests/test_executor_routing_721.py::test_rolled_back_collector_reuse_does_not_mirror_orphan`
- `tests/test_faction_brew_637.py::test_faction_apply_db_error_propagates_loudly_not_disguised`
- `tests/test_faction_brew_637.py::test_faction_claim_db_error_propagates_loudly`
- `tests/test_faction_leverage_9.py::test_whitelist_faction_delta_survives_full_settlement`
- `tests/test_fiscal_substrate_bridge.py::test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic`
- `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_failure_rolls_back_cutover_writes`
- `tests/test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances`
- `tests/test_gazette_author_1862.py::test_author_waits_until_rescript_is_done`
- `tests/test_grant_reconciliation_567.py::test_settle_entry_lands_engine_arrival_per_route`
- `tests/test_grant_reconciliation_567.py::test_web_state_payload_after_settle`
- `tests/test_history_decree_text_1843_reopen.py::test_history_turn_reads_decree_text_from_resolve_context`
- `tests/test_issue_decree_token_1277.py::test_double_issue_same_token_second_is_409_turn_plus_one`
- `tests/test_material_directory_1830.py::test_read_material_stays_inside_directory`
- `tests/test_material_directory_1830.py::test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error`
- `tests/test_mechanical_tail_1845.py::test_advance_schedules_mechanical_tail_after_front_month_advance`
- `tests/test_mechanical_tail_1845.py::test_reopen_resumes_incomplete_mechanical_tail`
- `tests/test_memorial_inbox_1726.py::test_state_payload_memorials_and_mark_read_api`
- `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_skips_move_when_session_close_fails`
- `tests/test_menu_lifecycle_drain_396.py::test_drain_rejects_late_pending_write_before_gate_acquire`
- `tests/test_menu_lifecycle_drain_396.py::test_get_main_db_path_prefers_active_db_over_launch_env`
- `tests/test_menu_lifecycle_drain_396.py::test_restore_main_db_path_config_remove_failure_is_loud`
- `tests/test_month_call_recovery_1846.py::test_escape_hatch_discards_world_segment_only_on_second_player_retry`
- `tests/test_month_call_recovery_1846.py::test_world_translate_exhaustion_keeps_text_resume_retries_translate_only`
- `tests/test_month_chain_1843.py::test_advance_reloads_memory_after_transaction_rollback`
- `tests/test_month_chain_1843.py::test_advance_uses_staged_declaration_ending`
- `tests/test_month_chain_1843.py::test_failed_declaration_commit_reloads_memory_from_db`
- `tests/test_month_chain_1843.py::test_held_dossier_settlement_failure_retry_and_reentry_isolation`
- `tests/test_month_chain_1843.py::test_missing_world_model_stops_before_world_commit`
- `tests/test_month_chain_1843.py::test_month_chain_lands_specialized_facts_before_due_and_gazette`
- `tests/test_month_chain_1843.py::test_month_drift_settles_due_secret_and_records_inertia_rejection`
- `tests/test_month_chain_1843.py::test_player_entry_recovers_ending_after_interrupted_segment`
- `tests/test_month_chain_1843.py::test_player_month_entry_settles_prepushed_edicts_then_world_once`
- `tests/test_month_chain_1843.py::test_player_recovery_uses_resolve_context_decree_not_ready_delta`
- `tests/test_month_chain_1843.py::test_questions_hold_rescript_and_gazette_is_required_before_advance`
- `tests/test_month_chain_1843.py::test_staged_ending_is_available_inside_its_settlement_transaction`
- `tests/test_month_chain_1847.py::test_answering_triad_applies_and_releases_rescript_gate`
- `tests/test_month_chain_1847.py::test_cross_month_pending_draft_opens_rescript_desk`
- `tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect`
- `tests/test_month_chain_1847.py::test_decree_question_continuation_idempotent_on_same_turn_reentry`
- `tests/test_month_chain_1847.py::test_pending_disclosures_share_commit_boundary_with_effects`
- `tests/test_month_chain_1847.py::test_prior_month_answered_rescript_does_not_block_or_reappear`
- `tests/test_month_chain_1847.py::test_settle_edicts_persists_pending_disclosures_in_same_transaction`
- `tests/test_month_chain_1847.py::test_step_4a_deferred_disclosure_sees_fresh_0058_progress`
- `tests/test_month_chain_1847.py::test_step_4a_missing_covert_fidelity_records_inline_rejection`
- `tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input`
- `tests/test_month_chain_1847.py::test_step_4a_rescript_path_feeds_landed_not_assembled_effects`
- `tests/test_month_chain_1847.py::test_step_4a_settles_due_secret_order`
- `tests/test_month_open_snapshot_1234.py::test_capture_before_mutation_on_advance_without_edict`
- `tests/test_month_open_snapshot_1234.py::test_capture_before_mutation_on_resolve_turn_entry`
- `tests/test_month_open_snapshot_1234.py::test_oracle_normal_phase_clears_via_startup_hook`
- `tests/test_month_open_snapshot_1234.py::test_player_month_advance_expires_snapshot`
- `tests/test_new_game_write_path_1749.py::test_gamesession_load_state_failure_closes_partial_resources`
- `tests/test_new_game_write_path_1749.py::test_new_game_construct_failure_keeps_old_writable`
- `tests/test_new_issues_section_rejections.py::test_event_to_issue_insert_exception_propagates`
- `tests/test_new_issues_section_rejections.py::test_new_issue_event_pool_insert_exception_propagates`
- `tests/test_new_issues_section_rejections.py::test_new_issue_insert_code_exception_propagates`
- `tests/test_no_edict_full_settlement_1274.py::test_no_edict_advance_runs_full_settlement_chain`
- `tests/test_no_edict_full_settlement_1274.py::test_no_edict_zero_decisions_completes_without_stuck`
- `tests/test_no_edict_full_settlement_1274.py::test_web_no_edict_endpoint_routes_to_full_settlement`
- `tests/test_opening_gazette_delete_1356.py::test_old_save_exact_purge_keeps_real_with_phrase_counterexample`
- `tests/test_override_breach_costs_564.py::test_commit_false_breach_rolls_back_with_later_cancellation_failure`
- `tests/test_override_breach_costs_564.py::test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation`
- `tests/test_pihong_dossier_1490.py::test_1620_http_follow_draft_grant_uses_stored_amount`
- `tests/test_pihong_dossier_1490.py::test_1620_http_follow_draft_office_token_routes_to_person`
- `tests/test_pihong_dossier_1490.py::test_1625_inflight_phase2_does_not_advertise_resume`
- `tests/test_pihong_dossier_1490.py::test_657_record_event_choice_failure_rolls_back_batch`
- `tests/test_pihong_dossier_1490.py::test_658_free_decree_capture_target_dossier_real_entry`
- `tests/test_pihong_dossier_1490.py::test_658_routing_rejected_draft_retries_across_real_turn_boundaries`
- `tests/test_pihong_dossier_1490.py::test_due_commitment_shaped_submit_does_not_poison_or_deadlock`
- `tests/test_pihong_dossier_1490.py::test_lying_label_rebuilt_from_server_option`
- `tests/test_pihong_dossier_1490.py::test_ordinary_event_with_hallucinated_capability_submits`
- `tests/test_player_army_projection_321.py::test_army_state_and_map_payloads_project_situation`
- `tests/test_player_payload_1022.py::test_issue_terminals_keep_unadvanced_month_visible`
- `tests/test_player_payload_1022.py::test_settlement_sse_routes_serialize_only_player_narrative`
- `tests/test_power_section_rejections.py::test_canonical_person_power_writer_code_exception_is_fail_loud`
