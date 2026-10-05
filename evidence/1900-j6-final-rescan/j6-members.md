# J6 全成员语义处置表

成员总数 101（含已删样本登记）；disposition 计数：`{'KEEP_SINGLE_FAULT_OR_CONTROL': 18, 'KEEP_EXTERNAL_ENUM_OR_CONTENT': 11, 'KEEP_EXTERNAL_OR_CONTROL': 53, 'FIX_DONE': 6, 'KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL': 6, 'KEEP_STRUCTURED_PRIMARY': 6, 'DELETE_HELPER_PSEUDO': 1}`

官方能力：pytest ExceptionInfo / `excinfo.value` 对象身份；[docs.pytest.org assert exceptions](https://docs.pytest.org/en/stable/how-to/assert.html#assertions-about-expected-exceptions)；Python exception chaining。

## 本轮施工

| 成员 | disposition | 依据 |
|---|---|---|
| `tests/test_chat_stream_failpaths_393.py::test_worker_postprocess_exception_emits_error_end` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_cli_backend.py::test_run_backend_for_config_traces_on_backend_error` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_mechanical_tail_1845.py::test_mechanical_tail_missing_llm_config_surfaces_retry` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_relation_seed_638.py::test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | **DELETE_HELPER_PSEUDO** | FakeDB/FailingConnection helper-only；非闸类拒收负向；无真实入口外部结果。本轮删除。 |
| `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` | **FIX_DONE** | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |

## 全表

| file | test | disposition | why |
|---|---|---|---|
| `tests/test_affairs_1831.py` | `test_conflicting_affair_declaration_on_existing_dossier_fails_loud` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_audience_night_498.py` | `test_open_summon_close_chain_readable_by_night` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_audience_night_498.py` | `test_dead_person_enter_rejected_with_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_audience_restore_505.py` | `test_post_reply_failure_resumes_close_without_regenerating_reply` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_audience_restore_505.py` | `test_failed_retry_rolls_back_side_effects_and_keeps_question` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_audience_translate_1837.py` | `test_pending_round_approval_endorsed_before_close_or_after_month_join` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_audience_translation_1838.py` | `test_three_speaker_segments_private_whisper_reaches_only_participant` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_character_knowledge_489.py` | `test_archive_write_materializes_unmirrored_source_scope` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_character_knowledge_489.py` | `test_turn_report_counterpart_never_uses_aggregate_when_sources_exist` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_chat_stream_failpaths_393.py` | `test_prologue_failure_fails_orphan_turn_and_releases_gate` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_chat_stream_failpaths_393.py` | `test_prologue_finally_does_not_release_foreign_gate_holder` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_chat_stream_failpaths_393.py` | `test_prologue_cleanup_failure_still_releases_gate_and_counter` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_chat_stream_failpaths_393.py` | `test_worker_postprocess_exception_emits_error_end` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_cli_backend.py` | `test_run_runner_accepts_config_model` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_cli_backend.py` | `test_run_backend_for_config_traces_on_backend_error` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_cli_backend.py` | `test_material_runner_uses_cwd_and_read_only_tool_surface` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_cli_play_turn.py` | `test_cli_does_not_end_unadvanced_turn` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_decree_dossiers_571.py` | `test_dossier_roster_write_boundary_rejects_invalid_delegator` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_decree_dossiers_571.py` | `test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_decree_dossiers_571.py` | `test_immediate_terminal_payload_cannot_bypass_execution_surface` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_dossier_reported_progress_619.py` | `test_origin_namespace_minimum_closed_set_and_open_append` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_dossier_reported_progress_619.py` | `test_terminal_surface_dossier_rejects_reported_progress` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_enter_settlement_period_1235.py` | `test_session_reaccept_orphan_exits_after_owner_release` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_error_pack.py` | `test_write_error_pack_inside_atomic_is_rejected` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_error_pack.py` | `test_web_issue_endpoint_returns_structured_abort` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_event_chain_cascade.py` | `test_cascade_rolls_back_owned_transaction_on_later_write_failure` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_event_trigger_gate.py` | `test_apply_score_extraction_appointment_rolls_back_with_outer_transaction` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_execution_pressure_654.py` | `test_revoke_decree_523_producer_durable_oracle_chain` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_executor_routing_721.py` | `test_rolled_back_collector_reuse_does_not_mirror_orphan` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_executor_routing_721.py` | `test_directive_routing_rejection_rolls_back_with_outer_owner` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_pay_source_errors_abort_fixed_flows` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_gazette_author_1862.py` | `test_author_archives_own_title_and_same_run_advances` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_gazette_author_1862.py` | `test_gazette_failure_retries_report_only` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_issue_decree_token_1277.py` | `test_double_issue_same_token_second_is_409_turn_plus_one` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_llm_channel_config.py` | `test_verify_llm_available_api_empty_content_passes` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_llm_channel_config.py` | `test_verify_llm_available_api_empty_content_none_passes` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_mechanical_tail_1845.py` | `test_exhausted_mechanical_tail_fails_and_blocks_next_month` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_mechanical_tail_1845.py` | `test_real_brew_failure_reaches_tail_failure_and_retry` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_mechanical_tail_1845.py` | `test_non_exhausted_tail_failure_stays_pending_and_retries` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_mechanical_tail_1845.py` | `test_mechanical_tail_missing_llm_config_surfaces_retry` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_month_call_recovery_1846.py` | `test_month_entry_world_push_follows_audience_transport_policy` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_forecast_exhaustion_does_not_overwrite_prior_ending` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_world_text_exhaustion_stops_month_keeps_settled_edicts` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_escape_hatch_discards_world_segment_only_on_second_player_retry` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_settlement_recovery_projects_month_call_failure` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_month_call_recovery_1846.py` | `test_code_exception_during_world_commit_keeps_phase_and_settled_edicts` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_world_commit_failure_after_alongside_retries_uncommitted_segment` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_edict_settle_code_exception_stops_at_month_entry_and_retries_once` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_call_recovery_1846.py` | `test_error_pack_failure_keeps_original_fault_and_retry_phase` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_month_chain_1843.py` | `test_player_entry_recovers_ending_after_interrupted_segment` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_chain_1843.py` | `test_failed_declaration_commit_reloads_memory_from_db` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_month_chain_1847.py` | `test_step_4a_missing_covert_fidelity_records_inline_rejection` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_month_chain_1847.py` | `test_settle_edicts_persists_pending_disclosures_in_same_transaction` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_month_chain_1847.py` | `test_pending_disclosures_share_commit_boundary_with_effects` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_new_game_dependency_mismatch_1721.py` | `test_new_game_stale_agno_returns_typed_dependency_facts` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_new_game_dependency_mismatch_1721.py` | `test_continue_stale_agno_sse_carries_typed_dependency_facts` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_new_game_write_path_1749.py` | `test_new_game_write_path_direct_and_via_exit` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_office_inference.py` | `test_fresh_gamesession_start_makes_no_backend_calls` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_override_breach_costs_564.py` | `test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_override_breach_costs_564.py` | `test_commit_false_breach_rolls_back_with_later_cancellation_failure` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_pihong_dossier_1490.py` | `test_657_abi_mapper_matrix_a1_a12` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_pihong_dossier_1490.py` | `test_657_punishment_name_target_id_conflict_zero_writes` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_qa_b3_409_ux.py` | `test_load_save_409_during_resolve_body_keeps_old_session_tail` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_refugee_loop_652.py` | `test_outer_atomic_rolls_back_surcharge_and_absorption` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_rejection_wiring.py` | `test_rollback_leaves_no_rows_and_no_jsonl` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_rejection_wiring.py` | `test_nested_atomic_success_path_does_not_orphan_jsonl` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_relation_seed_638.py` | `test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` | `DELETE_HELPER_PSEUDO` | FakeDB/FailingConnection helper-only；非闸类拒收负向；无真实入口外部结果。本轮删除。 |
| `tests/test_rescript_option_field_heal_1746.py` | `test_heal_response_contract_failure_consumes_attempt_keeps_siblings` | `KEEP_STRUCTURED_PRIMARY` | 主契约为结构化 code/status/turn/落账或已含注入原文 membership；message 非空仅为辅，不机械加身份。 |
| `tests/test_secret_order_isolation_883.py` | `test_883_shared_archive_bypass_positive_and_negative` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_secret_order_monthly_progress_566.py` | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_settlement_write_guard_393.py` | `test_direct_db_write_refused_when_gate_held` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_state_reload.py` | `test_pre_settle_self_reloads_memory_on_rollback` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_state_reload.py` | `test_rollback_purges_content_character_ghost` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_state_reload.py` | `test_reload_skipped_inside_nested_atomic` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_state_reload.py` | `test_rollback_restores_existing_character_attributes` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_state_reload.py` | `test_atomic_and_reload_reloads_and_reraises_at_depth0` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_state_reload.py` | `test_atomic_and_reload_skips_reload_when_nested` | `KEEP_EXTERNAL_CONTROL_OR_ZERO_CALL` | 调用记录本身即外部契约（零 LLM／嵌套不 reload／CLI 回合序／空 content 连通不抛）；非替身替代被测行为。 |
| `tests/test_state_reload.py` | `test_atomic_and_reload_chains_reload_failure` | `FIX_DONE` | 必要失败路径：可见诊断绑定原故障来源（注入对象/str 或生产缺配置原文）；变异替换诊断红、恢复绿。 |
| `tests/test_state_reload.py` | `test_atomic_and_reload_runs_on_error_before_reload` | `KEEP_SINGLE_FAULT_OR_CONTROL` | 单次失败冒出或控制流；无次生诊断替换假绿证据；不机械加身份。 |
| `tests/test_transaction_boundary.py` | `test_swallowed_inner_exception_forces_outer_rollback` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_transaction_boundary.py` | `test_connection_rollback_attempts_all_runtime_callbacks` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_transaction_boundary.py` | `test_swallowed_conn_context_exception_forces_outer_rollback` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_transaction_boundary.py` | `test_ddl_after_swallowed_conn_context_does_not_escape` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_transaction_boundary.py` | `test_ddl_after_explicit_midatomic_rollback_does_not_escape` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_web_llm_runtime_config.py` | `test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_web_llm_runtime_config.py` | `test_menu_save_llm_cli_channel_rejects_empty_runner` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |
| `tests/test_web_llm_runtime_config.py` | `test_continue_load_save_reach_hud_zero_llm_calls` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_web_llm_runtime_config.py` | `test_hot_replace_http_success_reopens_state_and_writes` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_web_llm_runtime_config.py` | `test_hot_replace_http_failure_keeps_old_state_and_writes_usable` | `KEEP_EXTERNAL_ENUM_OR_CONTENT` | PRIVATE_MARKER 为枚举误伤（AUDIBILITY_PRIVATE／ORIGIN_MARK_PRIVATE_*／内容 marker／model_flag）；外部可读字段契约保留。 |
| `tests/test_web_llm_runtime_config.py` | `test_menu_save_llm_api_channel_rejects_placeholder_existing_key` | `KEEP_EXTERNAL_OR_CONTROL` | 外部零写／错误包／相位／控制流结果为契约；非仅非空诊断。 |

## 原范围复扫

- 判词三样本：trace / SSE 已 FIX_DONE；seed FakeDB 已 DELETE。
- mechanical_tail 缺配置：由非空改为绑定「结局总评缺少模型配置」。
- 上轮误留 KEEP_NO_SWALLOW_SEAM 已纠正为删除。
- 不以扩大 raises 关键词数量结清；处置按可见诊断是否绑定原故障来源。
- 复扫后 core_hits（不含已删）见 j6-enum-summary.json。
