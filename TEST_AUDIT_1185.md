# TEST_AUDIT_1185 — 全量测试五尺审计报告

> 票面：#1185 测试大清理 · 第二阶段审计腿（零删除）  
> 分支：`policy/issue-1185-test-tiering` @ `6bd36b4`  
> 采集：`.venv/bin/python -m pytest -q --durations=0`  
> **审计基线（Batch 1 前）**：3024 passed, 11 skipped in 1060.15s (0:17:40)  
> 收集：3035 tests / 129 files / 73027 lines  
> 约束：本轮只审计、不改任何测试文件。本报告为冻结审计件，非活台账。

---

## 0. 执行摘要

| 指标 | 值 |
|---|---|
| 墙钟全量 | **1060.15s（17m40s）** |
| 通过/跳过 | 3024 passed / 11 skipped |
| 文件/用例/行 | 129 / 3035 / 73027 |
| 单文件耗时合计（估） | ~1049s（call+setup+teardown；<0.005s call 按 0.002s 估） |
| 最大瓶颈 | `test_session_cli_fallback.py` ~386s（实打 agy CLI） |
| 次瓶颈 | `test_secret_order_isolation_883.py` ~147s（同上） |

**关键发现**：全量 17.6 分钟里，约 **一半以上** 耗在 ~10 条未 mock 干净的 CLI 会话用例上——
`apply_cli_conversation_actions` → `classify_cli_action_intent` → `_run_agy` → 真实 `subprocess`（cProfile 单案 45.3s poll）。
这不是「业务重」，是**测试双线泄漏**。改造这批 mock 即可在不删契约的前提下砍掉 ~8–10 分钟。

五尺主类分布（每文件一个主类）：

| 五尺 | 文件数 |
|---|---:|
| 真行为契约 | 103 |
| 盯文 | 9 |
| 重复 | 1 |
| 只测helper | 14 |
| mock伪行为 | 2 |

---

## 1. 计时总表（按估时降序）

说明：
- `call_shown` = `--durations=0` 展示的 call 累计（≥0.005s）
- `setup/teardown` = 同文件 setup+teardown 展示累计
- `hidden` = 用例数 − 展示 call 数（各 <0.005s）
- `total_est` = call_shown + setup + teardown + hidden×0.002

| # | 文件 | 行 | 用例 | call_s | setup_s | total_est_s | 主类 | 处置 | 闸 |
|---:|---|---:|---:|---:|---:|---:|---|---|---|
| 1 | `tests/test_session_cli_fallback.py` | 2923 | 92 | 377.34 | 8.96 | 386.47 | 真行为契约 | 改造 |  |
| 2 | `tests/test_secret_order_isolation_883.py` | 2093 | 42 | 141.13 | 5.51 | 146.68 | 真行为契约 | 改造 | 🔒 |
| 3 | `tests/test_event_trigger_gate.py` | 5908 | 203 | 1.15 | 53.27 | 55.32 | 真行为契约 | 改造 | 🔒 |
| 4 | `tests/test_conversational_draft.py` | 1892 | 77 | 0.78 | 47.27 | 49.26 | 真行为契约 | 改造 |  |
| 5 | `tests/test_decree_dossiers_571.py` | 3412 | 172 | 1.44 | 34.91 | 36.88 | 真行为契约 | — | 🔒 |
| 6 | `tests/test_character_knowledge_489.py` | 993 | 52 | 4.07 | 30.28 | 35.03 | 真行为契约 | 合并 | 🔒 |
| 7 | `tests/test_fiscal_substrate_bridge.py` | 5333 | 184 | 1.65 | 32.35 | 34.21 | 真行为契约 | 改造 | 🔒 |
| 8 | `tests/test_person_delta_adapter.py` | 4135 | 126 | 0.82 | 17.00 | 18.00 | 真行为契约 | — | 🔒 |
| 9 | `tests/test_minister_context.py` | 1019 | 47 | 1.04 | 15.49 | 16.70 | mock伪行为 | 改造 |  |
| 10 | `tests/test_pending_actions.py` | 2493 | 80 | 0.64 | 15.56 | 16.35 | 真行为契约 | — | 🔒 |
| 11 | `tests/test_decree_commitment_settlement_229.py` | 1651 | 34 | 1.47 | 12.93 | 14.48 | 真行为契约 | — |  |
| 12 | `tests/test_knowledge.py` | 467 | 20 | 0.67 | 9.92 | 10.63 | 重复 | 合并 |  |
| 13 | `tests/test_decree_commitment_creation_136.py` | 1221 | 33 | 0.23 | 9.08 | 9.42 | 真行为契约 | — |  |
| 14 | `tests/test_fiscal_levy_effect.py` | 1394 | 49 | 0.50 | 8.77 | 9.32 | 真行为契约 | — |  |
| 15 | `tests/test_dossier_links_559.py` | 589 | 42 | 0.87 | 8.12 | 9.09 | 真行为契约 | — |  |
| 16 | `tests/test_mindreading_491.py` | 302 | 14 | 0.60 | 7.27 | 7.90 | 真行为契约 | — |  |
| 17 | `tests/test_issue_entities.py` | 595 | 32 | 0.15 | 7.10 | 7.30 | 真行为契约 | — | 🔒 |
| 18 | `tests/test_faction_leverage_9.py` | 1258 | 37 | 1.14 | 6.03 | 7.23 | 真行为契约 | — |  |
| 19 | `tests/test_promulgation_judge_561.py` | 699 | 38 | 0.30 | 6.26 | 6.66 | 真行为契约 | — | 🔒 |
| 20 | `tests/test_multi_directive_502.py` | 671 | 18 | 0.16 | 6.44 | 6.62 | 真行为契约 | — |  |
| 21 | `tests/test_driver.py` | 592 | 35 | 1.10 | 5.33 | 6.51 | 真行为契约 | — | 🔒 |
| 22 | `tests/test_cli_backend.py` | 1832 | 137 | 2.16 | 2.90 | 5.44 | 只测helper | 改造 |  |
| 23 | `tests/test_event_chain_cascade.py` | 360 | 16 | 0.02 | 5.28 | 5.36 | 真行为契约 | — |  |
| 24 | `tests/test_db_broad_except_surface.py` | 197 | 8 | 0.02 | 5.04 | 5.08 | 真行为契约 | — |  |
| 25 | `tests/test_error_pack.py` | 434 | 18 | 0.16 | 4.51 | 4.75 | 真行为契约 | — | 🔒 |
| 26 | `tests/test_audience_background.py` | 744 | 22 | 2.28 | 2.33 | 4.66 | 真行为契约 | — |  |
| 27 | `tests/test_audience_extraction_501.py` | 713 | 34 | 0.23 | 4.32 | 4.59 | 真行为契约 | — | 🔒 |
| 28 | `tests/test_pre_settle_transaction.py` | 504 | 18 | 0.29 | 4.25 | 4.57 | 真行为契约 | — | 🔒 |
| 29 | `tests/test_decree_commitment_schema_136.py` | 349 | 34 | 0.34 | 3.68 | 4.16 | 真行为契约 | — |  |
| 30 | `tests/test_commitment_display_348.py` | 338 | 24 | 0.12 | 3.92 | 4.10 | 盯文 | 改造 |  |
| 31 | `tests/test_recommendations.py` | 323 | 14 | 0.02 | 3.98 | 4.10 | 真行为契约 | — |  |
| 32 | `tests/test_resolve_context_recovery.py` | 378 | 16 | 0.04 | 3.94 | 4.03 | 真行为契约 | — |  |
| 33 | `tests/test_advance_paths_atomic.py` | 1412 | 35 | 0.44 | 3.50 | 3.97 | 真行为契约 | — | 🔒 |
| 34 | `tests/test_beat_orchestration_503.py` | 518 | 17 | 0.32 | 3.48 | 3.85 | 真行为契约 | — |  |
| 35 | `tests/test_effect_origin_558.py` | 390 | 13 | 0.10 | 3.69 | 3.83 | 真行为契约 | — |  |
| 36 | `tests/test_web_audience_night_498.py` | 471 | 7 | 2.89 | 0.92 | 3.81 | 真行为契约 | 合并 |  |
| 37 | `tests/test_promulgation_seam_560.py` | 579 | 28 | 0.50 | 3.10 | 3.62 | 真行为契约 | — | 🔒 |
| 38 | `tests/test_chat_mutations_freeze.py` | 181 | 6 | 0.00 | 3.32 | 3.34 | 真行为契约 | — | 🔒 |
| 39 | `tests/test_secret_order_monthly_progress_566.py` | 714 | 24 | 0.59 | 2.65 | 3.24 | 真行为契约 | — | 🔒 |
| 40 | `tests/test_new_issues_section_rejections.py` | 516 | 42 | 0.12 | 2.85 | 3.07 | 真行为契约 | — | 🔒 |
| 41 | `tests/test_transaction_boundary.py` | 581 | 27 | 0.00 | 2.86 | 2.91 | 真行为契约 | — | 🔒 |
| 42 | `tests/test_near_minister_reports_492.py` | 220 | 17 | 0.10 | 2.44 | 2.59 | 真行为契约 | — |  |
| 43 | `tests/test_section_fiscal_rejections.py` | 750 | 44 | 1.35 | 1.11 | 2.48 | 真行为契约 | — | 🔒 |
| 44 | `tests/test_audience_scroll_539.py` | 416 | 18 | 0.12 | 2.29 | 2.43 | 真行为契约 | — |  |
| 45 | `tests/test_audience_undo_506.py` | 585 | 17 | 0.22 | 2.14 | 2.39 | 真行为契约 | — |  |
| 46 | `tests/test_section4_rejections.py` | 758 | 47 | 1.15 | 1.19 | 2.35 | 真行为契约 | — | 🔒 |
| 47 | `tests/test_audience_night_498.py` | 637 | 17 | 0.57 | 1.57 | 2.19 | 真行为契约 | — | 🔒 |
| 48 | `tests/test_audience_restore_505.py` | 506 | 13 | 0.20 | 1.92 | 2.13 | 真行为契约 | — |  |
| 49 | `tests/test_audience_pipeline_499.py` | 528 | 13 | 0.41 | 1.57 | 2.00 | 真行为契约 | — |  |
| 50 | `tests/test_secret_order_update.py` | 179 | 12 | 0.03 | 1.87 | 1.96 | 真行为契约 | — |  |
| 51 | `tests/test_audience_presence_500.py` | 403 | 14 | 0.07 | 1.86 | 1.95 | 真行为契约 | — |  |
| 52 | `tests/test_close_issues_section_rejections.py` | 202 | 19 | 0.02 | 1.62 | 1.92 | 真行为契约 | — | 🔒 |
| 53 | `tests/test_web_court_visibility.py` | 449 | 22 | 0.00 | 1.77 | 1.81 | 真行为契约 | — |  |
| 54 | `tests/test_economy_section_rejections.py` | 219 | 11 | 1.08 | 0.71 | 1.81 | 真行为契约 | — | 🔒 |
| 55 | `tests/test_state_reload.py` | 369 | 15 | 0.06 | 1.71 | 1.79 | 真行为契约 | — | 🔒 |
| 56 | `tests/test_audience_continuous_507.py` | 236 | 8 | 0.15 | 1.63 | 1.79 | 真行为契约 | — |  |
| 57 | `tests/test_rescript_choices_563.py` | 272 | 13 | 0.06 | 1.65 | 1.75 | 真行为契约 | — |  |
| 58 | `tests/test_army_salary_44.py` | 351 | 24 | 0.28 | 1.41 | 1.73 | 真行为契约 | — |  |
| 59 | `tests/test_office_rank_562.py` | 421 | 18 | 0.17 | 1.42 | 1.61 | 真行为契约 | — |  |
| 60 | `tests/test_action_cluster_registry_515.py` | 637 | 16 | 0.16 | 1.34 | 1.52 | 真行为契约 | — |  |
| 61 | `tests/test_character_projection_1023.py` | 78 | 2 | 0.10 | 1.39 | 1.50 | 真行为契约 | — |  |
| 62 | `tests/test_settle_core.py` | 386 | 11 | 0.15 | 1.23 | 1.38 | 真行为契约 | — |  |
| 63 | `tests/test_transit_aging_346.py` | 380 | 12 | 0.02 | 1.33 | 1.37 | 真行为契约 | — |  |
| 64 | `tests/test_appointment_tenure_607.py` | 208 | 13 | 0.10 | 1.24 | 1.36 | 真行为契约 | — |  |
| 65 | `tests/test_rejection_wiring.py` | 804 | 24 | 0.74 | 0.58 | 1.32 | 真行为契约 | — | 🔒 |
| 66 | `tests/test_person_write_inventory.py` | 108 | 5 | 1.19 | 0.05 | 1.25 | 只测helper | 删 |  |
| 67 | `tests/test_new_game_smoke.py` | 166 | 7 | 0.11 | 1.12 | 1.24 | 真行为契约 | — |  |
| 68 | `tests/test_parallel_extractors.py` | 317 | 14 | 0.57 | 0.62 | 1.21 | 真行为契约 | — |  |
| 69 | `tests/test_applier_contract.py` | 389 | 23 | 0.00 | 1.14 | 1.19 | 真行为契约 | — |  |
| 70 | `tests/test_menu_lifecycle_drain_396.py` | 838 | 21 | 0.92 | 0.18 | 1.12 | 真行为契约 | — |  |
| 71 | `tests/test_event_outcome_retry.py` | 117 | 3 | 0.02 | 1.07 | 1.10 | 真行为契约 | — |  |
| 72 | `tests/test_cli_play_turn.py` | 619 | 17 | 0.05 | 0.82 | 1.03 | 真行为契约 | — | 🔒 |
| 73 | `tests/test_army_firearms.py` | 226 | 16 | 0.08 | 0.88 | 0.99 | 真行为契约 | — |  |
| 74 | `tests/test_faction_class_section_rejections.py` | 242 | 10 | 0.46 | 0.47 | 0.94 | 真行为契约 | — | 🔒 |
| 75 | `tests/test_army_maintenance_retire_173.py` | 175 | 12 | 0.12 | 0.77 | 0.91 | 真行为契约 | — |  |
| 76 | `tests/test_identity_seed_488.py` | 160 | 11 | 0.14 | 0.71 | 0.87 | 真行为契约 | — |  |
| 77 | `tests/test_junxin_alias_loyalty_313.py` | 92 | 3 | 0.02 | 0.84 | 0.86 | 真行为契约 | — |  |
| 78 | `tests/test_secret_order_injection.py` | 66 | 4 | 0.00 | 0.85 | 0.86 | 真行为契约 | — |  |
| 79 | `tests/test_relation_store_632.py` | 195 | 5 | 0.01 | 0.83 | 0.85 | 真行为契约 | — |  |
| 80 | `tests/test_office_inference.py` | 267 | 36 | 0.40 | 0.37 | 0.84 | 只测helper | 改造 |  |
| 81 | `tests/test_settle_channel_injection.py` | 167 | 5 | 0.11 | 0.69 | 0.80 | 真行为契约 | — |  |
| 82 | `tests/test_office_hedge_504.py` | 197 | 5 | 0.01 | 0.72 | 0.75 | 真行为契约 | — |  |
| 83 | `tests/test_settlement_write_guard_393.py` | 428 | 62 | 0.02 | 0.59 | 0.73 | 真行为契约 | — | 🔒 |
| 84 | `tests/test_empire_modifier_income_only_341.py` | 57 | 3 | 0.00 | 0.72 | 0.73 | 真行为契约 | — |  |
| 85 | `tests/test_fiscal_tick.py` | 177 | 61 | 0.00 | 0.59 | 0.71 | 真行为契约 | — | 🔒 |
| 86 | `tests/test_army_display_173.py` | 212 | 9 | 0.01 | 0.68 | 0.71 | 盯文 | 改造 |  |
| 87 | `tests/test_appease_mao_contract.py` | 184 | 6 | 0.03 | 0.64 | 0.68 | 真行为契约 | — |  |
| 88 | `tests/test_region_citydefense_display.py` | 47 | 5 | 0.00 | 0.65 | 0.66 | 盯文 | 改造 |  |
| 89 | `tests/test_region_cannon_delta.py` | 100 | 6 | 0.11 | 0.53 | 0.64 | 真行为契约 | — |  |
| 90 | `tests/test_featured_dossiers_494.py` | 100 | 4 | 0.02 | 0.60 | 0.64 | 盯文 | 改造 |  |
| 91 | `tests/test_enrich_list_guards.py` | 84 | 7 | 0.03 | 0.57 | 0.61 | 真行为契约 | — | 🔒 |
| 92 | `tests/test_power_section_rejections.py` | 272 | 12 | 0.22 | 0.36 | 0.60 | 真行为契约 | — | 🔒 |
| 93 | `tests/test_web_chat_serialization_393.py` | 404 | 8 | 0.19 | 0.39 | 0.59 | 真行为契约 | — |  |
| 94 | `tests/test_secret_order_section_rejections.py` | 196 | 9 | 0.26 | 0.31 | 0.57 | 真行为契约 | — | 🔒 |
| 95 | `tests/test_initiative_resolve_pairing.py` | 185 | 18 | 0.01 | 0.48 | 0.52 | 真行为契约 | — | 🔒 |
| 96 | `tests/test_advances_section_rejections.py` | 156 | 24 | 0.00 | 0.44 | 0.49 | 真行为契约 | — | 🔒 |
| 97 | `tests/test_web_llm_runtime_config.py` | 973 | 38 | 0.00 | 0.38 | 0.46 | 真行为契约 | 合并 |  |
| 98 | `tests/test_secret_order_status_cn.py` | 234 | 12 | 0.02 | 0.41 | 0.45 | 盯文 | 合并 |  |
| 99 | `tests/test_bandit_power_model_190.py` | 99 | 4 | 0.03 | 0.36 | 0.39 | 真行为契约 | — |  |
| 100 | `tests/test_chat_stream_failpaths_393.py` | 209 | 3 | 0.03 | 0.35 | 0.38 | 只测helper | 改造 |  |
| 101 | `tests/test_person_archive_schema.py` | 180 | 6 | 0.09 | 0.27 | 0.37 | 真行为契约 | — |  |
| 102 | `tests/test_six_sciences_seed_608.py` | 70 | 3 | 0.08 | 0.24 | 0.32 | 真行为契约 | — |  |
| 103 | `tests/test_region_citydefense.py` | 62 | 5 | 0.01 | 0.29 | 0.31 | 真行为契约 | — |  |
| 104 | `tests/test_adr0015_per_item_rejection.py` | 263 | 8 | 0.06 | 0.22 | 0.29 | 真行为契约 | — | 🔒 |
| 105 | `tests/test_llm_channel_config.py` | 434 | 23 | 0.00 | 0.22 | 0.27 | 真行为契约 | 合并 |  |
| 106 | `tests/test_yuan_arrival_185.py` | 213 | 2 | 0.00 | 0.22 | 0.25 | 真行为契约 | — |  |
| 107 | `tests/test_runtime_llm_config.py` | 472 | 22 | 0.00 | 0.20 | 0.24 | 真行为契约 | 合并 |  |
| 108 | `tests/test_web_budget_payload.py` | 99 | 2 | 0.01 | 0.21 | 0.22 | 真行为契约 | — |  |
| 109 | `tests/test_named_characters_seed_484.py` | 176 | 8 | 0.02 | 0.18 | 0.21 | 真行为契约 | — |  |
| 110 | `tests/test_cli_model_choices.py` | 137 | 12 | 0.00 | 0.13 | 0.15 | 真行为契约 | — |  |
| 111 | `tests/test_production_person_key_contract_558.py` | 44 | 2 | 0.00 | 0.14 | 0.14 | 真行为契约 | — |  |
| 112 | `tests/test_secret_order_refresh.py` | 49 | 1 | 0.03 | 0.11 | 0.14 | 真行为契约 | — |  |
| 113 | `tests/test_army_pay_source_prompt_contract.py` | 44 | 1 | 0.02 | 0.10 | 0.12 | 真行为契约 | — |  |
| 114 | `tests/test_web_issue_condition_display.py` | 58 | 9 | 0.00 | 0.09 | 0.11 | 盯文 | 改造 |  |
| 115 | `tests/test_minister_chat_timeout.py` | 181 | 5 | 0.02 | 0.05 | 0.08 | mock伪行为 | 改造 |  |
| 116 | `tests/test_person_archive_contract_index.py` | 233 | 7 | 0.00 | 0.06 | 0.07 | 只测helper | 改造 |  |
| 117 | `tests/test_decision_event_binding_389.py` | 64 | 6 | 0.00 | 0.06 | 0.07 | 只测helper | — |  |
| 118 | `tests/test_extractor_misroute_surface.py` | 75 | 5 | 0.00 | 0.05 | 0.06 | 只测helper | 改造 |  |
| 119 | `tests/test_llm_key_helpers.py` | 45 | 5 | 0.00 | 0.05 | 0.06 | 只测helper | 删 |  |
| 120 | `tests/test_memory_person_changes.py` | 69 | 5 | 0.00 | 0.05 | 0.06 | 盯文 | 改造 |  |
| 121 | `tests/test_load_observability.py` | 46 | 5 | 0.00 | 0.04 | 0.05 | 只测helper | 删 |  |
| 122 | `tests/test_player_payload_1022.py` | 155 | 4 | 0.00 | 0.04 | 0.05 | 真行为契约 | — |  |
| 123 | `tests/test_qualitative.py` | 28 | 3 | 0.00 | 0.02 | 0.03 | 只测helper | 删 |  |
| 124 | `tests/test_read_game_fixture.py` | 28 | 2 | 0.00 | 0.02 | 0.02 | 只测helper | 删 |  |
| 125 | `tests/test_release_bundle_assets.py` | 34 | 2 | 0.00 | 0.02 | 0.02 | 盯文 | 改造 |  |
| 126 | `tests/test_distance_matrix.py` | 81 | 4 | 0.01 | 0.00 | 0.02 | 只测helper | 删 |  |
| 127 | `tests/test_personnel_origin_prompt_558.py` | 24 | 1 | 0.00 | 0.01 | 0.01 | 盯文 | 改造 |  |
| 128 | `tests/test_suggestions_chips_527.py` | 18 | 1 | 0.00 | 0.01 | 0.01 | 只测helper | 删 |  |
| 129 | `tests/test_env_isolation.py` | 19 | 1 | 0.00 | 0.00 | 0.00 | 只测helper | — |  |

### 1.1 最慢单测 call TOP 15

| s | nodeid |
|---:|---|
| 97.85 | `tests/test_secret_order_isolation_883.py::test_976_production_extract_rush_progress_no_pure_public_pin` |
| 50.81 | `tests/test_session_cli_fallback.py::test_secret_conversation_actions_persist_complete_minister_reply[\u63d0\u4ea4\u6838\u8bae-claim]` |
| 47.86 | `tests/test_session_cli_fallback.py::test_secret_conversation_actions_persist_complete_minister_reply[\u8bb0\u8fdb\u5c55-note]` |
| 46.89 | `tests/test_session_cli_fallback.py::test_conversation_rush_skips_pending_review` |
| 46.69 | `tests/test_session_cli_fallback.py::test_non_streaming_path_surfaces_pending_action_id` |
| 46.63 | `tests/test_session_cli_fallback.py::test_non_parallel_safe_chat_serially_classifies_new_actions[\u8bf7\u53e6\u62df\u4e00\u9053\u8d48\u9655\u897f\u7684\u65e8\u3002-classified0-directive-plain]` |
| 46.26 | `tests/test_session_cli_fallback.py::test_conversation_update_lands_via_session_path` |
| 46.22 | `tests/test_session_cli_fallback.py::test_non_parallel_safe_chat_serially_classifies_new_actions[\u8bf7\u53e6\u62df\u4e00\u9053\u8d48\u9655\u897f\u7684\u65e8\u3002-classified3-directive-consort]` |
| 45.71 | `tests/test_session_cli_fallback.py::test_non_parallel_safe_chat_serially_classifies_new_actions[\u8bf7\u53e6\u62df\u4e00\u9053\u8d48\u9655\u897f\u7684\u65e8\u3002-classified2-directive-active_secret]` |
| 42.80 | `tests/test_secret_order_isolation_883.py::test_976_production_session_extract_update_withholds_oral` |
| 1.19 | `tests/test_person_write_inventory.py::test_person_write_inventory_covers_current_character_sql_writes` |
| 1.15 | `tests/test_cli_backend.py::test_codex_streaming_runner_degrades_to_oneshot_final` |
| 1.12 | `tests/test_audience_background.py::test_background_audience_recommendation_stages_candidate_snapshot` |
| 1.03 | `tests/test_web_audience_night_498.py::test_sync_advance_endpoint_does_not_stall_event_loop` |
| 0.90 | `tests/test_web_audience_night_498.py::test_asgi_hanging_chat_makes_issue_fail_closed` |

### 1.2 耗时热点结论（cProfile 实证）

单跑 `test_conversation_rush_skips_pending_review`：

```text
45.45s  session.apply_cli_conversation_actions
45.45s    cli_backend.classify_cli_action_intent
45.45s      cli_backend._run_agy
45.30s        select.poll (subprocess.communicate ×8)
```

该案只 mock 了 `extract_minister_actions`，**未** mock `classify_cli_action_intent` / `_run_agy`，
却 `monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")`，导致每次分类意图都拉起真实 agy CLI。
同类模式至少覆盖 session_cli_fallback 中 ~8 条 46–50s 案 + isolation_883 中 ~2 条 40–90s 案。

---

## 2. 五尺分类（逐文件）

五尺定义（票面/宪法 #13）：

1. **盯文** — 对自由文本/展示文案建机械依赖（改词即红）
2. **重复** — 同根问题多套夹具/多文件重叠
3. **只测 helper·内部结构** — 私有函数、常量索引、测试基建，非外部行为
4. **mock 伪行为** — mock 顶替真实调用后只断言协作/kwargs，不经真接缝
5. **真行为契约** — 经公共接缝观察外部行为（含闸类负向）

主类按该文件**主导问题**归；次类在注记。证据引具体断言行。

### 2.1 真行为契约（103 文件）

#### `tests/test_session_cli_fallback.py`
- 规模: 2923 行 / 92 案 / ~386.47s · 次类: mock伪行为 · 处置建议: **改造**
- 注: 会话 CLI 胶水真契约；但多条用例只 mock extract_minister_actions，未 mock classify_cli_action_intent → 实打 agy subprocess ~45s/案。全量 ~386s 中约 8 案即占 ~360s。
- 证据:
  - L2905-2923 test_conversation_rush_skips_pending_review：assert res['secret_order_id'] is None / status==pending_review
  - cProfile: apply_cli_conversation_actions → classify_cli_action_intent → _run_agy → subprocess.poll = 45.3s
  - L2773-2799 test_secret_conversation_actions_persist：assert payload[claim|note]==reply（~50s×2 因实打 CLI）

#### `tests/test_secret_order_isolation_883.py`
- 规模: 2093 行 / 42 案 / ~146.68s · 🔒闸类不可删 · 处置建议: **改造**
- 注: #883/#976 密令隔离闸类契约（负向案不可删）。最慢 test_976_production_extract_rush_progress ~90s：生产 extract 路径未 mock classify，实打 agy。
- 证据:
  - L1519-1581 test_976_production_extract_rush：assert pid>0 / pub_status != 'withheld'
  - L998: assert sec_status == 'withheld'
  - L1738/L2093: assert _shared_source_count(db, mid)==0

#### `tests/test_event_trigger_gate.py`
- 规模: 5908 行 / 203 案 / ~55.32s · 次类: 盯文 · 🔒闸类不可删 · 处置建议: **改造**
- 注: 203 案 5908 行。历史事件前提门——闸类主卷。setup 重（~53s）。可合并同类 gate 参数化。
- 证据:
  - L45: assert all(c.id != "__test_gated_hist__" for c in cands)
  - L2618: assert out["issue_summary"]["new_issues"][0]["rejected"] is True

#### `tests/test_conversational_draft.py`
- 规模: 1892 行 / 77 案 / ~49.26s · 次类: 盯文 · 处置建议: **改造**
- 注: 拟旨意图+pending LWW。部分 prompt 字符串盯文（L1384 【现有草案】）。
- 证据:
  - L102: assert len(pend)==1
  - L1384: assert "【现有草案】原始草稿：清查粮饷。" in captured["draft_prompt"]
  - L1892: assert sess.last_decree == "诏书：保留有效稿"

#### `tests/test_decree_dossiers_571.py`
- 规模: 3412 行 / 172 案 / ~36.88s · 🔒闸类不可删
- 注: 172 案 dossier 生命周期主契约；raises=37 负向丰富。
- 证据:
  - L34: `assert len(people) == count`
  - L903: `assert dossier["executor_id"] == (assignee if expected_executor_kind else "")`
  - L1856: `assert db.list_pending_actions(state.turn) == []`

#### `tests/test_character_knowledge_489.py`
- 规模: 993 行 / 52 案 / ~35.03s · 次类: 重复 · 🔒闸类不可删 · 处置建议: **合并**
- 注: #489 主卷（52 案 ~35s）。与 test_knowledge 合并时以本文件为锚，迁入 archive 独有案后删 knowledge 重复面。
- 证据:
  - L20: assert all(name not in roster for name in names)
  - L255: assert "礼部本职所涉" not in view["personnel"]
  - L675: assert excluded.office == "礼部尚书"

#### `tests/test_fiscal_substrate_bridge.py`
- 规模: 5333 行 / 184 案 / ~34.21s · 次类: 盯文 · 🔒闸类不可删 · 处置建议: **改造**
- 注: 184 案 5333 行 ~34s。桥+seed 真契约；中文 assert 多（cnA=311）但多为账户名/字段键。可瘦身重复 seed 变体。
- 证据:
  - L108: assert settle["p"]["Due"]["宗禄"] == pytest.approx(...)
  - L4202: assert isinstance(settle, dict)
  - raises=26 负向 fail-loud

#### `tests/test_person_delta_adapter.py`
- 规模: 4135 行 / 126 案 / ~18.00s · 次类: 盯文 · 🔒闸类不可删
- 注: ADR0009 person delta 主卷 126 案。中文状态/官职枚举多。
- 证据:
  - L48: `assert normalize_person_changes(extracted) == [`
  - L1010: `assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs + 2`
  - L2110: `assert row["transit_to"] == "liaodong"`

#### `tests/test_pending_actions.py`
- 规模: 2493 行 / 80 案 / ~16.35s · 🔒闸类不可删
- 注: ADR0006 动作闸门主契约。
- 证据:
  - L104: `assert row["title"] == "原标题"`
  - L619: `assert db.withdraw_pending_action(pending_id, state.turn) is True`
  - L1282: `assert failures[0]["retryable"] is True`

#### `tests/test_decree_commitment_settlement_229.py`
- 规模: 1651 行 / 34 案 / ~14.48s
- 证据:
  - L24: `assert row is not None`
  - L501: `assert _issue_row(db, open_issue_id)["status"] == "active"`
  - L795: `assert _army_arrears(db, "guanning") == 150`

#### `tests/test_decree_commitment_creation_136.py`
- 规模: 1221 行 / 33 案 / ~9.42s
- 证据:
  - L68: `assert created["rejected"] is False`
  - L376: `assert created["category"] == "invalid_enum"`
  - L619: `assert created["category"] == "invalid_enum"`

#### `tests/test_fiscal_levy_effect.py`
- 规模: 1394 行 / 49 案 / ~9.32s
- 证据:
  - L73: `assert math.isclose(settle["p"]["三饷应征"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)`
  - L393: `assert math.isclose(`
  - L816: `assert after["p"] == before["p"]`

#### `tests/test_dossier_links_559.py`
- 规模: 589 行 / 42 案 / ~9.09s
- 证据:
  - L34: `assert [row["target_dossier_id"] for row in db.list_dossier_links(protection)] == targets`
  - L176: `assert other_secret["id"] not in visible_ids`
  - L414: `assert len(db.list_secret_orders()) == before_orders`

#### `tests/test_mindreading_491.py`
- 规模: 302 行 / 14 案 / ~7.90s
- 注: #491 近臣读心：独立生成、定性输入与流水线边界。
- 证据:
  - L46: `assert is_inner_court_attendant(wang)`
  - L98: `assert agent.db is None`
  - L149: `assert "工心计" in material["底案"]`

#### `tests/test_issue_entities.py`
- 规模: 595 行 / 32 案 / ~7.30s · 🔒闸类不可删
- 注: 国策结案实体后果 + 全局严格(不静默)。  覆盖 issues._apply_issue_entities 与底层 apply： - 建军 / 补兵 / 人物状态(死/流放/下狱) 真落库 - 非法 delta 抛错中断，绝不静默跳过（用户拍板的全局严格·选项1）
- 证据:
  - L44: `assert _army_count(db) == before + 1`
  - L162: `assert content.characters[name].status == "dismissed"`
  - L271: `with pytest.raises(ValueError):`

#### `tests/test_faction_leverage_9.py`
- 规模: 1258 行 / 37 案 / ~7.23s
- 注: #9：派系势力(faction leverage) 随「在朝成员官职权重」全重算联动。  修前 set_character_status 不动 leverage、character_status_changes 与派系势力无联动， 实测阉党三核心(田尔耕/崔呈秀/王体乾)退场后 leverage 仍挂 78(全场第一)
- 证据:
  - L34: `assert row is not None, "阉党需有握高权官(内阁/司礼监/吏部/兵部)的在朝核心"`
  - L343: `assert db.conn.execute(`
  - L569: `assert _office_rank_multiplier("游击") == 0.25`

#### `tests/test_promulgation_judge_561.py`
- 规模: 699 行 / 38 案 / ~6.66s · 🔒闸类不可删
- 注: 【闸类/负向契约——不可删】
- 证据:
  - L28: `assert context == decree_mod.build_promulgation_judge_context(`
  - L131: `with pytest.raises(decree_mod.LLMContractError, match="颁布判官 verdicts 必须为列表"):`
  - L343: `assert len(calls) == 1`

#### `tests/test_multi_directive_502.py`
- 规模: 671 行 / 18 案 / ~6.62s
- 注: 多道圣旨独立成条（issue #502，ADR 0006/0038/0049）。  外部行为契约：一夜之内皇帝分别请大臣拟数道**各自独立**的旨，每道旨自成一条 候选（独立 pending_actions(kind=directive) 行、各自正文），不被并进同一条圣旨。 对现有草案的**补充/修改**仍原地更新那
- 证据:
  - L133: `assert len(pending) == 1`
  - L253: `assert {`
  - L406: `assert _approved_directive_ids(db, nid) == {id_a}`

#### `tests/test_driver.py`
- 规模: 592 行 / 35 案 / ~6.51s · 🔒闸类不可删
- 注: s1 (#10) — driver.run_settle：探针确定性结算入口。  run_settle 收一份**中文 schema 形态**的稀疏 delta（我在对话里产的形态）， 规范化 → pre_settle → settle_with_delta，推进一回合。CLI 子命令是它的薄壳。  注：本文件断言 t
- 证据:
  - L33: `assert driver.main(["settle", "--delta", str(bad)], game=game) == 1`
  - L140: `assert new_unrest == old_unrest + 5`
  - L347: `assert state.turn == before + 1`

#### `tests/test_event_chain_cascade.py`
- 规模: 360 行 / 16 案 / ~5.36s
- 注: #195：历史事件链终态后的级联作废。
- 证据:
  - L57: `assert row is not None`
  - L129: `assert db.conn.execute(`
  - L201: `assert _terminal_state(db, downstream.id) == (`

#### `tests/test_db_broad_except_surface.py`
- 规模: 197 行 / 8 案 / ~5.08s
- 注: #14 调试盲区：db.py 的静默 `except Exception:` JSON 回退路加 tlog 留痕。  契约（行为不变 + 可观测）：当某列存的 JSON 损坏时——   1) 回退行为保持原样（默认回空 / 跳过该项），不抛、不崩；   2) **同时** 经 tlog 响亮留痕（不再静默吞，给调试一条
- 证据:
  - L39: `assert len(out) == 1`
  - L79: `assert ctx is not None`
  - L122: `assert ctx is not None`

#### `tests/test_error_pack.py`
- 规模: 434 行 / 18 案 / ~4.75s · 🔒闸类不可删
- 注: S6 (ADR 0008 PR1) — extractor 失败响亮中止 + 错误包。  决定 3（:406 改响亮中止）：extractor 抛错不再 extracted={} 静默续跑——上抛 SettlementAbort， 回合不推进、无落库。决定 6/7：自动落错误包到 user-data 目录（traceb
- 证据:
  - L44: `with pytest.raises(SettlementAbort) as ei:`
  - L106: `assert db.get_turn_report(before) == ""`
  - L197: `assert ctx["narrative"] == "n"`

#### `tests/test_audience_background.py`
- 规模: 744 行 / 22 案 / ~4.66s
- 证据:
  - L150: `assert isinstance(accepted, dict)`
  - L261: `assert pending_payload.get("mode", "ordinary") == expected_mode`
  - L469: `assert "近臣查访" in prompt`

#### `tests/test_audience_extraction_501.py`
- 规模: 713 行 / 34 案 / ~4.59s · 🔒闸类不可删
- 注: #501 叙事抽取落账（站台落账 / 补跑抽取 / 响亮错误包 / 收夜前清空待补）。  外部行为契约（PRD #497「restore·崩溃一致性」「召对退出」「抽取链边界」；ADR 0035/0036）： - 含站台情节的回话跑完 → 账上有该条（涉及人 / 可闻性正确），涉在场变化带机器可读在场效果； - 注入垃
- 证据:
  - L87: `assert len(facts) == 1`
  - L198: `assert [e for e in an.list_ledger(db, nid) if e["source_chat_turn_id"] == ctid] == []`
  - L374: `assert ei.value.error_pack_path`

#### `tests/test_pre_settle_transaction.py`
- 规模: 504 行 / 18 案 / ~4.57s · 🔒闸类不可删
- 注: S4 — pre_settle 自成事务 + settling 完成相位 + begin_turn 白名单（ADR 0008 决定 3 第二条）。  pre_settle（暂存动作 commit + 固定财政 + auto_trigger + auto_submit_due_secret_orders） 整体包成自己的 【闸类/负向契约——不可删】
- 证据:
  - L39: `assert isinstance(auto, list)`
  - L143: `assert not db.conn.in_transaction`
  - L241: `assert state.turn == turn  # 未推进`

#### `tests/test_decree_commitment_schema_136.py`
- 规模: 349 行 / 34 案 / ~4.16s
- 证据:
  - L32: `assert "end_turn" in cols`
  - L107: `assert dict(log) == {"old_value": building["name"], "field": "remove"}`
  - L189: `assert row["commitment_kind"] == "until_stop"`

#### `tests/test_recommendations.py`
- 规模: 323 行 / 14 案 / ~4.10s
- 注: #493 大臣荐人：网络/见闻裁切与采纳后的可恢复荐人事件。
- 证据:
  - L28: `assert same_faction.name in names`
  - L147: `assert candidate.name not in names`
  - L227: `assert "list_recommendable_persons" not in tools`

#### `tests/test_resolve_context_recovery.py`
- 规模: 378 行 / 16 案 / ~4.03s
- 注: S2+S3 (ADR 0008 PR1) — resolve_context 无条件持久化 + validate 前置 + 事务内清理。  重跑契约第一件：每回合进入结算后半段前必存 resolve_context（extractor delta + 叙事）， 持久化前先过 validate_delta_shape（毒
- 证据:
  - L28: `assert ctx is not None`
  - L111: `assert db.get_resolve_context(turn) is not None`
  - L172: `assert ctx["extracted"] is None  # phase1 占位，判别位 ready=0 → 不可见`

#### `tests/test_advance_paths_atomic.py`
- 规模: 1412 行 / 35 案 / ~3.97s · 🔒闸类不可删
- 注: S7 (ADR 0008 PR1) — 三条推进回合写路径统一 atomic 事务包裹 + 恢复入口消费。  决定 2：任何推进回合的写序列(正常 settle / simulator-fallback / advance_without_edict) 全有或全无——整体包 atomic，崩在中途整体回滚、内存从 DB 【闸类/负向契约——不可删】
- 证据:
  - L58: `with pytest.raises(RuntimeError, match="advance boom"):`
  - L356: `assert result.awaiting is False`
  - L652: `assert event_id not in I._event_trigger_refs(db), (`

#### `tests/test_beat_orchestration_503.py`
- 规模: 518 行 / 17 案 / ~3.85s
- 注: #503 开场/收夜 beat 编排——输入路由 / 零形式约束传递 / P4 不喂 / 见闻供给接口。  seam： - assemble_beat_inputs（输入路由的公开边界，断言输入面：AC2/AC4/AC5 审计）； - 真实召对会话入口 attach_chat_turn_to_night + close
- 证据:
  - L100: `assert body_a and body_b`
  - L170: `assert calls["n"] == 0`
  - L258: `assert a in body_a and b in body_b`

#### `tests/test_effect_origin_558.py`
- 规模: 390 行 / 13 案 / ~3.83s
- 证据:
  - L32: `assert state.metrics["国库"] == before`
  - L128: `assert (row["bar_value"], row["status"]) == (51, "active")`
  - L254: `assert result["applied_person_changes"][0]["origin_ref"] == origin_ref`

#### `tests/test_web_audience_night_498.py`
- 规模: 471 行 / 7 案 / ~3.81s · 次类: 重复 · 处置建议: **合并**
- 注: 与 test_audience_night_498 同根 #498；本文件走 ASGI/web 接缝，core 文件走 engine。可保留分层但应去重交叉断言。
- 证据:
  - web L194: test_asgi_inflight_reply_lands_then_issue_closes_and_advances
  - core L94: test_open_summon_close_chain_readable_by_night
  - 两者均覆盖 advance/close 夜链路

#### `tests/test_promulgation_seam_560.py`
- 规模: 579 行 / 28 案 / ~3.62s · 🔒闸类不可删
- 注: 【闸类/负向契约——不可删】
- 证据:
  - L17: `assert stub_promulgation_verdicts(dossiers, state) == [`
  - L162: `with pytest.raises(SettlementAbort) as exc_info:`
  - L302: `assert db.list_decree_dossier_decisions(second_id) == []`

#### `tests/test_chat_mutations_freeze.py`
- 规模: 181 行 / 6 案 / ~3.34s · 🔒闸类不可删
- 注: PR #90 R2 codex P2——恢复窗（FRONT_HALF_DONE）冻结聊天侧全部即时写路。  draft 提案早已堵在源头（_proposal_blocked），但任免落地、史实人物补档、密令工具、 CLI 前缀密令 upsert 仍可在 settling/awaiting_decision 直写 DB/ 【闸类/负向契约——不可删】
- 证据:
  - L46: `assert (appointed, displaced) == ("", "")`
  - L79: `assert "__secret_order_registered__" not in out  # 未登记`
  - L105: `assert payload["action"] == "记进展"`

#### `tests/test_secret_order_monthly_progress_566.py`
- 规模: 714 行 / 24 案 / ~3.24s · 🔒闸类不可删
- 注: #566: production settlement owns the durable monthly progress rail.
- 证据:
  - L130: `assert private_contexts[0]["monthly_dossier_reports"][0]["progress"] == []`
  - L270: `assert db.get_decree_dossier(chained_dossier)["status"] == "closed"`
  - L384: `assert db.conn.execute(`

#### `tests/test_new_issues_section_rejections.py`
- 规模: 516 行 / 42 案 / ~3.07s · 🔒闸类不可删
- 注: #63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 new_issues 段 insert 路迁逐项拒收。  原先：db.insert_issue 连同内联 int()/dict()/list() 强转一起裹在 `try: ... except Except 【闸类/负向契约——不可删】
- 证据:
  - L123: `assert same_id_events == [replacement]`
  - L198: `assert len(created) == 1, out  # 不 abort、照常落库`
  - L295: `assert rej[0]["category"] == "invalid_enum"`

#### `tests/test_transaction_boundary.py`
- 规模: 581 行 / 27 案 / ~2.91s · 🔒闸类不可删
- 注: S1 — ming_sim/applier.py 事务包裹 + commit 暂停（ADR 0008 决定 2/8）。  覆盖 atomic contextmanager 的原子语义：暂停期 commit 变 no-op、正常退出真 commit、 异常回滚 + 透传、嵌套 flat 语义、暂停期 rollback 仍 【闸类/负向契约——不可删】
- 证据:
  - L23: `assert row is not None`
  - L179: `assert db.conn.in_transaction`
  - L272: `with pytest.raises(RuntimeError):`

#### `tests/test_near_minister_reports_492.py`
- 规模: 220 行 / 17 案 / ~2.59s
- 注: #492 督抚官缺与近臣回奏的外部 seam。
- 证据:
  - L13: `assert {"陕西巡抚", "三边总督"} <= vacancies.keys()`
  - L71: `assert report["statement"]`
  - L101: `assert bandits["statement"] == "流寇势弱"`

#### `tests/test_section_fiscal_rejections.py`
- 规模: 750 行 / 44 案 / ~2.48s · 🔒闸类不可删
- 注: PR2-S3(ADR 0008 决定 1,#91)——apply_score_extraction 的 fiscal 三段迁拒收契约。  fiscal_removes / fiscal_creates / fiscal_changes 三段原先 LLM 脏项要么 print 静默跳、 要么静默归 0/continue。 【闸类/负向契约——不可删】
- 证据:
  - L56: `assert len(rows) == 1`
  - L224: `assert len(rows) == 1`
  - L389: `assert cfg[key] == before_human`

#### `tests/test_audience_scroll_539.py`
- 规模: 416 行 / 18 案 / ~2.43s
- 注: Issue #539: night-scroll read contract at the audience-night public seam.
- 证据:
  - L55: `assert response.headers["content-type"].startswith("text/event-stream")`
  - L134: `assert message["chat_turn_id"] > 0`
  - L219: `assert aside["content"] == "万岁爷，他这话留了半分。"`

#### `tests/test_audience_undo_506.py`
- 规模: 585 行 / 17 案 / ~2.39s
- 注: #506 撤回本轮效果逆转（轮级撤销日志 / 白名单审计，ADR 0038 cmr R1 修订版）。  一条贯穿真实入口：召对夜里一「轮」= 一次玩家发话到下一次发话的完整交换，落为一条 `chat_turns` 行。生产走 `capture_chat_rollback_snapshot`（轮前）→ 该轮全部写入 → 
- 证据:
  - L108: `assert any(e["source_chat_turn_id"] == chat_id for e in an.list_ledger(db, night_id))`
  - L211: `with pytest.raises(AudienceNightError) as ei:`
  - L334: `assert db.conn.execute("SELECT COUNT(*) FROM secret_orders").fetchone()[0] == 1`

#### `tests/test_section4_rejections.py`
- 规模: 758 行 / 47 案 / ~2.35s · 🔒闸类不可删
- 注: PR2-S2(ADR 0008 决定 1,#91)——section 4 三条裸奔路迁入逐项拒收契约。  section 4 的 create_armies_from_extraction(new_armies)、apply_region_deltas (region_delta)、apply_army_deltas( 【闸类/负向契约——不可删】
- 证据:
  - L36: `assert row is not None`
  - L182: `assert "public_support" in log_fields`
  - L346: `assert len(rows) == 1`

#### `tests/test_audience_night_498.py`
- 规模: 637 行 / 17 案 / ~2.19s · 次类: 重复 · 🔒闸类不可删
- 注: #498 夜宴引擎主契约。
- 证据:
  - L94 open_summon_close 链
  - L243 advance_without_edict_auto_closes

#### `tests/test_audience_restore_505.py`
- 规模: 506 行 / 13 案 / ~2.13s
- 注: #505 [S4] 续夜 restore：重开回到最后一条持久化对话轮续夜（ADR 0036）。  一条贯穿真实入口→DB 末态的 tracer：用生产 seam（open_night / attach_chat_turn_to_night / append_chat_message）造出「回话生成半途被 kill」的
- 证据:
  - L113: `assert ledger_after == ledger_before`
  - L216: `assert "臣愚见如此。" in [m["content"] for m in proj if m["role"] == "minister"]`
  - L340: `assert db.conn.execute(`

#### `tests/test_audience_pipeline_499.py`
- 规模: 528 行 / 13 案 / ~2.00s
- 注: #499 P5 时序编排：回话流式 / 读心流水线 / 回奏并行。  时序契约（PRD #497 接缝义务②）： - 回话流式可见；首 token 先于读心 - 读心必串于回话完成+持久化之后；输入含完整回话 - 投毒：回话未完即发读心、只喂问句 → 被咬住 - 不依赖回话的真实调用经生产入口并发发出 - 回话 don
- 证据:
  - L30: `assert mindreading_eligible(db, content.characters, target) == wang`
  - L142: `assert "军务如何？" not in seen_replies[0]`
  - L303: `assert _wait_for(lambda: db.get_mindreading_status(cid) == "failed")`

#### `tests/test_secret_order_update.py`
- 规模: 179 行 / 12 案 / ~1.96s
- 注: 密令更新路径：同一承办大臣再次下密令 = 更新其要旨，而非建重复条。  补 toolcall 缺口——CLI 后端无 function-calling，原 report/update 密令工具失效， 「补充/更新已有密令」无路径。db.upsert_secret_order 提供 create-or-update。
- 证据:
  - L31: `assert db.update_secret_order_by_id(`
  - L51: `assert "改" in row["title"]`
  - L97: `assert db.update_secret_order_by_id(state, oid, title, body)`

#### `tests/test_audience_presence_500.py`
- 规模: 403 行 / 14 案 / ~1.95s
- 注: #500 在场推导与进出账——真实 GameDB + 真实 content 语境的进出账 → 在场末态。  一条外部行为契约：进出账（入殿/告退/传召在途）经确定性推导器得出「任一时刻 谁在场」，以及侍立区间可闻性取数。真实 open_night 落常在员额（王承恩），真实 summon_enter 落入殿账；断言推导
- 证据:
  - L51: `assert {"毕自严", "王绍徽", STANDING} <= before`
  - L124: `assert TAG_EXIT in last["tags"] and character.name in last["person_names"]`
  - L227: `assert minister.name in an.present_names_at(db, nid)`

#### `tests/test_close_issues_section_rejections.py`
- 规模: 202 行 / 19 案 / ~1.92s · 🔒闸类不可删
- 注: #63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 close_issues 段迁逐项拒收契约。  原先：坏 issue_id 静默 continue、坏 reason print[WARN]+continue、close_issue 抛异常 print[W 【闸类/负向契约——不可删】
- 证据:
  - L37: `assert len(rej) == 1`
  - L62: `assert rej[0]["category"] == "invalid_enum"`
  - L99: `assert rej[0]["category"] == "missing_ref"`

#### `tests/test_web_court_visibility.py`
- 规模: 449 行 / 22 案 / ~1.81s
- 注: #104: 朝堂大臣列表按 DB 权威状态过滤 offstage（离场/未登场不入列）。  回归要点：过滤须用 db.get_character_status（DB 权威），**不能用内存 c.status**—— auto-debut 等路径（db.set_character_status）只写 DB、不回写内存，c
- 证据:
  - L30: `assert visible_in_court(content.characters[name], db) is True`
  - L139: `assert db.get_character_status(name)[0] == "offstage"  # 物化后 setup 真生效`
  - L241: `assert db.get_character_status(consort)[0] == "active"`

#### `tests/test_economy_section_rejections.py`
- 规模: 219 行 / 11 案 / ~1.81s · 🔒闸类不可删
- 注: economy_moves 段迁入逐项拒收契约（ADR 0008 决定 1，#14 economy 残留 / ADR 0012）。  原先 `_clean_economy_moves`（cleaner，pre-apply）与 `_apply_economy_list`（applier）对 非法 account（∉国库/ 【闸类/负向契约——不可删】
- 证据:
  - L46: `assert len(rows) == 1, rows`
  - L75: `assert _rejection_rows(db, turn, ECO_REJ) == []`
  - L146: `assert _rejection_rows(db, turn, ECO_REJ) == []`

#### `tests/test_audience_continuous_507.py`
- 规模: 236 行 / 8 案 / ~1.79s
- 注: #507 连场编排——presence-aware 组装：谁在场听到了什么，区间事实送对。  一条外部行为契约：连场一夜里，对话流按在场名单送入组装——侍立者的补话组装输入 含其在场时段殿上公开对话（AC2 区间取数），未在场者的组装输入不含殿内对话（AC3）， 且回奏输入按角色见闻分流（AC4，千人千答非旧询问机制）
- 证据:
  - L67: `assert "徐光启奏：宜用洪承畴督师陕西。" in recap`
  - L109: `assert "徐光启奏：宜用洪承畴督师陕西。" in prompt_present`
  - L145: `assert {"毕自严", "徐光启", "洪承畴", "王绍徽", STANDING} <= final`

#### `tests/test_state_reload.py`
- 规模: 369 行 / 15 案 / ~1.79s · 🔒闸类不可删
- 注: S5 — 内存态与 DB 同源恢复（ADR 0008 决定 3 第三条）。  DB 回滚不还原内存副作用（state.metrics 直加 flows.py:192、turn_phase、next_period）。 回滚后重跑前把 state 从 DB 重载（与 restore/load_state 同路径），原地刷新
- 证据:
  - L48: `assert state.turn_phase != "reviewing"`
  - L102: `assert db_phase != "settling"`
  - L172: `assert db.conn.execute(`

#### `tests/test_rescript_choices_563.py`
- 规模: 272 行 / 13 案 / ~1.75s
- 证据:
  - L56: `with pytest.raises(RuntimeError, match="tracer stop"):`
  - L119: `assert dossier_decisions == {"withdrawn", "hold"}`
  - L180: `assert len(dossiers) == 1`

#### `tests/test_army_salary_44.py`
- 规模: 351 行 / 24 案 / ~1.73s
- 注: #44：军饷应发挂钩兵力（设计 v2）——军存每军 salary_rate（两/兵·月）， 应发 needed(万两) = ceil(manpower × salary_rate / 10000)，仅 owner_power=='ming'。 0 兵 → 0 饷（消解白嫖扩军上界 + 零兵吃饷下界）。扩军只落 manp
- 证据:
  - L44: `assert army_needed(_army_row(db, army_id)) == expected`
  - L131: `assert row["salary_rate"] == pytest.approx(SALARY_RATE_ANCHOR), (`
  - L254: `assert row["arrears"] == pytest.approx(10)`

#### `tests/test_office_rank_562.py`
- 规模: 421 行 / 18 案 / ~1.61s
- 证据:
  - L44: `assert {row["type"] for row in table["priority"]} | {table["fallback"]["type"]} == set(table["allowed_types"])`
  - L147: `assert big["break_rank"]["basis"] == "historical_office"`
  - L198: `assert office_rank_band("文华殿大学士") == 5`

#### `tests/test_action_cluster_registry_515.py`
- 规模: 637 行 / 16 案 / ~1.52s
- 注: #515 S0：动作分类器扩展挂点 + 识别兜底 + 脚本化判词契约。  Seams: - ACTION_CLUSTERS 唯一登记（含 materialize_fn / FieldSpec） - run_materialize_pipeline / session.chat / WebGame.chat+undo_l
- 证据:
  - L54: `assert _EXPECTED_MIGRATED_KINDS <= registered`
  - L130: `assert int_specs, "catalog must expose a clamped int FieldSpec"`
  - L246: `assert payload.get("name") == "测试候选人甲"`

#### `tests/test_character_projection_1023.py`
- 规模: 78 行 / 2 案 / ~1.50s
- 注: #1023 player-facing LLM inputs share the qualitative character projection.
- 证据:
  - L36: `assert character.name in rendered`
  - L41: `assert row["党派认同"] == "党色极深"`
  - L51: `assert "胆略敢任其事" in character_rendered`

#### `tests/test_settle_core.py`
- 规模: 386 行 / 11 案 / ~1.38s
- 注: s1 (#10) — 确定性结算核 settle_with_delta / pre_settle 的行为测试。  settle_with_delta 是从 decree._settle_after_narrative 抽出的「后括号」： 收一份已规范化的 extracted delta → 落库 → inertia →
- 证据:
  - L37: `assert state.turn == before_turn + 1`
  - L153: `assert f"settlement:narrative:{before_turn}" not in by_source`
  - L235: `assert "公开结算标记" in excluded_text`

#### `tests/test_transit_aging_346.py`
- 规模: 380 行 / 12 案 / ~1.37s
- 注: #346 transit-aging 兜底：≤2月强制到任 + transit_start_turn 计时。  覆盖： 1. 在途 ≥2 月 → force_transit_arrivals 强制到任（location=transit_to, transit_to=''） 2. 在途 0 月（刚启程）→ 不强制 3. 
- 证据:
  - L45: `assert name in names`
  - L95: `assert row["transit_to"] == DEST, "1 月在途，transit_to 不应被清"`
  - L159: `assert row["transit_start_turn"] == state.turn, (`

#### `tests/test_appointment_tenure_607.py`
- 规模: 208 行 / 13 案 / ~1.36s
- 证据:
  - L50: `assert json.loads(dossier["payload_json"])["任别"] == tenure`
  - L98: `assert rejected["rejected"] is True`
  - L150: `assert dict(db.conn.execute(`

#### `tests/test_rejection_wiring.py`
- 规模: 804 行 / 24 案 / ~1.32s · 🔒闸类不可删
- 注: PR2-S0(ADR 0008 决定 5/8,#91)——拒收收集器接进结算管线。  生命周期与事务对齐:apply 产生的拒收项 → 事务内 flush 进 rejection_reports → commit 成功后镜像 jsonl → 回滚路 reset 不留行不留镜像。attempt 从错误目录推导 (不从 D 【闸类/负向契约——不可删】
- 证据:
  - L41: `assert len(rows) == 1`
  - L183: `assert len(rows) == 1`
  - L387: `assert row["category"] == "missing_field"`

#### `tests/test_new_game_smoke.py`
- 规模: 166 行 / 7 案 / ~1.24s
- 注: 新档冒烟（#96 release 清单 / #92 E2E 确定性核）：开新档 → driver.run_settle 跑 3 回合全链 （pre_settle 固定财政 tick → settle_with_delta 落库/inertia/结局/推进，同真实核 ADR 0004）→ restore 接续。含 #66
- 证据:
  - L60: `assert isinstance(settle, dict) and "st" in settle and "p" in settle, \`
  - L76: `assert sess.db.conn.execute(`
  - L129: `assert office["office_type"] == character["office_type"]`

#### `tests/test_parallel_extractors.py`
- 规模: 317 行 / 14 案 / ~1.21s
- 注: #83：月末 4 个 extractor 串行改并行（仅 CLI 后端）。  并行只动 LLM 调用阶段（run_agent_text ×4，互不依赖）；解析/sanitizer/合并仍串行按模块顺序， 输出与串行版语义一致。落库在本函数之外、仍串行单事务（ADR 0008）。形态1/api 后端串行不变。
- 证据:
  - L45: `assert serial[0] == parallel[0]      # merged dict 一致`
  - L110: `assert any("同源同额承诺重复" in str(r.get("reason", "")) for r in rejections)`
  - L196: `assert max_active == 1, f"串行路径出现并发，峰值={max_active}"`

#### `tests/test_applier_contract.py`
- 规模: 389 行 / 23 案 / ~1.19s
- 注: S0 — ming_sim/applier.py 契约类型骨架测试。  覆盖：Provenance 枚举 / RejectedItem / SectionResult 聚合 / ApplyContext / RejectionCollector 缓冲→flush_to_db / mirror_to_jsonl。
- 证据:
  - L18: `assert Provenance.player_decree.value == "player_decree"`
  - L70: `assert len(r.rejected) == 1`
  - L156: `assert rows[0][1] == "军队 id 不存在"`

#### `tests/test_menu_lifecycle_drain_396.py`
- 规模: 838 行 / 21 案 / ~1.12s
- 注: #396: menu lifecycle endpoints must drain in-flight writes before closing DB sessions.
- 证据:
  - L40: `assert not done.wait(0.2)`
  - L219: `assert os.environ["MING_SIM_DB"] == old_db_path`
  - L400: `assert not done.wait(0.3)`

#### `tests/test_event_outcome_retry.py`
- 规模: 117 行 / 3 案 / ~1.10s
- 证据:
  - L59: `assert extracted["事件结局"] == {"jisi_lubian": "入塞被遏"}`
  - L63: `assert agents[module].calls == 1`
  - L87: `assert extracted["事件结局"] == {"jisi_lubian": "入塞被遏"}`

#### `tests/test_cli_play_turn.py`
- 规模: 619 行 / 17 案 / ~1.03s · 🔒闸类不可删
- 注: PR #90 R1 gemini medium——issue 分支拒绝后留在回合交互循环（continue 不 return）。  return 会退出 play_turn，外层主循环重进时重印回合引导/在册大臣=刷屏；skip 分支 已是 continue，issue 分支的 ValueError/Settlemen
- 证据:
  - L72: `assert sess.calls == ["begin", "resolve", "advance"]`
  - L235: `with pytest.raises(KeyboardInterrupt):`
  - L364: `assert db.conn.execute(`

#### `tests/test_army_firearms.py`
- 规模: 226 行 / 16 案 / ~0.99s
- 注: 火器装备 / 大炮装备 两条军备轴（数据字段，供 simulator 软判，代码不硬算）。  火器装备：鸟铳/三眼铳——野战齐射 + 守城皆宜（0-100 状态轴）。 大炮装备：红夷炮——守城/攻城神器，笨重不利野战（随军门数，clamp 0-12；城防炮另挂 region.cannon）。 simulator 看得见
- 证据:
  - L26: `assert "firearm_equipment" in ARMY_SCORE_FIELDS`
  - L62: `assert row["cannon_equipment"] == 10  # 随军炮 10 门(在 0-12 内)`
  - L127: `assert "火器" in rpt`

#### `tests/test_faction_class_section_rejections.py`
- 规模: 242 行 / 10 案 / ~0.94s · 🔒闸类不可删
- 注: faction_delta / class_delta 两段迁入逐项拒收契约（ADR 0008 决定 1，#14/#63）。  原先 `db.adjust_factions`/`adjust_classes` 对查无此派系/阶级名 `if not row: continue` 零痕迹静默丢（#63 死法 3、#14 模 【闸类/负向契约——不可删】
- 证据:
  - L25: `assert row is not None, "probe.db 需至少一个派系"`
  - L83: `assert rows[0][2] == "missing_ref"`
  - L120: `assert _class_satisfaction(db, good) == before`

#### `tests/test_army_maintenance_retire_173.py`
- 规模: 175 行 / 12 案 / ~0.91s
- 注: #173：物理移除退役的 armies.maintenance_per_turn 列。月饷由 army_needed(按兵力派生)唯一承载。  本文件验删列后的契约——维护费彻底不再是字段：   · schema 无该列；   · 建军唯一必填=manpower（维护费键给了也当未知键忽略；inf 等极值不崩建军）； 
- 证据:
  - L45: `assert "maintenance_per_turn" not in cols, "维护费列应已物理删除"`
  - L83: `assert not created[0].get("rejected"), f"drop 后建新军 INSERT 应成功不崩：{created[0]}"`
  - L108: `assert not created[0].get("rejected"), f"塞维护费键不应拒整军：{created[0]}"`

#### `tests/test_identity_seed_488.py`
- 规模: 160 行 / 11 案 / ~0.87s
- 证据:
  - L17: `assert row["faction"] == "皇党"`
  - L43: `assert dict(after) == dict(before)`
  - L74: `assert json.loads(inserted["seed_guilt"]) == content.characters["王承恩"].seed_guilt`

#### `tests/test_junxin_alias_loyalty_313.py`
- 规模: 92 行 / 3 案 / ~0.86s
- 注: #313 — 中文「军心」别名 morale→loyalty（ADR 0025 D1 附带必修）。  验收（纯单元，extractor delta 别名落库 seam）： - army_delta 含「军心」key → 落 army.loyalty，不碰 morale - army_delta 含「士气」key → 仍
- 证据:
  - L38: `assert before["morale"] == 50`
  - L50: `assert after["loyalty"] == 58, "军心 must map to loyalty (ADR 0025 D1 / #313)"`
  - L62: `assert before["loyalty"] == 50`

#### `tests/test_secret_order_injection.py`
- 规模: 66 行 / 4 案 / ~0.86s
- 注: #108：密令注入月末推演时 pending_review 全进，不被满载 active 的整体 [:cap] 截断饿死。  pending_review = 到期密令，本回合必须给 done/failed 裁决；被截断会永久卡住不结案。 旧码 `(active + pending_review)[:20]` 在 ac
- 证据:
  - L28: `assert "待核议令甲" in titles, "pending_review 被满载 active 饿死（#108）"`
  - L29: `assert sum(1 for o in sel if o["status"] == "pending_review") == 1`
  - L51: `assert len(sel) == 20`

#### `tests/test_relation_store_632.py`
- 规模: 195 行 / 5 案 / ~0.85s
- 证据:
  - L31: `assert forward_id != reverse_id`
  - L41: `with pytest.raises(ValueError, match="未知边事件类目"):`
  - L118: `assert [(edge["source"], edge["target"]) for edge in edges] == [`

#### `tests/test_settle_channel_injection.py`
- 规模: 167 行 / 5 案 / ~0.80s
- 注: 通道 enrichment 经 settle_with_delta 的注入闭包回归（ADR-0004 一致）。  base 的 ADR-0004 把月末结算抽成「不依赖 llm_config 的确定性核 settle_with_delta + 注入闭包（chapter_recorder / ending_summari
- 证据:
  - L85: `assert row is not None`
  - L88: `assert chapter_calls[0][0][0] is chapter_agent`
  - L109: `assert _j.loads(row["effect_on_resolve"]) == {}`

#### `tests/test_office_hedge_504.py`
- 规模: 197 行 / 5 案 / ~0.75s
- 注: #504 / ADR 0028 R1+R2：任免的双向对冲 —— 名册 ⊕ 同夜暂存为比对真基准。  行为契约（对着 issue #504 AC6/AC7）：召对里皇帝反悔时，本轮抽出的任免与同夜一条 【尚未落库的反向暂存任免】相抵，须撤销那条暂存、不落新动作——暂存免职未提交时名册仍 显示在职，只比名册会把「留任」误
- 证据:
  - L81: `assert len(staged) == 1 and staged[0]["action"] == "罢免"`
  - L114: `assert len(staged) == 1 and staged[0]["action"] == "任命"`
  - L139: `assert len(staged) == 1 and staged[0]["action"] == "任命"`

#### `tests/test_settlement_write_guard_393.py`
- 规模: 428 行 / 62 案 / ~0.73s · 🔒闸类不可删
- 注: #393 串行门补全（cmr Gate1 + Gate2）：web 端「绕过会话层、直写 game.db」的玩家/调试端点， 必须与月末结算原子块 / 后台召对 worker 在同一无锁连接上串行——不许重叠。  Gate1：相位（SETTLING / AWAITING_DECISION）期间拒写。 Gate2（F-A 【闸类/负向契约——不可删】
- 证据:
  - L39: `assert row["id"] == 7`
  - L244: `assert game.db.writes == [], f"{name} wrote DB during settlement: {game.db.writes}"`
  - L291: `with pytest.raises(RuntimeError):`

#### `tests/test_empire_modifier_income_only_341.py`
- 规模: 57 行 / 3 案 / ~0.73s
- 注: 帝国修正只作用收入、不放大支出（issue #341）。  根因：record_issue_economy_move 对支出（delta < 0）也调 apply_legacy_pct， 把「国库 -12%」从「收入缩水 12%」错误地变成「支出涨价 12%」。 修法：帝国修正只对正向流水（delta > 0）生效；负
- 证据:
  - L18: `assert net_pct < 0, f"前置条件：游戏开局应有负的国库帝国修正（实为 {net_pct}）"`
  - L23: `assert actual == -50, (`
  - L39: `assert actual == expected, (`

#### `tests/test_fiscal_tick.py`
- 规模: 177 行 / 61 案 / ~0.71s · 🔒闸类不可删
- 注: settle_tick golden G1–G22 + fail-loud；独立锚+守恒 oracle。高效（61 案 ~0.7s）。
- 证据:
  - L29: assert math.isclose(got, vv, ...)
  - L147/169: pytest.raises(ValueError/FiscalConservationError)

#### `tests/test_appease_mao_contract.py`
- 规模: 184 行 / 6 案 / ~0.68s
- 证据:
  - L28: `assert issue["resolve_condition"] == "character.毛文龙.loyalty >= 65"`
  - L79: `assert "65" not in simulator_issue["stop_condition"]`
  - L115: `assert '"integrity": -15' not in rendered`

#### `tests/test_region_cannon_delta.py`
- 规模: 100 行 / 6 案 / ~0.64s
- 注: s2 (#4) — 城防炮 region.cannon 的 delta 落库路径。  城防炮（城头红夷炮）此前无 delta 写入路径：apply_region_cannon 已存在且带 city_level×8 clamp，但零调用方；region_delta 带「城防炮」会被当非法字段拒。 本组验证：经 run_s
- 证据:
  - L19: `assert REGION_FIELD_LABELS.get("cannon") == "城防炮"`
  - L54: `assert len(rows) == 1, f"clamp 成 no-op 的城防炮请求须留 1 条 region_log 痕迹，实得 {len(rows)}"`
  - L70: `assert len(rows) == 1, "请求减炮被下限 clamp 成 no-op 也须留痕"`

#### `tests/test_enrich_list_guards.py`
- 规模: 84 行 / 7 案 / ~0.61s · 🔒闸类不可删
- 注: #117：enrich / apply 路径对 LLM 给的「真值非 list/dict」集合加 isinstance 守卫，不崩回合。  根因：`X.get(key) or []` 只兜 None/假值，兜不住真值非 list（true/数字/字符串）——`for x in 它` 抛 TypeError（字符串还逐字
- 证据:
  - L25: `assert isinstance(out["effect_on_resolve"], dict)  # 不崩、结构正常`
  - L40: `assert len(out) == 1, f"合法 economy 项被守卫误吞：{out}"`
  - L49: `assert loads_effect_dict({"already": "parsed"}) == {"already": "parsed"}  # 已解析 dict 原样（codex R4）`

#### `tests/test_power_section_rejections.py`
- 规模: 272 行 / 12 案 / ~0.60s · 🔒闸类不可删
- 注: PR2-S1(ADR 0008 决定 1,#91)——两个整段吞 section 迁入逐项拒收契约。  section 5 power_updates、section 9b character_power_changes：原先 `try: db.apply_*() except Exception: print [WA 【闸类/负向契约——不可删】
- 证据:
  - L31: `assert row is not None, "probe.db 需至少一个非明势力"`
  - L91: `with pytest.raises(SettlementAbort):`
  - L182: `assert len(rows) == 1`

#### `tests/test_web_chat_serialization_393.py`
- 规模: 404 行 / 8 案 / ~0.59s
- 证据:
  - L30: `assert self.allow_finish.wait(1.0), "test timed out waiting to finish fake stream"`
  - L201: `assert events == [{`
  - L260: `assert str(exc) == "production prompt failure"`

#### `tests/test_secret_order_section_rejections.py`
- 规模: 196 行 / 9 案 / ~0.57s · 🔒闸类不可删
- 注: secret_order 段拒收补精确 category（ADR 0008 决定 1 逐项拒收契约统一，#14 C2）。  secret_order_closes 早已逐项拒收（含未知 order_id「密令不存在」）、updates 此前对未知/非 active id 静默报成功（cmr r1 codex 抓出，#1 【闸类/负向契约——不可删】
- 证据:
  - L37: `assert len(rows) == 1, rows`
  - L103: `assert len(rows) == 1, rows`
  - L145: `assert "测试密令副作用R8" in (in_tx["sim_note"] or "")`

#### `tests/test_initiative_resolve_pairing.py`
- 规模: 185 行 / 18 案 / ~0.52s · 🔒闸类不可删
- 注: #45/#46（M1 状态可信链路）：国策结案实体后果强制配对守门。  军事国策（练军/募营/调将）结案却无 new_armies/office_changes、或经制国策（月经费/俸/饷） 结案却无月度 economy/fiscal_creates 时，响亮告警——不再静默放过「只推进度条、无实体后果」 的空壳结案（ 【闸类/负向契约——不可删】
- 证据:
  - L17: `assert warns, "军事国策结案无 new_armies 应告警"`
  - L45: `assert warns == [], f"已带 ongoing economy 不应告警：{warns}"`
  - L78: `assert any("new_armies" in w for w in warns), "练军只挂人物变更（无 new_armies）应告警缺军籍"`

#### `tests/test_advances_section_rejections.py`
- 规模: 156 行 / 24 案 / ~0.49s · 🔒闸类不可删
- 注: #63 / ADR 0008 决定 1：apply_issue_tracker_output 的 advances 段迁逐项拒收 + fail-loud。  原先：坏 issue_id 裸 continue 无留痕、非 dict 项 adv.get 抛 AttributeError 崩整月、delta_bar/ ine 【闸类/负向契约——不可删】
- 证据:
  - L37: `assert len(rej) == 1`
  - L50: `assert "issue_id" in rej[0]["reason"]`
  - L88: `assert len(rej) == 1, out`

#### `tests/test_web_llm_runtime_config.py`
- 规模: 973 行 / 38 案 / ~0.46s · 次类: 重复 · 处置建议: **合并**
- 注: web menu/API 接缝；保留 web 独有，下沉共享断言到 channel/runtime。
- 证据:
  - L34: `assert cfg.channel == "cli"`
  - L266: `assert result["channel"] == "cli"`
  - L508: `assert status["llm"]["api_reasoning_strength"] == "low"`

#### `tests/test_bandit_power_model_190.py`
- 规模: 99 行 / 4 案 / ~0.39s
- 注: Issue #190 bandit leader/stock split behavior.
- 证据:
  - L19: `assert rows["李自成"]["power_id"] == "bandit_li_zicheng"`
  - L21: `assert rows["李自成"]["power_id"] != rows["张献忠"]["power_id"]`
  - L32: `assert powers["bandit_li_zicheng"]["military_strength"] != powers["bandit_zhang_xianzhong"]["military_strength"]`

#### `tests/test_person_archive_schema.py`
- 规模: 180 行 / 6 案 / ~0.37s
- 注: ADR 0009 person archive schema contract.
- 证据:
  - L25: `assert "reason_code" in cols`
  - L31: `assert info[name]["dflt_value"] == "''"`
  - L65: `assert "idx_person_logs_turn" in indexes`

#### `tests/test_six_sciences_seed_608.py`
- 规模: 70 行 / 3 案 / ~0.32s
- 注: #608：六科官署与言官 seed。
- 证据:
  - L14: `assert infer_office_type_from_office("六科") == "六科"`
  - L32: `assert len(rows) == 2`
  - L40: `assert by_name["韩一良"]["status"] == "offstage"`

#### `tests/test_region_citydefense.py`
- 规模: 62 行 / 5 案 / ~0.31s · 次类: 重复
- 注: schema/seed/payload 契约；display 文件是其文案孪生。
- 证据:
  - L18-19: assert city_level/cannon in cols
  - L28-37: 史实等级锚 beizhili==5 等
  - L61-62: simulator payload 含字段

#### `tests/test_adr0015_per_item_rejection.py`
- 规模: 263 行 / 8 案 / ~0.29s · 🔒闸类不可删
- 注: 【闸类/负向契约——不可删】
- 证据:
  - L43: `assert ctx["extracted"]["economy_moves"] == [{"account": "国库", "delta": 1, "category": "ok"}]`
  - L81: `assert len(mirrored) == 1`
  - L164: `assert rows`

#### `tests/test_llm_channel_config.py`
- 规模: 434 行 / 23 案 / ~0.27s · 次类: 重复 · 处置建议: **合并**
- 注: LLMConfig 构造/load 真源；与 runtime_llm_config / web_llm_runtime_config 有通道字段重叠。
- 证据:
  - L26: `assert isinstance(model, OpenAIChat)`
  - L91: `assert cfg.advanced_thinking_level == ""`
  - L287: `with pytest.raises(LLMUnavailable):`

#### `tests/test_yuan_arrival_185.py`
- 规模: 213 行 / 2 案 / ~0.25s
- 注: #185 e2e：在途大臣（transit_to=目的地）+ 抵达前置条件（欠饷补齐）→ 条件满足后真到任。  #185 = [验证] transit→抵达 落库已修：确认欠饷补齐后到任(e2e)。  覆盖范围说明（诚实化，回应评审）：本 e2e 验的是 **#185 的到任落库机制本身—— 人物无关**：抵达时 tr
- 证据:
  - L66: `assert row["transit_to"] == DEST, "应处于在途态"`
  - L75: `assert arrears0 > 0, f"前置：关宁军应有欠饷，实测 {arrears0}（无欠饷则条件场景不成立）"`
  - L128: `assert arrived["status"] == "active"`

#### `tests/test_runtime_llm_config.py`
- 规模: 472 行 / 22 案 / ~0.24s · 次类: 重复 · 处置建议: **合并**
- 注: runtime 持久化槽；与 channel_config/web 重叠 load/save 形状。
- 证据:
  - L11: `assert llm_config.load_runtime_llm() == {}`
  - L126: `assert saved["api"]["api_key"] == "sk-test"`
  - L257: `assert saved["reasoning_strength"] == ""`

#### `tests/test_web_budget_payload.py`
- 规模: 99 行 / 2 案 / ~0.22s
- 证据:
  - L19: `assert "中央军饷" not in categories`
  - L20: `assert "临时调拨" in categories`
  - L85: `assert "边饷hub" in ledger_categories`

#### `tests/test_named_characters_seed_484.py`
- 规模: 176 行 / 8 案 / ~0.21s
- 注: #484 R4：named-character 史实档案的 loader/DB 契约。
- 证据:
  - L17: `assert chars["郭允厚"].seed_guilt == {"crime": "交结近侍又次等", "severity": "中"}`
  - L34: `assert li.office_type == "工部"`
  - L68: `assert character.location == location`

#### `tests/test_cli_model_choices.py`
- 规模: 137 行 / 12 案 / ~0.15s
- 注: CLI runner 策展模型清单（前端下拉的单一真源）。  CLI Model 从自由文本框改成 per-runner 策展下拉，清单在后端单点定义、经 config 端点暴露给前端。这里测清单结构 + 默认档语义 + 与默认常量的一致性 （不重写字面量），以及两个 config 端点确实把清单带出去。
- 证据:
  - L20: `assert set(choices) == cb._CLI_BACKENDS == {"agy", "codex", "claude"}`
  - L34: `assert len(values) == len(set(values)), f"{runner} 档位 value 重复"`
  - L57: `assert "gpt-5.3-codex-spark" in values  # bench「可用主力·快」档`

#### `tests/test_production_person_key_contract_558.py`
- 规模: 44 行 / 2 案 / ~0.14s
- 证据:
  - L28: `assert prompts[0][1] == "issue_enrich"`
  - L30: `assert "人物变更" in guidance`
  - L33: `assert legacy_key not in guidance`

#### `tests/test_secret_order_refresh.py`
- 规模: 49 行 / 1 案 / ~0.14s
- 注: 密令创建后 refresh 承办大臣 agent，使其上下文立即带上新密令简报。  bug：CLI 后端创建密令后未 refresh，大臣缓存 agent 上下文冻结， 他"不知道自己有这密令"。修：web_app 创建密令后 registry.refresh(承办人)。 此处测 refresh 机制本身：建密令后 g
- 证据:
  - L41: `assert reg.get(char) is a1              # 创建不触发刷新 → 仍是陈旧缓存`
  - L44: `assert a2 is not a1                      # refresh 后重建`
  - L46: `assert "辰字密令更新测试" in joined        # 新 agent 上下文带上了新密令简报`

#### `tests/test_army_pay_source_prompt_contract.py`
- 规模: 44 行 / 1 案 / ~0.12s
- 证据:
  - L41: `assert row is not None`
  - L42: `assert row["pay_source_region"] == "shaanxi"`
  - L43: `assert row["province_pay_share"] == 0.65`

#### `tests/test_player_payload_1022.py`
- 规模: 155 行 / 4 案 / ~0.05s
- 注: #1022 — 玩家历史、结算流与 CLI 只交付叙事形态。
- 证据:
  - L42: `assert payload == {`
  - L113: `assert payload["decisions"] == [{"title": "辽饷", "context": "家赀约十万两，是否发帑"}]`
  - L150: `assert handled == "handled"`

### 2.2 盯文（9 文件）

#### `tests/test_commitment_display_348.py`
- 规模: 338 行 / 24 案 / ~4.10s · 次类: 真行为契约 · 处置建议: **改造**
- 注: 部分断言防绝对回合号泄漏（真契约），部分钉中文展示词。
- 证据:
  - L52: assert "17" not in text  # 防绝对回合泄漏——真契约，保留
  - L126: assert "直到补齐" in text
  - L193: assert bar is None

#### `tests/test_army_display_173.py`
- 规模: 212 行 / 9 案 / ~0.71s · 次类: 真行为契约 · 处置建议: **改造**
- 注: army_needed 呈现口径真契约混有精确中文金额串。
- 证据:
  - L72: assert "欠饷约60万两" in joined
  - L77: assert forbidden not in joined
  - L147: assert int(row[ni]) == expected

#### `tests/test_region_citydefense_display.py`
- 规模: 47 行 / 5 案 / ~0.66s · 处置建议: **改造**
- 注: 对 region_report/detail 自由中文展示串做机械 contains。字段在 payload 已有契约（test_region_citydefense），本文件只钉文案。
- 证据:
  - L22: assert "城防炮5门" in rep
  - L31-32: assert "城市等级" in det / "城防大炮6门" in det
  - L47: assert f"城防{label}" in detail

#### `tests/test_featured_dossiers_494.py`
- 规模: 100 行 / 4 案 / ~0.64s · 次类: mock伪行为 · 处置建议: **改造**
- 注: 人物/派系 dossier 长散文 contains；含 mock。
- 证据:
  - L32: assert all("事例：" in minister_dossier(c) for c in ministers)
  - L50: assert "这个党是什么样一伙人" in high
  - L100: assert rendered.count("以皇帝直控…") == 1

#### `tests/test_secret_order_status_cn.py`
- 规模: 234 行 / 12 案 / ~0.45s · 次类: 真行为契约 · 处置建议: **合并**
- 注: group_secret_orders_for_prompt 中文状态桶 + 公共 LLM 不预读密令。状态标签盯文可改结构断言；隔离面与 #883 重叠。
- 证据:
  - L51: assert set(grouped.keys()) == {"在办", "待核议"}
  - L79: assert entry["progress"] == "已查两淮"
  - L234: assert get_resolve_context(...)["secret_orders"] == {}  # 真隔离契约

#### `tests/test_web_issue_condition_display.py`
- 规模: 58 行 / 9 案 / ~0.11s · 处置建议: **改造**
- 注: humanize 条件 → 精确中文句。改一个词即红。
- 证据:
  - L9: assert text == "毛文龙忠诚回稳"
  - L27: assert "character" not in text
  - L58: assert "65" not in text

#### `tests/test_memory_person_changes.py`
- 规模: 69 行 / 5 案 / ~0.06s · 处置建议: **改造**
- 注: effect_brief 叙事摘要精确中文串。
- 证据:
  - L16: assert "人事调整：孙传庭、皇太极" in brief
  - L28: assert brief == "盘面无显著结构化变化"
  - L45: assert "处分：魏忠贤" in brief

#### `tests/test_release_bundle_assets.py`
- 规模: 34 行 / 2 案 / ~0.02s · 次类: 只测helper · 处置建议: **改造**
- 注: 读 .spec 源文件字符串 contains；打包资产契约可用更稳的结构断言。
- 证据:
  - L33: assert 'tree_datas("web/dist"...' in spec
  - L34: assert 'tree_datas("web/public"...' not in spec

#### `tests/test_personnel_origin_prompt_558.py`
- 规模: 24 行 / 1 案 / ~0.01s · 处置建议: **改造**
- 注: 对 prompt 模板字符串做正则+字面 dossier:17 钉死。
- 证据:
  - L18: assert all(item["来源引用"] == "dossier:17" for item in decree_items)
  - L19: assert "dossier:17" in text[:match.start()]

### 2.3 重复（1 文件）

#### `tests/test_knowledge.py`
- 规模: 467 行 / 20 案 / ~10.63s · 次类: 真行为契约 · 处置建议: **合并**
- 注: 与 test_character_knowledge_489 同根 #489 知识投影。本文件偏 archive/source_scope；489 偏 office slice/参与。重叠：secret exclusion、chapter counterpart、public source。
- 证据:
  - test_knowledge L119: assert public_marker in excluded_text
  - test_character_knowledge_489 L316: test_public_directive_is_seen_by_uninvolved_minister_but_secret_exclusion_wins
  - 两者均测 chapter/turn_report counterpart 与 secret 边界

### 2.4 只测helper（14 文件）

#### `tests/test_cli_backend.py`
- 规模: 1832 行 / 137 案 / ~5.44s · 次类: 真行为契约, 盯文 · 处置建议: **改造**
- 注: 文档自承「确定性逻辑/解析层」。大量 _extract_assignee_action / _infer_tag 私有函数 + 中文 prompt 标签。密令提取/trace 有真契约面可抽留。
- 证据:
  - L377: assert cb._extract_assignee_action(clause, "李若琏") == "暗查"
  - L1369: assert cb._infer_tag("你扮演被皇帝召见的大臣…") == "minister"
  - L39: assert acts["decree_text"] == reply

#### `tests/test_person_write_inventory.py`
- 规模: 108 行 / 5 案 / ~1.25s · 处置建议: **删**
- 注: ADR0009 写点库存扫描器——测的是测试/工具自身的 AST 扫描与 disposition 表，非产品外部行为。
- 证据:
  - L16: assert discovered_locations <= inventory_locations
  - L45: assert by_location["ming_sim/db.py:seed_static_data"]["disposition"] == "adr0009_exempt"
  - L81-83: assert _enclosing_function_name / _call_name 内部 helper

#### `tests/test_office_inference.py`
- 规模: 267 行 / 36 案 / ~0.84s · 次类: 真行为契约 · 处置建议: **改造**
- 注: office_type 表查找；含 seed 不调 CLI 的真契约。
- 证据:
  - L72: assert infer(office) == expected
  - L201: assert calls == []  # seed 不应调 CLI
  - L266: assert content.characters["刘鸿训"].office_type == "礼部"

#### `tests/test_chat_stream_failpaths_393.py`
- 规模: 209 行 / 3 案 / ~0.38s · 次类: 真行为契约 · 处置建议: **改造**
- 注: 大量私有接缝（priv=21）；流式 failpath 真契约但耦合内部 prologue。
- 证据:
  - L68: `with pytest.raises(RuntimeError):`
  - L73: `assert not runtime._write_gate.locked()`
  - L133: `assert not runtime._write_gate.locked()`

#### `tests/test_person_archive_contract_index.py`
- 规模: 233 行 / 7 案 / ~0.07s · 处置建议: **改造**
- 注: 把散文契约钉成 PERSON_TRANSITION_MATRIX 常量索引；不测 applier 行为。
- 证据:
  - L24: assert PERSON_TRANSITION_ACTIONS == ("任命", "罢黜", ...)
  - L84: assert set(MATRIX[status]) == set(ACTIONS)
  - L233: assert normalize_reason_code("未识别") == "未识别"

#### `tests/test_decision_event_binding_389.py`
- 规模: 64 行 / 6 案 / ~0.07s · 次类: 真行为契约
- 注: 纯函数 bind_decisions_to_candidate_events；守护 #389 绑定真源，偏单元。
- 证据:
  - L21: assert out[0]["event_id"] == "mao_wenlong"
  - L45: assert "event_id" not in out[0]

#### `tests/test_extractor_misroute_surface.py`
- 规模: 75 行 / 5 案 / ~0.06s · 次类: 真行为契约 · 处置建议: **改造**
- 注: 测 _sanitize_module_output 与 _FIELD_OWNER_MODULE 内部表；surface 可观测是真契约。
- 证据:
  - L27: assert out.get("metric_delta") == {"国库": 10}
  - L75: assert sim._FIELD_OWNER_MODULE[field] == module

#### `tests/test_llm_key_helpers.py`
- 规模: 45 行 / 5 案 / ~0.06s · 处置建议: **删**
- 注: 纯函数 is_real_api_key / real_api_key_or_empty 真值表。无外部行为接缝。
- 证据:
  - L17-20: assert is_real_api_key(None/''/placeholder) is False
  - L32: assert is_real_api_key("sk-abc123") is True
  - L45: assert real_api_key_or_empty("  sk-abc123  ") == "sk-abc123"

#### `tests/test_load_observability.py`
- 规模: 46 行 / 5 案 / ~0.05s · 处置建议: **删**
- 注: describe_effective_model 标签字符串。
- 证据:
  - L16: assert describe_effective_model(cli) == "codex/gpt-5.3-codex-spark"
  - L46: assert "api-fallback" not in label

#### `tests/test_qualitative.py`
- 规模: 28 行 / 3 案 / ~0.03s · 处置建议: **删**
- 注: qualitative_band/bucket/building_qualitative_fields 纯函数。
- 证据:
  - L13: assert qualitative_band(0, words) == "low"
  - L20: assert qualitative_bucket(40, (40,80), default=50) == 1
  - L28: assert building_qualitative_fields(row) == ("初设", "残损", "低")

#### `tests/test_read_game_fixture.py`
- 规模: 28 行 / 2 案 / ~0.02s · 处置建议: **删**
- 注: 测的是 pytest fixture read_game 自身边界，非产品。
- 证据:
  - L13-16: armies/regions/characters 非空
  - L23: pytest.raises(OperationalError, match="readonly")

#### `tests/test_distance_matrix.py`
- 规模: 81 行 / 4 案 / ~0.02s · 处置建议: **删**
- 注: 距离矩阵纯计算（对称/三角不等式）。
- 证据:
  - L20: assert matrix["a"]["a"] == 0
  - L43: assert matrix["a"]["b"] <= matrix["a"]["c"] + matrix["c"]["b"]

#### `tests/test_suggestions_chips_527.py`
- 规模: 18 行 / 1 案 / ~0.01s · 处置建议: **删**
- 注: suggestions_for == 模块内常量 _PREFIX_ONLY，近乎同义反复。
- 证据:
  - L18: assert items == _PREFIX_ONLY

#### `tests/test_env_isolation.py`
- 规模: 19 行 / 1 案 / ~0.00s
- 注: 钉 conftest autouse 的 user_data 隔离，防测试污染 repo data。属测试基建 pin，非产品契约。
- 证据:
  - L17: assert os.environ.get("MING_SIM_USER_DATA_DIR")
  - L19: assert user_data_dir() != repo data

### 2.5 mock伪行为（2 文件）

#### `tests/test_minister_context.py`
- 规模: 1019 行 / 47 案 / ~16.70s · 次类: 盯文, 真行为契约 · 处置建议: **改造**
- 注: 34 处 mock；大量 rendered 中文 contains。有真实 DB projection 案（test_minister_context_uses_real_db_projection）。
- 证据:
  - L275: assert "不可知的他派密议" not in rendered
  - L712: assert "欠饷" in fact
  - L1019: assert f"第{state.turn}回合" in rendered

#### `tests/test_minister_chat_timeout.py`
- 规模: 181 行 / 5 案 / ~0.08s · 处置建议: **改造**
- 注: 文档称 public interface，实则 patch create_chat_model 断言调用 kwargs 键名。
- 证据:
  - L76: assert MINISTER_CHAT_CLI_TIMEOUT_SECONDS < CLI_DEFAULT_TIMEOUT_SECONDS  # 常量比较
  - L105: assert "cli_timeout" in captured
  - L136: assert "timeout_seconds" in captured

---

## 3. Kill-list（带证据 · 三类处置）

> 本表是过庭素材，**本轮不执行**。闸类负向案标 🔒 不可删。

### 3.1 建议删除（删）

原则：无独立外部行为契约、或同义反复、或纯 helper 真值表且已被集成面覆盖。

| 文件 | 估时 | 用例 | 证据摘要 | 风险 |
|---|---:|---:|---|---|
| `tests/test_suggestions_chips_527.py` | 0.01 | 1 | L18 `assert items == _PREFIX_ONLY` 与模块常量同义反复 | 低：无闸类 |
| `tests/test_llm_key_helpers.py` | 0.06 | 5 | L17-45 纯函数真值表；channel/runtime 集成已覆盖 placeholder/real key 分支 | 低：无闸类 |
| `tests/test_qualitative.py` | 0.03 | 3 | L13-28 band/bucket 纯函数；player_payload/character_projection 已用定性出口 | 低：无闸类 |
| `tests/test_distance_matrix.py` | 0.02 | 4 | L20/L43 纯矩阵数学；无游戏接缝断言 | 低：无闸类 |
| `tests/test_load_observability.py` | 0.05 | 5 | L16 标签字符串 `codex/gpt-5.3-codex-spark`；模型名一变即红 | 低：无闸类 |
| `tests/test_read_game_fixture.py` | 0.02 | 2 | L13-28 测 pytest fixture 自身，非产品 | 低：无闸类 |
| `tests/test_person_write_inventory.py` | 1.25 | 5 | L16/L45/L81 扫描器+disposition 表+AST helper，属工具自测 | 低：无闸类 |

小计可删：~1.4s / 25 案（时长收益小，主要减维护面）。

### 3.2 建议合并（合并）

| 簇 | 成员 | 估时合计 | 合并策略 | 证据 |
|---|---|---:|---|---|
| #489 知识投影 | `test_knowledge.py` + `test_character_knowledge_489.py` | 45.7 | 以 489 为锚，迁入 knowledge 独有 archive/source_scope 案，删重叠 exclusion/counterpart | 两文件均含 secret exclusion + chapter counterpart；489 L316 vs knowledge L88-120 |
| #498 夜宴 | `test_audience_night_498.py` + `test_web_audience_night_498.py` | 6.0 | 引擎案留 core；web 只留 ASGI/event-loop/fail-closed 独有接缝 | core L243 auto_closes vs web L267 night_approved_closes |
| 城防 | `test_region_citydefense.py` + `test_region_citydefense_display.py` | 1.0 | display 文案断言并入 payload/report 结构断言或删 | display L22 "城防炮5门"；citydefense L61 payload 已有字段 |
| 密令状态/隔离 | `test_secret_order_status_cn.py` 隔离面 + `test_secret_order_isolation_883.py` | 147.1 | status_cn 保留 group 纯函数；L234 隔离断言迁 883 | status_cn L234 secret_orders=={}；883 全卷 withheld/shared=0 |
| LLM 配置三叠 | `test_llm_channel_config.py` + `test_runtime_llm_config.py` + `test_web_llm_runtime_config.py` | 1.0 | 共享 load/save/placeholder 下沉一处；web 只留 HTTP/menu 接缝 | 三者均测 cli/api slot、reasoning_strength、placeholder key |

### 3.3 建议改造（改造）——优先按收益排序

| 优先级 | 文件 | 估时 | 改造刀口 | 证据 | 期望收益 |
|---:|---|---:|---|---|---|
| P0 | `test_session_cli_fallback.py` | 386 | 凡 `MING_SIM_LLM_BACKEND=agy` 的案，统一 mock `classify_cli_action_intent` **与** `_run_agy`/`_run_codex`；禁止实打 subprocess | cProfile: classify→_run_agy→poll 45.3s；L2905 只 mock extract | **−350s 级** |
| P0 | `test_secret_order_isolation_883.py` | 147 | 同上；🔒 契约保留，只堵 CLI 泄漏 | L1519 production extract 路径 ~90s call | **−130s 级** |
| P1 | `test_cli_backend.py` | 5.4 | 删除/下沉 `_extract_*`/`_infer_tag` 私有单测；保留 JSON 规范化与密令 merge 公共出口 | L377 `_extract_assignee_action`；L1369 `_infer_tag` | 减 152 处 priv 耦合 |
| P1 | `test_minister_context.py` | 16.7 | 将 34 mock 案改为真实 DB projection 接缝；去掉 rendered 长中文 contains，改结构化字段 | L275/L712/L1019 中文 contains | 稳 + 略加速 |
| P1 | `test_minister_chat_timeout.py` | 0.1 | 改经 public create 超时行为（短超时 fail），勿断言 kwargs 键名 | L105 `"cli_timeout" in captured` | 去伪行为 |
| P2 | `test_event_trigger_gate.py` | 55 | 203 案参数化合并同类 gate；减轻 per-case setup（setup 53s） | L45 gated hist 排除；setup>>call | −setup 重复 |
| P2 | `test_fiscal_substrate_bridge.py` | 34 | 184 案瘦身：seed 变体参数化；保留 fail-loud 🔒 | raises=26；L108 宗禄 approx | 减行数/维护 |
| P2 | `test_conversational_draft.py` | 49 | 去 prompt 字面盯文（L1384）；保留 pending LWW 状态契约 | L1384 `【现有草案】…` in prompt | 稳 |
| P2 | 盯文簇 display/memory/featured/personnel_prompt | <5 | 展示断言改为：关键数值/枚举在场 + 禁机读键；删精确散文 | citydefense_display L22；memory L16；featured L50 | 减脆 |
| P2 | `test_person_archive_contract_index.py` | 0.1 | 常量矩阵改为「applier 消费该索引」的行为测，或并入 person_delta | L24 ACTIONS 元组相等 | 去纯索引测 |
| P2 | `test_office_inference.py` | 0.8 | 表命中可留少量；LLM 兜底 mock 案改行为出口 | L72 parametrize 表；L201 seed 不调 CLI 保留 | 瘦参 |
| P2 | `test_extractor_misroute_surface.py` | 0.1 | 去掉 `sim._FIELD_OWNER_MODULE` 私有表断言，留 surface 可观测 | L75 私有表 | 去内部 |
| P2 | `test_release_bundle_assets.py` | 0.0 | .spec 字符串改解析/结构断言 | L33 tree_datas contains | 减盯文 |
| P2 | `test_chat_stream_failpaths_393.py` | 0.4 | 减少私有 prologue 耦合，经 SSE/公开错误包观察 | priv=21 | 去内部 |

### 3.4 明确不可删（闸类契约负向案）

下列文件含拒收/写门/事务/事件前提等**负向闸**，过庭执行时**整文件默认保留**；
内部单案若重复可合并，但不得删除「脏输入被拒 + 无脏写」类断言。

| 文件 | 闸类焦点 | 负向证据例 |
|---|---|---|
| `tests/test_event_trigger_gate.py` | 历史事件前提门 | L2618 rejected is True；未满足 gate 不进候选 |
| `tests/test_settlement_write_guard_393.py` | 结算期写拒 | parametrize phase×endpoint direct_db_write_refused |
| `tests/test_section4_rejections.py` | army/region delta 逐项拒 | L533 invalid_enum；L750 pytest.raises |
| `tests/test_new_issues_section_rejections.py` | new_issues 脏字段拒 | L295 category==invalid_enum |
| `tests/test_section_fiscal_rejections.py` | 财政段拒收 | fail-loud dirty delta |
| `tests/test_close_issues_section_rejections.py` | 结案段拒收 | bad issue_id rejected |
| `tests/test_economy_section_rejections.py` | economy 段拒收 | bad account |
| `tests/test_power_section_rejections.py` | power 段拒收 | — |
| `tests/test_faction_class_section_rejections.py` | 派系/class 拒收 | — |
| `tests/test_advances_section_rejections.py` | advances 拒收 | — |
| `tests/test_secret_order_section_rejections.py` | 密令段拒收 | — |
| `tests/test_adr0015_per_item_rejection.py` | 逐项拒收 ADR | — |
| `tests/test_rejection_wiring.py` | 拒收收集器入管线 | — |
| `tests/test_promulgation_seam_560.py` | 颁诏接缝拒畸形 | raises=19 |
| `tests/test_promulgation_judge_561.py` | 颁诏裁决形状 | raises=14 |
| `tests/test_transaction_boundary.py` | 事务边界 | atomic rejects plain connection |
| `tests/test_pre_settle_transaction.py` | 预结算同事务 | — |
| `tests/test_advance_paths_atomic.py` | 推进路径原子 | raises=19 |
| `tests/test_initiative_resolve_pairing.py` | 国策结案配对告警 | L17 warns on missing new_armies |
| `tests/test_chat_mutations_freeze.py` | 恢复窗禁写 | — |
| `tests/test_secret_order_isolation_883.py` | 密令隔离/withheld | shared_source_count==0 |
| `tests/test_pending_actions.py` | 动作闸 ADR0006 | — |
| `tests/test_fiscal_tick.py` | 守恒 fail-loud | FiscalConservationError |
| `tests/test_character_knowledge_489.py` | 密令知识黑名单 | exclusion wins |
| `tests/test_decree_dossiers_571.py` | dossier 畸形拒 | raises=37 |
| `tests/test_person_delta_adapter.py` | 非法 person_change 拒 | rejects unknown/invalid |

---

## 4. 时长收益粗算（改造后，不删契约）

| 动作 | 粗算节省 |
|---|---:|
| P0 mock 堵 CLI 泄漏（session_cli + isolation） | **~480s** |
| P2 event_trigger/fiscal 参数化减 setup | ~20–40s |
| 删 7 个 helper 文件 | ~2s |
| 合并知识/夜宴/配置重叠 | ~5–15s + 大减行数 |
| **乐观合计** | **全量 17.6min → ~8–9min** |

**测试分级政策**：不在本报告另立口径。真源见 [`docs/DEV_WORKFLOW.md`](docs/DEV_WORKFLOW.md) §测试分级——批次/家族收尾在最终待合并状态跑全量、失败修复后重跑、最终绿灯作 merge 门。

**kill-list 执行进度**：见票 #1185 评论流；本报告不维护平行结果表（冻结审计件，非活台账）。

---

## 5. 方法与局限

- 环境：`python3 -m venv .venv && pip install -r requirements.txt pytest`
- 全量命令：`.venv/bin/python -m pytest -q --durations=0`（无墙钟上限）
- durations 隐藏 <0.005s；hidden call 按 0.002s 估入 total_est
- 分类以文件为主单位（票面「逐测试文件」）；文件内混合五尺时主类取主导问题，次类入注
- 未改任何 `tests/**` 文件；本报告为唯一产物（冻结审计件）

---

## 附录 A. 家族耗时汇总

| 家族 | 文件 | 用例 | 估时 s |
|---|---:|---:|---:|
| cli/session（含 CLI 泄漏） | 3 | 246 | 392.9 |
| secret_order | 7 | 104 | 153.9 |
| event | 4 | 228 | 61.9 |
| fiscal | 4 | 338 | 46.7 |
| decree/dossier | 10 | 422 | 90.8 |
| audience | 10 | 163 | 27.9 |
| knowledge/minister | 7 | 157 | 74.4 |
| section_rejection | 11 | 250 | 15.8 |
| person | 8 | 165 | 21.3 |

## 附录 B. 原始 pytest 尾摘要（审计基线 · Batch 1 前）

```text
3024 passed, 11 skipped in 1060.15s (0:17:40)
```

## 附录 C. 处置建议计数

- 删: 7 文件
- 合并: 7 文件
- 改造: 20 文件
- 无处置（保留）: 95 文件
- 闸类锁定: 36 文件

