# F3 KEEP_NEEDS semantic dispose — read log

依据：冻结判词 `00-1834-judge-768cb88e1.json` F3/F14；fix-packet；P7 射程。

方法：按文件打开源码（及 by_file ±8 摘录）；同形状共享判据；**不**词形自动 KEEP；固定夹具透传与生成措辞分列。

- 原 KEEP_NEEDS_CONTEXT_NOT_AUTO：**1388**
- 已实读文件：**152**
- 未读剩余：**0**
- 类计数：`{'T_TRANSPARENT': 695, 'T_DET_INPUT': 90, 'T_STRUCT': 579, 'T_NEG_FIXTURE': 24}`
- 本轮代码删除/恢复：**0**（非法正文锁与空壳已在本分支前序提交处置；本轮语义复核无新增非法成员）
- F14：现行 `CALENDAR_ADVANCED_*`；历史 `CLOSED_*` 不改写

## 共享契约判据
| class_id | 含义 | 处置 |
| --- | --- | --- |
| T_TRANSPARENT | 同测夹具种子/磁盘写入/mock 回包 → 读回或呈现相等 | KEEP |
| T_DET_INPUT | 玩家/调用输入或固定 prompt 文件契约 | KEEP |
| T_STRUCT | DTO/身份/枚举/固定 UI 字段（P7 界面固定话语） | KEEP |
| T_NEG_FIXTURE | 否定夹具字节出现/P4 不裸数/隔离 | KEEP |
| T_NEG_GENERATED / T_GENERATED_LOCK | 生成散文正/负向锁 | DELETE（本轮成员集中未再发现） |
| T_EMPTY_SHELL | 删断言后无行为证明 | DELETE 用例（本轮未再发现；前序已 RESTORE 或删） |

## 已读文件清单
- `tests/test_appointment_tenure_607.py` n=6 {'T_TRANSPARENT': 6}
- `tests/test_audience_background.py` n=1 {'T_DET_INPUT': 1}
- `tests/test_audience_continuous_507.py` n=2 {'T_STRUCT': 2}
- `tests/test_audience_draft_grant_once_1777.py` n=2 {'T_STRUCT': 2}
- `tests/test_audience_night_498.py` n=2 {'T_STRUCT': 2}
- `tests/test_audience_presence_500.py` n=3 {'T_DET_INPUT': 1, 'T_STRUCT': 2}
- `tests/test_audience_restore_505.py` n=5 {'T_DET_INPUT': 3, 'T_TRANSPARENT': 2}
- `tests/test_audience_scroll_539.py` n=14 {'T_STRUCT': 12, 'T_TRANSPARENT': 1, 'T_DET_INPUT': 1}
- `tests/test_audience_translate_1837.py` n=4 {'T_DET_INPUT': 3, 'T_STRUCT': 1}
- `tests/test_audience_translate_1837_reopen.py` n=5 {'T_TRANSPARENT': 2, 'T_DET_INPUT': 3}
- `tests/test_audience_translation_1838.py` n=14 {'T_STRUCT': 14}
- `tests/test_audience_travel_gating_670.py` n=2 {'T_STRUCT': 2}
- `tests/test_audience_undo_506.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_authority_ledger_611.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_bandit_power_model_190.py` n=5 {'T_TRANSPARENT': 5}
- `tests/test_breach_plea_623.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_character_knowledge_489.py` n=18 {'T_NEG_FIXTURE': 2, 'T_TRANSPARENT': 8, 'T_STRUCT': 8}
- `tests/test_chat_stream_failpaths_393.py` n=2 {'T_TRANSPARENT': 1, 'T_DET_INPUT': 1}
- `tests/test_cli_backend.py` n=8 {'T_NEG_FIXTURE': 2, 'T_TRANSPARENT': 1, 'T_DET_INPUT': 5}
- `tests/test_cli_play_turn.py` n=4 {'T_DET_INPUT': 1, 'T_TRANSPARENT': 1, 'T_STRUCT': 2}
- `tests/test_cli_transport_1465.py` n=1 {'T_DET_INPUT': 1}
- `tests/test_covert_levy_651.py` n=6 {'T_TRANSPARENT': 6}
- `tests/test_credit_events_628.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_declaration_dispatch_1835.py` n=11 {'T_TRANSPARENT': 9, 'T_STRUCT': 2}
- `tests/test_decree_commitment_creation_136.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_decree_dossiers_571.py` n=17 {'T_TRANSPARENT': 11, 'T_DET_INPUT': 3, 'T_STRUCT': 3}
- `tests/test_deformation_dual_rail_622.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_dossier_endorsements_612.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_dossier_reported_progress_619.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_draft_admission_resubmit_1769.py` n=3 {'T_DET_INPUT': 3}
- `tests/test_effect_origin_558.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_enrich_list_guards.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_error_pack.py` n=3 {'T_TRANSPARENT': 1, 'T_STRUCT': 2}
- `tests/test_event_trigger_gate.py` n=16 {'T_STRUCT': 1, 'T_TRANSPARENT': 15}
- `tests/test_execution_joint_liability_565.py` n=12 {'T_TRANSPARENT': 4, 'T_STRUCT': 8}
- `tests/test_execution_pressure_654.py` n=4 {'T_TRANSPARENT': 4}
- `tests/test_executor_routing_721.py` n=20 {'T_TRANSPARENT': 17, 'T_STRUCT': 3}
- `tests/test_faction_brew_637.py` n=17 {'T_TRANSPARENT': 11, 'T_DET_INPUT': 6}
- `tests/test_faction_class_section_rejections.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_faction_leverage_9.py` n=8 {'T_TRANSPARENT': 7, 'T_STRUCT': 1}
- `tests/test_family_tail_615.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_featured_dossiers_494.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_fiscal_levy_effect.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_fiscal_substrate_bridge.py` n=51 {'T_STRUCT': 38, 'T_TRANSPARENT': 11, 'T_NEG_FIXTURE': 2}
- `tests/test_grant_reconciliation_567.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_highlight_judge_544.py` n=8 {'T_TRANSPARENT': 3, 'T_STRUCT': 3, 'T_DET_INPUT': 2}
- `tests/test_history_decree_text_1843_reopen.py` n=1 {'T_NEG_FIXTURE': 1}
- `tests/test_identity_seed_488.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_impeachment_surge_655.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_issue_decree_token_1277.py` n=2 {'T_TRANSPARENT': 1, 'T_DET_INPUT': 1}
- `tests/test_issue_entities.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_llm_channel_config.py` n=3 {'T_DET_INPUT': 3}
- `tests/test_manual_directive_institution_normalize_1279.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_manual_directive_locality_1685.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_material_directory_1830.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_mechanical_tail_1845.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_menu_lifecycle_drain_396.py` n=1 {'T_DET_INPUT': 1}
- `tests/test_month_call_recovery_1846.py` n=7 {'T_STRUCT': 4, 'T_DET_INPUT': 3}
- `tests/test_month_chain_1843.py` n=5 {'T_TRANSPARENT': 5}
- `tests/test_month_chain_1847.py` n=6 {'T_TRANSPARENT': 5, 'T_DET_INPUT': 1}
- `tests/test_month_open_snapshot_1234.py` n=2 {'T_TRANSPARENT': 1, 'T_STRUCT': 1}
- `tests/test_month_translate_1840.py` n=1 {'T_STRUCT': 1}
- `tests/test_mutiny_actual_residence_659.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_mutiny_latch_315.py` n=4 {'T_TRANSPARENT': 4}
- `tests/test_mutiny_noop_whitelist_319.py` n=1 {'T_STRUCT': 1}
- `tests/test_mutiny_progression_316.py` n=6 {'T_TRANSPARENT': 5, 'T_STRUCT': 1}
- `tests/test_mutiny_third_strike_318.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_named_characters_seed_484.py` n=10 {'T_STRUCT': 4, 'T_TRANSPARENT': 6}
- `tests/test_new_issues_section_rejections.py` n=5 {'T_STRUCT': 2, 'T_TRANSPARENT': 3}
- `tests/test_office_inference.py` n=14 {'T_TRANSPARENT': 5, 'T_DET_INPUT': 9}
- `tests/test_office_rank_562.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_on_scene_immediate_write_1839.py` n=2 {'T_STRUCT': 1, 'T_TRANSPARENT': 1}
- `tests/test_opening_gazette_delete_1356.py` n=1 {'T_STRUCT': 1}
- `tests/test_override_breach_costs_564.py` n=3 {'T_STRUCT': 2, 'T_TRANSPARENT': 1}
- `tests/test_p4_guard_new_surfaces_547.py` n=1 {'T_STRUCT': 1}
- `tests/test_pay_order_override_653.py` n=36 {'T_TRANSPARENT': 36}
- `tests/test_pay_order_override_extraction_653.py` n=3 {'T_DET_INPUT': 3}
- `tests/test_person_archive_contract_index.py` n=10 {'T_TRANSPARENT': 10}
- `tests/test_person_delta_adapter.py` n=41 {'T_STRUCT': 10, 'T_TRANSPARENT': 31}
- `tests/test_pihong_dossier_1490.py` n=26 {'T_TRANSPARENT': 9, 'T_STRUCT': 14, 'T_DET_INPUT': 3}
- `tests/test_player_army_projection_321.py` n=6 {'T_TRANSPARENT': 6}
- `tests/test_player_payload_1022.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_population_transfers_649.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_population_unit_648.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_power_section_rejections.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_production_person_key_contract_558.py` n=2 {'T_DET_INPUT': 2}
- `tests/test_promulgation_judge_561.py` n=11 {'T_TRANSPARENT': 11}
- `tests/test_public_character_place_1683.py` n=2 {'T_STRUCT': 2}
- `tests/test_public_sayings_1829.py` n=6 {'T_TRANSPARENT': 6}
- `tests/test_qa_a3_seed_data.py` n=6 {'T_STRUCT': 6}
- `tests/test_qa_b3_409_ux.py` n=7 {'T_STRUCT': 6, 'T_NEG_FIXTURE': 1}
- `tests/test_qa_c2_phase_settlement_mask_1374.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_qa_d1_decree_normalize_1274.py` n=6 {'T_DET_INPUT': 3, 'T_STRUCT': 2, 'T_TRANSPARENT': 1}
- `tests/test_qa_e1_numeric_presentation.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_qa_h1_seed_data.py` n=7 {'T_TRANSPARENT': 5, 'T_STRUCT': 2}
- `tests/test_qa_s2_copy_prompts_1356_1402.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_recommendation_edges_635.py` n=4 {'T_TRANSPARENT': 4}
- `tests/test_recommendations.py` n=8 {'T_TRANSPARENT': 8}
- `tests/test_region_cannon_delta.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_reign_period_label.py` n=7 {'T_STRUCT': 7}
- `tests/test_relation_brew_636.py` n=12 {'T_TRANSPARENT': 12}
- `tests/test_relation_capture_633.py` n=11 {'T_TRANSPARENT': 11}
- `tests/test_relation_seed_638.py` n=39 {'T_TRANSPARENT': 12, 'T_STRUCT': 27}
- `tests/test_relation_store_632.py` n=7 {'T_TRANSPARENT': 7}
- `tests/test_rescript_choices_563.py` n=4 {'T_STRUCT': 4}
- `tests/test_rescript_draft_656.py` n=32 {'T_TRANSPARENT': 17, 'T_DET_INPUT': 10, 'T_STRUCT': 5}
- `tests/test_rescript_heal_isolation_1801.py` n=6 {'T_DET_INPUT': 4, 'T_STRUCT': 2}
- `tests/test_rescript_option_field_heal_1746.py` n=2 {'T_DET_INPUT': 2}
- `tests/test_secret_order_isolation_883.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_secret_order_monthly_progress_566.py` n=2 {'T_DET_INPUT': 1, 'T_TRANSPARENT': 1}
- `tests/test_secret_order_payoff_1504.py` n=28 {'T_TRANSPARENT': 14, 'T_NEG_FIXTURE': 4, 'T_STRUCT': 9, 'T_DET_INPUT': 1}
- `tests/test_secret_order_section_rejections.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_secret_order_update.py` n=5 {'T_TRANSPARENT': 5}
- `tests/test_section4_rejections.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_section_fiscal_rejections.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_shared_resource_order_1844.py` n=2 {'T_STRUCT': 2}
- `tests/test_six_sciences_seed_608.py` n=4 {'T_TRANSPARENT': 4}
- `tests/test_staged_assignment_identity_1890.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_start_sh_deps_1721.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_structured_decree_contract_1624.py` n=7 {'T_TRANSPARENT': 2, 'T_DET_INPUT': 5}
- `tests/test_style_temperament_641.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_surcharge_causal_chain_650.py` n=3 {'T_TRANSPARENT': 3}
- `tests/test_web_audience_night_498.py` n=2 {'T_TRANSPARENT': 2}
- `tests/test_web_budget_payload.py` n=1 {'T_TRANSPARENT': 1}
- `tests/test_web_chat_serialization_393.py` n=1 {'T_DET_INPUT': 1}
- `tests/test_web_court_visibility.py` n=9 {'T_TRANSPARENT': 9}
- `tests/test_web_issue_condition_display.py` n=11 {'T_TRANSPARENT': 5, 'T_STRUCT': 6}
- `web/src/appDurableWiring.test.tsx` n=101 {'T_STRUCT': 50, 'T_TRANSPARENT': 45, 'T_NEG_FIXTURE': 6}
- `web/src/buildResources.test.ts` n=5 {'T_STRUCT': 5}
- `web/src/chatFailures.test.ts` n=8 {'T_STRUCT': 6, 'T_TRANSPARENT': 2}
- `web/src/cliRunners.test.ts` n=7 {'T_STRUCT': 7}
- `web/src/components/cliRunnerDropdown.consistency.test.tsx` n=6 {'T_STRUCT': 6}
- `web/src/components/decisionModal.test.tsx` n=67 {'T_TRANSPARENT': 52, 'T_STRUCT': 12, 'T_NEG_FIXTURE': 3}
- `web/src/components/drawers.test.tsx` n=20 {'T_TRANSPARENT': 6, 'T_STRUCT': 14}
- `web/src/components/gameMenu.test.tsx` n=46 {'T_STRUCT': 35, 'T_TRANSPARENT': 11}
- `web/src/components/map.test.tsx` n=4 {'T_STRUCT': 4}
- `web/src/components/menuPage.test.tsx` n=30 {'T_STRUCT': 21, 'T_TRANSPARENT': 9}
- `web/src/components/modals.test.tsx` n=73 {'T_TRANSPARENT': 37, 'T_STRUCT': 35, 'T_NEG_FIXTURE': 1}
- `web/src/components/settlementFaces.test.tsx` n=34 {'T_TRANSPARENT': 8, 'T_STRUCT': 26}
- `web/src/components/situation.test.tsx` n=10 {'T_TRANSPARENT': 10}
- `web/src/decisionRouting.test.tsx` n=27 {'T_STRUCT': 27}
- `web/src/escClose.test.tsx` n=6 {'T_STRUCT': 6}
- `web/src/mindreading.test.ts` n=2 {'T_TRANSPARENT': 2}
- `web/src/mindreadingDelivery.test.tsx` n=15 {'T_STRUCT': 10, 'T_TRANSPARENT': 5}
- `web/src/ministerScrollLens.test.ts` n=10 {'T_STRUCT': 9, 'T_TRANSPARENT': 1}
- `web/src/reasoningSupport.test.ts` n=6 {'T_STRUCT': 6}
- `web/src/settleStream.test.ts` n=3 {'T_TRANSPARENT': 2, 'T_STRUCT': 1}
- `web/src/settlementPresentation.test.ts` n=30 {'T_STRUCT': 28, 'T_NEG_FIXTURE': 2}
- `web/src/staleGuard.test.tsx` n=20 {'T_TRANSPARENT': 13, 'T_DET_INPUT': 3, 'T_STRUCT': 4}
- `web/src/styles.test.ts` n=19 {'T_STRUCT': 19}
- `web/src/useDurableProjection.test.tsx` n=7 {'T_STRUCT': 7}
- `web/src/useSettlementFlow.test.tsx` n=34 {'T_TRANSPARENT': 24, 'T_STRUCT': 10}
