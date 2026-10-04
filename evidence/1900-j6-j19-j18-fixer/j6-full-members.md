# J6 全仓成员表（权威）

类定义：清除盯文、内部伪证及未完成失败路径的初始态证明；完成/失败/回滚须可辨别。

法源：对自由文本一切机械依赖均属盯文；**P7 禁模板负向不是合法盯文豁免**（若成立须删，不得标 KEEP）。

枚举：`git ls-files` 全仓测试 + Python AST（比较/包含/相等/正则/生成文本名 + mock/helper/oracle/wait/boundary）+ TS 行扫。
原始候选：`j6-ast-candidates.jsonl`；摘要：`j6-ast-summary.json`；命令：`enum-cmd.txt`。

**本表禁止未决项，禁止以他票/web 划拒修。** 不成立→KEEP+契约；成立→FIX。

## 处置计数

```
KEEP_DOM_FIXTURE_OR_STRUCTURE: 396
KEEP_LLM_BOUNDARY: 195
KEEP_IO_BOUNDARY: 162
KEEP_STRUCTURED_FIELD: 87
KEEP_STRUCTURED_OR_HARNESS: 80
KEEP_RESCRIPT_STRUCTURE: 75
KEEP_WEB_FETCH_HARNESS: 73
KEEP_FISCAL_ORACLE: 28
KEEP_LLM_CONFIG_SURFACE: 25
KEEP_FIXTURE_OR_SEED: 23
KEEP_CLI_ARGV_OR_ASSEMBLY: 22
KEEP_FIXTURE_ECHO: 16
KEEP_SECRET_ORDER_STRUCTURE: 16
KEEP_COMPLETION_SYNC: 15
KEEP_UI_CHROME: 12
KEEP_P4_NEGATIVE: 12
KEEP_TYPED_ERROR_SHAPE: 6
KEEP_SEED_SOURCE_ID: 5
FIX_THREAD_FACTORY: 4
KEEP_STRUCTURED_SCROLL: 1
KEEP_ARCHIVE_SHAPE: 1
KEEP_REJECTION_NEGATIVE: 1
KEEP_STRUCTURED_SUMMON: 1
KEEP_TRACE_ONCE: 1
KEEP_THREAD_CAPTURE: 1
TOTAL_FOCUS: 1258
```

## 本轮代码 FIX

- `tests/test_menu_lifecycle_drain_396.py`：`_capture_real_drain_threads` → `make_thread` 工厂。
- `ming_sim/db.py`：`_merge_directive_payload` 先 normalize 新名单，空则 pop；非空再共享 merge。
- `tests/test_grant_reconciliation_567.py`：删软判提案失效说明（J18）。
- 先前：草案伪证整条删除；截止平行块删除；拒收负向保留。

## 原未决项（本轮逐项结清）

| path | line | disposition | why |
|---|---|---|---|
| `tests/test_audience_restore_505.py` | 332 | KEEP_FIXTURE_ECHO | retry 路径回传本测注入的 canned answer；另有 chat_messages/calls 结构化断言 |
| `tests/test_audience_scroll_539.py` | 327 | KEEP_STRUCTURED_SCROLL | 断言 beat/divider/record_id 结构化派生；「臣遵旨」仅 append_night_chat 夹具入参 |
| `tests/test_audience_scroll_539.py` | 420 | KEEP_ARCHIVE_SHAPE | list_closed_night_archives 标题/audience_type/无 content 键；夹具回话非盯文 |
| `tests/test_audience_translate_1837.py` | 246 | KEEP_REJECTION_NEGATIVE | 真实 translate 入口未知 section/坏形状拒收；不证截止 |
| `tests/test_audience_translate_1837.py` | 365 | KEEP_LLM_BOUNDARY | FakeAgent 边界；断言 appointment/grant/ledger 结构化效果 |
| `tests/test_audience_translate_1837.py` | 600 | KEEP_LLM_BOUNDARY | FakeAgent 边界；CLI/API 同形结构化声明 |
| `tests/test_audience_translate_1837.py` | 804 | KEEP_LLM_BOUNDARY | FakeAgent 边界；pending 增删应允 undo 的 DB 状态 |
| `tests/test_audience_travel_gating_670.py` | 251 | KEEP_STRUCTURED_SUMMON | Admission 枚举 + unsettled origin_id 集合；reason=="" 为空因字段 |
| `tests/test_cli_backend.py` | 751 | KEEP_CLI_ARGV_OR_ASSEMBLY | CliChat.invoke 装配：用户消息 EXTRACT 进入 prompt；response_format 有无改变装配 |
| `tests/test_cli_backend.py` | 998 | KEEP_TRACE_ONCE | 密令提取 trace 条数==1；canned JSON 为 runner 替身返回值非叙事盯文 |
| `tests/test_month_chain_1847.py` | 1384 | KEEP_LLM_BOUNDARY | supply 边界 + SettlementAbort.stage + dossier_progress 空/非空 + call_count 重试 |
| `tests/test_month_chain_1847.py` | 1455 | KEEP_LLM_BOUNDARY | supply 边界 + 崩溃恢复幂等；产物落库与不再重跑 supply |
| `tests/test_month_chain_1847.py` | 1563 | KEEP_LLM_BOUNDARY | supply 边界 + 缺 fidelity 内联记录的结构化链标志 |
| `tests/test_month_chain_1847.py` | 1806 | KEEP_LLM_BOUNDARY | supply 边界 + 非校验失败保留产物的结构化状态 |
| `tests/test_menu_lifecycle_drain_396.py` | 126 | FIX_THREAD_FACTORY | api_menu_new_game + 真实 Thread.join 后断言 move/文件；工厂已去包装类 |
| `tests/test_menu_lifecycle_drain_396.py` | 211 | FIX_THREAD_FACTORY | 同上 WAL 回滚完成后再断言外部路径 |
| `tests/test_menu_lifecycle_drain_396.py` | 258 | FIX_THREAD_FACTORY | 同上 close 失败不 move |

## 全焦点成员

| path | line | test | tags | disposition | why |
|---|---|---|---|---|---|
| `tests/conftest.py` | 433 | _offline_audience_translation_provider | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/conftest.py` | 434 | _offline_audience_translation_provider | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/conftest.py` | 490 | stub_audience_translate | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/conftest.py` | 520 | _offline_scene_beat_generator | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/month_chain_helpers.py` | 59 | canned_full_settlement | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/month_chain_helpers.py` | 60 | canned_full_settlement | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/month_chain_helpers.py` | 64 | canned_full_settlement | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_applier_contract.py` | 104 | test_apply_context_holds_all_fields | GEN_TEXT_ATTR,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 应用上下文/军籍结构化字段 |
| `tests/test_army_card_status_1501.py` | 76 | _assert_ming_register | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 应用上下文/军籍结构化字段 |
| `tests/test_army_card_status_1501.py` | 79 | _assert_ming_register | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_army_card_status_1501.py` | 85 | _assert_text_keeps_statuses | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_background.py` | 153 | _wait_for_pending_writes_to_drain | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_audience_draft_grant_once_1777.py` | 105 | test_http_audience_one_matter_grant_with_d | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_restore_505.py` | 332 | test_post_reply_failure_resumes_close_with | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | retry 路径回传本测注入的 canned answer；另有 chat_messages/calls 结构化断言 |
| `tests/test_audience_restore_505.py` | 788 | web_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_audience_scroll_539.py` | 327 |  | PRIOR_REVIEW | KEEP_STRUCTURED_SCROLL | 断言 beat/divider/record_id 结构化派生；「臣遵旨」仅 append_night_chat 夹具入参 |
| `tests/test_audience_scroll_539.py` | 442 | test_closed_night_archive_derives_stable_t | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_ARCHIVE_SHAPE | list_closed_night_archives 标题/audience_type/无 content 键；夹具回话非盯文 |
| `tests/test_audience_translate_1837.py` | 151 | test_pending_round_approval_endorsed_befor | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 190 | test_pending_round_approval_endorsed_befor | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 246 |  | PRIOR_REVIEW | KEEP_REJECTION_NEGATIVE | 真实 translate 入口未知 section/坏形状拒收；不证截止 |
| `tests/test_audience_translate_1837.py` | 365 |  | PRIOR_REVIEW | KEEP_LLM_BOUNDARY | FakeAgent 边界；断言 appointment/grant/ledger 结构化效果 |
| `tests/test_audience_translate_1837.py` | 413 | test_appointment_and_relief_through_scene_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 468 | test_appointment_and_relief_through_scene_ | ASSERT_COMPARE,GEN_TEXT_ATTR,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_audience_translate_1837.py` | 555 | test_emperor_准_via_scene_chat_approves_no_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 626 | test_scene_chat_cli_and_api_same_translati | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | FakeAgent 边界；CLI/API 同形结构化声明 |
| `tests/test_audience_translate_1837.py` | 725 | test_translate_call_failure_is_not_empty_s | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 739 | test_translate_call_failure_is_not_empty_s | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_audience_translate_1837.py` | 757 | test_translate_empty_success_still_dispatc | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837.py` | 765 | test_translate_empty_success_still_dispatc | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_audience_translate_1837.py` | 819 | test_translation_pending_create_approve_re | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | FakeAgent 边界；pending 增删应允 undo 的 DB 状态 |
| `tests/test_audience_translate_1837.py` | 1038 | test_scene_chat_translation_can_approve_st | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837_reopen.py` | 128 | _player_month | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_audience_translate_1837_reopen.py` | 129 | _player_month | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_audience_translate_1837_reopen.py` | 135 | _player_month | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_audience_translation_once_1898.py` | 59 | test_reopen_webgame_catches_up_pending_tra | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_audience_travel_gating_670.py` | 251 |  | PRIOR_REVIEW | KEEP_STRUCTURED_SUMMON | Admission 枚举 + unsettled origin_id 集合；reason=="" 为空因字段 |
| `tests/test_breach_plea_623.py` | 481 | test_revoke_forecast_translation_input_car | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_breach_plea_623.py` | 482 | test_revoke_forecast_translation_input_car | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_breach_plea_623.py` | 483 | test_revoke_forecast_translation_input_car | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_character_knowledge_489.py` | 117 | test_turn_zero_knowledge_is_role_specific_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_SEED_SOURCE_ID | 确定性种子 source_id / 知识事件身份字段 |
| `tests/test_character_knowledge_489.py` | 118 | test_turn_zero_knowledge_is_role_specific_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_SEED_SOURCE_ID | 确定性种子 source_id / 知识事件身份字段 |
| `tests/test_character_knowledge_489.py` | 529 | test_long_knowledge_bodies_survive_storage | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SEED_SOURCE_ID | 确定性种子 source_id / 知识事件身份字段 |
| `tests/test_character_knowledge_489.py` | 786 | test_knowledge_titles_restore_without_pers | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SEED_SOURCE_ID | 确定性种子 source_id / 知识事件身份字段 |
| `tests/test_character_knowledge_489.py` | 974 | test_archive_write_materializes_unmirrored | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SEED_SOURCE_ID | 确定性种子 source_id / 知识事件身份字段 |
| `tests/test_character_knowledge_489.py` | 1005 | test_turn_report_counterpart_never_uses_ag | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_character_knowledge_489.py` | 1131 | test_structured_person_scope_replaces_role | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_chat_stream_failpaths_393.py` | 459 | _assert_structured_llm_http | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_chat_stream_failpaths_393.py` | 460 | _assert_structured_llm_http | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_chat_stream_failpaths_393.py` | 506 | test_nonstream_api_issue_decree_llm_unavai | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_chat_stream_failpaths_393.py` | 1035 | test_chat_stream_halfstream_retry_replaces | GEN_TEXT_NAME | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_chat_stream_failpaths_393.py` | 1049 | test_chat_stream_halfstream_retry_replaces | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_chat_stream_failpaths_393.py` | 1083 | test_chat_stream_halfstream_terminal_fail_ | GEN_TEXT_NAME | KEEP_TYPED_ERROR_SHAPE | 流式失败 typed detail/provider 字段 |
| `tests/test_cli_backend.py` | 44 | _patch_backend | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 63 | test_secret_exclusion_extracts_people_and_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 78 | test_extract_secret_order_preserves_long_t | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 82 | test_extract_secret_order_preserves_long_t | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py` | 118 | test_secret_content_assembly_is_emperor_pl | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 172 | test_enrich_army_parsed_and_normalized | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 184 | test_enrich_building_region_floor | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 190 | test_enrich_backend_error_returns_empty_ef | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 197 | test_enrich_nondict_subfields_guarded | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 208 | test_enrich_trace_records_actual_backend | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 286 | test_run_claude_stdout_only | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 288 | test_run_claude_stdout_only | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | runner argv/拼装提示含调用方原文；属传输装配契约非叙事盯文 |
| `tests/test_cli_backend.py` | 337 | test_agy_materials_mode_uses_material_cwd_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 347 | test_run_codex_flags_and_stdout | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 378 | test_codex_streaming_runner_degrades_to_on | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 379 | test_codex_streaming_runner_degrades_to_on | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 382 | test_codex_streaming_runner_degrades_to_on | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 427 | test_api_backend_streaming_emits_real_toke | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 428 | test_api_backend_streaming_emits_real_toke | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 467 | test_luna_shaped_stream_keeps_content_when | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_backend.py` | 472 | test_codex_final_text_handles_item_complet | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 494 | test_run_runner_accepts_config_model | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 524 | test_run_codex_stdout_empty_fallback | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 531 | test_run_claude_maps_reasoning_strength_to | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 539 | test_run_claude_off_reasoning_uses_explici | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 656 | test_login_shell_path_uses_printenv_not_do | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | runner argv/拼装提示含调用方原文；属传输装配契约非叙事盯文 |
| `tests/test_cli_backend.py` | 748 | test_clichat_invoke_builds_prompt_and_comp | ASSERT_COMPARE,GEN_TEXT_ATTR,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CliChat.invoke 装配：用户消息 EXTRACT 进入 prompt；response_format 有无改变装配 |
| `tests/test_cli_backend.py` | 769 | test_clichat_invoke_json_constraint_and_no | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | runner argv/拼装提示含调用方原文；属传输装配契约非叙事盯文 |
| `tests/test_cli_backend.py` | 785 | test_clichat_invoke_error_traced_and_rerai | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 803 | test_clichat_call_cli_dispatch | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 804 | test_clichat_call_cli_dispatch | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 805 | test_clichat_call_cli_dispatch | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 851 | test_run_agy_success_single_subprocess | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 933 | test_run_backend_infers_trace_tag_from_pro | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 945 | test_run_backend_for_config_traces_every_c | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 963 | test_run_backend_for_config_passes_reasoni | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 979 | test_run_backend_for_config_traces_on_back | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 991 | test_office_inference_llm_call_is_traced | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 1002 | test_secret_extract_traces_exactly_once | BOUNDARY_STUB | KEEP_TRACE_ONCE | 密令提取 trace 条数==1；canned JSON 为 runner 替身返回值非叙事盯文 |
| `tests/test_cli_backend.py` | 1065 | test_run_cursor_flags_and_stdout | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 1068 | test_run_cursor_flags_and_stdout | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | runner argv/拼装提示含调用方原文；属传输装配契约非叙事盯文 |
| `tests/test_cli_backend.py` | 1071 | test_run_cursor_flags_and_stdout | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 1079 | test_run_kimi_prompt_flag_no_yolo_stdout_o | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 1081 | test_run_kimi_prompt_flag_no_yolo_stdout_o | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 1092 | test_run_grok_flags_effort_and_plain | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 1094 | test_run_grok_flags_effort_and_plain | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 1108 | test_run_pi_flags_thinking_and_stdout | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_backend.py` | 1110 | test_run_pi_flags_thinking_and_stdout | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_CLI_ARGV_OR_ASSEMBLY | runner argv/拼装提示含调用方原文；属传输装配契约非叙事盯文 |
| `tests/test_cli_backend.py` | 1115 | test_run_pi_flags_thinking_and_stdout | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_backend.py` | 1145 | test_run_backend_for_config_dispatches_new | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_backend.py` | 1153 | test_run_backend_for_config_dispatches_new | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_cli_backend.py` | 1168 | test_clichat_call_cli_dispatches_new_runne | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_play_turn.py` | 174 | test_terminal_minister_chat_persists_messa | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 195 | test_terminal_minister_chat_persists_messa | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 229 | test_terminal_minister_chat_removes_user_m | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 245 | test_terminal_minister_chat_removes_user_m | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 278 | test_terminal_minister_chat_removes_user_m | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 294 | test_terminal_minister_chat_removes_user_m | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 375 | test_terminal_minister_chat_reply_persist_ | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_cli_play_turn.py` | 610 | test_terminal_minister_chat_accepts_retry_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_cli_play_turn.py` | 634 | test_terminal_minister_chat_accepts_retry_ | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_cli_play_turn.py` | 680 | test_play_turn_hitl_advancement_ends_turn | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_cli_play_turn.py` | 681 | test_play_turn_hitl_advancement_ends_turn | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_cli_runner_error_typed_1299.py` | 48 | test_clichat_runner_exit_raises_typed_llm_ | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_runner_error_typed_1299.py` | 49 | test_clichat_runner_exit_raises_typed_llm_ | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_CLI_ARGV_OR_ASSEMBLY | CLI runner 装配/stdout 夹具契约 |
| `tests/test_cli_runner_error_typed_1299.py` | 70 | test_clichat_normal_reply_still_returns | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_cli_runner_error_typed_1299.py` | 86 | test_extract_agent_text_error_status_raise | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_cli_runner_error_typed_1299.py` | 87 | test_extract_agent_text_error_status_raise | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_court_break_player_lock_1727.py` | 49 | web_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_declaration_dispatch_1835.py` | 68 | test_stub_declaration_lands_on_existing_st | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_declaration_dispatch_1835.py` | 112 | test_commission_with_draft_and_grant_for_s | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_declaration_dispatch_1835.py` | 166 | test_commission_with_appointment_and_grant | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_declaration_dispatch_1835.py` | 229 | test_reference_to_nonexistent_entity_is_re | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_declaration_dispatch_1835.py` | 256 | test_unknown_top_level_section_is_rejected | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_declaration_dispatch_1835.py` | 448 | test_presence_lands_with_declared_body_ver | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_declaration_dispatch_1835.py` | 754 | test_staged_declaration_discard_and_idempo | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py` | 334 | test_pending_directive_only_enters_settlem | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py` | 999 | test_manual_directive_capture_reaches_stru | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1011 | test_manual_directive_capture_reaches_stru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_decree_dossiers_571.py` | 1017 | test_manual_directive_capture_reaches_stru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_decree_dossiers_571.py` | 1067 | test_manual_directive_capture_rejects_malf | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1106 | test_manual_directive_capture_rejects_miss | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1239 | test_cli_edit_replaces_text_and_mechanics_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1247 | test_cli_edit_replaces_text_and_mechanics_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_decree_dossiers_571.py` | 1252 | test_cli_edit_replaces_text_and_mechanics_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_decree_dossiers_571.py` | 1439 | test_session_manual_directive_keeps_struct | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1580 | test_allocation_rejects_unknown_economy_ac | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py` | 1658 | test_incomplete_mechanical_directive_is_re | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py` | 1682 | test_mechanical_directive_missing_target_f | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_dossiers_571.py` | 1737 | test_draft_extraction_does_not_capture_act | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 1778 | test_batch_draft_extraction_preserves_each | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_dossiers_571.py` | 2058 | test_secret_authorization_rejects_missing_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_decree_forecast_1861.py` | 203 | test_scene_chat_approval_forecasts_each_de | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 219 | test_scene_chat_approval_forecasts_each_de | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 231 | test_scene_chat_approval_forecasts_each_de | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_forecast_1861.py` | 335 | test_scene_chat_rejection_is_staged_for_la | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 336 | test_scene_chat_rejection_is_staged_for_la | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 350 | test_scene_chat_rejection_is_staged_for_la | GEN_TEXT_ATTR | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_decree_forecast_1861.py` | 385 | test_repeat_scene_approval_does_not_rerun_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 386 | test_repeat_scene_approval_does_not_rerun_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 427 | test_restored_directive_forecast_uses_its_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 428 | test_restored_directive_forecast_uses_its_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 432 | test_restored_directive_forecast_uses_its_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_forecast_1861.py` | 501 | test_held_rejudgments_overlap_instead_of_w | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 502 | test_held_rejudgments_overlap_instead_of_w | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 503 | test_held_rejudgments_overlap_instead_of_w | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_decree_forecast_1861.py` | 568 | test_same_local_ids_on_two_saves_both_stag | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 569 | test_same_local_ids_on_two_saves_both_stag | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_decree_forecast_1861.py` | 570 | test_same_local_ids_on_two_saves_both_stag | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_deepseek_thinking_disable_1797.py` | 26 | test_create_chat_model_deepseek_on_hermes_ | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 39 | test_create_chat_model_deepseek_on_officia | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 52 | test_create_chat_model_deepseek_on_dashsco | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 65 | test_create_chat_model_deepseek_on_minimax | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 78 | test_create_chat_model_non_deepseek_on_rel | GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 113 | test_create_chat_model_deepseek_strength_s | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 128 | test_create_chat_model_deepseek_enable_thi | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 138 | test_create_chat_model_deepseek_enable_thi | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 152 | test_create_chat_model_non_deepseek_dashsc | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 166 | test_create_chat_model_non_deepseek_minima | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 217 | test_dump_llm_messages_records_reasoning_u | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_deepseek_thinking_disable_1797.py` | 218 | test_dump_llm_messages_records_reasoning_u | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_dossier_links_559.py` | 75 | test_reference_candidates_hide_other_minis | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_dossier_reported_progress_619.py` | 111 | test_execution_surface_dossier_can_record_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_dossier_reported_progress_619.py` | 196 | test_origin_namespace_minimum_closed_set_a | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_draft_admission_resubmit_1769.py` | 144 | _queue_backend | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 182 | _assert_error_pack_from | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_draft_admission_resubmit_1769.py` | 183 | _assert_error_pack_from | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_draft_admission_resubmit_1769.py` | 286 | test_draft_admission_resubmit_success_adva | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_draft_admission_resubmit_1769.py` | 288 | test_draft_admission_resubmit_success_adva | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_draft_admission_resubmit_1769.py` | 330 | test_draft_admission_exhaust_keeps_draft_a | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 364 | test_draft_admission_exhaust_keeps_draft_a | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 409 | test_draft_admission_mixed_good_and_bad_in | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 503 | test_resubmit_non_intent_keeps_original_pa | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 555 | test_pending_product_error_enters_resubmit | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_draft_admission_resubmit_1769.py` | 595 | test_exhaust_zero_dossier_system_simulatio | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_due_review_621.py` | 190 | test_unconsumed_todo_rolls_across_settles_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_due_review_621.py` | 200 | test_unconsumed_todo_rolls_across_settles_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_due_review_621.py` | 265 | test_due_review_scene_tops_live_open_night | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_enrich_list_guards.py` | 23 | test_enrich_buildings_non_list_no_crash | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_enter_settlement_period_1235.py` | 61 | _fake_settlement_llm | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_enter_settlement_period_1235.py` | 74 | _fake_settlement_llm | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_enter_settlement_period_1235.py` | 87 | web_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_enter_settlement_period_1235.py` | 223 | test_web_entry_captures_before_await_close | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_enter_settlement_period_1235.py` | 460 | test_advance_http_reject_after_accept_exit | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_execution_pressure_654.py` | 552 | test_path2_pending_bad_roster_stays_draft_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py` | 560 | test_path2_pending_bad_roster_stays_draft_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py` | 594 | test_path3_locality_fail_keeps_draft_no_te | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py` | 597 | test_path3_locality_fail_keeps_draft_no_te | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_execution_pressure_654.py` | 607 | test_path3_locality_fail_keeps_draft_no_te | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_executor_routing_721.py` | 319 | test_pending_routing_rejection_lands_on_en | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py` | 322 | test_pending_routing_rejection_lands_on_en | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py` | 334 | test_pending_routing_rejection_lands_on_en | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py` | 337 | test_pending_routing_rejection_lands_on_en | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_executor_routing_721.py` | 398 | test_directive_routing_rejection_rolls_bac | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_faction_denunciation_627.py` | 262 | test_ac2_scripted_accept_and_clamp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_faction_denunciation_627.py` | 267 | test_ac2_scripted_accept_and_clamp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_faction_denunciation_627.py` | 463 | test_ac5_zero_template_exposure_and_622 | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_fiscal_levy_effect.py` | 161 | test_liao_levy_rise_approved_lands_on_no_e | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_fiscal_levy_effect.py` | 1179 | test_lost_seeded_province_keeps_current_le | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_fiscal_levy_effect.py` | 1290 | _install_liao_month_stubs | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_fiscal_levy_effect.py` | 1291 | _install_liao_month_stubs | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_fiscal_levy_effect.py` | 1292 | _install_liao_month_stubs | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_fiscal_levy_effect.py` | 1293 | _install_liao_month_stubs | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_fiscal_levy_effect.py` | 1297 | _install_liao_month_stubs | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_fiscal_substrate_bridge.py` | 274 | _assert_hub_oracle_mutation_fails | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 810 | test_substrate_hub_cutover_runs_multi_tick | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 847 | test_settling_context_retry_does_not_recom | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1040 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1046 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1055 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1064 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1074 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1232 | test_fixed_flows_substrate_hub_central_pay | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1377 | test_fixed_flows_substrate_hub_books_split | ORACLE_HELPER,_assert_hub_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1382 | test_fixed_flows_substrate_hub_books_split | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1390 | test_fixed_flows_substrate_hub_books_split | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1398 | test_fixed_flows_substrate_hub_books_split | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_fiscal_substrate_bridge.py` | 1406 | test_fixed_flows_substrate_hub_books_split | ORACLE_HELPER,_assert_hub_oracle_mutation_fails | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_gazette_author_1862.py` | 53 | _session | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_gazette_author_1862.py` | 75 | test_author_waits_until_rescript_is_done | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 77 | test_author_waits_until_rescript_is_done | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 350 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_gazette_author_1862.py` | 355 | test_author_archives_own_title_and_same_ru | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 356 | test_author_archives_own_title_and_same_ru | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 379 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_gazette_author_1862.py` | 382 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_gazette_author_1862.py` | 404 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_gazette_author_1862.py` | 438 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_gazette_author_1862.py` | 439 | test_author_archives_own_title_and_same_ru | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_gazette_author_1862.py` | 484 | test_gazette_failure_retries_report_only | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 485 | test_gazette_failure_retries_report_only | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_gazette_author_1862.py` | 496 | test_gazette_failure_retries_report_only | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_gazette_author_1862.py` | 506 | test_gazette_failure_retries_report_only | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_grant_reconciliation_567.py` | 358 | test_web_state_payload_after_settle | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_highlight_judge_544.py` | 211 | test_chat_stream_done_before_highlights_an | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_highlight_judge_544.py` | 245 | test_chat_stream_slow_success_attaches_aft | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_highlight_judge_544.py` | 265 | test_chat_stream_slow_success_attaches_aft | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_highlight_judge_544.py` | 290 | test_chat_nonstream_folds_judge_within_tim | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_highlight_judge_544.py` | 341 | test_chat_nonstream_timeout_returns_reply_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_highlight_judge_544.py` | 348 | test_chat_nonstream_timeout_returns_reply_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_FIXTURE_ECHO | 断言等于本测试注入的罐头 fixture 回传/落库，非 LLM 自由生成盯文 |
| `tests/test_llm_channel_config.py` | 387 | test_create_chat_model_maps_reasoning_stre | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py` | 402 | test_create_chat_model_maps_reasoning_stre | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py` | 420 | test_minimax_reasoning_strength_overrides_ | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py` | 462 | test_verify_llm_available_respects_api_cha | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 474 | test_verify_llm_available_respects_api_cha | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_llm_channel_config.py` | 488 | test_verify_llm_available_smokes_cli_chann | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 512 | test_verify_llm_available_cli_channel_fail | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 539 | test_verify_llm_available_smokes_legacy_en | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 552 | test_verify_llm_available_legacy_env_only_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 587 | test_verify_llm_available_api_smoke_omits_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 610 | test_verify_llm_available_api_empty_conten | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 633 | test_verify_llm_available_api_empty_conten | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 656 | test_verify_llm_available_api_empty_conten | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 677 | test_verify_llm_available_api_error_status | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_llm_channel_config.py` | 882 | test_agent_factories_omit_max_tokens_on_pa | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_manual_directive_institution_normalize_1279.py` | 39 | _mock_draft_intent | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_manual_directive_institution_normalize_1279.py` | 44 | _assert_decree_reached_backend | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_manual_directive_institution_normalize_1279.py` | 133 | test_seeded_draft_accepts_ministry_subject | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_manual_directive_locality_1685.py` | 47 | test_manual_directive_region_assembly_writ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_material_directory_1830.py` | 251 | test_character_materials_exclude_legacy_ra | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_mechanical_tail_1845.py` | 32 | _archive_and_stub_world | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_mechanical_tail_1845.py` | 33 | _archive_and_stub_world | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 76 | test_advance_schedules_mechanical_tail_aft | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 118 | test_reopen_resumes_incomplete_mechanical_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 162 | test_exhausted_mechanical_tail_fails_and_b | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 203 | test_real_brew_failure_reaches_tail_failur | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_mechanical_tail_1845.py` | 220 | test_real_brew_failure_reaches_tail_failur | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_mechanical_tail_1845.py` | 257 | test_web_barrier_resumes_pending_tail_befo | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 311 | test_non_exhausted_tail_failure_stays_pend | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 345 | test_non_exhausted_tail_failure_stays_pend | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 366 | test_ending_summary_runs_in_mechanical_tai | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 378 | test_ending_summary_runs_in_mechanical_tai | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_mechanical_tail_1845.py` | 483 | test_chapter_memory_retired_from_three_rea | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_mechanical_tail_1845.py` | 492 | test_chapter_memory_retired_from_three_rea | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_mechanical_tail_1845.py` | 497 | test_chapter_memory_retired_from_three_rea | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_mechanical_tail_1845.py` | 499 | test_chapter_memory_retired_from_three_rea | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_mechanical_tail_1845.py` | 503 | test_chapter_memory_retired_from_three_rea | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_mechanical_tail_1845.py` | 550 | test_mechanical_tail_missing_llm_config_su | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_mechanical_tail_1845.py` | 556 | test_mechanical_tail_missing_llm_config_su | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_memorial_inbox_1726.py` | 86 | test_progress_and_denunciation_project_as_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_memorial_inbox_1726.py` | 95 | test_progress_and_denunciation_project_as_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_memorial_inbox_1726.py` | 197 | test_state_payload_memorials_and_mark_read | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_menu_continue_stream_1195.py` | 56 | test_menu_continue_streams_stage_labels_th | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_menu_continue_stream_1195.py` | 97 | test_menu_continue_streams_error_when_llm_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_menu_continue_stream_1195.py` | 156 | test_stale_continue_worker_does_not_publis | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_continue_stream_1195.py` | 220 | test_stale_continue_worker_does_not_publis | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 31 | _capture_real_drain_threads | BOUNDARY_STUB | FIX_THREAD_FACTORY | Thread 包装类改为 make_thread 工厂，仅 append 真实 Thread |
| `tests/test_menu_lifecycle_drain_396.py` | 60 | test_exit_to_menu_returns_before_delayed_c | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 98 | test_new_game_returns_before_delayed_close | WAIT_UNTIL | FIX_THREAD_FACTORY | api_menu_new_game + 真实 Thread.join 后断言 move/文件；工厂已去包装类 |
| `tests/test_menu_lifecycle_drain_396.py` | 175 | test_drain_archive_moves_wal_and_shm_with_ | WAIT_UNTIL | FIX_THREAD_FACTORY | 同上 WAL 回滚完成后再断言外部路径 |
| `tests/test_menu_lifecycle_drain_396.py` | 258 |  | PRIOR_REVIEW | FIX_THREAD_FACTORY | 同上 close 失败不 move |
| `tests/test_menu_lifecycle_drain_396.py` | 308 | test_shutdown_waits_for_drain_before_retur | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 484 | test_drain_waits_for_queued_chat_stream_no | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_menu_lifecycle_drain_396.py` | 515 | test_drain_waits_for_queued_chat_stream_no | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 543 | test_drain_rejects_late_pending_write_befo | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 550 | test_drain_rejects_late_pending_write_befo | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 591 | test_spawn_pending_write_thread_start_fail | BOUNDARY_STUB | KEEP_THREAD_CAPTURE | 捕获真实 threading.Thread 引用以便 join；不替 worker 行为 |
| `tests/test_menu_lifecycle_drain_396.py` | 595 | test_spawn_pending_write_thread_start_fail | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_menu_lifecycle_drain_396.py` | 631 | test_new_game_switches_db_path_when_web_ga | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_month_call_recovery_1846.py` | 133 | test_month_entry_world_push_follows_audien | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_call_recovery_1846.py` | 139 | test_month_entry_world_push_follows_audien | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_call_recovery_1846.py` | 187 | test_forecast_exhaustion_does_not_overwrit | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 229 | test_world_text_exhaustion_stops_month_kee | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 243 | test_world_text_exhaustion_stops_month_kee | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_call_recovery_1846.py` | 250 | test_world_text_exhaustion_stops_month_kee | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_call_recovery_1846.py` | 284 | test_world_translate_exhaustion_keeps_text | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 285 | test_world_translate_exhaustion_keeps_text | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 308 | test_world_translate_exhaustion_keeps_text | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 309 | test_world_translate_exhaustion_keeps_text | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 361 | test_escape_hatch_discards_world_segment_o | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 362 | test_escape_hatch_discards_world_segment_o | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 409 | test_settlement_recovery_projects_month_ca | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 422 | test_settlement_recovery_projects_month_ca | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 479 | test_code_exception_during_world_commit_ke | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 486 | test_code_exception_during_world_commit_ke | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 539 | test_world_commit_failure_after_alongside_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 540 | test_world_commit_failure_after_alongside_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 618 | test_edict_settle_code_exception_stops_at_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 619 | test_edict_settle_code_exception_stops_at_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 675 | test_error_pack_failure_keeps_original_fau | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_call_recovery_1846.py` | 676 | test_error_pack_failure_keeps_original_fau | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_call_recovery_1846.py` | 703 | test_error_pack_failure_keeps_original_fau | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_chain_1843.py` | 57 | _prepare_player_month | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 61 | _prepare_player_month | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 66 | _prepare_player_month | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 115 | test_unforecast_edict_is_caught_up_once_an | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 158 | test_questions_hold_rescript_and_gazette_i | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 161 | test_questions_hold_rescript_and_gazette_i | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 201 | test_questions_hold_rescript_and_gazette_i | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 229 | test_player_recovery_uses_resolve_context_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 233 | test_player_recovery_uses_resolve_context_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 260 | test_finish_rescript_phase2_stays_settling | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 271 | test_world_segment_persists_declaration_en | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 314 | test_player_entry_recovers_ending_after_in | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 315 | test_player_entry_recovers_ending_after_in | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 327 | test_player_entry_recovers_ending_after_in | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 508 | test_missing_world_model_stops_before_worl | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 509 | test_missing_world_model_stops_before_worl | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 510 | test_missing_world_model_stops_before_worl | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 536 | test_month_drift_settles_due_secret_and_re | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 537 | test_month_drift_settles_due_secret_and_re | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1843.py` | 549 | test_month_drift_settles_due_secret_and_re | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1843.py` | 600 | test_world_segment_reads_material_director | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1843.py` | 700 | test_month_chain_lands_specialized_facts_b | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 74 | test_world_question_opens_rescript_desk_an | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 77 | test_world_question_opens_rescript_desk_an | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 100 | test_world_segment_multiple_questions_shar | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 104 | test_world_segment_multiple_questions_shar | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 113 | test_world_segment_multiple_questions_shar | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_month_chain_1847.py` | 139 | test_prior_month_answered_rescript_does_no | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 140 | test_prior_month_answered_rescript_does_no | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 147 | test_prior_month_answered_rescript_does_no | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 160 | test_this_turn_rejection_opens_triad_on_sa | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 191 | test_answering_triad_applies_and_releases_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 192 | test_answering_triad_applies_and_releases_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 220 | test_answering_triad_applies_and_releases_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 232 | test_answering_world_question_resumes_suff | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 235 | test_answering_world_question_resumes_suff | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 252 | test_answering_world_question_resumes_suff | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 253 | test_answering_world_question_resumes_suff | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 278 | test_answering_world_question_resumes_suff | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 320 | test_decree_question_continuation_idempote | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 321 | test_decree_question_continuation_idempote | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 322 | test_decree_question_continuation_idempote | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 329 | test_decree_question_continuation_idempote | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 351 | test_decree_question_continuation_idempote | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 399 | test_decree_continuation_survives_llm_exha | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 400 | test_decree_continuation_survives_llm_exha | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 401 | test_decree_continuation_survives_llm_exha | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 408 | test_decree_continuation_survives_llm_exha | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 463 | test_decree_question_and_world_question_sh | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 467 | test_decree_question_and_world_question_sh | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 476 | test_decree_question_and_world_question_sh | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_month_chain_1847.py` | 512 | test_missing_model_keeps_decree_question_u | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 513 | test_missing_model_keeps_decree_question_u | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 537 | test_missing_model_keeps_decree_question_u | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 550 | test_missing_model_does_not_mark_world_con | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 553 | test_missing_model_does_not_mark_world_con | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 573 | test_missing_model_does_not_mark_world_con | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 606 | test_cross_month_pending_draft_opens_rescr | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 607 | test_cross_month_pending_draft_opens_rescr | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 620 | test_cross_month_pending_draft_opens_rescr | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_month_chain_1847.py` | 621 | test_cross_month_pending_draft_opens_rescr | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 678 | test_decree_continuation_keeps_forecast_an | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 680 | test_decree_continuation_keeps_forecast_an | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 681 | test_decree_continuation_keeps_forecast_an | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 700 | test_decree_continuation_keeps_forecast_an | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_month_chain_1847.py` | 701 | test_decree_continuation_keeps_forecast_an | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_chain_1847.py` | 758 | test_decree_forecast_keeps_every_question_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 763 | test_decree_forecast_keeps_every_question_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 767 | test_decree_forecast_keeps_every_question_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 817 | test_question_note_only_is_kept_and_other_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 818 | test_question_note_only_is_kept_and_other_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 819 | test_question_note_only_is_kept_and_other_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 954 | test_fatal_midzhi_rejection_hides_force_op | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 955 | test_fatal_midzhi_rejection_hides_force_op | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 991 | test_midzhi_promulgation_records_authority | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1024 | test_midzhi_verdict_and_metadata_roll_back | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1074 | test_decree_continuation_ending_ends_the_m | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1075 | test_decree_continuation_ending_ends_the_m | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1076 | test_decree_continuation_ending_ends_the_m | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1077 | test_decree_continuation_ending_ends_the_m | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1078 | test_decree_continuation_ending_ends_the_m | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1105 | _resolve_with_emperor_fate | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1106 | _resolve_with_emperor_fate | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1107 | _resolve_with_emperor_fate | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1108 | _resolve_with_emperor_fate | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1162 | test_drift_sees_effects_landed_after_answe | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1165 | test_drift_sees_effects_landed_after_answe | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1168 | test_drift_sees_effects_landed_after_answe | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1196 | test_step_4a_no_eligible_objects_skips_run | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1197 | test_step_4a_no_eligible_objects_skips_run | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1202 | test_step_4a_no_eligible_objects_skips_run | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1207 | test_step_4a_no_eligible_objects_skips_run | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 1273 | test_step_4a_rescript_continuation_feeds_s | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1276 | test_step_4a_rescript_continuation_feeds_s | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1279 | test_step_4a_rescript_continuation_feeds_s | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1280 | test_step_4a_rescript_continuation_feeds_s | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1295 | test_step_4a_rescript_continuation_feeds_s | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 1361 | test_step_4a_deferred_disclosure_sees_fres | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1362 | test_step_4a_deferred_disclosure_sees_fres | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1363 | test_step_4a_deferred_disclosure_sees_fres | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1368 | test_step_4a_deferred_disclosure_sees_fres | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_LLM_BOUNDARY | supply 边界 + SettlementAbort.stage + dossier_progress 空/非空 + call_count 重试 |
| `tests/test_month_chain_1847.py` | 1431 | test_step_4a_incomplete_0058_report_fails_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1432 | test_step_4a_incomplete_0058_report_fails_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1433 | test_step_4a_incomplete_0058_report_fails_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1449 | test_step_4a_incomplete_0058_report_fails_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_LLM_BOUNDARY | supply 边界 + 崩溃恢复幂等；产物落库与不再重跑 supply |
| `tests/test_month_chain_1847.py` | 1487 | test_step_4a_crash_recovery_resumes_withou | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1488 | test_step_4a_crash_recovery_resumes_withou | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1489 | test_step_4a_crash_recovery_resumes_withou | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1520 | test_step_4a_crash_recovery_resumes_withou | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 1563 |  | PRIOR_REVIEW | KEEP_LLM_BOUNDARY | supply 边界 + 缺 fidelity 内联记录的结构化链标志 |
| `tests/test_month_chain_1847.py` | 1625 | test_step_4a_missing_covert_fidelity_recor | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1626 | test_step_4a_missing_covert_fidelity_recor | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1627 | test_step_4a_missing_covert_fidelity_recor | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1672 | test_step_4a_missing_covert_fidelity_recor | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 1845 | test_step_4a_non_validation_failure_keeps_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | supply 边界 + 非校验失败保留产物的结构化状态 |
| `tests/test_month_chain_1847.py` | 1846 | test_step_4a_non_validation_failure_keeps_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1847 | test_step_4a_non_validation_failure_keeps_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1861 | test_step_4a_non_validation_failure_keeps_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 1916 | test_step_4a_settles_due_secret_order | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 1917 | test_step_4a_settles_due_secret_order | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1918 | test_step_4a_settles_due_secret_order | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 1923 | test_step_4a_settles_due_secret_order | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_chain_1847.py` | 2079 | test_build_secret_orders_supply_feed_uses_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_chain_1847.py` | 2162 | test_step_4a_rescript_path_feeds_landed_no | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_chain_1847.py` | 2165 | test_step_4a_rescript_path_feeds_landed_no | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 2168 | test_step_4a_rescript_path_feeds_landed_no | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 2169 | test_step_4a_rescript_path_feeds_landed_no | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_chain_1847.py` | 2180 | test_step_4a_rescript_path_feeds_landed_no | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_month_loop_tracer_1468.py` | 63 | _stub_outer_llm_seams | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_loop_tracer_1468.py` | 87 | _stub_outer_llm_seams | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_loop_tracer_1468.py` | 91 | _stub_outer_llm_seams | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_month_loop_tracer_1468.py` | 95 | _stub_outer_llm_seams | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_month_loop_tracer_1468.py` | 299 | _resolve_decisions_via_stream | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_loop_tracer_1468.py` | 300 | _resolve_decisions_via_stream | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_loop_tracer_1468.py` | 341 | _play_one_month | GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_month_translate_1840.py` | 483 | test_unparseable_month_segment_does_not_st | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_new_game_dependency_mismatch_1721.py` | 80 | test_new_game_stale_agno_returns_typed_dep | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_new_game_smoke.py` | 49 | fresh_game_dir | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_new_game_write_path_1749.py` | 108 | _wait_spawns | INITIAL_OR_ATTEMPT,WAIT_UNTIL | KEEP_COMPLETION_SYNC | len(spawns) 仅取 completion 句柄；随后 done.wait()+close_ok+外部文件证明完成/失败 |
| `tests/test_new_game_write_path_1749.py` | 241 | _assert_chat_persisted | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_new_game_write_path_1749.py` | 244 | _assert_chat_persisted | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_new_game_write_path_1749.py` | 265 | _write_and_verify_live | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_new_game_write_path_1749.py` | 365 | test_new_game_write_path_direct_and_via_ex | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_new_game_write_path_1749.py` | 547 | test_load_save_close_fail_restores_writabl | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_new_game_write_path_1749.py` | 577 | test_exit_close_fail_blocks_archive_on_rea | INITIAL_OR_ATTEMPT,WAIT_UNTIL | KEEP_COMPLETION_SYNC | len(spawns) 仅取 completion 句柄；随后 done.wait()+close_ok+外部文件证明完成/失败 |
| `tests/test_new_game_write_path_1749.py` | 589 | test_exit_close_fail_blocks_archive_on_rea | WAIT_UNTIL | KEEP_COMPLETION_SYNC | wait_until 同步 closed/文件/sealed/done 完成态 |
| `tests/test_new_game_write_path_1749.py` | 595 | test_exit_close_fail_blocks_archive_on_rea | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_no_edict_full_settlement_1274.py` | 55 | test_no_edict_advance_runs_full_settlement | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_office_inference.py` | 66 | test_api_channel_unknown_office_does_not_u | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 88 | test_runtime_cli_unknown_office_uses_confi | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 112 | test_api_channel_unknown_office_ignores_cl | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 126 | test_api_channel_unknown_office_ignores_cl | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 145 | test_use_llm_false_skips_backend_and_trust | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 168 | test_fresh_seed_makes_no_office_type_backe | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_office_inference.py` | 201 | test_fresh_gamesession_start_makes_no_back | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_on_scene_immediate_write_1839.py` | 118 | test_textual_fact_and_public_saying_land_a | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_on_scene_immediate_write_1839.py` | 223 | test_night_bound_sections_reject_missing_o | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_pay_order_override_653.py` | 628 | test_due_order_bad_shapes_raise | ORACLE_HELPER,_oracle_order | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_pay_order_override_653.py` | 1619 | _capture_override_decree | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pay_order_override_extraction_653.py` | 25 | test_single_pay_order_capture_grounds_rela | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pay_order_override_extraction_653.py` | 50 | test_relative_deadline_cannot_stage_llm_co | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pay_order_override_extraction_653.py` | 67 | test_single_pay_order_capture_rejects_miss | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pay_order_override_extraction_653.py` | 90 | test_multi_pay_order_capture_preserves_rev | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 57 | web_game | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 58 | web_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 75 | _657_install_real_phase2_llm_boundary | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 311 | test_missing_dossier_fields_stay_pending_t | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 312 | test_missing_dossier_fields_stay_pending_t | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 322 | test_missing_dossier_fields_stay_pending_t | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 323 | test_missing_dossier_fields_stay_pending_t | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 372 | test_due_commitment_shaped_submit_does_not | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 373 | test_due_commitment_shaped_submit_does_not | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 397 | test_lying_label_rebuilt_from_server_optio | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 398 | test_lying_label_rebuilt_from_server_optio | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 443 | test_mixed_legal_illegal_options_illegal_c | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 444 | test_mixed_legal_illegal_options_illegal_c | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 454 | test_mixed_legal_illegal_options_illegal_c | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 462 | test_mixed_legal_illegal_options_illegal_c | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 463 | test_mixed_legal_illegal_options_illegal_c | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 493 | test_ordinary_event_with_hallucinated_capa | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 494 | test_ordinary_event_with_hallucinated_capa | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 578 | test_657_p6_mapper_deliberate_preserve_fre | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 592 | test_657_p6_mapper_deliberate_preserve_fre | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 595 | test_657_p6_mapper_deliberate_preserve_fre | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 596 | test_657_p6_mapper_deliberate_preserve_fre | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 853 | test_657_return_revise_round_prior_and_cle | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 874 | test_657_return_revise_round_prior_and_cle | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 897 | test_657_return_revise_round_prior_and_cle | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1255 | test_657_s10_http_five_actions_and_1490_no | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 1329 | test_657_s10_http_five_actions_and_1490_no | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 1341 | test_657_s10_http_five_actions_and_1490_no | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 1345 | test_657_s10_http_five_actions_and_1490_no | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1346 | test_657_s10_http_five_actions_and_1490_no | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1421 | test_1621_http_follow_draft_uses_catalog_a | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 1456 | test_1621_http_follow_draft_uses_catalog_a | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1457 | test_1621_http_follow_draft_uses_catalog_a | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1480 | test_657_mixed_batch_follow_plus_decision_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1502 | test_657_mixed_batch_follow_plus_decision_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1603 | test_1589_empty_desk_rejects_nonempty_keyl | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1604 | test_1589_empty_desk_rejects_nonempty_keyl | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1610 | test_1589_empty_desk_rejects_nonempty_keyl | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1634 | test_657_s6_http_present_target_gets_uniqu | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1707 | test_657_web_http_hitl_lock_boundary_same_ | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1727 | test_657_illegal_summon_target_http_zero_w | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1728 | test_657_illegal_summon_target_http_zero_w | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1755 | test_1620_http_follow_draft_office_token_r | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1756 | test_1620_http_follow_draft_office_token_r | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1792 | test_1620_http_follow_draft_grant_uses_sto | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1793 | test_1620_http_follow_draft_grant_uses_sto | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1934 | test_657_summon_missing_tag_enter_blocks_p | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1959 | test_657_preferred_hitl_choice_urgent_foll | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 1961 | test_657_preferred_hitl_choice_urgent_foll | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py` | 1969 | test_657_preferred_hitl_choice_urgent_foll | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 2086 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2100 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2113 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2119 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2126 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2143 | test_657_revise_deliberate_strict_contract | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2416 | test_658_stalled_excluded_from_promulgatio | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2541 | test_658_endorsement_provenance_xor | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py` | 2585 | test_658_free_decree_capture_target_dossie | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 2688 | test_658_typed_target_and_backing_reject_b | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 2702 | test_658_typed_target_and_backing_reject_b | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py` | 2706 | test_658_typed_target_and_backing_reject_b | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_pihong_dossier_1490.py` | 2710 | test_658_typed_target_and_backing_reject_b | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 2730 | test_658_routing_rejected_draft_retries_ac | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 2819 | test_658_mixed_ordinary_triad_and_target_r | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_pihong_dossier_1490.py` | 2843 | _1778_generate | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 2901 | _1778_plant_and_follow | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 2902 | _1778_plant_and_follow | ASSERT_COMPARE,GEN_TEXT_ATTR,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 2917 | test_1778_drafted_roster_rides_to_pihong_a | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_pihong_dossier_1490.py` | 2984 | test_1778_missing_roster_heals_then_error_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_pihong_dossier_1490.py` | 3007 | test_1778_missing_roster_heals_then_error_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_player_army_projection_321.py` | 227 | _assert_chain_embeds_situation | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_player_army_projection_321.py` | 228 | _assert_chain_embeds_situation | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_player_army_projection_321.py` | 230 | _assert_chain_embeds_situation | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_population_transfers_649.py` | 389 | test_mutation_oracle_four_mutations_all_bi | ORACLE_HELPER,_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_transfers_649.py` | 395 | test_mutation_oracle_four_mutations_all_bi | ORACLE_HELPER,_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_transfers_649.py` | 400 | test_mutation_oracle_four_mutations_all_bi | ORACLE_HELPER,_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_transfers_649.py` | 406 | test_mutation_oracle_four_mutations_all_bi | ORACLE_HELPER,_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_transfers_649.py` | 415 | test_mutation_oracle_four_mutations_all_bi | ORACLE_HELPER,_conservation_oracle | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_population_unit_648.py` | 283 | test_new_save_restore_jianzhou_keeps_perso | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_promulgation_judge_561.py` | 45 | test_promulgation_context_is_deterministic | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_promulgation_judge_561.py` | 579 | test_appointment_text_is_pure_gatekeeper_t | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_promulgation_judge_561.py` | 581 | test_appointment_text_is_pure_gatekeeper_t | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_promulgation_judge_561.py` | 623 | test_ordinary_class_all_promulgated_covers | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_promulgation_judge_561.py` | 790 | test_default_promulgation_judge_uses_one_b | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_promulgation_judge_561.py` | 915 | test_review_exempt_actions_auto_promulgate | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_public_projection_consistency_1830.py` | 122 | test_scene_person_public_layer_matches_cha | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_public_projection_consistency_1830.py` | 207 | test_rebuild_adds_only_the_new_record_own_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_public_sayings_1829.py` | 57 | test_yuan_public_death_rumor_does_not_chan | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_public_sayings_1829.py` | 201 | test_public_saying_excluded_name_does_not_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_public_sayings_1829.py` | 202 | test_public_saying_excluded_name_does_not_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 42 | test_capture_drops_dachen_generic_no_409 | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 78 | test_capture_unknown_person_still_409 | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 166 | test_empty_text_capture_short_circuits_wit | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 208 | test_seeded_draft_long_extract_still_lands | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_d1_decree_normalize_1274.py` | 244 | test_normal_capture_path_unchanged | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | 256 | test_seal_claim_rejects_current_trail_legs | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_refugee_loop_652.py` | 269 | _advance_canned_month | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_refugee_loop_652.py` | 435 | test_recovery_shared_pool_advances_once_af | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_refugee_loop_652.py` | 476 | test_monthly_recovery_follows_each_month_a | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_refugee_loop_652.py` | 531 | test_in_transit_relief_stays_executing_bef | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_refugee_loop_652.py` | 532 | test_in_transit_relief_stays_executing_bef | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_refugee_loop_652.py` | 551 | test_in_transit_relief_stays_executing_bef | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_refugee_loop_652.py` | 552 | test_in_transit_relief_stays_executing_bef | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_relation_brew_636.py` | 46 | test_provider_fault_becomes_typed_brew_fai | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_relation_capture_633.py` | 449 | test_context_stored_byte_identical_through | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_read_640.py` | 217 | test_td7_local_marker_negative_assertion | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_seed_638.py` | 37 | fresh_session | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_relation_seed_638.py` | 163 | test_seeded_pair_flows_into_month_end_brew | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_seed_638.py` | 186 | test_earliest_legal_start_imports_only_ear | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_relation_seed_638.py` | 212 | test_missing_bundled_seed_fails_new_save_a | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_relation_seed_638.py` | 291 | test_seed_failure_rolls_back_new_save_and_ | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_relation_seed_638.py` | 323 | test_new_save_imports_sample_seed_ledger_q | GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_relation_seed_638.py` | 448 | test_existing_save_is_never_touched_by_see | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_rescript_choices_563.py` | 39 | test_manual_mode_uses_typed_extractor_judg | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_rescript_choices_563.py` | 50 | test_manual_edit_preserves_existing_mode_w | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_rescript_draft_656.py` | 296 | test_validate_and_persist_preserve_whitesp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 297 | test_validate_and_persist_preserve_whitesp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 305 | test_validate_and_persist_preserve_whitesp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 306 | test_validate_and_persist_preserve_whitesp | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 321 | test_generate_ungrounded_region_heals_then | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 329 | test_generate_ungrounded_region_heals_then | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 347 | test_generate_ungrounded_army_heals_then_d | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 356 | test_generate_ungrounded_army_heals_then_d | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 403 | test_generate_combined_target_and_roster_f | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 409 | test_generate_combined_target_and_roster_f | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 468 | test_generate_combined_target_roster_parti | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 474 | test_generate_combined_target_roster_parti | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 526 | test_generate_unknown_roster_character_hea | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 532 | test_generate_unknown_roster_character_hea | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 564 | test_generate_unknown_delegator_heals_then | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 576 | test_generate_unknown_delegator_heals_then | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 591 | test_generate_existing_offcourt_roster_cha | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 604 | test_generate_existing_offcourt_roster_cha | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 622 | test_generate_military_order_region_target | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 634 | test_generate_military_order_region_target | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 653 | test_generate_rejects_military_order_empty | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 662 | test_generate_rejects_military_order_empty | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_draft_656.py` | 811 | test_generate_rescript_draft_degrades_loud | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 827 | test_generate_rescript_draft_program_error | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 904 | test_persist_then_abort_draft_never_enters | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_rescript_draft_656.py` | 956 | test_r3_strict_parse_degrades_via_generate | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_draft_656.py` | 1298 | test_657_s1_list_rescript_desk_merges_cros | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_rescript_draft_656.py` | 1301 | test_657_s1_list_rescript_desk_merges_cros | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_rescript_draft_656.py` | 1302 | test_657_s1_list_rescript_desk_merges_cros | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_rescript_heal_isolation_1801.py` | 108 | test_1801_top_unformed_heals_then_no_draft | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 110 | test_1801_top_unformed_heals_then_no_draft | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_heal_isolation_1801.py` | 130 | test_1801_item_utf8_heals_then_drops_only_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 132 | test_1801_item_utf8_heals_then_drops_only_ | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 134 | test_1801_item_utf8_heals_then_drops_only_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_heal_isolation_1801.py` | 138 | test_1801_item_utf8_heals_then_drops_only_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 150 | test_1801_unknown_top_key_heals_then_ignor | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 152 | test_1801_unknown_top_key_heals_then_ignor | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 154 | test_1801_unknown_top_key_heals_then_ignor | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_heal_isolation_1801.py` | 187 | test_1801_unknown_top_key_heal_items_empty | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 189 | test_1801_unknown_top_key_heal_items_empty | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 191 | test_1801_unknown_top_key_heal_items_empty | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_heal_isolation_1801.py` | 209 | test_1801_unknown_top_key_heal_omit_key_su | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 211 | test_1801_unknown_top_key_heal_omit_key_su | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 226 | test_1801_eight_items_all_pass_no_heal_no_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_heal_isolation_1801.py` | 228 | test_1801_eight_items_all_pass_no_heal_no_ | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_heal_isolation_1801.py` | 232 | test_1801_eight_items_all_pass_no_heal_no_ | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 146 | _assert_call_history | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 201 | test_run_agent_text_prior_messages_sent_as | ASSERT_COMPARE,GEN_TEXT_NAME,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 315 | test_contract_failure_heals_not_batch_reje | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 317 | test_contract_failure_heals_not_batch_reje | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 318 | test_contract_failure_heals_not_batch_reje | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 337 | test_amount_numeric_string_accepted_via_gr | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 342 | test_amount_numeric_string_accepted_via_gr | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 362 | test_missing_target_kind_only_heals_not_co | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 364 | test_missing_target_kind_only_heals_not_co | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 365 | test_missing_target_kind_only_heals_not_co | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 386 | test_army_single_combo_heals_not_batch_red | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 388 | test_army_single_combo_heals_not_batch_red | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 417 | test_dual_missing_discriminator_heals_gran | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 419 | test_dual_missing_discriminator_heals_gran | ASSERT_COMPARE,GEN_TEXT_HINT,GEN_TEXT_NAME,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 464 | test_typed_illegal_also_heals | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 466 | test_typed_illegal_also_heals | ASSERT_COMPARE,GEN_TEXT_HINT,GEN_TEXT_NAME,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 545 | test_overflow_json_number_heals_not_batch | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 547 | test_overflow_json_number_heals_not_batch | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 590 | test_overflow_json_number_exhaust_drops_on | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 592 | test_overflow_json_number_exhaust_drops_on | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 666 | test_option_shape_failures_heal_not_batch | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 668 | test_option_shape_failures_heal_not_batch | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 669 | test_option_shape_failures_heal_not_batch | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 686 | test_provider_still_whole_batch_item_missi | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 701 | test_provider_still_whole_batch_item_missi | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 703 | test_provider_still_whole_batch_item_missi | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 705 | test_provider_still_whole_batch_item_missi | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 777 | test_heal_response_contract_failure_consum | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 779 | test_heal_response_contract_failure_consum | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_rescript_option_field_heal_1746.py` | 782 | test_heal_response_contract_failure_consum | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 783 | test_heal_response_contract_failure_consum | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_rescript_option_field_heal_1746.py` | 859 | test_first_draw_parse_failure_heals_then_d | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 901 | test_heal_bad_identity_refuses_merge_then_ | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_rescript_option_field_heal_1746.py` | 903 | test_heal_bad_identity_refuses_merge_then_ | GEN_TEXT_NAME | KEEP_RESCRIPT_STRUCTURE | 批红/疗伤结构化字段与 draft 状态 |
| `tests/test_run_agent_text_transport_1465.py` | 51 | test_run_agent_text_final_text_from_termin | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_run_agent_text_transport_1465.py` | 154 | test_run_agent_text_history_backed_drops_e | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_scene_llm_1836.py` | 66 | test_scene_chat_one_call_returns_multi_per | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_scene_llm_1836.py` | 75 | test_scene_chat_one_call_returns_multi_per | ASSERT_COMPARE,GEN_TEXT_ATTR | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_scene_llm_1836.py` | 94 | test_xuan_lands_enter_then_present_on_next | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_scene_llm_1836.py` | 150 | test_cli_selection_uses_scene_turn_as_admi | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_scene_llm_1836.py` | 165 | test_retire_via_scene_chat_closes_night_an | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_secret_order_isolation_883.py` | 148 | test_883_audience_chat_path_does_not_leave | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 170 | test_883_audience_chat_paraphrase_does_not | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 171 | test_883_audience_chat_paraphrase_does_not | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 172 | test_883_audience_chat_paraphrase_does_not | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 193 | test_883_audience_chat_paraphrase_does_not | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 292 | test_883_post_brief_public_audience_enters | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 368 | test_883_zero_overlap_semantic_rewrite_wit | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 446 | test_976_pure_public_minister_reply_releas | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 497 | test_976_secret_chat_turn_withholds_both_s | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 595 | test_883_shared_archive_bypass_positive_an | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_secret_order_isolation_883.py` | 922 | test_976_non_create_stage_commit_update_wi | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_isolation_883.py` | 1546 | test_976_rt05_save_restore_between_hold_an | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_monthly_progress_566.py` | 54 | _canned_monthly_settlement | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_secret_order_monthly_progress_566.py` | 73 | test_emperor_private_payload_preserves_mon | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_monthly_progress_566.py` | 127 | test_disclosure_promotes_monthly_report_to | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_payoff_1504.py` | 413 | test_settle_due_keeps_existing_progress_re | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_payoff_1504.py` | 1047 | test_supply_call_writes_identity_materials | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_secret_order_payoff_1504.py` | 1048 | test_supply_call_writes_identity_materials | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_secret_order_payoff_1504.py` | 2052 | test_invalid_declaration_stops_month_chain | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_secret_order_update.py` | 72 | test_update_preserves_long_text | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_secret_order_update.py` | 73 | test_update_preserves_long_text | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_SECRET_ORDER_STRUCTURE | 密令结构化隔离/身份字段 |
| `tests/test_staged_assignment_identity_1890.py` | 280 | test_revision_keeps_original_source_turn_a | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_staged_assignment_identity_1890.py` | 290 | test_revision_keeps_original_source_turn_a | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_staged_assignment_identity_1890.py` | 521 | test_undo_deletes_only_this_turns_committe | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_structured_decree_contract_1624.py` | 221 | test_month_end_entry_owner_and_matrix_reje | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_structured_decree_contract_1624.py` | 228 | test_month_end_entry_owner_and_matrix_reje | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_structured_decree_contract_1624.py` | 251 | test_month_end_entry_owner_and_matrix_reje | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_structured_decree_contract_1624.py` | 272 | test_month_end_entry_owner_and_matrix_reje | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_structured_decree_contract_1624.py` | 279 | test_month_end_entry_owner_and_matrix_reje | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_structured_decree_contract_1624.py` | 349 | test_manual_owner_example_seal_advances | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_structured_decree_contract_1624.py` | 429 | test_http_manual_directive_lands_beyond_fi | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_structured_decree_contract_1624.py` | 592 | test_combo_correction_preserves_first_draw | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_structured_decree_contract_1624.py` | 750 | test_batch_combo_correction_real_wrapper | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_style_temperament_641.py` | 341 | test_context_passes_raw_style_and_ledger_p | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_surcharge_causal_chain_650.py` | 266 | test_player_month_recovery_consumes_old_le | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_surcharge_causal_chain_650.py` | 269 | test_player_month_recovery_consumes_old_le | ASSERT_COMPARE,GEN_TEXT_HINT,STR_LITERAL | KEEP_STRUCTURED_FIELD | 枚举/状态机/字段名等结构化结果 |
| `tests/test_surcharge_causal_chain_650.py` | 382 | test_exact_levy_fact_stays_out_of_public_r | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_surcharge_causal_chain_650.py` | 383 | test_exact_levy_fact_stays_out_of_public_r | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_surcharge_causal_chain_650.py` | 392 | test_exact_levy_fact_stays_out_of_public_r | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_surcharge_causal_chain_650.py` | 393 | test_exact_levy_fact_stays_out_of_public_r | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_FIXTURE_OR_SEED | 种子/夹具字面量回显或确定性种子字段 |
| `tests/test_transit_countdown_668.py` | 49 | test_henan_normal_speed_arrives_next_month | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 70 | test_speed_factors_match_f2_oracle_on_diff | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 72 | test_speed_factors_match_f2_oracle_on_diff | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 98 | test_pre_settle_tick_before_event_terminal | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 128 | test_pre_settle_tick_before_seed_auto_trig | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 157 | test_ousted_in_transit_stops_countdown_and | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 162 | test_ousted_in_transit_stops_countdown_and | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_transit_countdown_668.py` | 196 | test_mid_countdown_save_reopen_continues_i | ORACLE_HELPER,_oracle_n | KEEP_FISCAL_ORACLE | 财政 hub 独立 oracle 变异咬合（非自由文本哨兵） |
| `tests/test_verify_llm_clocks_884.py` | 136 | test_api_verify_installs_sdk_attempt_clock | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_web_audience_night_498.py` | 92 | _fake_settlement_llm | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_web_audience_night_498.py` | 95 | _fake_settlement_llm | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_web_audience_night_498.py` | 99 | _fake_settlement_llm | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_web_audience_night_498.py` | 135 | web_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_web_audience_night_498.py` | 670 | test_night_approved_directive_closes_into_ | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_STRUCTURED_OR_HARNESS | 结构化字段或 harness 契约（非自由文本哨兵） |
| `tests/test_web_court_visibility.py` | 216 | _stub_game | BOUNDARY_STUB | KEEP_IO_BOUNDARY | IO/环境边界替身；外部结果另有结构化断言 |
| `tests/test_web_llm_runtime_config.py` | 903 | _count_llm_calls | BOUNDARY_STUB | KEEP_LLM_BOUNDARY | LLM/supply/drain 边界替身；行为断言在结构化外部结果 |
| `tests/test_web_llm_runtime_config.py` | 988 | test_continue_load_save_reach_hud_zero_llm | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 999 | test_continue_load_save_reach_hud_zero_llm | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1007 | test_continue_load_save_reach_hud_zero_llm | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1013 | test_continue_load_save_reach_hud_zero_llm | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1016 | test_continue_load_save_reach_hud_zero_llm | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1063 | test_hot_replace_http_success_reopens_stat | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1064 | test_hot_replace_http_success_reopens_stat | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1114 | test_hot_replace_http_failure_keeps_old_st | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `tests/test_web_llm_runtime_config.py` | 1115 | test_hot_replace_http_failure_keeps_old_st | ASSERT_COMPARE,GEN_TEXT_NAME | KEEP_LLM_CONFIG_SURFACE | 模型配置/通道表面结构化字段 |
| `web/src/appDurableWiring.test.tsx` | 127 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 142 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 180 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 181 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 182 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 254 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 255 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 256 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 258 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 347 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 348 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 392 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 407 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 581 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/appDurableWiring.test.tsx` | 584 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/appDurableWiring.test.tsx` | 606 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 611 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 612 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 620 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 645 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 708 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 719 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1047 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1050 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1051 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1112 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1123 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1124 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1126 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1317 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1318 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1354 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1355 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1424 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1425 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1466 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1552 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1564 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1618 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/appDurableWiring.test.tsx` | 1736 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1737 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1738 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1908 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1920 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 1943 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2038 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2058 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2168 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2428 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2429 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2479 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2503 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2573 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2596 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2655 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2657 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2658 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2706 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2707 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2756 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/appDurableWiring.test.tsx` | 2783 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2784 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2845 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/appDurableWiring.test.tsx` | 2854 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2875 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2979 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2980 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 2981 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3002 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3003 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3004 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3069 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3070 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3071 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3297 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3369 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3370 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3371 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3386 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3387 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3389 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3432 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3434 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3493 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3504 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3506 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3542 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3617 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/appDurableWiring.test.tsx` | 3618 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/buildResources.test.ts` | 46 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/chatFailures.test.ts` | 21 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/chatFailures.test.ts` | 121 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/chatFailures.test.ts` | 131 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 45 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 63 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 64 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 65 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/decisionModal.test.tsx` | 109 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/decisionModal.test.tsx` | 150 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 151 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 160 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 161 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 162 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 167 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 172 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 208 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 250 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 263 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 264 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 281 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 325 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 326 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 332 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 337 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 440 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 442 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 450 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 456 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 492 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 544 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 549 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 550 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/decisionModal.test.tsx` | 552 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 163 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 164 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 166 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 167 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 168 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 193 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 194 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 222 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 223 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 224 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/drawers.test.tsx` | 232 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 257 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 258 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 340 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 450 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 817 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 823 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/drawers.test.tsx` | 832 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/drawers.test.tsx` | 841 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 845 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/drawers.test.tsx` | 890 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 892 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 907 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 908 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 909 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 926 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 928 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/drawers.test.tsx` | 960 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 111 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 150 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/gameMenu.test.tsx` | 177 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 208 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 215 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 245 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 254 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 291 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 299 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 343 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 344 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 350 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 391 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 392 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 400 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 430 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 500 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 580 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 633 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 679 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 716 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 724 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 730 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 737 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 744 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 786 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 787 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 793 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 815 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 827 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 828 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 836 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/gameMenu.test.tsx` | 868 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/gameMenu.test.tsx` | 869 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/map.test.tsx` | 78 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/map.test.tsx` | 103 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/map.test.tsx` | 104 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/map.test.tsx` | 144 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/map.test.tsx` | 145 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/map.test.tsx` | 146 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/map.test.tsx` | 181 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 96 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 182 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 231 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/menuPage.test.tsx` | 237 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/menuPage.test.tsx` | 271 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 299 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 415 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 478 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 485 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 491 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 558 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 565 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 639 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 640 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 646 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 721 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 722 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 730 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 797 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 979 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 1006 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 1018 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/menuPage.test.tsx` | 1019 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 1050 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 1070 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/menuPage.test.tsx` | 1117 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 56 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 295 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 296 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 320 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 334 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 335 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 338 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 343 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 359 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 370 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 371 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 378 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 455 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 466 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 467 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 474 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 478 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 502 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 503 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 512 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/modals.test.tsx` | 513 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/modals.test.tsx` | 520 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/modals.test.tsx` | 542 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 543 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 574 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 575 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 601 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 602 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 603 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 604 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 608 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 609 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 644 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 646 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 649 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 661 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 664 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 687 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 688 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 691 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 692 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 693 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 694 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 697 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 717 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 720 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 721 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 722 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 725 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 742 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 743 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 754 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 756 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 836 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 837 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 838 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 881 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 882 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 883 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 899 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 904 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 906 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 907 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 934 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 952 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 974 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 984 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 996 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 997 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 998 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1004 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1016 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1017 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1018 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1025 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1026 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1027 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1045 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1059 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1065 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1067 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1068 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1075 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1085 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1095 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1098 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1100 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1101 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1112 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1138 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1146 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1164 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1184 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1186 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1201 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1207 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1213 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1220 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1285 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1286 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1287 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1298 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1299 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1300 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1321 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1339 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1341 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1349 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1368 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1383 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1390 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1416 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1418 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1419 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1420 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1421 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1426 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1453 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1471 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1488 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1489 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1490 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1492 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1500 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1504 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1505 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/modals.test.tsx` | 1509 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1519 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1527 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1559 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1564 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1604 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1631 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1647 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/components/modals.test.tsx` | 1674 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/modals.test.tsx` | 1675 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1740 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1741 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1764 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1765 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1772 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1774 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1775 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1786 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/modals.test.tsx` | 1839 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 108 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 109 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 110 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 113 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 114 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 126 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 129 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 130 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 156 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 161 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 218 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 250 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 261 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 263 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 335 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 355 |  | STR_ASSERT | KEEP_UI_CHROME | P7 射程外：按钮/菜单/忙等固定界面话语 |
| `web/src/components/settlementFaces.test.tsx` | 402 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 403 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 411 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementFaces.test.tsx` | 412 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementGazettePanel.test.tsx` | 39 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/settlementGazettePanel.test.tsx` | 40 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/situation.test.tsx` | 78 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/situation.test.tsx` | 145 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/situation.test.tsx` | 211 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/situation.test.tsx` | 212 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/components/situation.test.tsx` | 213 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/components/situation.test.tsx` | 214 |  | STR_ASSERT | KEEP_P4_NEGATIVE | P4：皇帝不见裸数值/定性条；负向禁止呈现属呈现层契约 |
| `web/src/decisionRouting.test.tsx` | 178 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 182 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 183 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 187 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 188 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 189 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 190 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 194 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 198 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 199 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/decisionRouting.test.tsx` | 200 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/escClose.test.tsx` | 118 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/escClose.test.tsx` | 147 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreading.test.ts` | 15 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 142 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 149 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 178 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 179 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 180 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 208 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 209 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 228 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 234 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 298 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 303 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 328 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/mindreadingDelivery.test.tsx` | 332 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/settleStream.test.ts` | 37 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/settleStream.test.ts` | 45 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 84 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 105 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 166 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 167 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 251 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 263 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 324 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 325 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 327 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 341 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 342 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 343 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 390 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 391 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 392 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 438 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 439 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 440 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 441 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 457 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 459 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 471 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 472 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 479 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/staleGuard.test.tsx` | 485 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useDurableProjection.test.tsx` | 71 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 196 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 199 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 203 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 208 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 214 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 215 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 222 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 223 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 224 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 256 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 258 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 265 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 286 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 288 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 305 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 343 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 347 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 348 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 378 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 407 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 408 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 439 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 442 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 479 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 480 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 487 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 489 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 490 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 491 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 492 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 493 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 554 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 556 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 581 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 582 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 589 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 592 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 593 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 594 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 595 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 596 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 597 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 598 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 599 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 634 |  | MOCK_CALL | KEEP_WEB_FETCH_HARNESS | fetch/spy 调用次数与 URL 契约；非叙事生成文本盯文 |
| `web/src/useSettlementFlow.test.tsx` | 635 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
| `web/src/useSettlementFlow.test.tsx` | 636 |  | STR_ASSERT | KEEP_DOM_FIXTURE_OR_STRUCTURE | DOM 呈现测试注入 fixture 或结构化属性；非生产 LLM 叙事盯文 |
