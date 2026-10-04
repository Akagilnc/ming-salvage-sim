# D5 全成员表（0ca77fecc → HEAD，人工实读分类）

## 类定义（判词 + 现行票面，未收窄）

D5：测试清退仍有来源契约误删及失效证明残留。

- **保留**：真实入口的调用输入、来源及持久化契约；来源比较取实际输入，不锁固定措辞。
- **清除**：失去契约价值的 helper／内部／重复证明及其夹具。
- **禁止**：整函数恢复、平行测试、扫描机制、生产护栏。

## 枚举原命令（全仓测试路径，非仅 tests/+web/src）

```bash
# 1) 全仓 tracked 测试路径宇宙（git ls-files + 测试路径谓词）
git ls-files | rg -i '(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$|fixtures?/)'
# → 265 paths；本仓谓词命中均落在 tests/ 与 web/（0 条在其它根）

# 2) 基线测试路径并集（含已删）
git ls-tree -r --name-only 0ca77fecc | rg -i '(同上谓词)'
# universe = base∪head = 269

# 3) 授权范围 name-status 与宇宙求交
git diff --name-status 0ca77fecc..HEAD
# → 触及 167 条（A6/M157/D4）；含 fixture 与断言未变但改调用之实例
```

分类代号：`R`保留/修理来源或真入口 · `W`盯文/呈现退役 · `H`helper/内部/重复 · `C`仅调用/夹具重接 · `A`新增 · `D`退役整删 · `X`例外

| # | 路径 | st | Δassert/+expect | 类 | 依据（实读） |
|---:|---|---|---:|---|---|
| 1 | `tests/audience_chat_helpers.py` | A | FILE_ADD | A | 共享召对入口 helper |
| 2 | `tests/conftest.py` | M | a-0/+1 | C | D7 原生任务 join/wait; 非 D5 来源类 |
| 3 | `tests/directive_entry_helpers.py` | A | FILE_ADD | A | 共享拟旨/草稿准备 helper |
| 4 | `tests/issue_stream_helpers.py` | A | FILE_ADD | A | SSE/issue 流 helper |
| 5 | `tests/sse_helpers.py` | A | FILE_ADD | A | parse_sse 共享 |
| 6 | `tests/test_adr0015_per_item_rejection.py` | M | a-7/+8 | R | 断言重组 -7/+8（保留/改写行为或来源面） |
| 7 | `tests/test_advance_paths_atomic.py` | M | a-4/+0 | H | inspect.getsource/hasattr 内部缺席证明 |
| 8 | `tests/test_advance_without_edict_report_1345.py` | D | FILE_DEL | D | 快路/报告措辞退役; 现役 advance 他案 |
| 9 | `tests/test_advances_section_rejections.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 10 | `tests/test_applier_contract.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 11 | `tests/test_appointment_tenure_607.py` | M | a-1/+0 | W | 固定 ValueError 包装句≠注入来源; 回滚行为仍在 |
| 12 | `tests/test_army_card_status_1501.py` | M | a-6/+1 | R | 断言重组 -6/+1（保留/改写行为或来源面） |
| 13 | `tests/test_army_display_173.py` | M | a-13/+6 | W | 欠饷文案/排序呈现盯文为主; payload 键有并行案 |
| 14 | `tests/test_army_firearms.py` | M | a-8/+7 | R | 断言重组 -8/+7（保留/改写行为或来源面） |
| 15 | `tests/test_army_maintenance_retire_173.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 16 | `tests/test_audience_background.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 17 | `tests/test_audience_draft_grant_once_1777.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 18 | `tests/test_audience_night_498.py` | M | a-1/+3 | R | 断言重组 -1/+3（保留/改写行为或来源面） |
| 19 | `tests/test_audience_translate_1837.py` | M | a-2/+1 | R | 断言重组 -2/+1（保留/改写行为或来源面） |
| 20 | `tests/test_audience_translate_1837_reopen.py` | M | a-0/+1 | R | 新增 assert 1 |
| 21 | `tests/test_audience_travel_gating_670.py` | M | a-12/+0 | W | 净删 assert 12（拒句/match/呈现/内部；行为断言复核仍在） |
| 22 | `tests/test_authority_ledger_611.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 23 | `tests/test_bandit_power_model_190.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 24 | `tests/test_breach_plea_623.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 25 | `tests/test_character_knowledge_489.py` | M | a-5/+5 | R | 断言重组 -5/+5（保留/改写行为或来源面） |
| 26 | `tests/test_chat_stream_failpaths_393.py` | M | a-5/+1 | R | 断言重组 -5/+1（保留/改写行为或来源面） |
| 27 | `tests/test_cli_backend.py` | M | a-43/+17 | C | 入口/合并路径重构断言重组 |
| 28 | `tests/test_cli_entry_1902.py` | A | FILE_ADD | A | 1902 CLI 入口契约新案 |
| 29 | `tests/test_cli_play_turn.py` | M | a-16/+17 | R | 断言重组 -16/+17（保留/改写行为或来源面） |
| 30 | `tests/test_cli_runner_error_typed_1299.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 31 | `tests/test_cli_transport_1465.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 32 | `tests/test_close_issues_section_rejections.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） |
| 33 | `tests/test_commitment_backlash_626.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） |
| 34 | `tests/test_court_break_player_lock_1727.py` | M | a-1/+6 | R | 断言重组 -1/+6（保留/改写行为或来源面） |
| 35 | `tests/test_covert_levy_651.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 36 | `tests/test_credit_events_628.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 37 | `tests/test_db_broad_except_surface.py` | M | a-4/+4 | R | 断言重组 -4/+4（保留/改写行为或来源面） |
| 38 | `tests/test_declaration_dispatch_1835.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 39 | `tests/test_decree_commitment_creation_136.py` | M | a-23/+1 | R | 断言重组 -23/+1（保留/改写行为或来源面） |
| 40 | `tests/test_decree_commitment_schema_136.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 41 | `tests/test_decree_commitment_settlement_229.py` | M | a-6/+1 | R | 断言重组 -6/+1（保留/改写行为或来源面） |
| 42 | `tests/test_decree_dossiers_571.py` | M | a-25/+2 | H | getsource set_decree 缺席+部分措辞; 行为案保留 |
| 43 | `tests/test_deepseek_thinking_disable_1797.py` | M | a-6/+3 | R | 改走 _dump_value 序列化入口携带原始 reasoning/usage/finish; 非锁 dump 模板 |
| 44 | `tests/test_dossier_endorsements_612.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 45 | `tests/test_dossier_links_559.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 46 | `tests/test_dossier_reported_progress_619.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 47 | `tests/test_draft_admission_resubmit_1769.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 48 | `tests/test_due_review_621.py` | M | a-6/+1 | R | prepare_scene_materials 真入口+origin/criterion 实际输入; wait jobs; 删 helper/extractor hasattr |
| 49 | `tests/test_enter_settlement_period_1235.py` | M | a-10/+5 | R | 断言重组 -10/+5（保留/改写行为或来源面） |
| 50 | `tests/test_error_pack.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 51 | `tests/test_event_chain_cascade.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 52 | `tests/test_event_trigger_gate.py` | M | a-37/+0 | W | reason/summary 中文模板大删; 触发/落库行为保留 |
| 53 | `tests/test_execution_joint_liability_565.py` | M | a-8/+1 | R | 断言重组 -8/+1（保留/改写行为或来源面） |
| 54 | `tests/test_execution_pressure_654.py` | M | a-12/+0 | W | 净删 assert 12（拒句/match/呈现/内部；行为断言复核仍在） |
| 55 | `tests/test_executor_routing_721.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 56 | `tests/test_faction_brew_637.py` | M | a-14/+0 | W | 净删 assert 14（拒句/match/呈现/内部；行为断言复核仍在） |
| 57 | `tests/test_faction_class_section_rejections.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 58 | `tests/test_faction_denunciation_627.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） |
| 59 | `tests/test_faction_leverage_9.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 60 | `tests/test_featured_dossiers_494.py` | M | a-11/+7 | W | 档料标题/键名盯文→dossier 非空且进入 context |
| 61 | `tests/test_fiscal_levy_effect.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 62 | `tests/test_fiscal_substrate_bridge.py` | M | a-39/+8 | W | 财政呈现/理由子串清退 |
| 63 | `tests/test_gazette_author_1862.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 64 | `tests/test_grant_reconciliation_567.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 65 | `tests/test_history_decree_text_1843_reopen.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 66 | `tests/test_hitl_quota_delete_1467.py` | D | FILE_DEL | D | HITL 配额整机制退役证明 |
| 67 | `tests/test_identity_seed_488.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 68 | `tests/test_impeachment_surge_655.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 69 | `tests/test_issue_decree_token_1277.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 70 | `tests/test_issue_entities.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 71 | `tests/test_junxin_monthly_tick_314.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 72 | `tests/test_llm_channel_config.py` | M | a-22/+0 | H | 内部配置形状/重复证明清退 |
| 73 | `tests/test_manual_directive_institution_normalize_1279.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） |
| 74 | `tests/test_manual_directive_locality_1685.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 75 | `tests/test_material_directory_1830.py` | M | a-8/+0 | W | 净删 assert 8（拒句/match/呈现/内部；行为断言复核仍在） |
| 76 | `tests/test_mechanical_tail_1845.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 77 | `tests/test_menu_continue_stream_1195.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 78 | `tests/test_menu_lifecycle_drain_396.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） |
| 79 | `tests/test_minister_chat_timeout.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 80 | `tests/test_month_call_recovery_1846.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 81 | `tests/test_month_chain_1843.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 82 | `tests/test_month_chain_1847.py` | M | a-5/+5 | R | 断言重组 -5/+5（保留/改写行为或来源面） |
| 83 | `tests/test_month_loop_tracer_1468.py` | M | a-3/+2 | R | 断言重组 -3/+2（保留/改写行为或来源面） |
| 84 | `tests/test_month_open_snapshot_1234.py` | M | a-2/+1 | R | 断言重组 -2/+1（保留/改写行为或来源面） |
| 85 | `tests/test_mutiny_noop_whitelist_319.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 86 | `tests/test_mutiny_third_strike_318.py` | M | a-7/+0 | W | 净删 assert 7（拒句/match/呈现/内部；行为断言复核仍在） |
| 87 | `tests/test_named_characters_seed_484.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 88 | `tests/test_new_game_dependency_mismatch_1721.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 89 | `tests/test_new_game_smoke.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 90 | `tests/test_new_game_write_path_1749.py` | M | a-3/+6 | C | 改走玩家召对真写入口+stage_draft 数据准备 |
| 91 | `tests/test_new_issues_section_rejections.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） |
| 92 | `tests/test_no_edict_full_settlement_1274.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 93 | `tests/test_office_inference.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） |
| 94 | `tests/test_on_scene_immediate_write_1839.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 95 | `tests/test_opening_gazette_delete_1356.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） |
| 96 | `tests/test_override_breach_costs_564.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 97 | `tests/test_pay_order_override_653.py` | M | a-8/+0 | W | 净删 assert 8（拒句/match/呈现/内部；行为断言复核仍在） |
| 98 | `tests/test_pay_order_override_extraction_653.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） |
| 99 | `tests/test_person_archive_schema.py` | M | a-15/+0 | W | 净删 assert 15（拒句/match/呈现/内部；行为断言复核仍在） |
| 100 | `tests/test_person_delta_adapter.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 101 | `tests/test_pihong_dossier_1490.py` | M | a-14/+3 | R | label/hint==server_option; note==lying.note; wait_idle; 删 match/批红句 |
| 102 | `tests/test_player_army_projection_321.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 103 | `tests/test_player_payload_1022.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 104 | `tests/test_population_transfers_649.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 105 | `tests/test_population_unit_648.py` | M | a-4/+3 | R | 断言重组 -4/+3（保留/改写行为或来源面） |
| 106 | `tests/test_power_section_rejections.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 107 | `tests/test_pre_settle_transaction.py` | M | a-8/+0 | H | inspect.getsource 内部缺席证明 |
| 108 | `tests/test_production_person_key_contract_558.py` | D | FILE_DEL | D | prompt 人物键措辞盯文 |
| 109 | `tests/test_promulgation_judge_561.py` | M | a-9/+0 | W | 净删 assert 9（拒句/match/呈现/内部；行为断言复核仍在） |
| 110 | `tests/test_promulgation_seam_560.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 111 | `tests/test_public_sayings_1829.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） |
| 112 | `tests/test_qa_1281_issue_audience_case_facts.py` | M | a-0/+0 | W | raises 去 match 盯文; 行为 raises 仍在 |
| 113 | `tests/test_qa_a3_seed_data.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 114 | `tests/test_qa_b3_409_ux.py` | M | a-13/+1 | R | 断言重组 -13/+1（保留/改写行为或来源面） |
| 115 | `tests/test_qa_d1_decree_normalize_1274.py` | M | a-17/+2 | R | 断言重组 -17/+2（保留/改写行为或来源面） |
| 116 | `tests/test_qa_e1_numeric_presentation.py` | M | a-21/+1 | R | 断言重组 -21/+1（保留/改写行为或来源面） |
| 117 | `tests/test_qa_h1_seed_data.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 118 | `tests/test_qa_s2_copy_prompts_1356_1402.py` | M | a-11/+0 | W | 净删 assert 11（拒句/match/呈现/内部；行为断言复核仍在） |
| 119 | `tests/test_qa_t1_extraction_dual_source_1353.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 120 | `tests/test_recommendation_batch_snapshot_1583.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 121 | `tests/test_refugee_loop_652.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 122 | `tests/test_region_cannon_delta.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 123 | `tests/test_region_citydefense_display.py` | M | a-6/+4 | R | 断言重组 -6/+4（保留/改写行为或来源面） |
| 124 | `tests/test_rejection_wiring.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） |
| 125 | `tests/test_relation_brew_636.py` | M | a-22/+3 | R | 断言重组 -22/+3（保留/改写行为或来源面） |
| 126 | `tests/test_relation_capture_633.py` | M | a-19/+0 | R | 坏端点名→reason 本轮以变量补回; 其余拒句 match 盯文维持删; 零边行为保留 |
| 127 | `tests/test_relation_seed_638.py` | M | a-19/+1 | R | 断言重组 -19/+1（保留/改写行为或来源面） |
| 128 | `tests/test_relation_store_632.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 129 | `tests/test_rescript_choices_563.py` | M | a-4/+1 | R | 断言重组 -4/+1（保留/改写行为或来源面） |
| 130 | `tests/test_rescript_draft_656.py` | M | a-23/+1 | R | reason==str(unavailable); title-in-tlog 本轮补回; 删 prompt/SQL/match 盯文 |
| 131 | `tests/test_runtime_llm_config.py` | M | a-18/+7 | R | 断言重组 -18/+7（保留/改写行为或来源面） |
| 132 | `tests/test_secret_order_isolation_883.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 133 | `tests/test_secret_order_monthly_progress_566.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 134 | `tests/test_secret_order_payoff_1504.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 135 | `tests/test_section4_rejections.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） |
| 136 | `tests/test_session_write_queue_1353.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） |
| 137 | `tests/test_settlement_write_guard_393.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） |
| 138 | `tests/test_shared_resource_order_1844.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 139 | `tests/test_six_sciences_seed_608.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 140 | `tests/test_state_reload.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 141 | `tests/test_structured_decree_contract_1624.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） |
| 142 | `tests/test_style_temperament_641.py` | M | a-3/+2 | R | payload_summary==item[reason] 来源相等; 删 or 固定句兜底 |
| 143 | `tests/test_supervision_625.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） |
| 144 | `tests/test_surcharge_causal_chain_650.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 145 | `tests/test_transaction_boundary.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 146 | `tests/test_transit_countdown_668.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） |
| 147 | `tests/test_urge_lever_624.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 |
| 148 | `tests/test_web_audience_night_498.py` | M | a-1/+2 | R | 断言重组 -1/+2（保留/改写行为或来源面） |
| 149 | `tests/test_web_chat_serialization_393.py` | M | a-4/+2 | R | 断言重组 -4/+2（保留/改写行为或来源面） |
| 150 | `tests/test_web_court_visibility.py` | M | a-7/+2 | R | choose_minister 真实选择→Character/None; 删 print 名册与拒因中文子串 |
| 151 | `tests/test_web_entry_1902.py` | A | FILE_ADD | A | 新增测试/helper |
| 152 | `tests/test_web_issue_condition_display.py` | M | a-13/+4 | R | 断言重组 -13/+4（保留/改写行为或来源面） |
| 153 | `tests/test_web_llm_runtime_config.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） |
| 154 | `tests/web_audience_test_doubles.py` | M | a-0/+0 | C | 双端替身/调用面调整 |
| 155 | `web/src/appDurableWiring.test.tsx` | M | e-95/+1 | W | 拟诏台/局部文案大删; 保留 alert==detail.message 等来源; 空疏改 empty-note |
| 156 | `web/src/chatFailures.test.ts` | M | e-4/+0 | W | 赴京/SUMMON 缺席盯文 |
| 157 | `web/src/components/decisionModal.test.tsx` | M | e-4/+0 | W | hint 固定提示文案 |
| 158 | `web/src/components/drawers.test.tsx` | M | e-21/+0 | W | 抽屉数值/欠饷呈现盯文 |
| 159 | `web/src/components/electronLayout.medium.test.tsx` | M | e-4/+2 | C | 布局不相交度量键更名 |
| 160 | `web/src/components/gameMenu.test.tsx` | M | e-1/+0 | W | runner 列表含 grok 盯文 |
| 161 | `web/src/components/modals.test.tsx` | M | e-8/+3 | W | 固定报警句→有文案; 删按钮含「删」 |
| 162 | `web/src/components/settlementFaces.test.tsx` | M | e-4/+0 | W | 邸报/起居注固定标签 |
| 163 | `web/src/components/situation.test.tsx` | M | e-12/+4 | W | 进度/空疏固定句→节点存在性 |
| 164 | `web/src/decisionRouting.test.tsx` | M | e-1/+0 | W | error 不含「重新拉取」 |
| 165 | `web/src/ministerScrollLens.test.ts` | M | e-4/+0 | W | 密令/神色等缺席盯文 |
| 166 | `web/src/settlementPresentation.test.ts` | M | e-23/+0 | W | 年月/王承恩条固定句与 formatter 证明 |
| 167 | `web/src/styles.test.ts` | D | e-31/+0 | D | CSS 字符串形状盯文 |

## 计数

- `R`: 40
- `W`: 83
- `H`: 4
- `C`: 30
- `A`: 6
- `D`: 4
- `X`: 0
- **合计成员**: 167

## 本轮生产同型简修（非测试成员，附录）

- `ming_sim/knowledge.py:550`：亲验非 `event_pool` + 非空 `stage_text` → `TypeError`（`not in None`）。已与 materials/`project_issue_materials` 同口径 `audiences = _issue_audience_names(...) or set()`。
- `ming_sim/materials.py`：上轮已钳制，维持。

## 复扫例外

- 未对每一条 ±assert 做变异亲验（派单不要求）；分类依据为 diff 实读 + 与判词样本同型的来源/空洞判据。
- 拒因中文模板 / `pytest.raises(..., match=固定句)` / UI 固定提示 / CSS 形状：一律归 `W`，不整补。
- 端点名/title/异常 str 进入结构化 reason 或 tlog：归 `R`，按实际输入变量比较。
- 未新建 enumerate/classify 扫描机制；本表为人工分类回执，`/tmp` 一次性摘录不入仓。

## 复扫结论

授权范围内 167 个测试路径成员均已逐文件实读归类；本轮补：knowledge None 钳制、rescript title→tlog、relation 坏端点名→reason。未发现仍存活的空洞证明（仅 assert 真值/None 却声称选择或供料契约）。Web 13 文件 expect 全量实读，非抽查。
