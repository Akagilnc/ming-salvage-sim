# J6 全仓成员表（权威）

类定义：清除盯文、内部伪证及未完成失败路径的初始态证明；完成/失败/回滚须可辨别。
法源：对自由文本一切机械依赖均属盯文；**P7 禁模板负向不是合法盯文豁免**。

枚举命令见 `enum-cmd.txt`。复扫最短结果见 `rescan-final.txt`。**无平行 dispositions.json**。

## 本轮处置 / 授权面

| path | line | test | tags | disposition | why |
|---|---|---|---|---|---|
| `tests/test_audience_restore_505.py` | 314 | test_post_reply_failure_resumes_close_without_re | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_scroll_539.py` | 327 | test_extractor_open_tags_do_not_drive_beat_or_so | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_scroll_539.py` | 420 | test_closed_night_archive_derives_stable_titles_ | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 246 | test_translation_entry_preserves_unknown_rejecti | STRUCTURED_REPAIR | FIXED_REJECTION_ONLY | 删除截止平行证明；仅保留未知section/坏形状拒收负向；不宣称证明截止 |
| `tests/test_audience_translate_1837.py` | 365 | test_appointment_and_relief_through_scene_chat_t | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 600 | test_scene_chat_cli_and_api_same_translation_sha | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_translate_1837.py` | 804 | test_translation_pending_create_approve_reject_u | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_travel_gating_670.py` | 129 | test_cli_initial_selection_records_remote_summon | ANTI_TEMPLATE_PHRASE | FIXED_DROP_PRINT | 删除 print 禁模板负向盯文；保留 unsettled/DB 结构化断言 |
| `tests/test_audience_travel_gating_670.py` | 147 | test_cli_initial_selection_rejects_unknown_unreg | STRUCTURED_REPAIR | FIXED_DROP_PRINT | 删除 print 禁模板负向盯文；保留 unsettled/DB 结构化断言 |
| `tests/test_audience_travel_gating_670.py` | 251 | test_multi_origin_same_person_dedupes_consumer_p | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_audience_travel_gating_670.py` | 679 | test_cli_midflow_summon_consumes_admission_witho | ANTI_TEMPLATE_PHRASE | FIXED_DROP_PRINT | 删除 print 禁模板负向盯文；保留 unsettled/DB 结构化断言 |
| `tests/test_cli_backend.py` | 751 | test_clichat_invoke_json_constraint_and_no_const | PROSE_LOCK | REVIEW_AUTH_PROSE | 授权面散文/拼装机械依赖，逐案确认 |
| `tests/test_cli_backend.py` | 998 | test_secret_extract_traces_exactly_once | ANTI_TEMPLATE_PHRASE | REVIEW_PROSE_ILLEGAL_EXEMPTION | P7 禁模板负向仍属自由文本机械依赖；不豁免为合法 KEEP |
| `tests/test_menu_lifecycle_drain_396.py` | 126 | test_drain_archive_move_failure_keeps_wal_and_sh | STRUCTURED_REPAIR | FIXED_THREAD_JOIN | 真实 api_menu_new_game + 保留真实 Thread join；再断言外部文件/失败 |
| `tests/test_menu_lifecycle_drain_396.py` | 211 | test_drain_archive_rolls_back_main_db_when_wal_m | STRUCTURED_REPAIR | FIXED_THREAD_JOIN | 真实 api_menu_new_game + 保留真实 Thread join；再断言外部文件/失败 |
| `tests/test_menu_lifecycle_drain_396.py` | 258 | test_drain_archive_skips_move_when_session_close | STRUCTURED_REPAIR | FIXED_THREAD_JOIN | 真实 api_menu_new_game + 保留真实 Thread join；再断言外部文件/失败 |
| `tests/test_month_chain_1847.py` | 1384 | test_step_4a_incomplete_0058_report_fails_loud_a | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_month_chain_1847.py` | 1455 | test_step_4a_crash_recovery_resumes_without_re_r | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_month_chain_1847.py` | 1563 | test_step_4a_missing_covert_fidelity_records_inl | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |
| `tests/test_month_chain_1847.py` | 1806 | test_step_4a_non_validation_failure_keeps_produc | MOCK_ORACLE | REVIEW_AUTH_MOCK | 授权面 mock/call oracle；不得替代外部结果 |

## 本轮删除（不另造）

- `test_current_unissued_draft_is_not_character_carryover`：自算 carryover_ids 伪证；prepare 无断言。整条删除。
- 截止案 `_strictly_before` / SQL count / `len(night_said)` 平行块：整块删除；不宣称证明截止。

## 授权面外

全仓谓词另有 web/他票命中（见 rescan 计数）；本票不伪称结清，也不把禁模板负向标成合法 KEEP。
