# #1902 F1–F4 本轮全仓分类表
生成自临时脚本 `/tmp/ming1902-f1f4-rescand/scan_*.py`；完整 JSON：`evidence/issue-1902/f1-f4-classification-table.json`。
## 摘要
- F1 except_total=840 wash_candidates=373 dispositions={'retain': 373}
- F2 config projection hits=590；parallel_effective_after_filter=9
- F3 test_paths=267 dispositions={'retain': 261, 'fixed_this': 4, 'fixed_prev': 2}
- F4 pure-forward AST candidates=49 dispositions={'retain': 49}

## F3 本轮处置成员（非全表）
- `tests/test_cli_backend.py` — **fixed_this** — 删死夹具 _patch_backend；secret/enrich 改钉 _run_json_extractor_for_config/_run_backend_for_config 真缝
- `tests/test_cli_entry_1902.py` — **fixed_this** — 删落库案内重复正向 validate_all；保留 ordinary 拒收独立参数契约与落库断言
- `tests/test_faction_denunciation_627.py` — **fixed_prev** — 已删重复 helper 案（0e7d35d）
- `tests/test_llm_channel_config.py` — **fixed_this** — 删 test_cli_reasoning_strength_runners_authoritative_set 内部 frozenset 锁；保留 matrix 闸类谓词案
- `tests/test_on_scene_immediate_write_1839.py` — **fixed_prev** — 已改精确 reason + DB status（0e7d35d）
- `tests/test_web_llm_runtime_config.py` — **fixed_this** — 删三端 set==CLI_REASONING_STRENGTH_RUNNERS 内部集合锁；保留 grok∈名单与 reasoning_supported 行为断言

## F4 本轮处置成员

## F3 全路径分类（逐案）
| path | flags | disposition | reason |
|---|---|---|---|
| `tests/README.md` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/army_pay_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/audience_chat_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/cli_process_doubles.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/conftest.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/directive_entry_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/dossier_test_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/fiscal_test_utils.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/fixtures/agno-2.7.3-py3-none-any.whl` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/game_fixture_retained_inventory.tsv` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/issue_stream_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/legacy_staging_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/month_chain_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/offline_audience_reply.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/section_rejection_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/sse_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_adr0015_per_item_rejection.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_advance_paths_atomic.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_advance_without_edict_token_1351.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_advances_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_affairs_1831.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_applier_contract.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_appointment_tenure_607.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_army_card_status_1501.py` | assert_substr_in,weak_or_source | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_army_display_173.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_army_firearms.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_army_maintenance_retire_173.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_army_pay_source_prompt_contract.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_army_salary_44.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_background.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_continuous_507.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_audience_draft_grant_once_1777.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_extraction_501.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_night_498.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_audience_presence_500.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_audience_restore_505.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_audience_scroll_539.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_audience_translate_1837.py` | assert_substr_in,named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_audience_translate_1837_reopen.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_translation_1838.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_translation_once_1898.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_audience_travel_gating_670.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_audience_undo_506.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_authority_ledger_611.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_bandit_power_model_190.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_breach_plea_623.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_candidate_supply_1893.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_centrifuge_ledger_690.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_character_knowledge_489.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_chat_stream_failpaths_393.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_cli_backend.py` | assert_substr_in,setattr_run_backend | fixed_this | 删死夹具 _patch_backend；secret/enrich 改钉 _run_json_extractor_for_config/_run_backend_for_config 真缝 |
| `tests/test_cli_entry_1902.py` | helper_plus_land_db | fixed_this | 删落库案内重复正向 validate_all；保留 ordinary 拒收独立参数契约与落库断言 |
| `tests/test_cli_model_choices.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_cli_play_turn.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_cli_runner_error_typed_1299.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_cli_transport_1465.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_close_issues_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_commitment_backlash_626.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_commitment_display_348.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_court_break_player_lock_1727.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_court_layout_1290.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_covert_levy_651.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_credit_events_628.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_db_broad_except_surface.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_decision_event_binding_389.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_declaration_dispatch_1835.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_decree_commitment_creation_136.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_decree_commitment_schema_136.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_decree_commitment_settlement_229.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_decree_dossiers_571.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_decree_forecast_1861.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_deepseek_thinking_disable_1797.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_deformation_dual_rail_622.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_distance_matrix.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_dossier_endorsements_612.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_dossier_links_559.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_dossier_reported_progress_619.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_draft_admission_resubmit_1769.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_due_review_621.py` | weak_or_source | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_economy_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_effect_origin_558.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_empire_modifier_income_only_341.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_enrich_list_guards.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_enter_settlement_period_1235.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_env_isolation.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_error_pack.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_event_chain_cascade.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_event_trigger_gate.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_execution_joint_liability_565.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_execution_pressure_654.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_execution_tenure_613.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_executor_routing_721.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_faction_brew_637.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_faction_class_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_faction_denunciation_627.py` | assert_substr_in | fixed_prev | 已删重复 helper 案（0e7d35d） |
| `tests/test_faction_leverage_9.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_family_tail_615.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_family_tail_642.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_family_tail_restore_570.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_featured_dossiers_494.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_fiscal_beyond_intent_1260.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_fiscal_levy_effect.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_fiscal_substrate_bridge.py` | assert_substr_in,named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_fiscal_tick.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_gazette_author_1862.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_grant_reconciliation_567.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_highlight_judge_544.py` | assert_substr_in,weak_or_source | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_history_decree_text_1843_reopen.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_identity_seed_488.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_impeachment_surge_655.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_initiative_resolve_pairing.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_intrigue_concealment_1896.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_issue_decree_token_1277.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_issue_entities.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_junxin_alias_loyalty_313.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_junxin_monthly_tick_314.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_llm_channel_config.py` | setattr_run_backend | fixed_this | 删 test_cli_reasoning_strength_runners_authoritative_set 内部 frozenset 锁；保留 matrix 闸类谓词案 |
| `tests/test_llm_key_helpers.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_loyalty_soft_adjust_clamp_320.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_manual_directive_institution_normalize_1279.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_manual_directive_locality_1685.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_material_directory_1830.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_mechanical_tail_1845.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_memorial_inbox_1726.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_menu_continue_stream_1195.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_menu_lifecycle_drain_396.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_mindreading_491.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_minister_chat_timeout.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_month_call_recovery_1846.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_month_chain_1843.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_month_chain_1847.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_month_loop_tracer_1468.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_month_open_snapshot_1234.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_month_translate_1840.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_mutiny_actual_residence_659.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_mutiny_latch_315.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_mutiny_noop_whitelist_319.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_mutiny_progression_316.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_mutiny_redemption_317.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_mutiny_third_strike_318.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_named_characters_seed_484.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_new_game_dependency_mismatch_1721.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_new_game_smoke.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_new_game_write_path_1749.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_new_issues_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_no_edict_full_settlement_1274.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_office_inference.py` | assert_substr_in,setattr_run_backend | retain | 负向探测 API 通道不得误调 CLI；真缝正确 |
| `tests/test_office_rank_562.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_on_scene_immediate_write_1839.py` | assert_substr_in | fixed_prev | 已改精确 reason + DB status（0e7d35d） |
| `tests/test_opening_gazette_delete_1356.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_override_breach_costs_564.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_p4_guard_new_surfaces_547.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_pay_order_override_653.py` | assert_substr_in,named_helper_or_pure,setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_pay_order_override_extraction_653.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_person_archive_contract_index.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_person_archive_schema.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_person_delta_adapter.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_person_transit_write_667.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_pihong_dossier_1490.py` | assert_substr_in,helper_plus_land_db,named_helper_or_pure,setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_player_army_projection_321.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_player_payload_1022.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_population_transfers_649.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_population_transfers_662.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_population_unit_648.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_power_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_pre_settle_transaction.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_promulgation_judge_561.py` | assert_substr_in,named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_promulgation_seam_560.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_public_character_place_1683.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_public_projection_consistency_1830.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_public_sayings_1829.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_1281_issue_audience_case_facts.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_a3_seed_data.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_qa_b3_409_ux.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_c2_phase_settlement_mask_1374.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_qa_c2_settlement_display_lifecycle_1343.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_c3_secret_order_path_1357_1376.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_d1_decree_normalize_1274.py` | assert_substr_in,setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_qa_e1_numeric_presentation.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_h1_seed_data.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_qa_s2_copy_prompts_1356_1402.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_qa_t1_extraction_dual_source_1353.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_u2_liaodong_buildings.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_qa_u3_map_nodes_1401.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_recommendation_batch_snapshot_1583.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_recommendation_edges_635.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_recommendations.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_refugee_loop_652.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_region_cannon_delta.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_region_citydefense.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_reign_period_label.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_rejection_wiring.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_relation_brew_636.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_relation_capture_633.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_relation_read_640.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_relation_seed_638.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_relation_store_632.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_release_bundle_assets.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_rescript_choices_563.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_rescript_draft_656.py` | assert_substr_in,named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_rescript_heal_isolation_1801.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_rescript_option_field_heal_1746.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_run_agent_text_transport_1465.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_runtime_llm_config.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_scene_llm_1836.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_secret_dossier_participants_1252.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_secret_order_isolation_883.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_secret_order_monthly_progress_566.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_secret_order_payoff_1504.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_secret_order_section_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_secret_order_update.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_section4_rejections.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_section_fiscal_rejections.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_session_write_queue_1353.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_settle_core.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_settlement_write_guard_393.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_shared_resource_order_1844.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_six_sciences_seed_608.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_staged_assignment_identity_1890.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_start_sh_deps_1721.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_state_reload.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_structured_decree_contract_1624.py` | setattr_run_backend | retain | setattr 命中无配置回落真缝 _run_backend，或并有 for_config 注入；非判词失效 mock 缝 |
| `tests/test_style_temperament_641.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_supervision_625.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_surcharge_causal_chain_650.py` | assert_substr_in,weak_or_source | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_textual_facts_1828.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_transaction_boundary.py` | named_helper_or_pure | retain | 命名含 helper/pure 但承接真实行为/负向闸，或非与真入口重复的失效证明 |
| `tests/test_transit_aging_346.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_transit_countdown_668.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_urge_lever_624.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_value_matrix_691.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_verify_llm_clocks_884.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_web_audience_night_498.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_web_budget_payload.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_web_chat_serialization_393.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_web_court_visibility.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_web_entry_1902.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/test_web_llm_runtime_config.py` | assert_substr_in,lock_internal_capability_set,setattr_run_backend | fixed_this | 删三端 set==CLI_REASONING_STRENGTH_RUNNERS 内部集合锁；保留 grok∈名单与 reasoning_supported 行为断言 |
| `tests/test_world_materials_1834.py` | assert_substr_in | retain | 子串断言属结构化 reason/来源透传/隔离负向或既结 D5 复查保留面；非本轮 F3 点名失效/重复内部类 |
| `tests/test_yuan_arrival_185.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/wait_utils.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `tests/web_audience_test_doubles.py` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/appDurableWiring.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/buildResources.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/chatFailures.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/cliRunners.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/cliRunnerDropdown.consistency.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/decisionModal.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/drawers.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/gameMenu.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/map.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/menuPage.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/modals.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/settlementFaces.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/settlementGazettePanel.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/components/situation.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/decisionRouting.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/escClose.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/mindreading.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/mindreadingDelivery.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/ministerScrollLens.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/reasoningSupport.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/settleStream.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/settlementPresentation.test.ts` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/staleGuard.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/useDurableProjection.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
| `web/src/useSettlementFlow.test.tsx` | — | retain | 无 F3 嫌疑旗；行为/夹具/类型案保留 |
