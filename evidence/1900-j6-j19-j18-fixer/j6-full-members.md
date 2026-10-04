# J6 全仓成员表（权威）

类定义：清除盯文、内部伪证及未经过失败行为的初始状态证明；完成/失败/回滚须可辨别。
法源禁止对自由文本一切机械依赖——**P7 禁模板负向不是合法盯文豁免**。

枚举命令见 `enum-cmd.txt`。机器处置：`j6-dispositions.json`。

## 授权面 / 本轮处置

| path | line | test | tags | disposition | why |
|---|---|---|---|---|---|
| `tests/test_army_card_status_1501.py` | 138 | test_army_payload_omits_static_status_exposes_arre | PROSE_LOCK | KEEP_NONLEAK_DB | 先断言无 status 键；比较 DB 种子值不进载荷字段 |
| `tests/test_audience_background.py` | 231 | test_current_unissued_draft_is_not_character_carry | STRUCTURED_REPAIR | FIXED | 本轮：结构化读侧/完成态同步；删除拼装字符串哨兵与 attempt-only wait |
| `tests/test_audience_continuous_507.py` | 34 | test_scene_recap_quotes_public_dialogue_within_pre | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_audience_continuous_507.py` | 59 | test_scene_recap_excludes_dialogue_before_person_e | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_audience_continuous_507.py` | 81 | test_qianqing_continuous_night_skeleton_runs | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_audience_restore_505.py` | 314 | test_post_reply_failure_resumes_close_without_rege | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_scroll_539.py` | 327 | test_extractor_open_tags_do_not_drive_beat_or_soft | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_scroll_539.py` | 420 | test_closed_night_archive_derives_stable_titles_pe | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 246 | test_translation_entry_preserves_unknown_rejection | PROSE_LOCK | FIXED | 本轮：结构化读侧/完成态同步；删除拼装字符串哨兵与 attempt-only wait |
| `tests/test_audience_translate_1837.py` | 411 | test_appointment_and_relief_through_scene_chat_the | PROSE_LOCK,ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 646 | test_scene_chat_cli_and_api_same_translation_shape | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 850 | test_translation_pending_create_approve_reject_und | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_travel_gating_670.py` | 129 | test_cli_initial_selection_records_remote_summon_w | STRUCTURED_REPAIR | FIXED | 本轮：删除 print 禁模板负向盯文，只留 unsettled/DB 结构化断言 |
| `tests/test_audience_travel_gating_670.py` | 151 | test_cli_initial_selection_rejects_unknown_unregis | STRUCTURED_REPAIR | FIXED | 本轮：删除 print 禁模板负向盯文，只留 unsettled/DB 结构化断言 |
| `tests/test_audience_travel_gating_670.py` | 261 | test_multi_origin_same_person_dedupes_consumer_pro | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_travel_gating_670.py` | 689 | test_cli_midflow_summon_consumes_admission_without | STRUCTURED_REPAIR | FIXED | 本轮：删除 print 禁模板负向盯文，只留 unsettled/DB 结构化断言 |
| `tests/test_audience_undo_506.py` | 158 | test_audit_passes_whitelisted_and_catches_unwhitel | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_audience_undo_506.py` | 361 | test_undo_restores_staging_row_deleted_by_verbal_r | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_audience_undo_506.py` | 563 | test_undo_erases_inactive_office_summon_origin_bou | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_cli_backend.py` | 104 | test_secret_content_assembly_is_emperor_plus_extra | PROSE_LOCK | KEEP_CONFIG | CLI argv/配置开关契约，非叙事自由文本 |
| `tests/test_cli_backend.py` | 508 | test_run_codex_maps_reasoning_strength_to_native_e | PROSE_LOCK | KEEP_CONFIG | CLI argv/配置开关契约，非叙事自由文本 |
| `tests/test_cli_backend.py` | 644 | test_login_shell_path_uses_printenv_not_dollar_pat | PROSE_LOCK | KEEP_CONFIG | CLI argv/配置开关契约，非叙事自由文本 |
| `tests/test_cli_backend.py` | 751 | test_clichat_invoke_json_constraint_and_no_constra | PROSE_LOCK | KEEP_CONFIG | CLI argv/配置开关契约，非叙事自由文本 |
| `tests/test_cli_backend.py` | 986 | test_office_inference_llm_call_is_traced | PROSE_LOCK | KEEP_CONFIG | CLI argv/配置开关契约，非叙事自由文本 |
| `tests/test_cli_backend.py` | 998 | test_secret_extract_traces_exactly_once | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_cli_play_turn.py` | 568 | test_terminal_minister_chat_accepts_retry_reply_co | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_cli_runner_error_typed_1299.py` | 53 | test_clichat_normal_reply_still_returns | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_decree_dossiers_571.py` | 1287 | test_secret_order_progress_undo_restores_order_and | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_highlight_judge_544.py` | 310 | test_chat_nonstream_timeout_returns_reply_without_ | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_menu_lifecycle_drain_396.py` | 89 | test_drain_archive_move_failure_keeps_wal_and_shm | STRUCTURED_REPAIR | FIXED | 本轮：结构化读侧/完成态同步；删除拼装字符串哨兵与 attempt-only wait |
| `tests/test_menu_lifecycle_drain_396.py` | 179 | test_drain_archive_rolls_back_main_db_when_wal_mov | STRUCTURED_REPAIR | FIXED | 本轮：结构化读侧/完成态同步；删除拼装字符串哨兵与 attempt-only wait |
| `tests/test_menu_lifecycle_drain_396.py` | 231 | test_drain_archive_skips_move_when_session_close_f | STRUCTURED_REPAIR | FIXED | 本轮：结构化读侧/完成态同步；删除拼装字符串哨兵与 attempt-only wait |
| `tests/test_month_chain_1843.py` | 70 | test_unforecast_edict_is_caught_up_once_and_crash_ | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_month_chain_1847.py` | 224 | test_answering_world_question_resumes_suffix_then_ | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_month_chain_1847.py` | 1384 | test_step_4a_incomplete_0058_report_fails_loud_and | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_month_chain_1847.py` | 1455 | test_step_4a_crash_recovery_resumes_without_re_run | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_month_chain_1847.py` | 1563 | test_step_4a_missing_covert_fidelity_records_inlin | PROSE_LOCK,MOCK_ORACLE | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_month_chain_1847.py` | 1692 | test_settle_edicts_persists_pending_disclosures_in | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_month_chain_1847.py` | 1806 | test_step_4a_non_validation_failure_keeps_product_ | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_public_sayings_1829.py` | 113 | test_public_saying_excluded_name_does_not_see_it_o | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 127 | test_closing_restore_path_still_catches_up | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 296 | test_stream_post_reply_exception_preserves_phase_a | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 328 | test_dispatch_exception_after_persist_retains_repl | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_relation_read_640.py` | 120 | test_dto_shape_summary_plus_recent_context_with_ba | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_relation_read_640.py` | 160 | test_judge_face_reads_edges_invisible_to_role_view | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |
| `tests/test_scene_llm_1836.py` | 153 | test_retire_via_scene_chat_closes_night_and_keeps_ | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_world_materials_1834.py` | 26 | test_prepare_writes_typed_tree_with_board_affairs_ | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认是否结构化契约 |

## 授权面外

全仓谓词另有大量 web/他票命中（见本轮枚举扫描）；本票不伪称结清，也不把禁模板负向标成合法 KEEP。
