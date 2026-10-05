# S1 成员真实处置表（187 + 独占依赖）

- base: `10e64fbef`
- audit head: `6b91e05b90f2624de6c8f006d878def241437921`
- ZERO 审计: 187
- DELETE=4 KEEP=184（含独占依赖 credit_event_to_edge）

**禁止把 disposition_hint 冒充最终处置。** 本表每行均为核实后的 disposition。

| name | disposition | rationale | base_prod | tests_at_audit |
|---|---|---|---|---|
| `credit_event_to_edge` | **DELETE** | 独占依赖：仅被 credit_events_as_edges 调用；随根清退（删前同文件 Load 故不在 187） | via credit_events_as_edges → db.read_credit_events_as_edges | 0 |
| `credit_events_as_edges` | **DELETE** | 底座 ming_sim/db.py:read_credit_events_as_edges 生产包装已删（import+方法）；现仅 tests/test_relation_store_632.py 专属测；删根 + credit_event_to_edge 独占依赖 + test_credit_contract_fixture_* | ming_sim/db.py:64,ming_sim/db.py:22624 | 2 |
| `delete_chat_messages` | **DELETE** | 底座 ming_sim/cli/terminal.py 调用已删；现仅 test_character_knowledge_489 直调 + test_cli_play_turn 对已不存在路径的 monkeypatch；删方法 + 专属测 + 清 monkeypatch | ming_sim/cli/terminal.py:486 | 2 |
| `get_night_protagonist` | **DELETE** | 底座 ming_sim/session.py 留侍分支消费者已删；现仅 test_audience_translation_1838 观测引用；删生产包装；AC3 真入口测改读 audience_nights.protagonist_name 账本列（set/reproject 仍写） | ming_sim/session.py:1191,ming_sim/session.py:1197 | 10 |
| `ACCEPTANCE_SCENARIOS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `ALLOWED_PORTRAIT_TYPES` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `ApplyContext` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `CLOSE_STEPS` | **KEEP** | KEEP_LIVE — 当前仍有生产引用 ['ming_sim/db.py:1488'] | ming_sim/db.py:1489 | 0 |
| `ChatResult` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `CourtContext` | **KEEP** | KEEP_LIVE — 当前仍有生产引用 ['ming_sim/session.py:61'] | ming_sim/session.py:62 | 1 |
| `DENUNCIATION_ALLOWED_COLS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `DENUNCIATION_TABLE` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `DGOLD` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `DUE_REVIEW_ENTRY_KIND_WHITELIST` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `EXPOSURE_ALLOWED_COLS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `EXPOSURE_TABLE` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `FACT_METRICS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `FORBIDDEN_DULLING_COL_FRAGMENTS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `MINISTER_DISMISS_COMMANDS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `MINISTRY_OFFICE_TYPES` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `MONTH_OPEN_KEYS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 4 |
| `MaterialsRoot` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `PERSON_LEGAL_REASON_CODES` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `PRESENCE_ALLOWED_COLS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `PRESENCE_TABLE` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `STRUCT` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `SUPERVISION_SURFACE_KEYS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_` | **KEEP** | KEEP_LIVE — 当前仍有生产引用 ['docs/raw/06_harness_scripts/bench.py:32', 'docs/raw/06_harness_scripts/bench2.py:39', 'ming_sim/action_materialize.py:453'] | docs/raw/06_harness_scripts/bench.py:32,docs/raw/06_harness_scripts/bench2.py:39,ming_sim/action_materialize.py:453,ming_sim/action_materialize.py:1303 | 653 |
| `_HUANG_TIAN_RENT_PER_WAN_MU` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_STATUS_DISCARDED` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_STATUS_SETTLED` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_STATUS_STAGED` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_TERMINAL_ACTIONS` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_collect_compliant_promulgation_items` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_dossier_ids_from_simulator_payload` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_fiscal_container_value` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_haircut_bp` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_merge_compliant_promulgation_items` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_open_affair_ids_from_payload` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_promulgable_proposed_dossiers` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_province_collection_rate` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_province_transport_ratio` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `_require_active_minister` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `accrue_blood_debt` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 39 |
| `accrue_detection_wariness` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `admin_page` | **KEEP** | KEEP_FASTAPI_OR_FRAMEWORK — web 框架/页面入口 | — | 0 |
| `ainvoke` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `ainvoke_stream` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `api_add_favorite` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_admin_delete` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_admin_table` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_admin_tables` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_admin_upsert` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_advance_without_edict` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 7 |
| `api_audience_chat_history` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_audience_chat_stream` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_audience_scroll` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_create_save` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_delete_directive` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_delete_save` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_get_court_layout` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 2 |
| `api_get_llm_config` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 6 |
| `api_get_portrait` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_history_turn` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_history_turns` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_issue_decree_stream` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 4 |
| `api_list_saves` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_load_save` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 2 |
| `api_memorials_read` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_menu_continue` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_menu_delete_save` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_menu_exit` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 2 |
| `api_menu_load_save` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_menu_new_game` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 6 |
| `api_menu_save_llm` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 8 |
| `api_menu_shutdown` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 2 |
| `api_menu_status` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 12 |
| `api_remove_favorite` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_resolve_decisions_stream` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 3 |
| `api_retry_audience_reply` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_retry_mechanical_tail` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_retry_pending_translation` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_secret_orders` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_set_court_layout` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 3 |
| `api_set_llm_config` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 9 |
| `api_state` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `api_undo_audience_chat` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 1 |
| `api_upload_portrait` | **KEEP** | KEEP_FASTAPI — FastAPI 框架入口（装饰器注册；AST Load=0 假死） | — | 0 |
| `army_detail` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `audit_night_direct_writes` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `axis_collision_stances` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `build_fiscal_fact_brief` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 31 |
| `build_period_report` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `build_secret_covert_effect_briefs` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `building_detail` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `clear_directive_needs_clarification` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `clear_pending_decisions` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 9 |
| `clear_resolve_context` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `cluster_effect` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `contract_axes_direction` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `count_active_initiatives` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `create_rescript_draft_agent` | **KEEP** | #1847 配套 agent 工厂保留 | — | 2 |
| `dependency_mismatch_handler` | **KEEP** | KEEP_FASTAPI_OR_FRAMEWORK — web 框架/页面入口 | — | 0 |
| `dict_of_string_lists` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `dict_of_strings` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `disaster_severity_band` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `discard_pending_directives` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `discover_character_write_sql_locations` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `drop_pending_actions_for_minister` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `event_context` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `execution_side_read_fields` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `experiences` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `faction_report` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `first_character_name` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `flag_directive_needs_clarification` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `format_fiscal_fact_brief_tsv` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `format_power_changes` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `generate_rescript_draft` | **KEEP** | #1847 待接线能力合法保留 | — | 46 |
| `get_faction_stance_summary` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 10 |
| `get_message_highlights` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 4 |
| `has_player_visible_rejection` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `historical_anchor_for_month` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `hline` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `holder_kind` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `is_sealed` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `isatty` | **KEEP** | KEEP_LIVE — 当前仍有生产引用 ['launcher.py:23', 'launcher.py:24'] | launcher.py:23,launcher.py:24 | 0 |
| `list_arrived_unsettled_summons` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 8 |
| `list_dossier_actual_rail` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `list_dossier_link_rejections` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 4 |
| `list_dossiers_for_directive` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 9 |
| `list_endorsed_dossier_candidates` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `list_execution_liability_parties` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `list_ministers` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 6 |
| `list_night_promulgated_directives` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `list_night_timeline` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `list_office_effects_for_dossier` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `list_office_vacancies` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `list_open_grant_reconciliations` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `list_promulgated_directives` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `mark_chat_turn_failed` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `matrix_snapshot` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `mean_aligned_stance` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `minister_speaker_role` | **KEEP** | 底座原本无生产调用，不强求删 | — | 0 |
| `night_dossiers_ready` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `parse_covert_exec_selections` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `parse_json_dict` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `person_write_locations_by_disposition` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `persons_entered_tonight` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `persons_present_tonight` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 10 |
| `point_dossier` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `point_issue` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `pointing_at` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `prepare_character_materials` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 41 |
| `rebuild_centrifuge_cache` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `record_economy_moves` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `record_monthly_supervision_facts` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `reject_directive` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `release_previous_material_tree` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `require_bool` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `require_int_range` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `require_non_empty_text` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `revoke_pay_order_decree` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 2 |
| `run_agent_stream_text` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `run_audience_turn_translation` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `run_exclusive` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 7 |
| `run_month_end_relation_brew` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 45 |
| `save_pending_promulgation_verdicts` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 5 |
| `save_rescript_drafts` | **KEEP** | 共享 DB API；测试 fixture / 月链他路 | — | 24 |
| `season_option_contract_prompt` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `select_triage_actor` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 8 |
| `settle_province_tick` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 30 |
| `stage_authorization_candidate` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 6 |
| `stage_grant_allocation_candidate` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 3 |
| `stage_month_segment` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 10 |
| `stage_referral_candidate` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `stage_revoke_authority_candidate` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `state_context` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `status_delta` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `treasury_ledger` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `turn_army_summary` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `turn_economy_summary` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `turn_power_summary` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 0 |
| `turn_region_summary` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `upsert_pending_directive` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 6 |
| `vacate` | **KEEP** | KEEP_LIVE — 当前仍有生产引用 ['ming_sim/session_write_queue.py:163', 'ming_sim/session_write_queue.py:396'] | ming_sim/session_write_queue.py:163,ming_sim/session_write_queue.py:396 | 2 |
| `value_axes` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 1 |
| `write_decree` | **KEEP** | KEEP_NEVER_WIRED_OR_SCAN_FALSEDEAD — 底座与当前均无外生产调用方（或仅注释提及）；非本分支删消费者所致，不强求删 | — | 6 |
