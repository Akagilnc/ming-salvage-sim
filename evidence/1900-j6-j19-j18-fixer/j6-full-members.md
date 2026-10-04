# J6 全仓成员表（权威·完整宇宙）

类定义：清除盯文、内部伪证及未经过失败行为的初始状态证明；完成/失败/回滚须可辨别。

法源：对自由文本一切机械依赖均属盯文；**P7 禁模板负向不是合法盯文豁免**。

枚举：`git ls-files` 全仓测试 + Python AST **全量 Assert**（含纯 numeric/None/bool/索引/空集合）+ unittest assert* + stub/mock/helper/wait/oracle + TS **全** expect/assert/spy/mock/matcher 入口。

命令真源：`enum-cmd.txt`（`FULL_NO_NUMERIC_DROP`；**已废除**旧 `visit_Assert drop pure numeric structured unless mock` 收窄）。

机械候选 raw：`j6-ast-candidates.jsonl`（与 full 同一宇宙，不平行双表）。

规模：path_count=248 py_files=227 ts_files=21 py_cand=13420 ts_cand=1663 adjudicated=15083 groups=2930。

**本表=全部机械候选的处置真源**（非 FOCUS 子集）。FOCUS 旧标签仅作既有 KEEP 复用线索，**不是授权边界**。纯数字**不**默认为合法——按外部契约语义归入 KEEP_* 或 FIX。

格式：按 `file::test` 分组；组内列断言行号与主处置+契约理由（不逐行重复泛泛 KEEP）。


## 处置计数（全宇宙）

```
KEEP_STRUCTURED_OR_HARNESS: 6757
KEEP_STRUCTURED_FIELD: 6428
KEEP_DOM_FIXTURE_OR_STRUCTURE: 592
KEEP_LLM_BOUNDARY: 256
KEEP_WEB_FETCH_HARNESS: 256
KEEP_FISCAL_ORACLE: 164
KEEP_IO_BOUNDARY: 162
KEEP_CLI_ARGV_OR_ASSEMBLY: 128
KEEP_RESCRIPT_STRUCTURE: 75
KEEP_FIXTURE_ECHO: 64
KEEP_P4_NEGATIVE: 53
KEEP_LLM_CONFIG_SURFACE: 52
KEEP_FIXTURE_OR_SEED: 23
KEEP_COMPLETION_SYNC: 20
KEEP_SECRET_ORDER_STRUCTURE: 16
KEEP_UI_CHROME: 12
KEEP_TYPED_ERROR_SHAPE: 6
KEEP_SEED_SOURCE_ID: 5
KEEP_NONBLOCKING_RETURN: 4
KEEP_FAILURE_TRAVERSED: 4
KEEP_THREAD_FACTORY_APPLIED: 3
KEEP_ARCHIVE_SHAPE: 1
KEEP_TRACE_ONCE: 1
KEEP_THREAD_CAPTURE: 1
TOTAL_ADJUDICATED: 15083
TOTAL_GROUPS: 2930
```


## 本轮代码 FIX

- **无新生产/测试代码改动**：全宇宙语义复核后，未发现仍成立的盯文哨兵 / 失败路径未经过的初始态假绿 / raises(match=) / mock 调用锁残留。

- 既有已落 FIX（本轮复用为 KEEP_*_APPLIED / 契约 KEEP）：`make_thread` 归档三负向；草案/截止伪证已删；J19 normalize+merge；J18 软判说明已删。


## 高相关组（初始态/同步/边界/生成文线索/先前样本邻域）

### `tests/conftest.py::_offline_audience_translation_provider`
- lines: 433, 434
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/conftest.py::_offline_scene_beat_generator`
- lines: 520
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/conftest.py::stub_audience_translate`
- lines: 490
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/month_chain_helpers.py::canned_full_settlement`
- lines: 59, 60, 64
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_audience_background.py::_assert_next_accepted`
- lines: 158, 159, 160, 161, 162, 163, 164
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_background.py::_wait_for_pending_writes_to_drain`
- lines: 153
- disposition: `KEEP_COMPLETION_SYNC`
- tags: WAIT_UNTIL
- contract/why: wait_until 同步 closed/文件/sealed/done 完成态

### `tests/test_audience_background.py::test_chat_reload_exposes_retryable_failed_secret_order`
- lines: 186, 187, 188
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_background.py::test_chat_stream_closed_before_turn_creation_is_noop`
- lines: 249, 250, 251
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, INDEX_ACCESS
- contract/why: 索引字段外部结果

### `tests/test_audience_background.py::test_newer_interrupted_turn_blocks_withdrawal_of_completed_turn`
- lines: 207, 210, 211
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, INDEX_ACCESS, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_background.py::test_withdrawal_under_web_write_gate_returns_undone_turn`
- lines: 227, 228
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INDEX_ACCESS, NONE_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_continuous_507.py::test_scene_recap_excludes_dialogue_before_person_entered`
- lines: 72, 73
- disposition: `KEEP_FIXTURE_ECHO` （组内另有 {'KEEP_P4_NEGATIVE': 1}）
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: 中文子串——按夹具回传/结构化字段审；非模板哨兵则保留

### `tests/test_audience_draft_grant_once_1777.py::test_http_audience_one_matter_grant_with_deadline_1783`
- lines: 105, 151, 154, 161, 163, 164, 165, 167, 168, 175, 182, 186, 196, 197, 207, 209, 211, 212, 219, 227, 228, 235, 246, 247, 259, 260, 261, 268, 269, 275, 277, 279, 280
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 13, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_restore_505.py::test_post_reply_failure_resumes_close_without_regenerating_reply`
- lines: 321, 332, 333, 334, 335
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_restore_505.py::web_game`
- lines: 788
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_audience_scroll_539.py::test_closed_night_archive_derives_stable_titles_people_and_no_content`
- lines: 434, 435, 439, 440, 441, 442
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_ARCHIVE_SHAPE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837.py::_hong_name`
- lines: 97
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_IS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translate_1837.py::_region_id`
- lines: 81
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_IS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translate_1837.py::test_appointment_and_relief_through_scene_chat_then_close_and_settle`
- lines: 413, 456, 457, 459, 460, 461, 462, 463, 464, 465, 468, 473, 482, 491, 501, 509, 525, 531
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_FIXTURE_ECHO': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_ATTR, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_translate_1837.py::test_appointment_region_id_stages_into_pending_payload`
- lines: 1002, 1004, 1011, 1012
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837.py::test_appointment_without_text_is_rejected_not_templated`
- lines: 786, 787, 794
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837.py::test_emperor_准_via_scene_chat_approves_no_reply_stays_unapproved`
- lines: 555, 568, 583, 593, 594
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_audience_translate_1837.py::test_pending_round_approval_endorsed_before_close_or_after_month_join`
- lines: 151, 170, 175, 176, 178, 190, 198, 230, 231, 236, 237, 238, 243
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837.py::test_pure_office_dossier_uses_payload_text_not_template`
- lines: 953, 955, 962, 973, 974, 976, 978
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_translate_1837.py::test_scene_chat_cli_and_api_same_translation_shape`
- lines: 626, 649, 659, 660
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: FakeAgent 边界；CLI/API 同形结构化声明

### `tests/test_audience_translate_1837.py::test_scene_chat_translation_can_approve_staged_action`
- lines: 1038, 1048
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_audience_translate_1837.py::test_scene_stay_attend_uses_actual_protagonist_not_virtual_speaker`
- lines: 361, 362
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_audience_translate_1837.py::test_summons_translation_does_not_apply_monthly_effects_at_night`
- lines: 319, 332, 333, 334, 342, 343, 344
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837.py::test_translate_call_failure_is_not_empty_success_dispatch`
- lines: 725, 733, 739, 743, 745
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_ATTR, NONE_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_audience_translate_1837.py::test_translate_empty_success_still_dispatches_without_failure`
- lines: 757, 765, 766
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_ATTR, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_audience_translate_1837.py::test_translation_entry_preserves_unknown_rejection`
- lines: 291, 296, 300, 309
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837.py::test_translation_pending_create_approve_reject_undo_via_real_chat_turn`
- lines: 819, 838, 845, 847, 851, 857, 860, 872, 888, 892, 907, 921, 929, 930, 931, 932, 933
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837.py::test_unhandleable_commission_rejected_as_fact_no_forced_ask`
- lines: 680, 681, 682, 702, 703, 704
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837_reopen.py::_active_minister`
- lines: 50
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_IS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translate_1837_reopen.py::_bound_exposure`
- lines: 80
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, NUM_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_audience_translate_1837_reopen.py::_hong`
- lines: 34
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_IS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translate_1837_reopen.py::_player_month`
- lines: 128, 129, 135, 139
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_audience_translate_1837_reopen.py::_scene_declaration`
- lines: 104
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_IS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translate_1837_reopen.py::test_commission_failure_does_not_erase_prior_staged_item`
- lines: 213, 214, 216
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837_reopen.py::test_inquiry_declaration_preserves_assignment_in_attendant_materials`
- lines: 334, 335, 340, 344, 345, 346, 348, 360, 362
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837_reopen.py::test_prohibit_covert_levy_commission_binds_exposed_dossier`
- lines: 151, 156, 165, 166, 172, 173, 174, 175, 181, 182, 183, 194, 195, 196, 199
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_translate_1837_reopen.py::test_recommendation_commission_stages_office_with_reason`
- lines: 259, 260, 261, 266, 268, 269, 270, 271, 272, 276, 282, 287, 289
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_translate_1837_reopen.py::test_recommendation_outside_slice_is_rejected`
- lines: 319, 320, 321
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, EMPTY_COLLECTION
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_translate_1837_reopen.py::test_repeated_urgent_summons_have_independent_rollback_origins`
- lines: 471, 475, 476, 479
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837_reopen.py::test_rush_commitment_stages_pending_催办`
- lines: 422, 423, 428, 429, 431, 432, 433, 439, 440, 445, 446
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837_reopen.py::test_separate_inquiries_same_turn_survive_and_retry_is_idempotent`
- lines: 383, 384, 390, 391
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, LEN_CALL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_audience_translate_1837_reopen.py::test_travel_tone_updates_this_round_summon_ledger`
- lines: 515, 518, 519, 523, 524, 536, 537, 542, 543, 544, 553
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_audience_translate_1837_reopen.py::test_urgent_summons_cannot_bypass_audience_admission`
- lines: 581, 583
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, INDEX_ACCESS, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_translation_once_1898.py::test_reopen_webgame_catches_up_pending_translation`
- lines: 59, 79, 80, 81, 85, 86
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_audience_travel_gating_670.py::test_cli_initial_selection_records_remote_summon_without_returning_minister`
- lines: 140, 142
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INITIAL_HINT, NONE_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_audience_travel_gating_670.py::test_multi_origin_fresh_closes_once_per_person_and_retries`
- lines: 564, 565, 569, 570, 571, 572, 589, 593, 600, 601, 602, 603, 605, 606, 607, 609
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 7}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_breach_plea_623.py::test_revoke_forecast_translation_input_carries_original_and_continuing_dossier`
- lines: 453, 458, 459, 470, 471, 481, 482, 483, 491, 494, 495, 499, 500, 501, 502
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_character_knowledge_489.py::test_knowledge_titles_restore_without_persistence_truncation`
- lines: 786
- disposition: `KEEP_SEED_SOURCE_ID`
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_NAME
- contract/why: 确定性种子 source_id / 知识事件身份字段

### `tests/test_character_knowledge_489.py::test_long_knowledge_bodies_survive_storage_without_brief_card_cap`
- lines: 529
- disposition: `KEEP_SEED_SOURCE_ID`
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_NAME, INDEX_ACCESS
- contract/why: 确定性种子 source_id / 知识事件身份字段

### `tests/test_character_knowledge_489.py::test_turn_zero_knowledge_is_role_specific_and_restores`
- lines: 112, 113, 114, 115, 116, 117, 118
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_SEED_SOURCE_ID': 2}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_chat_stream_failpaths_393.py::_assert_structured_llm_http`
- lines: 452, 453, 456, 457, 458, 459, 460, 461
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_TYPED_ERROR_SHAPE': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_ATTR, GEN_TEXT_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_chat_stream_failpaths_393.py::_assert_write_path_free`
- lines: 45, 59
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_NOT, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_config_max_attempts_override`
- lines: 906, 908, 909, 910
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_LLM_CONFIG_SURFACE': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_deterministic_4xx_no_retry`
- lines: 810, 812, 813, 814, 815, 816, 817
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_LLM_CONFIG_SURFACE': 1}）
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_halfstream_retry_replaces_temp_presentation`
- lines: 1010, 1012, 1014, 1016, 1027, 1035, 1048, 1049, 1050
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_TYPED_ERROR_SHAPE': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, GEN_TEXT_NAME, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_idle_budget_independent_per_attempt`
- lines: 968, 970, 973, 974, 975, 976, 977, 978, 979
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_provider_5xx_retries_status_preserved`
- lines: 776, 778, 781, 782, 783, 785, 786, 787, 788, 789
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_provider_default_502_not_washed_to_retryable`
- lines: 832, 834, 836, 837, 838, 840, 841
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_run_error_event_sse_system_layer_no_retry`
- lines: 664, 665, 667, 668, 670, 671, 672, 673, 675, 676
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_three_transient_exhausted_system_fail_then_resend`
- lines: 717, 719, 721, 722, 724, 726, 727, 728, 730, 731, 732, 734, 737, 741, 742, 743, 751, 754, 755, 756, 760, 761
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 8}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_chat_stream_failpaths_393.py::test_chat_stream_typed_429_preserved`
- lines: 867, 868, 869, 870, 872, 873, 874
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_chat_stream_failpaths_393.py::test_prologue_finally_does_not_release_foreign_gate_holder`
- lines: 203, 205, 206, 210, 212, 213, 217
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, EMPTY_COLLECTION, HELPER_CALL, INITIAL_HINT, _assert_write_path_free
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_cli_backend.py::_patch_backend`
- lines: 44
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_add_gate_llm_args_uses_gate_cli_runners`
- lines: 1275
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_agy_materials_mode_uses_material_cwd_and_print_argument`
- lines: 335, 336, 337, 338, 339
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_cli_backend.py::test_api_backend_streaming_emits_real_token_deltas`
- lines: 414, 427, 428
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_NAME, STR_LITERAL
- contract/why: CLI runner 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_backend_env_claude`
- lines: 226
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_clichat_call_cli_dispatch`
- lines: 803, 804, 805, 806, 807, 808, 810, 811, 812
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 2}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_clichat_call_cli_dispatches_new_runners`
- lines: 1168, 1170, 1172
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_clichat_invoke_error_traced_and_reraised`
- lines: 783, 784, 785
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_ATTR, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_codex_final_text_handles_item_completed_shape`
- lines: 472, 475, 478
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_cli_backend.py::test_codex_materials_dir_reaches_popen_cwd_and_readonly_argv`
- lines: 320, 321, 322, 323, 324, 325, 326
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_codex_streaming_runner_degrades_to_oneshot_final`
- lines: 378, 379, 381, 382
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, STR_LITERAL
- contract/why: CLI runner 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_enrich_army_parsed_and_normalized`
- lines: 172, 175, 176
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_enrich_backend_error_returns_empty_effects`
- lines: 190, 193
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_enrich_building_region_floor`
- lines: 184, 186
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_enrich_nondict_subfields_guarded`
- lines: 197, 203
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_enrich_trace_records_actual_backend`
- lines: 208, 212
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_extract_secret_order_preserves_long_title_without_formal_cap`
- lines: 72, 78, 82, 83
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_cli_backend.py::test_gate_evidence_config_honest_cli_and_api`
- lines: 1252, 1253, 1254, 1262, 1263, 1264
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_gate_llm_config_api_from_args_not_persisted_shape`
- lines: 1214, 1215, 1216, 1217, 1218
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_gate_llm_config_api_from_env`
- lines: 1226
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_gate_llm_config_cli_channel`
- lines: 1199, 1200, 1201
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_login_shell_path_uses_printenv_not_dollar_path`
- lines: 654, 656, 657, 658, 659
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_luna_shaped_stream_keeps_content_when_reasoning_deltas_interleave`
- lines: 447, 466, 467, 468
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_FIXTURE_OR_SEED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_NAME, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_materials_dir_reaches_popen_cwd_and_readonly_argv`
- lines: 298, 299, 300, 301, 302, 303, 304, 305, 307, 308, 309, 310
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_office_inference_llm_call_is_traced`
- lines: 991, 994, 995
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare`
- lines: 562, 573, 574
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_agy_success_single_subprocess`
- lines: 851, 852, 853
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_backend.py::test_run_backend_for_config_dispatches_new_runners`
- lines: 1145, 1153, 1154, 1155, 1157
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_backend_for_config_passes_reasoning_strength_to_codex`
- lines: 963, 969
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_run_backend_for_config_traces_every_call`
- lines: 945, 947, 948, 950, 951, 952
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_backend_for_config_traces_on_backend_error`
- lines: 979, 982, 983
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_run_backend_infers_trace_tag_from_prompt`
- lines: 933, 938, 939
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_cli_backend.py::test_run_claude_maps_reasoning_strength_to_thinking_tokens`
- lines: 531, 532
- disposition: `KEEP_FIXTURE_ECHO` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_backend.py::test_run_claude_off_reasoning_uses_explicit_minimum_tokens`
- lines: 539, 540
- disposition: `KEEP_FIXTURE_ECHO` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_backend.py::test_run_claude_stdout_only`
- lines: 286, 287, 288, 289
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL
- contract/why: CLI runner 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_codex_flags_and_stdout`
- lines: 347, 348, 349, 350
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_codex_maps_reasoning_strength_to_native_effort`
- lines: 513, 514
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_codex_reasoning_env_optional`
- lines: 504, 505
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_IN, INDEX_ACCESS, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_codex_stdout_empty_fallback`
- lines: 524
- disposition: `KEEP_FIXTURE_ECHO`
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_backend.py::test_run_cursor_flags_and_stdout`
- lines: 1065, 1067, 1068, 1069, 1070, 1071, 1072
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_grok_flags_effort_and_plain`
- lines: 1092, 1094, 1095, 1096, 1098
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_kimi_prompt_flag_no_yolo_stdout_only`
- lines: 1079, 1081, 1082, 1083, 1085
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_pi_flags_thinking_and_stdout`
- lines: 1108, 1110, 1111, 1112, 1114, 1115, 1116, 1117
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_run_runner_accepts_config_model`
- lines: 494, 495, 496
- disposition: `KEEP_FIXTURE_ECHO` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_backend.py::test_secret_content_assembly_is_emperor_plus_extractor_only`
- lines: 118, 125, 126
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_NAME, STR_LITERAL
- contract/why: CLI runner 装配/stdout 夹具契约

### `tests/test_cli_backend.py::test_secret_exclusion_extracts_people_and_offices`
- lines: 63, 65, 66, 67
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS
- contract/why: 索引字段外部结果

### `tests/test_cli_backend.py::test_secret_extract_traces_exactly_once`
- lines: 1002, 1005
- disposition: `KEEP_TRACE_ONCE` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, LEN_CALL, NUM_LITERAL
- contract/why: 密令提取 trace 条数==1；canned JSON 为 runner 替身返回值非叙事盯文

### `tests/test_cli_model_choices.py::test_default_label_reflects_env_override`
- lines: 38, 39
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_model_choices.py::test_menu_status_exposes_raw_cli_model_saved_default`
- lines: 80, 81
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_play_turn.py::test_play_turn_hitl_advancement_ends_turn`
- lines: 680, 681, 692, 693, 694
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_cli_play_turn.py::test_play_turn_reports_secret_order_failure_when_settlement_aborts`
- lines: 561, 562, 563
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_play_turn.py::test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn`
- lines: 470, 471
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_play_turn.py::test_review_issue_reaches_staged_directive_default_approval`
- lines: 148, 149
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_play_turn.py::test_terminal_failure_printer_preserves_zero_id`
- lines: 392
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_play_turn.py::test_terminal_minister_chat_accepts_retry_reply_command`
- lines: 609, 610, 623, 628, 629, 634, 638, 639, 641, 642
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_FIELD': 2, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL, WAIT_UNTIL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_cli_runner_error_typed_1299.py::test_clichat_normal_reply_still_returns`
- lines: 70
- disposition: `KEEP_FIXTURE_ECHO`
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文

### `tests/test_cli_runner_error_typed_1299.py::test_clichat_runner_exit_raises_typed_llm_unavailable`
- lines: 48, 49, 50
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_ATTR
- contract/why: CLI runner 装配/stdout 夹具契约

### `tests/test_cli_runner_error_typed_1299.py::test_extract_agent_text_normal_reply_passes`
- lines: 101
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_runner_error_typed_1299.py::test_extract_agent_text_plain_string_still_works`
- lines: 116
- disposition: `KEEP_CLI_ARGV_OR_ASSEMBLY`
- tags: ASSERT, ASSERT_EQ, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_transport_1465.py::test_cli_chat_stream_deterministic_failure_runs_once`
- lines: 226, 228, 230, 232, 233
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_cli_transport_1465.py::test_cli_chat_stream_three_transient_exhausted_system_fail_night_open_then_resend`
- lines: 183, 185, 187, 189, 192, 197, 198, 200, 202, 203, 210, 212, 213, 214
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 5, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_cli_transport_1465.py::test_cli_chat_stream_two_transient_then_success_three_attempts`
- lines: 146, 148, 150, 152, 155, 156
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_cli_transport_1465.py::test_cli_process_idle_over_budget_dies_then_retry_succeeds`
- lines: 343, 345, 348, 349, 350, 352, 354, 355, 356
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_cli_transport_1465.py::test_cli_process_keeps_streaming_past_old_300s_wall`
- lines: 292, 294, 296, 297, 298, 299, 301, 302
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 顺序/大小外部可比结果（非内部方向 oracle 默许）

### `tests/test_cli_transport_1465.py::test_cli_stdin_write_failure_fails_loudly_not_as_empty_output_retry`
- lines: 257, 259, 262, 263, 264
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_CLI_ARGV_OR_ASSEMBLY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: CLI 装配/stdout 夹具契约

### `tests/test_court_break_player_lock_1727.py::web_game`
- lines: 49
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_declaration_dispatch_1835.py::test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item`
- lines: 203, 206, 213, 214, 215, 216, 219, 220, 228, 229, 230, 231
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_declaration_dispatch_1835.py::test_staged_declaration_discard_and_idempotent_settle_in_decree_order`
- lines: 727, 732, 739, 740, 741, 742, 743, 747, 753, 754, 755, 756, 760, 762, 766
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 5, 'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_declaration_dispatch_1835.py::test_unknown_top_level_section_is_rejected_durably_without_dropping_sibling`
- lines: 248, 249, 255, 256, 257
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_decree_dossiers_571.py::test_allocation_rejects_unknown_economy_account_before_dossier_birth`
- lines: 1576, 1580
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, GEN_TEXT_HINT, NONE_LITERAL, STR_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_decree_dossiers_571.py::test_batch_draft_extraction_preserves_each_mechanical_payload`
- lines: 1778, 1785, 1786, 1787, 1789, 1790, 1791, 1792, 1793
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_FISCAL_ORACLE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_decree_dossiers_571.py::test_cli_edit_replaces_text_and_mechanics_before_promulgation`
- lines: 1239, 1245, 1246, 1247, 1252, 1253, 1254, 1260, 1261
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 结构化字段或 harness 契约（非自由文本哨兵）

### `tests/test_decree_dossiers_571.py::test_draft_extraction_does_not_capture_acting_appointment`
- lines: 1737, 1747, 1748, 1750
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_decree_dossiers_571.py::test_incomplete_mechanical_directive_is_rejected_instead_of_retyped`
- lines: 1654, 1658, 1659
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_reaches_structured_dossier`
- lines: 999, 1011, 1017, 1018, 1019, 1021, 1023, 1025, 1026, 1034, 1037, 1038, 1040, 1044, 1046
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_malformed_roster`
- lines: 1067, 1081, 1083, 1084, 1085
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_decree_dossiers_571.py::test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes`
- lines: 1106, 1122, 1123, 1124
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_decree_dossiers_571.py::test_mechanical_directive_missing_target_fails_loudly_at_real_entry`
- lines: 1678, 1682, 1683
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_decree_dossiers_571.py::test_pending_directive_only_enters_settlement_after_final_approval`
- lines: 308, 309, 311, 312, 313, 334, 335, 336, 339, 340, 346
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_decree_dossiers_571.py::test_secret_authorization_rejects_missing_assignee_without_grant`
- lines: 2054, 2058, 2059
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_decree_dossiers_571.py::test_session_manual_directive_keeps_structured_action_at_submission`
- lines: 1439, 1463, 1469, 1470, 1471, 1472
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_decree_forecast_1861.py::_drain_legs`
- lines: 123
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_decree_forecast_1861.py::test_held_rejudgments_overlap_instead_of_waiting_in_one_worker`
- lines: 501, 502, 503, 508, 512, 513, 519, 520, 521, 522, 530, 531, 538, 539, 541, 546
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_FISCAL_ORACLE': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_decree_forecast_1861.py::test_repeat_scene_approval_does_not_rerun_exhausted_forecast`
- lines: 385, 386, 396, 397, 398, 399
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_decree_forecast_1861.py::test_restored_directive_forecast_uses_its_approved_night`
- lines: 427, 428, 432, 438, 443, 444, 445
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_decree_forecast_1861.py::test_same_local_ids_on_two_saves_both_stage`
- lines: 568, 569, 570, 588, 589, 592, 601, 602, 604
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_decree_forecast_1861.py::test_scene_chat_approval_forecasts_each_decree_without_visible_effect`
- lines: 198, 203, 214, 215, 219, 231, 239, 247, 249, 250, 251, 252, 253, 254, 255, 256, 260, 261, 262, 267, 272, 274, 275, 278, 281, 282, 292, 293
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6, 'KEEP_LLM_CONFIG_SURFACE': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, INITIAL_HINT
- contract/why: 索引字段外部结果

### `tests/test_decree_forecast_1861.py::test_scene_chat_rejection_is_staged_for_later_rescript_not_shown_at_night`
- lines: 335, 336, 347, 348, 349, 350, 351, 352, 353
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, EMPTY_COLLECTION, GEN_TEXT_ATTR, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_dossier_reported_progress_619.py::test_execution_surface_dossier_can_record_and_list_full_history`
- lines: 90, 93, 94, 95, 98, 99, 100, 107, 111, 118, 119, 120
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, GEN_TEXT_NAME, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_dossier_reported_progress_619.py::test_origin_namespace_minimum_closed_set_and_open_append`
- lines: 192, 194, 195, 196
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_IN, ASSERT_ORDER, GEN_TEXT_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_draft_admission_resubmit_1769.py::_queue_backend`
- lines: 138, 144
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_draft_admission_resubmit_1769.py::test_draft_admission_exhaust_keeps_draft_and_advances`
- lines: 327, 328, 330, 331, 334, 335, 336, 338, 339, 342, 344, 349, 354, 363, 364, 365, 366, 367, 368
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 9}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_draft_admission_resubmit_1769.py::test_draft_admission_mixed_good_and_bad_independent`
- lines: 401, 404, 405, 407, 408, 409, 410, 411, 413, 415
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, GEN_TEXT_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_draft_admission_resubmit_1769.py::test_exhaust_zero_dossier_system_simulation_no_decree`
- lines: 594, 595, 596, 598, 601, 602, 603, 605
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_draft_admission_resubmit_1769.py::test_pending_product_error_enters_resubmit_seam_not_softlock`
- lines: 544, 549, 550, 551, 554, 555, 556, 557
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_draft_admission_resubmit_1769.py::test_resubmit_non_intent_keeps_original_payload_no_special_decree`
- lines: 496, 499, 500, 503, 505, 506, 510, 511, 512
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, GEN_TEXT_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_enrich_list_guards.py::test_enrich_buildings_non_list_no_crash`
- lines: 23, 25, 26
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_enter_settlement_period_1235.py::_fake_settlement_llm`
- lines: 61, 74
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_enter_settlement_period_1235.py::test_noncreator_exit_must_not_clear_owner_during_gatefree`
- lines: 718, 719, 720, 746, 747, 748, 749, 757, 758, 759, 760, 761, 762, 764, 765, 766
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 7}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, BOOL_LITERAL, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_enter_settlement_period_1235.py::web_game`
- lines: 87
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_error_pack.py::test_attempt_derived_from_existing_dirs`
- lines: 32, 33, 34
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_error_pack.py::test_attempt_never_overwrites_existing_pack`
- lines: 86, 87
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, INITIAL_HINT, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_error_pack.py::test_next_attempt_skips_malformed_and_foreign_entries`
- lines: 163
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_event_trigger_gate.py::test_mao_event_effect_uses_unified_person_change_key`
- lines: 811, 812, 813
- disposition: `KEEP_FIXTURE_ECHO` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, STR_LITERAL
- contract/why: 中文子串——按夹具回传/结构化字段审；非模板哨兵则保留

### `tests/test_event_trigger_gate.py::test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome`
- lines: 1405, 1406, 1407, 1408, 1409, 1410, 1411, 1412, 1413
- disposition: `KEEP_P4_NEGATIVE` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_FIXTURE_ECHO': 3}）
- tags: ASSERT, ASSERT_IN, INDEX_ACCESS, STR_LITERAL
- contract/why: 必要负向：禁泄露片段

### `tests/test_execution_pressure_654.py::test_path2_pending_bad_roster_stays_draft_on_ensure_batch`
- lines: 552, 553, 556, 560, 561
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_execution_pressure_654.py::test_path3_locality_fail_keeps_draft_no_text_in_rejection`
- lines: 594, 595, 597, 598, 604, 607, 608, 611, 612
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_P4_NEGATIVE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_executor_routing_721.py::test_directive_routing_rejection_rolls_back_with_outer_owner`
- lines: 398, 401, 407, 410
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_executor_routing_721.py::test_pending_routing_rejection_lands_on_ensure_batch_seam`
- lines: 319, 322, 325, 328, 333, 334, 337, 340, 343, 346, 347
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_fiscal_levy_effect.py::_install_liao_month_stubs`
- lines: 1290, 1291, 1292, 1293, 1297
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 2}）
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_fiscal_levy_effect.py::test_fiscal_levy_events_are_not_in_model_candidate_pool`
- lines: 566, 567, 568, 570
- disposition: `KEEP_P4_NEGATIVE` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: P4 负向：皇帝可见文本不得裸数值

### `tests/test_fiscal_levy_effect.py::test_liao_levy_rise_approved_lands_on_no_edict_advance_before_fiscal_tick`
- lines: 161, 176, 177, 178, 180, 181
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_gazette_author_1862.py::_session`
- lines: 53
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances`
- lines: 148, 188, 350, 355, 356, 360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370, 371, 374, 375, 377, 379, 380, 382, 384, 385, 386, 387, 388, 389, 393, 397, 398, 400, 401, 404, 408, 412, 425, 426, 428 …(+7)
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 11, 'KEEP_IO_BOUNDARY': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_gazette_author_1862.py::test_author_waits_until_rescript_is_done`
- lines: 75, 77, 83, 84
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_gazette_author_1862.py::test_gazette_failure_retries_report_only`
- lines: 484, 485, 492, 493, 494, 496, 499, 500, 501, 502, 506, 507
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_grant_reconciliation_567.py::test_web_state_payload_after_settle`
- lines: 357, 375, 376, 377, 378, 380, 382, 383
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_highlight_judge_544.py::test_chat_nonstream_folds_judge_within_timeout`
- lines: 290, 296, 298, 306, 307
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_highlight_judge_544.py::test_chat_nonstream_timeout_returns_reply_without_highlights`
- lines: 341, 345, 348, 350, 354, 356
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, ASSERT_ORDER, BOUNDARY_STUB, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_highlight_judge_544.py::test_chat_stream_done_before_highlights_and_degrade`
- lines: 211, 215, 216, 217, 218, 219, 221, 224
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_highlight_judge_544.py::test_chat_stream_slow_success_attaches_after_done`
- lines: 245, 260, 261, 262, 264, 265, 267, 268, 271
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_FIXTURE_OR_SEED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 顺序/大小外部可比结果（非内部方向 oracle 默许）

### `tests/test_llm_channel_config.py::test_agent_factories_omit_max_tokens_on_param_surface`
- lines: 859, 864, 865, 882, 885, 886
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_error_status_raises`
- lines: 656, 659
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_none_passes`
- lines: 633, 635
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, LEN_CALL, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_empty_content_passes`
- lines: 610, 613
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, LEN_CALL, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_error_status_nonempty_content_raises`
- lines: 677, 681
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_api_smoke_omits_max_tokens`
- lines: 587, 590
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_cli_channel_failure_raises`
- lines: 512
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_legacy_env_only_failure_raises`
- lines: 552
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_respects_api_channel_over_backend_env`
- lines: 462, 474, 475
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_LLM_CONFIG_SURFACE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IN, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_smokes_cli_channel_without_backend_env`
- lines: 488, 502, 503
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_llm_channel_config.py::test_verify_llm_available_smokes_legacy_env_only_backend`
- lines: 539, 542
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_manual_directive_institution_normalize_1279.py::_mock_draft_intent`
- lines: 39
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_manual_directive_locality_1685.py::test_manual_directive_region_assembly_writes_single_and_advances`
- lines: 37, 39, 47, 52, 53, 58, 60, 61, 63, 64
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_mechanical_tail_1845.py::_archive_and_stub_world`
- lines: 32, 33
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_mechanical_tail_1845.py::test_advance_schedules_mechanical_tail_after_front_month_advance`
- lines: 76, 84, 85, 86, 87, 91, 92, 95
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers`
- lines: 460, 461, 467, 468, 483, 492, 493, 495, 497, 499, 501, 503, 504, 505, 510
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_FIXTURE_OR_SEED': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_mechanical_tail_1845.py::test_ending_summary_runs_in_mechanical_tail_after_advance`
- lines: 366, 378, 409, 410, 411, 412, 416, 417, 418, 419, 427, 428, 429, 430, 432, 435, 436, 438, 439, 440, 442, 443, 444
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 9}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_exhausted_mechanical_tail_fails_and_blocks_next_month`
- lines: 162, 171, 176, 178
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_mechanical_tail_missing_llm_config_surfaces_retry`
- lines: 541, 543, 545, 546, 547, 548, 550, 556, 562, 564, 566, 568, 569
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 5, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_non_exhausted_tail_failure_stays_pending_and_retries`
- lines: 311, 312, 313, 316, 317, 322, 323, 332, 333, 335, 338, 339, 340, 342, 343, 345, 346, 347, 348, 349
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 9}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_real_brew_failure_reaches_tail_failure_and_retry`
- lines: 203, 209, 215, 216, 217, 220, 223, 227, 228
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_reopen_resumes_incomplete_mechanical_tail`
- lines: 118, 123, 128, 146, 147
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_mechanical_tail_1845.py::test_web_barrier_resumes_pending_tail_before_join`
- lines: 257, 275, 280
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_menu_continue_stream_1195.py::test_menu_continue_streams_error_when_llm_unavailable`
- lines: 93, 94, 96, 97, 98
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_menu_continue_stream_1195.py::test_menu_continue_streams_stage_labels_then_done_state`
- lines: 42, 56, 60, 61, 64, 66, 67, 70, 71, 74, 75, 76
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_continue_stream_1195.py::test_stale_continue_worker_does_not_publish_after_exit`
- lines: 120, 146, 147, 151, 152, 154, 155, 156, 157
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_continue_stream_1195.py::test_stale_continue_worker_does_not_publish_after_new_game`
- lines: 172, 184, 210, 212, 216, 217, 218, 219, 220, 221
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::_capture_real_drain_threads`
- lines: 31
- disposition: `KEEP_THREAD_FACTORY_APPLIED`
- tags: BOUNDARY_STUB
- contract/why: 归档三负向已改 make_thread+join；本行属已落 FIX 的接缝/同步，现作 KEEP

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_move_failure_keeps_wal_and_shm`
- lines: 135, 137, 141, 142, 143, 144, 145, 146
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_COMPLETION_SYNC': 1, 'KEEP_FAILURE_TRAVERSED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INITIAL_HINT, NONE_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_moves_wal_and_shm_with_main_db`
- lines: 173, 175, 178, 180, 181, 182, 183, 184, 185
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_THREAD_FACTORY_APPLIED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, WAIT_UNTIL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_rolls_back_main_db_when_wal_move_fails`
- lines: 221, 223, 227, 228, 229, 230, 231, 232
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_COMPLETION_SYNC': 1, 'KEEP_FAILURE_TRAVERSED': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INITIAL_HINT, NONE_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_skips_move_when_session_close_fails`
- lines: 263, 265, 269, 270, 271, 272, 273
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3, 'KEEP_FAILURE_TRAVERSED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, EMPTY_COLLECTION, INITIAL_HINT, NONE_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_drain_rejects_late_pending_write_before_gate_acquire`
- lines: 537, 543, 544, 546, 550, 551
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_COMPLETION_SYNC': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, WAIT_UNTIL
- contract/why: 存在性/空值外部字段契约

### `tests/test_menu_lifecycle_drain_396.py::test_drain_waits_for_queued_chat_stream_not_just_gate_holder`
- lines: 483, 484, 487, 492, 506, 515, 516, 517, 519
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_NONBLOCKING_RETURN': 1, 'KEEP_COMPLETION_SYNC': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_menu_lifecycle_drain_396.py::test_exit_to_menu_returns_before_delayed_close_drains`
- lines: 47, 54, 55, 56, 60, 61
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_NONBLOCKING_RETURN': 1, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, EMPTY_COLLECTION, INITIAL_HINT, NONE_LITERAL, SUSPECT_INITIAL, WAIT_UNTIL
- contract/why: 存在性/空值外部字段契约

### `tests/test_menu_lifecycle_drain_396.py::test_new_game_returns_before_delayed_close_drains`
- lines: 80, 92, 93, 94, 98, 99
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_NONBLOCKING_RETURN': 1, 'KEEP_THREAD_FACTORY_APPLIED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, EMPTY_COLLECTION, INITIAL_HINT, NONE_LITERAL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_new_game_switches_db_path_when_web_game_is_none`
- lines: 622, 623, 626, 629, 631, 634, 638
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_COMPLETION_SYNC': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL, WAIT_UNTIL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_new_game_switches_db_path_when_web_game_none_and_no_env`
- lines: 653, 654, 656, 657, 659
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_shutdown_waits_for_drain_before_returning_or_killing`
- lines: 291, 300, 301, 302, 307, 308
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_NONBLOCKING_RETURN': 1, 'KEEP_COMPLETION_SYNC': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, EMPTY_COLLECTION, INITIAL_HINT, SUSPECT_INITIAL, WAIT_UNTIL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_menu_lifecycle_drain_396.py::test_spawn_pending_write_thread_start_failure_releases_ownership`
- lines: 591, 594, 595
- disposition: `KEEP_THREAD_CAPTURE` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, BOUNDARY_STUB, WAIT_UNTIL
- contract/why: 捕获真实 threading.Thread 引用以便 join；不替 worker 行为

### `tests/test_minister_chat_timeout.py::test_minister_chat_idle_death_time_follows_settings_threshold`
- lines: 85, 87, 90, 91, 92, 96, 98
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_month_call_recovery_1846.py::test_code_exception_during_world_commit_keeps_phase_and_settled_edicts`
- lines: 479, 486, 493, 494, 495, 496, 497, 502, 503, 504, 505
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_edict_settle_code_exception_stops_at_month_entry_and_retries_once`
- lines: 618, 619, 640, 641, 642, 643, 644, 645, 646, 648, 649, 652, 654, 655
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase`
- lines: 675, 676, 702, 703, 704, 705, 706, 708, 709, 710, 713, 715, 716
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, EMPTY_COLLECTION, GEN_TEXT_ATTR, INDEX_ACCESS, LEN_CALL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_escape_hatch_discards_world_segment_only_on_second_player_retry`
- lines: 361, 362, 371, 372, 373, 381, 382, 383, 384, 389, 390, 391, 392, 393, 394
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 6}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_forecast_exhaustion_does_not_overwrite_prior_ending`
- lines: 187, 197, 198, 199, 200, 204, 205, 206, 207
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_month_entry_world_push_follows_audience_transport_policy`
- lines: 124, 125, 127, 128, 131, 132, 133, 138, 139, 140, 141
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_LLM_CONFIG_SURFACE': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, EMPTY_COLLECTION, GEN_TEXT_HINT, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_settlement_recovery_projects_month_call_failure`
- lines: 409, 422, 429, 431, 432, 433, 434, 439, 451, 452, 453, 457
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 3, 'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_world_commit_failure_after_alongside_retries_uncommitted_segment`
- lines: 539, 540, 565, 566, 567, 568, 569, 573, 574, 575, 579, 580, 581, 584, 585, 586, 588, 589, 590, 591
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_world_text_exhaustion_stops_month_keeps_settled_edicts`
- lines: 229, 236, 237, 238, 240, 242, 243, 248, 249, 250, 251, 252
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_call_recovery_1846.py::test_world_translate_exhaustion_keeps_text_resume_retries_translate_only`
- lines: 284, 285, 295, 296, 297, 298, 300, 301, 302, 308, 309, 316, 317, 318, 319, 320
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::_prepare_player_month`
- lines: 57, 61, 66
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1843.py::test_finish_rescript_phase2_stays_settling_until_advanced`
- lines: 260, 264, 265
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::test_missing_world_model_stops_before_world_commit`
- lines: 507, 508, 509, 510, 511
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2, 'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::test_month_chain_lands_specialized_facts_before_due_and_gazette`
- lines: 700, 701, 702, 706, 713, 715, 716, 717, 721, 722
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_month_chain_1843.py::test_month_drift_settles_due_secret_and_records_inertia_rejection`
- lines: 536, 537, 549, 550, 555, 557, 558
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_month_chain_1843.py::test_player_entry_recovers_ending_after_interrupted_segment`
- lines: 314, 315, 322, 323, 324, 327, 329, 330, 339, 340, 341, 342
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::test_player_recovery_uses_resolve_context_decree_not_ready_delta`
- lines: 229, 233, 234, 236, 237, 239, 240
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_month_chain_1843.py::test_questions_hold_rescript_and_gazette_is_required_before_advance`
- lines: 158, 161, 165, 166, 167, 168, 169, 170, 183, 184, 185, 198, 199, 201, 202, 203, 211, 212, 214, 215
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::test_unforecast_edict_is_caught_up_once_and_crash_does_not_double_charge`
- lines: 115, 122, 123, 124, 125, 130, 131, 132, 135
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_FIXTURE_ECHO': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1843.py::test_world_segment_persists_declaration_ending_with_commit`
- lines: 271, 283, 284, 286
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS
- contract/why: 索引字段外部结果

### `tests/test_month_chain_1843.py::test_world_segment_reads_material_directory`
- lines: 600, 605, 607, 608, 609, 610, 611, 613, 614, 617, 618, 619
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_month_chain_1847.py::_resolve_with_emperor_fate`
- lines: 1105, 1106, 1107, 1108
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 2}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_chain_1847.py::test_answering_triad_applies_and_releases_rescript_gate`
- lines: 191, 192, 214, 215, 216, 219, 220
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_month_chain_1847.py::test_answering_world_question_resumes_suffix_then_gazette`
- lines: 232, 235, 252, 253, 270, 271, 272, 274, 275, 278, 279, 281
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_FIELD': 3, 'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_cross_month_pending_draft_opens_rescript_desk`
- lines: 606, 607, 614, 615, 616, 617, 618, 620, 621
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2, 'KEEP_FIXTURE_OR_SEED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_decree_continuation_ending_ends_the_month`
- lines: 1074, 1075, 1076, 1077, 1078, 1089, 1090, 1091, 1092
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect`
- lines: 678, 680, 681, 700, 701, 704, 705, 706, 708, 709, 710, 713, 716, 722, 723, 729
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_FIXTURE_OR_SEED': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_decree_continuation_survives_llm_exhaustion_then_retries`
- lines: 399, 400, 401, 408, 426, 427, 430, 431, 435, 436, 439, 440
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, BOUNDARY_STUB, INITIAL_HINT, LEN_CALL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_decree_forecast_keeps_every_question_and_translates_prefix_once`
- lines: 758, 763, 767, 775, 776, 777, 781, 782
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_decree_question_and_world_question_share_one_desk`
- lines: 463, 467, 474, 476
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_FIXTURE_OR_SEED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_NAME
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_chain_1847.py::test_decree_question_continuation_idempotent_on_same_turn_reentry`
- lines: 320, 321, 322, 329, 345, 346, 350, 351, 352
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_drift_sees_effects_landed_after_answers`
- lines: 1162, 1165, 1168, 1172, 1173, 1183, 1186
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_fatal_midzhi_rejection_hides_force_option`
- lines: 954, 955, 963, 965, 967
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_chain_1847.py::test_midzhi_promulgation_records_authority_cost_once`
- lines: 991, 999, 1004
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_month_chain_1847.py::test_midzhi_verdict_and_metadata_roll_back_together`
- lines: 1024, 1029, 1031, 1035
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_chain_1847.py::test_missing_model_does_not_mark_world_continued`
- lines: 550, 553, 567, 569, 570, 571, 573, 580, 581
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_missing_model_keeps_decree_question_until_retry`
- lines: 512, 513, 527, 528, 529, 537, 540, 541, 542
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_prior_month_answered_rescript_does_not_block_or_reappear`
- lines: 139, 140, 146, 147, 148
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_question_note_only_is_kept_and_other_decisions_still_require_label`
- lines: 817, 818, 819, 836, 837, 838, 847, 848, 849, 871, 872
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_step_4a_crash_recovery_resumes_without_re_running_supply`
- lines: 1487, 1488, 1489, 1511, 1513, 1515, 1516, 1520, 1521, 1523, 1525
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_month_chain_1847.py::test_step_4a_deferred_disclosure_sees_fresh_0058_progress`
- lines: 1361, 1362, 1363, 1368, 1376, 1377, 1379, 1381
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_step_4a_incomplete_0058_report_fails_loud_and_retry_restarts`
- lines: 1431, 1432, 1433, 1440, 1442, 1444, 1445, 1449, 1450, 1451, 1452
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, GEN_TEXT_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_step_4a_missing_covert_fidelity_records_inline_rejection`
- lines: 1625, 1626, 1627, 1633, 1636, 1637, 1638, 1639, 1640, 1641, 1642, 1646, 1648, 1649, 1655, 1659, 1660, 1662, 1663, 1664, 1665, 1666, 1672, 1673, 1674, 1676, 1677, 1678, 1684, 1685, 1689
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 4, 'KEEP_STRUCTURED_FIELD': 9, 'KEEP_P4_NEGATIVE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_step_4a_no_eligible_objects_skips_run_and_completes`
- lines: 1196, 1197, 1202, 1207, 1209
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_step_4a_non_validation_failure_keeps_product_on_retry`
- lines: 1845, 1846, 1847, 1854, 1856, 1857, 1858, 1861, 1862, 1863
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 4, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input`
- lines: 1273, 1276, 1279, 1280, 1287, 1288, 1295, 1298, 1299, 1300, 1306, 1313, 1317, 1319
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_step_4a_rescript_path_feeds_landed_not_assembled_effects`
- lines: 2162, 2165, 2168, 2169, 2175, 2180, 2182, 2183, 2184, 2189, 2195, 2196
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 3, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_step_4a_settles_due_secret_order`
- lines: 1916, 1917, 1918, 1923, 1926, 1928, 1929
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_month_chain_1847.py::test_this_turn_rejection_opens_triad_on_same_desk`
- lines: 160, 165, 166, 173, 175, 176, 177
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_world_question_opens_rescript_desk_and_awaits`
- lines: 74, 77, 84, 85, 86, 87, 88, 90, 91, 92, 93
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_chain_1847.py::test_world_segment_multiple_questions_share_one_desk`
- lines: 100, 104, 111, 113
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_FIXTURE_OR_SEED': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, GEN_TEXT_NAME
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_loop_tracer_1468.py::_play_one_month`
- lines: 313, 318, 324, 325, 329, 341, 342, 352, 361, 369, 375
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, GEN_TEXT_NAME, HELPER_CALL, INDEX_ACCESS, INITIAL_HINT, LEN_CALL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_month_loop_tracer_1468.py::_stub_outer_llm_seams`
- lines: 63, 87, 91, 95
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_month_translate_1840.py::test_unparseable_month_segment_does_not_stage_or_commit`
- lines: 483, 488, 491
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_new_game_dependency_mismatch_1721.py::test_new_game_stale_agno_returns_typed_dependency_facts`
- lines: 70, 72, 75, 76, 78, 79, 80
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_new_game_smoke.py::fresh_game_dir`
- lines: 49, 57
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_new_game_write_path_1749.py::_wait_spawns`
- lines: 108, 111
- disposition: `KEEP_COMPLETION_SYNC` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_IS, BOOL_LITERAL, INITIAL_OR_ATTEMPT, WAIT_UNTIL
- contract/why: len(spawns) 仅取 completion 句柄；随后 done.wait()+close_ok+外部文件证明完成/失败

### `tests/test_new_game_write_path_1749.py::test_exit_close_fail_blocks_archive_on_real_new_game`
- lines: 558, 560, 575, 576, 577, 580, 581, 584, 585, 587, 589, 590, 591, 595, 597
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_COMPLETION_SYNC': 2, 'KEEP_STRUCTURED_OR_HARNESS': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, EMPTY_COLLECTION, GEN_TEXT_NAME, HELPER_CALL, INDEX_ACCESS, INITIAL_OR_ATTEMPT
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_new_game_write_path_1749.py::test_new_game_write_path_direct_and_via_exit`
- lines: 292, 293, 295, 304, 305, 307, 309, 312, 314, 315, 318, 320, 324, 325, 326, 328, 331, 332, 333, 340, 342, 351, 352, 354, 357, 358, 360, 363, 365, 370, 371, 372, 382, 383, 384, 388, 392, 393, 396, 398 …(+12)
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 20, 'KEEP_COMPLETION_SYNC': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, HELPER_CALL, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_no_edict_full_settlement_1274.py::test_no_edict_advance_runs_full_settlement_chain`
- lines: 52, 53, 54, 55, 56, 58, 59, 72
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, GEN_TEXT_HINT, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_office_inference.py::test_api_channel_unknown_office_does_not_use_backend_env`
- lines: 66, 74, 75
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_office_inference.py::test_api_channel_unknown_office_ignores_cli_derived_cache`
- lines: 112, 122, 126, 134, 135
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 2}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_office_inference.py::test_fresh_gamesession_start_makes_no_backend_calls`
- lines: 201, 216
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_office_inference.py::test_fresh_seed_makes_no_office_type_backend_calls`
- lines: 168, 178, 187, 188, 189
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_office_inference.py::test_runtime_cli_unknown_office_uses_configured_runner_without_env`
- lines: 88, 99, 100, 101
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_CLI_ARGV_OR_ASSEMBLY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_office_inference.py::test_use_llm_false_skips_backend_and_trusts_content_type`
- lines: 145, 151, 154, 155, 157, 158
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_p4_guard_new_surfaces_547.py::_assert_no_character_axis_keys`
- lines: 39
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_NOT, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pay_order_override_653.py::_capture_override_decree`
- lines: 1619, 1623, 1624, 1625, 1632, 1633
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_pay_order_override_extraction_653.py::test_multi_pay_order_capture_preserves_reverse_non_tied_priorities`
- lines: 90, 95, 96
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_pay_order_override_extraction_653.py::test_relative_deadline_cannot_stage_llm_computed_expired_turn`
- lines: 50
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_pay_order_override_extraction_653.py::test_single_pay_order_capture_grounds_relative_deadline_at_current_turn`
- lines: 25, 29, 43, 44
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_pay_order_override_extraction_653.py::test_single_pay_order_capture_rejects_missing_entries`
- lines: 67
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_pihong_dossier_1490.py::_1778_generate`
- lines: 2843
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_pihong_dossier_1490.py::_657_install_real_phase2_llm_boundary`
- lines: 75
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_pihong_dossier_1490.py::test_1621_http_follow_draft_uses_catalog_army_id`
- lines: 1421, 1429, 1431, 1455, 1456, 1457, 1459
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_ATTR, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_pihong_dossier_1490.py::test_1625_inflight_phase2_does_not_advertise_resume`
- lines: 2262, 2263, 2286, 2287, 2288, 2289, 2311, 2312, 2313, 2314, 2317, 2318, 2320, 2321
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, EMPTY_COLLECTION, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_1625_phase1_publication_projects_only_coherent_recovery_tuples`
- lines: 2234, 2235, 2236, 2237, 2238, 2240, 2241, 2242, 2243
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOOL_LITERAL, EMPTY_COLLECTION, INDEX_ACCESS, INITIAL_HINT
- contract/why: 索引字段外部结果

### `tests/test_pihong_dossier_1490.py::test_1778_missing_roster_heals_then_error_pack_without_assigning_anyone`
- lines: 2984, 2993, 2996, 2998, 3003, 3004, 3007, 3008, 3013, 3015, 3016, 3019
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 4, 'KEEP_RESCRIPT_STRUCTURE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_657_preferred_hitl_choice_urgent_follow_draft_ordinary_intact`
- lines: 1959, 1960, 1961, 1962, 1965, 1966, 1967, 1968, 1969
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 2, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 批红/疗伤结构化字段与 draft 状态

### `tests/test_pihong_dossier_1490.py::test_657_return_revise_round_prior_and_clear_anchor`
- lines: 852, 853, 860, 861, 862, 863, 865, 867, 869, 873, 874, 878, 879, 887, 892, 896, 897, 898
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 3, 'KEEP_STRUCTURED_OR_HARNESS': 7}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, BOOL_LITERAL, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_657_revise_deliberate_strict_contracts_zero_write_on_bad_shape`
- lines: 2086, 2090, 2091, 2100, 2104, 2107, 2109, 2110, 2113, 2117, 2118, 2119, 2121, 2126, 2128, 2130, 2132, 2133, 2134, 2135, 2136, 2137, 2138, 2143, 2147, 2148
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 6, 'KEEP_STRUCTURED_OR_HARNESS': 9}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_NOT, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_pihong_dossier_1490.py::test_657_s10_http_five_actions_and_1490_no_regress`
- lines: 1255, 1264, 1329, 1341, 1344, 1345, 1346, 1350, 1351, 1357, 1359, 1361, 1364, 1367, 1368, 1373, 1375, 1376, 1385, 1387, 1388, 1390, 1391, 1393
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 3, 'KEEP_RESCRIPT_STRUCTURE': 2, 'KEEP_STRUCTURED_OR_HARNESS': 7}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_ATTR, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_pihong_dossier_1490.py::test_658_endorsement_provenance_xor`
- lines: 2538, 2541, 2542
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, GEN_TEXT_HINT, INDEX_ACCESS, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_pihong_dossier_1490.py::test_658_free_decree_capture_target_dossier_real_entry`
- lines: 2580, 2585, 2594, 2595, 2596, 2617, 2619, 2620, 2621, 2622, 2624, 2626, 2628, 2631, 2632, 2636, 2637, 2638, 2639, 2640, 2642
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 8}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_658_mixed_ordinary_triad_and_target_rejected`
- lines: 2819, 2822, 2823
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_pihong_dossier_1490.py::test_658_routing_rejected_draft_retries_across_real_turn_boundaries`
- lines: 2730, 2739, 2740, 2745, 2746, 2748, 2749, 2750, 2752, 2753, 2754, 2755, 2756, 2757, 2759, 2761, 2762, 2763, 2764, 2765, 2768, 2769, 2772, 2773, 2775, 2776, 2777, 2779, 2780
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 10}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_658_stalled_excluded_from_promulgation_validation`
- lines: 2416, 2419, 2420, 2421, 2422
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes`
- lines: 2671, 2672, 2673, 2674, 2675, 2676, 2677, 2678, 2684, 2688, 2690, 2691, 2693, 2696, 2697, 2698, 2702, 2703, 2706, 2710, 2713, 2714, 2715, 2716
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 8, 'KEEP_LLM_BOUNDARY': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_pihong_dossier_1490.py::web_game`
- lines: 57, 58
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_IO_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_promulgation_judge_561.py::test_default_promulgation_judge_uses_one_batch_and_existing_validator`
- lines: 790, 798, 804, 805, 806
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_promulgation_judge_561.py::test_gate_extracts_actual_cli_judge_payload_and_rejects_ambiguous_capture`
- lines: 170, 172, 173
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_promulgation_judge_561.py::test_review_exempt_actions_auto_promulgate_without_judge_contract_abort`
- lines: 915, 924, 925, 926
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_public_sayings_1829.py::test_public_saying_excluded_name_does_not_see_it_others_do`
- lines: 160, 163, 166, 170, 171, 194, 201, 202, 218, 219, 220, 221, 222, 227, 229, 230, 231, 241, 242, 246, 247, 249, 251, 255
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 7, 'KEEP_IO_BOUNDARY': 1, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 索引字段外部结果

### `tests/test_qa_a3_seed_data.py::test_lai_zongdao_remains_opening_libu_shangshu`
- lines: 66, 67
- disposition: `KEEP_FIXTURE_ECHO`
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: 中文子串——按夹具回传/结构化字段审；非模板哨兵则保留

### `tests/test_qa_d1_decree_normalize_1274.py::test_capture_drops_dachen_generic_no_409`
- lines: 42, 47, 48, 56, 57
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, BOUNDARY_STUB, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_qa_d1_decree_normalize_1274.py::test_capture_unknown_person_still_409`
- lines: 78
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_empty_text_capture_short_circuits_without_llm`
- lines: 166, 170, 171, 172
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_normal_capture_path_unchanged`
- lines: 244, 251, 252, 254
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_qa_d1_decree_normalize_1274.py::test_seeded_draft_long_extract_still_lands_real_dossier`
- lines: 208, 217, 218, 224, 225, 226
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_qa_t1_extraction_dual_source_1353.py::test_empty_startup_catchup_claims_zero_tickets`
- lines: 198, 199, 202
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, INITIAL_HINT, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_qa_t1_extraction_dual_source_1353.py::test_seal_claim_rejects_current_trail_legs_without_write`
- lines: 256, 261, 264, 265
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, EMPTY_COLLECTION, INITIAL_HINT, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_qa_t1_extraction_dual_source_1353.py::test_wait_in_flight_releases_on_worker_terminal`
- lines: 246, 247
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, ASSERT_EQ, ASSERT_NOT, EMPTY_COLLECTION, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_refugee_loop_652.py::_advance_canned_month`
- lines: 269, 276
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_refugee_loop_652.py::test_in_transit_relief_stays_executing_before_gazette`
- lines: 531, 532, 537, 542, 544, 551, 552, 564, 565, 566, 572, 573, 574, 576, 577, 579, 586, 588, 591, 592
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_refugee_loop_652.py::test_monthly_recovery_follows_each_month_actual_payment`
- lines: 476, 483, 492, 494
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, GEN_TEXT_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_refugee_loop_652.py::test_recovery_shared_pool_advances_once_after_empty_effect_month`
- lines: 435, 436, 451, 453, 454, 455, 459, 460, 461
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, GEN_TEXT_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_region_cannon_delta.py::test_zero_cannon_request_leaves_no_log`
- lines: 76
- disposition: `KEEP_STRUCTURED_FIELD`
- tags: ASSERT, ASSERT_EQ, INITIAL_HINT, LEN_CALL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_rejection_wiring.py::test_rejected_item_lands_in_reports_and_jsonl`
- lines: 44, 46, 47, 48, 50, 52, 53, 54
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_relation_brew_636.py::test_provider_fault_becomes_typed_brew_failure`
- lines: 46, 50
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IS, BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_relation_seed_638.py::fresh_session`
- lines: 37
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_relation_seed_638.py::test_earliest_legal_start_imports_only_earlier_seed_events`
- lines: 186, 197, 199, 200
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_ORDER, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_relation_seed_638.py::test_existing_save_is_never_touched_by_seed_import`
- lines: 434, 448, 461, 462
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_relation_seed_638.py::test_missing_bundled_seed_fails_new_save_and_retry_imports`
- lines: 212, 223, 228, 229
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_relation_seed_638.py::test_seed_failure_rolls_back_new_save_and_retry_imports`
- lines: 291, 304, 309, 310
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, BOUNDARY_STUB, INDEX_ACCESS, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_rescript_choices_563.py::test_manual_edit_preserves_existing_mode_when_text_and_extractor_are_silent`
- lines: 50, 58
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_rescript_choices_563.py::test_manual_mode_uses_typed_extractor_judgment`
- lines: 39, 42
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_rescript_draft_656.py::test_generate_combined_target_and_roster_failures_reported_together_then_land`
- lines: 403, 409, 410, 412, 413, 414, 416, 418, 423, 424
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_rescript_draft_656.py::test_generate_combined_target_roster_partial_heal_reports_remaining`
- lines: 468, 474, 475, 476, 477, 478, 479, 484, 489
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_ORDER, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_rescript_draft_656.py::test_generate_existing_offcourt_roster_character_lands`
- lines: 591, 604, 605, 606, 607
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_rescript_draft_656.py::test_generate_military_order_region_target_heals_then_drops`
- lines: 622, 634, 636
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_rejects_military_order_empty_assignee`
- lines: 653, 662, 664, 665, 666
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_rescript_draft_degrades_loudly_without_raising`
- lines: 811, 813, 815, 817
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_rescript_draft_program_error_propagates`
- lines: 827
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_ungrounded_army_heals_then_drops_sibling_kept`
- lines: 347, 356, 357, 358
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_ungrounded_region_heals_then_drops_sibling_kept`
- lines: 321, 329, 330, 331
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_unknown_delegator_heals_then_drops_sibling_kept`
- lines: 564, 576, 577, 578
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_draft_656.py::test_generate_unknown_roster_character_heals_with_legal_set_then_lands`
- lines: 526, 532, 533, 535, 536, 538, 544, 545, 546, 547, 548, 550, 551
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_rescript_draft_656.py::test_r3_strict_parse_degrades_via_generate`
- lines: 956, 959, 961
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_IS, BOUNDARY_STUB, NONE_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_heal_isolation_1801.py::test_1801_eight_items_all_pass_no_heal_no_trim`
- lines: 226, 228, 229, 230, 231, 232, 234
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, LEN_CALL, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_rescript_heal_isolation_1801.py::test_1801_item_utf8_heals_then_drops_only_bad_item`
- lines: 130, 132, 133, 134, 136, 137, 138
- disposition: `KEEP_RESCRIPT_STRUCTURE` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 2, 'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 批红/疗伤结构化字段与 draft 状态

### `tests/test_rescript_heal_isolation_1801.py::test_1801_top_unformed_heals_then_no_drafts`
- lines: 108, 109, 110, 111, 113, 114, 115, 117
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings`
- lines: 187, 189, 190, 191
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, NONE_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items`
- lines: 209, 211, 212, 213
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_heal_isolation_1801.py::test_1801_unknown_top_key_heals_then_ignores_key_keeps_items`
- lines: 150, 152, 153, 154, 157, 158, 159, 163
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_rescript_option_field_heal_1746.py::test_amount_numeric_string_accepted_via_grant_shape`
- lines: 337, 342, 344
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_army_single_combo_heals_not_batch_redraw`
- lines: 386, 388, 389, 392, 393, 394, 396, 398, 399
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_rescript_option_field_heal_1746.py::test_contract_failure_heals_not_batch_reject`
- lines: 315, 317, 318, 323, 325, 327, 328
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 2, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_dual_missing_discriminator_heals_grant_action`
- lines: 417, 419, 423
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_STRUCTURED_FIELD': 1, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades`
- lines: 859, 860, 861, 863, 865, 867
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_rescript_option_field_heal_1746.py::test_heal_bad_identity_refuses_merge_then_drops`
- lines: 901, 903, 905
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_heal_response_contract_failure_consumes_attempt_keeps_siblings`
- lines: 777, 779, 780, 782, 783, 786, 792, 794, 797, 799, 800, 803, 808, 810, 812, 814, 816, 818, 820, 823, 827, 837, 838, 840, 841, 842, 844, 845
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 10}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, HELPER_CALL, INDEX_ACCESS, LEN_CALL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_rescript_option_field_heal_1746.py::test_missing_target_kind_only_heals_not_combo_batch`
- lines: 362, 364, 365, 367
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 1, 'KEEP_FISCAL_ORACLE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, NUM_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_option_shape_failures_heal_not_batch`
- lines: 666, 668, 669, 674, 675, 676
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_overflow_json_number_exhaust_drops_only_bad`
- lines: 590, 592, 593, 595, 598, 601, 603, 604, 606
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, LEN_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_rescript_option_field_heal_1746.py::test_overflow_json_number_heals_not_batch`
- lines: 545, 547, 548, 549, 551, 552, 556, 557, 558, 561, 565, 568
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_RESCRIPT_STRUCTURE': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_NAME, HELPER_CALL, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_rescript_option_field_heal_1746.py::test_provider_still_whole_batch_item_missing_heals_and_drops`
- lines: 686, 690, 701, 703, 704, 705
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 2, 'KEEP_RESCRIPT_STRUCTURE': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_rescript_option_field_heal_1746.py::test_typed_illegal_also_heals`
- lines: 464, 466, 470, 471
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_runtime_llm_config.py::test_runtime_llm_transport_nonpositive_falls_back_to_defaults`
- lines: 569, 570, 571, 573, 574, 575, 576, 588, 589, 590
- disposition: `KEEP_LLM_CONFIG_SURFACE` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, SUSPECT_INITIAL
- contract/why: 传输/重试策略配置外部契约，非内部伪证

### `tests/test_runtime_llm_config.py::test_runtime_llm_transport_slot_defaults_and_preserve`
- lines: 511, 512, 513, 515, 527, 537, 538, 539
- disposition: `KEEP_LLM_CONFIG_SURFACE` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 传输/重试策略配置外部契约，非内部伪证

### `tests/test_scene_llm_1836.py::test_retire_via_scene_chat_closes_night_and_keeps_last_turn`
- lines: 165, 169, 183, 187, 189, 191, 193, 196, 197, 198
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOUNDARY_STUB, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_scene_llm_1836.py::test_scene_chat_one_call_returns_multi_person_script`
- lines: 66, 72, 74, 75, 76
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, GEN_TEXT_ATTR, INDEX_ACCESS, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_scene_llm_1836.py::test_xuan_lands_enter_then_present_on_next_prepare`
- lines: 86, 94, 105, 106, 109, 110
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_IN, BOUNDARY_STUB
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_secret_order_monthly_progress_566.py::_canned_monthly_settlement`
- lines: 54
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_secret_order_payoff_1504.py::test_invalid_declaration_stops_month_chain_and_marks_invalid`
- lines: 2013, 2014, 2015, 2016, 2018, 2019, 2020, 2031, 2032, 2033, 2052, 2063, 2064, 2065, 2066
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_ORDER, BOOL_LITERAL, BOUNDARY_STUB, EMPTY_COLLECTION, INDEX_ACCESS, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree`
- lines: 1038, 1040, 1041, 1047, 1048, 1053, 1062, 1064, 1067, 1070, 1071, 1072, 1073, 1074, 1075, 1076, 1077, 1086, 1087, 1088
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 2, 'KEEP_STRUCTURED_FIELD': 6}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, INDEX_ACCESS, LEN_CALL, NONE_LITERAL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_session_write_queue_1353.py::test_barrier_waits_healthy_slow_worker_terminal`
- lines: 281, 310, 313, 314
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_session_write_queue_1353.py::test_cancel_key_vacates_and_blocks_run`
- lines: 199, 201, 202, 203, 212
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, BOOL_LITERAL, INDEX_ACCESS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL
- contract/why: 结构化数值外部结果；非生成文盯文

### `tests/test_session_write_queue_1353.py::test_fail_vacate_lets_barrier_through`
- lines: 139, 143, 144
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL
- contract/why: 存在性/空值外部字段契约

### `tests/test_session_write_queue_1353.py::test_post_barrier_claim_run_waits_for_barrier`
- lines: 173, 184, 185, 190, 191, 192
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_session_write_queue_1353.py::test_queue_order_early_claim_late_finish_before_barrier`
- lines: 51, 82, 84, 85, 91, 92, 93, 94
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 3}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_session_write_queue_1353.py::test_write_turn_orders_cs_not_whole_leg_llm`
- lines: 396, 425, 426, 430, 431, 432, 433, 434
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 4}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, INITIAL_HINT, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 字符串结构化/夹具契约

### `tests/test_session_write_queue_1353.py::wait_pending_writes`
- lines: 34
- disposition: `KEEP_STRUCTURED_OR_HARNESS`
- tags: ASSERT, INITIAL_HINT
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_staged_assignment_identity_1890.py::test_undo_deletes_only_this_turns_committed_draft_directive`
- lines: 512, 516, 517, 521
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_IS, GEN_TEXT_HINT, INDEX_ACCESS, NONE_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_structured_decree_contract_1624.py::test_batch_combo_correction_real_wrapper`
- lines: 750, 757, 762, 763, 764, 765, 766, 767, 768, 769, 770, 781, 782
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, ASSERT_ORDER, BOUNDARY_STUB, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_structured_decree_contract_1624.py::test_combo_correction_preserves_first_draw_roster`
- lines: 539, 592, 601, 602, 603, 604, 605, 606, 607, 609, 610
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 5}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IN, BOUNDARY_STUB, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL, STR_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_structured_decree_contract_1624.py::test_http_manual_directive_lands_beyond_fifteen_initiatives_1790`
- lines: 404, 406, 420, 429, 431, 439, 440, 442, 450, 452, 453, 454, 457, 462, 463
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_LLM_BOUNDARY': 1, 'KEEP_STRUCTURED_OR_HARNESS': 6}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, BOUNDARY_STUB, HELPER_CALL, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_structured_decree_contract_1624.py::test_manual_owner_example_seal_advances`
- lines: 341, 343, 349, 352, 357, 366, 368, 369, 370, 372, 373
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_STRUCTURED_FIELD': 4, 'KEEP_LLM_BOUNDARY': 1}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, ASSERT_ORDER, BOUNDARY_STUB, HELPER_CALL, NONE_LITERAL, NUM_LITERAL, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_structured_decree_contract_1624.py::test_month_end_entry_owner_and_matrix_reject`
- lines: 221, 228, 230, 231, 232, 233, 234, 235, 236, 251, 255, 256, 258, 259, 260, 261, 262, 272, 276, 277, 278, 279, 280, 282, 284, 285, 287
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_IO_BOUNDARY': 3, 'KEEP_STRUCTURED_OR_HARNESS': 10}）
- tags: ASSERT, ASSERT_EQ, ASSERT_IS, ASSERT_NOT, BOUNDARY_STUB, GEN_TEXT_HINT, GEN_TEXT_NAME, INDEX_ACCESS, LEN_CALL, NONE_LITERAL
- contract/why: 枚举/状态机/字段名等结构化结果

### `tests/test_surcharge_causal_chain_650.py::test_player_month_recovery_consumes_old_levy_once`
- lines: 266, 269, 270, 272, 273
- disposition: `KEEP_STRUCTURED_OR_HARNESS` （组内另有 {'KEEP_IO_BOUNDARY': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, GEN_TEXT_HINT, STR_LITERAL
- contract/why: 其余 assert：按外部可见结构化结果保留

### `tests/test_verify_llm_clocks_884.py::test_api_verify_401_does_not_retry`
- lines: 111, 112, 113, 114, 116, 117, 118, 119
- disposition: `KEEP_STRUCTURED_FIELD` （组内另有 {'KEEP_STRUCTURED_OR_HARNESS': 1}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, NUM_LITERAL, STR_LITERAL
- contract/why: 长度/计数/身份/能力等结构化外部结果（非默许纯数字）

### `tests/test_verify_llm_clocks_884.py::test_api_verify_hang_retries_then_exhausts_with_stage`
- lines: 80, 81, 83, 84, 85, 88
- disposition: `KEEP_LLM_CONFIG_SURFACE` （组内另有 {'KEEP_STRUCTURED_FIELD': 2}）
- tags: ASSERT, ASSERT_EQ, INDEX_ACCESS, INITIAL_HINT, LEN_CALL, STR_LITERAL, SUSPECT_INITIAL
- contract/why: 传输/重试策略配置外部契约，非内部伪证

### `tests/test_verify_llm_clocks_884.py::test_api_verify_installs_sdk_attempt_clock`
- lines: 136, 139, 140
- disposition: `KEEP_LLM_BOUNDARY` （组内另有 {'KEEP_LLM_CONFIG_SURFACE': 1, 'KEEP_STRUCTURED_FIELD': 1}）
- tags: ASSERT, ASSERT_EQ, BOUNDARY_STUB, INDEX_ACCESS, INITIAL_HINT, NUM_LITERAL
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果

### `tests/test_web_audience_night_498.py::_fake_settlement_llm`
- lines: 92, 95, 99
- disposition: `KEEP_IO_BOUNDARY` （组内另有 {'KEEP_LLM_BOUNDARY': 1}）
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_web_audience_night_498.py::web_game`
- lines: 135
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_web_budget_payload.py::test_budget_payload_filters_central_army_pay_fixed_flow`
- lines: 18, 19
- disposition: `KEEP_P4_NEGATIVE` （组内另有 {'KEEP_FIXTURE_ECHO': 1}）
- tags: ASSERT, ASSERT_IN, STR_LITERAL
- contract/why: 必要负向：禁泄露片段

### `tests/test_web_court_visibility.py::_stub_game`
- lines: 216
- disposition: `KEEP_IO_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: IO/环境边界替身；外部结果另有结构化断言

### `tests/test_web_llm_runtime_config.py::_count_llm_calls`
- lines: 903
- disposition: `KEEP_LLM_BOUNDARY`
- tags: BOUNDARY_STUB
- contract/why: LLM/supply/drain 边界替身；行为断言在结构化外部结果


## 其余组（压缩一行/组；完整行级见 j6-full-disposition.jsonl）

| file::test | n | lines(head) | disposition | why |
|---|---:|---|---|---|
| `tests/legacy_staging_helpers.py::close_office_to_dossier` | 2 | 100,120 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_adr0015_per_item_rejection.py::test_sqlite_text_sanitization_covers_issue_rows_and_advances` | 5 | 57,58,59,63,67 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_adr0015_per_item_rejection.py::test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate` | 2 | 27,28 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_advance_paths_atomic.py::test_mark_event_triggered_upgrades_pending_choice_row` | 7 | 370,371,372,373,374,375,376 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_advance_paths_atomic.py::test_record_event_decision_choice_inserts_fresh_without_terminal_state` | 3 | 347,348,349 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_advance_paths_atomic.py::test_record_event_decision_choice_preserves_non_triggered_terminal_state` | 3 | 334,335,336 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_advance_paths_atomic.py::test_recovery_replay_blocked_by_pending_directives` | 1 | 436 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_advance_paths_atomic.py::test_skip_refused_at_front_half_done` | 1 | 451 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_advance_paths_atomic.py::test_submit_decisions_does_not_overwrite_already_decided_rows` | 7 | 204,222,223,240,241,251,253 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_advance_paths_atomic.py::test_submit_dossier_rescript_does_not_create_event_trigger` | 4 | 291,294,299,300 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_advance_paths_atomic.py::test_submit_event_decision_binds_from_candidate_snapshot_without_event_id` | 5 | 166,171,172,173,174 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_advance_paths_atomic.py::test_submit_event_decision_persists_choice_after_pending_cleanup` | 7 | 99,104,105,106,107,114,115 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_advance_paths_atomic.py::test_terminal_markers_upgrade_pending_choice_row` | 7 | 412,413,414,415,416,417,418 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_advances_section_rejections.py::test_advance_bad_issue_id_rejected` | 2 | 47,48 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_dirty_int_field_rejected` | 2 | 66,67 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_missing_issue_no_metric_leak` | 2 | 125,126 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_missing_issue_rejected` | 2 | 75,76 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_non_active_issue_no_metric_leak` | 2 | 138,139 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_non_active_issue_rejected` | 2 | 86,87 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_non_dict_item_rejected_not_crash` | 2 | 37,38 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_non_dict_metric_delta_tolerated` | 2 | 153,154 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_advances_section_rejections.py::test_advance_valid_still_advances` | 1 | 98 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_affairs_1831.py::test_conflicting_affair_declaration_on_existing_dossier_fails_loud` | 1 | 85 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_affairs_1831.py::test_new_issue_affair_attach_failure_leaves_no_partial_product` | 3 | 266,267,268 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_affairs_1831.py::test_same_name_affairs_are_not_merged_and_birth_close_is_rejected` | 5 | 101,107,126,133,134 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_affairs_1831.py::test_strategic_event_unauthorized_person_origin_reaches_final_projection` | 4 | 231,232,235,238 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_affairs_1831.py::test_typed_affair_new_issues_share_provenance_and_close_final_state` | 5 | 174,175,176,177,178 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_apply_context_holds_all_fields` | 4 | 102,103,104,105 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_collector_counts_deterministic_on_polluted_save` | 1 | 355 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_ddl_in_open_transaction_rolls_back` | 3 | 369,374,380 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_flush_then_mirror_writes_jsonl` | 3 | 255,257,258 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_mirror_idempotent_after_flush` | 1 | 274 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_mirror_to_jsonl_appends_on_multiple_calls` | 1 | 219 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_mirror_to_jsonl_empty_buffer_writes_nothing` | 1 | 228 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_mirror_to_jsonl_writes_lines` | 5 | 199,201,202,203,204 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_provenance_enum_values` | 5 | 18,19,20,21,22 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_applier_contract.py::test_provenance_from_string` | 2 | 27,28 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_record_accepts_plain_string_source` | 1 | 322 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_applier_contract.py::test_rejected_item_fields` | 4 | 44,45,46,47 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_rejection_collector_flush_before_record_leaves_db_empty` | 1 | 118 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_rejection_collector_flush_clears_buffer` | 1 | 163 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_rejection_collector_flush_stores_item_as_json` | 1 | 178 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_rejection_collector_flush_writes_rows` | 7 | 145,146,147,148,149,150,151 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_applier_contract.py::test_reset_discards_pending_and_flushed` | 2 | 303,308 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_section_result_holds_applied_and_rejected` | 2 | 61,62 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_applier_contract.py::test_section_result_merge` | 2 | 70,71 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_section_result_merge_empty` | 3 | 78,79,80 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_applier_contract.py::test_unflushed_rows_never_mirrored` | 1 | 287 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_appointment_tenure_607.py::test_acting_appointment_can_be_reappointed_permanent_on_same_path` | 1 | 208 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_appointment_tenure_607.py::test_appointment_dossier_and_office_archive_preserve_each_tenure` | 2 | 50,55 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_appointment_tenure_607.py::test_appointment_tenure_survives_restore` | 1 | 193 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_appointment_tenure_607.py::test_failed_dossier_reappointment_rolls_back_audit_and_sequence` | 7 | 150,153,158,161,170,171,172 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_appointment_tenure_607.py::test_legacy_appointment_defaults_to_permanent_without_rejudging` | 2 | 64,68 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_appointment_tenure_607.py::test_person_delta_rejects_invalid_appointment_tenure_without_mutation` | 4 | 98,99,100,101 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_army_card_status_1501.py::_assert_ming_register` | 3 | 74,76,79 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_card_status_1501.py::_assert_text_keeps_statuses` | 2 | 83,85 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_card_status_1501.py::_guanning_db_status` | 2 | 57,58 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_army_card_status_1501.py::test_army_payload_omits_static_status_exposes_arrears_text` | 9 | 145,153,158,159,161,165,173,181…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_card_status_1501.py::test_army_report_keeps_row_status` | 2 | 190,191 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_card_status_1501.py::test_db_status_field_untouched_after_payload_read` | 2 | 260,262 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_card_status_1501.py::test_shared_consumers_still_surface_status` | 13 | 205,207,208,213,218,222,231,232…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_display_173.py::test_army_payload_exposes_approx_arrears_text_not_raw` | 2 | 72,73 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_army_display_173.py::test_army_payload_exposes_army_needed` | 3 | 21,25,26 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_display_173.py::test_army_public_exits_approx_arrears_and_hide_split_accounts` | 1 | 48 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_display_173.py::test_army_rows_non_danger_sorted_by_theater_name` | 2 | 137,138 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_display_173.py::test_danger_order_preserves_fractional_arrears` | 1 | 127 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_display_173.py::test_danger_order_uses_army_needed_for_arrears_months` | 1 | 97 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_firearms.py::test_apply_army_delta_chinese_keys` | 2 | 162,163 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_firearms.py::test_apply_army_delta_sets_firearm` | 2 | 65,66 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_firearms.py::test_armies_table_has_firearm_columns` | 2 | 36,37 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_army_firearms.py::test_cannon_clamped_to_12` | 1 | 89 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_firearms.py::test_create_army_cannon_count_clamped` | 1 | 117 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_firearms.py::test_create_army_cannon_nonint_rejected_not_crash` | 2 | 140,144 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_firearms.py::test_create_army_with_firearm` | 2 | 102,103 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_firearms.py::test_firearm_clamped_0_100` | 1 | 77 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_firearms.py::test_fresh_seed_wires_firearm_not_all_zero` | 2 | 127,128 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_firearms.py::test_new_army_defaults_zero_firearm` | 2 | 50,51 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_firearms.py::test_score_fields_include_firearm_and_cannon` | 2 | 29,30 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_army_maintenance_retire_173.py::test_army_delta_maintenance_rejected_as_invalid_field` | 1 | 119 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_army_maintenance_retire_173.py::test_army_delta_other_fields_still_apply` | 1 | 134 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_maintenance_retire_173.py::test_existing_save_drops_maintenance_column_on_open` | 2 | 55,56 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_maintenance_retire_173.py::test_new_army_inf_manpower_rejected_not_crash` | 2 | 90,91 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_maintenance_retire_173.py::test_new_army_maintenance_key_ignored` | 2 | 70,71 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_maintenance_retire_173.py::test_new_army_still_requires_manpower` | 2 | 79,80 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_maintenance_retire_173.py::test_pay_derives_from_manpower` | 1 | 105 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_pay_source_prompt_contract.py::test_prompt_compatible_ming_new_army_pay_source_aliases_land` | 4 | 42,43,44,45 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_army_needed_derives_from_manpower_rate` | 1 | 26 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_salary_44.py::test_army_needed_non_ming_no_pay` | 1 | 64 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_army_needed_scales_with_manpower` | 2 | 44,45 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_salary_44.py::test_army_needed_shrink_lowers_pay` | 1 | 54 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_salary_44.py::test_army_needed_zero_manpower_zero_pay` | 1 | 34 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_army_pay_morale_delta_tiers` | 4 | 256,257,258,259 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_auto_pay_empty_allowed_ids_pays_no_armies` | 2 | 231,232 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_army_salary_44.py::test_auto_pay_reaches_salary_army_via_arrears_filter` | 1 | 215 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_salary_44.py::test_auto_pay_strips_allowed_army_ids_before_filtering` | 2 | 248,249 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_salary_44.py::test_backfill_anchor_when_column_present_but_data_unusable` | 1 | 154 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_army_salary_44.py::test_backfill_dynamic_army_falls_to_anchor` | 1 | 113 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_army_salary_44.py::test_backfill_reverse_fills_from_maintenance_on_direct_upgrade` | 1 | 132 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_army_salary_44.py::test_coerce_new_salary_rate_blocks_freeload` | 6 | 266,267,268,269,270,271 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_defected_army_to_ming_owes_salary_not_free` | 3 | 79,84,87 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_army_salary_44.py::test_manpower_clamp_to_zero_leaves_army_log` | 2 | 183,187 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_salary_44.py::test_manpower_true_noop_no_log` | 1 | 201 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_army_salary_44.py::test_non_finite_salary_rate_anchored_not_crash` | 4 | 281,282,283,288 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_army_salary_44.py::test_total_ming_salary_is_72_ceil_sum` | 1 | 166 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_audience_continuous_507.py::test_exit_excludes_later_public_ledger_from_character_hearing` | 2 | 134,135 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_continuous_507.py::test_present_roster_reflects_command_dismissal` | 3 | 146,150,151 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_continuous_507.py::test_qianqing_continuous_night_skeleton_runs` | 5 | 89,94,99,106,110 | `KEEP_STRUCTURED_OR_HARNESS` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_audience_continuous_507.py::test_scene_recap_quotes_public_dialogue_within_presence_interval` | 3 | 50,52,56 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_extraction_501.py::test_engine_close_night_drains_pending_success` | 5 | 30,51,52,53,54 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_extraction_501.py::test_engine_close_night_without_deps_keeps_pending_no_fail_closed` | 2 | 71,73 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_night_498.py::test_attach_without_scene_anchors_persists_readable_defaults` | 2 | 216,217 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_bad_audibility_and_append_after_close` | 2 | 589,593 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_chat_completion_via_attach` | 4 | 198,199,200,203 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_cli_minister_chat_anchors_turn_to_night` | 5 | 608,630,633,636,637 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_night_498.py::test_close_night_committed_without_dossier_does_not_publish_mingfa` | 4 | 663,665,667,668 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_audience_night_498.py::test_close_night_crash_then_reopen_db_resumes_idempotent` | 15 | 356,357,360,369,370,373,375,376…+7 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_close_night_only_commits_this_night_approved` | 2 | 433,435 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_closing_cursor0_reopen_refuses_new_and_explicit_resume_commits` | 8 | 465,470,471,472,476,477,479,482 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_cross_night_directive_reassigned_to_second_night` | 7 | 301,306,308,309,311,313,316 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_dead_person_enter_rejected_with_error_pack` | 3 | 230,231,232 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_legacy_reply_without_segments_stays_neutral_in_night_scroll` | 3 | 97,98,99 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_night_498.py::test_old_save_migration_night_id_index_order` | 5 | 554,555,561,570,571 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_night_498.py::test_open_night_atomic_on_dead_roster_injection` | 3 | 510,514,516 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_open_summon_close_chain_readable_by_night` | 11 | 116,117,118,122,123,124,125,126…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_standing_roster_skips_dead` | 6 | 238,252,255,256,257,259 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_summon_method_and_bad_method` | 2 | 142,145 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_night_498.py::test_two_nights_isolated_and_timeline_alignable` | 10 | 168,171,172,173,174,179,180,181…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_night_498.py::test_write_decree_leaves_unacted_pending_unchanged` | 2 | 284,286 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_presence_500.py::test_audible_interval_public_only` | 5 | 377,378,379,380,383 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_presence_500.py::test_court_break_writes_no_exit_ledger` | 5 | 149,151,161,168,169 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_presence_500.py::test_dismiss_command_updates_roster_immediately` | 5 | 52,55,57,60,61 | `KEEP_STRUCTURED_OR_HARNESS` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_audience_presence_500.py::test_dismiss_noop_when_not_present` | 4 | 74,75,76,80 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_presence_500.py::test_dismiss_via_cli_command_writes_exit_ledger` | 3 | 128,132,133 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_presence_500.py::test_present_names_at_table` | 2 | 306,307 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_audience_presence_500.py::test_present_names_at_uses_timeline_key_not_raw_seq` | 2 | 327,328 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_presence_500.py::test_reenter_after_exit_reappears_in_roster` | 6 | 220,230,231,232,234,235 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_presence_500.py::test_standing_roster_present_throughout` | 2 | 340,346 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_presence_500.py::test_transit_rejects_bad_method` | 3 | 249,250,253 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_restore_505.py::_agno_public_run_ids` | 1 | 621 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_audience_restore_505.py::chat` | 2 | 244,359 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_657_rescript_summon_atomic_on_enter_failure` | 2 | 933,937 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_657_rescript_summon_no_chat_turn_scaffold` | 2 | 905,906 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_657_rescript_summon_writes_enter_fact_and_is_idempotent` | 8 | 870,876,877,878,879,884,885,886 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_restore_505.py::test_failed_chat_rollback_returns_restored_directive_ids` | 2 | 400,404 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_failed_retry_rolls_back_side_effects_and_keeps_question` | 10 | 424,431,432,436,437,438,439,445…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_legacy_agno_sessions_runs_blob_still_counts_and_truncates` | 2 | 606,608 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_audience_restore_505.py::test_load_save_reconciles_interrupted_orphan` | 4 | 827,832,833,836 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_logical_history_matches_agno_merge_with_duplicate_legacy_ids` | 5 | 659,660,663,664,672 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_lost_reopen_cas_rejects_without_second_reply` | 1 | 475 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_pure_audience_zero_ledger_turn_survives_reopen` | 3 | 209,216,217 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_restore_505.py::test_reconcile_blob_baseline_drops_table_only_new_run` | 4 | 684,693,701,702 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_audience_restore_505.py::test_reconcile_does_not_delete_question_row` | 1 | 188 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_reconcile_leaves_completed_turn_untouched` | 2 | 161,165 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_reconcile_marks_questionless_orphan_failed` | 4 | 765,766,767,770 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_reconcile_truncates_agno_runs_to_turn_start` | 4 | 582,586,595,596 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_audience_restore_505.py::test_reopen_reconcile_preserves_ledger_exactly` | 1 | 114 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_reopen_reconcile_unblocks_and_keeps_question` | 5 | 130,137,138,141,144 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_retry_regenerates_reply_without_duplicate_question` | 6 | 292,297,301,306,307,309 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_restore_505.py::test_retry_rejected_in_settlement_phase` | 1 | 495 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_start_chat_turn_second_turn_reads_agno_v3_runs` | 5 | 808,811,815,816,817 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_restore_505.py::test_truncate_migrated_overlap_does_not_resurrect_via_agno_read` | 5 | 741,743,744,746,747 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_audience_scroll_539.py::test_empty_open_night_scroll_exposes_persisted_container` | 3 | 115,116,117 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_scroll_539.py::test_extractor_open_tags_do_not_drive_beat_or_soft_boundary` | 2 | 343,344 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_history_turns_lists_every_closed_night_including_night_only_turns` | 6 | 411,412,415,416,417,418 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_live_and_closed_night_share_the_real_http_contract` | 6 | 97,98,99,100,104,105 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_personal_projection_only_reads_the_current_open_night` | 2 | 454,455 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_presence_commands_only_record_facts` | 3 | 301,302,305 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_scroll_539.py::test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats` | 9 | 252,256,257,265,271,272,273,274…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_real_player_sse_replaces_closed_same_turn_night_before_failed_reply` | 4 | 47,49,54,55 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_scroll_539.py::test_real_player_summon_sse_precedes_reply_and_scroll_shows_protagonist` | 4 | 77,78,80,81 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_scroll_539.py::test_same_departure_facts_emit_one_divider_but_later_departure_survives` | 1 | 395 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_scroll_539.py::test_scroll_container_presents_audience_type_from_persisted_summon_method` | 2 | 360,361 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_scroll_539.py::test_scroll_contract_merges_both_stores_with_container_and_coda` | 5 | 285,286,289,290,291 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_audience_scroll_539.py::test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action` | 4 | 318,322,324,325 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_scroll_539.py::test_scroll_exposes_declared_protagonist_and_ledger_roster` | 2 | 132,133 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_scroll_539.py::test_scroll_exposes_translation_pending_until_late_declaration_lands` | 3 | 170,173,174 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_scroll_539.py::test_scroll_projects_portrait_for_legal_aside_speaker_outside_roster` | 3 | 155,156,157 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_scroll_539.py::test_scroll_without_next_entrance_has_unnamed_boundary` | 1 | 373 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_scroll_539.py::test_translation_segments_replace_neutral_reply_in_real_scroll` | 9 | 187,188,189,199,201,205,206,207…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_scroll_539.py::test_unnamed_speaker_cannot_finish_translation` | 2 | 226,229 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_translation_1838.py::test_edge_event_and_public_saying_attach_affair` | 7 | 338,339,345,346,348,350,354 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_translation_1838.py::test_edge_event_undo_deletes_via_source_turn` | 3 | 377,379,384 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_translation_1838.py::test_on_scene_fact_undo_via_translation_entry` | 5 | 410,411,412,415,419 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_translation_1838.py::test_presence_enter_exit_from_translation` | 4 | 151,152,154,163 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_translation_1838.py::test_protagonist_follows_translation_and_xuan_cut` | 7 | 223,235,236,237,248,249,250 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_translation_1838.py::test_protagonist_undo_reprojects_night_current` | 5 | 267,268,278,282,286 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_translation_1838.py::test_retry_older_round_keeps_newer_protagonist` | 1 | 303 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_translation_1838.py::test_three_speaker_segments_private_whisper_reaches_only_participant` | 14 | 94,95,103,108,109,110,111,112…+6 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_travel_gating_670.py::_arrive_at_destination` | 1 | 42 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_arrived_summon_continuation_survives_failed_apply_across_months` | 16 | 460,470,471,504,505,507,508,509…+8 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_travel_gating_670.py::test_audience_admission_distinguishes_capital_fresh_and_existing_transit` | 5 | 75,76,78,79,80 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_audience_admission_keeps_blank_fail_open_and_reuses_basic_qualification` | 2 | 86,92 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_audience_admission_records_nothing_for_capital_or_disqualified_person` | 3 | 120,123,126 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_audience_admission_records_offsite_summon_before_allowing_audience` | 4 | 104,105,106,107 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_cli_initial_selection_rejects_unknown_unregistered_person` | 7 | 155,160,161,162,163,164,165 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_cli_midflow_summon_consumes_admission_without_entering` | 2 | 691,693 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_audience_travel_gating_670.py::test_cli_midflow_summon_rejects_unknown_unregistered_person` | 7 | 707,711,712,713,714,715,716 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_consume_open_night_and_recorder_share_one_transaction` | 8 | 778,781,782,789,791,793,794,795 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_continuation_arrival_settles_origin_without_waiting` | 7 | 854,857,875,876,877,892,893 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_seed_closes_ticket_670_named_locations` | 2 | 537,544 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_summon_applier_failure_rolls_back_and_close_retry_is_safe` | 7 | 422,429,430,438,439,441,442 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_summon_departs_via_canonical_applier_only_when_night_closes` | 9 | 374,381,384,385,386,387,393,394…+1 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_summon_omitted_content_syncs_db_and_rolls_back_together` | 10 | 1344,1348,1349,1375,1377,1378,1379,1382…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_summon_origin_is_idempotent_and_projects_kind` | 2 | 240,241 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_fresh_summon_same_beizhili_journey_attaches_origin_without_reapply` | 7 | 1297,1316,1320,1322,1326,1327,1328 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_in_transit_summon_origin_is_idempotent_and_restorable` | 14 | 185,186,187,190,194,197,198,212…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_inactive_person_skips_continuation_and_retires_on_month` | 5 | 1246,1251,1252,1253,1256 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_legacy_capital_aliases_admit_in_capital_and_migrate_on_reopen` | 8 | 805,806,807,811,812,822,823,826 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_multi_origin_fresh_independent_retract_and_single_departure` | 14 | 631,632,639,640,641,642,648,657…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_multi_origin_same_person_dedupes_consumer_projections_not_ledger` | 21 | 268,269,270,273,274,279,283,290…+13 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_non_capital_location_aliases_migrate_on_reopen` | 2 | 1202,1203 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_travel_gating_670.py::test_shuntian_zhili_aliases_migrate_on_reopen` | 4 | 1213,1214,1229,1230 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_audience_travel_gating_670.py::test_summon_recorder_default_body_is_empty_and_tags_carry_facts` | 5 | 751,752,753,754,756 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_travel_gating_670.py::test_waiting_active_departure_commits_transit_log_settle_and_mirror` | 10 | 1066,1069,1070,1072,1073,1074,1080,1088…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_waiting_active_departure_external_rollback_reverts_transit_and_settle` | 6 | 1167,1168,1169,1172,1173,1174 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_waiting_active_departure_respects_strategic_preflight_savepoint` | 7 | 1106,1125,1127,1128,1133,1134,1135 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_waiting_active_departure_settle_failure_rolls_back_all_four_sides` | 7 | 1011,1013,1022,1028,1032,1033,1034 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_waiting_active_departure_settles_and_does_not_revive` | 6 | 929,945,946,947,948,957 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_travel_gating_670.py::test_waiting_inactive_retires_on_month` | 6 | 905,908,909,910,912,915 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_attach_origin_bind_atomic_no_orphan_enter_on_midway_crash` | 3 | 500,516,517 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_attach_origin_bind_atomic_normal_path_binds_and_undo_deletes` | 2 | 528,532 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_audience_undo_506.py::test_audit_passes_whitelisted_and_catches_unwhitelisted_night_write` | 4 | 171,177,188,189 | `KEEP_STRUCTURED_FIELD` | 中文子串——按夹具回传/结构化字段审；非模板哨兵则保留 |
| `tests/test_audience_undo_506.py::test_reject_pending_discards_inactive_office_summon_origin` | 3 | 610,617,618 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_confirm_round_reverts_pending_to_unapproved` | 3 | 338,346,355 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_dismiss_round_removes_exit_ledger_and_restores_presence` | 6 | 443,451,453,454,460,463 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_undo_erases_inactive_office_summon_origin_bound_to_chat_turn` | 4 | 585,586,587,591 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_erases_round_from_night_ledger_and_presence` | 7 | 112,113,122,123,125,127,129 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_undo_full_reversal_survives_kill_and_reopen` | 4 | 242,248,249,252 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_landed_secret_decree_removes_all_structured_records` | 4 | 416,417,424,427 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_pending_translation_leaves_no_orphan_retry` | 4 | 272,279,281,286 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_rejected_after_night_closed` | 2 | 143,147 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_undo_506.py::test_undo_removes_unlisted_person_registration` | 5 | 213,214,219,222,226 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_undo_restores_staging_row_deleted_by_verbal_reject` | 4 | 377,379,388,389 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_audience_undo_506.py::test_undo_reversal_is_atomic_on_midway_crash` | 3 | 315,316,317 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_audience_undo_506.py::test_undo_single_round_enter_and_dismiss_equals_not_happened` | 4 | 479,480,485,486 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_audience_undo_506.py::test_undo_survives_db_created_before_undone_at_column` | 2 | 557,558 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_authority_ledger_611.py::_eligible_dossier` | 1 | 34 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::_grant` | 1 | 45 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::_revoke` | 1 | 56 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_authority_changes_rejects_ineligible_keeps_legal_peer` | 8 | 189,218,219,220,221,222,224,225 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_duplicate_active_authority_is_rejected_across_dossiers` | 4 | 370,381,382,383 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_duplicate_check_ignores_authority_only_active_in_future` | 2 | 431,432 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_duplicate_check_uses_current_turn_not_future_effective_turn` | 2 | 406,407 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_authority_ledger_611.py::test_production_path_grant_restore_revoke_impression_tracer` | 21 | 91,93,104,105,116,117,131,132…+13 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_authority_ledger_611.py::test_production_rejects_bare_domain_scope` | 3 | 450,451,452 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_authority_ledger_611.py::test_projection_typed_domain_only_and_ignores_payload_authorization` | 7 | 276,277,278,281,282,285,288 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_promulgation_payload_does_not_write_authority_records` | 4 | 485,486,487,488 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_authority_ledger_611.py::test_same_dossier_grant_replay_is_idempotent` | 4 | 308,312,313,314 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_authority_ledger_611.py::test_same_dossier_grant_replay_returns_terminal_origin_without_regrant` | 5 | 344,345,348,350,351 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_bandit_power_model_190.py::test_bandit_power_backfill_serializes_list_aliases` | 1 | 87 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_bandit_power_model_190.py::test_bandit_power_split_backfill_preserves_changed_owner` | 2 | 99,102 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_bandit_power_model_190.py::test_old_save_schema_init_backfills_bandit_power_split` | 2 | 57,68 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_bandit_power_model_190.py::test_seed_splits_li_zicheng_and_zhang_xianzhong_bandit_powers` | 7 | 19,20,21,30,31,32,33 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_breach_plea_623.py::_executing_policy_dossier` | 1 | 78 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::_merge_funding_then_reversal` | 4 | 1247,1249,1251,1252 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_audience_revoke_commission_rejects_unrevocable_target` | 3 | 407,408,412 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_audience_revoke_commission_stages_typed_revoke_decree` | 7 | 372,377,378,379,380,381,383 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_breach_plea_survives_restore` | 2 | 1011,1013 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_breach_plea_623.py::test_commitment_due_expires_plea_without_persist_damage` | 6 | 901,902,903,905,906,908 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_funding_cutoff_writes_plea_no_damage_same_turn` | 11 | 150,152,153,154,156,157,160,161…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_kind_gate_apply_only_finalizes_staged` | 5 | 955,959,964,965,967 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_merged_funding_primary_remove_sponsor_absorbed_accounts` | 7 | 1338,1341,1342,1345,1346,1352,1354 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_merged_persist_via_extraction_settles` | 6 | 1307,1308,1309,1310,1314,1315 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_merged_persist_via_tracker_cancel_settles` | 8 | 1274,1275,1276,1278,1282,1283,1288,1290 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_merged_remove_sponsor_primary_funding_absorbed_accounts` | 7 | 1377,1380,1381,1384,1385,1391,1392 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_misappropriation_via_tags_producer_pipeline` | 3 | 1216,1222,1223 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_breach_plea_623.py::test_misappropriation_writes_plea` | 3 | 193,195,196 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_model_execution_verdict_lands_after_persist` | 6 | 765,776,781,785,787,788 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::test_no_decision_pause_on_breach_plea_settle` | 2 | 1030,1031 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_persist_leaves_execution_verdict_to_model` | 12 | 710,711,714,716,717,720,721,722…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_persist_reclaims_bundled_authority` | 3 | 1104,1108,1109 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_breach_plea_623.py::test_persist_remove_sponsor_no_0056` | 4 | 810,811,812,815 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::test_persist_via_extraction_cancels_true_entry` | 4 | 839,840,841,842 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_policy_reversal_revoke_keeps_same_origin_world_situations` | 2 | 343,344 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::test_policy_reversal_revoke_model_verdict_lands_same_month` | 3 | 302,306,307 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_policy_reversal_revoke_rejected_leaves_everything_untouched` | 4 | 587,588,591,592 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::test_policy_reversal_revoke_takes_effect_same_month` | 6 | 259,260,266,267,269,270 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_breach_plea_623.py::test_regret_via_extraction_true_entry_zero_damage` | 8 | 663,664,666,667,668,671,672,673 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_remove_sponsor_persist_writes_credit_edge` | 3 | 1131,1137,1138 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_remove_sponsor_writes_plea` | 4 | 218,220,222,225 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_revoke_target_identity_falls_back_to_dossier_row` | 9 | 539,540,541,542,551,552,558,559…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_same_sponsor_two_commitments_both_remove_edges` | 4 | 1177,1178,1186,1189 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_breach_plea_623.py::test_same_turn_dual_breach_kinds_merge_not_swallowed` | 5 | 1056,1062,1064,1067,1069 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_silence_keeps_pending_across_settle` | 5 | 873,874,875,879,881 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_takeover_window_excludes_breach_plea` | 1 | 985 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_breach_plea_623.py::test_two_successive_loosenings_get_independent_pleas` | 5 | 616,624,625,627,629 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_candidate_supply_1893.py::test_eligible_candidate_event_reaches_world_supply` | 4 | 77,79,82,83 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_impeachment_surge_candidate_survives_restore` | 2 | 447,453 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_candidate_supply_1893.py::test_impeachment_surge_lands_only_when_faction_actually_impeaches` | 9 | 375,376,385,402,406,408,409,410…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_candidate_supply_1893.py::test_ineligible_and_terminal_events_stay_out_of_supply` | 2 | 106,107 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_non_strategic_candidate_effects_land_without_event_id_binding` | 2 | 324,328 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_not_selected_candidate_leaves_no_terminal_state` | 2 | 299,300 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_candidate_supply_1893.py::test_selected_event_lands_once_via_existing_new_issues_write` | 5 | 268,269,273,278,282 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_supplied_outcome_labels_match_writer_whitelist` | 4 | 356,357,360,364 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_surge_candidate_offered_by_world_segment_is_declared_and_lands` | 5 | 167,174,175,191,192 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_translate_request_carries_current_candidate_facts` | 3 | 215,216,217 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_candidate_supply_1893.py::test_translate_request_omits_ineligible_candidate` | 1 | 245 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::_faction_of` | 1 | 69 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_centrifuge_ledger_690.py::test_t10_partial_preinserted_key_aborts` | 1 | 643 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t11_rebuild_clears_dirty_and_write_path_rolls_back` | 9 | 671,683,684,687,688,689,694,718…+1 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t12_restore_preserves_tables_and_rebuild` | 5 | 773,791,794,795,798 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t14_reason_code_sets_and_reject_unrecognized` | 1 | 844 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t1_confiscation_direct_anchors_via_public_api` | 4 | 117,118,119,120 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t2_kinship_uses_unrounded_formula` | 4 | 133,149,150,151 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_centrifuge_ledger_690.py::test_t2b_legitimacy_uses_raw_for_amounts` | 6 | 174,175,176,179,199,200 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_centrifuge_ledger_690.py::test_t3_zero_delta_empty_namespace_is_legal_noop` | 1 | 222 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t4_happy_path_and_forbidden_kwargs` | 7 | 249,250,252,253,259,278,279 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_centrifuge_ledger_690.py::test_t5_bastinado_overdraw_batch_and_non_bastinado` | 5 | 305,307,308,309,321 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_centrifuge_ledger_690.py::test_t6_bad_target_aborts_with_zero_write` | 1 | 348 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t6b_non_int_identity_aborts_with_zero_write` | 2 | 379,392 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_centrifuge_ledger_690.py::test_t7_cross_faction_isolation` | 5 | 406,424,425,426,428 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_centrifuge_ledger_690.py::test_t8_detection_wariness_only_kinship` | 8 | 451,452,453,454,455,456,476,477 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_centrifuge_ledger_690.py::test_t9_idempotency_namespace_and_empty_planned` | 6 | 514,538,556,569,586,598 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_883_legacy_aggregate_without_source_rows_does_not_authorize_knowledge` | 1 | 1077 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_appended_dossier_participant_learns_only_on_join_turn_after_restore` | 3 | 716,721,729 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_archive_write_materializes_unmirrored_source_scope` | 4 | 972,973,974,975 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_character_knowledge_489.py::test_army_truth_is_exactly_scoped_to_person_command` | 2 | 1351,1352 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_central_ledgers_reach_each_office_archive_carrier_without_crossing` | 2 | 1590,1595 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_character_added_after_archive_cannot_read_old_participant_source` | 1 | 1067 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_current_state_facts_are_selected_by_content_domain_not_role_label` | 4 | 99,100,101,102 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_decree_dossier_participant_reads_frozen_metadata_and_text` | 2 | 746,749 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_delete_chat_messages_removes_chat_derived_knowledge_from_context` | 3 | 287,290,293 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_character_knowledge_489.py::test_disclosed_secret_source_keeps_its_public_projection` | 2 | 478,479 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_event_office_blacklist_matches_current_office_name` | 1 | 658 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_excluded_participant_event_is_not_visible_to_excluded_character` | 1 | 329 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_household_secret_ledger_hides_case_by_excluded_office` | 10 | 1440,1443,1444,1445,1446,1455,1466,1469…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics` | 7 | 1397,1398,1399,1403,1411,1412,1413 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_inner_court_materials_do_not_read_faction_report` | 1 | 73 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_issue_roster_is_structured_and_read_side_projection_needs_no_write_hook` | 3 | 576,578,582 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_issue_write_path_projects_participants_across_restore` | 3 | 391,397,398 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_knowledge_exclusion_reads_current_office_without_nameerror` | 3 | 838,840,842 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_knowledge_projects_mixed_archive_from_durable_source_scope` | 4 | 914,915,916,917 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_knowledge_projects_public_events_without_leaking_private_matters` | 4 | 874,875,876,877 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_multi_lead_typed_archives_reach_only_each_office_successor` | 7 | 1557,1558,1559,1560,1561,1562,1564 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_new_participation_source_is_projected_without_read_side_type_branch` | 1 | 612 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_office_blacklist_preserves_unrelated_war_register_fact` | 2 | 640,641 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_office_slice_does_not_read_unrelated_sensitive_reports` | 3 | 56,57,58 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_participant_roster_is_discovered_from_any_persistent_table` | 1 | 694 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_participant_roster_is_discovered_from_persistent_record_without_adapter` | 1 | 629 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_participation_adapter_reads_structured_roster_without_fake_names` | 1 | 600 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_participation_record_adapter_covers_assignment_shape` | 1 | 375 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_participation_survives_restore` | 2 | 236,237 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_public_directive_is_seen_by_uninvolved_minister_but_secret_exclusion_wins` | 2 | 168,172 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_public_directive_remains_visible_on_a_later_turn` | 1 | 312 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_public_disclosure_drops_private_roster_but_keeps_event_exclusion` | 5 | 510,511,512,515,516 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_public_reports_accumulate_across_turns` | 2 | 360,361 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_restored_knowledge_uses_current_db_office_after_transfer` | 4 | 148,149,150,151 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py::test_rewritten_archive_cannot_reintroduce_restricted_source` | 1 | 943 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_role_roster_only_lists_current_active_ming_people` | 1 | 33 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_secret_alias_exclusion_is_canonicalized_before_projection` | 1 | 39 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_secret_amendment_preserves_legacy_blacklist_and_public_disclosure` | 3 | 541,545,550 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_secret_blacklist_survives_later_public_projection` | 1 | 343 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_secret_exclusion_is_source_scoped_not_global_for_same_bucket` | 2 | 564,565 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_secret_office_exclusion_does_not_hide_unrelated_world_bucket` | 4 | 409,410,414,415 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_secret_office_exclusion_snapshots_people_before_transfer_and_publication` | 4 | 457,459,460,461 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_secret_office_snapshot_keeps_explicit_people_target_separate` | 2 | 435,439 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_character_knowledge_489.py::test_secret_order_dossier_never_leaks_through_shared_roster_projection` | 1 | 766 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_character_knowledge_489.py::test_shared_archive_storage_never_writes_restricted_aggregate` | 4 | 1021,1028,1029,1034 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_structured_person_scope_replaces_role_wide_world_reports` | 56 | 1105,1113,1114,1115,1118,1131,1132,1133…+48 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_character_knowledge_489.py::test_turn_report_counterpart_never_uses_aggregate_when_sources_exist` | 2 | 1002,1005 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_turn_report_keeps_source_specific_secret_exclusion_boundary` | 2 | 194,195 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_turn_report_projects_public_and_secret_items_per_character` | 2 | 216,217 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_character_knowledge_489.py::test_undo_chat_turn_removes_chat_derived_knowledge_from_context` | 4 | 258,265,268,271 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_chat_stream_failpaths_393.py::test_chat_stream_error_status_run_output_system_layer_not_diegetic` | 6 | 1120,1122,1124,1125,1126,1127 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_chat_stream_failpaths_393.py::test_chat_stream_halfstream_terminal_fail_replaces_temp` | 4 | 1070,1072,1083,1094 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_chat_stream_failpaths_393.py::test_nonstream_api_issue_decree_llm_unavailable_is_structured_not_500` | 4 | 504,505,506,507 | `KEEP_STRUCTURED_FIELD` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_chat_stream_failpaths_393.py::test_prologue_cleanup_failure_still_releases_gate_and_counter` | 1 | 262 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_chat_stream_failpaths_393.py::test_prologue_failure_fails_orphan_turn_and_releases_gate` | 2 | 162,164 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_chat_stream_failpaths_393.py::test_worker_cleanup_double_failure_emits_original_error_end_and_logs` | 7 | 359,361,362,364,367,369,374 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_chat_stream_failpaths_393.py::test_worker_cleanup_failure_still_emits_error_and_releases_gate` | 4 | 319,320,321,322 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_chat_stream_failpaths_393.py::test_worker_postprocess_exception_emits_error_end` | 7 | 422,424,425,426,428,430,431 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_cli_backend.py::test_backend_env` | 2 | 219,221 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_cli_backend.py::test_clichat_codex_response_stream_passes_reasoning_strength` | 3 | 399,400,401 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_clichat_invoke_builds_prompt_and_completion_structure` | 6 | 742,743,745,746,747,748 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_cli_backend.py::test_clichat_invoke_json_constraint_and_no_constraint` | 3 | 769,770,771 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_cli_backend.py::test_describe_effective_model_includes_new_runners` | 1 | 1183 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_login_shell_path_extracts_from_sentinels_despite_noise` | 1 | 629 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_login_shell_path_single_dir_not_dropped` | 1 | 641 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_material_runner_uses_cwd_and_read_only_tool_surface` | 9 | 1027,1028,1031,1034,1050,1052,1053,1055…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_public_cli_support_restores_existing_runners` | 5 | 1012,1013,1014,1016,1018 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_resolve_cli_bin_absolutizes_relative_result` | 2 | 669,670 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_resolve_cli_bin_caches` | 3 | 612,613,614 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_resolve_cli_bin_falls_back_and_miss_not_cached` | 2 | 594,599 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_resolve_cli_bin_found_on_current_path` | 1 | 551 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_resolve_cli_bin_login_shell_path_last_resort` | 1 | 587 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_run_agy_auth_race_is_retryable_typed_without_private_loop` | 2 | 867,868 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_run_agy_nonzero_exit_is_terminal_and_runs_once` | 1 | 876 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_cli_backend.py::test_run_backend_dispatch` | 1 | 243 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_run_backend_dispatch_new_runners` | 1 | 1132 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_backend.py::test_run_runner_empty_output_is_retryable_typed` | 1 | 906 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py::test_run_runner_execs_resolved_abspath` | 1 | 688 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_cli_backend.py::test_typed_secret_exclusions_canonicalize_roster_alias_and_office` | 2 | 98,99 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_model_choices.py::test_default_labels_reuse_single_source_constants` | 2 | 29,30 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_cli_model_choices.py::test_get_llm_config_exposes_choices` | 2 | 107,108 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_cli_model_choices.py::test_menu_status_cli_model_saved_passes_explicit` | 1 | 91 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_model_choices.py::test_menu_status_exposes_choices` | 2 | 67,68 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_cli_play_turn.py::test_cli_does_not_end_unadvanced_turn` | 1 | 121 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_play_turn.py::test_cli_write_gate_canonical_session_attr` | 3 | 651,652,654 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_play_turn.py::test_issue_refusal_stays_in_loop` | 2 | 83,84 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_play_turn.py::test_play_turn_reports_default_approval_secret_order_failure` | 3 | 451,453,455 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_play_turn.py::test_play_turn_skip_settlement_abort_stays_in_player_loop` | 2 | 509,510 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_persists_messages_before_session_chat` | 3 | 174,194,195 | `KEEP_FIXTURE_OR_SEED` | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_removes_user_message_when_session_chat_fails` | 2 | 229,245 | `KEEP_FIXTURE_OR_SEED` | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted` | 2 | 278,294 | `KEEP_FIXTURE_OR_SEED` | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py::test_terminal_minister_chat_reply_persist_failure_keeps_user_message` | 2 | 374,375 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_cli_runner_error_typed_1299.py::test_extract_agent_text_error_status_raises_typed_not_leaks_banner` | 4 | 84,85,86,87 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_cli_runner_error_typed_1299.py::test_extract_agent_text_preserves_leading_trailing_whitespace` | 2 | 108,111 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_close_issues_section_rejections.py::test_close_already_inactive_rejected_missing_ref` | 3 | 95,96,97 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_bad_issue_id_rejected` | 2 | 37,38 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_bad_reason_rejected` | 2 | 59,60 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_failed_on_uncollapsible_rejected_invalid_enum` | 3 | 108,109,111 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_close_issues_section_rejections.py::test_close_non_dict_item_rejected_not_crash` | 2 | 48,49 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_overflow_issue_id_rejected` | 2 | 82,83 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_rejection_reaches_rejection_reports` | 2 | 133,134 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_close_issues_section_rejections.py::test_close_unknown_issue_rejected_missing_ref` | 2 | 70,71 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_close_issues_section_rejections.py::test_close_valid_issue_still_succeeds` | 2 | 181,182 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_close_issues_section_rejections.py::test_scalar_item_rejection_preserves_original_in_reports` | 1 | 156 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_commitment_backlash_626.py::_executing_policy_dossier` | 1 | 82 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_commitment_backlash_626.py::test_ac1_breach_verdict_triggers_commitment_backlash` | 13 | 162,172,173,175,176,182,183,184…+5 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac1_deformation_exposure_triggers_commitment_backlash` | 8 | 276,279,285,287,291,292,293,297 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac1_failed_terminal_triggers_commitment_backlash` | 9 | 214,222,223,226,230,231,232,236…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac1_transformed_without_beyond_intent_does_not_trigger` | 5 | 318,320,324,325,328 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac2_halfway_persist_one_commitment_metrics_no_double_count` | 17 | 364,368,369,370,378,379,380,381…+9 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac3_just_started_and_rooted_do_not_trigger` | 4 | 438,461,473,474 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac3_persist_stamps_verdict_and_still_triggers` | 4 | 666,670,671,672 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac3_plea_due_expire_then_commitment_expire_no_hammer` | 13 | 601,609,610,615,618,624,625,626…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac3_regret_then_expire_dropped_no_hammer` | 10 | 551,567,568,569,571,578,579,582…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac3_regret_then_resolve_no_breach_verdict_hammer` | 13 | 490,499,500,505,509,514,515,523…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac4_backlash_survives_restore_both_states` | 8 | 701,707,714,723,724,728,729,737 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_commitment_backlash_626.py::test_ac5_hook_idempotent_no_gate_table_expansion` | 4 | 766,767,772,773 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_commitment_display_348.py::test_bar_tracks_elapsed_via_wall_clock` | 6 | 67,68,69,72,73,74 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_commitment_display_348.py::test_origin_turn_unset_falls_back_to_state_turn` | 2 | 85,86 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_commitment_display_348.py::test_timed_bar_percentage_clamp_and_none_cases` | 8 | 29,30,31,32,33,37,42,48 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_court_break_player_lock_1727.py::test_court_break_locks_player_writes_and_closes_night` | 13 | 140,146,147,148,151,152,153,154…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_court_layout_1290.py::test_court_layout_roundtrip_player_override` | 3 | 62,63,66 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_court_layout_1290.py::test_new_game_court_layout_empty_is_legal` | 1 | 52 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::_exposed_todo` | 1 | 151 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_covert_consumer_requires_real_beyond_intent_effect_without_narrowing_generic_fork` | 2 | 129,134 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_covert_levy_651.py::test_dispositions_consume_only_real_canonical_complete_legs` | 4 | 178,196,200,202 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::test_empty_effect_month_rechecks_persisted_exposure` | 1 | 95 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_covert_levy_651.py::test_exposure_uses_single_dispatcher_and_projects_exact_case` | 6 | 42,44,46,47,48,49 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_covert_levy_651.py::test_false_denunciation_is_not_retroactively_made_true_by_current_fork` | 2 | 544,550 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_force_promulgated_history_is_the_canonical_prohibition_authority` | 2 | 525,526 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::test_population_transfer_is_the_self_grown_unrest_channel` | 4 | 568,569,572,574 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_prohibition_blocks_every_covert_write_but_preserves_ordinary_legs` | 13 | 320,368,369,370,371,372,373,374…+5 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::test_prohibition_consumes_immediately_when_arrears_are_already_zero` | 2 | 289,290 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_prohibition_neutralizes_once_with_zero_receipt_and_partial_clamp` | 7 | 402,403,408,422,427,431,432 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_prohibition_reminder_is_consumed_after_later_payoff` | 3 | 300,302,303 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_prohibition_removes_live_covert_creation_without_rewriting_history` | 4 | 477,478,479,484 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::test_prohibition_uses_only_current_canonical_incarnation` | 2 | 461,462 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_rejected_canonical_results_neither_consume_nor_create_channel` | 4 | 111,116,117,121 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_same_segment_denunciation_creates_exposure_todo` | 2 | 74,76 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_covert_levy_651.py::test_tacit_and_prohibition_use_real_canonical_identity_and_are_idempotent` | 12 | 230,231,233,234,235,237,238,239…+4 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_covert_levy_651.py::test_zero_pay_receipts_are_not_durable_tacit_effects` | 2 | 500,501 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_credit_events_628.py::_executing_dossier` | 1 | 53 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_credit_events_628.py::_transformed_dossier` | 1 | 65 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_credit_events_628.py::test_ac1_breach_plea_guofu_not_reimplemented` | 4 | 161,163,164,168 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_credit_events_628.py::test_disposition_scapegoat_cover_prosecute_on_transformed` | 20 | 382,385,398,400,401,402,403,405…+12 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_credit_events_628.py::test_fulfill_back_and_urge_three_decisions` | 18 | 194,196,198,199,200,201,230,231…+10 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_credit_events_628.py::test_idempotent_narrative_restore_write_only` | 8 | 597,606,622,623,627,628,642,643 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_db_broad_except_surface.py::test_legacy_modifiers_corrupt_json_skips_and_surfaces` | 3 | 85,96,97 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_db_broad_except_surface.py::test_pending_decisions_corrupt_choice_json_returns_none_and_surfaces` | 3 | 54,55,56 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_db_broad_except_surface.py::test_pending_decisions_corrupt_options_json_falls_back_and_surfaces` | 3 | 36,37,38 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_db_broad_except_surface.py::test_resolve_context_corrupt_payload_falls_back_and_surfaces` | 3 | 72,73,74 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decision_event_binding_389.py::test_candidate_binding_at_player_prewrite` | 3 | 34,35,36 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::_army_id` | 1 | 30 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_declaration_dispatch_1835.py::_minister` | 1 | 24 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_declaration_dispatch_1835.py::test_commission_with_appointment_and_grant_is_one_combined_payload_one_row` | 11 | 130,149,150,151,153,159,166,167…+3 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_declaration_dispatch_1835.py::test_commission_with_draft_and_grant_for_same_money_is_one_payload_one_row` | 7 | 102,103,105,112,113,114,115 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_declaration_dispatch_1835.py::test_edge_event_attaches_declared_affair` | 2 | 574,579 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_edge_event_conflicting_affair_pointer_is_rejected_first_binding_kept` | 5 | 607,616,617,618,623 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_edge_event_lands_and_categorizes_unknown_kind_and_hallucinated_person_differently` | 3 | 538,550,552 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_on_scene_fact_attaches_declared_affair_and_rejects_unopened_affair` | 6 | 353,354,358,370,371,373 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_on_scene_fact_conflicting_affair_pointer_rolls_back_the_person_change_too` | 8 | 398,400,408,409,410,413,417,420 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_declaration_dispatch_1835.py::test_on_scene_person_status_change_lands_and_rejects_nonexistent_person` | 3 | 331,332,334 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_presence_lands_with_declared_body_verbatim_no_synthesized_text` | 3 | 441,442,448 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_declaration_dispatch_1835.py::test_presence_rejects_nonexistent_person_without_polluting_ledger` | 4 | 471,472,473,477 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_presence_with_no_night_context_is_rejected_as_missing_ref` | 3 | 488,489,490 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_promise_referencing_action_id_belonging_to_another_night_is_rejected` | 4 | 310,311,312,316 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_promise_refuse_withdraws_staged_action_and_missing_action_id_is_rejected` | 8 | 275,277,278,279,280,281,282,287 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_declaration_dispatch_1835.py::test_protagonist_lands_and_rejects_nonexistent_person` | 4 | 633,634,637,638 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_registration_adds_new_person_to_roster_and_rejects_existing_name` | 8 | 653,654,655,656,661,662,663,664 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_registration_attaches_declared_affair` | 2 | 680,684 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_scene_fact_speaker_segment_lands_verbatim_and_rejects_bad_audibility_and_ghost_person` | 4 | 521,522,524,530 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_declaration_dispatch_1835.py::test_staging_onto_already_settled_decree_ref_is_rejected_not_stranded` | 3 | 791,806,808 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_declaration_dispatch_1835.py::test_stub_declaration_lands_on_existing_staging_and_new_records_without_missing_items` | 9 | 58,59,60,61,68,73,76,79…+1 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_decree_commitment_creation_136.py::test_commitment_rejects_string_numeric_person_loyalty_ongoing_effect` | 3 | 756,757,758 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_commitment_skips_cli_resolve_effect_enrich` | 2 | 1156,1157 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_creation_136.py::test_decree_commitment_dedups_same_batch_fiscal_create_carrier` | 5 | 127,128,129,133,134 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_decree_commitment_does_not_dedup_same_name_income_fiscal_create` | 2 | 181,182 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_creation_136.py::test_decree_commitment_same_account_alias_miss_keeps_distinct_fiscal_item` | 3 | 237,238,242 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_creation_136.py::test_decree_commitment_unrelated_account_keeps_fiscal_item` | 1 | 285 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_creation_136.py::test_empty_json_stop_condition_allows_advance_to_resolved` | 3 | 1114,1115,1116 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_creation_136.py::test_future_one_shot_commitment_issue_is_created_with_deadline_only` | 8 | 470,472,473,474,475,476,477,478 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_future_one_shot_commitment_shape_rejects_without_explicit_marker` | 3 | 566,567,568 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_has_stop_condition_handles_preparsed_and_json_whitespace` | 6 | 1084,1085,1086,1087,1088,1090 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_decree_commitment_creation_136.py::test_legacy_resolve_condition_person_commitment_rejects_without_marker` | 3 | 659,660,661 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_limited_duration_commitment_shape_rejects_without_explicit_marker` | 3 | 359,360,361 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn` | 3 | 399,400,401 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_limited_duration_ongoing_commitment_rejects_past_end_turn` | 3 | 441,442,443 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_one_shot_appeasement_economy_move_does_not_create_commitment_issue` | 2 | 1182,1183 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_open_ended_ongoing_commitment_issue_is_created_with_explicit_marker` | 7 | 505,507,508,509,510,511,512 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_decree_commitment_creation_136.py::test_open_ended_ongoing_commitment_shape_rejects_without_explicit_marker` | 3 | 538,539,540 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_stop_condition_only_commitment_shape_rejects_without_explicit_marker` | 3 | 594,595,596 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_stop_condition_without_commitment_kind_advance_to_full_stays_active` | 3 | 1078,1079,1080 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_creation_136.py::test_string_stop_condition_only_with_origin_ref_rejects_without_explicit_marker` | 3 | 622,623,624 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_advance_to_full_stays_active` | 3 | 1051,1052,1053 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_issue_is_created_with_carrier_fields` | 12 | 69,71,72,73,74,75,76,77…+4 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_direct_failed_close_without_effects` | 5 | 1007,1008,1010,1011,1012 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_direct_resolved_close` | 3 | 968,969,971 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_non_dict_stop_condition` | 3 | 785,786,787 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_one_shot_entity_creation_as_monthly_work` | 3 | 932,933,934 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_semantically_empty_ongoing_effects` | 3 | 899,900,901 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_rejects_stop_condition_without_table_prefix` | 3 | 814,815,816 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_requires_initiative_kind` | 3 | 688,689,690 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_requires_ongoing_effects` | 3 | 870,871,872 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_requires_origin_ref` | 3 | 842,843,844 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_shape_rejects_without_explicit_marker` | 3 | 321,322,323 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_creation_136.py::test_until_stop_commitment_supports_character_loyalty_condition` | 2 | 718,719 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_schema_136.py::test_decree_commitment_shape_with_string_stop_condition_requires_marker` | 3 | 199,200,204 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_commitment_schema_136.py::test_effect_dict_has_work_ignores_empty_or_invalid_payloads` | 1 | 56 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_decree_commitment_schema_136.py::test_effect_dict_has_work_recognizes_schema_effects` | 1 | 77 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_decree_commitment_schema_136.py::test_existing_issues_table_gets_commitment_columns_idempotently` | 3 | 258,259,260 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_commitment_schema_136.py::test_insert_issue_persists_commitment_deadline_columns` | 1 | 128 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_schema_136.py::test_insert_issue_serializes_structured_stop_condition_as_json` | 1 | 150 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_commitment_schema_136.py::test_issue_resolution_removes_building_and_keeps_remove_audit_log` | 3 | 101,108,109 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_schema_136.py::test_issues_schema_has_commitment_deadline_columns` | 6 | 31,32,33,34,35,36 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_commitment_schema_136.py::test_new_issue_persists_commitment_columns_from_tracker_output` | 5 | 171,176,177,178,179 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_decree_commitment_settlement_229.py::_army_arrears` | 1 | 24 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::_character_loyalty` | 1 | 42 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::_class_satisfaction` | 1 | 57 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::_faction_satisfaction` | 1 | 48 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::_issue_row` | 1 | 69 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::_region_cannon` | 1 | 63 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::test_arrears_commitment_preserves_explicit_monthly_payment_target` | 1 | 697 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_cancelled_commitment_is_distinct_from_expired_commitment` | 3 | 957,958,964 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_character_loyalty_commitment_ongoing_applies_monthly_and_records_progress` | 5 | 161,163,168,170,171 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_end_turn_expires_without_resolve_effects` | 4 | 813,814,815,822 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_expiry_respects_outer_transaction_rollback` | 2 | 350,351 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_malformed_pay_target_does_not_fall_back_to_priority_pool` | 4 | 1092,1094,1095,1096 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_missing_purpose_still_routes_arrears_budget` | 2 | 1002,1006 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_monthly_ongoing_respects_outer_transaction_rollback` | 1 | 378 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_ongoing_economy_not_scaled_by_bar_discount` | 1 | 659 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_ongoing_malformed_entity_payloads_are_rejected_without_crashing` | 4 | 283,290,291,293 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_pay_pool_is_scoped_to_arrears_stop_gate_armies` | 2 | 1188,1189 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_progress_contexts_are_structured` | 2 | 560,561 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_progress_fractional_strict_gate_can_be_satisfied` | 3 | 589,607,625 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_progress_keeps_strict_stop_gate_semantics` | 2 | 1217,1218 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_progress_skips_non_numeric_gate_values` | 1 | 403 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_stop_gate_resolve_respects_outer_transaction_rollback` | 2 | 320,321 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_commitment_targeted_pay_uses_explicit_arrears_target` | 1 | 1047 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_created_future_limited_duration_commitment_applies_first_month` | 5 | 111,116,118,119,124 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_settlement_229.py::test_due_one_shot_commitment_ack_closes_review_loop_without_effects` | 8 | 1441,1443,1444,1446,1447,1452,1457,1458 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_commitment_settlement_229.py::test_end_turn_without_ongoing_is_not_expired_by_settlement_tick` | 4 | 1246,1252,1253,1254 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_faction_class_commitment_ongoing_applies_monthly_when_counted` | 4 | 245,246,251,253 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_high_bar_metric_only_commitment_applies_and_records_monthly_progress` | 5 | 726,727,732,734,735 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached` | 4 | 207,209,210,215 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_limited_duration_commitment_ticks_until_end_turn_then_expires` | 8 | 861,862,865,866,870,871,872,878 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_commitment_settlement_229.py::test_metadata_only_one_shot_commitment_acks_once` | 5 | 1372,1373,1374,1393,1394 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_metric_commitment_records_progress_when_monthly_cap_blocks_effect` | 4 | 771,776,778,779 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_non_arrears_commitment_missing_pay_target_does_not_open_priority_pool` | 4 | 1139,1142,1143,1144 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_commitment_settlement_229.py::test_one_shot_end_turn_commitment_stays_active_after_month` | 3 | 1284,1285,1286 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_region_cannon_commitment_ongoing_applies_monthly_when_counted` | 3 | 436,441,443 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_commitment_settlement_229.py::test_semantically_empty_one_shot_commitment_acks_once` | 6 | 1316,1317,1318,1337,1338,1341 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_until_stop_arrears_commitment_settlement_oracle_resolves_with_restore` | 16 | 495,496,497,498,506,507,510,513…+8 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_commitment_settlement_229.py::test_until_stop_condition_beats_later_end_turn_for_stacked_commitment` | 3 | 912,913,918 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::_active_people` | 1 | 17 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_dossiers_571.py::test_allocation_candidate_edit_preserves_mechanical_payload` | 4 | 1911,1912,1913,1917 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_dossiers_571.py::test_allocation_rejected_is_zero_effect_and_force_promulgation_keeps_rejection` | 9 | 533,535,536,542,543,544,546,547…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_appointment_alias_uses_canonical_dossier_identity` | 4 | 933,934,938,945 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_assignment_promulgation_tracks_executor_until_terminal_state` | 4 | 566,567,573,576 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_character_terminal_state_closes_secret_order_and_execution_slot` | 5 | 475,476,477,478,479 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_cli_dossiered_directive_is_not_listed_editable_or_deletable` | 4 | 1176,1177,1178,1179 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_dossiers_571.py::test_cli_no_edict_route_rejudges_held_proposed_dossier` | 1 | 1198 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_commitments_bind_explicitly_when_multiple_dossiers_share_a_turn` | 3 | 513,514,515 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_dossiers_571.py::test_committing_each_directive_creates_independent_restoreable_dossier` | 3 | 278,282,283 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_complete_rejection_verdict_is_restoreable_audit_record` | 6 | 2156,2157,2158,2159,2160,2161 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_create_secret_order_has_resumable_dossier` | 2 | 1384,1385 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_decree_dossiers_571.py::test_directive_assignee_projects_to_executor_only_for_executable_types` | 6 | 636,639,640,641,648,651 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_directive_edit_replaces_mechanical_payload_before_submission` | 2 | 1555,1560 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_decree_dossiers_571.py::test_dossier_append_is_idempotent_only_for_identical_character_entry` | 2 | 153,166 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_dossier_create_rejects_malformed_structured_roster` | 1 | 62 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_dossier_execution_accepts_sqlite_integer_id` | 2 | 687,690 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_dossier_execution_rejects_non_sqlite_integer_ids` | 2 | 669,670 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_dossier_roster_append_keeps_existing_entries_and_delegator` | 1 | 138 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_dossier_roster_preserves_multiple_leads_support_roles_and_knowers` | 1 | 38 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_dossier_roster_rejects_unknown_character_references_at_write_boundary` | 2 | 74,85 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_dossier_roster_write_boundary_rejects_invalid_delegator` | 2 | 109,118 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_durable_allocation_rejects_non_integer_amount_without_downgrade` | 2 | 2112,2113 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_durable_military_order_without_assignee_fails_loudly` | 2 | 2135,2136 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_executing_dossier_stays_visible_and_extractor_can_close_it` | 3 | 1814,1827,1830 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_executing_execution_record_never_closes_or_stamps_closed_turn` | 2 | 860,861 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_extractor_accepts_transformed_execution_outcome` | 3 | 905,909,910 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_extractor_never_reconstructs_missing_dossier_authority_from_live_db` | 2 | 253,254 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_final_decree_edit_path_removed_no_bypass` | 3 | 1144,1150,1151 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_force_promulgated_dossier_authorizes_same_batch_effect_after_execution_close` | 2 | 883,886 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_held_dossier_reenters_only_for_next_month_rejudgment` | 3 | 1399,1408,1416 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_immediate_terminal_payload_cannot_bypass_execution_surface` | 1 | 1943 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_in_transit_allocation_requires_execution_verdict` | 4 | 2082,2089,2090,2091 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_inner_treasury_admission_uses_actual_once_and_preserves_surface` | 9 | 1966,1967,1973,1974,1975,1976,1978,1979…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_malformed_dossier_origin_is_rejected_fail_closed` | 3 | 1847,1848,1849 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_military_directive_projects_normalized_due_turn_to_dossier` | 2 | 1714,1715 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_month_end_extractor_appends_self_dispatched_participant` | 2 | 189,192 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_month_end_participant_batch_rejects_each_malformed_item` | 3 | 221,222,224 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_office_action_waits_for_verdict_then_materializes_from_same_payload` | 4 | 428,429,437,438 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_payload_owned_appointment_dedup_preserves_same_person_different_effect` | 2 | 838,839 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_dossiers_571.py::test_payload_owned_appointment_dedup_removes_only_exact_mechanical_effect` | 1 | 766 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_payload_owned_appointment_dedup_uses_prior_item_runtime_office_type` | 4 | 803,804,805,809 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_probe_directive_shared_entry_creates_and_settles_structured_dossier` | 5 | 1498,1499,1500,1511,1512 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_rejection_contract_rejects_numeric_contamination_without_history` | 2 | 2250,2251 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_rejection_verdict_defaults_omitted_midzhi_marker_to_false` | 2 | 2172,2177 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_decree_dossiers_571.py::test_secret_authorization_dossier_does_not_map_payload_to_skill_grant` | 4 | 2030,2031,2037,2038 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_decree_dossiers_571.py::test_secret_order_and_dossier_roll_back_as_one_unit` | 1 | 462 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_decree_dossiers_571.py::test_secret_order_close_failure_rolls_back_only_its_two_axes` | 4 | 1336,1337,1338,1339 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_secret_order_commitment_origin_maps_to_its_own_dossier` | 1 | 1694 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_secret_order_progress_persists_executing_until_terminal` | 5 | 1270,1275,1278,1284,1285 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` | 2 | 1357,1358 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_secret_order_progress_undo_restores_order_and_dossier_axes` | 3 | 1309,1311,1312 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_secret_order_target_survives_restore_and_is_queryable` | 1 | 1883 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_decree_dossiers_571.py::test_secret_pending_action_carries_chat_turn_and_pending_provenance` | 5 | 383,384,385,386,387 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_structured_dossier_origin_deduplicates_extractor_but_narrative_applies` | 2 | 735,736 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_decree_dossiers_571.py::test_terminal_target_does_not_interrupt_another_executor` | 2 | 404,405 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py::test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled` | 3 | 1628,1629,1630 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_dossiers_571.py::test_underfunded_in_transit_allocation_closes_from_execution_state` | 3 | 1606,1607,1608 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_decree_dossiers_571.py::test_withdrawn_rescript_records_closed_turn` | 2 | 1866,1867 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_enable_thinking_still_disables` | 2 | 128,138 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_on_dashscope_uses_enable_thinking` | 1 | 52 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_on_hermes_emits_reasoning_disable` | 1 | 26 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_on_minimax_uses_endpoint_key` | 1 | 65 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_on_official_keeps_thinking_disabled` | 1 | 39 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_deepseek_strength_still_disables` | 1 | 113 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_non_deepseek_dashscope_strength_unchanged` | 1 | 152 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_non_deepseek_minimax_strength_unchanged` | 1 | 166 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_create_chat_model_non_deepseek_on_relay_unchanged` | 1 | 78 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py::test_dump_llm_messages_records_reasoning_usage_finish_reason` | 13 | 186,216,217,218,219,221,222,223…+5 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_deformation_dual_rail_622.py::_insert_final_stage` | 1 | 55 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_deformation_dual_rail_622.py::test_ac1_ac2_transformed_vs_degraded_dual_rail_tracer` | 22 | 107,109,110,114,121,127,128,129…+14 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_deformation_dual_rail_622.py::test_ac5_audit_fork_signal_present_only_with_audit_link` | 7 | 225,227,229,230,231,232,241 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_deformation_dual_rail_622.py::test_apply_economy_list_directed_pay_arrears_echoes_beyond_intent` | 22 | 285,286,287,288,295,296,297,298…+14 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_deformation_dual_rail_622.py::test_apply_economy_list_four_exit_effective_origin_receipt_matrix` | 26 | 494,495,496,497,500,502,503,527…+18 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_deformation_dual_rail_622.py::test_commitment_pooled_pay_arrears_inherits_beyond_intent` | 6 | 422,423,424,425,426,427 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_distance_matrix.py::test_bake_selects_fastest_route_and_preserves_triangle_inequality` | 2 | 42,43 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_distance_matrix.py::test_bake_uses_half_endpoint_weights_and_zero_diagonal` | 4 | 20,21,22,23 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_distance_matrix.py::test_baked_content_covers_all_regions_and_three_golden_anchors` | 14 | 67,68,69,70,71,72,73,74…+6 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_distance_matrix.py::test_runtime_reader_is_lookup_only` | 1 | 55 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_endorsements_612.py::test_endorsement_forms_persist_restore_and_judge_without_roster_join` | 12 | 88,95,96,97,99,103,104,105…+4 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_dossier_endorsements_612.py::test_endorsement_write_boundary_rejects_unknown_or_illegal_forms` | 1 | 170 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_dossier_endorsements_612.py::test_undo_chat_turn_removes_source_bound_endorsements_from_judge` | 6 | 182,191,195,196,202,203 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_confirmed_secret_order_materializes_links_through_pending_commit` | 2 | 116,119 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_force_promulgated_rejected_dossier_is_referenceable` | 2 | 167,168 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_dossier_links_559.py::test_one_protection_dossier_links_three_older_allocations_both_directions` | 3 | 32,33,35 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_only_confirmed_narrowed_references_are_persisted` | 2 | 49,50 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_pending_rejection_does_not_follow_reused_rolled_back_source_id` | 3 | 189,191,192 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_dossier_links_559.py::test_reference_candidates_hide_other_ministers_secret_dossiers` | 4 | 74,75,76,77 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_dossier_links_559.py::test_reference_candidates_obey_canonical_disclosure_blacklist` | 2 | 95,96 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited` | 4 | 134,136,137,139 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_dossier_links_559.py::test_unknown_target_link_is_rejected_and_audited` | 2 | 152,154 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_links_559.py::test_withdrawn_rejected_dossier_is_not_referenceable` | 1 | 178 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_reported_progress_619.py::_executing_assignment` | 2 | 33,34 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_dossier_reported_progress_619.py::test_fake_progress_report_does_not_change_world_state` | 2 | 270,271 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_reported_progress_619.py::test_production_terminal_sidepath_records_degraded_transformed_only` | 14 | 230,231,233,236,237,238,239,242…+6 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_dossier_reported_progress_619.py::test_restore_preserves_report_history` | 3 | 286,295,302 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_reported_progress_619.py::test_secret_monthly_path_unchanged_and_stays_on_private_rail` | 5 | 139,140,141,146,147 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_dossier_reported_progress_619.py::test_short_and_one_shot_dossiers_have_no_empty_monthly_shell` | 4 | 165,166,167,168 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_dossier_reported_progress_619.py::test_terminal_surface_dossier_rejects_reported_progress` | 2 | 333,336 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_draft_admission_resubmit_1769.py::_assert_error_pack_from` | 5 | 176,177,181,182,183 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_draft_admission_resubmit_1769.py::_finish_month_after_gazette` | 3 | 189,200,201 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_draft_admission_resubmit_1769.py::_latest_directive_id` | 1 | 221 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_draft_admission_resubmit_1769.py::test_advance_without_edict_vacuum_no_decree_issued` | 6 | 676,682,684,685,686,687 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_draft_admission_resubmit_1769.py::test_draft_admission_code_fault_aborts_with_error_pack` | 3 | 438,439,440 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_draft_admission_resubmit_1769.py::test_draft_admission_resubmit_code_fault_aborts_with_error_pack` | 3 | 463,464,465 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_draft_admission_resubmit_1769.py::test_draft_admission_resubmit_success_advances_month` | 24 | 269,270,276,279,280,281,282,286…+16 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py::test_pending_preview_turn_key_no_keyerror_on_issue` | 8 | 633,634,635,657,658,659,661,663 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::_executing_policy_dossier` | 1 | 68 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_due_review_621.py::_insert_staged_commitment` | 1 | 96 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::_promulgated_origin` | 1 | 50 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_due_review_621.py::_settle_empty_month` | 1 | 106 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_consumed_todo_does_not_resurrect_on_rescan` | 3 | 162,163,164 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_due_review_621.py::test_dossier_branch_negative_does_not_open_parallel_slot` | 2 | 338,339 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_dossier_branch_writes_execution_slot_via_adapter` | 6 | 299,301,306,307,308,310 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_due_month_extractor_blocked_before_todo_write` | 8 | 705,707,710,711,725,726,729,730 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_due_review_scene_tops_live_open_night_even_with_body` | 4 | 250,259,260,265 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_due_review_621.py::test_due_review_scene_tops_next_audience_with_origin_context` | 3 | 221,223,224 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_due_review_621.py::test_due_review_settle_does_not_pause_or_decision` | 6 | 585,586,588,589,590,591 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_final_stage_terminal_close_joint_liability_at_most_once` | 8 | 492,493,497,511,512,513,515,517 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_formal_review_blocks_extractor_second_terminal` | 3 | 639,679,686 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_due_review_621.py::test_fulfilled_with_prior_durable_effect_zero_double_post` | 3 | 773,792,794 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_input_closed_set_degrades_when_sources_missing` | 4 | 609,610,611,612 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_due_review_621.py::test_mark_todo_pending_to_consumed_is_idempotent` | 5 | 136,139,140,142,143 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_mid_stage_no_close_no_joint_liability` | 5 | 460,461,462,465,466 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_no_dossier_branch_negative_does_not_create_dossier` | 1 | 423 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_no_dossier_branch_only_scene_no_forged_dossier` | 6 | 374,377,378,381,383,384 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_p6_gap_visible_cause_not_auto` | 1 | 818 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_due_review_621.py::test_takeover_guard_fail_closed_on_ownership_error` | 2 | 757,758 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_due_review_621.py::test_three_beat_timing_todo_then_scene_then_slot` | 7 | 550,551,556,558,561,565,566 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_due_review_621.py::test_unconsumed_todo_rolls_across_settles_and_restore` | 6 | 181,189,190,199,200,201 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_float_and_bool_delta_rejected` | 1 | 128 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_issue_effect_bad_account_economy_reaches_reports` | 1 | 111 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_issue_effect_cancel_economy_reaches_reports` | 1 | 169 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_noop_bad_account_skipped_not_rejected` | 1 | 144 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_economy_section_rejections.py::test_top_level_bad_account_rejected_good_lands` | 3 | 44,45,46 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_top_level_nonint_delta_rejected` | 1 | 59 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_economy_section_rejections.py::test_valid_economy_still_applies_no_reject` | 2 | 73,74 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_economy_section_rejections.py::test_zero_delta_economy_no_reject_no_apply` | 1 | 86 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_effect_origin_558.py::test_army_pay_source_classifies_before_origin_gate_and_never_writes_without_origin` | 5 | 363,370,379,382,383 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_effect_origin_558.py::test_decree_driven_effect_without_any_origin_is_rejected` | 2 | 32,33 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_effect_origin_558.py::test_effect_origins_round_trip_and_missing_origin_is_rejected` | 6 | 55,56,57,59,60,61 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_effect_origin_558.py::test_entity_origin_gate_does_not_replace_reference_shape_or_noop_classification` | 3 | 306,307,308 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_effect_origin_558.py::test_fabricated_origin_is_rejected_even_without_a_dossier` | 4 | 210,211,212,213 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_effect_origin_558.py::test_fiscal_remove_keeps_durable_origin_tombstone` | 3 | 150,151,156 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_effect_origin_558.py::test_issue_close_effects_inherit_parent_canonical_origin` | 4 | 92,93,96,100 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_effect_origin_558.py::test_legacy_economy_ledger_origin_backfill_uses_real_dossier_only` | 1 | 188 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_effect_origin_558.py::test_missing_origins_are_rejected_at_entity_write_seams_without_logs` | 5 | 282,283,284,285,287 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_effect_origin_558.py::test_ordinary_entity_log_families_persist_origin_at_write_seam` | 1 | 233 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_effect_origin_558.py::test_power_backlash_from_allegiance_change_inherits_canonical_origin` | 4 | 244,255,260,261 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_effect_origin_558.py::test_same_issue_row_inertia_and_ongoing_reuse_parent_canonical_origin` | 3 | 129,130,133 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_effect_origin_558.py::test_zero_manpower_origin_gate_matches_actual_arrears_writeoff` | 7 | 329,330,336,337,344,349,355 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_empire_modifier_income_only_341.py::test_expenditure_not_amplified_by_legacy` | 2 | 18,23 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_empire_modifier_income_only_341.py::test_expenditure_zero_net_pct_unchanged` | 2 | 54,58 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_empire_modifier_income_only_341.py::test_income_still_modified_by_legacy` | 2 | 34,40 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enrich_list_guards.py::test_apply_economy_list_non_list_no_crash` | 1 | 33 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enrich_list_guards.py::test_apply_economy_list_skips_non_dict_items` | 2 | 70,71 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_enrich_list_guards.py::test_apply_economy_list_valid_still_works` | 2 | 40,41 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_enrich_list_guards.py::test_apply_metric_faction_class_dict_non_dict_no_crash` | 3 | 82,83,84 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enrich_list_guards.py::test_loads_effect_dict_coerces_non_dict` | 3 | 60,61,63 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::_open_night_with_unextracted_reply` | 1 | 136 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_enter_settlement_period_1235.py::_terminal_sse` | 1 | 120 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_accept_creator_atomic_only_one_true` | 3 | 415,418,420 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_advance_http_reject_after_accept_exits_display` | 6 | 457,460,462,464,465,467 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_awaiting_decision_still_emits_pending` | 6 | 389,390,391,393,396,397 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_enter_settlement_period_1235.py::test_concurrent_advance_noncreator_must_not_clear_owner_snapshot` | 10 | 486,487,489,496,498,500,501,503…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_exit_settlement_display_acquires_write_gate` | 7 | 519,521,547,548,557,558,559 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_session_reaccept_orphan_exits_after_owner_release` | 16 | 608,609,611,641,642,643,647,648…+8 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_settling_keeps_display_for_recovery` | 5 | 348,351,352,354,355 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_true_failure_issue_exits_display` | 7 | 327,329,330,331,333,334,335 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_true_failure_pending_translation_exits_display` | 11 | 264,266,267,269,271,273,275,277…+3 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_enter_settlement_period_1235.py::test_web_entry_captures_before_await_close` | 9 | 198,199,213,215,216,217,219,220…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_env_isolation.py::test_user_data_dir_is_isolated_from_repo_data` | 2 | 17,19 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_error_pack.py::test_mirror_writes_to_rejections_jsonl_path` | 1 | 106 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_error_pack.py::test_rejections_jsonl_path_in_error_dir` | 2 | 63,64 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_error_pack.py::test_version_read_failure_falls_back_to_unknown` | 1 | 178 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_error_pack.py::test_web_issue_endpoint_returns_structured_abort` | 4 | 140,141,142,143 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_escort_route_1900.py::_dossier_for_pending` | 1 | 29 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_escort_route_1900.py::test_commission_declares_escort_inside_same_grant_decree` | 7 | 50,52,53,55,60,80,85 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_escort_route_1900.py::test_commission_escort_names_must_exist` | 2 | 128,129 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_escort_route_1900.py::test_commission_malformed_escort_is_rejected_not_dropped` | 3 | 108,109,110 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_escort_route_1900.py::test_commission_without_escort_declares_none` | 2 | 143,144 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_event_chain_cascade.py::_terminal_state` | 1 | 57 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_event_chain_cascade.py::test_cascade_rolls_back_owned_transaction_on_later_write_failure` | 1 | 248 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_event_chain_cascade.py::test_conjunctive_positive_terminal_state_predicates_are_intersected` | 2 | 200,201 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_negative_dependency_invalidates_when_upstream_fired_forbidden_outcome` | 2 | 290,291 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_negative_dependency_is_satisfied_by_upstream_avoidance_not_invalidated` | 3 | 306,307,311 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_chain_cascade.py::test_negative_dependency_is_satisfied_by_upstream_expiry_not_invalidated` | 2 | 271,275 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_event_chain_cascade.py::test_numeric_triggered_gt_zero_dependency_invalidates_when_upstream_expires` | 2 | 95,96 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_numeric_triggered_lt_one_dependency_invalidates_when_upstream_triggers` | 2 | 111,112 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_positive_dependency_invalidates_when_upstream_expires` | 2 | 79,80 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_positive_outcome_dependency_waits_for_frozen_outcome_label` | 2 | 128,129 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_chain_cascade.py::test_soft_gate_failure_does_not_invalidate_chain_candidate` | 3 | 329,330,334 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_chain_cascade.py::test_terminal_state_expired_dependency_invalidates_when_upstream_obsolete` | 2 | 147,148 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_terminal_state_in_expired_or_obsolete_invalidates_when_upstream_triggered` | 2 | 163,164 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_chain_cascade.py::test_terminal_state_including_triggered_preserves_expired_alternative` | 3 | 179,180,184 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_chain_cascade.py::test_transitive_cascade_invalidates_downstream_closure` | 3 | 348,349,350 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_apply_event_terminal_states_does_not_commit_existing_transaction` | 3 | 423,424,426 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_apply_issue_entities_person_changes_respect_commit_false` | 2 | 2925,2926 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_appointment_rolls_back_with_outer_transaction` | 3 | 3667,3670,3674 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_class_delta_respects_outer_transaction_rollback` | 4 | 2979,2993,3006,3008 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_fiscal_changes_respect_outer_transaction_rollback` | 2 | 2967,2970 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_fiscal_create_and_remove_respect_outer_transaction_rollback` | 4 | 3104,3105,3108,3109 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_metric_delta_restores_runtime_on_outer_rollback` | 3 | 1504,1505,1508 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_top_level_economy_respects_outer_transaction_rollback` | 2 | 2945,2948 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_apply_score_extraction_top_level_entity_deltas_respect_outer_transaction_rollback` | 11 | 3026,3051,3052,3053,3054,3055,3058,3062…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_army_numeric_gate_preserves_fractional_arrears_tail` | 2 | 726,727 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_auto_trigger_historical_event_to_issue_uses_outer_transaction` | 2 | 838,839 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_auto_trigger_historical_events_use_preloaded_terminal_refs` | 1 | 2069 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_auto_trigger_seed_event_expires_after_latest_window_when_gate_unsatisfied` | 5 | 322,327,328,329,330 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_character_numeric_gate_supports_aggregation` | 2 | 713,714 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_character_numeric_gate_supports_comparison` | 3 | 698,700,701 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_character_text_gate_key_passes_content_validation` | 2 | 786,787 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_character_text_gate_rejects_numeric_character_field` | 1 | 801 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_character_text_gate_rejects_serialized_list_field` | 1 | 794 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_character_text_gate_supports_equality` | 3 | 757,758,759 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_direct_issue_tracker_rejects_strategic_event_without_world_state_delta` | 3 | 1011,1020,1021 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_apply_uses_pushed_candidate_snapshot_not_fresh_recompute` | 4 | 383,395,396,400 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_current_candidate_recheck_cached_until_state_changes` | 2 | 4474,4475 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_alias_appointment_blocks_canonical_gate` | 4 | 3717,3718,3719,3723 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_alias_disposition_blocks_canonical_gate` | 5 | 3774,3775,3780,3781,3782 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_allegiance_backlash_blocks_power_gate` | 3 | 3593,3594,3598 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_appointment_clears_reason_gate` | 4 | 4074,4079,4080,4081 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_appointment_displacement_blocks_displaced_office_gate` | 3 | 4018,4019,4023 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_appointment_normalizes_equivalent_office` | 2 | 4177,4178 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_appointment_updates_office_type_gate` | 2 | 4127,4128 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_disposition_clears_office_gate` | 4 | 3290,3303,3304,3308 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_gate_reuses_shadow_prefetch_across_new_issues` | 2 | 3909,3910 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_invalid_allegiance_change_does_not_block_gate` | 3 | 3250,3251,3252 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_invalid_appointment_does_not_block_gate` | 3 | 3205,3206,3207 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_invalid_location_does_not_block_gate` | 6 | 3143,3156,3157,3158,3159,3163 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_invalid_location_does_not_clear_transit_gate` | 6 | 3346,3359,3360,3361,3362,3366 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_legacy_power_change_blocks_gate` | 4 | 3446,3461,3462,3466 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_person_changes_are_simulated_sequentially` | 6 | 3633,3634,3635,3636,3637,3638 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_rejected_legacy_gate_change_does_not_block` | 2 | 3408,3409 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_rejected_vassal_appointment_does_not_block_gate` | 4 | 3953,3954,3955,3959 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_pending_same_power_allegiance_noop_does_not_block_gate` | 5 | 3524,3525,3526,3527,3531 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_rechecks_after_advances_close_gate` | 4 | 2523,2535,2536,2537 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_event_pool_rechecks_after_prior_event_effect_closes_gate` | 5 | 2584,2598,2599,2600,2601 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_situation_insert_respects_outer_transaction_rollback` | 2 | 1539,1546 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_event_pool_uses_candidate_snapshot_before_top_level_metric_delta` | 4 | 2473,2485,2486,2487 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_fiscal_levy_events_stay_out_of_model_candidate_pool` | 2 | 2346,2351 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_cond_form_error_numeric_and_text` | 3 | 494,495,496 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_cond_numeric_neq_rejected_text_neq_ok` | 5 | 604,605,606,607,608 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_gate_key_form_error_accepts_valid_forms` | 1 | 477 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_gate_key_form_error_rejects_typo_metric_table_structure` | 4 | 483,484,485,486 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_key_rejects_empty_class_name` | 3 | 634,635,636 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_key_rejects_empty_region_after_at` | 3 | 676,677,678 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_gate_key_rejects_empty_segments` | 4 | 614,615,616,617 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_passed_tolerates_none` | 1 | 441 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gate_passed_tolerates_nonstring_cond` | 2 | 449,450 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_gated_auto_trigger_seed_event_does_not_refire_after_issue_resolved` | 3 | 2112,2121,2122 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_gated_historical_event_excluded_when_unsatisfied` | 1 | 92 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_gated_historical_event_included_when_satisfied` | 1 | 106 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_gather_candidate_events_filters_expired_auto_trigger_seed_without_writing` | 4 | 355,356,367,368 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_henan_bandit_policy_delta_does_not_capture_untriggered_luoyang_event` | 3 | 1135,1136,1139 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_henan_place_policy_delta_does_not_capture_untriggered_fall_events` | 4 | 1102,1103,1104,1107 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_historical_auto_trigger_core_effect_is_applied_once` | 4 | 2046,2047,2048,2049 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_historical_auto_trigger_event_expires_after_latest_window` | 3 | 2090,2091,2092 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_historical_event_expires_after_latest_window_when_gate_unsatisfied` | 6 | 142,143,150,159,160,164 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_historical_event_gate_can_read_event_triggered_record` | 2 | 176,180 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_historical_event_latest_month_is_still_inside_window` | 2 | 201,206 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_historical_event_none_gate_no_crash` | 1 | 461 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_historical_event_triggered_gate_ignores_obsolete_terminal` | 1 | 220 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_historical_situation_auto_trigger_backfills_core_effect_for_existing_soft_issue` | 6 | 2191,2197,2210,2211,2216,2217 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_historical_situation_auto_trigger_rolls_back_soft_issue_when_core_effect_fails` | 2 | 2170,2174 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_event_trigger_gate.py::test_huabei_plague_auto_triggers_with_deterministic_core_effect` | 5 | 2017,2018,2019,2024,2025 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_huabei_plague_keeps_soft_degree_axis_as_situation_issue` | 2 | 2140,2145 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_event_trigger_gate.py::test_huangtaiji_chengdi_lands_only_when_model_picks_it` | 14 | 2267,2279,2280,2281,2282,2285,2300,2301…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_invalid_pending_person_change_does_not_block_event_gate` | 6 | 4335,4336,4337,4338,4339,4340 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_issue_191_person_core_events_are_explicitly_classified` | 3 | 1889,1890,1901 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_issue_194_dead_named_general_does_not_obsolete_strategic_foreign_event` | 3 | 1995,1996,2001 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_issue_194_strategic_foreign_events_are_explicitly_classified_and_gated` | 6 | 1966,1967,1968,1969,1970,1971 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_advance_effects_respect_outer_transaction_rollback` | 4 | 2703,2707,2708,2712 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_advance_respects_outer_transaction_rollback` | 3 | 2667,2671,2672 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_cancel_cost_respects_outer_transaction_rollback` | 3 | 4255,4259,4260 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_cancel_respects_outer_transaction_rollback` | 3 | 4212,4216,4217 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_close_effects_respect_outer_transaction_rollback` | 6 | 2791,2795,2797,2801,2802,2806 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_close_entity_effects_respect_outer_transaction_rollback` | 4 | 2845,2849,2850,2851 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_close_legacy_expiry_respects_outer_transaction_rollback` | 4 | 2887,2892,2893,2894 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_close_respects_outer_transaction_rollback` | 3 | 2743,2747,2748 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_decree_new_issue_respects_outer_transaction_rollback` | 2 | 2636,2640 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_rollback_removes_dynamic_character_attrs` | 1 | 1488 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_issue_tracker_rollback_restores_bound_content_when_content_omitted` | 4 | 1466,1467,1470,1471 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_jingshi_plague_auto_triggers_and_weakens_capital_garrison` | 5 | 2233,2234,2235,2240,2241 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_legacy_event_pool_issue_backfills_trigger_without_guessing_outcome` | 6 | 1655,1666,1667,1668,1669,1680 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_legacy_event_trigger_terminal_reason_can_be_filled_by_real_outcome` | 2 | 1703,1711 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_legacy_person_core_static_fields_backfill_reachability` | 8 | 1753,1754,1755,1761,1766,1772,1773,1782 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_li_chenghai_event_opens_after_li_zicheng_historical_debut` | 3 | 1835,1836,1837 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_lindan_xiqian_does_not_capture_untriggered_beizhili_border_policy_delta` | 3 | 1069,1070,1073 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_luoyang_fallen_not_obsoleted_when_fu_wang_is_dead` | 2 | 1817,1818 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_excluded_after_appeasement` | 1 | 879 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_excluded_after_player_reassigns_yuan` | 1 | 931 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_excluded_when_yuan_unavailable` | 6 | 4398,4407,4408,4409,4410,4411 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_obsolete_when_core_subject_already_dead` | 6 | 4355,4366,4367,4372,4373,4374 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_pool_duplicate_emit_is_idempotent` | 6 | 4499,4500,4501,4502,4503,4504 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_pool_rechecks_after_same_turn_loyalty_assessment` | 4 | 4285,4286,4287,4288 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_pool_rechecks_after_same_turn_yuan_dismissal` | 4 | 4310,4311,4312,4313 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_pool_rechecks_gate_before_effect` | 5 | 1568,1569,1570,1571,1572 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_pool_uses_candidate_snapshot_before_advances` | 4 | 2432,2444,2445,2446 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_remains_candidate_while_player_departure_is_in_transit` | 4 | 898,907,912,913 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_trigger_lands_character_status` | 5 | 944,954,955,956,957 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_mao_wenlong_event_trigger_respects_outer_transaction_rollback` | 5 | 1437,1440,1441,1442,1443 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_open_window_historical_event_never_expires` | 2 | 242,247 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_open_window_historical_event_still_waits_for_earliest_time` | 1 | 266 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_ordinary_army_station_delta_with_strategic_place_anchor_is_not_rejected` | 2 | 1041,1044 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_ordinary_jinzhou_preparedness_delta_is_not_rejected_as_songshan_outcome` | 2 | 978,981 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_pending_gate_uses_same_place_canonical_terminal_state` | 1 | 1390 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_pending_person_gate_prefetches_character_rows_for_displacement` | 2 | 3834,3835 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_event_trigger_gate.py::test_person_core_event_obsoletes_when_named_subject_is_dead` | 6 | 1587,1593,1594,1595,1598,1599 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_person_core_static_backfill_preserves_relocated_mao` | 1 | 1801 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_person_events_are_model_candidates_not_engine_hard_fired` | 5 | 2393,2396,2397,2398,2399 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_person_write_state_restore_removes_dynamic_character_attrs` | 1 | 1722 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_rejected_strategic_event_does_not_land_substitute_commander_person_delta` | 5 | 1367,1368,1369,1370,1371 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_rejected_strategic_event_preserves_unanchored_target_region_delta` | 3 | 1309,1310,1313 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_rejected_strategic_event_preserves_unrelated_person_delta` | 3 | 1335,1336,1337 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_rejected_strategic_foreign_event_preserves_unrelated_region_delta` | 2 | 1284,1285 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_seed_event_expires_after_latest_window_when_gate_unsatisfied` | 4 | 287,288,299,300 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_strategic_foreign_event_rejects_trigger_without_world_state_delta` | 3 | 991,1000,1001 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_target_person_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate` | 4 | 1259,1260,1261,1262 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_target_region_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate` | 4 | 1185,1186,1187,1190 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_text_cond_field_must_be_text_field` | 4 | 666,667,668,669 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_text_cond_requires_text_capable_key` | 5 | 643,644,645,646,647 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_ungated_historical_event_unchanged` | 1 | 120 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_event_trigger_gate.py::test_unrelated_person_delta_does_not_satisfy_strategic_event_result_gate` | 4 | 1211,1212,1213,1214 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_unrelated_person_delta_with_event_anchor_does_not_satisfy_strategic_event_result_gate` | 4 | 1235,1236,1237,1238 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_event_trigger_gate.py::test_unrelated_region_delta_does_not_satisfy_strategic_event_result_gate` | 3 | 1160,1161,1162 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_event_trigger_gate.py::test_yuan_xialing_event_excluded_after_jisi_border_contained_outcome` | 1 | 1637 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_yuan_xialing_event_excluded_without_jisi_triggered` | 1 | 1620 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_event_trigger_gate.py::test_zhangxianzhong_event_opens_after_historical_debut_and_surrender_path` | 3 | 1849,1850,1860 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_joint_liability_565.py::_executing_dossier` | 1 | 35 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_joint_liability_565.py::test_adapter_replay_is_idempotent_on_joint_liability_rows` | 3 | 146,154,159 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_assistant_row_delegator_gets_secondary_assistant_zero_mechanical` | 8 | 272,273,274,283,284,289,295,296 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_dead_liable_party_skips_satisfaction_but_enters_note` | 6 | 197,198,202,207,208,210 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_joint_liability_565.py::test_direct_record_dossier_execution_does_not_trigger_joint_liability` | 2 | 424,425 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_dual_role_lead_and_delegator_primary_wins` | 6 | 315,316,323,324,329,335 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_engine_auto_failed_materialize_writes_zero_joint_liability` | 3 | 182,183,184 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_execution_note_merge_interface_and_restore` | 8 | 394,398,399,400,401,410,411,412 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_joint_liability_565.py::test_explicit_affected_parties_must_pass_full_key_validation` | 9 | 231,232,233,237,238,249,250,251…+1 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_fulfilled_writes_zero_joint_liability_rows` | 5 | 75,76,77,78,79 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_liability_query_excludes_knowers_but_keeps_delegator_fk` | 6 | 365,366,367,368,369,370 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_joint_liability_565.py::test_living_offstage_delegator_still_charged` | 2 | 381,386 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_joint_liability_565.py::test_terminal_outcomes_charge_lead_and_downgraded_delegator` | 11 | 103,104,106,108,109,118,125,128…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_authorization_region_gets_single_locality` | 5 | 984,989,990,1001,1006 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_authorization_region_to_character_amendment_clears_single_locality` | 11 | 1091,1095,1096,1108,1112,1113,1118,1119…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py::test_cli_target_kinds_accepts_canonical_eight` | 4 | 756,757,758,763 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_create_decree_dossier_int_abi_single_row` | 2 | 359,361 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_execution_pressure_654.py::test_ensure_directive_dossier_returns_list` | 1 | 431 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_execution_pressure_654.py::test_get_dossier_for_directive_existence_sentinel` | 3 | 388,398,400 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_execution_pressure_654.py::test_grant_region_to_character_amendment_clears_single_locality` | 11 | 1031,1035,1036,1050,1054,1055,1060,1061…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py::test_locality_fail_create_decree_dossiers_zero_rows` | 1 | 750 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_locality_matrix_8x3_and_unknown` | 2 | 727,729 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_location_canonical_seed_and_write_seam` | 18 | 895,897,898,899,900,901,904,919…+10 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_execution_pressure_654.py::test_mapper_rejects_contradictory_locality_scope_without_overwrite` | 11 | 62,63,67,68,80,84,85,97…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_pressure_654.py::test_named_lead_bulk_single_region_syncs_executor` | 5 | 338,340,344,345,346 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py::test_national_creates_one_row_idempotent` | 8 | 271,273,274,280,281,282,295,296 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_execution_pressure_654.py::test_national_policy_is_one_dossier_not_per_province` | 1 | 131 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_normalize_locality_scope` | 1 | 35 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_normalize_payload_locality_and_target_kind` | 4 | 443,453,454,455 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_pressure_654.py::test_path1_conversational_draft_bad_roster_marks_failed` | 3 | 652,656,660 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_execution_pressure_654.py::test_region_id_column_and_composite_indexes` | 7 | 210,218,219,221,223,224,226 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_execution_pressure_654.py::test_region_outside_province_set_yields_empty_locality` | 1 | 164 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_region_single_by_id` | 1 | 150 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_revoke_decree_523_producer_durable_oracle_chain` | 17 | 809,814,815,816,817,823,824,825…+9 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_special_decree_without_national_is_single_empty` | 1 | 145 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_pressure_654.py::test_validate_all_unknown_roster_name_zero_rows_before_insert` | 2 | 527,528 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_execution_tenure_613.py::_clear_character_offices` | 2 | 64,65 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_execution_tenure_613.py::_executing_policy` | 1 | 25 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_tenure_613.py::_set_tenure` | 2 | 17,18 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_execution_tenure_613.py::test_td8_same_office_four_tenures_live_assembly_chain` | 9 | 44,47,48,49,52,54,56,57…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_executor_routing_721.py::test_appointment_routes_to_appointee_at_creation` | 1 | 157 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_executor_routing_721.py::test_create_dossier_nails_roster_lead_in_canonical_insert_and_restore` | 2 | 70,78 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py::test_existing_delegated_lead_is_preserved_not_demoted` | 4 | 105,106,107,108 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_executor_routing_721.py::test_legacy_character_executor_migrates_without_overriding_roster` | 2 | 145,148 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py::test_national_policy_is_one_dossier_without_province_routing` | 2 | 445,447 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_executor_routing_721.py::test_new_appointee_identity_exists_before_promulgation_and_leads_dossier` | 3 | 173,183,190 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_executor_routing_721.py::test_production_assignee_is_named_route` | 3 | 123,125,126 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_executor_routing_721.py::test_punishment_stage_rejects_unmapped_category_before_pending_or_dossier` | 3 | 271,272,273 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_executor_routing_721.py::test_punishment_without_admitted_strike_subtype_is_excluded` | 3 | 50,51,52 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_executor_routing_721.py::test_real_assignment_stage_lead_comes_from_extract_not_summoned_minister` | 6 | 224,225,227,241,246,247 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_executor_routing_721.py::test_real_punishment_stage_preserves_category` | 1 | 260 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_executor_routing_721.py::test_rolled_back_collector_reuse_does_not_mirror_orphan` | 3 | 373,374,375 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_executor_routing_721.py::test_unknown_appointee_normalizes_unrecognized_faction` | 1 | 207 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_faction_brew_637.py::_eligible_dossier` | 1 | 399 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_any_endpoint_hit_selects_and_same_faction_dedups` | 3 | 112,117,118 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_authority_revoke_edge_reaches_holder_faction_with_emperor_target` | 9 | 446,456,462,463,468,475,480,481…+1 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_brew_637.py::test_both_endpoints_different_factions_both_selected` | 6 | 129,133,134,138,139,140 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_canonical_projection_intersects_existing_factions_only` | 6 | 92,93,95,98,99,100 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_faction_brew_637.py::test_event_month_updates_stance_and_no_event_month_byte_identical` | 8 | 174,175,176,186,187,189,190,191 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_faction_brew_637.py::test_faction_brew_prompt_retry_month_does_not_label_old_events_as_current_month` | 13 | 607,609,611,617,620,622,624,625…+5 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_faction_brew_637.py::test_failed_faction_brew_rebrews_once_via_existing_pending_seam` | 14 | 208,209,210,213,215,228,229,230…+6 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_brew_637.py::test_malformed_faction_output_degrades_and_keeps_old_summary_bytes` | 5 | 266,268,269,277,278 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_new_event_fields_are_pure_data_no_prose_composition` | 4 | 493,505,506,507 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_new_events_preserve_source_target_equal_to_db_rows` | 4 | 412,422,424,425 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_faction_brew_637.py::test_out_of_table_faction_and_unknown_person_never_projected` | 4 | 153,158,159,160 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_brew_637.py::test_relation_and_faction_items_share_single_batch_in_parallel` | 2 | 328,329 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_brew_637.py::test_source_faction_target_faction_equals_current_projection_and_nulls_and_no_concatenation` | 19 | 518,519,520,522,543,550,551,553…+11 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_faction_brew_637.py::test_zero_writes_to_factions_numeric_columns_across_all_seams` | 6 | 340,347,364,365,370,371 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_class_section_rejections.py::_valid_class_key` | 1 | 34 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_class_section_rejections.py::_valid_faction` | 1 | 26 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_class_section_rejections.py::test_flat_class_delta_rejected_while_nested_sibling_lands` | 3 | 190,203,204 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_faction_class_section_rejections.py::test_float_and_bool_class_values_rejected` | 2 | 138,139 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_class_section_rejections.py::test_float_and_bool_faction_values_rejected` | 2 | 157,161 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_class_section_rejections.py::test_illegal_class_value_rejected` | 3 | 119,120,121 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_class_section_rejections.py::test_illegal_faction_value_rejected` | 2 | 102,103 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_class_section_rejections.py::test_issue_effect_faction_rejection_reaches_reports` | 2 | 243,244 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_class_section_rejections.py::test_unknown_class_rejected_good_item_lands` | 4 | 83,84,85,87 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_class_section_rejections.py::test_unknown_faction_rejected_good_item_lands` | 4 | 53,54,55,58 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_class_section_rejections.py::test_valid_flat_int_faction_not_rejected` | 2 | 178,181 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_faction_class_section_rejections.py::test_zero_delta_faction_not_rejected` | 1 | 217 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_faction_denunciation_627.py::_pair_enemy` | 1 | 53 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_denunciation_627.py::test_ac2_scripted_accept_and_clamp` | 9 | 258,260,261,262,263,266,267,277…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_denunciation_627.py::test_ac3_veracity_true_and_false_from_fork` | 9 | 302,306,321,322,323,324,326,327…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_denunciation_627.py::test_ac4_dedup_upgrade_closed_and_restore` | 13 | 348,352,353,364,365,371,372,383…+5 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_faction_denunciation_627.py::test_ac5_zero_template_exposure_and_622` | 12 | 460,463,466,467,468,471,475,478…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_denunciation_627.py::test_fork_predicate_pure_and_single_source_expression` | 4 | 210,213,216,219 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_faction_denunciation_627.py::test_veracity_derivation_mechanical_and_origin_marks` | 6 | 226,227,231,232,233,234 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_denunciation_627.py::test_world_materials_exclude_secret_fork_from_gazette` | 1 | 161 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_active_member_empty_office_contributes_zero_weight` | 2 | 383,394 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_add_character_appointment_lifts_faction_leverage` | 5 | 343,351,352,355,357 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_faction_leverage_9.py::test_all_court_allowed_types_have_leverage_weight` | 2 | 639,644 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_calibrated_save_without_marker_not_re_anchored` | 3 | 932,933,944 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_chat_rollback_restores_faction_leverage` | 2 | 995,1004 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_faction_leverage_9.py::test_col_added_uncalibrated_save_recalibrates_on_open` | 4 | 860,877,880,883 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_displaced_minister_faction_leverage_recomputed` | 6 | 255,256,257,263,264,266 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_faction_leverage_9.py::test_faction_leverage_drops_when_core_minister_ousted` | 2 | 33,37 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_leverage_9.py::test_faction_leverage_rises_back_when_minister_restored` | 3 | 44,53,54 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_leverage_9.py::test_failed_appointment_rolls_back_faction_leverage` | 4 | 210,229,231,235 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_half_weight_odd_baseline_no_round_drift` | 3 | 1051,1057,1067 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_jundadou_deputy_ouster_impact_is_half_of_principal` | 3 | 586,590,591 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_legacy_save_calibrates_offset_on_open` | 2 | 800,804 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_leverage_clamps_at_zero_no_negative` | 2 | 328,331 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_neiting_has_leverage_weight_like_other_court_eunuchs` | 3 | 621,624,626 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_faction_leverage_9.py::test_non_whitelist_faction_delta_direct_leverage_survives_reconcile` | 3 | 736,740,744 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_non_whitelist_faction_row_leverage_not_recomputed` | 4 | 66,69,74,78 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_leverage_9.py::test_office_rank_aux_titles_audit_offices_json` | 16 | 559,560,561,562,564,565,566,568…+8 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_office_rank_deputy_titles_not_inflated_to_principal` | 18 | 524,525,526,527,529,530,531,532…+10 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_office_weight_takes_highest_domain_across_joint_offices` | 4 | 507,509,511,513 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_offset_not_re_anchored_on_reload_after_clamp` | 1 | 298 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_old_integer_offset_migrated_to_float` | 5 | 1085,1090,1111,1113,1117 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_power_id_defection_drops_faction_leverage_immediately` | 2 | 1026,1034 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_faction_leverage_9.py::test_promotion_via_set_character_office_raises_leverage` | 1 | 197 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_faction_leverage_9.py::test_rank_tier_modulates_impact` | 4 | 108,109,119,120 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_faction_leverage_9.py::test_recompute_all_reconciles_drift_from_unhooked_path` | 4 | 425,428,441,453 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_reconcile_runs_before_clear_gated_legacies_same_turn` | 4 | 482,487,493,494 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_faction_leverage_9.py::test_restore_uses_new_office_weight_not_old` | 6 | 161,162,164,168,173,177 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_rollback_snapshot_restores_leverage_offset` | 1 | 975 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_weizhongxian_ouster_drops_yandang_by_sili_weight` | 2 | 658,663 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_faction_leverage_9.py::test_whitelist_faction_delta_routes_to_offset_survives_reconcile` | 2 | 678,685 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_whitelist_faction_delta_survives_full_settlement` | 2 | 720,723 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_faction_leverage_9.py::test_xingbu_has_leverage_weight_like_other_ministries` | 2 | 604,609 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_faction_leverage_9.py::test_xixue_faction_in_whitelist_drops_when_member_ousted` | 2 | 88,92 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_family_tail_615.py::_board_with_td4_three` | 7 | 99,100,101,102,103,104,105 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_family_tail_615.py::_grant_self_scope_authority` | 1 | 80 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_family_tail_615.py::_stage_break_rank_acting` | 2 | 52,53 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_family_tail_615.py::test_break_rank_appointment_rescript_td4_tracer` | 31 | 143,144,145,146,171,172,173,174…+23 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_family_tail_restore_570.py::_face` | 1 | 40 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_family_tail_restore_570.py::test_mid_month_restore_keeps_dossier_four_faces` | 12 | 109,157,158,159,160,161,162,163…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::_executing_policy` | 1 | 39 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_fiscal_beyond_intent_1260.py::_insert_final_stage` | 1 | 70 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::_prime_and_apply_due_review` | 1 | 87 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s1_engine_grant_fiscal_create_stays_beyond_intent_zero` | 3 | 308,311,312 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s1_fiscal_changes_beyond_intent_tracer_and_negatives` | 6 | 190,206,211,232,239,240 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s1_fiscal_creates_beyond_intent_tracer_and_negatives` | 7 | 132,135,136,142,168,175,176 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s1_fiscal_removes_beyond_intent_tracer_and_negatives` | 5 | 262,277,282,283,291 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s2_pure_fiscal_beyond_intent_transformed_fork_backlash` | 11 | 340,343,345,349,350,358,359,365…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s2_pure_fiscal_without_beyond_intent_fulfilled_no_backlash` | 4 | 415,416,421,454 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_beyond_intent_1260.py::test_s3_nested_ongoing_economy_alias_旨外恶果_lands_ledger` | 2 | 504,505 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_bad_region_does_not_redistribute_jiao_lian_targets` | 4 | 400,402,403,404 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass` | 5 | 503,505,506,516,517 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_capstone_golden_all_seeded_provinces` | 7 | 226,237,239,253,259,265,266 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_components_are_land_share_calibrated_and_marked_provisional` | 3 | 1116,1122,1128 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_emperor_rejection_lands_outcome_without_levy` | 2 | 709,711 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_existing_terminal_reason_is_whitelist_validated` | 1 | 690 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_expired_pending_choice_is_terminalized` | 3 | 611,612,613 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_gate_waits_until_1631_and_generic_terminal_pass_skips_it` | 5 | 1256,1260,1268,1274,1275 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_held_petition_is_supplied_to_next_world_segment` | 8 | 1542,1547,1548,1549,1554,1555,1556,1557 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed` | 4 | 455,456,466,467 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_is_not_auto_approved_without_emperor_decision` | 4 | 535,538,548,549 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_outcome_is_written_once_and_first_verdict_wins` | 3 | 727,732,733 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_outcome_label_outside_closed_set_aborts` | 1 | 746 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_pending_choice_waits_for_event_window` | 4 | 805,811,812,824 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_pending_stop_choice_keeps_jiao_in_force_same_tick` | 2 | 774,779 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_petition_reaches_emperor_desk_and_lands_only_after_choice` | 11 | 1357,1362,1364,1365,1366,1377,1378,1383…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_rewrites_nonnumeric_current_targets_from_meta` | 2 | 352,353 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_skips_bad_settle_shape_without_blocking_other_regions` | 2 | 325,327 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_fiscal_levy_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass` | 2 | 290,292 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_independent_petition_outcome_commits_for_another_connection` | 5 | 1689,1698,1702,1703,1712 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_levy_effect.py::test_jiao_levy_rises_then_stops_and_keeps_base_transport` | 8 | 934,938,939,954,958,959,960,961 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_jiao_levy_stop_rejected_keeps_levy_in_force` | 1 | 1017 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_jiao_stop_is_obsolete_when_start_was_rejected` | 2 | 1030,1035 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_fiscal_levy_effect.py::test_later_illegal_outcome_does_not_discard_the_first_ruling` | 2 | 1672,1673 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_fiscal_levy_effect.py::test_levy_retreat_recomputes_transport_without_active_rate_change` | 2 | 992,993 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_lian_levy_gate_waits_until_1639_and_needs_no_stop_event` | 6 | 1211,1217,1228,1234,1240,1241 | `KEEP_STRUCTURED_OR_HARNESS` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_levy_effect.py::test_lian_levy_start_approved_updates_settle_before_fiscal_tick` | 6 | 647,648,649,652,653,659 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_lian_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p` | 8 | 1071,1076,1088,1089,1090,1091,1095,1099 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_levy_effect.py::test_liao_levy_rewrites_numeric_string_targets_to_canonical_numbers` | 4 | 894,895,896,902 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_liao_levy_rise_approved_by_emperor_updates_settle_before_fiscal_tick` | 6 | 124,125,126,129,130,136 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_liao_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p` | 7 | 845,855,856,857,858,862,866 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_levy_effect.py::test_lost_seeded_province_keeps_current_levy_rate_and_uses_it_on_restore` | 8 | 1163,1164,1170,1178,1179,1188,1189,1190 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_non_event_world_question_is_not_bound_to_the_only_due_levy` | 5 | 1450,1455,1457,1467,1468 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_fiscal_levy_effect.py::test_rejected_levy_identity_does_not_write_a_terminal_from_a_sibling_envelope` | 5 | 1497,1498,1499,1504,1505 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_levy_effect.py::test_same_batch_keeps_the_first_event_outcome` | 2 | 1597,1598 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_fiscal_levy_effect.py::test_shaanxi_primary_source_liao_seed_keeps_opening_transport_cap` | 4 | 93,94,95,96 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_levy_effect.py::test_unbound_envelope_does_not_overwrite_the_first_event_outcome` | 12 | 1626,1627,1628,1629,1630,1631,1646,1647…+4 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_levy_effect.py::test_unpresented_fiscal_levy_declaration_leaves_terminal_empty` | 2 | 1421,1422 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::_assert_hub_conservation_oracle` | 9 | 235,238,239,240,247,250,253,254…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::_assert_hub_oracle_mutation_fails` | 2 | 274 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py::test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic` | 3 | 4868,4872,4873 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | 7 | 4674,4675,4677,4678,4679,4681,4682 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_all_15_regular_provinces_first_tick_golden` | 2 | 3456,3467 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_fiscal_substrate_bridge.py::test_all_ming_settle_substrates_advance_through_fixed_flows` | 6 | 4892,4893,4903,4908,4912,4913 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_all_settle_substrate_provisional_meta_covers_virtual_fields` | 3 | 4985,4987,4989 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_advances_shaanxi_substrate` | 5 | 4233,4236,4237,4238,4239 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone` | 2 | 4854,4855 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_container_isolated` | 4 | 4733,4734,4736,4737 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_json_isolated` | 4 | 4759,4760,4762,4763 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated` | 3 | 4800,4802,4803 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_apply_fixed_period_flows_uses_dynamic_ming_settle_spine` | 4 | 4263,4264,4265,4270 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_fiscal_substrate_bridge.py::test_armies_provision_empty_mutiny_status_flag` | 3 | 2237,2238,2239 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_arrears_reconciles_pay_source_container_immediately` | 1 | 2522 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_arrears_rejects_exempt_army_under_cutover` | 4 | 2507,2508,2509,2510 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_arrears_splits_positive_and_rejects_negative_under_cutover` | 6 | 2465,2466,2467,2468,2474,2478 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_manpower_reconciles_pay_source_due_immediately` | 2 | 2551,2552 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_owner_power_from_ming_clears_pay_source_arrears` | 21 | 2674,2675,2683,2684,2685,2686,2687,2688…+13 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_owner_power_to_ming_requires_same_delta_pay_source` | 8 | 2575,2576,2595,2596,2597,2598,2599,2600 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_rejects_ming_exempt_flag_before_pay_arrears_writeoff` | 7 | 2743,2744,2764,2765,2766,2767,2770 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_rejects_pay_source_without_ming_settle_substrate` | 2 | 2665,2666 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_delta_rejects_unknown_owner_power_without_clearing_arrears` | 3 | 2634,2635,2636 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_army_pay_source_spine_seed_splits_arrears_and_reconciles_tusi` | 31 | 436,446,447,448,449,450,451,462…+23 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_beizhili_huangzhuang_is_inner_treasury_not_transport_quota` | 7 | 4077,4078,4079,4080,4081,4084,4085 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_border_slice_raw_content_keeps_primary_source_anchors` | 18 | 3782,3783,3784,3787,3788,3789,3790,3791…+10 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_budget_lines_read_persisted_substrate_hub_income_source` | 3 | 1499,1502,1503 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_budget_projection_preserves_persisted_fiscal_snapshots` | 3 | 1452,1453,1454 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_conservation_rejects_excluded_army_with_pay_source_debt` | 1 | 682 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_conservation_rejects_province_source_army_without_settle_base` | 1 | 707 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack` | 4 | 4480,4481,4482,4483 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | 5 | 4576,4577,4579,4580,4582 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | 5 | 4529,4530,4532,4533,4534 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_pay_source_errors_abort_fixed_flows` | 7 | 4419,4420,4422,4426,4427,4428,4429 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack` | 4 | 4602,4603,4605,4606 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | 5 | 4451,4452,4454,4455,4456 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack` | 4 | 4552,4553,4555,4556 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_dongjiang_content_pay_funnel_survives_fresh_db_pay_source_reconcile` | 2 | 3917,3918 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_economy_pay_arrears_clamps_integer_spend_and_preserves_tail` | 6 | 3005,3009,3010,3011,3012,3013 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_economy_pay_arrears_from_central_account_can_repay_pure_province_source_army` | 8 | 2855,2856,2881,2885,2888,2889,2890,2893 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_economy_pay_arrears_from_central_account_splits_by_current_debt_ratio` | 10 | 2787,2788,2789,2819,2823,2826,2829,2832…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_economy_pay_arrears_preserves_fractional_pay_source_tail` | 9 | 2945,2946,2947,2948,2949,2950,2951,2952…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_economy_pay_arrears_rejects_missing_or_unknown_target_without_repaying_other_armies` | 6 | 3072,3073,3074,3075,3076,3077 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fiscal_config_v8_migration_preserves_deleted_old_keys` | 3 | 2125,2130,2134 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flow_loader_accepts_already_decoded_fiscal_dict` | 2 | 4813,4814 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flow_loader_rejects_decoded_non_dict_payloads` | 2 | 4836,4837 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flow_loader_rejects_non_finite_numeric_values` | 2 | 4825,4826 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_cutover_uses_total_source_shortfall_for_mixed_army_morale` | 4 | 2444,2445,2446,2447 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_books_split_treasury_income_and_central_losses` | 24 | 1317,1329,1330,1334,1336,1337,1338,1339…+11 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_central_capacity_reduces_current_central_arrears` | 6 | 904,908,909,910,911,912 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_central_pay_carries_transport_loss_without_jingyun` | 28 | 1154,1155,1156,1157,1158,1159,1160,1161…+19 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_central_pay_shares_hub_tier_with_jingyun_grants` | 26 | 1003,1004,1005,1006,1007,1008,1009,1010…+13 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_failure_rolls_back_cutover_writes` | 5 | 2046,2047,2048,2049,2050 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_fractional_due_caps_integer_debit` | 10 | 1873,1874,1875,1876,1877,1878,1879,1880…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_integer_allocation_drives_all_consumers` | 6 | 1752,1753,1754,1755,1756,1759 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_retires_global_central_pay_route` | 6 | 757,761,762,765,767,768 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_fresh_save_pay_source_prefers_content_army_fields` | 3 | 554,555,556 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_henan_royal_grants_make_zonglu_due_heavy` | 5 | 4095,4096,4097,4098,4099 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due` | 5 | 4060,4061,4064,4065,4066 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_jiangnan_core_seeds_have_positive_remittance_golden` | 11 | 4035,4037,4038,4039,4040,4044,4045,4046…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_jiangnan_core_uses_wanli_huiji_lu_primary_seed` | 19 | 5040,5041,5042,5043,5045,5046,5050,5051…+11 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_liaodong_and_dongjiang_are_pure_military_pay_funnels` | 10 | 3818,3819,3820,3821,3822,3823,3824,3827…+2 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_fiscal_substrate_bridge.py::test_liaodong_pay_source_rows_add_to_standalone_military_funnel` | 3 | 3867,3869,3873 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_liaodong_primary_source_due_survives_fresh_db_pay_source_reconcile` | 3 | 3838,3844,3845 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_liaodong_settle_tick_keeps_standalone_funnel_deficit_out_of_pay_rows` | 5 | 3890,3905,3906,3907,3911 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_manpower_zero_then_arrears_delta_does_not_resurrect_writeoff_debt` | 7 | 3174,3175,3176,3177,3178,3179,3180 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_manpower_zero_writeoffs_pay_source_arrears_before_retiring_army` | 11 | 3125,3126,3127,3128,3129,3130,3131,3132…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_new_ming_army_rejects_initial_arrears_under_cutover` | 3 | 3277,3278,3279 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_new_ming_army_rejects_non_ming_pay_source_region` | 2 | 3221,3222 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_new_ming_army_requires_valid_pay_source_under_cutover` | 2 | 3195,3196 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_new_ming_army_stores_pay_source_columns_under_cutover` | 10 | 3241,3249,3250,3251,3252,3253,3254,3256…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_old_dongjiang_pay_funnel_due_backfills_before_new_pay_rows` | 3 | 3938,3942,3943 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_pay_source_conservation_rejects_per_army_derived_arrears_drift` | 1 | 2537 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_pre_s6_cutover_save_without_fiscal_engine_migrates_to_substrate_hub` | 6 | 2073,2077,2078,2085,2088,2092 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_substrate_bridge.py::test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | 5 | 4630,4631,4633,4634,4635 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_province_pay_shortfall_reduces_pure_province_army_morale` | 10 | 2199,2200,2201,2202,2211,2212,2213,2214…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_province_tick_derives_due_and_allocates_province_arrears_by_pay_source` | 11 | 634,638,639,640,641,646,647,659…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_region_army_morale_haircut_denominator_includes_standalone_funnel` | 6 | 1974,1975,1976,1977,1978,1979 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_region_army_pay_tick_treats_missing_breakdown_as_no_delta` | 4 | 1888,1913,1914,1915 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_region_loader_expands_shared_settle_meta_defaults` | 8 | 424,425,426,427,428,429,431,432 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack` | 5 | 4706,4707,4709,4710,4711 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_seed_royal_stipends_use_wanli_accounting_by_province` | 9 | 109,111,114,115,116,120,128,134…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_seeded_substrates_keep_multi_tick_historical_trajectories` | 4 | 4930,4941,4943,4946 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_fiscal_substrate_bridge.py::test_self_funded_seed_arrears_log_preserves_fractional_delta` | 4 | 526,527,528,529 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_fiscal_substrate_bridge.py::test_settle_province_tick_persists_border_remainder_golden` | 4 | 4158,4161,4163,4170 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_settle_province_tick_persists_shaanxi_historical_shadow_golden` | 4 | 4127,4128,4129,4134 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_settle_province_tick_port_lock_no_persist_on_raise` | 1 | 4204 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_settle_province_tick_qingzhang_action` | 2 | 4186,4187 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_fiscal_substrate_bridge.py::test_settling_context_retry_does_not_recompute_substrate_hub_pre_settle` | 6 | 840,844,845,846,847 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_shaanxi_seed_is_relabelled_to_historical_shadow_scale` | 25 | 3724,3725,3726,3727,3728,3729,3730,3731…+17 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues` | 18 | 3758,3759,3760,3761,3762,3763,3764,3767…+10 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_south_southwest_seeds_have_valid_historical_settle_substrate` | 33 | 3634,3635,3639,3641,3642,3643,3644,3645…+25 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_south_southwest_settle_tick_golden_and_bridge_persist` | 4 | 3711,3712,3713,3717 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_standalone_army_pay_container_total_uses_grouped_arrears` | 1 | 3984 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_absent_does_not_break_flows` | 2 | 4289,4291 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_corrupt_due_isolated` | 2 | 4330,4332 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_corrupt_isolated_from_flows` | 2 | 4308,4310 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_corrupt_stock_isolated` | 2 | 4351,4353 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_hub_cutover_runs_multi_tick_treasury_trajectory` | 7 | 809,810,818,819,820,821 | `KEEP_FISCAL_ORACLE` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_hub_display_name_collision_books_user_fiscal_exact` | 4 | 1542,1548,1560,1561 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_hub_dual_track_sanity_keeps_legacy_calc_as_reference` | 6 | 781,782,783,784,785,786 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_hub_uses_month_opening_treasury_before_lower_priority_expenses` | 5 | 1649,1650,1651,1652,1663 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_malformed_fiscal_container_is_logged_not_prefiltered` | 2 | 4396,4397 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_substrate_malformed_settle_shape_is_logged_not_prefiltered` | 3 | 4378,4379,4380 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_substrate_bridge.py::test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills` | 2 | 1423,1441 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_fiscal_substrate_bridge.py::test_tusi_self_funded_army_skips_pay_morale_channel` | 2 | 2363,2364 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_zero_due_province_army_morale_short_circuits` | 4 | 2308,2309,2310,2311 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_zhongyuan_jingshi_primary_source_refinement` | 19 | 3517,3518,3519,3520,3521,3522,3524,3525…+11 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_fiscal_substrate_bridge.py::test_zhongyuan_jingshi_settle_province_tick_golden` | 4 | 4108,4110,4111,4120 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_tick.py::_assert_end` | 1 | 29 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_fiscal_tick.py::test_conservation_error_is_distinct_type` | 2 | 174,176 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_fiscal_tick.py::test_fiscal_g9_three_tick_death_spiral` | 1 | 161 | `KEEP_FISCAL_ORACLE` | 财政 conservation/hub oracle，外部账守恒契约 |
| `tests/test_fiscal_tick.py::test_fiscal_golden` | 1 | 91 | `KEEP_FISCAL_ORACLE` | 财政 conservation/hub oracle，外部账守恒契约 |
| `tests/test_grant_reconciliation_567.py::_in_transit_grant` | 1 | 73 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_grant_reconciliation_567.py::test_1745_full_chain_player_state_no_fake_awaiting` | 7 | 331,332,333,334,335,336,340 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_close_merges_recon_note_without_second_treasury_debit` | 9 | 141,145,146,157,159,161,162,164…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_empty_targets_no_recon_rows` | 4 | 284,285,286,289 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_escort_progress_stays_on_the_secret_order_and_survives_restore` | 5 | 119,120,122,127,131 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_failed_close_reconciles_only_when_the_silver_already_left` | 27 | 186,187,188,190,209,212,213,214…+19 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_normal_close_same_turn_still_reconciles` | 5 | 299,300,303,304,305 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_prior_turn_close_is_not_re_reconciled` | 4 | 315,317,318,320 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_grant_reconciliation_567.py::test_settle_entry_lands_engine_arrival_per_route` | 5 | 273,274,276,277,278 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_highlight_judge_544.py::test_build_chat_projection_includes_minister_highlights` | 4 | 115,119,121,122 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_highlight_judge_544.py::test_highlights_survive_db_restore` | 3 | 159,171,174 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_highlight_judge_544.py::test_read_night_scroll_includes_minister_highlights` | 4 | 135,140,141,145 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_highlight_judge_544.py::test_run_highlight_judge_success_returns_phrases` | 1 | 74 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_highlight_judge_544.py::test_run_highlight_judge_timeout_and_exception_degrade_silently` | 2 | 43,53 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_history_decree_text_1843_reopen.py::test_history_turn_reads_decree_text_from_resolve_context` | 4 | 18,25,27,28 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_identity_seed_488.py::test_existing_save_migrates_seed_identity_and_inserts_missing_roster_member` | 4 | 71,72,73,74 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_identity_seed_488.py::test_identity_and_seed_guilt_are_loaded_from_roster_and_seeded` | 6 | 17,18,19,24,25,26 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_identity_seed_488.py::test_identity_and_seed_guilt_survive_restore` | 4 | 43,45,46,47 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_identity_seed_488.py::test_required_dig_7_seed_roster_entries_are_persisted` | 5 | 95,101,103,106,107 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_identity_seed_488.py::test_roster_has_no_cross_faction_aliases` | 1 | 118 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_impeachment_surge_655.py::_active_pair` | 1 | 53 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_impeachment_surge_655.py::test_apply_accepts_only_current_candidate_closed_target_and_free_text` | 5 | 158,160,161,162,165 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_impeachment_surge_655.py::test_delegator_only_responsible_is_eligible_target` | 7 | 104,106,107,108,109,110,112 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_impeachment_surge_655.py::test_dynamic_apply_deduplicates_same_candidate_within_input_snapshot` | 3 | 223,224,225 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_impeachment_surge_655.py::test_dynamic_apply_rejects_blank_title_wrong_faction_and_outside_target` | 2 | 179,180 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_impeachment_surge_655.py::test_dynamic_apply_rejects_non_text_free_fields_without_coercion` | 2 | 268,269 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_impeachment_surge_655.py::test_dynamic_targets_are_roleless_deduplicated_without_participant_roles` | 6 | 195,196,200,201,202,207 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_impeachment_surge_655.py::test_knower_departure_does_not_veto_active_responsible_dossier` | 6 | 135,137,138,139,140,141 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_impeachment_surge_655.py::test_leverage_boundary_and_authoritative_input_snapshot` | 3 | 280,292,299 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_impeachment_surge_655.py::test_target_roster_survives_generic_issue_restore` | 3 | 247,248,249 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_impeachment_surge_655.py::test_transformed_candidate_fails_closed_outside_window_or_without_liability` | 2 | 307,310 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_impeachment_surge_655.py::test_transformed_without_beyond_intent_yields_no_surge_candidate` | 2 | 80,81 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_intrigue_concealment_1896.py::test_current_format_reopen_keeps_seeded_and_played_intrigue` | 3 | 51,59,62 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_intrigue_concealment_1896.py::test_intrigue_is_seeded_from_roster_and_persisted` | 5 | 35,36,37,39,40 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_intrigue_concealment_1896.py::test_intrigue_reaches_character_input_only_as_a_qualitative_band` | 3 | 91,92,93 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_intrigue_concealment_1896.py::test_new_character_enters_roster_with_intrigue` | 2 | 78,79 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_issue_decree_token_1277.py::test_double_issue_same_token_second_is_409_turn_plus_one` | 8 | 76,91,92,97,99,100,101,102 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_api_channel_initiative_does_not_use_backend_env_floor` | 3 | 505,506,507 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_apply_score_extraction_accepts_flat_faction_scalar` | 2 | 335,336 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_issue_entities.py::test_apply_score_extraction_rejects_nondict_list_item_per_item` | 1 | 350 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_issue_entities.py::test_apply_score_extraction_rejects_nondict_power_second_level_per_entity` | 1 | 343 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_issue_entities.py::test_apply_score_extraction_rejects_unknown_top_level_key` | 3 | 374,375,376 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_issue_entities.py::test_apply_score_extraction_splits_bad_nested_entity` | 1 | 322 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_issue_entities.py::test_apply_score_extraction_tolerates_null_field` | 2 | 361,362 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_empty_effect_noop` | 1 | 312 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_inertia_natural_fail_applies_entities` | 1 | 574 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_issue_entities.py::test_inertia_natural_resolve_applies_entities` | 1 | 525 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_issue_entities.py::test_inertia_natural_resolve_applies_unified_person_change_with_bound_content` | 2 | 556,557 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_issue_entities.py::test_initiative_floor_applies_when_enrich_empty` | 2 | 442,444 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_issue_entities.py::test_issue_unified_person_change_shadows_legacy_person_effects` | 5 | 240,241,242,243,244 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_issue_entities.py::test_legacy_issue_status_change_does_not_use_month_end_active_gate` | 2 | 120,121 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_issue_entities.py::test_legacy_issue_status_change_uses_person_transition_matrix` | 2 | 90,91 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_issue_entities.py::test_new_issue_nondict_effect_fields_do_not_crash` | 2 | 426,427 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_resolve_applies_unified_person_change_effect` | 4 | 191,192,193,194 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_issue_entities.py::test_resolve_army_delta_reinforces_existing` | 2 | 388,389 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_resolve_changes_character_status` | 3 | 56,57,62 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_issue_entities.py::test_resolve_character_status_syncs_content_travel_state` | 6 | 158,159,160,161,162,163 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_issue_entities.py::test_resolve_creates_army` | 3 | 43,45,46 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_issue_entities.py::test_runtime_cli_initiative_floor_applies_without_backend_env` | 2 | 473,474 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_junxin_alias_loyalty_313.py::test_junxin_alias_maps_to_loyalty_not_morale` | 4 | 38,39,50,51 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_alias_loyalty_313.py::test_junxin_and_shiqi_aliases_independent` | 2 | 91,92 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_alias_loyalty_313.py::test_shiqi_alias_still_maps_to_morale` | 4 | 61,62,73,74 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_monthly_tick_314.py::test_army_loyalty_tick_delta_tiers` | 7 | 59,60,61,62,63,64,65 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_monthly_tick_314.py::test_self_funded_army_untouched_on_hub` | 1 | 179 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_monthly_tick_314.py::test_substrate_hub_hybrid_source_loyalty_regression` | 3 | 139,144,145 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_junxin_monthly_tick_314.py::test_substrate_hub_path_loyalty_tier` | 2 | 79,83 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_monthly_tick_314.py::test_substrate_hub_pure_province_source_loyalty_regression` | 3 | 108,113,114 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_junxin_monthly_tick_314.py::test_tusi_and_non_ming_untouched_on_hub` | 2 | 163,164 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_junxin_monthly_tick_314.py::test_zero_manpower_army_no_crash_no_tick_on_hub` | 1 | 193 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_llm_channel_config.py::test_cli_empty_cli_model_does_not_leak_api_model_to_runner` | 5 | 766,767,770,771,774 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_cli_reasoning_strength_runners_single_source_in_cli_backend` | 1 | 805 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_cli_supports_reasoning_strength_matrix` | 1 | 798 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_create_chat_model_keeps_top_p_for_non_reasoning_api_models` | 2 | 357,358 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_llm_channel_config.py::test_create_chat_model_leaves_openai_reasoning_default_unset` | 1 | 372 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_create_chat_model_maps_off_reasoning_to_openai_none` | 1 | 125 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_create_chat_model_maps_reasoning_strength_to_dashscope_thinking_budget` | 1 | 387 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py::test_create_chat_model_maps_reasoning_strength_to_minimax_thinking` | 1 | 402 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py::test_create_chat_model_never_injects_max_tokens` | 2 | 229,231 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_llm_channel_config.py::test_create_chat_model_off_reasoning_keeps_minimal_for_legacy_o1` | 1 | 156 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_create_chat_model_off_reasoning_keeps_minimal_for_o3_o4` | 1 | 173 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_llm_channel_config.py::test_create_chat_model_off_reasoning_uses_none_for_gpt56_not_version_list` | 1 | 141 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_create_chat_model_omits_default_headers_when_empty` | 2 | 276,277 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_llm_channel_config.py::test_create_chat_model_passes_default_headers_at_transport_boundary` | 3 | 251,252,253 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_create_chat_model_respects_api_channel_over_backend_env` | 2 | 26,27 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_create_chat_model_strips_provider_prefix_for_reasoning_family` | 6 | 181,182,183,184,194,204 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_create_chat_model_strips_top_p_for_openai_reasoning_family` | 4 | 337,338,341,342 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_llm_channel_config.py::test_create_chat_model_uses_cli_channel_without_backend_env` | 6 | 45,46,47,49,50,52 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_llm_channel_config.py::test_for_role_advanced_empty_cli_model_no_api_model_leak` | 4 | 744,745,747,748 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_for_role_preserves_cli_channel_fields_for_advanced_roles` | 4 | 698,699,700,701 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_gate_evidence_config_omits_max_tokens` | 1 | 898 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_legacy_backend_env_uses_runner_default_model_not_api_model` | 2 | 446,447 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_load_llm_config_cli_env_uses_cli_default_timeout_not_api` | 3 | 710,711,712 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_llm_channel_config.py::test_load_llm_config_migrates_legacy_advanced_thinking_to_reasoning` | 4 | 92,93,94,95 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_load_llm_config_migrates_legacy_none_thinking_to_off` | 1 | 109 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_load_llm_config_records_backend_env_as_cli_channel` | 4 | 61,62,63,64 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_llm_channel_config.py::test_loaded_api_config_is_not_rerouted_by_later_backend_env` | 3 | 74,75,76 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_minimax_reasoning_strength_overrides_stale_thinking_level` | 1 | 420 | `KEEP_LLM_CONFIG_SURFACE` | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py::test_scene_and_rescript_entries_pass_default_headers_at_transport` | 4 | 315,316,320,321 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_llm_channel_config.py::test_web_runtime_cli_no_saved_timeout_uses_cli_default` | 3 | 727,728,729 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_canonical_and_alias_same_event_do_not_double_count_negative` | 6 | 192,193,195,196,197,198 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_canonical_and_alias_same_event_do_not_double_count_positive` | 6 | 176,177,179,180,181,182 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_deterministic_tick_plus_five_unaffected_by_soft_clamp` | 1 | 112 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_dynamic_mutiny_cap_still_hard_ceiling_after_soft_clamp` | 1 | 90 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_fake_exemption_markers_do_not_bypass_soft_clamp` | 1 | 156 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_junxin_alias_also_soft_clamped` | 1 | 166 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_negative_delta_floors_at_zero` | 1 | 80 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_negative_large_delta_clamped_to_minus_15` | 1 | 70 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_positive_large_delta_clamped_to_plus_15` | 4 | 56,58,59,60 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_loyalty_soft_adjust_clamp_320.py::test_single_narrative_cannot_max_out_loyalty` | 2 | 122,123 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_manual_directive_institution_normalize_1279.py::_assert_decree_reached_backend` | 1 | 44 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_manual_directive_institution_normalize_1279.py::_capture_ids` | 1 | 72 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_adr0053_unknown_person_still_rejected_at_capture` | 1 | 235 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_capture_manual_directive_drops_collective_and_institution_names` | 5 | 195,196,197,198,199 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_capture_manual_directive_drops_ministry_name_as_participant` | 6 | 90,92,101,102,111,118 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_capture_manual_directive_keeps_real_person_participant` | 1 | 144 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_capture_manual_directive_keeps_surname_title_aliases` | 1 | 166 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_non_person_filter_does_not_use_institution_substring_class` | 10 | 207,208,209,211,212,213,214,215…+2 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_manual_directive_institution_normalize_1279.py::test_seeded_draft_accepts_ministry_subject_without_409` | 3 | 130,131,133 | `KEEP_STRUCTURED_OR_HARNESS` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_material_directory_1830.py::test_character_materials_exclude_legacy_raw_turn_report_and_keep_public_gazettes` | 3 | 251,254,255 | `KEEP_FIXTURE_OR_SEED` | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_material_directory_1830.py::test_material_tree_contains_only_structurally_related_world_details` | 3 | 93,110,113 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_material_directory_1830.py::test_matter_carriers_follow_the_real_knowledge_projection` | 2 | 152,154 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_material_directory_1830.py::test_prepare_fails_loud_when_dossier_read_breaks` | 1 | 169 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_material_directory_1830.py::test_prepare_writes_typed_tree_and_index` | 8 | 47,48,49,50,51,52,53,55 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_material_directory_1830.py::test_read_material_stays_inside_directory` | 7 | 184,190,191,197,201,202,203 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_material_directory_1830.py::test_same_requested_root_creates_independent_material_invocations` | 3 | 70,71,72 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_material_directory_1830.py::test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error` | 1 | 277 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_memorial_inbox_1726.py::test_mark_read_binds_to_row_not_dossier_and_persists` | 11 | 112,115,117,118,126,128,129,136…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_memorial_inbox_1726.py::test_new_game_memorial_inbox_empty` | 3 | 44,45,47 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_memorial_inbox_1726.py::test_progress_and_denunciation_project_as_memorials` | 12 | 76,80,84,85,86,87,90,93…+4 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_memorial_inbox_1726.py::test_progress_without_owner_uses_diegetic_fallback` | 3 | 240,241,242 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_memorial_inbox_1726.py::test_state_payload_memorials_and_mark_read_api` | 12 | 193,195,197,198,199,200,206,207…+4 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_menu_continue_stream_1195.py::test_menu_continue_404_when_no_main_db` | 1 | 105 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_minister_chat_timeout.py::_save_idle_threshold_via_settings_api` | 2 | 47,48 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_month_chain_1843.py::test_edict_that_drops_unrest_below_gate_does_not_trigger_world_event` | 2 | 772,773 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1843.py::test_edict_that_raises_unrest_over_gate_triggers_after_the_edict` | 2 | 783,784 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1843.py::test_failed_declaration_commit_reloads_memory_from_db` | 4 | 398,407,408,411 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_chain_1843.py::test_held_dossier_settlement_failure_retry_and_reentry_isolation` | 8 | 482,483,487,488,489,493,494,496 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1843.py::test_staged_ending_is_available_inside_its_settlement_transaction` | 4 | 363,364,365,366 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects` | 18 | 2035,2036,2037,2038,2039,2042,2044,2048…+10 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1847.py::test_declared_deposal_ends_on_the_existing_chain` | 5 | 1121,1122,1123,1124,1125 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1847.py::test_null_emperor_fate_does_not_end_the_month` | 4 | 1131,1132,1133,1134 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1847.py::test_pending_disclosures_share_commit_boundary_with_effects` | 7 | 2259,2260,2262,2266,2267,2271,2272 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_chain_1847.py::test_settle_edicts_persists_pending_disclosures_in_same_transaction` | 3 | 1746,1749,1803 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::_assert_court_break_closed` | 9 | 499,500,502,506,507,509,510,516…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::_assert_not_bare_500` | 2 | 144,148 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::_choices_from_decisions` | 1 | 224 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::_get_state` | 2 | 187,188 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_month_loop_tracer_1468.py::_pending_payload` | 2 | 196,197 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_month_loop_tracer_1468.py::_plant_extraction_debt` | 1 | 397 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_month_loop_tracer_1468.py::_post_issue_stream` | 6 | 256,257,260,270,278,281 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::_resolve_decisions_via_stream` | 4 | 297,298,299,300 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_loop_tracer_1468.py::_setup_open_night_participant` | 7 | 470,471,474,482,483,485,487 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_loop_tracer_1468.py::test_issue_extraction_llm_dead_single_source_not_cta` | 13 | 415,416,421,433,435,439,440,441…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_awaiting_decision_keeps_month_open_money_and_pending` | 5 | 126,127,128,129,130 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_capture_before_mutation_on_advance_without_edict` | 1 | 294 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_capture_before_mutation_on_resolve_turn_entry` | 1 | 261 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_capture_is_idempotent_and_turn_bound` | 2 | 76,77 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_clear_on_month_complete_returns_live_values` | 3 | 161,162,163 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_cross_month_snapshot_does_not_bleed` | 2 | 176,177 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_fresh_connection_same_face` | 3 | 143,144,145 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_oracle_normal_phase_clears_via_startup_hook` | 5 | 188,191,192,200,202 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_oracle_settling_phase_keeps_display_for_recovery` | 4 | 215,216,219,220 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_open_snapshot_1234.py::test_player_month_advance_expires_snapshot` | 4 | 305,306,308,309 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_state_payload_live_when_no_snapshot` | 2 | 103,105 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_open_snapshot_1234.py::test_state_payload_overlays_snapshot_when_present` | 4 | 92,94,95,96 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::_army_id` | 1 | 105 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_month_translate_1840.py::_region_id` | 1 | 111 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_month_translate_1840.py::test_final_strategic_rejection_leaves_no_owned_effects` | 2 | 916,917 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_hidden_affair_new_army_alone_does_not_trigger` | 5 | 839,840,841,842,843 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_hidden_affair_new_army_does_not_block_sibling_result` | 6 | 799,800,803,804,805,806 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_hidden_affair_strategic_result_does_not_trigger_or_land` | 3 | 726,727,728 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_pre_push_segment_translation_stages_declaration_without_world_writes` | 11 | 150,151,152,154,155,156,159,160…+3 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_translate_1840.py::test_staged_month_declarations_settle_in_given_order_and_effects_are_idempotent` | 11 | 373,380,381,384,391,394,396,397…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_translate_1840.py::test_staged_month_effects_keep_input_reference_authority` | 6 | 516,519,521,523,524,525 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_unknown_station_region_new_army_does_not_trigger_or_land` | 4 | 872,873,874,875 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_world_segment_applies_domain_effects_and_reports_rejected_effects` | 25 | 215,280,282,283,284,287,290,297…+17 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_world_segment_effects_use_frozen_visible_affairs` | 3 | 471,472,473 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_world_segment_explicit_stock_transfers_share_actual_amount` | 7 | 24,45,46,50,56,59,67 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_translate_1840.py::test_world_segment_failure_rolls_back_only_current_segment` | 1 | 448 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_month_translate_1840.py::test_world_segment_rejects_transfer_with_pay_arrears_claim` | 10 | 88,89,91,92,93,94,95,98…+2 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_month_translate_1840.py::test_world_segment_repeated_entity_effects_apply_in_order` | 6 | 556,557,558,562,563,565 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_month_translate_1840.py::test_world_segment_repeated_strategic_results_apply_in_order` | 17 | 660,661,662,666,667,668,669,670…+9 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_month_translate_1840.py::test_world_segment_translates_once_and_persists_repeated_subject_facts_in_order` | 3 | 197,204,205 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_actual_residence_659.py::test_fresh_seed_station_region_and_class_slices` | 7 | 151,152,153,154,155,156,157 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_actual_residence_659.py::test_redeploy_moves_fact_region_keeps_pay_source` | 8 | 95,109,113,114,115,122,123,124 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_mutiny_actual_residence_659.py::test_station_region_rejects_unknown_region_id` | 2 | 135,139 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_mutiny_latch_315.py::test_arrears_spiral_enters_mutiny_only_after_both_conditions` | 2 | 82,84 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_latch_315.py::test_derive_mutiny_state_boundaries_and_latch` | 1 | 125 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_latch_315.py::test_exempt_armies_preserve_mutiny_latch` | 1 | 143 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_latch_315.py::test_mutiny_exits_at_40_only_when_arrears_have_retired` | 1 | 101 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_latch_315.py::test_mutiny_latch_enters_only_beyond_four_months_arrears` | 2 | 152,155 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_latch_315.py::test_mutiny_latch_exits_only_within_four_months_arrears` | 1 | 164 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_latch_315.py::test_mutiny_latch_holds_beyond_four_months_arrears` | 1 | 173 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_latch_315.py::test_mutiny_stays_latched_while_loyalty_recovers_below_40` | 1 | 92 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_latch_315.py::test_raised_loyalty_alone_does_not_release_latch` | 1 | 108 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_apply_score_extraction_respects_latched_field_gate` | 4 | 458,459,460,461 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_chinese_aliases_same_rules` | 4 | 354,355,356,357 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_cutover_denies_pay_source_fields` | 1 | 478 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_cutover_mixed_item_pay_source_deny_whitelist_apply` | 3 | 551,552,553 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_cutover_rejects_invalid_pay_source_share` | 2 | 497,498 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_cutover_rejects_unknown_pay_source_region` | 2 | 517,518 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_denies_dispatch_armament_status_and_positive_manpower` | 1 | 154 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_loyalty_at_mutiny_cap_preflight_rejects_strategic_envelope` | 4 | 277,295,296,299 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_loyalty_legacy_flip_preflight_rejects_strategic_envelope` | 3 | 255,256,259 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_loyalty_positive_applies_negative_noop` | 2 | 188,193 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_loyalty_raw_positive_noop_when_legacy_flips_effect_sign` | 2 | 213,214 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_manpower_strict_negative_applies_zero_and_positive_noop` | 3 | 166,171,176 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_noop_whitelist_319.py::test_latched_mixed_item_allows_and_denies_per_field` | 4 | 325,326,327,328 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_non_latched_army_writes_all_legal_fields` | 6 | 389,390,391,392,393,394 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_noop_whitelist_319.py::test_non_latched_cutover_pay_source_fields_still_write` | 4 | 579,581,582,584 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_noop_whitelist_319.py::test_pay_clear_via_economy_moves_next_tick_loyalty_plus_5` | 7 | 402,419,422,423,424,429,430 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_progression_316.py::test_mutiny_count_is_capped_at_three` | 4 | 114,115,117,118 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_mutiny_progression_316.py::test_old_save_migrates_and_mutiny_progress_survives_reopen` | 6 | 132,136,149,150,154,155 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_progression_316.py::test_repeated_mutiny_persists_count_cap_and_probation` | 14 | 59,64,68,72,77,81,82,87…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_redemption_317.py::test_army_delta_clamps_loyalty_to_dynamic_mutiny_cap` | 1 | 124 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_redemption_317.py::test_full_pay_streak_can_be_saved_in_peace_and_partial_pay_resets_it` | 2 | 94,98 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_redemption_317.py::test_redemption_progress_migrates_and_survives_reopen` | 2 | 140,153 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_redemption_317.py::test_twelve_consecutive_full_pay_months_redeem_once_and_raise_cap` | 3 | 63,68,78 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_third_strike_318.py::test_empty_source_delta_cannot_defect_latched_first_or_second_strike` | 4 | 267,268,269,271 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_mutiny_third_strike_318.py::test_hub_excluded_persisted_third_strike_defects_once` | 6 | 550,551,552,556,559,563 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_mutiny_third_strike_318.py::test_hub_excluded_zero_manpower_latched_clears_once` | 4 | 456,457,458,465 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_mutiny_third_strike_318.py::test_non_latched_generic_owner_change_still_works_via_adapter` | 6 | 303,304,305,306,319,320 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_third_strike_318.py::test_persisted_third_strike_defects_next_tick_once` | 8 | 478,479,480,481,485,489,490,494 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_mutiny_third_strike_318.py::test_persisted_third_strike_defects_on_recovery_boundary` | 7 | 507,508,509,513,517,518,522 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_mutiny_third_strike_318.py::test_third_strike_does_not_repeat_while_already_bandit` | 4 | 189,194,195,199 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_third_strike_318.py::test_third_strike_transfers_to_bandit_via_adapter` | 17 | 122,126,127,128,129,130,131,132…+9 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_mutiny_third_strike_318.py::test_transfer_to_ming_rejects_mutiny_count_ge_3` | 3 | 362,363,364 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_mutiny_third_strike_318.py::test_transfer_to_ming_requires_d6_pay_source` | 7 | 394,395,419,420,421,422,423 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_mutiny_third_strike_318.py::test_zero_manpower_latched_clears_before_continue_no_third_strike` | 5 | 212,213,214,215,221 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_named_characters_seed_484.py::test_r3_named_characters_load_legal_guilt_and_historical_offices` | 14 | 17,18,21,22,23,24,25,31…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_named_characters_seed_484.py::test_r4_hu_tingyan_loader_and_db_preserve_non_holder_seed` | 2 | 46,51 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_named_characters_seed_484.py::test_r4_named_characters_debut_in_historical_order` | 14 | 57,65,66,67,68,69,70,72…+6 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_named_characters_seed_484.py::test_r5_loader_preserves_zero_identity` | 1 | 176 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_named_characters_seed_484.py::test_r6_xu_yingqiu_uses_verified_ministry_line_and_opening_status` | 6 | 93,94,95,96,97,98 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_new_game_dependency_mismatch_1721.py::test_continue_stale_agno_sse_carries_typed_dependency_facts` | 7 | 111,117,119,120,122,123,124 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_game_smoke.py::test_existing_office_fk_violation_is_normalized_on_reopen` | 3 | 139,140,141 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_new_game_smoke.py::test_new_game_enforces_foreign_keys_without_seed_violations` | 2 | 77,78 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_new_game_smoke.py::test_new_game_has_fiscal_substrate` | 2 | 70,72 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_new_game_smoke.py::test_person_title_kind_does_not_materialize_office_parent` | 2 | 109,112 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_game_smoke.py::test_unknown_event_id_fails_without_synthesizing_parent` | 1 | 86 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_game_smoke.py::test_unknown_office_type_fails_without_synthesizing_parent` | 1 | 98 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_game_write_path_1749.py::_assert_chat_persisted` | 8 | 239,240,241,242,243,244,245,246 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_game_write_path_1749.py::_chat_stream` | 8 | 208,209,211,214,215,217,219,221 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_game_write_path_1749.py::_rewrite_draft_via_http` | 3 | 192,193,195 | `KEEP_STRUCTURED_FIELD` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_new_game_write_path_1749.py::_seed_draft` | 1 | 177 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_game_write_path_1749.py::_write_and_verify_live` | 4 | 261,264,265,266 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_new_game_write_path_1749.py::test_gamesession_load_state_failure_closes_partial_resources` | 1 | 505 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_new_game_write_path_1749.py::test_load_save_close_fail_restores_writable_old_game` | 11 | 516,518,531,532,533,534,535,538…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_new_game_write_path_1749.py::test_new_game_construct_failure_keeps_old_writable` | 8 | 445,447,467,468,469,470,477,478 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_new_issues_section_rejections.py::test_authoritative_event_pool_rejects_same_batch_obsolete_event` | 4 | 418,435,436,437 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_new_issues_section_rejections.py::test_event_to_issue_duplicate_returns_none_not_raise` | 2 | 386,388 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_new_issues_section_rejections.py::test_new_issue_bad_kind_rejected` | 2 | 169,170 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_bool_float_int_field_rejected` | 2 | 289,290 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_dirty_coercion_field_rejected` | 2 | 157,158 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_dirty_inertia_rejected` | 2 | 180,181 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_event_pool_rejects_expired_event` | 3 | 401,402,403 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_falsy_nonstring_kind_rejected` | 2 | 301,302 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_garbage_severity_rejected` | 2 | 271,272 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_infinity_expected_months_rejected_not_abort` | 2 | 247,248 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_infinity_field_rejected_not_abort` | 2 | 236,237 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_non_dict_cancel_cost_tolerated` | 2 | 490,493 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_non_dict_item_rejected_not_crash` | 2 | 141,142 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_non_string_tag_element_rejected` | 2 | 462,463 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_oversized_severity_clamped_not_abort` | 2 | 194,197 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_scalar_string_tags_rejected` | 2 | 453,454 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_severity_zero_preserved` | 2 | 259,261 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_valid_cancel_cost_preserved` | 2 | 503,506 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_valid_decree_still_creates` | 3 | 329,332,333 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_new_issues_section_rejections.py::test_new_issue_valid_list_tags_preserved` | 2 | 472,475 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_new_issues_section_rejections.py::test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition` | 5 | 215,219,220,225,226 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_new_issues_section_rejections.py::test_temp_events_replaces_same_id_and_restores_original` | 4 | 123,124,127,128 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_no_edict_full_settlement_1274.py::test_no_edict_fast_path_branch_is_dead` | 5 | 92,93,94,95,96 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_no_edict_full_settlement_1274.py::test_no_edict_zero_decisions_completes_without_stuck` | 6 | 109,110,111,112,113,114 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_no_edict_full_settlement_1274.py::test_web_no_edict_endpoint_routes_to_full_settlement` | 5 | 185,186,187,188,189 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_no_edict_full_settlement_1274.py::test_with_edict_resolve_turn_still_full_settlement` | 5 | 143,144,145,146,147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_office_inference.py::test_appointment_seat_identity_reuses_local_and_strips_central` | 16 | 292,297,298,299,306,307,308,309…+8 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_inference.py::test_office_type_from_table` | 1 | 49 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_office_inference.py::test_sync_preserves_persisted_court_office_type_on_table_miss` | 1 | 242 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_office_inference.py::test_sync_restores_office_region_from_character_offices` | 3 | 269,270,271 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_inference.py::test_unknown_falls_to_daiquan_without_backend` | 1 | 59 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_inference.py::test_后宫_current_type_short_circuits` | 1 | 53 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_office_rank_562.py::test_appointment_dossier_uses_declared_type_for_uncommon_target_title` | 2 | 74,75 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_office_rank_562.py::test_existing_proposed_appointment_dossier_gets_one_time_break_rank_backfill` | 2 | 196,203 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_rank_562.py::test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once` | 7 | 245,246,249,256,261,262,271 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_office_rank_562.py::test_recognizable_archive_title_survives_blank_or_legacy_office_type` | 2 | 218,219 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_rank_562.py::test_restoration_and_displaced_third_state_use_latest_historical_office` | 14 | 101,102,107,108,109,119,120,124…+6 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_office_rank_562.py::test_same_rank_demotion_and_two_band_promotion_follow_upward_formula` | 6 | 82,83,86,90,91,95 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_office_rank_562.py::test_seed_archives_clean_historical_office_for_dismissed_ministers` | 12 | 285,286,287,290,291,292,299,300…+4 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_office_rank_562.py::test_unofficed_and_offstage_degree_labels_are_genuine_first_appointments` | 2 | 164,165 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_office_rank_562.py::test_white_body_high_appointment_is_marked_but_regular_first_office_is_not` | 4 | 38,45,46,53 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_on_scene_immediate_write_1839.py::test_commission_stays_staged_not_bypassing_promulgation` | 7 | 253,254,259,265,266,268,274 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_show_it` | 4 | 87,88,92,94 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_on_scene_immediate_write_1839.py::test_night_bound_sections_reject_missing_or_foreign_source_chat_turn` | 9 | 204,205,206,220,221,222,223,224…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_on_scene_immediate_write_1839.py::test_textual_fact_and_public_saying_land_and_show_in_materials` | 6 | 118,120,126,127,129,130 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_opening_gazette_delete_1356.py::test_new_game_t0_previous_reign_period_label_empty_with_empty_summary` | 4 | 65,66,67,69 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_opening_gazette_delete_1356.py::test_new_game_t0_previous_summary_strictly_empty` | 5 | 52,53,55,56,59 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_opening_gazette_delete_1356.py::test_old_save_exact_purge_keeps_real_with_phrase_counterexample` | 11 | 82,85,94,95,106,107,112,113…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_opening_gazette_delete_1356.py::test_state_payload_t0_previous_summary_empty` | 3 | 158,159,160 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_override_breach_costs_564.py::test_active_commitment_can_breach_closed_issued_dossier_but_not_never_issued` | 4 | 491,499,500,511 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_breach_charges_authority_ministers_and_related_factions_once` | 6 | 526,527,528,530,533,535 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_breach_excludes_stale_minister_faction_from_costs` | 2 | 192,193 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_breach_skips_dead_but_records_living_offstage_relations` | 5 | 214,216,217,218,225 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_cancel_linked_issue_breaches_only_its_origin_dossier_once` | 5 | 248,249,250,251,253 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_override_breach_costs_564.py::test_commit_false_breach_rolls_back_with_later_cancellation_failure` | 3 | 456,457,459 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_override_breach_costs_564.py::test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | 3 | 387,388,389 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_override_breach_costs_564.py::test_costs_are_idempotent_and_survive_restore` | 3 | 149,153,159 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_override_breach_costs_564.py::test_force_land_survey_charges_three_costs_without_eunuch_reaction` | 6 | 44,45,46,47,49,53 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_force_rejects_malformed_judge_reactions_before_any_cost` | 3 | 422,423,424 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_override_breach_costs_564.py::test_force_rejects_missing_or_stale_judge_reactions_before_any_cost` | 3 | 403,404,405 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_override_breach_costs_564.py::test_force_rejects_old_only_judge_reactions_atomically` | 3 | 440,441,442 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_override_breach_costs_564.py::test_force_then_breach_charges_each_real_entry_independently` | 4 | 174,175,176,181 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently` | 6 | 349,350,351,356,361,362 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_override_breach_costs_564.py::test_midzhi_apply_omits_guessed_parties_and_keeps_satisfaction` | 4 | 301,302,308,309 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_midzhi_rejection_no_party_fanout_then_force_only_authority` | 10 | 83,84,85,86,92,93,95,96…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_midzhi_rejudgment_never_applies_party_satisfaction` | 4 | 125,136,137,138 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_override_breach_costs_564.py::test_ordinary_rejection_has_zero_reaction_and_authority` | 4 | 111,112,113,114 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_public_apply_rejects_invalid_mode_decision_reaction_shape_before_writes` | 2 | 284,285 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_override_breach_costs_564.py::test_signed_reactions_use_typed_direction_not_narrative_words` | 2 | 70,71 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_p4_guard_new_surfaces_547.py::test_audience_archive_qiju_keeps_sentinels_out_and_world_facts_in` | 6 | 244,245,247,248,249,250 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_p4_guard_new_surfaces_547.py::test_rescript_page_payload_keeps_sentinels_out_and_world_facts_in` | 7 | 178,188,189,190,200,202,203 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_p4_guard_new_surfaces_547.py::test_scroll_and_highlight_list_keep_sentinels_out_and_world_facts_in` | 8 | 133,134,135,136,137,140,142,143 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_pay_order_override_653.py::test_apply_score_extraction_accepts_llm_direction_with_fiscal_loss` | 3 | 1133,1137,1138 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_arrears_order_resolution_default_and_override` | 2 | 217,220 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pay_order_override_653.py::test_bridge_applies_due_order_and_haircut_end_to_end` | 4 | 598,599,600,601 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_central_due_haircut_consumer` | 5 | 1271,1275,1284,1285,1288 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e` | 7 | 1666,1671,1672,1673,1679,1688,1702 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_due_order_bad_shapes_raise` | 2 | 628 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_pay_order_override_653.py::test_expired_only_keys_return_none_fast_path` | 2 | 228,229 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pay_order_override_653.py::test_f23_region_logs_flow_sign_domain_repaid_negative` | 5 | 659,680,687,688,689 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pay_order_override_653.py::test_fact_brief_arrears_provenance_prefers_winning_scoped_over_nationwide` | 3 | 1020,1021,1022 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_attributes_arrears_order_displacement_to_dossier` | 5 | 885,886,887,891,896 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_attributes_priority_displacement_to_dossier` | 2 | 765,774 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_fact_brief_central_haircut_floor_per_army_matches_real_accounting` | 5 | 1492,1498,1499,1500,1501 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_levy_derives_regular_assessment_like_settle_tick` | 2 | 753,754 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_levy_uses_civil_arrears_breakdown_relation` | 2 | 725,726 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_long_term_stock_not_fed_as_turn_damage` | 2 | 1565,1566 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_fact_brief_per_source_windows_and_region_attribution` | 9 | 1417,1418,1419,1420,1421,1423,1424,1426…+1 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pay_order_override_653.py::test_fact_brief_priority_provenance_falls_back_to_nationwide_scope` | 5 | 942,943,949,950,951 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_priority_provenance_ignores_later_noncausal_dossier` | 3 | 1044,1045,1046 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_priority_provenance_prefers_winning_scoped_over_later_nationwide` | 3 | 973,974,975 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_province_auto_repaied_is_beneficiary_fact` | 3 | 1544,1545,1546 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_fact_brief_unmet_relief_is_current_turn_damage` | 3 | 1522,1523,1524 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_fact_brief_zero_need_army_region_attribution_not_gated` | 4 | 1455,1460,1469,1470 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pay_order_override_653.py::test_fiscal_fact_brief_haircut_and_relief_facts` | 3 | 1094,1113,1114 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pay_order_override_653.py::test_fiscal_fact_brief_missing_settle_key_exits_dynamic_membership` | 1 | 1054 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pay_order_override_653.py::test_fiscal_fact_brief_pure_projection_deterministic_tsv` | 7 | 696,698,702,703,706,708,711 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_golden1_pay_order_reversal_breakdown_tsv` | 9 | 238,239,240,246,247,249,250,251…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_golden2_haircut_half_is_exemption_not_debt` | 5 | 260,266,268,269,271 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_golden3_arrears_waterfall_reversal` | 5 | 281,282,283,286,287 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_golden4_last_write_wins_with_two_provenance_rows` | 5 | 303,308,309,310,311 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_golden5_expiry_and_revoke_restore_byte_identical_default` | 6 | 325,334,335,337,346,356 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_golden7_replay_determinism` | 2 | 578,579 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_legacy_engine_pay_order_materialize_fails_loud_not_fulfilled` | 4 | 910,916,918,919 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_lifecycle_force_promulgation_after_rejection` | 3 | 1192,1194,1195 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_lifecycle_promulgated_materializes_and_next_settlement_reads` | 5 | 1149,1155,1159,1161,1164 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_lifecycle_rejected_decree_zero_config_write` | 3 | 1178,1179,1182 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_manual_override_capture_stages_without_premature_materialization` | 2 | 1641,1642 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pay_order_override_653.py::test_override_key_legal_shapes` | 1 | 75 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_precedence_region_beats_bare_and_full_order` | 2 | 204,206 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_priority_tie_breaks_on_default_baseline_stable` | 1 | 212 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pay_order_override_653.py::test_proposed_revoke_does_not_restore_override` | 6 | 423,424,425,426,430,434 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_pure_central_zero_haircut_due_clears_shortfall_counter` | 10 | 1301,1308,1309,1311,1313,1327,1328,1336…+2 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_pay_order_override_653.py::test_r3_central_side_scope_resolution` | 7 | 163,164,167,168,169,176,177 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_pay_order_override_653.py::test_r4_golden1_region_source_specificity_wins` | 5 | 149,150,152,153,154 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pay_order_override_653.py::test_r4_golden2_expiry_falls_back_to_next_specific` | 4 | 188,189,191,192 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pay_order_override_653.py::test_r4_no_phantom_region_materialization_is_all_or_nothing` | 2 | 124,125 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_real_revoke_decree_restores_override_and_clears_expiry` | 5 | 378,379,380,385,392 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_real_revoke_restores_override_same_month_with_active_commitment` | 6 | 535,536,553,563,564,569 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_rejected_revoke_does_not_restore_override` | 6 | 469,470,471,472,476,480 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pay_order_override_653.py::test_revoke_later_same_dim_decree_not_stomped` | 4 | 793,801,805,811 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_pay_order_override_653.py::test_revoke_provincial_falls_back_to_nationwide` | 6 | 829,837,838,840,842,844 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pay_order_override_653.py::test_stale_until_cleared_by_permanent_overwrite` | 6 | 1206,1210,1211,1217,1220,1221 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pay_order_override_653.py::test_turn_region_summary_claim_audit_rows_do_not_consume_limit` | 3 | 506,516,517 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_person_archive_contract_index.py::test_active_title_kind_normalizes_appointment_via_person_delta` | 12 | 78,89,90,91,106,107,121,122…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_archive_contract_index.py::test_reason_alias_shouzhi_outranks_offstage_default_via_person_delta` | 4 | 168,169,170,171 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_archive_contract_index.py::test_reason_code_aliases_and_missing_via_person_delta` | 6 | 40,41,51,54,64,67 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_archive_schema.py::test_add_character_persists_transit_to` | 1 | 60 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_archive_schema.py::test_north_star_named_figures_are_seeded_with_identity_metadata` | 3 | 88,90,91 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_archive_schema.py::test_person_logs_accepts_audit_rows_for_existing_characters` | 1 | 25 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_archive_schema.py::test_reload_restores_complete_transit_ledger_from_db` | 1 | 75 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::_materialize_active_prince` | 1 | 1903 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_add_character_person_title_skips_office_type_scaffold` | 4 | 1706,1707,1708,1711 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_apply_office_appointment_new_person_person_title_no_dirty_office_row` | 7 | 3538,3546,3547,3551,3552,3554,3557 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_apply_office_appointment_person_title_survives_stem_collision` | 10 | 3612,3620,3624,3625,3626,3629,3646,3647…+2 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_apply_office_appointment_rejects_vassal_prince` | 3 | 1935,1937,1938 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_person_changes_disposition_does_not_commit_inside_batch` | 2 | 417,418 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_accepts_status_reason_as_person_reason` | 3 | 1170,1171,1172 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_allegiance_change_rebinds_identity_title` | 6 | 1598,1621,1622,1623,1624,1625 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_applies_person_change_banish` | 4 | 1484,1485,1486,1487 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_applies_person_change_disposition` | 5 | 1458,1459,1460,1461,1462 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_applies_person_change_office_action` | 7 | 679,680,681,682,683,684,685 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_clamps_loyalty_assessment_delta` | 3 | 332,333,334 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_clears_displaced_reason_when_reappointed` | 2 | 1043,1072 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_does_not_echo_normalized_person_changes` | 6 | 147,151,152,157,158,159 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_does_not_release_non_ming_when_derived_appointment_is_rejected` | 14 | 1419,1420,1421,1422,1423,1425,1426,1427…+6 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_does_not_release_when_derived_appointment_is_invalid` | 13 | 1121,1122,1123,1124,1126,1127,1128,1129…+5 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_loyalty_assessment_does_not_commit_inside_batch` | 1 | 371 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_materializes_derived_release_before_appointment` | 10 | 823,824,825,826,834,838,839,840…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change` | 5 | 951,957,958,959,982 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_new_person_changes_shadow_legacy_person_keys` | 4 | 2305,2306,2307,2308 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_offstage_disposition_clears_db_and_content_office` | 5 | 1535,1536,1537,1538,1539 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_one_time_grant_and_assessment_do_not_create_commitment_issue` | 3 | 486,487,488 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_persists_reason_code_and_person_log` | 5 | 1572,1573,1574,1578,1584 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | 8 | 235,240,241,242,243,244,248,249 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_banish_from_imprisoned` | 3 | 1512,1513,1514 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_dead_status_outbound` | 9 | 1874,1875,1876,1877,1878,1879,1880,1881…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_forged_legacy_partial_power_way` | 4 | 611,612,613,614 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_invalid_loyalty_assessment` | 9 | 288,290,291,292,293,294,295,296…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_invalid_person_dispositions` | 1 | 1834 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_invalid_person_travel` | 15 | 2093,2094,2095,2096,2097,2098,2099,2100…+7 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_legacy_trapped_prisoner_office_change` | 6 | 779,780,781,782,783,784 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_malformed_power_move_backlash_before_writing` | 12 | 521,522,523,524,526,527,528,529…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_person_change_power_move_without_way` | 10 | 177,178,180,181,182,183,184,185…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_power_move_without_backlash_side_effect` | 2 | 646,647 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_trapped_prisoner_appointment` | 5 | 747,748,749,750,751 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_unknown_person_change` | 9 | 1850,1851,1852,1853,1854,1855,1856,1857…+1 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_unknown_person_change_new_appointment` | 4 | 714,715,716,717 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rejects_unknown_person_travel_region` | 8 | 2126,2127,2128,2129,2130,2131,2132,2133 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_rolls_back_derived_release_when_office_write_fails` | 13 | 1223,1224,1225,1226,1227,1228,1230,1231…+5 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_apply_score_extraction_treats_active_identity_title_as_unappointed` | 3 | 1664,1665,1666 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_bandit_amnesty_rejects_backlash_targeting_another_bandit_power` | 3 | 3479,3480,3481 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_bandit_amnesty_rejects_same_power_top_level_suppression` | 4 | 3115,3116,3117,3118 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_person_delta_adapter.py::test_bandit_amnesty_rejects_same_power_top_level_suppression_when_backlash_empty` | 5 | 3211,3212,3213,3214,3215 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_create_secret_order_allows_returned_defector` | 1 | 2046 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_person_delta_adapter.py::test_create_secret_order_persists_canonical_name` | 1 | 1997 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_derived_release_rejection_keeps_prior_person_change_in_atomic_batch` | 15 | 1300,1301,1302,1303,1304,1305,1306,1311…+7 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_derived_release_restores_when_post_office_helper_raises` | 13 | 1362,1363,1364,1365,1366,1367,1369,1370…+5 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_displaced_holder_transit_to_cleared` | 3 | 2635,2636,2638 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_disposition_manual_rollback_restores_memory_reason_fields` | 2 | 2475,2477 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_disposition_syncs_reason_code_to_content_in_txn` | 3 | 2771,2772,2773 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_empty_new_person_change_key_does_not_shadow_legacy_normalization` | 2 | 2325,2326 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_fresh_seed_migrates_legacy_office_pollution` | 4 | 2553,2554,2556,2557 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_fresh_static_seed_person_title_character_no_offices_parent` | 3 | 3587,3591,3594 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_historical_death_tick_sets_reason_code` | 2 | 2660,2661 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_historical_death_tick_writes_person_log` | 1 | 2683 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_historical_debut_tick_sets_reason_code_and_log` | 3 | 2705,2706,2711 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_legacy_office_pollution_migrated_on_load` | 8 | 2574,2575,2577,2578,2581,2583,2584,2585 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_legacy_office_pollution_resolves_transit_to_region_id` | 2 | 2603,2604 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_legacy_status_change_clears_transit_to_after_person_travel` | 6 | 2260,2261,2262,2263,2264,2265 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_legacy_status_change_rejects_non_active_target_before_transition_matrix` | 13 | 561,562,563,565,566,567,568,569…+5 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_list_ministers_excludes_active_prince` | 1 | 1949 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_migration_does_not_write_nonregion_location` | 1 | 2815 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_new_appointment_falsy_return_restores_snapshot` | 2 | 2527,2531 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_normalize_legacy_person_changes_preserves_origin` | 1 | 122 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_normalize_person_changes_ignores_non_item_shapes` | 3 | 126,129,130 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_normalize_person_changes_keeps_new_key_items` | 1 | 41 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_normalize_person_changes_translates_legacy_keys_in_replay_order` | 6 | 79,85,91,92,101,107 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_person_delta_adapter.py::test_orphan_bandit_power_can_be_suppressed_when_dead_leader_amnesty_is_rejected` | 3 | 3388,3389,3390 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_person_delta_adapter.py::test_pending_dismiss_rejects_vassal_prince` | 2 | 2054,2055 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_person_change_rejects_unknown_action_not_silent` | 4 | 2950,2951,2956,2957 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_person_disposition_clears_existing_transit_to` | 3 | 2159,2160,2161 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_person_log_normalized_not_truncated` | 1 | 2072 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_political_marker_is_audit_only_no_status_premigration` | 4 | 2368,2373,2374,2379 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_reappoint_nonactive_syncs_character_reason_to_db` | 3 | 2408,2409,2411 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_reappoint_rollback_restores_character_reason` | 3 | 2440,2441,2442 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_reappointment_clears_displaced_mark_in_both_db_and_content` | 2 | 2800,2801 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_registry_and_tools_court_roster_exclude_active_prince` | 1 | 1924 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_rejected_bandit_amnesty_does_not_block_same_power_suppression` | 4 | 3296,3297,3298,3302 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_person_delta_adapter.py::test_rejected_derived_appointment_durably_restores_complete_person_state` | 2 | 882,884 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_delta_adapter.py::test_reload_syncs_reason_code_status_reason_to_content` | 2 | 2750,2751 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_s15_amnesty_to_ming_then_appoint` | 3 | 3017,3019,3020 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_s2_reappointment_derives_qifu_from_retired` | 4 | 2877,2878,2882,2883 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_s3_reappointment_derives_zhaoxue_from_dismissed` | 5 | 2902,2903,2904,2906,2907 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_s4_reappointment_derives_duoqing_when_mourning` | 5 | 2926,2927,2930,2931,2932 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_s8_demotion_release_then_lower_appointment_derives_qifu` | 3 | 3521,3522,3527 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_s9_consort_leaves_palace_clears_office` | 4 | 2983,2985,2986,2987 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_seed_backfill_skips_person_title_character_offices` | 4 | 1741,1745,1748,1751 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_set_character_office_person_title_survives_stem_collision` | 3 | 1772,1773,1776 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_person_delta_adapter.py::test_set_character_status_clears_office_for_offstage` | 3 | 2205,2206,2207 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_delta_adapter.py::test_set_character_status_clears_stale_reason_code_when_missing` | 3 | 2224,2225,2226 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_set_character_status_clears_transit_to_when_leaving_active` | 2 | 2188,2189 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_unified_appointment_resolves_alias_before_hallucinated_guard` | 1 | 2502 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_yizhu_clears_status_reason_in_db` | 5 | 2842,2843,2844,2845,2846 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_delta_adapter.py::test_yizhu_sets_active_in_new_master_service` | 2 | 2735,2736 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_transit_write_667.py::test_departure_persists_matrix_distance_and_urgent_factor` | 5 | 113,114,115,120,121 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_person_transit_write_667.py::test_departure_reads_matrix_from_frozen_bundle_outside_cwd` | 1 | 72 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_person_transit_write_667.py::test_departure_rejects_location_shapes_without_mutation` | 2 | 97,98 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_transit_write_667.py::test_departure_rejects_nonfinite_distance_before_ledger_write` | 2 | 50,51 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_transit_write_667.py::test_invalid_tone_is_rejected_before_same_destination_idempotence` | 1 | 240 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_person_transit_write_667.py::test_noncanonical_origin_is_narrative_only_noop` | 3 | 139,141,147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_transit_write_667.py::test_office_appointment_keeps_status_reason_mirrored` | 3 | 217,221,222 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_transit_write_667.py::test_same_destination_is_idempotent` | 1 | 253 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_person_transit_write_667.py::test_status_exit_clears_complete_transit_ledger` | 4 | 168,169,181,183 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::_1778_plant_and_follow` | 6 | 2886,2888,2893,2900,2901,2902 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::_658_plant_stalled_deliberation` | 1 | 2398 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pihong_dossier_1490.py::_get_state` | 1 | 280 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::_summonable_name` | 1 | 2387 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1589_empty_desk_rejects_nonempty_keyless_choices` | 8 | 1594,1602,1603,1604,1605,1609,1610,1611 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1589_mixed_desk_keyless_choice_rejected_batch_zero_writes` | 9 | 1531,1532,1536,1537,1539,1540,1541,1542…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1589_pure_decision_keyless_rejected_then_keyed_same_choice_passes` | 9 | 1565,1566,1569,1571,1572,1573,1575,1580…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1620_http_follow_draft_grant_uses_stored_amount` | 9 | 1778,1781,1791,1792,1793,1795,1797,1799…+1 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_pihong_dossier_1490.py::test_1620_http_follow_draft_office_token_routes_to_person` | 9 | 1754,1755,1756,1758,1761,1762,1765,1767…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1620_layer_a_money_grant_requires_positive_amount` | 8 | 1821,1822,1825,1826,1827,1828,1830,1831 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pihong_dossier_1490.py::test_1627_stamp_ignores_pre_edict_clarification_directive` | 8 | 797,798,802,804,805,806,807,808 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1682_late_grants_follow_policy_without_consuming_verdict_batch` | 17 | 1178,1181,1182,1183,1185,1186,1187,1188…+9 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_1682_phase2_surfaces_ambiguous_stored_choice` | 1 | 1985 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_1778_drafted_roster_rides_to_pihong_and_nails_the_dossier` | 25 | 2917,2919,2921,2922,2924,2926,2927,2928…+17 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_abi_mapper_matrix_a1_a12` | 54 | 929,930,932,966,974,975,978,982…+46 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_applied_revise_refresh_resumes_without_hold` | 15 | 2363,2364,2365,2366,2367,2368,2369,2371…+7 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_appointment_name_target_id_conflict_batch_reject` | 1 | 2017 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::test_657_c1_decided_mismatch_rejects_and_cas0` | 1 | 555 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_default_hold_missing_and_empty_action` | 14 | 627,628,630,631,633,634,637,638…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_default_hold_preserves_red_pen_note` | 3 | 2008,2009,2010 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pihong_dossier_1490.py::test_657_five_actions_domain_writes` | 18 | 697,698,700,709,711,712,721,722…+10 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_follow_draft_ignores_client_field_overlay` | 8 | 1845,1848,1849,1850,1851,1852,1853,1854 | `KEEP_STRUCTURED_FIELD` | 必要负向：禁泄露片段 |
| `tests/test_pihong_dossier_1490.py::test_657_http_default_hold_keyed_empty_action_and_betray` | 4 | 680,682,683,685 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::test_657_illegal_summon_target_http_zero_writes` | 6 | 1726,1727,1728,1730,1731,1733 | `KEEP_STRUCTURED_FIELD` | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py::test_657_midzhi_persists_decision_key_and_llm_label` | 4 | 1867,1870,1871,1872 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_midzhi_verdict_no_party_satisfaction` | 3 | 1889,1890,1893 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_mixed_batch_follow_plus_decision_and_no_context_copy` | 14 | 1479,1480,1487,1489,1491,1492,1494,1496…+6 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_p6_mapper_deliberate_preserve_free_text` | 15 | 572,573,574,575,578,589,591,592…+7 | `KEEP_STRUCTURED_FIELD` | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py::test_657_prewrite_failure_zero_db_writes` | 2 | 915,916 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_punishment_name_target_id_conflict_zero_writes` | 9 | 2031,2036,2038,2047,2048,2050,2051,2053…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_pihong_dossier_1490.py::test_657_record_event_choice_failure_rolls_back_batch` | 3 | 833,835,837 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_657_resume_phase2_signal_empty_desk_http` | 4 | 2340,2341,2345,2346 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_s6_http_present_target_gets_unique_origin_entry` | 4 | 1634,1638,1640,1641 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_summon_missing_tag_enter_blocks_phase2_then_retry` | 6 | 1934,1935,1936,1943,1945,1946 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_657_summon_single_flight_concurrent_http` | 4 | 2186,2190,2192,2193 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::test_657_web_http_hitl_lock_boundary_same_gate` | 6 | 1662,1673,1681,1707,1709,1710 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_658_candidates_require_active_status` | 3 | 2553,2555,2562 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_658_deliberate_backed_and_stalled_dossier_first` | 18 | 2457,2458,2460,2461,2462,2463,2464,2465…+10 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_pihong_dossier_1490.py::test_658_ordinary_edit_does_not_inherit_push_target` | 10 | 2791,2792,2793,2800,2801,2802,2803,2804…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pihong_dossier_1490.py::test_658_stage_rejects_bad_backing_zero_write` | 4 | 2515,2523,2525,2528 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pihong_dossier_1490.py::test_bind_preserves_dossier_event_id` | 1 | 337 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py::test_bind_unbinds_dossier_prefix_without_capability_fields` | 1 | 346 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pihong_dossier_1490.py::test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | 8 | 371,372,373,374,376,378,379,380 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::test_lying_label_rebuilt_from_server_option` | 9 | 396,397,398,399,401,402,403,404…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pihong_dossier_1490.py::test_missing_dossier_fields_stay_pending_then_full_retry_decides` | 13 | 310,311,312,314,315,316,321,322…+5 | `KEEP_STRUCTURED_FIELD` | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py::test_mixed_legal_illegal_options_illegal_choice_stays_pending` | 17 | 442,443,444,446,447,448,453,454…+9 | `KEEP_STRUCTURED_FIELD` | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py::test_ordinary_event_with_hallucinated_capability_submits` | 8 | 492,493,494,495,497,499,500,501 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_pihong_dossier_1490.py::test_parse_rescript_capability_pair_rejects_non_positive_and_unknown` | 9 | 410,411,412,413,414,415,416,417…+1 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_player_army_projection_321.py::_assert_chain_embeds_situation` | 3 | 227,228,230 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_player_army_projection_321.py::_assert_structured_situation` | 8 | 214,215,216,219,220,221,222,223 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_player_army_projection_321.py::test_apply_army_deltas_rejects_five_persistent_mutiny_columns` | 3 | 403,404,408 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_player_army_projection_321.py::test_four_chains_embed_situation_matrix` | 12 | 267,271,276,277,280,283,286,290…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_player_army_projection_321.py::test_player_army_situation_six_tier_truth_table` | 5 | 106,107,108,112,114 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_player_army_projection_321.py::test_restore_five_columns_and_player_tier_survives_reopen` | 20 | 343,353,354,355,356,357,360,362…+12 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_player_payload_1022.py::test_history_payload_preserves_narrative_without_machine_ledger` | 1 | 40 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_player_payload_1022.py::test_issue_terminals_keep_unadvanced_month_visible` | 5 | 163,164,165,166,167 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_player_payload_1022.py::test_settlement_sse_routes_serialize_only_player_narrative` | 6 | 131,132,134,136,137,147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::_conservation_oracle` | 4 | 357,363,364,368 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_transfers_649.py::test_all_inflow_reasons_positive_cases_land` | 3 | 107,108,117 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_amount_and_balance_validation_per_item` | 3 | 162,163,164 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_class_delta_chinese_population_key_upgraded_to_per_item_rejection` | 5 | 274,275,279,280,284 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_transfers_649.py::test_class_delta_population_key_upgraded_to_per_item_rejection` | 5 | 250,251,255,256,260 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_transfers_649.py::test_direction_matrix_violations_rejected_per_item` | 6 | 141,142,143,144,146,147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_legacy_wan_unit_transfer_caps_to_stock_without_unit_conversion` | 10 | 306,312,314,315,316,325,327,328…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_mutation_oracle_four_mutations_all_bitten` | 11 | 389,395,400,406,413,415 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_transfers_649.py::test_new_save_unit_is_persons` | 1 | 340 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_transfers_649.py::test_origin_ref_required_and_validated` | 4 | 193,194,195,196 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_population_transfers_649.py::test_reference_validation_national_row_cross_region_unknown` | 2 | 178,179 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_population_transfers_649.py::test_section_non_list_rejects_section_rest_lands` | 3 | 231,232,236 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_transfers_649.py::test_transfer_two_legs_same_transaction_conservation` | 9 | 78,80,81,82,83,84,85,86…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_unknown_top_level_key_now_per_section_rejection_not_abort` | 3 | 296,297,298 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_649.py::test_whitelist_extra_field_and_non_dict_item_rejected` | 4 | 211,212,215,216 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_662.py::test_disaster_and_war_amounts_above_old_caps_land_and_conserve` | 5 | 66,67,68,69,72 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_transfers_662.py::test_same_batch_multi_origin_merges_into_single_pool_account` | 5 | 103,104,105,106,107 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_unit_648.py::test_class_delta_displaced_accepts_sat_lev_population_face_removed` | 7 | 215,216,217,225,226,231,232 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_unit_648.py::test_legacy_save_defaults_to_wan_unit_and_keeps_snapshot` | 4 | 146,150,154,156 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_population_unit_648.py::test_legacy_save_restore_jianzhou_converts_to_wan` | 1 | 305 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_unit_648.py::test_new_save_classes_seed_persons_scale` | 1 | 119 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_unit_648.py::test_new_save_displaced_class_seed_frozen_table` | 15 | 81,84,87,88,89,90,96,97…+7 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_unit_648.py::test_new_save_persistent_population_unit_marker` | 2 | 134,138 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_unit_648.py::test_new_save_regions_seed_persons_scale` | 1 | 128 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_population_unit_648.py::test_new_save_restore_jianzhou_keeps_persons_unit` | 3 | 283,292,293 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_population_unit_648.py::test_population_unit_mutation_matrix` | 6 | 174,176,178,179,188,190 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_population_unit_648.py::test_web_region_payload_has_no_population_wan_projection` | 4 | 250,252,256,257 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_power_section_rejections.py::_valid_power_id` | 1 | 30 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_power_section_rejections.py::test_all_reason_aliases_consumed_as_reason` | 2 | 269,270 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_power_section_rejections.py::test_dirty_power_value_rejected_sibling_field_lands` | 4 | 180,182,183,186 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_power_section_rejections.py::test_dirty_power_value_string_rejected` | 2 | 200,201 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_power_section_rejections.py::test_float_and_bool_power_values_rejected` | 3 | 234,235,238 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_power_section_rejections.py::test_illegal_power_field_rejected` | 2 | 74,75 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_power_section_rejections.py::test_ming_power_update_rejected_with_trace` | 3 | 215,216,217 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_power_section_rejections.py::test_power_change_formatter_skips_rejected_items` | 3 | 155,159,160 | `KEEP_STRUCTURED_OR_HARNESS` | 必要负向：禁泄露片段 |
| `tests/test_power_section_rejections.py::test_reason_carrier_aliases_not_recorded_as_rejection` | 1 | 253 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_power_section_rejections.py::test_unknown_person_power_change_rejected_good_lands` | 4 | 115,116,117,121 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_power_section_rejections.py::test_unknown_power_id_rejected_good_item_lands` | 4 | 51,53,54,58 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_advance_without_edict_refused_after_settling` | 4 | 228,229,230,233 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_advance_without_edict_refused_at_awaiting` | 4 | 332,336,337,338 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_crash_inside_pre_settle_no_missing_fiscal` | 4 | 165,167,168,170 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_crash_reload_at_settling_no_double_fiscal_tick` | 6 | 40,41,43,50,52,53 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_due_secret_order_submission_rolls_back_on_pre_settle_crash` | 3 | 95,112,113 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pre_settle_transaction.py::test_enter_review_does_not_clobber_settling` | 2 | 213,216 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pre_settle_transaction.py::test_guarded_early_return_does_not_consume_pending` | 2 | 390,393 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_placeholder_save_crash_rolls_back_settling` | 4 | 437,438,439,440 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pre_settle_transaction.py::test_pre_settle_guard_covers_awaiting_decision` | 2 | 281,284 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_pre_settle_rolls_back_on_seed_issue_failure` | 3 | 136,137,138 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_resolve_turn_idempotent_at_awaiting` | 2 | 365,366 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_settling_survives_begin_turn_phase_whitelist` | 3 | 80,81,83 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_pre_settle_transaction.py::test_sticky_phases_cover_awaiting_decision` | 2 | 306,308 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_pre_settle_transaction.py::test_two_consecutive_player_months_both_get_fiscal_tick` | 4 | 188,189,192,195 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_appointment_rejection_check_requires_faction_gate_structure` | 6 | 596,598,601,604,607,610 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_promulgation_judge_561.py::test_appointment_tenure_is_the_rejection_snapshot_value` | 2 | 845,846 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_promulgation_judge_561.py::test_appointment_text_is_pure_gatekeeper_transfer_without_land_confiscation` | 2 | 579,581 | `KEEP_FIXTURE_OR_SEED` | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_promulgation_judge_561.py::test_choose_rescripts_keeps_authority_edge_off_force_promulgated` | 5 | 564,565,566,567,570 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_promulgation_judge_561.py::test_gate_evidence_reloads_dossier_after_reconsideration_mutation` | 6 | 410,412,413,419,420,423 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_promulgation_judge_561.py::test_gate_reconsideration_removes_only_named_opponent_and_keeps_real_bench` | 10 | 326,327,331,335,341,343,344,345…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_gate_reconsideration_resolves_missing_target_to_land_survey` | 7 | 366,367,369,372,373,374,375 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_promulgation_judge_561.py::test_gate_second_verdict_reads_pending_or_applied_history_strictly` | 2 | 433,434 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_gatekeeper_successor_removes_donglin_block_posture` | 6 | 493,494,495,502,503,507 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_promulgation_judge_561.py::test_leader_only_mutation_changes_faction_posture_not_roster` | 13 | 671,672,673,677,678,680,681,682…+5 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_promulgation_judge_561.py::test_ordinary_class_all_promulgated_covers_planted_ordinary_only` | 5 | 623,624,630,633,638 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgated_midzhi_strips_affected_parties_with_rejection_noise` | 2 | 280,284 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgated_true_path_clean_verdict_passes` | 1 | 294 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgated_verdict_strips_rejection_only_noise` | 2 | 246,248 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgation_context_is_deterministic_and_excludes_satisfaction` | 14 | 45,49,50,51,52,53,54,55…+6 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgation_context_projects_faction_leverage_as_qualitative_band` | 5 | 106,109,112,119,120 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_promulgation_judge_561.py::test_promulgation_history_only_projects_forced_and_midzhi_markers` | 1 | 144 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_promulgation_judge_omits_max_tokens` | 1 | 709 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_promulgation_judge_561.py::test_promulgation_verdict_accepts_exact_keys_for_each_mode` | 1 | 745 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_rejected_exact_keys_accept_only_empty_legal_reason_slot` | 1 | 758 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_judge_561.py::test_run_resolve_arm_recovers_settled_verdicts_from_history` | 5 | 462,472,473,474,477 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_seam_560.py::test_default_promulgation_stub_passes_every_dossier_without_collaborators` | 1 | 14 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_promulgation_seam_560.py::test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row` | 1 | 48 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_public_character_place_1683.py::test_public_character_projects_transit` | 5 | 51,52,53,54,55 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_public_character_place_1683.py::test_yuan_keli_init_db_location_henan` | 4 | 16,20,21,23 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_public_projection_consistency_1830.py::_seed_public_world` | 1 | 45 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_public_projection_consistency_1830.py::test_rebuild_adds_only_the_new_record_own_carrier` | 3 | 203,206,207 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_public_projection_consistency_1830.py::test_scene_person_public_layer_matches_character_and_world_admission` | 15 | 86,117,118,122,123,124,126,139…+7 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_public_sayings_1829.py::test_absent_minister_reads_saying_not_actual_status` | 3 | 82,98,101 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_public_sayings_1829.py::test_public_saying_may_annotate_person_affair_or_neither` | 9 | 300,301,302,303,304,305,306,307…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 索引字段外部结果 |
| `tests/test_public_sayings_1829.py::test_public_saying_survives_same_turn_archive_projection` | 1 | 275 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_public_sayings_1829.py::test_yuan_public_death_rumor_does_not_change_actual_life` | 10 | 44,54,56,57,58,59,60,67…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_1281_issue_audience_case_facts.py::_issue_row` | 1 | 25 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_qa_1281_issue_audience_case_facts.py::test_audience_supplement_grants_originating_issue_outside_knowledge` | 7 | 95,96,101,102,103,111,112 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_1281_issue_audience_case_facts.py::test_empty_audience_is_empty_supplement_not_knowledge_veto` | 3 | 71,76,81 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_1281_issue_audience_case_facts.py::test_issue_material_projection_does_not_pollute_durable_events_or_db` | 4 | 222,223,225,226 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_1281_issue_audience_case_facts.py::test_issue_materials_keep_knowledge_visibility_without_audience_veto` | 8 | 39,40,47,48,49,50,58,59 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_1281_issue_audience_case_facts.py::test_malformed_knowledge_issue_id_fails_loud_from_material_entry` | 1 | 169 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_a3_seed_data.py::test_active_seed_characters_do_not_occupy_office_slots` | 2 | 18,29 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_a3_seed_data.py::test_li_daiwen_office_forbids_unproven_province_tokens` | 1 | 57 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_a3_seed_data.py::test_qian_qianyi_seed_office_records_bajiu_dismissal` | 3 | 115,116,117 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_a3_seed_data.py::test_seed_has_exactly_one_active_libu_shangshu` | 1 | 90 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_a3_seed_data.py::test_settled_located_xunfu_offices_carry_province_or_zhen_title` | 3 | 45,46,47 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_a3_seed_data.py::test_wen_tiren_opening_office_is_libu_you_shilang` | 1 | 74 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_a3_seed_data.py::test_zhang_fengyi_office_strips_future_title` | 3 | 102,103,104 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_b3_409_ux.py::_front_half_detail` | 2 | 70,72 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_b3_409_ux.py::test_closing_player_message_is_diegetic_without_bare_night_id` | 7 | 47,50,51,52,55,56,57 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_b3_409_ux.py::test_directive_payload_authority_not_notes_alias` | 3 | 110,111,112 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_b3_409_ux.py::test_load_save_409_during_resolve_body_keeps_old_session_tail` | 5 | 291,292,293,299,300 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_b3_409_ux.py::test_resolve_decisions_stream_awaiting_still_submits_under_lock` | 5 | 208,222,224,225,227 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_b3_409_ux.py::test_resolve_decisions_stream_phase_precheck_before_lock` | 5 | 192,194,195,196,197 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_b3_409_ux.py::test_serialized_web_write_phase_messages_cover_front_half_done` | 3 | 80,84,86 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_c2_phase_settlement_mask_1374.py::test_resolve_stream_clear_throw_emits_error_not_done` | 3 | 229,230,231 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_c2_phase_settlement_mask_1374.py::test_resolve_stream_entry_failure_exits_display_when_not_front_half` | 3 | 188,189,190 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_qa_c2_phase_settlement_mask_1374.py::test_resolve_stream_uses_settlement_period_entry` | 4 | 131,133,164,166 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_refresh_turn_no_longer_clears_orphan` | 1 | 68 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_c3_secret_order_path_1357_1376.py::test_pending_secret_order_count_reflects_staged_candidate` | 4 | 103,111,112,114 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_c3_secret_order_path_1357_1376.py::test_pending_secret_order_count_zero_without_staged` | 2 | 74,75 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_d1_decree_normalize_1274.py::test_night_archive_involved_people_drops_non_persons` | 5 | 95,112,115,116,117 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_d1_decree_normalize_1274.py::test_patch_decree_and_manual_create_routes_removed_draft_rw_remains` | 3 | 135,142,150 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_e1_numeric_presentation.py::test_army_payload_arrears_text_is_approximate_not_raw` | 2 | 99,100 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_e1_numeric_presentation.py::test_player_budget_payload_strips_engineering_notes` | 3 | 76,78,84 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_e1_numeric_presentation.py::test_renaming_army_pay_budget_line_does_not_double_debit` | 5 | 49,62,63,67,68 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_qa_e1_numeric_presentation.py::test_substrate_budget_splits_proposals_without_treasury_cap` | 2 | 40,42 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_h1_seed_data.py::_deficit_seed` | 1 | 43 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_h1_seed_data.py::test_deficit_stage_text_aligns_with_opening_treasury_and_hubu` | 4 | 172,173,178,181 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_h1_seed_data.py::test_dongjiang_commander_is_active_mao_wenlong` | 4 | 70,71,73,74 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_h1_seed_data.py::test_fresh_seed_army_equipment_and_commanders_wire_through` | 15 | 126,132,133,134,135,137,138,139…+7 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_h1_seed_data.py::test_guanning_commander_not_bajiu_offstage_yuan` | 5 | 54,58,59,62,63 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_h1_seed_data.py::test_seed_army_firearms_differentiated_within_p2_caps` | 11 | 83,89,90,93,94,96,97,98…+3 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_close_retry_on_healed_cleanup_no_stale_ids` | 2 | 189,190 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_closing_restore_path_still_catches_up` | 2 | 147,148 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_debt_exhausted_single_source_no_player_cta` | 3 | 123,124,125 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_dispatch_exception_after_persist_retains_reply_recovery` | 6 | 342,344,345,346,350,351 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_drain_fail_cleanup_does_not_hide_blocking_turn` | 7 | 78,79,84,85,86,87,89 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_drain_fail_concurrent_heal_asks_retry_no_dual_source` | 3 | 105,106,107 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_partial_heal_single_source_pending_only_fresh` | 2 | 172,173 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_resolve_turn_write_gate_held_by_caller_no_reenter` | 1 | 367 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_startup_catchup_uses_ticketed_gate_not_bare` | 4 | 284,286,287,288 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_t1_extraction_dual_source_1353.py::test_stream_post_reply_exception_preserves_phase_and_recovers_original_turn` | 6 | 315,318,319,322,323,324 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_u2_liaodong_buildings.py::test_liaodong_buildings_content_nonempty_and_no_cheats` | 7 | 25,29,32,34,39,40,41 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_u2_liaodong_buildings.py::test_liaodong_buildings_enter_monthly_period_flows` | 4 | 64,67,76,91 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_u2_liaodong_buildings.py::test_liaodong_buildings_seed_into_fresh_db` | 2 | 51,53 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_u3_map_nodes_1401.py::test_map_nodes_no_double_army_hang` | 3 | 34,39,40 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_qa_u3_map_nodes_1401.py::test_map_nodes_no_nameless_nodes` | 5 | 136,139,149,154,158 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_qa_u3_map_nodes_1401.py::test_map_nodes_province_garrison_co_node` | 20 | 69,75,76,78,81,83,87,92…+12 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_recommendation_batch_snapshot_1583.py::test_same_batch_consecutive_appointments_keep_prebatch_recommendation_snapshot` | 9 | 83,103,108,109,110,114,115,116…+1 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendation_batch_snapshot_1583.py::test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch` | 5 | 142,153,155,159,160 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_recommendation_edges_635.py::_commit_and_promulgate` | 1 | 39 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_recommendation_edges_635.py::test_appointment_without_recommendation_writes_no_edges` | 1 | 219 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendation_edges_635.py::test_approved_recommendation_writes_both_edges_atomically` | 16 | 58,60,61,64,70,74,75,76…+8 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_recommendation_edges_635.py::test_empty_reason_fails_loud_and_rolls_back_everything` | 3 | 121,122,125 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendation_edges_635.py::test_real_entry_persists_raw_reason_verbatim` | 3 | 166,169,170 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_recommendation_edges_635.py::test_replay_same_event_with_changed_reason_stays_two_rows` | 4 | 191,194,195,197 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendation_edges_635.py::test_second_leg_failure_rolls_back_everything` | 3 | 147,148,151 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendation_edges_635.py::test_unapproved_appointment_writes_zero_edges` | 2 | 107,108 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_adopted_recommendation_is_an_auditable_event_after_restore` | 4 | 214,215,216,217 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_recommendations.py::test_hearing_exclusion_hides_candidate_by_current_position` | 1 | 146 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_hearing_title_without_displacement_reason_is_not_talent_pool_candidate` | 1 | 310 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_recommendations.py::test_listed_heard_for_selection_candidate_stays_recovery_type_through_context_and_restore` | 5 | 282,283,284,289,290 | `KEEP_STRUCTURED_OR_HARNESS` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_recommendations.py::test_low_identity_recommender_can_see_high_identity_same_faction_candidate` | 1 | 47 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_private_and_public_structured_hearing_exposes_cross_faction_candidate` | 2 | 84,85 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_public_structured_hearing_exclusion_hides_cross_faction_candidate` | 1 | 112 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_recommendation_appointment_preserves_kind_and_restores_both_types` | 3 | 257,263,264 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_recommendations.py::test_recommendation_candidates_are_limited_to_faction_or_character_knowledge` | 2 | 27,28 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_same_faction_future_debut_is_not_recommendable` | 1 | 198 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_recommendations.py::test_source_local_exclusion_preserves_same_faction_network_candidate` | 1 | 180 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::_force_in_transit_recovery_grant` | 3 | 415,416,417 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_refugee_loop_652.py::_in_transit_recovery_grant` | 3 | 346,347,349 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_refugee_loop_652.py::test_bandit_absorption_clamps_pool_strength_and_ceiling` | 7 | 164,166,167,177,178,179,194 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_bandit_absorption_rejects_unknown_fields_keeps_clean_sibling` | 7 | 218,219,220,221,223,224,225 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_refugee_loop_652.py::test_free_positive_bandit_strength_rejected_negative_ok` | 4 | 238,239,240,246 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_legacy_population_unit_skips_absorption_and_recovery` | 4 | 628,636,638,641 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_llm_free_回流_rejected` | 3 | 259,260,261 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_month_settle_with_disaster_and_executing_relief` | 3 | 616,617,618 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_refugee_loop_652.py::test_non_recovery_grant_no_回流` | 3 | 292,293,296 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_outer_atomic_rolls_back_surcharge_and_absorption` | 2 | 146,147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_recovery_without_paid_evidence_produces_nothing` | 3 | 303,310,313 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_refugee_loop_652.py::test_standalone_absorption_is_durable_to_second_connection` | 2 | 94,96 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_refugee_loop_652.py::test_standalone_surcharge_is_durable_to_second_connection` | 1 | 119 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_region_cannon_delta.py::test_city_cannon_capped_at_zero_for_low_city_level` | 4 | 42,49,50,51 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_region_cannon_delta.py::test_city_cannon_delta_lands_clamped` | 1 | 27 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_region_cannon_delta.py::test_city_cannon_lower_bound_clamp_audited_not_as_cap` | 2 | 63,64 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_region_cannon_delta.py::test_illegal_region_field_rejected_not_raised` | 3 | 89,90,91 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_region_citydefense.py::test_city_level_tiers_by_history` | 10 | 21,22,23,24,25,26,27,28…+2 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_region_citydefense.py::test_region_cannon_cap_by_city_level` | 2 | 37,39 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_region_citydefense.py::test_region_cannon_level0_caps_zero` | 1 | 46 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rejection_wiring.py::test_attempt_derivation_failure_does_not_abort_settlement` | 2 | 167,168 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rejection_wiring.py::test_bridge_synthesizes_reason_when_producer_omits` | 1 | 213 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_inertia_power_move_backlash_rejection_lands_in_reports` | 3 | 551,552,553 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rejection_wiring.py::test_inertia_tolerated_rejections_reach_reports` | 2 | 239,240 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rejection_wiring.py::test_issue_close_power_move_backlash_rejection_is_not_duplicated` | 4 | 512,513,514,515 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rejection_wiring.py::test_issue_summary_nested_rejections_are_collected` | 3 | 122,123,124 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rejection_wiring.py::test_item_json_is_original_delta_item_when_producer_carries_it` | 3 | 260,262,263 | `KEEP_STRUCTURED_OR_HARNESS` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_nested_atomic_success_path_does_not_orphan_jsonl` | 2 | 144,145 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_rejection_wiring.py::test_non_ming_appointment_rejection_keeps_original_person_delta_item` | 4 | 392,393,395,396 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_noncancellable_cancel_rejection_carries_reason` | 3 | 180,190,191 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_office_change_rejection_item_json_keeps_original_person_delta_item` | 4 | 354,355,357,358 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rejection_wiring.py::test_person_change_rejection_item_json_keeps_original_delta_item` | 3 | 288,290,291 | `KEEP_STRUCTURED_OR_HARNESS` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_power_move_backlash_rejection_lands_in_reports` | 4 | 449,450,451,452 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rejection_wiring.py::test_power_move_rejection_item_json_keeps_original_person_delta_item` | 3 | 324,326,327 | `KEEP_STRUCTURED_OR_HARNESS` | 存在性/空值外部字段契约 |
| `tests/test_rejection_wiring.py::test_provenance_from_stored_recovers_all_forms` | 9 | 566,568,569,571,572,574,575,576…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rejection_wiring.py::test_rollback_leaves_no_rows_and_no_jsonl` | 4 | 84,104,105,106 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure` | 1 | 490 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_batch_of_five_relations_all_enter_call_seam_concurrently` | 3 | 664,665,667 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_brew_636.py::test_brew_batch_runs_items_in_parallel_not_serialized` | 3 | 376,377,379 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_brew_636.py::test_brew_fn_value_error_is_program_error_propagates_loudly` | 1 | 545 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical` | 2 | 348,351 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_brew_636.py::test_brew_program_error_propagates_loudly_not_degraded` | 1 | 525 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_build_brew_input_projects_prior_event_fields` | 3 | 251,255,256 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_brew_636.py::test_duplicate_json_objects_rejected_not_first_object_picked` | 5 | 594,608,611,612,613 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_brew_636.py::test_failed_month_degrades_to_pending_and_rebrews_next_month` | 12 | 206,209,210,212,223,225,229,230…+4 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_brew_636.py::test_flip_brew_input_must_contain_new_edge_events` | 6 | 170,181,183,184,185,187 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_brew_636.py::test_founding_segment_survives_consecutive_brews_byte_identical` | 6 | 103,106,107,119,120,131 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_relation_brew_636.py::test_historical_events_alone_do_not_select_in_later_month` | 3 | 398,399,400 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_relation_brew_636.py::test_merge_founding_segment_append_only_and_dedup` | 5 | 406,407,408,410,411 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_brew_636.py::test_merge_founding_segment_exact_old_entry_re_report_appended_verbatim` | 2 | 435,439 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_merge_founding_segment_never_infers_by_lines` | 2 | 447,449 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_brew_636.py::test_merge_founding_segment_preserves_bytes_exactly` | 7 | 417,418,420,421,423,426,427 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_brew_636.py::test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews` | 4 | 152,153,155,156 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_brew_636.py::test_parse_seam_value_error_degrades_single_item` | 5 | 564,565,567,568,569 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_prepare_attaches_prior_events_only_via_history_seam` | 8 | 285,315,319,320,321,322,323,324 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_brew_636.py::test_relation_dimension_marks_emperor_edges` | 3 | 575,576,577 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_brew_636.py::test_unescaped_control_byte_rejected_not_stripped` | 3 | 631,632,633 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_relation_capture_633.py::test_authorized_dossier_origin_accepted_bound_to_current_turn` | 6 | 317,318,321,322,324,325 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_capture_633.py::test_authorized_dossier_outside_frozen_batch_rejected_zero_edges` | 5 | 355,356,357,360,361 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_context_stored_byte_identical_through_full_chain` | 1 | 449 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_capture_633.py::test_empty_capture_writes_nothing` | 2 | 140,144 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_capture_633.py::test_empty_or_all_invalid_targets_reject_whole_item_zero_edges` | 4 | 628,629,630,633 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_hallucinated_and_emperor_endpoints_rejected_per_item_zero_edges` | 3 | 533,534,535 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_interaction_then_same_batch_dismissal_still_lands` | 5 | 661,677,679,681,682 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_relation_capture_633.py::test_live_roster_cannot_rescue_endpoint_outside_passed_union` | 5 | 758,767,768,769,770 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_relation_capture_633.py::test_missing_endpoint_qualification_set_fails_loud` | 1 | 785 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_capture_633.py::test_missing_frozen_dossier_set_is_empty_closed_set` | 5 | 415,416,417,427,428 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_missing_or_forged_provenance_rejected_with_trace_no_edges` | 3 | 231,232,234 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_multi_target_with_blank_or_self_member_rejects_whole_item_zero_edges` | 4 | 591,592,593,596 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_multi_target_with_one_bad_endpoint_writes_zero_edges_for_item` | 3 | 556,557,560 | `KEEP_STRUCTURED_OR_HARNESS` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_never_qualified_endpoints_still_rejected_in_mutating_batch` | 4 | 742,743,744,745 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_non_string_actor_target_context_shapes_rejected` | 3 | 204,205,206 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_reinstatement_then_interaction_in_same_batch_still_lands` | 4 | 691,707,709,711 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_capture_633.py::test_replayed_delta_does_not_double_write` | 1 | 126 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_settlement_edge_origin_rejects_missing_and_non_string` | 1 | 271 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_capture_633.py::test_settlement_interaction_lands_directed_edge_with_origin_round` | 8 | 59,61,64,68,69,70,71,73 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_capture_633.py::test_shape_garbage_rejected_per_existing_extractor_contract` | 4 | 167,174,175,177 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_relation_capture_633.py::test_three_way_joint_memorial_expands_lead_to_each_cosigner_only` | 7 | 95,98,102,103,106,107,110 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_unauthorized_dossier_inside_frozen_set_still_rejected` | 3 | 392,393,394 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_valid_roster_endpoints_still_land_after_endpoint_gate` | 2 | 648,649 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_capture_633.py::test_whitespace_padded_noncanonical_origins_rejected_no_strip_rescue` | 3 | 252,253,255 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_capture_633.py::test_writer_rejects_non_string_context` | 1 | 481 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_capture_633.py::test_writer_stores_whitespace_context_byte_identical` | 1 | 461 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_read_640.py::test_blank_viewer_fails_closed_not_omniscient` | 2 | 101,104 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_read_640.py::test_dto_shape_summary_plus_recent_context_with_backref` | 3 | 129,130,132 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_read_640.py::test_empty_ledger_projects_empty` | 2 | 110,114 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_judge_face_reads_edges_invisible_to_role_view` | 3 | 165,167,170 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_load_relation_history_before_empty_when_no_older_events` | 1 | 296 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_load_relation_history_before_returns_full_stable_prior_stream` | 4 | 268,274,278,279 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_omniscient_is_superset_same_core` | 2 | 181,184 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_relation_read_640.py::test_participant_sees_own_edge_non_participant_default_invisible` | 2 | 76,79 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_role_view_cuts_by_either_end_participation` | 1 | 86 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_td7_dto_field_set_equals_frozen_whitelist` | 2 | 194,196 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_read_640.py::test_td7_local_marker_negative_assertion` | 3 | 217,220,221 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_read_640.py::test_updated_at_period_is_era_label_not_bare_turn` | 2 | 142,143 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_seed_638.py::test_fresh_seed_summary_is_readable_with_seed_event_clock` | 2 | 126,132 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_seed_638.py::test_invalid_bundled_seed_rolls_back_new_save_and_can_retry` | 4 | 246,247,254,255 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_seed_638.py::test_issue_639_seed_owner_audit_corrections` | 35 | 490,495,496,500,502,506,507,509…+27 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_seed_638.py::test_new_save_imports_sample_seed_ledger_queryable_and_pregame` | 3 | 320,323,326 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_seed_638.py::test_new_save_seed_founding_events_enter_founding_segment` | 5 | 474,476,478,479,480 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_seed_638.py::test_pre_tianqi_seed_event_projects_honest_calendar_label` | 1 | 360 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_seed_638.py::test_pregame_turn_scale_matches_load_state_mapping` | 4 | 171,172,173,174 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_seed_638.py::test_repeated_import_is_idempotent_no_double_write` | 7 | 381,382,383,386,394,395,396 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_seed_638.py::test_reverse_chronological_seed_keeps_latest_event_readable` | 3 | 343,345,346 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_relation_seed_638.py::test_seed_document_validation_is_fail_closed` | 2 | 106,110 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_relation_seed_638.py::test_seed_replay_does_not_overwrite_later_brew_summary` | 3 | 423,424,425 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_relation_seed_638.py::test_seeded_pair_flows_into_month_end_brew_selection` | 4 | 146,156,157,163 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_store_632.py::test_directed_edge_events_are_stored_and_queryable` | 5 | 30,31,32,33,34 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_store_632.py::test_distinct_pipe_origins_are_never_merged` | 3 | 138,140,141 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_store_632.py::test_edge_event_kind_and_evidence_are_fail_closed` | 3 | 71,72,73 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_relation_store_632.py::test_record_relation_edge_event_respects_caller_owned_transaction` | 6 | 157,167,171,172,173,179 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_relation_store_632.py::test_relation_edges_survive_restore` | 5 | 104,105,106,111,117 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_release_bundle_assets.py::test_pool_portrait_scan_falls_back_to_built_dist_when_public_absent` | 2 | 24,33 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_choices_563.py::test_657_capability_revalidate_on_follow` | 2 | 381,396 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_rescript_choices_563.py::test_decision_parser_rejects_empty_or_ambiguous_labels` | 1 | 364 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_choices_563.py::test_decision_parser_rejects_unknown_typed_action_and_keeps_sibling` | 3 | 349,350,351 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_choices_563.py::test_declared_staging_uses_typed_mode_not_minister_text` | 2 | 101,102 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_choices_563.py::test_financial_decision_uses_stored_option_not_client_payload` | 8 | 229,244,246,248,249,250,251,252 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_choices_563.py::test_held_dossier_rejection_stigma_is_idempotent_across_months` | 2 | 152,156 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_choices_563.py::test_missing_dossier_mode_defaults_to_ordinary` | 1 | 78 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_choices_563.py::test_predeclared_midzhi_promulgation_persists_stigma` | 1 | 65 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_rescript_choices_563.py::test_presence_aware_mode_preserves_draft_until_explicit_override` | 4 | 117,124,129,130 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_rescript_choices_563.py::test_rejected_midzhi_and_force_promulgation_are_idempotent` | 1 | 173 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_rescript_choices_563.py::test_rejected_ordinary_force_promulgation_adds_rescript_stigma` | 1 | 188 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_rescript_draft_656.py::test_1620_internal_canonical_xiexang_renormalizes_without_kind` | 3 | 1250,1251,1252 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_1620_layer_a_reward_with_army_target_stays_reward` | 1 | 1212 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_1620_validate_army_pay_grant_kind_maps_to_xiexang` | 4 | 1174,1175,1176,1177 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_657_s1_derive_draft_capability_stable_and_sensitive` | 4 | 1039,1043,1047,1051 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_657_s1_list_rescript_desk_merges_cross_month_and_decisions` | 18 | 1298,1300,1301,1302,1304,1307,1308,1309…+10 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_draft_656.py::test_657_s1_option_shape_stamps_draft_capability` | 5 | 1114,1115,1116,1129,1130 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_657_s1_rescript_emitted_set_subset_of_dossier` | 2 | 1019,1020 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_rescript_draft_656.py::test_657_s1_schema_columns_and_no_banned_fields` | 6 | 998,999,1000,1002,1004,1011 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_657_validate_layer_a_roundtrip_capability` | 8 | 1086,1088,1089,1090,1091,1092,1095,1096 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_draft_656.py::test_clear_pending_decisions_keeps_rescript_drafts` | 2 | 196,197 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_persist_then_abort_draft_never_enters_hitl_envelope` | 4 | 895,896,904,915 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_r3_lone_surrogate_field_rejects_whole_batch` | 1 | 982 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_repeated_overwrite_keeps_stable_synthetic_ids` | 4 | 263,267,268,271 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_rescript_draft_idx_continues_after_decision_rows` | 3 | 173,174,176 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_restore_roundtrip_at_awaiting_pause_has_no_draft_rows` | 3 | 855,857,858 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_save_and_list_rescript_drafts_roundtrip` | 9 | 145,147,148,149,150,151,152,153…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_save_pending_decisions_keeps_rescript_drafts` | 5 | 223,224,225,227,229 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_save_rescript_drafts_overwrites_not_duplicates` | 1 | 239 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_triage_actor_absent_when_both_offices_vacant` | 1 | 110 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rescript_draft_656.py::test_triage_actor_duplicate_hits_deterministic_order` | 1 | 105 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rescript_draft_656.py::test_triage_actor_falls_back_to_eunuch_director` | 1 | 89 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rescript_draft_656.py::test_triage_actor_follows_reappointment` | 2 | 117,123 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_rescript_draft_656.py::test_triage_actor_negative_yumajian_zhangyin_never_selected` | 1 | 96 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_rescript_draft_656.py::test_triage_actor_prefers_first_assistant_over_eunuch_director` | 1 | 82 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_validate_and_persist_preserve_whitespace_verbatim` | 10 | 294,296,297,298,299,300,301,305…+2 | `KEEP_STRUCTURED_FIELD` | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py::test_validate_items_accepts_optional_issue_id_binding_key` | 1 | 801 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_draft_656.py::test_validate_items_binds_only_board_issue_ids` | 2 | 681,682 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_validate_items_empty_list_is_legal_headless_month` | 1 | 767 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_draft_656.py::test_validate_items_empty_options_drops_item_keeps_siblings` | 4 | 748,749,750,751 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_validate_items_many_options_not_gated_or_truncated` | 2 | 737,738 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_validate_items_no_count_cap_keeps_all_legal` | 2 | 695,696 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_validate_items_non_list_options_drops_item_keeps_siblings` | 3 | 761,762,763 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_draft_656.py::test_validate_items_single_option_is_legal` | 3 | 725,726,727 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_rescript_heal_isolation_1801.py::_parse_heal` | 3 | 66,68,69 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_option_field_heal_1746.py::_assert_call_history` | 4 | 145,146,147,148 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_option_field_heal_1746.py::_field_failure_map` | 3 | 166,168,169 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_option_field_heal_1746.py::_parse_heal_request` | 4 | 155,157,158,159 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_option_field_heal_1746.py::test_run_agent_text_prior_messages_sent_as_message_list` | 5 | 201,203,204,205,206 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_rescript_option_field_heal_1746.py::test_run_agent_text_without_prior_passes_plain_prompt` | 2 | 226,227 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_run_agent_text_transport_1465.py::test_run_agent_text_final_text_from_terminal_not_chunk_join` | 2 | 51,52 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_run_agent_text_transport_1465.py::test_run_agent_text_history_backed_drops_empty_completed_before_retry` | 9 | 112,134,139,154,155,157,163,164…+1 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_runtime_llm_config.py::test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env` | 1 | 440 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_runtime_llm_config.py::test_cli_backend_active_total_on_unsupported_runner` | 1 | 451 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_runtime_llm_config.py::test_for_role_advanced_drops_placeholder_key` | 2 | 480,481 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_load_runtime_flat_cli_backend_placeholder_not_api_channel` | 1 | 428 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_coerces_stringified_numeric_fields` | 2 | 35,36 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_exposes_api_aliases_when_cli_is_active` | 4 | 304,305,306,307 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_garbage_numeric_fields_fall_back_to_default` | 2 | 49,50 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_ignores_legacy_max_tokens_key` | 5 | 69,70,71,72,73 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_malformed_json_returns_empty` | 1 | 20 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_migrates_flat_api_config` | 5 | 108,109,122,123,124 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_missing_file_keeps_empty_dict_contract` | 1 | 11 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_non_dict_payload_returns_empty` | 1 | 82 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_runtime_llm_config.py::test_load_runtime_llm_preserves_cli_reasoning_strength` | 1 | 332 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_runtime_llm_api_save_preserves_default_headers_when_omitted` | 3 | 644,645,646 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_runtime_llm_cli_save_preserves_api_default_headers` | 3 | 672,673,674 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_runtime_llm_default_headers_roundtrip_and_empty_is_status_quo` | 4 | 610,613,614,622 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_api_save_preserves_cli_reasoning_strength` | 3 | 204,205,206 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_can_clear_reasoning_strength_to_default` | 2 | 279,280 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_cli_save_can_seed_api_reasoning_strength` | 4 | 249,250,251,252 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_cli_save_preserves_api_reasoning_strength` | 4 | 228,229,230,231 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_persists_api_reasoning_strength` | 1 | 171 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_persists_channel_slots` | 6 | 145,146,147,148,149,150 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_preserves_existing_api_slot_when_saving_cli` | 10 | 394,395,396,397,400,401,402,403…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_runtime_llm_config.py::test_save_runtime_llm_preserves_existing_cli_slot_when_saving_api` | 3 | 353,354,355 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_scene_llm_1836.py::test_cli_selection_uses_scene_turn_as_admission_origin` | 6 | 138,139,141,143,144,150 | `KEEP_STRUCTURED_OR_HARNESS` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_dossier_participants_1252.py::_people` | 1 | 23 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_dossier_participants_1252.py::_secret` | 1 | 33 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_secret_dossier_participants_1252.py::test_month_segment_dispatch_uses_secret_order_dossier_ids_authority` | 5 | 222,233,234,236,241 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_dossier_participants_1252.py::test_s1_public_projection_filter_unchanged` | 2 | 45,46 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_dossier_participants_1252.py::test_s2_missing_secret_authority_never_rebuilds_from_live_db` | 2 | 261,262 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_dossier_participants_1252.py::test_s2_private_field_rejects_non_batch_and_public_ids` | 4 | 169,170,171,172 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_dossier_participants_1252.py::test_s2_public_dossier_participants_still_rejects_secret_id` | 2 | 125,126 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_dossier_participants_1252.py::test_s2_tracer_613_565_readers_see_appended_roster` | 5 | 86,91,93,100,101 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::_assert_oral_decree_withheld_not_shared` | 3 | 859,860,868 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_1026_secret_order_update_rollback_restores_existing_brief` | 3 | 1467,1485,1486 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_883_audience_chat_paraphrase_does_not_leave_origin_in_shared_sources` | 13 | 170,171,172,185,191,192,193,195…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py::test_883_audience_chat_path_does_not_leave_secret_in_shared_sources` | 10 | 129,130,136,141,146,147,148,149…+2 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_secret_order_isolation_883.py::test_883_cross_turn_chat_origin_withheld_on_late_secret_create` | 5 | 327,333,334,338,339 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_883_cross_turn_repeat_disclosed_does_not_mint_duplicate_public_event` | 7 | 671,677,678,689,694,695,696 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_isolation_883.py::test_883_only_explicit_leak_conclusion_promotes_secret_order_to_public` | 4 | 636,637,649,655 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_isolation_883.py::test_883_post_brief_public_audience_enters_shared_sources` | 7 | 289,292,293,297,300,309,310 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_883_public_audience_same_turn_survives_secret_classification` | 10 | 255,258,264,268,271,272,274,277…+2 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_883_shared_archive_bypass_positive_and_negative` | 2 | 588,595 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_883_shared_summary_write_seam_rejects_secret_order_source` | 2 | 111,112 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_883_shared_write_seam_keeps_public_assignee_audience` | 2 | 221,231 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_883_thematic_public_audience_survives_secret_create` | 8 | 389,392,398,403,404,409,410,411 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_883_two_turn_probe_secret_never_enters_shared_archives` | 5 | 57,79,80,81,82 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_883_zero_overlap_semantic_rewrite_withholds_prior_audience_origin` | 6 | 354,362,368,369,370,373 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_cross_person_speaker_user_origin_withheld_not_shared` | 5 | 708,717,722,723,732 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_held_user_chat_released_when_never_classified_as_secret` | 5 | 605,608,614,615,622 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_message_level_origin_persisted_on_brief` | 4 | 1583,1584,1587,1588 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_minister_reply_not_shared_before_classification` | 2 | 421,424 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_non_create_pure_public_not_auto_pinned_as_secret_origin` | 6 | 1067,1079,1086,1091,1094,1098 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin` | 3 | 1024,1030,1031 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_non_create_stage_commit_rush_withholds_oral_pin` | 6 | 944,965,968,973,975,982 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_976_non_create_stage_commit_update_withholds_oral_pin` | 9 | 882,886,910,913,918,921,922,924…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_pending_secret_pin_survives_partial_commit_same_minister` | 11 | 1162,1163,1164,1165,1166,1167,1170,1174…+3 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_976_pure_public_minister_reply_released_after_settle` | 2 | 441,446 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_release_stamps_original_message_date` | 4 | 563,564,571,572 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_secret_order_isolation_883.py::test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit` | 6 | 1198,1201,1206,1210,1211,1212 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_rt01_two_secret_orders_different_assignees_no_cross_track` | 21 | 1234,1237,1240,1241,1242,1243,1244,1245…+13 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_rt02_misassigned_provenance_follows_origin_message` | 10 | 1296,1299,1300,1312,1313,1314,1322,1323…+2 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_976_rt03_late_chat_after_create_same_turn` | 12 | 1337,1347,1348,1349,1352,1353,1354,1355…+4 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_rt04_undo_chat_turn_secret_order_brief_consistent` | 12 | 1399,1400,1403,1406,1407,1408,1428,1429…+4 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_isolation_883.py::test_976_rt05_save_restore_between_hold_and_release` | 17 | 1510,1512,1516,1532,1533,1534,1535,1545…+9 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_same_window_pure_public_user_survives_secret_classification` | 9 | 755,767,768,770,771,774,775,778…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_secret_chat_turn_withholds_both_sides_but_public_turn_survives` | 6 | 465,488,489,493,496,497 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py::test_976_stage_confirm_pin_provenance_not_max_held_user` | 8 | 791,820,824,829,838,840,842,851 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_isolation_883.py::test_976_withhold_does_not_yank_old_released_public_user` | 8 | 513,516,528,530,533,537,540,541 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_monthly_progress_566.py::test_character_terminal_status_closes_secret_orders_through_canonical_progress_rail` | 8 | 204,205,206,207,208,210,211,212 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_monthly_progress_566.py::test_current_secret_order_deadline_controls_monthly_eligibility` | 6 | 218,224,225,226,228,229 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_monthly_progress_566.py::test_disclosure_promotes_monthly_report_to_public_event_only_after_disclosure` | 3 | 111,127,128 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_monthly_progress_566.py::test_emperor_private_payload_preserves_monthly_report` | 3 | 73,95,96 | `KEEP_SECRET_ORDER_STRUCTURE` | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_monthly_progress_566.py::test_missing_bad_unknown_and_duplicate_reports_are_rejected` | 1 | 402 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_monthly_progress_566.py::test_only_an_existing_monthly_chain_gets_terminal_progress` | 2 | 168,169 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_secret_order_monthly_progress_566.py::test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | 9 | 324,359,362,364,369,372,374,376…+1 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_monthly_progress_566.py::test_titles_do_not_classify_and_all_active_secret_orders_are_candidates` | 4 | 138,148,149,150 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::_catch_names` | 1 | 203 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::_minister` | 1 | 89 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_secret_order_payoff_1504.py::test_1376_candidate_confirm_freezes_explicit_typed_contract` | 6 | 799,802,803,804,805,806 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_4a_declaration_lands_actions_and_spoliation_through_month_chain` | 12 | 1538,1560,1561,1565,1567,1568,1572,1574…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_4a_unknown_target_declaring_spoliation_is_rejected` | 3 | 1372,1373,1374 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_actual_progress_container_separate_from_reported_rail` | 9 | 345,346,347,348,350,351,352,355…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_auto_submit_due_no_longer_flips_pending_review` | 3 | 633,634,638 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_case_opening_source_clue_assists_its_fact` | 3 | 1133,1137,1140 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_case_opening_without_pointer_creates_no_clue` | 3 | 1173,1177,1178 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_catch_quantity_tracer_same_unit_done_and_mismatch_ignored` | 4 | 2595,2598,2599,2600 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_closed_case_blocks_same_fact_on_later_case_and_due` | 10 | 2449,2453,2454,2455,2488,2490,2494,2495…+2 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_confirm_persists_task_specific_contract_absent_before` | 9 | 304,311,312,313,314,315,322,323…+1 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_create_secret_order_rejects_missing_contract` | 1 | 2611 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_decide_settlement_delivery_gap_bidirectional` | 3 | 240,246,251 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_deep_dig_lands_through_month_chain_entry` | 59 | 1677,1678,1684,1685,1687,1689,1698,1699…+51 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_payoff_1504.py::test_false_memorial_does_not_create_or_erase_evidence` | 4 | 1495,1512,1513,1515 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_fiscal_quantity_tracer_same_unit_done_and_gap` | 4 | 2529,2530,2544,2545 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_gap_after_months_failed` | 5 | 464,468,472,473,474 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_invalid_investigation_declaration_is_rejected_not_zero_effort` | 8 | 1970,1971,1972,1973,1974,1981,1982,1983 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_payoff_1504.py::test_investigation_history_is_not_truncated` | 3 | 1211,1214,1215 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_investigator_away_from_target_cannot_acquire_evidence` | 4 | 882,883,892,899 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_merged_clue_assists_the_fact_it_points_at` | 17 | 2191,2192,2197,2198,2199,2205,2213,2232…+9 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_mid_month_restore_preserves_actual_progress` | 5 | 589,596,597,598,599 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_missing_minister_row_no_progress` | 1 | 570 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_monthly_actual_does_not_invent_generic_world_package` | 5 | 679,680,684,685,686 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite` | 2 | 655,657 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_monthly_actual_then_delivered_done` | 6 | 438,442,443,444,446,447 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_n_month_deadline_yields_exactly_n_ticks` | 9 | 491,493,494,507,509,510,511,515…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_no_evidence_case_opens_and_stays_empty` | 7 | 1234,1242,1249,1250,1251,1254,1255 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_non_finite_effort_is_invalid_not_full_investment` | 5 | 838,840,841,848,849 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_non_investigation_contract_keeps_its_delivery_account` | 2 | 1099,1100 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_offstage_minister_no_progress_no_world_effects` | 5 | 538,546,547,548,549 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_positive_inflow_does_not_freeze_purpose_and_counts` | 7 | 2694,2713,2714,2715,2720,2721,2724 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_purpose_liaoxiang_canonicalizes_to_other_and_counts` | 4 | 2623,2636,2644,2645 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_reaction_declarations_need_real_knowledge_across_months` | 3 | 933,950,953 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_region_monthly_progress_sums_increments_without_final_value_gate` | 3 | 2665,2677,2680 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_region_quantity_ignores_same_origin_turn_with_mismatched_identity` | 1 | 2570 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_payoff_1504.py::test_repeated_pointerless_orders_do_not_mint_clues` | 12 | 2092,2104,2105,2108,2109,2120,2121,2122…+4 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_rush_preserves_frozen_contract` | 4 | 729,731,732,733 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_secret_order_closes_field_is_ignored` | 2 | 617,618 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_seed_guilt_structured_clean_vs_debt` | 6 | 228,229,230,231,232,233 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_settle_due_keeps_existing_progress_result_over_memorial` | 4 | 397,411,412,413 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_settle_due_reads_actual_rail_only_report_does_not_flip_verdict` | 3 | 382,383,385 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_spoliated_fact_reported_as_unreachable_in_feed` | 4 | 2413,2414,2418,2419 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_payoff_1504.py::test_spoliation_makes_fact_harder_and_survives_case_reopen` | 9 | 1425,1429,1432,1443,1444,1455,1456,1457…+1 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_spoliation_requires_real_knowledge_source` | 10 | 1290,1291,1292,1310,1311,1319,1320,1334…+2 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_payoff_1504.py::test_submit_unlimited_keeps_frozen_target` | 12 | 698,699,701,704,706,708,709,710…+4 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_supply_feed_carries_per_fact_investigation_materials` | 8 | 2344,2346,2348,2350,2351,2352,2354,2356 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_payoff_1504.py::test_supply_feed_identity_material_is_empty_for_topic_target` | 3 | 2300,2301,2302 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_payoff_1504.py::test_task_specific_contract_from_explicit_fields_not_tags` | 5 | 266,267,268,269,270 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_payoff_1504.py::test_topic_investigation_backlash_fails_without_world_package` | 7 | 2752,2753,2757,2758,2759,2764,2765 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_payoff_1504.py::test_unlimited_investigation_due_now_reads_real_acquisitions` | 7 | 759,762,769,773,776,777,778 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_secret_order_section_rejections.py::test_apply_score_extraction_secret_order_update_respects_outer_transaction_rollback` | 5 | 90,92,93,97,98 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_secret_order_section_rejections.py::test_oversized_order_id_rejected_not_crash` | 1 | 113 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_section_rejections.py::test_update_nonint_order_id_invalid_enum` | 1 | 35 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_section_rejections.py::test_update_unknown_order_id_missing_ref` | 2 | 51,52 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_secret_order_section_rejections.py::test_update_valid_active_order_applies_no_reject` | 2 | 73,74 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_secret_order_update.py::test_creation_brief_uses_persisted_truncated_title` | 1 | 134 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_secret_order_update.py::test_update_by_id_keeps_assignee_brief_identical_to_persisted_order` | 2 | 116,124 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_update.py::test_update_by_id_noop_on_non_active` | 2 | 143,145 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_secret_order_update.py::test_update_by_id_persists_assignee_brief_after_restore` | 6 | 80,85,99,104,105,106 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_update.py::test_update_by_id_preserves_tags_when_none` | 1 | 57 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_update.py::test_update_by_id_targets_exact_order_not_newest` | 4 | 40,43,46,47 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_secret_order_update.py::test_update_preserves_long_text` | 3 | 67,72,73 | `KEEP_SECRET_ORDER_STRUCTURE` | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_update.py::test_upsert_creates_then_updates` | 5 | 14,18,19,21,22 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_secret_order_update.py::test_upsert_different_minister_creates_new` | 1 | 29 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::_a_region` | 1 | 35 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::_an_army` | 1 | 41 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::_valid_power_id` | 1 | 293 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::test_absent_optional_army_fields_use_defaults` | 2 | 586,587 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::test_all_score_fields_guarded_on_creation` | 2 | 644,648 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_army_cannon_over_cap_clamps_not_rejected` | 2 | 435,438 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_army_firearm_over_100_clamps_not_rejected` | 2 | 476,479 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_army_missing_manpower_rejected_good_builds` | 5 | 344,345,346,347,349 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::test_dirty_army_value_rejected_sibling_lands` | 4 | 280,281,282,285 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_dirty_optional_army_field_rejects_item` | 3 | 568,571,572 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_dirty_region_cannon_value_rejected_not_abort` | 3 | 548,549,554 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_dirty_region_value_rejected_sibling_lands` | 4 | 120,121,122,125 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_duplicate_army_noninteger_manpower_rejected` | 3 | 528,529,530 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_duplicate_army_without_manpower_rejected` | 3 | 366,367,368 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_illegal_army_field_rejected_sibling_lands` | 4 | 257,258,259,262 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_illegal_region_field_rejected_sibling_lands` | 4 | 95,96,97,100 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_inertia_natural_resolution_tolerated_rejection_no_crash` | 2 | 702,704 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_section4_rejections.py::test_issue_path_tolerated_rejections_reach_reports` | 2 | 675,676 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_issue_path_tolerates_previously_skipped_cases` | 1 | 607 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_nondict_new_army_item_recorded_not_silent` | 2 | 627,628 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_region_army_formatters_skip_rejected_items` | 6 | 494,502,506,507,510,511 | `KEEP_STRUCTURED_OR_HARNESS` | 必要负向：禁泄露片段 |
| `tests/test_section4_rejections.py::test_region_cannon_over_cap_clamps_not_rejected` | 2 | 457,460 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_region_controlled_by_accepts_existing_power_ids_and_restore_hook` | 5 | 160,171,172,179,180 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_section4_rejections.py::test_region_controlled_by_mixed_invalid_and_valid_siblings_apply` | 4 | 203,204,211,212 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_region_controlled_by_rejects_non_power_id_and_preserves_region` | 3 | 144,146,150 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_section4_rejections.py::test_unknown_army_rejected_good_item_lands` | 4 | 234,236,237,240 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section4_rejections.py::test_unknown_owner_power_army_rejected_good_builds` | 5 | 314,315,316,320,324 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section4_rejections.py::test_unknown_region_rejected_good_item_lands` | 4 | 72,74,75,78 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section_fiscal_rejections.py::test_change_central_loss_rate_pair_above_100_rejected` | 4 | 386,387,389,390 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_section_fiscal_rejections.py::test_change_central_loss_rate_rebalance_uses_batch_final_total` | 3 | 420,422,423 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_section_fiscal_rejections.py::test_change_dirty_delta_rejected_sibling_lands` | 4 | 292,293,294,296 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_change_dynamic_tax_rate_scales_region_field` | 2 | 344,349 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section_fiscal_rejections.py::test_change_empty_key_rejected` | 3 | 323,324,325 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_change_structural_sink_loss_rate_below_floor_rejected` | 3 | 364,365,366 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_change_unknown_key_rejected_good_change_lands` | 4 | 267,269,270,272 | `KEEP_STRUCTURED_OR_HARNESS` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_change_zero_delta_no_op_not_rejected` | 1 | 309 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_section_fiscal_rejections.py::test_chinese_direction_alias_accepted_at_applier` | 2 | 576,579 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_create_absent_init_value_defaults_zero` | 1 | 246 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section_fiscal_rejections.py::test_create_dirty_init_value_rejected_not_silent_zero` | 5 | 224,225,226,228,230 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_create_duplicate_key_rejected_good_create_lands` | 3 | 173,174,176 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_create_illegal_account_rejected_sibling_lands` | 5 | 197,198,199,200,202 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section_fiscal_rejections.py::test_create_rate_only_sibling_collision_rejected_not_abort` | 1 | 456 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_create_with_rate_suffix_key_rejected` | 2 | 501,502 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_direct_fiscal_create_display_defaults_from_key` | 1 | 628 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section_fiscal_rejections.py::test_direct_remove_central_human_loss_rate_stem_refuses_loss_pair` | 2 | 150,151 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section_fiscal_rejections.py::test_double_suffix_key_rejected_no_phantom` | 2 | 538,539 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_double_suffix_remove_rejected_not_destructive` | 3 | 552,559,562 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_section_fiscal_rejections.py::test_empty_key_rejected_even_with_noop_delta` | 1 | 471 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_falsy_dirty_delta_still_rejected` | 2 | 439,440 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_fiscal_change_reopens_with_value_origin_history_and_scaled_rows` | 3 | 674,675,682 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_section_fiscal_rejections.py::test_garbage_key_category_consistent_across_sections` | 3 | 645,646,647 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_section_fiscal_rejections.py::test_lossless_int_string_same_verdict_both_paths` | 3 | 611,612,613 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_section_fiscal_rejections.py::test_negative_init_value_rejected_not_clamped` | 2 | 519,520 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_remove_central_human_loss_rate_rejected_as_loss_pair` | 3 | 117,118,119 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_remove_central_human_loss_rate_stem_rejected_as_loss_pair` | 3 | 137,138,139 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_remove_dynamic_tax_still_zeroes_region_field` | 2 | 80,85 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_section_fiscal_rejections.py::test_remove_missing_key_rejected` | 2 | 484,485 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_remove_structural_sink_loss_rate_rejected` | 3 | 100,101,102 | `KEEP_STRUCTURED_FIELD` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_remove_unknown_fiscal_key_rejected_good_removal_lands` | 4 | 56,58,59,61 | `KEEP_STRUCTURED_OR_HARNESS` | 财政/数量外部账结果 |
| `tests/test_section_fiscal_rejections.py::test_whitespace_only_key_rejected_at_applier` | 2 | 592,593 | `KEEP_FISCAL_ORACLE` | 财政/数量外部账结果 |
| `tests/test_session_write_queue_1353.py::test_barrier_proceeds_after_worker_fail_vacate` | 2 | 321,339 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_session_write_queue_1353.py::test_barrier_waits_multiple_prior_tickets` | 4 | 103,128,131,132 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_session_write_queue_1353.py::test_get_session_write_queue_wiring_fail_loud_no_broad_swallow` | 5 | 512,513,514,515,516 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_session_write_queue_1353.py::test_post_barrier_claim_cannot_cross_barrier_write` | 5 | 255,265,266,267,274 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_session_write_queue_1353.py::test_run_exclusive_serializes_writes` | 3 | 372,373,379 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_session_write_queue_1353.py::test_ticketed_gate_cancel_blocks_write` | 2 | 219,226 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_session_write_queue_1353.py::test_wait_pending_writes_fail_loud_on_false_and_exception` | 1 | 523 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_session_write_queue_1353.py::test_write_turn_still_blocks_on_open_barrier` | 4 | 457,467,468,473 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_settle_core.py::test_pre_settle_persists_event_terminal_states_in_write_path` | 4 | 62,63,69,82 | `KEEP_STRUCTURED_OR_HARNESS` | 存在性/空值外部字段契约 |
| `tests/test_settle_core.py::test_pre_settle_runs_fixed_fiscal_tick` | 2 | 28,29 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_settlement_write_guard_393.py::read_directive_dossier_payload` | 1 | 40 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_settlement_write_guard_393.py::test_advance_short_hold_409_when_gate_taken_after_admit` | 6 | 340,343,346,348,349,350 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_settlement_write_guard_393.py::test_advance_without_edict_refused_by_phase` | 2 | 259,260 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_settlement_write_guard_393.py::test_advance_without_edict_refused_when_gate_held` | 4 | 288,290,291,292 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_settlement_write_guard_393.py::test_direct_db_write_refused_by_phase` | 2 | 225,226 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_settlement_write_guard_393.py::test_direct_db_write_refused_when_gate_held` | 2 | 239,240 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_settlement_write_guard_393.py::test_direct_db_write_succeeds_when_free` | 2 | 362,363 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_settlement_write_guard_393.py::test_directive_capture_result_is_rejected_after_turn_changes` | 2 | 187,188 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_settlement_write_guard_393.py::test_directive_capture_runs_outside_write_gate` | 3 | 159,160,161 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_shared_resource_order_1844.py::_settled_declaration` | 1 | 21 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_shared_resource_order_1844.py::test_player_decree_missing_entity_rejection_persists_for_feed` | 4 | 153,156,164,167 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_shared_resource_order_1844.py::test_player_decrees_sequential_army_station_reads_updated_roster` | 7 | 185,191,210,218,219,220,221 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_shared_resource_order_1844.py::test_player_decrees_soft_cap_shared_treasury_in_order` | 4 | 124,125,130,133 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_shared_resource_order_1844.py::test_world_segment_cross_category_order_by_declaration` | 5 | 256,258,262,264,265 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_shared_resource_order_1844.py::test_world_segment_cross_category_order_survives_reopen` | 6 | 294,297,298,306,309,312 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_shared_resource_order_1844.py::test_world_segment_stamps_each_shared_item_once` | 7 | 372,373,374,375,376,377,378 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_six_sciences_seed_608.py::test_fresh_seed_contains_sourced_six_sciences_censors` | 14 | 25,32,34,35,36,39,40,41…+6 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_six_sciences_seed_608.py::test_six_sciences_censor_exit_recomputes_its_faction_leverage` | 2 | 63,75 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_six_sciences_seed_608.py::test_six_sciences_offices_infer_to_own_category` | 4 | 14,15,16,17 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_staged_assignment_identity_1890.py::_finish_turn` | 1 | 67 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_staged_assignment_identity_1890.py::_payload` | 1 | 52 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_staged_assignment_identity_1890.py::_promulgate_assignment` | 2 | 589,592 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_staged_assignment_identity_1890.py::_promulgated_policy_origin` | 1 | 539 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_staged_assignment_identity_1890.py::test_assignment_prose_year_promise_lands_no_staged_commitment` | 6 | 616,617,618,619,620,622 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_staged_assignment_identity_1890.py::test_assignment_stages_prose_string_never_reaches_promulgation` | 4 | 652,653,655,658 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_assignment_structured_stages_land_through_full_chain` | 4 | 677,678,679,680 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_staged_assignment_identity_1890.py::test_declared_new_secret_order_lands_and_undo_removes_all_records` | 9 | 360,370,375,377,378,385,388,393…+1 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_staged_assignment_identity_1890.py::test_dispatch_stamps_source_turn_on_each_staged_assignment` | 3 | 94,95,98 | `KEEP_STRUCTURED_FIELD` | 公开结果空集合（未 move/无存档/无拒收） |
| `tests/test_staged_assignment_identity_1890.py::test_failed_turn_cleanup_removes_this_turn_staged_assignment` | 3 | 424,429,432 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_month_chain_staging_has_no_source_turn` | 1 | 151 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_staged_assignment_identity_1890.py::test_new_issues_prose_year_promise_does_not_become_commitment_stages` | 3 | 707,708,710 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_new_issues_structured_stages_still_land` | 2 | 739,743 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_pacification_commission_keeps_its_own_mode_and_gets_source_turn` | 5 | 125,128,129,130,131 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_staged_assignment_identity_1890.py::test_retry_restore_removes_this_turn_staged_assignment` | 3 | 451,462,465 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_revision_keeps_original_source_turn_and_undo_restores_it` | 8 | 272,273,280,281,289,290,291,292 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_undo_voids_this_turns_assignments_without_rollback_log` | 6 | 181,191,198,200,204,207 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_staged_assignment_identity_1890.py::test_void_discards_that_directive_night_forecast` | 2 | 325,330 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_staged_assignment_identity_1890.py::test_voided_assignment_cannot_be_approved_after_retraction` | 3 | 228,229,232 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_start_sh_deps_1721.py::test_start_sh_default_path_runs_pip_frontend_and_uvicorn_in_order` | 11 | 128,130,131,132,133,134,135,136…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_start_sh_deps_1721.py::test_start_sh_pip_failure_does_not_start_uvicorn` | 5 | 149,150,152,153,154 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_start_sh_deps_1721.py::test_start_sh_syncs_requirements_before_uvicorn` | 12 | 99,101,102,103,104,105,106,107…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure` | 1 | 348 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_atomic_and_reload_commits_on_success` | 1 | 293 | `KEEP_STRUCTURED_FIELD` | 结构化数值外部结果；非生成文盯文 |
| `tests/test_state_reload.py::test_atomic_and_reload_reloads_and_reraises_at_depth0` | 2 | 307,308 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_atomic_and_reload_runs_on_error_before_reload` | 1 | 368 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_atomic_and_reload_skips_reload_when_nested` | 1 | 332 | `KEEP_STRUCTURED_FIELD` | 可观察集合/计数外部结果 |
| `tests/test_state_reload.py::test_metrics_refresh_never_empty_window` | 3 | 229,230,232 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_pre_settle_self_reloads_memory_on_rollback` | 6 | 129,132,134,135,140,141 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_reload_content_no_crash` | 2 | 83,84 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_reload_passes_llm_config_to_content_rebuild` | 1 | 281 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_state_reload.py::test_reload_refreshes_state_in_place` | 6 | 48,49,54,55,56,57 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_state_reload.py::test_reload_scrubs_dirty_settling_phase` | 2 | 101,107 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_state_reload.py::test_reload_scrubs_next_period_advance` | 3 | 67,71,72 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_reload_skipped_inside_nested_atomic` | 1 | 216 | `KEEP_STRUCTURED_FIELD` | 可观察集合/计数外部结果 |
| `tests/test_state_reload.py::test_rollback_purges_content_character_ghost` | 5 | 169,170,180,184,188 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_state_reload.py::test_rollback_restores_existing_character_attributes` | 2 | 263,264 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_structured_decree_contract_1624.py::_assert_drafted_roster_nailed` | 3 | 69,71,73 | `KEEP_STRUCTURED_FIELD` | 顺序/大小外部可比结果（非内部方向 oracle 默许） |
| `tests/test_structured_decree_contract_1624.py::test_normalize_rescript_layer_a_option_contract` | 4 | 504,508,518,526 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_structured_decree_contract_1624.py::test_rescript_follow_draft_nails_drafted_roster` | 8 | 323,326,327,328,329,330,331,332 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_structured_decree_contract_1624.py::test_shared_validate_rejects_region_id_and_category_holes` | 5 | 173,184,185,192,193 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_style_temperament_641.py::test_apply_score_extraction_rejects_invalid_temperament` | 11 | 233,235,236,238,239,240,241,242…+3 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_style_temperament_641.py::test_apply_score_extraction_writes_temperament_style_and_log` | 6 | 91,101,102,103,119,120 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_character_context_with_db_reads_own_style_and_viewer_ledger` | 5 | 278,280,283,284,286 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_context_passes_raw_style_and_ledger_prose_without_rewrite` | 8 | 333,337,338,339,340,341,342,343 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_inertia_natural_resolve_applies_temperament_style` | 7 | 69,70,71,72,77,83,84 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_relation_edge_events_do_not_mutate_style` | 7 | 377,379,380,381,382,383,388 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_style_temperament_641.py::test_temperament_committed_style_survives_reload` | 2 | 205,206 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_temperament_does_not_write_relation_edges` | 2 | 407,408 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_temperament_outer_tx_rollback_restores_db_and_runtime` | 3 | 188,191,192 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_style_temperament_641.py::test_temperament_style_preserves_raw_bytes_through_write_kernel` | 12 | 129,138,139,141,155,157,158,159…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_supervision_625.py::_insert_staged` | 1 | 137 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_supervision_625.py::test_ac1_monthly_write_idempotent_readable_and_restore` | 17 | 196,198,199,200,201,202,205,206…+9 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_supervision_625.py::test_ac1_presence_exposure_schema_pragma_and_no_dulling_cols` | 5 | 153,158,165,166,178 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_supervision_625.py::test_ac1_settle_segment_writes_presence` | 2 | 254,256 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_supervision_625.py::test_ac2_paired_observation_slots_and_countermeasure_hard_gate` | 13 | 298,299,306,307,308,309,311,312…+5 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_supervision_625.py::test_ac4_exposure_history_delta_on_tendency_surface` | 6 | 343,344,350,351,352,354 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_supervision_625.py::test_ac4_unified_presence_gate_on_terminal_and_recon_paths` | 10 | 372,380,382,392,393,394,408,409…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_supervision_625.py::test_due_review_supervision_history_no_longer_hardcoded_empty` | 5 | 449,450,457,459,460 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_surcharge_causal_chain_650.py::_gazette_projection_body` | 1 | 369 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_surcharge_causal_chain_650.py::_settle_month` | 1 | 66 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_batch_rejects_duplicate_surcharge_and_matching_explicit_transfer` | 4 | 187,188,189,190 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_surcharge_causal_chain_650.py::test_decree_bad_items_rejected_individually` | 3 | 146,147,148 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_surcharge_causal_chain_650.py::test_decree_lands_accumulated_ledger_same_turn` | 7 | 88,93,95,96,97,100,101 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_e2e_surcharge_and_stop_share_month_open_snapshot` | 3 | 460,465,469 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_exact_levy_fact_stays_out_of_public_read_chain_and_free_report_enters_it` | 4 | 382,383,392,393 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_surcharge_causal_chain_650.py::test_levy_ledger_corruption_fails_loud` | 1 | 356 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_surcharge_causal_chain_650.py::test_levy_pass_folds_jiapai_into_sanxiang_targets` | 2 | 243,244 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_ming_province_without_fiscal_base_is_not_a_levy_member` | 2 | 316,317 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_surcharge_causal_chain_650.py::test_no_decree_no_ledger_entry` | 2 | 108,110 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_province_without_population_pool_rejects_surcharge_and_old_ledger_exits` | 5 | 282,283,299,300,301 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_repeated_decrees_accumulate_and_negative_stops` | 4 | 120,121,126,131 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_surcharge_causal_chain_650.py::test_repeated_delta_apply_does_not_consume_levy_ledger` | 2 | 219,220 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_surcharge_causal_chain_650.py::test_surcharge_filter_does_not_capture_other_transfer_origins` | 2 | 204,205 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_surcharge_causal_chain_650.py::test_surcharge_origin_requires_effect_eligible_materialized_dossier` | 3 | 171,172,173 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_surcharge_causal_chain_650.py::test_unmarked_cutover_save_rejects_and_never_consumes_surcharge` | 5 | 440,441,446,447,448 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_surcharge_causal_chain_650.py::test_zero_base_province_gets_no_transfer` | 2 | 326,327 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_textual_facts_1828.py::test_append_inside_atomic_rolls_back_with_outer_transaction` | 1 | 127 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_textual_facts_1828.py::test_sun_chuanting_injury_then_recovery_both_readable_by_month` | 2 | 15,37 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_textual_facts_1828.py::test_textual_facts_are_not_rumors_and_do_not_change_character_mechanics` | 4 | 106,107,108,109 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_textual_facts_1828.py::test_textual_facts_on_army_region_and_affair_are_object_materials` | 4 | 70,73,76,79 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_textual_facts_1828.py::test_textual_facts_survive_reopen` | 1 | 158 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::_fiscal_config_value` | 1 | 23 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_atomic_normal_exit_commits_to_disk` | 1 | 76 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_atomic_reraises_original_exception` | 3 | 226,228,230 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_atomic_rolls_back_on_error` | 1 | 59 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_atomic_suspends_internal_method_commit` | 1 | 91 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_begin_failure_at_entry_restores_flags` | 3 | 575,576,579 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_commit_failure_at_atomic_exit_rolls_back` | 4 | 482,483,484,485 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_commit_failure_in_conn_context_rolls_back` | 2 | 457,458 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_connection_commit_attempts_all_runtime_callbacks` | 1 | 372 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_connection_context_inside_atomic_rolls_back` | 1 | 278 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_connection_context_outside_atomic_still_commits` | 1 | 288 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_transaction_boundary.py::test_connection_rollback_attempts_all_runtime_callbacks` | 1 | 348 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_ddl_after_explicit_midatomic_rollback_does_not_escape` | 2 | 554,555 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_ddl_after_swallowed_conn_context_does_not_escape` | 1 | 533 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_ddl_first_inside_atomic_rolls_back` | 1 | 437 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_game_db_owns_transaction_tracks_atomic_and_open_transactions` | 4 | 29,32,34,39 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_nested_atomic_both_succeed_commits_once` | 2 | 126,135 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_nested_atomic_inner_commit_held_outer_rolls_back` | 3 | 107,110,111 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_nested_atomic_inner_error_rolls_back_at_outer` | 5 | 247,248,250,251,253 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_outside_atomic_commit_is_real` | 1 | 168 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_rollback_still_works_during_suspension` | 2 | 148,152 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_set_fiscal_config_batch_respects_caller_owned_transaction` | 6 | 199,206,207,208,210,211 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_set_fiscal_config_respects_caller_owned_transaction` | 4 | 179,183,184,186 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transaction_boundary.py::test_swallowed_conn_context_exception_forces_outer_rollback` | 4 | 408,409,410,411 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transaction_boundary.py::test_swallowed_inner_exception_forces_outer_rollback` | 4 | 309,311,312,314 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_transit_aging_346.py::test_pre_settle_ticks_arrival_before_terminal_states` | 3 | 195,198,207 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transit_aging_346.py::test_tick_does_not_arrive_when_remaining_still_positive` | 5 | 219,224,229,230,231 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_aging_346.py::test_行止_change_dest_is_rejected` | 3 | 149,150,151 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_aging_346.py::test_行止_payload_cannot_write_arrival` | 3 | 89,90,91 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_aging_346.py::test_行止_reemit_same_dest_preserves_start_turn` | 4 | 110,122,123,124 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_transit_aging_346.py::test_行止_sets_transit_start_turn` | 4 | 65,66,69,70 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_countdown_668.py::_assert_ledger_match` | 7 | 249,250,251,253,255,257,259 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_countdown_668.py::_assert_transit_frame_equal` | 8 | 175,176,177,178,180,182,184,186 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_countdown_668.py::test_arrivals_sorted_by_name_stable` | 3 | 265,272,273 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transit_countdown_668.py::test_henan_beizhili_matrix_special_case_le_one_and_symmetric` | 2 | 40,41 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_transit_countdown_668.py::test_henan_normal_speed_arrives_next_month` | 10 | 48,49,50,52,53,56,58,60 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_transit_countdown_668.py::test_mid_countdown_save_reopen_continues_identically` | 10 | 196,197,206,207,209,217,231,235…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 结构化 harness 断言助手，非自由文本哨兵 |
| `tests/test_transit_countdown_668.py::test_ousted_in_transit_stops_countdown_and_never_arrives` | 10 | 157,160,161,162,165,167,168 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py::test_pre_settle_tick_before_event_terminal_reads_new_location` | 6 | 98,107,108,116 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py::test_pre_settle_tick_before_seed_auto_trigger_reads_new_location` | 7 | 128,137,138,147,148 | `KEEP_FISCAL_ORACLE` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py::test_speed_factors_match_f2_oracle_on_differentiated_route` | 14 | 70,71,72,77,79,80,82,83…+3 | `KEEP_STRUCTURED_FIELD` | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_urge_lever_624.py::_executing_policy_dossier` | 1 | 61 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_urge_lever_624.py::test_commitment_rush_via_pending_actions_gate` | 10 | 580,582,589,590,596,599,600,601…+2 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_grace_plea_payload_truth_hidden_from_player_ac6` | 13 | 258,260,261,262,266,267,269,272…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_urge_lever_624.py::test_missing_urge_and_supervision_fail_closed_ac7` | 2 | 331,332 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_urge_lever_624.py::test_payload_json_corrupt_read_is_loud` | 3 | 629,630,631 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_payload_json_roundtrip_insert_list_restore` | 3 | 460,462,468 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_urge_lever_624.py::test_remonstrance_not_projected_applied_or_takeover` | 9 | 410,414,419,420,423,424,429,430…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_rush_does_not_side_write_end_turn` | 1 | 498 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_rush_staged_commitment_advances_due_and_fills_urge_history` | 10 | 128,129,135,137,140,143,144,145…+2 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_rush_without_issue_fail_closed_no_remonstrance` | 1 | 365 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_urge_audience_project_and_consume_path` | 7 | 528,530,532,533,538,539,544 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_urge_lever_624.py::test_urge_history_restore_from_committed_pending_ac7` | 2 | 350,351 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_urge_lever_624.py::test_urge_no_longer_rewrites_verdict_ac1_1895` | 3 | 220,224,225 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_audience_night_498.py::test_asgi_dossiered_directive_has_no_retired_review_surface` | 9 | 529,542,543,546,550,551,552,553…+1 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_audience_night_498.py::test_asgi_hanging_chat_issue_waits_for_worker_terminal` | 8 | 753,771,785,786,788,789,790,791 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_audience_night_498.py::test_asgi_inflight_reply_lands_then_issue_closes_and_advances` | 9 | 595,597,625,627,630,633,634,635…+1 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_audience_night_498.py::test_asgi_phase_flip_while_waiting_gate_rejected` | 3 | 514,515,516 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_audience_night_498.py::test_legacy_pending_only_advances_to_durable_dossier_without_review_api` | 9 | 701,702,711,713,714,715,717,718…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_audience_night_498.py::test_night_approved_directive_closes_into_month_end_without_second_review` | 7 | 653,661,662,663,664,665,670 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_audience_night_498.py::test_pending_translation_retries_original_round_after_night_seal` | 5 | 203,204,205,206,209 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_audience_night_498.py::test_persisted_reply_before_translation_admission_has_no_retry_button` | 2 | 180,181 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_audience_night_498.py::test_sync_advance_endpoint_does_not_stall_event_loop` | 3 | 836,837,839 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_audience_night_498.py::test_translation_failure_retry_and_undo_through_audience_http` | 37 | 241,267,270,272,273,276,280,281…+29 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_chat_serialization_393.py::test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn` | 7 | 217,234,235,242,243,245,246 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_chat_serialization_393.py::test_chat_stream_sse_waits_for_sync_generator_in_executor` | 2 | 308,309 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_chat_serialization_393.py::test_identity_setup_failure_preserves_question_and_releases_pending_owner` | 6 | 259,263,264,265,266,267 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_chat_serialization_393.py::test_lightweight_stream_seam_reaches_done_without_durable_identity_or_night_signature` | 2 | 274,276 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_chat_serialization_393.py::test_nonstream_api_chat_keeps_game_state_responsive_while_chat_blocks` | 3 | 359,363,364 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_chat_serialization_393.py::test_nonstream_chat_rejects_when_session_draining` | 2 | 385,386 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_active_consort_chat_not_rejected` | 1 | 250 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_active_ming_minister_visible` | 1 | 31 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_active_minister_not_in_talent_pool` | 1 | 132 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_active_non_ming_character_not_in_court` | 1 | 47 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_amnestied_rebel_excluded_from_talent_pool` | 2 | 160,161 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_choose_minister_real_entry_excludes_weishi_includes_court` | 1 | 552 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_court_visibility.py::test_consort_excluded_from_court` | 1 | 196 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_db_active_included_even_if_memory_offstage` | 1 | 70 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_db_offstage_excluded_even_if_memory_active` | 2 | 56,57 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_db_resolve_power_id_authoritative` | 3 | 396,399,402 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_enemy_active_character_cannot_be_summoned` | 2 | 308,310 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_find_existing_minister_uses_db_power_id` | 2 | 383,386 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_identity_resolves_weishi_and_vassal_aliases_no_duplicate_file` | 13 | 485,486,487,488,498,499,504,508…+5 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_court_visibility.py::test_list_ministers_uses_db_power_id` | 2 | 361,364 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_normal_ming_minister_still_summonable` | 1 | 339 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_web_court_visibility.py::test_offstage_former_minister_in_talent_pool` | 2 | 123,125 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_real_court_ministers_not_collateral_damaged_by_1317` | 6 | 463,465,466,467,469,473 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_same_year_future_month_debut_excluded_from_talent_pool` | 2 | 177,179 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_court_visibility.py::test_shi_kefa_not_in_summonable_court_roster` | 12 | 432,434,435,437,438,442,443,444…+4 | `KEEP_STRUCTURED_FIELD` | 字符串结构化/夹具契约 |
| `tests/test_web_court_visibility.py::test_summon_power_check_uses_db_not_content` | 2 | 328,330 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_court_visibility.py::test_vassal_prince_chat_rejected` | 2 | 227,231 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_vassal_prince_excluded_from_court` | 3 | 103,104,105 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_vassal_prince_excluded_from_talent_pool` | 2 | 140,141 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_court_visibility.py::test_zongfan_cannot_be_summoned_via_can_summon` | 3 | 270,272,280 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_web_llm_runtime_config.py::_assert_hud` | 3 | 908,909,910 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_1271_menu_save_cli_grok_high_round_trip` | 7 | 816,817,818,819,820,821,822 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_1271_three_endpoints_grok_reasoning_supported_and_capability_list` | 15 | 843,844,845,846,847,863,864,865…+7 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_accepts_default_headers` | 3 | 649,650,651 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_commit_runs_on_event_loop` | 2 | 224,225 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_explicit_cli_channel_switch` | 9 | 152,153,154,155,156,157,158,159…+1 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_response_reports_reasoning_capability` | 2 | 129,130 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception` | 3 | 271,272,273 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_api_set_llm_config_verify_runs_off_event_loop` | 2 | 245,246 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_web_llm_runtime_config.py::test_build_llm_config_does_not_reuse_placeholder_as_api_key` | 2 | 1157,1158 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_build_llm_config_recovers_preserved_api_key_on_switch_back` | 2 | 77,78 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_build_llm_config_switches_to_api_on_real_key_over_backend_env` | 10 | 55,56,57,58,59,60,61,62…+2 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_commit_cli_preserves_when_slot_already_has_key` | 2 | 200,201 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_commit_cli_seeds_api_slot_from_session_when_slot_empty` | 4 | 181,182,183,184 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_continue_load_save_reach_hud_zero_llm_calls` | 14 | 954,982,987,988,998,999,1006,1007…+6 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_fresh_start_zero_llm_calls_disposes_old_main_db` | 3 | 926,927,928 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_game_llm_config_reports_active_cli_channel_without_fake_api_key` | 11 | 728,729,730,731,732,733,734,735…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_game_llm_config_reports_inactive_cli_reasoning_strength` | 3 | 769,770,771 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_game_llm_config_uses_advanced_model_for_api_reasoning_capability` | 1 | 790 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_game_start_rejects_placeholder_api_key` | 1 | 1170 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_hot_replace_http_failure_keeps_old_state_and_writes_usable` | 7 | 1107,1109,1110,1112,1114,1115,1116 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_llm_runtime_config.py::test_hot_replace_http_success_reopens_state_and_writes` | 8 | 1054,1056,1057,1059,1061,1062,1063,1064 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_llm_runtime_config.py::test_menu_save_cli_verify_runs_off_event_loop` | 2 | 455,456 | `KEEP_STRUCTURED_FIELD` | 存在性/空值外部字段契约 |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_accepts_default_headers_from_request` | 4 | 574,575,576,577 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_api_channel_rejects_placeholder_existing_key` | 2 | 1135,1136 | `KEEP_STRUCTURED_FIELD` | 长度/计数/身份/能力等结构化外部结果（非默许纯数字） |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_cli_channel_rejects_empty_runner` | 3 | 496,497,498 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_persists_cli_channel_without_api_key` | 15 | 418,419,420,421,422,423,424,425…+7 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_validates_api_channel_over_backend_env` | 4 | 516,517,518,519 | `KEEP_STRUCTURED_OR_HARNESS` | 字符串结构化/夹具契约 |
| `tests/test_web_llm_runtime_config.py::test_menu_save_llm_verify_carries_runtime_default_headers` | 2 | 545,546 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_active_cli_placeholder_api_key_not_counted` | 3 | 320,321,323 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_active_cli_unsupported_runner_not_ready_despite_preserved_api_key` | 3 | 297,298,300 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_and_game_config_expose_default_headers` | 2 | 614,617 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_reports_inactive_cli_reasoning_strength` | 3 | 372,373,374 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_reports_reasoning_strength_capability_for_cli_runner` | 4 | 342,343,344,345 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_treats_saved_cli_runtime_as_ready_without_api_key` | 4 | 678,679,680,681 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_unsupported_cli_runner_not_ready` | 4 | 474,475,476,477 | `KEEP_STRUCTURED_FIELD` | 枚举/状态机/字段名等结构化结果 |
| `tests/test_web_llm_runtime_config.py::test_menu_status_uses_advanced_model_for_api_reasoning_capability` | 1 | 395 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_web_llm_runtime_config.py::test_set_llm_config_cli_placeholder_not_real_api_key` | 2 | 105,106 | `KEEP_STRUCTURED_FIELD` | 公开布尔/状态字段 |
| `tests/test_world_materials_1834.py::test_all_characters_get_an_experience_file_not_just_current_court` | 2 | 76,85 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_character_army_region_textual_facts_reach_world_directory` | 1 | 129 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_prepare_rebuilds_from_world_record_after_restore` | 1 | 147 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_prepare_writes_typed_tree_with_board_affairs_and_gazette_index` | 11 | 45,46,48,49,52,53,54,55…+3 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_world_materials_carry_due_fiscal_levy_petitions` | 6 | 316,319,324,326,328,332 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_world_materials_carry_eligible_person_event_candidates` | 8 | 281,283,285,288,289,290,298,299 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_world_materials_include_textual_facts_once_and_gazette_not_duplicated` | 12 | 232,237,238,240,241,245,247,250…+4 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_world_materials_1834.py::test_world_materials_isolate_invocations_and_databases` | 5 | 157,158,159,178,180 | `KEEP_STRUCTURED_OR_HARNESS` | 其余 assert：按外部可见结构化结果保留 |
| `tests/test_yuan_arrival_185.py::test_arrival_clearing_is_not_noop_negative_control` | 2 | 168,169 | `KEEP_STRUCTURED_FIELD` | 索引字段外部结果 |
| `tests/test_yuan_arrival_185.py::test_yuan_arrears_paid_then_arrives_e2e` | 19 | 38,39,40,41,42,49,51,82…+11 | `KEEP_STRUCTURED_FIELD` | 其余 assert：按外部可见结构化结果保留 |
| `web/src/appDurableWiring.test.tsx::(module)` | 542 | 97,120,122,126,127,135,140,141…+534 | `KEEP_STRUCTURED_OR_HARNESS` | web 结构化字段/枚举字符串 |
| `web/src/buildResources.test.ts::(module)` | 5 | 46,56,61,62,67 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/chatFailures.test.ts::(module)` | 18 | 16,21,43,50,51,52,53,69…+10 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/components/cliRunnerDropdown.consistency.test.tsx::(module)` | 9 | 52,157,158,159,160,164,255,256…+1 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/components/decisionModal.test.tsx::(module)` | 123 | 42,45,46,56,63,64,65,66…+115 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx::(module)` | 119 | 98,163,164,165,166,167,168,193…+111 | `KEEP_STRUCTURED_OR_HARNESS` | web 标量断言；按用例外部可见结果保留 |
| `web/src/components/gameMenu.test.tsx::(module)` | 108 | 59,91,100,102,111,145,146,149…+100 | `KEEP_STRUCTURED_OR_HARNESS` | web 标量断言；按用例外部可见结果保留 |
| `web/src/components/map.test.tsx::(module)` | 12 | 78,85,103,104,140,141,142,144…+4 | `KEEP_STRUCTURED_OR_HARNESS` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx::(module)` | 68 | 85,86,96,127,128,143,144,147…+60 | `KEEP_STRUCTURED_OR_HARNESS` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx::(module)` | 329 | 56,57,293,294,295,296,298,302…+321 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx::(module)` | 54 | 104,108,109,110,113,114,119,124…+46 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementGazettePanel.test.tsx::(module)` | 7 | 28,37,38,39,40,45,47 | `KEEP_STRUCTURED_OR_HARNESS` | web 结构化字段/枚举字符串 |
| `web/src/components/situation.test.tsx::(module)` | 23 | 71,78,84,92,117,136,137,144…+15 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/decisionRouting.test.tsx::(module)` | 57 | 29,30,35,36,45,46,51,52…+49 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/escClose.test.tsx::(module)` | 17 | 46,59,62,65,69,75,105,107…+9 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | web DOM/fixture 结构契约 |
| `web/src/mindreading.test.ts::(module)` | 2 | 11,15 | `KEEP_STRUCTURED_OR_HARNESS` | web expect 结构化匹配 |
| `web/src/mindreadingDelivery.test.tsx::(module)` | 33 | 112,136,141,142,148,149,154,177…+25 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/settleStream.test.ts::(module)` | 6 | 29,37,45,53,59,73 | `KEEP_STRUCTURED_OR_HARNESS` | web 结构化字段/枚举字符串 |
| `web/src/staleGuard.test.tsx::(module)` | 25 | 84,105,166,167,251,263,324,325…+17 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useDurableProjection.test.tsx::(module)` | 11 | 43,71,72,73,78,79,80,81…+3 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | web DOM/fixture 结构契约 |
| `web/src/useSettlementFlow.test.tsx::(module)` | 95 | 196,199,203,207,208,213,214,215…+87 | `KEEP_DOM_FIXTURE_OR_STRUCTURE` | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
