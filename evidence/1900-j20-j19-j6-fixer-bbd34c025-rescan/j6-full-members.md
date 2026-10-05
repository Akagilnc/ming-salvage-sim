# J6 全仓成员表（完整宇宙·本轮 rescan）

类定义：清除盯文、退役行为配套及被其他前置失败遮蔽的证明；必要负向须其余前置合法、实际经过所保失败、外部结果可辨别；保留拒收/回滚/同步；不以替身吞被测行为；不另禁并发/同步、不加生产钩子。J17 来源负回退并入。

枚举：`j6_full_enum.py` → `j6-ast-candidates.jsonl`（FULL_NO_NUMERIC_DROP）。

规模：python+ts candidates=15111；groups=2930。

## 处置计数

```
KEEP_STRUCTURED_OR_HARNESS: 12491
KEEP_DOM_FIXTURE_OR_STRUCTURE: 1351
KEEP_STRUCTURED_OR_FIXTURE: 657
KEEP_LLM_BOUNDARY: 248
KEEP_IO_OR_BOUNDARY: 106
KEEP_WEB_CALLBACK_CONTRACT: 84
KEEP_STRUCTURED_FIELD: 65
KEEP_FISCAL_ORACLE: 56
KEEP_COMPLETION_SYNC: 17
FIX_APPLIED_PROSE_OR_STUB: 15
KEEP_TYPED_ERROR_SHAPE: 13
KEEP_FAILURE_TRAVERSED: 8
```

## 本轮 FIX（代码）

- held 闸：去掉 resolve_directives 替身，改 canned_full_settlement 真实前置
- 注入异常措辞盯文：travel_gating / secret_order_566 / month_call_recovery / material_directory / chat_stream_failpaths / cli_backend / surcharge corruption
- 上轮已清：rejection_wiring 退役提案、month_chain_1843 异常子串、relation J17 甲乙、section4 盯文

## 组别（file::test）

### `tests/conftest.py::_offline_audience_translation_provider`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2})
- lines: 433, 434
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/conftest.py::_offline_scene_beat_generator`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 520
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/conftest.py::stub_audience_translate`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 490
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/month_chain_helpers.py::canned_full_settlement`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 3})
- lines: 59, 60, 64
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_draft_grant_once_1777.py::test_http_audience_one_matter_grant_with_deadline_1783`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 31, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 105, 151, 154, 161, 163, 164, 165, 167, 168, 175, 182, 186…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_restore_505.py::web_game`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 788
- why: IO/环境/边界替身

### `tests/test_audience_translate_1837.py::test_appointment_and_relief_through_scene_chat_then_close_and_settle`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 15, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 413, 456, 457, 459, 460, 461, 462, 463, 464, 465, 468, 473…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_emperor_准_via_scene_chat_approves_no_reply_stays_unapproved`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 555, 568, 583, 593, 594
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_pending_round_approval_endorsed_before_close_or_after_month_join`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 11})
- lines: 151, 170, 175, 176, 178, 190, 198, 230, 231, 236, 237, 238…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_scene_chat_cli_and_api_same_translation_shape`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 626, 649, 659, 660
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_scene_chat_translation_can_approve_staged_action`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 1038, 1048
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_translate_call_failure_is_not_empty_success_dispatch`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 725, 733, 739, 743, 745
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_translate_empty_success_still_dispatches_without_failure`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 757, 765, 766
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837.py::test_translation_pending_create_approve_reject_undo_via_real_chat_turn`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 16})
- lines: 819, 838, 845, 847, 851, 857, 860, 872, 888, 892, 907, 921…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translate_1837_reopen.py::_player_month`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 128, 129, 135, 139
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_audience_translation_once_1898.py::test_reopen_webgame_catches_up_pending_translation`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 59, 79, 80, 81, 85, 86
- why: IO/环境/边界替身

### `tests/test_breach_plea_623.py::test_revoke_forecast_translation_input_carries_original_and_continuing_dossier`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 12, 'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1})
- lines: 453, 458, 459, 470, 471, 481, 482, 483, 491, 494, 495, 499…
- why: 默认：外部可见结构化/夹具

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_config_max_attempts_override`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 906, 908, 909, 910
- why: 默认：外部可见结构化/夹具

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_deterministic_4xx_no_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 810, 812, 813, 814, 815, 816, 817
- why: 默认：外部可见结构化/夹具

### `tests/test_cli_backend.py::_patch_backend`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 44
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_clichat_call_cli_dispatch`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 803, 804, 805, 806, 807, 808, 810, 811, 812
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_clichat_call_cli_dispatches_new_runners`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 1168, 1170, 1172
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_enrich_army_parsed_and_normalized`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 172, 175, 176
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_enrich_backend_error_returns_empty_effects`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 190, 193
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_enrich_building_region_floor`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 184, 186
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_enrich_nondict_subfields_guarded`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 197, 203
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_enrich_trace_records_actual_backend`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 208, 212
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_extract_secret_order_preserves_long_title_without_formal_cap`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_LLM_BOUNDARY': 1})
- lines: 72, 78, 82, 83
- why: 标量/空集/索引结构化契约

### `tests/test_cli_backend.py::test_office_inference_llm_call_is_traced`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 991, 994, 995
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_run_backend_for_config_dispatches_new_runners`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 1145, 1153, 1154, 1155, 1157
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_run_backend_for_config_passes_reasoning_strength_to_codex`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 963, 969
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_run_backend_for_config_traces_every_call`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 945, 947, 948, 950, 951, 952
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_run_backend_for_config_traces_on_backend_error`
- disposition: `FIX_APPLIED_PROSE_OR_STUB` (+{'FIX_APPLIED_PROSE_OR_STUB': 2, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 979, 982, 983
- why: 本轮/上轮已清盯文、退役夹具或前置遮蔽；保留类型+外部结果

### `tests/test_cli_backend.py::test_run_backend_infers_trace_tag_from_prompt`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 933, 938, 939
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_secret_exclusion_extracts_people_and_offices`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 63, 65, 66, 67
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_backend.py::test_secret_extract_traces_exactly_once`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 1002, 1005
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_cli_play_turn.py::test_play_turn_hitl_advancement_ends_turn`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 680, 681, 692, 693, 694
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_court_break_player_lock_1727.py::web_game`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 49
- why: IO/环境/边界替身

### `tests/test_decree_dossiers_571.py::test_batch_draft_extraction_preserves_each_mechanical_payload`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 1778, 1785, 1786, 1787, 1789, 1790, 1791, 1792, 1793
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_cli_edit_replaces_text_and_mechanics_before_promulgation`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 1239, 1245, 1246, 1247, 1252, 1253, 1254, 1260, 1261
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_draft_extraction_does_not_capture_acting_appointment`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 1737, 1747, 1748, 1750
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_reaches_structured_dossier`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 13, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 999, 1011, 1017, 1018, 1019, 1021, 1023, 1025, 1026, 1034, 1037, 1038…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_malformed_roster`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 1067, 1081, 1083, 1084, 1085
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 1106, 1122, 1123, 1124
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_dossiers_571.py::test_session_manual_directive_keeps_structured_action_at_submission`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 1439, 1463, 1469, 1470, 1471, 1472
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_decree_forecast_1861.py::test_held_rejudgments_overlap_instead_of_waiting_in_one_worker`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 13})
- lines: 501, 502, 503, 508, 512, 513, 519, 520, 521, 522, 530, 531…
- why: IO/环境/边界替身

### `tests/test_decree_forecast_1861.py::test_repeat_scene_approval_does_not_rerun_exhausted_forecast`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 385, 386, 396, 397, 398, 399
- why: IO/环境/边界替身

### `tests/test_decree_forecast_1861.py::test_restored_directive_forecast_uses_its_approved_night`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 427, 428, 432, 438, 443, 444, 445
- why: IO/环境/边界替身

### `tests/test_decree_forecast_1861.py::test_same_local_ids_on_two_saves_both_stage`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 568, 569, 570, 588, 589, 592, 601, 602, 604
- why: IO/环境/边界替身

### `tests/test_decree_forecast_1861.py::test_scene_chat_approval_forecasts_each_decree_without_visible_effect`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 25, 'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1})
- lines: 198, 203, 214, 215, 219, 231, 239, 247, 249, 250, 251, 252…
- why: 默认：外部可见结构化/夹具

### `tests/test_decree_forecast_1861.py::test_scene_chat_rejection_is_staged_for_later_rescript_not_shown_at_night`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 335, 336, 347, 348, 349, 350, 351, 352, 353
- why: IO/环境/边界替身

### `tests/test_draft_admission_resubmit_1769.py::_queue_backend`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_LLM_BOUNDARY': 1})
- lines: 138, 144
- why: 默认：外部可见结构化/夹具

### `tests/test_enrich_list_guards.py::test_enrich_buildings_non_list_no_crash`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 23, 25, 26
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_enter_settlement_period_1235.py::_fake_settlement_llm`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2})
- lines: 61, 74
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_enter_settlement_period_1235.py::web_game`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 87
- why: IO/环境/边界替身

### `tests/test_fiscal_levy_effect.py::_install_liao_month_stubs`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 5})
- lines: 1290, 1291, 1292, 1293, 1297
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_fiscal_levy_effect.py::test_liao_levy_rise_approved_lands_on_no_edict_advance_before_fiscal_tick`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 161, 176, 177, 178, 180, 181
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_gazette_author_1862.py::_session`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 53
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 43, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 2})
- lines: 148, 188, 350, 355, 356, 360, 361, 362, 363, 364, 365, 366…
- why: 默认：外部可见结构化/夹具

### `tests/test_gazette_author_1862.py::test_author_waits_until_rescript_is_done`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 75, 77, 83, 84
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_gazette_author_1862.py::test_gazette_failure_retries_report_only`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 10})
- lines: 484, 485, 492, 493, 494, 496, 499, 500, 501, 502, 506, 507
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_grant_reconciliation_567.py::test_web_state_payload_after_settle`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 357, 375, 376, 377, 378, 380, 382, 383
- why: IO/环境/边界替身

### `tests/test_highlight_judge_544.py::test_chat_nonstream_folds_judge_within_timeout`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 290, 296, 298, 306, 307
- why: IO/环境/边界替身

### `tests/test_highlight_judge_544.py::test_chat_nonstream_timeout_returns_reply_without_highlights`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 341, 345, 348, 350, 354, 356
- why: IO/环境/边界替身

### `tests/test_highlight_judge_544.py::test_chat_stream_done_before_highlights_and_degrade`
- disposition: `KEEP_STRUCTURED_FIELD` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 5, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 211, 215, 216, 217, 218, 219, 221, 224
- why: IO/环境/边界替身

### `tests/test_highlight_judge_544.py::test_chat_stream_slow_success_attaches_after_done`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 245, 260, 261, 262, 264, 265, 267, 268, 271
- why: IO/环境/边界替身

### `tests/test_llm_channel_config.py::test_agent_factories_omit_max_tokens_on_param_surface`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_STRUCTURED_OR_FIXTURE': 2, 'KEEP_LLM_BOUNDARY': 1})
- lines: 859, 864, 865, 882, 885, 886
- why: 默认：外部可见结构化/夹具

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_error_status_raises`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 656, 659
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_none_passes`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 633, 635
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_passes`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 610, 613
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_error_status_nonempty_content_raises`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 677, 681
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_smoke_omits_max_tokens`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 587, 590
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_cli_channel_failure_raises`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 512
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_legacy_env_only_failure_raises`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 552
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_respects_api_channel_over_backend_env`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 462, 474, 475
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_smokes_cli_channel_without_backend_env`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 488, 502, 503
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_smokes_legacy_env_only_backend`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 539, 542
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_manual_directive_institution_normalize_1279.py::_mock_draft_intent`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 39
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_manual_directive_locality_1685.py::test_manual_directive_region_assembly_writes_single_and_advances`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 9, 'KEEP_LLM_BOUNDARY': 1})
- lines: 37, 39, 47, 52, 53, 58, 60, 61, 63, 64
- why: 标量/空集/索引结构化契约

### `tests/test_material_directory_1830.py::test_prepare_fails_loud_when_dossier_read_breaks`
- disposition: `FIX_APPLIED_PROSE_OR_STUB` (+{'FIX_APPLIED_PROSE_OR_STUB': 1})
- lines: 169
- why: 本轮/上轮已清盯文、退役夹具或前置遮蔽；保留类型+外部结果

### `tests/test_mechanical_tail_1845.py::_archive_and_stub_world`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2})
- lines: 32, 33
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_advance_schedules_mechanical_tail_after_front_month_advance`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 76, 84, 85, 86, 87, 91, 92, 95
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_TYPED_ERROR_SHAPE': 2, 'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 6})
- lines: 460, 461, 467, 468, 483, 492, 493, 495, 497, 499, 501, 503…
- why: typed 错误包/通道字段非空或排除 banner

### `tests/test_mechanical_tail_1845.py::test_ending_summary_runs_in_mechanical_tail_after_advance`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 21})
- lines: 366, 378, 409, 410, 411, 412, 416, 417, 418, 419, 427, 428…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_exhausted_mechanical_tail_fails_and_blocks_next_month`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 162, 171, 176, 178
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_mechanical_tail_missing_llm_config_surfaces_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 11, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_OR_BOUNDARY': 1})
- lines: 541, 543, 545, 546, 547, 548, 550, 556, 562, 564, 566, 568…
- why: 默认：外部可见结构化/夹具

### `tests/test_mechanical_tail_1845.py::test_non_exhausted_tail_failure_stays_pending_and_retries`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 18})
- lines: 311, 312, 313, 316, 317, 322, 323, 332, 333, 335, 338, 339…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_real_brew_failure_reaches_tail_failure_and_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 203, 209, 215, 216, 217, 220, 223, 227, 228
- why: IO/环境/边界替身

### `tests/test_mechanical_tail_1845.py::test_reopen_resumes_incomplete_mechanical_tail`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 118, 123, 128, 146, 147
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_mechanical_tail_1845.py::test_web_barrier_resumes_pending_tail_before_join`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 257, 275, 280
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_menu_continue_stream_1195.py::test_menu_continue_streams_stage_labels_then_done_state`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1})
- lines: 42, 56, 60, 61, 64, 66, 67, 70, 71, 74, 75, 76
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::_capture_real_drain_threads`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 31
- why: IO/环境/边界替身

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_move_failure_keeps_wal_and_shm`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_FAILURE_TRAVERSED': 1})
- lines: 135, 137, 141, 142, 143, 144, 145, 146
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_rolls_back_main_db_when_wal_move_fails`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_FAILURE_TRAVERSED': 2})
- lines: 221, 223, 227, 228, 229, 230, 231, 232
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_skips_move_when_session_close_fails`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_FAILURE_TRAVERSED': 1})
- lines: 263, 265, 269, 270, 271, 272, 273
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::test_drain_waits_for_queued_chat_stream_not_just_gate_holder`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_STRUCTURED_OR_FIXTURE': 1, 'KEEP_FAILURE_TRAVERSED': 1, 'KEEP_COMPLETION_SYNC': 1})
- lines: 483, 484, 487, 492, 506, 515, 516, 517, 519
- why: 默认：外部可见结构化/夹具

### `tests/test_menu_lifecycle_drain_396.py::test_exit_to_menu_returns_before_delayed_close_drains`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_FAILURE_TRAVERSED': 1, 'KEEP_COMPLETION_SYNC': 1})
- lines: 47, 54, 55, 56, 60, 61
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::test_new_game_returns_before_delayed_close_drains`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_STRUCTURED_OR_FIXTURE': 1, 'KEEP_FAILURE_TRAVERSED': 1, 'KEEP_COMPLETION_SYNC': 1})
- lines: 80, 92, 93, 94, 98, 99
- why: 标量/空集/索引结构化契约

### `tests/test_menu_lifecycle_drain_396.py::test_shutdown_waits_for_drain_before_returning_or_killing`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_FAILURE_TRAVERSED': 1, 'KEEP_COMPLETION_SYNC': 1})
- lines: 291, 300, 301, 302, 307, 308
- why: 默认：外部可见结构化/夹具

### `tests/test_menu_lifecycle_drain_396.py::test_spawn_pending_write_thread_start_failure_releases_ownership`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_COMPLETION_SYNC': 1})
- lines: 591, 594, 595
- why: IO/环境/边界替身

### `tests/test_month_call_recovery_1846.py::test_code_exception_during_world_commit_keeps_phase_and_settled_edicts`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'FIX_APPLIED_PROSE_OR_STUB': 1, 'KEEP_STRUCTURED_OR_HARNESS': 9})
- lines: 479, 486, 493, 494, 495, 496, 497, 502, 503, 504, 505
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_edict_settle_code_exception_stops_at_month_entry_and_retries_once`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 11, 'FIX_APPLIED_PROSE_OR_STUB': 1})
- lines: 618, 619, 640, 641, 642, 643, 644, 645, 646, 648, 649, 652…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 9, 'FIX_APPLIED_PROSE_OR_STUB': 2})
- lines: 675, 676, 702, 703, 704, 705, 706, 708, 709, 710, 713, 715…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_escape_hatch_discards_world_segment_only_on_second_player_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 13})
- lines: 361, 362, 371, 372, 373, 381, 382, 383, 384, 389, 390, 391…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_forecast_exhaustion_does_not_overwrite_prior_ending`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 187, 197, 198, 199, 200, 204, 205, 206, 207
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_month_entry_world_push_follows_audience_transport_policy`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 11})
- lines: 124, 125, 127, 128, 131, 132, 133, 138, 139, 140, 141
- why: 标量/空集/索引结构化契约

### `tests/test_month_call_recovery_1846.py::test_settlement_recovery_projects_month_call_failure`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 9, 'FIX_APPLIED_PROSE_OR_STUB': 1})
- lines: 409, 422, 429, 431, 432, 433, 434, 439, 451, 452, 453, 457
- why: IO/环境/边界替身

### `tests/test_month_call_recovery_1846.py::test_world_commit_failure_after_alongside_retries_uncommitted_segment`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 18})
- lines: 539, 540, 565, 566, 567, 568, 569, 573, 574, 575, 579, 580…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_world_text_exhaustion_stops_month_keeps_settled_edicts`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 11})
- lines: 229, 236, 237, 238, 240, 242, 243, 248, 249, 250, 251, 252
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_call_recovery_1846.py::test_world_translate_exhaustion_keeps_text_resume_retries_translate_only`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_OR_HARNESS': 12})
- lines: 284, 285, 295, 296, 297, 298, 300, 301, 302, 308, 309, 316…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::_prepare_player_month`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1})
- lines: 57, 61, 66
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_finish_rescript_phase2_stays_settling_until_advanced`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 259, 263, 264
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_missing_world_model_stops_before_world_commit`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_LLM_BOUNDARY': 1})
- lines: 506, 507, 508, 509, 510
- why: 默认：外部可见结构化/夹具

### `tests/test_month_chain_1843.py::test_month_drift_settles_due_secret_and_records_inertia_rejection`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 535, 536, 548, 549, 554, 556, 557
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_player_entry_recovers_ending_after_interrupted_segment`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 9, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 313, 314, 321, 322, 323, 326, 328, 329, 338, 339, 340, 341
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_player_recovery_uses_resolve_context_decree_not_ready_delta`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 228, 232, 233, 235, 236, 238, 239
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_questions_hold_rescript_and_gazette_is_required_before_advance`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 18})
- lines: 157, 160, 164, 165, 166, 167, 168, 169, 182, 183, 184, 197…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 115, 122, 123, 124, 129, 130, 131, 134
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_world_segment_persists_declaration_ending_with_commit`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 270, 282, 283, 285
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1843.py::test_world_segment_reads_material_directory`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 599, 604, 606, 607, 608, 609, 610, 612, 613, 616, 617, 618
- why: IO/环境/边界替身

### `tests/test_month_chain_1847.py::_resolve_with_emperor_fate`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 4})
- lines: 1105, 1106, 1107, 1108
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_answering_triad_applies_and_releases_rescript_gate`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 191, 192, 214, 215, 216, 219, 220
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_answering_world_question_resumes_suffix_then_gazette`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 232, 235, 252, 253, 270, 271, 272, 274, 275, 278, 279, 281
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_cross_month_pending_draft_opens_rescript_desk`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 606, 607, 614, 615, 616, 617, 618, 620, 621
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_continuation_ending_ends_the_month`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 5, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 1074, 1075, 1076, 1077, 1078, 1089, 1090, 1091, 1092
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_TYPED_ERROR_SHAPE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 11, 'KEEP_STRUCTURED_FIELD': 1})
- lines: 678, 680, 681, 700, 701, 704, 705, 706, 708, 709, 710, 713…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_continuation_survives_llm_exhaustion_then_retries`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 399, 400, 401, 408, 426, 427, 430, 431, 435, 436, 439, 440
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_forecast_keeps_every_question_and_translates_prefix_once`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 758, 763, 767, 775, 776, 777, 781, 782
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_question_and_world_question_share_one_desk`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 463, 467, 474, 476
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_decree_question_continuation_idempotent_on_same_turn_reentry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 320, 321, 322, 329, 345, 346, 350, 351, 352
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_drift_sees_effects_landed_after_answers`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 1162, 1165, 1168, 1172, 1173, 1183, 1186
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_fatal_midzhi_rejection_hides_force_option`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 954, 955, 963, 965, 967
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_midzhi_promulgation_records_authority_cost_once`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 991, 999, 1004
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_midzhi_verdict_and_metadata_roll_back_together`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 1024, 1029, 1031, 1035
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_missing_model_does_not_mark_world_continued`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 550, 553, 567, 569, 570, 571, 573, 580, 581
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_missing_model_keeps_decree_question_until_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 512, 513, 527, 528, 529, 537, 540, 541, 542
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_prior_month_answered_rescript_does_not_block_or_reappear`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 139, 140, 146, 147, 148
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_question_note_only_is_kept_and_other_decisions_still_require_label`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 817, 818, 819, 836, 837, 838, 847, 848, 849, 871, 872
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_crash_recovery_resumes_without_re_running_supply`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 1487, 1488, 1489, 1511, 1513, 1515, 1516, 1520, 1521, 1523, 1525
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_deferred_disclosure_sees_fresh_0058_progress`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 1361, 1362, 1363, 1368, 1376, 1377, 1379, 1381
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 1431, 1432, 1433, 1440, 1442, 1444, 1445, 1449, 1450, 1451, 1452
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_missing_covert_fidelity_records_inline_rejection`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 27, 'KEEP_STRUCTURED_FIELD': 1})
- lines: 1625, 1626, 1627, 1633, 1636, 1637, 1638, 1639, 1640, 1641, 1642, 1646…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_no_eligible_objects_skips_run_and_completes`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 1196, 1197, 1202, 1207, 1209
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_non_validation_failure_keeps_product_on_retry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 7})
- lines: 1845, 1846, 1847, 1854, 1856, 1857, 1858, 1861, 1862, 1863
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 9, 'KEEP_STRUCTURED_FIELD': 1})
- lines: 1273, 1276, 1279, 1280, 1287, 1288, 1295, 1298, 1299, 1300, 1306, 1313…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_rescript_path_feeds_landed_not_assembled_effects`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_STRUCTURED_FIELD': 2})
- lines: 2162, 2165, 2168, 2169, 2175, 2180, 2182, 2183, 2184, 2189, 2195, 2196
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_step_4a_settles_due_secret_order`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 1916, 1917, 1918, 1923, 1926, 1928, 1929
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_this_turn_rejection_opens_triad_on_same_desk`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 160, 165, 166, 173, 175, 176, 177
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_world_question_opens_rescript_desk_and_awaits`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 9})
- lines: 74, 77, 84, 85, 86, 87, 88, 90, 91, 92, 93
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_chain_1847.py::test_world_segment_multiple_questions_share_one_desk`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 100, 104, 111, 113
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_month_loop_tracer_1468.py::_stub_outer_llm_seams`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 3})
- lines: 63, 87, 91, 95
- why: IO/环境/边界替身

### `tests/test_month_translate_1840.py::test_unparseable_month_segment_does_not_stage_or_commit`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 483, 488, 491
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_new_game_smoke.py::fresh_game_dir`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 49, 57
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_api_channel_unknown_office_does_not_use_backend_env`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 66, 74, 75
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_api_channel_unknown_office_ignores_cli_derived_cache`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 112, 122, 126, 134, 135
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_fresh_gamesession_start_makes_no_backend_calls`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 201, 216
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_fresh_seed_makes_no_office_type_backend_calls`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 168, 178, 187, 188, 189
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_runtime_cli_unknown_office_uses_configured_runner_without_env`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 88, 99, 100, 101
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_office_inference.py::test_use_llm_false_skips_backend_and_trusts_content_type`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 145, 151, 154, 155, 157, 158
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pay_order_override_653.py::_capture_override_decree`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 1619, 1623, 1624, 1625, 1632, 1633
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pay_order_override_extraction_653.py::test_multi_pay_order_capture_preserves_reverse_non_tied_priorities`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 90, 95, 96
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pay_order_override_extraction_653.py::test_relative_deadline_cannot_stage_llm_computed_expired_turn`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 50
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pay_order_override_extraction_653.py::test_single_pay_order_capture_grounds_relative_deadline_at_current_turn`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 25, 29, 43, 44
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pay_order_override_extraction_653.py::test_single_pay_order_capture_rejects_missing_entries`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 67
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pihong_dossier_1490.py::_1778_generate`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 2843
- why: IO/环境/边界替身

### `tests/test_pihong_dossier_1490.py::_657_install_real_phase2_llm_boundary`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 75
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pihong_dossier_1490.py::test_1621_http_follow_draft_uses_catalog_army_id`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 2})
- lines: 1421, 1429, 1431, 1455, 1456, 1457, 1459
- why: IO/环境/边界替身

### `tests/test_pihong_dossier_1490.py::test_1778_missing_roster_heals_then_error_pack_without_assigning_anyone`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_STRUCTURED_FIELD': 1})
- lines: 2984, 2993, 2996, 2998, 3003, 3004, 3007, 3008, 3013, 3015, 3016, 3019
- why: IO/环境/边界替身

### `tests/test_pihong_dossier_1490.py::test_657_revise_deliberate_strict_contracts_zero_write_on_bad_shape`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 6, 'KEEP_STRUCTURED_OR_HARNESS': 19, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 2086, 2090, 2091, 2100, 2104, 2107, 2109, 2110, 2113, 2117, 2118, 2119…
- why: IO/环境/边界替身

### `tests/test_pihong_dossier_1490.py::test_657_s10_http_five_actions_and_1490_no_regress`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 18, 'KEEP_STRUCTURED_OR_FIXTURE': 3})
- lines: 1255, 1264, 1329, 1341, 1344, 1345, 1346, 1350, 1351, 1357, 1359, 1361…
- why: IO/环境/边界替身

### `tests/test_pihong_dossier_1490.py::test_658_free_decree_capture_target_dossier_real_entry`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 20, 'KEEP_LLM_BOUNDARY': 1})
- lines: 2580, 2585, 2594, 2595, 2596, 2617, 2619, 2620, 2621, 2622, 2624, 2626…
- why: 标量/空集/索引结构化契约

### `tests/test_pihong_dossier_1490.py::test_658_mixed_ordinary_triad_and_target_rejected`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 2819, 2822, 2823
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pihong_dossier_1490.py::test_658_routing_rejected_draft_retries_across_real_turn_boundaries`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 28})
- lines: 2730, 2739, 2740, 2745, 2746, 2748, 2749, 2750, 2752, 2753, 2754, 2755…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pihong_dossier_1490.py::test_658_stalled_excluded_from_promulgation_validation`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 2416, 2419, 2420, 2421, 2422
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 22, 'KEEP_LLM_BOUNDARY': 2})
- lines: 2671, 2672, 2673, 2674, 2675, 2676, 2677, 2678, 2684, 2688, 2690, 2691…
- why: 默认：外部可见结构化/夹具

### `tests/test_pihong_dossier_1490.py::web_game`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_OR_BOUNDARY': 1})
- lines: 57, 58
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_promulgation_judge_561.py::test_default_promulgation_judge_uses_one_batch_and_existing_validator`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 790, 798, 804, 805, 806
- why: IO/环境/边界替身

### `tests/test_promulgation_judge_561.py::test_review_exempt_actions_auto_promulgate_without_judge_contract_abort`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 915, 924, 925, 926
- why: IO/环境/边界替身

### `tests/test_public_sayings_1829.py::test_public_saying_excluded_name_does_not_see_it_others_do`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 22, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1})
- lines: 160, 163, 166, 170, 171, 194, 201, 202, 218, 219, 220, 221…
- why: 标量/空集/索引结构化契约

### `tests/test_qa_d1_decree_normalize_1274.py::test_capture_drops_dachen_generic_no_409`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 42, 47, 48, 56, 57
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_capture_unknown_person_still_409`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 78
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_empty_text_capture_short_circuits_without_llm`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 166, 170, 171, 172
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_normal_capture_path_unchanged`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 244, 251, 252, 254
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_seeded_draft_long_extract_still_lands_real_dossier`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5})
- lines: 208, 217, 218, 224, 225, 226
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_qa_t1_extraction_dual_source_1353.py::test_seal_claim_rejects_current_trail_legs_without_write`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 256, 261, 264, 265
- why: IO/环境/边界替身

### `tests/test_refugee_loop_652.py::test_in_transit_relief_stays_executing_before_gazette`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 16, 'KEEP_IO_OR_BOUNDARY': 1})
- lines: 531, 532, 537, 542, 544, 551, 552, 564, 565, 566, 572, 573…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_relation_brew_636.py::test_provider_fault_becomes_typed_brew_failure`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 46, 50
- why: IO/环境/边界替身

### `tests/test_relation_seed_638.py::fresh_session`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 37
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_relation_seed_638.py::test_earliest_legal_start_imports_only_earlier_seed_events`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 186, 197, 199, 200
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_relation_seed_638.py::test_existing_save_is_never_touched_by_seed_import`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_LLM_BOUNDARY': 1})
- lines: 434, 448, 461, 462
- why: 标量/空集/索引结构化契约

### `tests/test_relation_seed_638.py::test_missing_bundled_seed_fails_new_save_and_retry_imports`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 212, 223, 228, 229
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_relation_seed_638.py::test_seed_failure_rolls_back_new_save_and_retry_imports`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 291, 304, 309, 310
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_rescript_choices_563.py::test_manual_edit_preserves_existing_mode_when_text_and_extractor_are_silent`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 50, 58
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_rescript_choices_563.py::test_manual_mode_uses_typed_extractor_judgment`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 39, 42
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_rescript_draft_656.py::test_generate_combined_target_and_roster_failures_reported_together_then_land`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_STRUCTURED_OR_FIXTURE': 2})
- lines: 403, 409, 410, 412, 413, 414, 416, 418, 423, 424
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_combined_target_roster_partial_heal_reports_remaining`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 468, 474, 475, 476, 477, 478, 479, 484, 489
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_existing_offcourt_roster_character_lands`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 591, 604, 605, 606, 607
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_military_order_region_target_heals_then_drops`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 622, 634, 636
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_rejects_military_order_empty_assignee`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 653, 662, 664, 665, 666
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_rescript_draft_degrades_loudly_without_raising`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 811, 813, 815, 817
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_rescript_draft_program_error_propagates`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 827
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_ungrounded_army_heals_then_drops_sibling_kept`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 347, 356, 357, 358
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_ungrounded_region_heals_then_drops_sibling_kept`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 321, 329, 330, 331
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_unknown_delegator_heals_then_drops_sibling_kept`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 564, 576, 577, 578
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_generate_unknown_roster_character_heals_with_legal_set_then_lands`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_STRUCTURED_OR_FIXTURE': 5})
- lines: 526, 532, 533, 535, 536, 538, 544, 545, 546, 547, 548, 550…
- why: IO/环境/边界替身

### `tests/test_rescript_draft_656.py::test_r3_strict_parse_degrades_via_generate`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 956, 959, 961
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_eight_items_all_pass_no_heal_no_trim`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 226, 228, 229, 230, 231, 232, 234
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_item_utf8_heals_then_drops_only_bad_item`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 2})
- lines: 130, 132, 133, 134, 136, 137, 138
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_top_unformed_heals_then_no_drafts`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 108, 109, 110, 111, 113, 114, 115, 117
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 187, 189, 190, 191
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3})
- lines: 209, 211, 212, 213
- why: IO/环境/边界替身

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heals_then_ignores_key_keeps_items`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 3})
- lines: 150, 152, 153, 154, 157, 158, 159, 163
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_amount_numeric_string_accepted_via_grant_shape`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 337, 342, 344
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_army_single_combo_heals_not_batch_redraw`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_STRUCTURED_OR_FIXTURE': 3})
- lines: 386, 388, 389, 392, 393, 394, 396, 398, 399
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_contract_failure_heals_not_batch_reject`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 315, 317, 318, 323, 325, 327, 328
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_dual_missing_discriminator_heals_grant_action`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1})
- lines: 417, 419, 423
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 859, 860, 861, 863, 865, 867
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_heal_bad_identity_refuses_merge_then_drops`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 901, 903, 905
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_heal_response_contract_failure_consumes_attempt_keeps_siblings`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 24, 'KEEP_STRUCTURED_OR_FIXTURE': 3})
- lines: 777, 779, 780, 782, 783, 786, 792, 794, 797, 799, 800, 803…
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_missing_target_kind_only_heals_not_combo_batch`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 362, 364, 365, 367
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_option_shape_failures_heal_not_batch`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 666, 668, 669, 674, 675, 676
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_overflow_json_number_exhaust_drops_only_bad`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8})
- lines: 590, 592, 593, 595, 598, 601, 603, 604, 606
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_overflow_json_number_heals_not_batch`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 545, 547, 548, 549, 551, 552, 556, 557, 558, 561, 565, 568
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_provider_still_whole_batch_item_missing_heals_and_drops`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 686, 690, 701, 703, 704, 705
- why: IO/环境/边界替身

### `tests/test_rescript_option_field_heal_1746.py::test_typed_illegal_also_heals`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 464, 466, 470, 471
- why: IO/环境/边界替身

### `tests/test_runtime_llm_config.py::test_runtime_llm_transport_nonpositive_falls_back_to_defaults`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 10})
- lines: 569, 570, 571, 573, 574, 575, 576, 588, 589, 590
- why: 默认：外部可见结构化/夹具

### `tests/test_runtime_llm_config.py::test_runtime_llm_transport_slot_defaults_and_preserve`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 511, 512, 513, 515, 527, 537, 538, 539
- why: 默认：外部可见结构化/夹具

### `tests/test_scene_llm_1836.py::test_retire_via_scene_chat_closes_night_and_keeps_last_turn`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 9})
- lines: 165, 169, 183, 187, 189, 191, 193, 196, 197, 198
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_scene_llm_1836.py::test_scene_chat_one_call_returns_multi_person_script`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 66, 72, 74, 75, 76
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_scene_llm_1836.py::test_xuan_lands_enter_then_present_on_next_prepare`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_LLM_BOUNDARY': 1})
- lines: 86, 94, 105, 106, 109, 110
- why: 默认：外部可见结构化/夹具

### `tests/test_secret_order_monthly_progress_566.py::_canned_monthly_settlement`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 54
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_secret_order_payoff_1504.py::test_invalid_declaration_stops_month_chain_and_marks_invalid`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 11, 'KEEP_STRUCTURED_OR_FIXTURE': 3, 'KEEP_IO_OR_BOUNDARY': 1})
- lines: 2013, 2014, 2015, 2016, 2018, 2019, 2020, 2031, 2032, 2033, 2052, 2063…
- why: 标量/空集/索引结构化契约

### `tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 17, 'KEEP_IO_OR_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_FIXTURE': 1})
- lines: 1038, 1040, 1041, 1047, 1048, 1053, 1062, 1064, 1067, 1070, 1071, 1072…
- why: 默认：外部可见结构化/夹具

### `tests/test_structured_decree_contract_1624.py::test_batch_combo_correction_real_wrapper`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 12})
- lines: 750, 757, 762, 763, 764, 765, 766, 767, 768, 769, 770, 781…
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_structured_decree_contract_1624.py::test_combo_correction_preserves_first_draw_roster`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_LLM_BOUNDARY': 1})
- lines: 539, 592, 601, 602, 603, 604, 605, 606, 607, 609, 610
- why: 默认：外部可见结构化/夹具

### `tests/test_structured_decree_contract_1624.py::test_http_manual_directive_lands_beyond_fifteen_initiatives_1790`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 14, 'KEEP_LLM_BOUNDARY': 1})
- lines: 404, 406, 420, 429, 431, 439, 440, 442, 450, 452, 453, 454…
- why: 标量/空集/索引结构化契约

### `tests/test_structured_decree_contract_1624.py::test_manual_owner_example_seal_advances`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 10, 'KEEP_LLM_BOUNDARY': 1})
- lines: 341, 343, 349, 352, 357, 366, 368, 369, 370, 372, 373
- why: 标量/空集/索引结构化契约

### `tests/test_structured_decree_contract_1624.py::test_month_end_entry_owner_and_matrix_reject`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_IO_OR_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 24})
- lines: 221, 228, 230, 231, 232, 233, 234, 235, 236, 251, 255, 256…
- why: IO/环境/边界替身

### `tests/test_surcharge_causal_chain_650.py::test_player_month_recovery_consumes_old_levy_once`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 4})
- lines: 266, 269, 270, 272, 273
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_verify_llm_clocks_884.py::test_api_verify_hang_retries_then_exhausts_with_stage`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_STRUCTURED_OR_HARNESS': 6})
- lines: 80, 81, 83, 84, 85, 88
- why: 默认：外部可见结构化/夹具

### `tests/test_verify_llm_clocks_884.py::test_api_verify_installs_sdk_attempt_clock`
- disposition: `KEEP_STRUCTURED_OR_HARNESS` (+{'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2})
- lines: 136, 139, 140
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_web_audience_night_498.py::_fake_settlement_llm`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 3})
- lines: 92, 95, 99
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `tests/test_web_audience_night_498.py::web_game`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 135
- why: IO/环境/边界替身

### `tests/test_web_court_visibility.py::_stub_game`
- disposition: `KEEP_IO_OR_BOUNDARY` (+{'KEEP_IO_OR_BOUNDARY': 1})
- lines: 216
- why: IO/环境/边界替身

### `tests/test_web_llm_runtime_config.py::_count_llm_calls`
- disposition: `KEEP_LLM_BOUNDARY` (+{'KEEP_LLM_BOUNDARY': 1})
- lines: 903
- why: 外部 LLM/世界段缝替身；行为断言在结构化结果

### `web/src/components/decisionModal.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 25, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 85, 'KEEP_WEB_CALLBACK_CONTRACT': 13})
- lines: 42, 45, 46, 56, 63, 64, 65, 66, 70, 74, 78, 83…
- why: 默认：外部可见结构化/夹具

### `web/src/components/drawers.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 11, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 102, 'KEEP_WEB_CALLBACK_CONTRACT': 6})
- lines: 98, 163, 164, 165, 166, 167, 168, 193, 194, 221, 222, 223…
- why: 默认：外部可见结构化/夹具

### `web/src/components/gameMenu.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 22, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 80, 'KEEP_WEB_CALLBACK_CONTRACT': 6})
- lines: 59, 91, 100, 102, 111, 145, 146, 149, 150, 174, 175, 177…
- why: 默认：外部可见结构化/夹具

### `web/src/components/menuPage.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 17, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 45, 'KEEP_WEB_CALLBACK_CONTRACT': 6})
- lines: 85, 86, 96, 127, 128, 143, 144, 147, 149, 154, 155, 156…
- why: 默认：外部可见结构化/夹具

### `web/src/components/modals.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_DOM_FIXTURE_OR_STRUCTURE': 234, 'KEEP_STRUCTURED_OR_HARNESS': 67, 'KEEP_WEB_CALLBACK_CONTRACT': 28})
- lines: 56, 57, 293, 294, 295, 296, 298, 302, 311, 312, 313, 315…
- why: Web DOM/结构/回调

### `web/src/components/settlementGazettePanel.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 5, 'KEEP_WEB_CALLBACK_CONTRACT': 1})
- lines: 28, 37, 38, 39, 40, 45, 47
- why: 默认：外部可见结构化/夹具

### `web/src/useSettlementFlow.test.tsx::_`
- disposition: `KEEP_DOM_FIXTURE_OR_STRUCTURE` (+{'KEEP_STRUCTURED_OR_HARNESS': 23, 'KEEP_WEB_CALLBACK_CONTRACT': 24, 'KEEP_DOM_FIXTURE_OR_STRUCTURE': 48})
- lines: 196, 199, 203, 207, 208, 213, 214, 215, 216, 221, 222, 223…
- why: 默认：外部可见结构化/夹具


## KEEP 组别例外（可核）

- KEEP_* 组别数=2678：断言落在结构化字段/标量契约/LLM·IO 边界替身/Web 回调/完成态同步/财政 oracle。
- 逐条处置见 `j6-full-disposition.jsonl`（与本表同一宇宙，禁止以冻结旧表归零）。
- 高相关/FIX 组详列=252。