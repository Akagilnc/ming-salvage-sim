# test-cleanup-audit-1185 — 二阶段全量测试处置清单

> 票面：[#1185](https://github.com/Akagilnc/ming-salvage-sim/issues/1185) 测试大清理 · **二阶段审计**（只审计、**零改测试代码**）  
> 分支：`audit/issue-1185-test-cleanup` @ `132839e1`  
> 采集：`.venv/bin/python -m pytest --collect-only -q` → **3081 tests / 130 files**  
> 前序：一阶段分级政策已 merge = [PR#1186](https://github.com/Akagilnc/ming-salvage-sim/pull/1186)；冻结件 `TEST_AUDIT_1185.md`（Batch1 前 3024p/11s in 1060s）  
> 约束：本轮交付 = 本报告 + issue 评论 + commit；**不动任何 `tests/**`**。不跑烧额度用例。  
> 法源：仓宪测试五尺（全局宪法 #13 / 票面升格段）+ [`docs/DEV_WORKFLOW.md`](DEV_WORKFLOW.md) §测试分级

---

## 0. 执行摘要

| 指标 | 值 |
|---|---|
| 当前收集 | **3081** nodes / **130** files / 2555 函数级用例 |
| 相对 PR#1186 审计基线 | 基线 3035 nodes/129 files；已删 helper×2；新增 #564/#611/#612 三卷 |
| P0 CLI 泄漏（一阶段已堵） | `session_cli_fallback` + `isolation_883` 已 `preclassified_intent` / classify stub；本轮复核 **无残留裸 apply→agy subprocess** |
| 建议 delete（节点） | **33** |
| 建议 merge（节点） | **99**（估可净减 ~44 重叠） |
| 建议 rewrite（节点） | **398**（改造不先删契约） |
| 建议 keep（节点） | **2551** |
| 估执行后节点 | **~3004**（−33 delete −~44 merge 重叠） |
| 时长目标（票面终线） | 全量墙钟 ≤120s（开发机）；P0 已指向 −480s 级，本清单供过庭后执行 |

### 五尺对照（本清单标签）

| 尺 | 含义 | 本轮刀口 |
|---|---|---|
| ① 泄漏 | subprocess/LLM/网络会烧额度或本地/CI 分叉 | 第一刀点名；P0 已堵主泄漏，纪律固化进 rewrite/keep 理由 |
| ② 盯文 | 对自由文本建机械依赖 | display/prompt/rendered 精确中文 → rewrite |
| ③ 重复 | 同根多套夹具/一契约多 tracer | knowledge↔489、night core↔web、LLM 三叠、status_cn↔883 |
| ④ helper | 只测 helper/内部结构/常量自证 | 整文件或单测 delete |
| ⑤ 可改造 | 既有测试可改成真行为 | rewrite，优先不另加平行测 |

---

## 1. 第一刀：subprocess / LLM / 网络泄漏点名

### 1.1 已在 PR#1186 堵上的主泄漏（复证：仍 keep 契约，禁回退）

| 文件 | 原症 | 现状 | 处置 |
|---|---|---|---|
| `tests/test_session_cli_fallback.py` | `apply_cli_conversation_actions` → `classify_cli_action_intent` → `_run_agy` 实打 subprocess（单案 ~45s，整文件 ~386s） | 非 classifier 契约案已传 `preclassified_intent` 或 stub classify；显式 `_run_agy` mock 保留错误路径 | **keep** 契约 / 文件级纪律 **rewrite** 防回退 |
| `tests/test_secret_order_isolation_883.py` | production extract 路径未 mock classify（~90s+） | `test_976_production_*` 已 `preclassified_intent` | **keep** 🔒闸类 |

点名（历史烧额度案，现已堵，执行期回归时若再裸跑 classify 即违规）：

- `test_session_cli_fallback.py::test_conversation_rush_skips_pending_review`
- `test_session_cli_fallback.py::test_secret_conversation_actions_persist_complete_minister_reply[*]`
- `test_session_cli_fallback.py::test_non_streaming_path_surfaces_pending_action_id`
- `test_session_cli_fallback.py::test_non_parallel_safe_chat_serially_classifies_new_actions[*]`
- `test_session_cli_fallback.py::test_conversation_update_lands_via_session_path`
- `test_secret_order_isolation_883.py::test_976_production_extract_rush_progress_no_pure_public_pin`
- `test_secret_order_isolation_883.py::test_976_production_session_extract_update_withholds_oral`

### 1.2 本轮复核不构成泄漏的 apply 路径（曾被启发式打标，人工核后排除）

下列调用 `apply_cli_conversation_actions` 但 **未** 走裸 classify→subprocess：恢复窗短接 / resolve+extract stub / `_run_json_extractor_for_config` mock / API channel / session 方法桩。

| 文件::测试 | 为何不是泄漏 | 处置 |
|---|---|---|
| `test_chat_mutations_freeze.py::test_cli_prefix_secret_order_blocked_in_recovery_window` | stub `resolve_minister_actions`+extract；恢复窗短接 | keep 🔒 |
| `test_chat_mutations_freeze.py::test_nl_staged_actions_blocked_in_recovery_window` | 同上；断言 extractor 零调用 | keep 🔒 |
| `test_pending_actions.py::test_chat_proposal_not_staged_at_front_half_done` | FRONT_HALF_DONE 源头堵，不进 classify | keep 🔒 |
| `test_pending_actions.py::test_chat_confirm_defers_commit_at_front_half_done` | stub `extract_confirmation_intent` only | keep 🔒 |
| `test_pending_actions.py::test_front_half_done_directive_confirmation_commits_without_second_review` | 同上 | keep 🔒 |
| `test_dossier_links_559.py::test_real_cli_materialize_path_commits_only_semantically_confirmed_link` | mock `_run_json_extractor_for_config` | keep |
| `test_dossier_links_559.py::test_parallel_cli_bad_link_does_not_roll_back_valid_secret_order` | 同上 | keep |
| `test_dossier_links_559.py::test_real_web_stream_pending_commit_traces_only_confirmed_visible_links` | session.apply 桩返回空；API channel | keep |
| `test_audience_background.py::test_stream_confirmation_ignores_same_turn_secret_order_tool_output` | mock `_run_api_for_config` + FakeAgent | keep |
| `test_audience_background.py::test_background_audience_secret_order_persists_after_observer_departure` | `_cli_web_game` 桩 apply_calls，不实打 CLI | keep |

### 1.3 `test_cli_backend.py` runner 单测（subprocess **均 mock**，不烧额度；属 ④/⑤ 非 ①）

`test_run_agy_*` / `test_run_codex_*` / `test_run_claude_*` 全部 `monkeypatch.setattr(cb.subprocess, ...)`。**不删泄漏帽**；处置见 §4 该文件：rewrite 为公开 argv/错误契约或保持 mock 单测。

### 1.4 网络

全套 `tests/**` 未发现未 mock 的 `requests`/`httpx`/`urlopen` 实网调用。**网络泄漏：无。**

### 1.5 纪律（执行期）

1. 测试禁真 `subprocess` 调 agy/codex/claude 二进制。
2. `MING_SIM_LLM_BACKEND=agy|codex|claude` 出现时，必须同时有 `preclassified_intent` 或 `classify_cli_action_intent` stub 或 `_run_*`/`subprocess` mock。
3. 若遇 grok/agy **额度 403**：立即停，不重试烧额度。

---

## 2. 净增减账

### 2.1 相对一阶段冻结件的树增量（已发生）

| 变化 | 文件 | 节点估 |
|---|---|---:|
| 已删（PR#1186） | `test_load_observability.py`, `test_read_game_fixture.py` | −7 |
| 已改（P0 堵漏，非删案） | `test_session_cli_fallback.py`, `test_secret_order_isolation_883.py` | 0 |
| 新增（main 其后） | `test_authority_ledger_611.py` (18), `test_dossier_endorsements_612.py` (11), `test_override_breach_costs_564.py` (25) | +54 级 |
| **当前** | 130 files | **3081** |

### 2.2 本清单建议执行后的账（过庭后才动刀；本轮不执行）

| 动作 | 函数级 | 节点级 | 说明 |
|---|---:|---:|---|
| keep | 2108 | 2551 | 含 🔒 闸类 |
| rewrite | 320 | 398 | 改造成真行为/去盯文/参数化；节点数未必降 |
| merge | 94 | 99 | 合并后估净减 ~44 重叠节点 |
| delete | 33 | 33 | helper/私有/同义反复 |
| **预计净减节点** | | **−33 ~ −77** | delete + merge 重叠 |
| **预计保留节点** | | **~3004** | 相对 3081 |

时长账（继承冻结件粗算，本轮未重跑全量 durations，避免与评审争资源）：

| 项 | 粗算 |
|---|---|
| 冻结基线墙钟 | 1060s（17m40s） |
| P0 堵漏期望 | −480s 级（一阶段已落地，待收尾全量复证） |
| delete helper | −~2s |
| merge 去重 + setup 池化/参数化 | −20–40s 级（event_trigger/fiscal/conversational） |
| 票面终线 | ≤120s（需 xdist + 夹具池化，超出本审计腿） |

---

## 3. 合并簇与整文件 delete 总表

### 3.1 建议整文件 delete

| 文件 | 节点 | 理由 |
|---|---:|---|
| `test_suggestions_chips_527.py` | 1 | ④ `assert items == _PREFIX_ONLY` 同义反复 |
| `test_llm_key_helpers.py` | 5 | ④ 纯函数真值表；channel/runtime 已覆盖 |
| `test_qualitative.py` | 3 | ④ band/bucket 纯函数；projection 出口已用 |
| `test_distance_matrix.py` | 4 | ④ 纯矩阵数学，无游戏接缝 |
| `test_person_write_inventory.py` | 5 | ④ AST 扫描器/disposition 自测 |

（`test_load_observability.py` / `test_read_game_fixture.py` 已在 PR#1186 删除，不重复入账。）

### 3.2 建议 merge 簇

| 簇 | 成员 | 策略 |
|---|---|---|
| #489 知识投影 | `test_knowledge.py` + `test_character_knowledge_489.py` | 以 489 为锚；迁 knowledge 独有 archive/source_scope；删重叠 exclusion/counterpart |
| #498 夜宴 | `test_audience_night_498.py` + `test_web_audience_night_498.py` | core 留引擎；web 只留 ASGI/event-loop/fail-closed/inflight |
| 城防 | `test_region_citydefense.py` + `test_region_citydefense_display.py` | display 文案并入结构断言或删 |
| 密令状态/隔离 | `test_secret_order_status_cn.py` + `test_secret_order_isolation_883.py` | 隔离断言迁 883；状态桶改结构 |
| LLM 配置三叠 | `test_llm_channel_config.py` + `test_runtime_llm_config.py` + `test_web_llm_runtime_config.py` | 共享 load/save/placeholder 下沉；web 留 HTTP/menu |

### 3.3 闸类锁定（整文件默认 keep；内部可参数化不可删负向）

见冻结件 §3.4；本轮增补：`test_override_breach_costs_564.py`、`test_authority_ledger_611.py`。

---

## 4. 逐文件逐测试处置清单

图例：`keep` / `merge` / `delete` / `rewrite`。理由一句。节点数 = pytest 收集（含 parametrize）。

### `tests/test_action_cluster_registry_515.py`

- 规模：637 行 / 15 函数 / 16 节点 · 处置分布：`{'keep': 15}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_required_six_migrated_subset_of_registry` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_registry_row_carries_handler_and_fields_prompt_from_specs` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_registry_rows_generate_shape_contract_matrix` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_strict_shape_rejects_unknown_kind_and_out_of_enum_subfield` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_soft_llm_path_degrades_bad_shape_to_empty_list` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_normalize_preserves_none_vs_empty_list_semantics` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unrecognized_scripted_verdict_zero_writes` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scripted_appointment_stages_via_registry_materializer` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scripted_confirmation_answer_existing_no_new_stage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_finish_poisoned_classifier_yields_empty_list_not_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_non_parallel_cli_chat_materializes_each_top_level_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_chat_bidirectional_barrier_parallel_required` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_chat_poisoned_classifier_zero_writes` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_webgame_chat_create_then_undo_removes_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_webgame_cross_round_update_then_undo_restores_before_image` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_adr0015_per_item_rejection.py` 🔒

- 规模：263 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 8}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_persist_resolve_context_rejects_bad_items_and_saves_sanitized_delta` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_driver_validate_rejection_mirrors_jsonl_after_outer_atomic` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_validate_and_module_rejections_do_not_leak_into_player_visible_extraction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_player_visible_rejection_aggregates_durable_rows_across_attempts_and_resimulation` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_misrouted_module_field_becomes_rejection_not_only_trace` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_sqlite_text_sanitization_covers_resolve_report_and_extraction_rows` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_sqlite_text_sanitization_covers_issue_rows_and_advances` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_advance_paths_atomic.py` 🔒

- 规模：1412 行 / 33 函数 / 35 节点 · 处置分布：`{'keep': 33}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_advance_without_edict_atomic` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fallback_branch_atomic` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_crash_after_savestate_before_clear_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_code_exception_writes_pack_and_aborts` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_entry_resimulates_legacy_commitment_without_origin` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_entry_replays_modern_noop_without_origin` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_entry_consumes_ready_context` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recover_after_simulation_crash_can_resettle` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_path_commits_pending_actions` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_poison_replay_clears_context_for_resimulation` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_retry_replays_ready_context_without_reextract` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_submit_event_decision_persists_choice_after_pending_cleanup` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_submit_event_decision_binds_from_candidate_snapshot_without_event_id` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_ready_replay_retry_keeps_original_event_choice` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_submit_dossier_rescript_does_not_create_event_trigger` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_record_event_decision_choice_preserves_non_triggered_terminal_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_record_event_decision_choice_inserts_fresh_without_terminal_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_mark_event_triggered_upgrades_pending_choice_row` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_markers_upgrade_pending_choice_row` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_poison_replay_downgrades_context_then_reextracts` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_commit_rolls_back_with_failed_replay` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_reextract_branch_commits_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_escape_hatch_failure_does_not_mask_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resim_path_does_not_preconsume_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fallback_path_commits_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fallback_persists_sources_created_by_inertia_before_archive` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_restores_last_decree_for_web_display` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_recovery_replay_blocked_by_pending_directives` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_replay_blocked_by_pending_directives` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_skip_refused_at_front_half_done` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_draft_mutators_frozen_at_front_half_done` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_noready_recovery_uses_persisted_decree` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_reload_failure_propagates_raw_not_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_advances_section_rejections.py` 🔒

- 规模：156 行 / 10 函数 / 24 节点 · 处置分布：`{'keep': 10}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_advance_non_dict_item_rejected_not_crash` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_bad_issue_id_rejected` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_dirty_int_field_rejected` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_missing_issue_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_non_active_issue_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_valid_still_advances` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_code_exception_propagates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_missing_issue_no_metric_leak` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_non_active_issue_no_metric_leak` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_non_dict_metric_delta_tolerated` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_appease_mao_contract.py`

- 规模：184 行 / 6 函数 / 6 节点 · 处置分布：`{'keep': 6}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_appease_mao_active_issue_context_marks_character_loyalty_stop_condition` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_appease_mao_simulator_payload_marks_character_loyalty_stop_condition` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_simulator_projects_structured_character_stop_condition_but_keeps_machine_gate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_simulator_projects_issue_character_deltas_but_preserves_effect_details` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_appease_mao_commitment_bar_100_stays_active_until_explicit_close` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_appease_mao_commitment_rejects_direct_resolved_close_until_completion_flow` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_applier_contract.py`

- 规模：389 行 / 23 函数 / 23 节点 · 处置分布：`{'keep': 23}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_provenance_enum_values` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_provenance_from_string` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejected_item_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejected_item_constructs_with_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_section_result_holds_applied_and_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_section_result_merge` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_section_result_merge_empty` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_apply_context_holds_all_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejection_collector_flush_before_record_leaves_db_empty` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejection_collector_flush_writes_rows` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejection_collector_flush_clears_buffer` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejection_collector_flush_stores_item_as_json` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mirror_to_jsonl_writes_lines` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mirror_to_jsonl_appends_on_multiple_calls` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mirror_to_jsonl_empty_buffer_writes_nothing` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_flush_then_mirror_writes_jsonl` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mirror_idempotent_after_flush` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unflushed_rows_never_mirrored` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reset_discards_pending_and_flushed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_record_accepts_plain_string_source` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_record_rejects_unknown_source_string` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_collector_counts_deterministic_on_polluted_save` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ddl_in_open_transaction_rolls_back` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_appointment_tenure_607.py`

- 规模：208 行 / 6 函数 / 13 节点 · 处置分布：`{'keep': 6}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_appointment_dossier_and_office_archive_preserve_each_tenure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_appointment_defaults_to_permanent_without_rejudging` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_person_delta_rejects_invalid_appointment_tenure_without_mutation` | 8 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_failed_dossier_reappointment_rolls_back_audit_and_sequence` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_appointment_tenure_survives_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_acting_appointment_can_be_reappointed_permanent_on_same_path` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_army_display_173.py`

- 规模：212 行 / 9 函数 / 9 节点 · 处置分布：`{'keep': 7, 'rewrite': 2}` · 主注：②⑤ 中文金额串盯文

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_army_payload_exposes_army_needed` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_army_report_shows_actual_charge` | 1 | **rewrite** | ② 精确中文金额/展示串 |
| `test_army_arrears_presentation_reports_approx_total_and_hides_abstract_stats` | 1 | **rewrite** | ② 精确中文金额/展示串 |
| `test_army_arrears_presentation_rounds_half_steps_up` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_army_payload_preserves_fractional_arrears_for_web_rendering` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_simulator_payload_exposes_army_needed` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_danger_order_uses_army_needed_for_arrears_months` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_danger_order_preserves_fractional_arrears` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |
| `test_army_rows_non_danger_sorted_by_theater_name` | 1 | **keep** | 真行为 army_needed 数值/schema 契约 |

### `tests/test_army_firearms.py`

- 规模：226 行 / 16 函数 / 16 节点 · 处置分布：`{'keep': 16}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_score_fields_include_firearm_and_cannon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_armies_table_has_firearm_columns` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_army_defaults_zero_firearm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_apply_army_delta_sets_firearm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_firearm_clamped_0_100` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cannon_clamped_to_12` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_create_army_with_firearm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_create_army_cannon_count_clamped` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_detail_shows_firearm_cannon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_report_shows_firearm_and_cannon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_detail_dynamic_new_army_shows_firearm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fresh_seed_wires_firearm_not_all_zero` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_create_army_cannon_nonint_rejected_not_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_apply_army_delta_chinese_keys` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_simulator_payload_includes_firearm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_roster_shows_firearm_cannon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_army_maintenance_retire_173.py`

- 规模：175 行 / 10 函数 / 12 节点 · 处置分布：`{'keep': 10}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_armies_table_has_no_maintenance_column` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drop_maintenance_column_removes_and_idempotent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_existing_save_drops_maintenance_column_on_open` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_new_army_needs_only_manpower` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_army_maintenance_key_ignored` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_army_still_requires_manpower` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_army_inf_manpower_rejected_not_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pay_derives_from_manpower` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_delta_maintenance_rejected_as_invalid_field` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_delta_other_fields_still_apply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_army_pay_source_prompt_contract.py`

- 规模：44 行 / 1 函数 / 1 节点 · 处置分布：`{'keep': 1}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_prompt_compatible_ming_new_army_pay_source_aliases_land` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_army_salary_44.py`

- 规模：351 行 / 19 函数 / 24 节点 · 处置分布：`{'keep': 19}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_army_needed_derives_from_manpower_rate` | 5 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_needed_zero_manpower_zero_pay` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_needed_scales_with_manpower` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_needed_shrink_lowers_pay` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_needed_non_ming_no_pay` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_defected_army_to_ming_owes_salary_not_free` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_backfill_dynamic_army_falls_to_anchor` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_backfill_reverse_fills_from_maintenance_on_direct_upgrade` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_backfill_anchor_when_column_present_but_data_unusable` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_total_ming_salary_is_72_ceil_sum` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_manpower_clamp_to_zero_leaves_army_log` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_manpower_true_noop_no_log` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_auto_pay_reaches_salary_army_via_arrears_filter` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_auto_pay_empty_allowed_ids_pays_no_armies` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_auto_pay_strips_allowed_army_ids_before_filtering` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_salary_tick_preserves_fractional_opening_arrears` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_coerce_new_salary_rate_blocks_freeload` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_non_finite_salary_rate_anchored_not_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_twelve_turns_no_arrears_explosion` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_background.py`

- 规模：744 行 / 20 函数 / 22 节点 · 处置分布：`{'keep': 20}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_chat_stream_observer_departure_after_acceptance_still_completes_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_reload_exposes_retryable_failed_secret_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_chat_response_preserves_retryable_failed_secret_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_reply_preserves_emperor_mode_after_observer_departure` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stream_tool_staged_secret_order_merges_minister_reply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stream_confirmation_ignores_same_turn_secret_order_tool_output` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stream_secret_order_tool_blocked_in_recovery_window` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stream_secret_order_plain_tool_result_does_not_stage_empty_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_uses_session_augmented_audience_prompt` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_does_not_expose_unissued_draft_to_uninvolved_minister` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_projects_return_report_with_derived_source` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_does_not_create_near_minister_report_for_ordinary_minister` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_secret_order_persists_after_observer_departure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_pending_action_persists_after_observer_departure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_appointment_stages_after_observer_departure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_recommendation_stages_candidate_snapshot` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_llm_failure_does_not_leave_half_chat_in_history` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_background_audience_failure_after_action_rolls_back_cleanly` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_rejects_second_concurrent_turn_same_minister` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_closed_before_turn_creation_is_noop` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_continuous_507.py`

- 规模：236 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 8}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_scene_recap_quotes_public_dialogue_within_presence_interval` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scene_recap_excludes_dialogue_before_person_entered` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_carries_heard_hall_dialogue_for_present_attendant` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_qianqing_continuous_night_skeleton_runs` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reply_input_routes_per_character_knowledge_not_one_answer_for_all` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_excludes_hall_dialogue_after_command_dismiss` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audience_prompt_excludes_hall_dialogue_after_extraction_exit` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_present_roster_reflects_both_exit_paths_single_core` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_extraction_501.py` 🔒

- 规模：796 行 / 29 函数 / 35 节点 · 处置分布：`{'keep': 29}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_parse_extraction_facts_accepts_valid_and_keeps_presence` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_parse_extraction_facts_rejects_bad_shape` | 7 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_extraction_ledgers_staging_fact` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_extraction_bad_shape_writes_error_pack_and_marks_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_watermark_idempotent_no_double_ledger` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_is_atomic_all_or_nothing` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_catch_up_extracts_persisted_reply_without_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_catch_up_persistent_failure_does_not_lock_and_marks_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_catch_up_processes_source_turns_serially_even_on_parallel_safe_backend` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_present_roster_consumes_presence_effect_not_freetext` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extraction_exit_with_open_tag_leaves_all_presence_derivers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_present_roster_ignores_unextracted_reply` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extraction_order_key_lands_at_source_turn_position` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_drain_before_close_clears_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_drain_before_close_fail_closed` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_reply_trail_ledgers_via_real_wiring` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_trail_extraction_runs_after_reply_persist` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_trail_extraction_failure_marks_pending_not_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_await_inflight_does_not_pre_drain_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_refuses_on_closed_night` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_refuses_dead_actor_enter_but_allows_mention` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extraction_open_tag_enter_does_not_drive_presence` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dead_actor_open_tag_enter_does_not_bypass_dead_check` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_engine_close_night_drains_pending_success` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_engine_close_night_fail_closed_on_boom` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_engine_close_night_fail_closed_without_deps` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settle_failure_surfaces_pending_never_throws` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_blank_reply_marked_done_and_closeable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_readable_and_retry_via_web` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_audience_night_498.py` 🔒

- 规模：637 行 / 17 函数 / 17 节点 · 处置分布：`{'keep': 17}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_open_summon_close_chain_readable_by_night` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_summon_method_and_bad_method` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_two_nights_isolated_and_timeline_alignable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_chat_completion_via_attach` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_attach_without_scene_anchors_persists_readable_defaults` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dead_person_enter_rejected_with_error_pack` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_standing_roster_skips_dead` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_auto_closes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_write_decree_leaves_unacted_pending_unchanged` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cross_night_directive_reassigned_to_second_night` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_night_crash_then_reopen_db_resumes_idempotent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_night_only_commits_this_night_approved` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_closing_cursor0_reopen_refuses_new_and_explicit_resume_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_night_atomic_on_dead_roster_injection` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_old_save_migration_night_id_index_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bad_audibility_and_append_after_close` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_minister_chat_anchors_turn_to_night` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_audience_pipeline_499.py`

- 规模：528 行 / 13 函数 / 13 节点 · 处置分布：`{'keep': 13}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_mindreading_eligible_skips_self_and_missing_slot` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_run_mindreading_for_turn_persists_and_survives_failed_turn_guard` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_done_before_mindreading_and_delivers_event` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_action_intent_overlaps_reply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_poll_path_after_stream` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_build_chat_projection_weaves_mindreading_by_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_failed_mindreading_marks_terminal_and_stops_pending` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_chat_persistence_atomically_accepts_mindreading_task` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_persist_minister_reply_atomic_transaction_rolls_back` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_startup_reconcile_via_real_close_reopen` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_backfill_upgraded_save_reopen_not_pending` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pending_turn_ids_covers_all_pending_turns_not_only_latest` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_pending_flag_guides_bounded_poll` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_presence_500.py`

- 规模：403 行 / 12 函数 / 14 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_dismiss_command_updates_roster_immediately` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_dismiss_noop_when_not_present` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_dismiss_via_cli_command_writes_exit_ledger` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_court_break_writes_no_exit_ledger` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_session_chat_tool_dismiss_writes_exit_ledger` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_session_chat_non_dismiss_leaves_present` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reenter_after_exit_reappears_in_roster` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_transit_rejects_bad_method` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_present_names_at_table` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_present_names_at_uses_timeline_key_not_raw_seq` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_standing_roster_present_throughout` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audible_interval_public_only` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_restore_505.py`

- 规模：506 行 / 13 函数 / 13 节点 · 处置分布：`{'keep': 13}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_reopen_reconcile_preserves_ledger_exactly` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reopen_reconcile_unblocks_and_keeps_question` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reconcile_leaves_completed_turn_untouched` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reconcile_does_not_delete_question_row` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pure_audience_zero_ledger_turn_survives_reopen` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_retry_regenerates_reply_without_duplicate_question` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_retry_without_interrupted_turn_is_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_failed_retry_rolls_back_side_effects_and_keeps_question` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lost_reopen_cas_rejects_without_second_reply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_retry_rejected_in_settlement_phase` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reconcile_truncates_agno_runs_to_turn_start` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reconcile_marks_questionless_orphan_failed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_load_save_reconciles_interrupted_orphan` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_scroll_539.py`

- 规模：416 行 / 18 函数 / 18 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_real_player_sse_replaces_closed_same_turn_night_before_failed_reply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_live_and_closed_night_share_the_real_http_contract` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scroll_contract_merges_both_stores_with_container_and_coda` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_presence_commands_project_to_diegetic_scene_beats` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scroll_derives_soft_boundary_and_omits_dialogue_carried_action` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scroll_merges_mindreading_and_uses_structured_dedup_boundaries` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_extractor_open_tags_do_not_drive_beat_or_soft_boundary` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scroll_container_presents_audience_type_from_persisted_summon_method` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_scroll_without_next_entrance_has_unnamed_boundary` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_departure_facts_emit_one_divider_but_later_departure_survives` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_history_turns_lists_every_closed_night_including_night_only_turns` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_closed_night_archive_derives_stable_titles_people_and_no_content` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_closed_night_archive_batches_each_metadata_store_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_read_night_scroll_reads_each_metadata_store_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_personal_projection_only_reads_the_current_open_night` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ending_timeline_consumes_monthly_archive_once_not_scene_rows` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_history_projection_handlers_are_sync_for_sqlite_access` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_audience_undo_506.py`

- 规模：585 行 / 17 函数 / 17 节点 · 处置分布：`{'keep': 17}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_undo_erases_round_from_night_ledger_and_presence` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_rejected_after_night_closed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_extraction_skips_dead_round_but_writes_live_round` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_night_direct_write_whitelist_enumerates_two_items` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_audit_passes_whitelisted_and_catches_unwhitelisted_night_write` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_removes_unlisted_person_registration` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_full_reversal_survives_kill_and_reopen` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_pending_extraction_leaves_no_orphan_retry` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_reversal_is_atomic_on_midway_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_confirm_round_reverts_pending_to_unapproved` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_restores_staging_row_deleted_by_verbal_reject` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_landed_secret_decree_removes_all_structured_records` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_dismiss_round_removes_exit_ledger_and_restores_presence` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_single_round_enter_and_dismiss_equals_not_happened` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_attach_origin_bind_atomic_no_orphan_enter_on_midway_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_attach_origin_bind_atomic_normal_path_binds_and_undo_deletes` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_survives_db_created_before_undone_at_column` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_authority_ledger_611.py` 🔒

- 规模：540 行 / 13 函数 / 14 节点 · 处置分布：`{'keep': 13}` · 主注：真行为🔒 新 #611

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_authority_changes_alias_canonicalizes_chinese_and_english_op_locally` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_authority_op_alias_does_not_rewrite_other_sections_action_field` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_production_path_grant_restore_revoke_impression_tracer` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_authority_changes_rejects_ineligible_keeps_legal_peer` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_projection_typed_domain_only_and_ignores_payload_authorization` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_same_dossier_grant_replay_is_idempotent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_same_dossier_grant_replay_returns_terminal_origin_without_regrant` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_duplicate_active_authority_is_rejected_across_dossiers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_duplicate_check_uses_current_turn_not_future_effective_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_duplicate_check_ignores_authority_only_active_in_future` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_production_rejects_bare_domain_scope` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_payload_does_not_write_authority_records` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_judge_instructions_cover_held_authority_modifiers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_bandit_power_model_190.py`

- 规模：99 行 / 4 函数 / 4 节点 · 处置分布：`{'keep': 4}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_seed_splits_li_zicheng_and_zhang_xianzhong_bandit_powers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_old_save_schema_init_backfills_bandit_power_split` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_bandit_power_backfill_serializes_list_aliases` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_bandit_power_split_backfill_preserves_changed_owner` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_beat_orchestration_503.py`

- 规模：518 行 / 17 函数 / 17 节点 · 处置分布：`{'keep': 17}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_enter_beat_varies_by_identity_and_method` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_enter_beat_time_location_from_night_container_not_call_arg` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_whitespace_generator_falls_back_to_deterministic_bodies` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_close_night_skips_generator_when_body_given_or_already_closed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_enter_generator_raise_on_new_night_leaves_zero_writes` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_open_and_close_beat_bodies_land` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_no_generator_keeps_deterministic_fallback` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_production_generator_varies_enter_body_by_identity` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_web_start_chat_turn_wires_production_beat_generator` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_second_summon_inputs_include_prior_enter_and_audience` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_beat_inputs_carry_no_form_constraint_or_naked_number` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_generator_called_with_only_beat_inputs_no_constraints` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_enter_input_flows_from_injected_knowledge_provider` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_frame_beats_flow_from_provider_and_vary` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_assembly_never_calls_omniscient_builders` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_court_tension_routed_from_default_provider` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_public_layer_excludes_private_whispers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_character_knowledge_489.py` 🔒

- 规模：993 行 / 52 函数 / 52 节点 · 处置分布：`{'keep': 52}` · 主注：③🔒 #489 合并锚

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_role_roster_only_lists_current_active_ming_people` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_chapter_aggregate_never_projects_paraphrased_restricted_source` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_alias_exclusion_is_canonicalized_before_projection` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_order_commit_recovers_named_alias_and_office_targets_from_content` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_order_commit_recovers_non_disclosure_clause` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_order_tool_path_canonicalizes_omitted_exclusions_before_staging` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_every_supported_office_type_has_a_role_specific_current_world_slice` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_every_character_office_type_has_a_content_knowledge_mapping` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_generic_offices_receive_distinct_current_world_slices` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_office_slice_does_not_read_unrelated_sensitive_reports` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_every_distinct_office_type_gets_a_distinct_current_world_slice` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_role_slice_contains_only_the_current_office_roster` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_different_office_types_do_not_share_the_same_role_facts` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_office_knowledge_domains_are_loaded_from_content` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_current_state_facts_are_selected_by_content_domain_not_role_label` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_turn_zero_knowledge_is_role_specific_and_restores` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_restored_knowledge_uses_current_db_office_after_transfer` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_public_directive_is_seen_by_uninvolved_minister_but_secret_exclusion_wins` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_turn_report_keeps_source_specific_secret_exclusion_boundary` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_turn_report_projects_public_and_secret_items_per_character` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_participation_survives_restore` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_undo_chat_turn_removes_chat_derived_knowledge_from_context` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_undo_chat_turn_removes_turn_scoped_near_minister_report` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_failed_chat_turn_removes_turn_scoped_near_minister_report_but_keeps_prior_one` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_undo_chat_turn_keeps_preexisting_identical_near_minister_report` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_delete_chat_messages_removes_chat_derived_knowledge_from_context` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_public_directive_remains_visible_on_a_later_turn` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_excluded_participant_event_is_not_visible_to_excluded_character` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_blacklist_survives_later_public_projection` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_public_reports_accumulate_across_turns` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_participation_record_adapter_covers_assignment_shape` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_issue_write_path_projects_participants_across_restore` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_knowledge_world_keeps_countable_fiscal_facts_but_not_abstract_axes` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_office_exclusion_does_not_hide_unrelated_world_bucket` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_office_snapshot_keeps_explicit_people_target_separate` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_office_exclusion_snapshots_people_before_transfer_and_publication` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_disclosed_secret_source_keeps_its_public_projection` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_public_disclosure_drops_private_roster_but_keeps_event_exclusion` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_long_knowledge_bodies_survive_storage_without_brief_card_cap` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_amendment_preserves_legacy_blacklist_and_public_disclosure` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_exclusion_is_source_scoped_not_global_for_same_bucket` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_issue_roster_is_structured_and_read_side_projection_needs_no_write_hook` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_participation_adapter_reads_structured_roster_without_fake_names` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_new_participation_source_is_projected_without_read_side_type_branch` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_participant_roster_is_discovered_from_persistent_record_without_adapter` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_office_blacklist_preserves_unrelated_court_domain_fact` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_event_office_blacklist_matches_current_office_name` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_participant_roster_is_discovered_from_any_persistent_table` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_appended_dossier_participant_learns_only_on_join_turn_after_restore` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_decree_dossier_participant_reads_frozen_metadata_and_text` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_secret_order_dossier_never_leaks_through_shared_roster_projection` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |
| `test_knowledge_titles_restore_without_persistence_truncation` | 1 | **keep** | 🔒③ #489 知识投影主锚（合并 knowledge 时保留） |

### `tests/test_character_projection_1023.py`

- 规模：78 行 / 2 函数 / 2 节点 · 处置分布：`{'keep': 2}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_simulator_context_projects_character_axes_but_keeps_world_numbers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_character_projection_allows_memorial_wealth_approximation_without_an_exact_wealth_field` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_chat_mutations_freeze.py` 🔒

- 规模：181 行 / 6 函数 / 6 节点 · 处置分布：`{'keep': 6}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_appointment_blocked_in_recovery_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unlisted_person_blocked_in_recovery_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_tool_blocked_in_recovery_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_tool_progress_allows_same_month_correction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_prefix_secret_order_blocked_in_recovery_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nl_staged_actions_blocked_in_recovery_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_chat_stream_failpaths_393.py`

- 规模：209 行 / 3 函数 / 3 节点 · 处置分布：`{'rewrite': 3}` · 主注：④⑤ 私有 gate 耦合

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_prologue_failure_fails_orphan_turn_and_releases_gate` | 1 | **rewrite** | ④⑤ 私有 _write_gate → 公开错误/串行行为 |
| `test_prologue_cleanup_failure_still_releases_gate_and_counter` | 1 | **rewrite** | ④⑤ 私有 _write_gate → 公开错误/串行行为 |
| `test_worker_cleanup_failure_still_emits_error_and_releases_gate` | 1 | **rewrite** | ④⑤ 私有 _write_gate → 公开错误/串行行为 |

### `tests/test_cli_backend.py`

- 规模：1832 行 / 135 函数 / 137 节点 · 处置分布：`{'rewrite': 90, 'keep': 35, 'delete': 10}` · 主注：④⑤② 私有 _extract/_infer 删；runner/密令公共面留/改

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_draft_prefix_captures_reply` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_no_prefix_no_action` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_merges_emperor_intent_with_reply` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_exclusion_extracts_people_and_offices` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_secret_order_preserves_long_title_without_formal_cap` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_exclusion_recovery_splits_each_explicit_person` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_exclusion_recovery_covers_target_first_and_imperative` | 2 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_exclusion_recovery_covers_common_clause_and_shipped_office` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_exclusion_recovery_covers_non_disclosure_clause` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_cli_and_durable_secret_exclusion_share_the_same_parser` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_prefix_deadline_only_confirmation_uses_recent_context` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_bad_llm_content_still_keeps_emperor_intent` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_partial_llm_content_still_keeps_emperor_intent` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_llm_keeps_emperor_but_drops_minister_assignee` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_assignee_defaults_when_unspecified` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_llm_keeps_assignee_field_but_drops_from_content_merges` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_llm_keeps_emperor_but_drops_minister_supplements` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_extract_assignee_hint_does_not_corrupt_name_with_trailing_verb` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_assignee_hint_keeps_cao_surname_characters` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_assignee_hint_greedy_strip_handles_all_verb_tails` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_assignee_action_pulls_verb_after_name` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_assignee_action_uses_hint_match_when_name_repeats` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_content_reflects_supplements_rejects_name_only_when_action_dropped` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_content_reflects_supplements_uses_hint_tail_when_name_repeats` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_content_reflects_supplements_accepts_when_name_and_action_preserved` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_acknowledgment_only_replies_are_not_material` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_mixed_acknowledgment_and_material_replies_ignore_ack_clauses` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_content_reflects_supplements_rejects_when_tail_material_dropped` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_extract_assignee_hint_keeps_wei_and_si_surnames` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_assignee_hint_prefers_long_compound_prefixes` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_extract_imperative_assignee_requires_command_boundary` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_clause_split_handles_colons_and_newlines` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_assignee_does_not_drift_to_unvalidated_llm_field` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_assignee_prefers_hint_when_bad_llm_field_survives_merge` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_assignee_uses_emperor_imperative_hint_when_llm_blank` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_prefix_action_word_dropped_triggers_merge` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_plain` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_code_fence` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_with_prose_around` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_garbage_none` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_enrich_army_parsed_and_normalized` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_enrich_building_region_floor` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_backend_env` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_backend_env_claude` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_claude_stdout_only` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_backend_dispatch_claude` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_backend_dispatch_default_agy` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_backend_dispatch_codex` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_enrich_backend_error_returns_empty_effects` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_secret_extract_backend_error_falls_back` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_recovers_explicit_exclusion_when_backend_omits_it` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_recovers_office_exclusion_when_backend_fails` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_merges_office_exclusion_when_backend_omits_it` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_classifies_institutional_knowledge_ban_as_office` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_classifies_institutional_title_knowledge_ban_as_office` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_classifies_office_title_knowledge_ban_as_office` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_classifies_grand_secretariat_title_knowledge_ban_as_office` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_classifies_shipped_hanlin_targets_as_offices` | 2 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_run_codex_flags_and_stdout` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_codex_streaming_runner_degrades_to_oneshot_final` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_clichat_codex_response_stream_passes_reasoning_strength` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_api_backend_streaming_emits_real_token_deltas` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_codex_stream_watchdog_kills_hung_process` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_codex_final_text_handles_item_completed_shape` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_codex_accepts_config_model_and_timeout` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_reasoning_env_optional` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_maps_reasoning_strength_to_native_effort` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_stdout_empty_fallback` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_accepts_config_model_and_timeout` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_maps_reasoning_strength_to_thinking_tokens` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_off_reasoning_uses_explicit_minimum_tokens` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_resolve_cli_bin_found_on_current_path` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_resolve_cli_bin_login_shell_path_last_resort` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_resolve_cli_bin_falls_back_to_name_when_truly_missing` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_resolve_cli_bin_caches` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_login_shell_path_extracts_from_sentinels_despite_noise` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_login_shell_path_single_dir_not_dropped` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_resolve_cli_bin_does_not_cache_miss` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_login_shell_path_uses_printenv_not_dollar_path` | 1 | **keep** | 真行为 CLI 二进制解析/路径契约（subprocess mock） |
| `test_resolve_cli_bin_absolutizes_relative_result` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_codex_execs_resolved_abspath` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_execs_resolved_abspath` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_agy_execs_resolved_abspath` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_extract_minister_actions_update` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_minister_actions_preserves_long_new_title` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_minister_actions_none` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_minister_actions_cultivate` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_minister_actions_backend_error_safe` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_extract_minister_actions_nonint_ids_floor_to_zero` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_infer_tag_each_branch` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_infer_tag_order_minister_wins_over_decree` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_infer_tag_chapter_memory_before_extractor` | 1 | **delete** | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_messages_to_prompt_role_tags_and_order` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_messages_to_prompt_skips_empty_and_none` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_messages_to_prompt_unknown_role_and_nonstr_content` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_messages_to_prompt_json_object_constraint` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_messages_to_prompt_basemodel_constraint` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_messages_to_prompt_no_json_no_constraint` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_strip_narration_removes_leading_english` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_strip_narration_skips_blank_then_strips` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_strip_narration_pure_chinese_unchanged` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_strip_narration_all_narration_falls_back_to_original` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_braces_but_invalid_json` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_jsonc_trailing_comma_stripped` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_preserves_comma_brace_in_string` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_preserves_double_slash_in_string` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_preserves_url_in_string` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_array_trailing_comma` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_escaped_quote_then_slashes_in_string` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_agy_success_first_attempt` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_agy_auth_race_then_success` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_agy_all_timeout_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_agy_all_auth_fail_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_timeout_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_timeout_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_nonzero_exit_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_codex_empty_output_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_claude_nonzero_exit_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_run_agy_nonzero_exit_retries_then_raises` | 1 | **rewrite** | ⑤ runner 私有入口：经 subprocess mock 可改造成 argv/错误公开契约，勿实打二进制 |
| `test_clichat_invoke_strips_narration_before_parse` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_clichat_invoke_error_traced_and_reraised` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_loads_lenient_strips_jsonc_comments_and_trailing_comma` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_keeps_url_double_slash` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_loads_lenient_valid_json_with_comma_brace_in_value_not_mangled` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_extract_minister_actions_unknown_action_floored` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_enrich_nondict_subfields_guarded` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_enrich_trace_records_actual_backend` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_clichat_call_cli_dispatch` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_clichat_call_cli_unknown_backend_raises` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_backend_for_config_traces_every_call` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_run_backend_for_config_passes_reasoning_strength_to_codex` | 1 | **rewrite** | ⑤ cli_backend 面去私有耦合 |
| `test_run_backend_for_config_traces_on_backend_error` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_office_inference_llm_call_is_traced` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |
| `test_secret_extract_traces_exactly_once` | 1 | **keep** | 真行为 密令/抽取/规范化公共出口（backend 已 mock） |

### `tests/test_cli_model_choices.py`

- 规模：137 行 / 12 函数 / 12 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_choices_cover_all_supported_runners` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_each_runner_has_default_escape_option_first` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_default_labels_reuse_single_source_constants` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_default_label_reflects_env_override` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_codex_offers_spark_fast_tier` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_claude_offers_haiku_and_sonnet_tiers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_curated_values_are_lowercase_known_ids` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_choices_returns_independent_copies` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_menu_status_exposes_choices` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_menu_status_exposes_raw_cli_model_saved_default` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_menu_status_cli_model_saved_passes_explicit` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_get_llm_config_exposes_choices` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_cli_play_turn.py` 🔒

- 规模：619 行 / 15 函数 / 17 节点 · 处置分布：`{'keep': 15}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_issue_refusal_stays_in_loop` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_review_issue_reaches_staged_directive_default_approval` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_persists_messages_before_session_chat` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_removes_user_message_when_session_chat_fails` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_preserves_chat_error_when_rollback_fails` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_reply_persist_failure_keeps_user_message` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_persistent_chat_finalization_failure_rolls_back_real_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_can_retry_failed_secret_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_minister_chat_blocks_retry_during_settlement_recovery` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_failure_printer_preserves_zero_id` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_play_turn_reports_default_approval_secret_order_failure` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_play_turn_skip_settlement_abort_stays_in_player_loop` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_play_turn_reports_secret_order_failure_when_settlement_aborts` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_close_issues_section_rejections.py` 🔒

- 规模：202 行 / 12 函数 / 19 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_close_bad_issue_id_rejected` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_non_dict_item_rejected_not_crash` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_bad_reason_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_unknown_issue_rejected_missing_ref` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_overflow_issue_id_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_already_inactive_rejected_missing_ref` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_failed_on_uncollapsible_rejected_invalid_enum` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_rejection_reaches_rejection_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_effect_brief_ignores_rejected_closes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_scalar_item_rejection_preserves_original_in_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_issue_code_exception_propagates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_valid_issue_still_succeeds` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_commitment_display_348.py`

- 规模：338 行 / 24 函数 / 24 节点 · 处置分布：`{'keep': 2, 'rewrite': 22}` · 主注：②⑤ 展示盯文/回合泄漏真契约混杂

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_no_absolute_month_in_text` | 1 | **keep** | 真行为 防绝对回合号泄漏 |
| `test_shows_total_duration` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_shows_elapsed_months` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_shows_remaining_months` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_remaining_clamps_to_zero` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_no_absolute_month_in_passive_text` | 1 | **keep** | 真行为 防绝对回合号泄漏 |
| `test_shows_duration_in_passive_text` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_passive_still_says_dao_qi_dai_cai` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_arrears_type_unchanged` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_goal_gate_type_unchanged` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_open_commitment_unchanged` | 1 | **rewrite** | ② 中文展示词盯文→结构/枚举 |
| `test_returns_time_based_percentage` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_at_full_duration_returns_100` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_clamps_to_100_when_overrun` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_at_zero_elapsed_returns_zero` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_returns_none_for_no_end_turn` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_returns_none_for_stop_gate` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_returns_none_for_arrears_gate` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_returns_none_for_passive_timed` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_bar_advances_by_wall_clock_when_ongoing_advance_is_rejected` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_bar_advances_with_time` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_bar_at_initial_turn_is_zero` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_origin_turn_null_falls_back_to_state_turn` | 1 | **rewrite** | ②⑤ 展示面改造 |
| `test_origin_turn_missing_key_falls_back_to_state_turn` | 1 | **rewrite** | ②⑤ 展示面改造 |

### `tests/test_conversational_draft.py`

- 规模：1892 行 / 56 函数 / 77 节点 · 处置分布：`{'keep': 51, 'rewrite': 5}` · 主注：②⑤ prompt 盯文可去

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_conversational_draft_intent_stages_pending` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_new_conversational_draft_uses_emperor_mode_over_extractor` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_no_draft_pending_when_no_intent` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_explicit_prefix_stages_same_pending_directive_as_natural_language` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_last_write_wins` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_real_conversation_draft_supplement_preserves_and_appends_roster` | 21 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_commit_creates_turn_directive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_commit_failure_propagates_and_rolls_back_outer_atomic` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_dialogue_affirm_commits_pending_directive_to_later_ui` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_dialogue_reject_drops_pending_directive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_explicit_secret_order_prefix_stages_pending_candidate` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_natural_language_secret_order_stages_pending_candidate` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_secret_order_status_query_does_not_stage_new_hidden_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_secret_order_progress_query_does_not_stage_new_hidden_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_secret_order_chaban_query_does_not_stage_new_hidden_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_new_secret_order_with_existing_order_stages_only_new_candidate` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_dialogue_reject_drops_pending_new_secret_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_dialogue_affirm_commits_pending_new_secret_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_no_reply_path_directive_reachable_by_list_directives` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_count_nonzero_after_conversational_draft` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_count_zero_after_commit` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_pending_directive_count_zero_without_any_draft` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_prompt_includes_supplement_hint_when_has_pending` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_supplement_schema_keeps_valid_json_comma` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_coerces_non_string_existing_draft_text` | 1 | **rewrite** | ② 对 prompt 自由文本机械依赖 |
| `test_extract_draft_intent_no_supplement_hint_when_no_pending` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_last_write_wins_uses_has_pending_draft_flag` | 1 | **rewrite** | ② 对 prompt 自由文本机械依赖 |
| `test_draft_request_with_appointment_content_stages_directive_not_office` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_structured_verdict_alone_routes_natural_language_action` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_none_player_message_does_not_crash_draft_probe` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_discard_pending_directives_does_not_commit_outer_transaction` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_supplement_stores_merged_draft_not_raw_reply` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_undo_chat_turn_removes_write_decree_draft` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_supplement_mode_falls_back_to_existing_draft_when_merged_empty` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_supplement_mode_prefers_merged_when_present` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_backend_exception_degrades_to_none` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_non_object_json_degrades_to_none` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_dirty_action_normalized_to_none` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_extract_draft_intent_no_intent_returns_empty_draft_text` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_supplement_existing_draft_text_swallows_malformed_payload_json` | 1 | **rewrite** | ② 对 prompt 自由文本机械依赖 |
| `test_supplement_existing_draft_text_ignores_non_object_payload_json` | 2 | **rewrite** | ② 对 prompt 自由文本机械依赖 |
| `test_supplement_existing_draft_text_accepts_preparsed_payload_json` | 1 | **rewrite** | ② 对 prompt 自由文本机械依赖 |
| `test_commit_directive_with_empty_text_returns_false_no_archive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_commit_pending_actions_rejects_conflicting_kind_filters` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_commit_directive_actor_falls_back_to_minister_name` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_commit_directive_rolls_back_draft_when_bookkeeping_update_fails` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_confirm_gate_does_not_sweep_conversational_directive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_confirm_reject_does_not_delete_conversational_directive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_targeted_directive_rejection_does_not_drop_secret_order` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_write_decree_rejects_before_committing_conversational_directive` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_undo_chat_turn_preserves_unrelated_same_actor_draft` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_undo_supplement_turn_removes_committed_draft` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_stale_decree_not_issued_when_new_draft_created_after_generation` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_supplied_decree_not_used_after_pending_directive_auto_commit` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_undo_clears_generated_decree_when_committed_draft_deleted` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |
| `test_normal_undo_keeps_valid_decree` | 1 | **keep** | 真行为 pending LWW/拟旨状态契约 |

### `tests/test_db_broad_except_surface.py`

- 规模：197 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 8}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_pending_decisions_corrupt_options_json_falls_back_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pending_decisions_corrupt_choice_json_returns_none_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_resolve_context_corrupt_payload_falls_back_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_resolve_context_corrupt_secret_orders_falls_back_to_dict_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_resolve_context_corrupt_extracted_returns_none_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_relevant_memories_corrupt_tags_no_crash_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_keyword_memories_corrupt_tags_no_crash_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_modifiers_corrupt_json_skips_and_surfaces` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_decision_event_binding_389.py`

- 规模：64 行 / 6 函数 / 6 节点 · 处置分布：`{'keep': 6}` · 主注：④ 绑定纯函数真源，单元可留

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_missing_event_id_binds_from_unique_title` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_valid_echoed_event_id_is_trusted_unchanged` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_offsnapshot_echoed_event_id_does_not_win_over_snapshot` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_offsnapshot_id_with_no_title_match_is_unbound` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ambiguous_title_remains_unbound` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_no_snapshot_returns_decisions_unchanged` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_decree_commitment_creation_136.py`

- 规模：1221 行 / 33 函数 / 33 节点 · 处置分布：`{'keep': 33}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_until_stop_commitment_issue_is_created_with_carrier_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_commitment_dedups_same_batch_fiscal_create_carrier` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_commitment_does_not_dedup_same_name_income_fiscal_create` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_commitment_same_account_alias_miss_emits_residual_signal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_commitment_unrelated_account_no_residual_signal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_shape_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_limited_duration_commitment_shape_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_limited_duration_ongoing_commitment_rejects_current_turn_end_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_limited_duration_ongoing_commitment_rejects_past_end_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_future_one_shot_commitment_issue_is_created_with_deadline_only` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_open_ended_ongoing_commitment_issue_is_created_with_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_open_ended_ongoing_commitment_shape_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_future_one_shot_commitment_shape_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stop_condition_only_commitment_shape_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_string_stop_condition_only_with_origin_ref_rejects_without_explicit_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_resolve_condition_person_commitment_rejects_without_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_requires_initiative_kind` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_supports_character_loyalty_condition` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_rejects_string_numeric_person_loyalty_ongoing_effect` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_non_dict_stop_condition` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_stop_condition_without_table_prefix` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_requires_origin_ref` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_requires_ongoing_effects` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_semantically_empty_ongoing_effects` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_one_shot_entity_creation_as_monthly_work` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_direct_resolved_close` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_rejects_direct_failed_close_without_effects` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_commitment_advance_to_full_stays_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stop_condition_without_commitment_kind_advance_to_full_stays_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_has_stop_condition_handles_preparsed_and_json_whitespace` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_empty_json_stop_condition_allows_advance_to_resolved` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_skips_cli_resolve_effect_enrich` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_one_shot_appeasement_economy_move_does_not_create_commitment_issue` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_decree_commitment_schema_136.py`

- 规模：349 行 / 14 函数 / 34 节点 · 处置分布：`{'keep': 14}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_issues_schema_has_commitment_deadline_columns` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_effect_dict_has_work_ignores_metadata_only_payloads` | 9 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_effect_dict_has_work_recognizes_schema_effects` | 12 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_issue_resolution_removes_building_and_keeps_remove_audit_log` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_effect_dict_has_work_ignores_malformed_person_loyalty` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_insert_issue_persists_commitment_deadline_columns` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_insert_issue_serializes_structured_stop_condition_as_json` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_issue_persists_commitment_columns_from_tracker_output` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_commitment_shape_with_string_stop_condition_requires_marker` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_canonicalize_new_issue_preserves_commitment_columns` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_initiative_cap_allows_fifteen_active_issues` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_show_active_issues_uses_fifteen_initiative_cap` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_existing_issues_table_gets_commitment_columns_idempotently` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_decree_initiative_cap_rejects_sixteenth_with_updated_message` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_decree_commitment_settlement_229.py`

- 规模：1651 行 / 34 函数 / 34 节点 · 处置分布：`{'keep': 34}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_created_future_limited_duration_commitment_applies_first_month` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_character_loyalty_commitment_ongoing_applies_monthly_and_records_progress` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_faction_class_commitment_ongoing_applies_monthly_when_counted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_ongoing_malformed_entity_payloads_are_rejected_without_crashing` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_stop_gate_resolve_respects_outer_transaction_rollback` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_expiry_respects_outer_transaction_rollback` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_monthly_ongoing_respects_outer_transaction_rollback` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_progress_skips_non_numeric_gate_values` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_region_cannon_commitment_ongoing_applies_monthly_when_counted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_arrears_commitment_settlement_oracle_resolves_with_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_progress_contexts_are_structured` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_arrears_commitment_progress_preserves_fractional_remaining` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_progress_fractional_strict_gate_can_be_satisfied` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_progress_text_splits_by_commitment_shape_and_gate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_ongoing_economy_not_scaled_by_bar_discount` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_arrears_commitment_preserves_explicit_monthly_payment_target` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_high_bar_metric_only_commitment_applies_and_records_monthly_progress` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_metric_commitment_records_progress_when_monthly_cap_blocks_effect` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_end_turn_expires_without_resolve_effects` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_limited_duration_commitment_ticks_until_end_turn_then_expires` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_until_stop_condition_beats_later_end_turn_for_stacked_commitment` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cancelled_commitment_is_distinct_from_expired_commitment` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_missing_purpose_still_routes_arrears_budget` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_targeted_pay_uses_explicit_arrears_target` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_malformed_pay_target_does_not_fall_back_to_priority_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_non_arrears_commitment_missing_pay_target_does_not_open_priority_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_pay_pool_is_scoped_to_arrears_stop_gate_armies` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_commitment_progress_keeps_strict_stop_gate_semantics` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_end_turn_without_ongoing_is_not_expired_by_settlement_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_one_shot_end_turn_commitment_surfaces_in_existing_review_channel` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_semantically_empty_one_shot_commitment_surfaces_and_acks_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_metadata_only_one_shot_commitment_surfaces_and_acks_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_due_one_shot_commitment_ack_closes_review_loop_without_effects` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_decree_dossiers_571.py` 🔒

- 规模：3394 行 / 94 函数 / 171 节点 · 处置分布：`{'keep': 94}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_dossier_roster_preserves_multiple_leads_support_roles_and_knowers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_create_rejects_malformed_structured_roster` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_roster_rejects_unknown_character_references_at_write_boundary` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_conversation_draft_roster_reaches_committed_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_conversation_draft_rejects_malformed_roster_without_staging` | 14 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_roster_write_boundary_rejects_invalid_delegator` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_roster_append_keeps_existing_entries_and_delegator` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_append_is_idempotent_only_for_identical_character_entry` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_month_end_extractor_appends_self_dispatched_participant` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_month_end_participant_batch_rejects_each_malformed_item` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_driver_settle_freezes_dossier_roster_authority_at_input` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settlement_replay_uses_only_persisted_dossier_authority` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_driver_crash_persists_frozen_dossier_authority_for_replay` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extractor_never_reconstructs_missing_dossier_authority_from_live_db` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_committing_each_directive_creates_independent_restoreable_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_explicit_directive_without_extractor_payload_becomes_narrative_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_directive_only_enters_settlement_after_final_approval` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_pending_action_carries_chat_turn_and_pending_provenance` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_terminal_target_does_not_interrupt_another_executor` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_office_action_waits_for_verdict_then_materializes_from_same_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_cannot_start_in_execution_state` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_and_dossier_roll_back_as_one_unit` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_character_terminal_state_closes_secret_order_and_execution_slot` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commitments_bind_explicitly_when_multiple_dossiers_share_a_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_allocation_rejected_is_zero_effect_and_force_promulgation_keeps_rejection` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_assignment_promulgation_tracks_executor_until_terminal_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_directive_assignee_projects_to_executor_only_for_executable_types` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_real_resolve_entry_applies_promulgation_verdict_and_payload_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_real_resolve_entry_without_pending_dossiers_skips_promulgation_llm` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_dossier_uses_player_rescript_choice_and_resume` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_dossier_survives_simulator_failure_on_rescript_rail` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_narrative_dossier_is_not_an_executable_or_extractor_origin` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_execution_rejects_non_sqlite_integer_ids` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dossier_execution_accepts_sqlite_integer_id` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_structured_dossier_origin_deduplicates_extractor_but_narrative_applies` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_payload_owned_appointment_dedup_removes_only_exact_mechanical_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_payload_owned_appointment_dedup_uses_prior_item_runtime_office_type` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_payload_owned_appointment_dedup_preserves_same_person_different_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_executing_execution_record_never_closes_or_stamps_closed_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_force_promulgated_dossier_authorizes_same_batch_effect_after_execution_close` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extractor_accepts_transformed_execution_outcome` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_appointment_alias_uses_canonical_dossier_identity` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_manual_directive_capture_reaches_structured_dossier` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_manual_directive_capture_rejects_malformed_roster` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_manual_directive_capture_rejects_missing_empty_or_invalid_tier_without_writes` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_final_decree_edit_cannot_bypass_frozen_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_dossiered_directive_is_not_listed_editable_or_deletable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_no_edict_route_rejudges_held_proposed_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_edit_replaces_text_and_mechanics_before_promulgation` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extractor_context_origin_ref_round_trips_to_commitment` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_progress_persists_executing_until_terminal` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_progress_undo_restores_order_and_dossier_axes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_close_failure_rolls_back_only_its_two_axes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_and_engine_action_types_cannot_create_dossiers` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_secret_orders_restore_with_unique_resumable_dossiers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_secret_order_migration_ignores_free_text_progress` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_held_dossier_reenters_only_for_next_month_rejudgment` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promoted_held_dossier_exposes_only_current_verdict_to_simulator` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_interim_verdict_rejects_reserved_legal_reason_code` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_session_manual_directive_keeps_structured_action_at_submission` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_probe_directive_shared_entry_creates_and_settles_structured_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_directive_freezes_at_dossier_birth` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_directive_edit_replaces_mechanical_payload_before_submission` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_allocation_rejects_unknown_economy_account_before_dossier_birth` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_underfunded_in_transit_allocation_closes_from_execution_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_incomplete_mechanical_directive_is_rejected_instead_of_retyped` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_mechanical_directive_missing_target_fails_loudly_at_real_entry` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_commitment_origin_maps_to_its_own_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_military_directive_projects_normalized_due_turn_to_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_draft_extraction_does_not_capture_acting_appointment` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_batch_draft_extraction_preserves_each_mechanical_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_executing_dossier_stays_visible_and_extractor_can_close_it` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_malformed_dossier_origin_is_rejected_fail_closed` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_invalid_promulgation_decision_stops_before_simulation` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_withdrawn_rescript_records_closed_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_target_survives_restore_and_is_queryable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_allocation_candidate_edit_preserves_mechanical_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_immediate_terminal_payload_cannot_bypass_execution_surface` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inner_treasury_admission_uses_actual_once_and_preserves_surface` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_inner_treasury_allocation_closes_next_month_without_replay` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_protection_execution_closes_from_next_month_extractor` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_authorization_dossier_does_not_map_payload_to_skill_grant` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_authorization_rejects_missing_assignee_without_grant` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_in_transit_allocation_requires_execution_verdict` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_durable_allocation_rejects_non_integer_amount_without_downgrade` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_durable_military_order_without_assignee_fails_loudly` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_complete_rejection_verdict_is_restoreable_audit_record` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejection_verdict_defaults_omitted_midzhi_marker_to_false` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejection_runtime_contract_rejects_each_missing_field` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejection_runtime_contract_rejects_unknown_references` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejection_snapshot_rejects_malformed_typed_values` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejection_contract_rejects_numeric_contamination_without_history` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_distance_matrix.py`

- 规模：81 行 / 4 函数 / 4 节点 · 处置分布：`{'delete': 4}` · 主注：④ 纯矩阵数学无游戏接缝

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_bake_uses_half_endpoint_weights_and_zero_diagonal` | 1 | **delete** | ④ 纯矩阵数学无游戏接缝 |
| `test_bake_selects_fastest_route_and_preserves_triangle_inequality` | 1 | **delete** | ④ 纯矩阵数学无游戏接缝 |
| `test_runtime_reader_is_lookup_only` | 1 | **delete** | ④ 纯矩阵数学无游戏接缝 |
| `test_baked_content_covers_all_regions_and_three_golden_anchors` | 1 | **delete** | ④ 纯矩阵数学无游戏接缝 |

### `tests/test_dossier_endorsements_612.py`

- 规模：923 行 / 11 函数 / 11 节点 · 处置分布：`{'keep': 11}` · 主注：真行为 新 #612

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_endorsement_write_boundary_rejects_unknown_or_illegal_forms` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_chat_turn_removes_source_bound_endorsements_from_judge` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ordinary_extraction_and_parse_boundaries` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_post_reply_extracts_ordinary_facts_immediately_even_with_approved_pending` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_close_night_endorsement_batch_once_gate_free_and_parallel_independent_work` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_close_night_beat_and_endorsement_exceptions_terminate_before_reopen` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_endorsement_failure_keeps_open_drafts_and_retries_idempotently` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_office_phase1_draft_only_materializes_once_after_endorsement` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mingfa_publication_ignores_extractor_source_and_malformed_suffix_on_retry` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_no_edict_chain_binds_endorsement_after_draft` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_dossier_links_559.py`

- 规模：590 行 / 23 函数 / 42 节点 · 处置分布：`{'keep': 23}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_one_protection_dossier_links_three_older_allocations_both_directions` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_only_confirmed_narrowed_references_are_persisted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_secret_order_extractor_only_carries_explicit_confirmed_dossier_ids` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_semantic_verdict_rejects_negative_quote_vague_and_containment` | 4 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_semantic_verdict_bad_shape_fails_closed_without_crashing` | 6 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_semantic_verdict_can_narrow_to_exactly_one_proposed_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_secret_order_extractor_rejects_model_id_outside_visible_candidates` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reference_candidates_hide_other_ministers_secret_dossiers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reference_candidates_obey_canonical_disclosure_blacklist` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_api_session_tool_path_commits_only_semantically_confirmed_link` | 4 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_cli_materialize_path_commits_only_semantically_confirmed_link` | 4 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_web_stream_pending_commit_traces_only_confirmed_visible_links` | 6 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_confirmed_secret_order_materializes_links_through_pending_commit` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unknown_target_link_is_rejected_and_audited` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_target_multiple_relations_keep_exact_confirmed_tuples` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_force_promulgated_rejected_dossier_is_referenceable` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_withdrawn_rejected_dossier_is_not_referenceable` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pending_rejection_does_not_follow_reused_rolled_back_source_id` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_serial_and_parallel_join_share_proposal_normalization` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_parallel_cli_bad_link_does_not_roll_back_valid_secret_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cli_secret_extraction_overlaps_independent_confirmation` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_real_secret_order_tool_schema_describes_dossier_link_contract` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_driver.py` 🔒

- 规模：592 行 / 31 函数 / 35 节点 · 处置分布：`{'keep': 31}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_cli_settle_rejects_non_dict_envelope_delta` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_rejects_non_dict_raw_delta` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_none_delta_is_empty_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_logs_chapter_memory_skip` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_no_chapter_skip_audit_when_settle_aborts` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_records_non_dict_nested_value` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_rejects_unknown_toplevel_key` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_records_non_dict_module_value` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_game_loads_board` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_normalizes_chinese_delta_and_advances` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_persists_narrative_and_applied_extraction_trace` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_persists_applied_person_results_for_player_visible_extraction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_preserves_legacy_person_key_order_after_issue_close` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_preserves_unified_person_key_order_after_issue_close` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_state_prints_board` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_settle_applies_delta_file` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_settle_envelope_persists_narrative` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cli_dump_prints_regions` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_persists_resolve_context_before_settle` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_clears_resolve_context_on_completion` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_crash_inside_pre_settle_leaves_no_ready_context` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_persist_crash_rolls_back_pre_settle` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_default_db_is_absolute_repo_anchored` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_game_fails_loud_on_missing_db` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_game_rejects_empty_or_nonsave_db` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_game_rejects_degenerate_db_with_state_but_empty_board` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_open_game_handles_uri_special_chars_in_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_canonicalize_extraction_public_api` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_player_sourced_rejection_surfaces_diegetic_hint` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_no_rejection_no_hint` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_run_settle_system_source_rejection_stays_silent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_economy_section_rejections.py` 🔒

- 规模：219 行 / 11 函数 / 11 节点 · 处置分布：`{'keep': 11}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_top_level_bad_account_rejected_good_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_top_level_nonint_delta_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_valid_economy_still_applies_no_reject` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_zero_delta_economy_no_reject_no_apply` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_effect_bad_account_economy_reaches_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_float_and_bool_delta_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_noop_bad_account_skipped_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_effect_cancel_economy_reaches_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_economy_rejections_not_in_player_visible` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_clean_economy_moves_passes_bad_through` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_clean_economy_moves_non_list_returns_empty` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_effect_origin_558.py`

- 规模：390 行 / 13 函数 / 13 节点 · 处置分布：`{'keep': 13}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_decree_driven_effect_without_any_origin_is_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_effect_origins_round_trip_and_missing_origin_is_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_issue_close_effects_inherit_parent_canonical_origin` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_issue_row_inertia_and_ongoing_reuse_parent_canonical_origin` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_remove_keeps_durable_origin_tombstone` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_economy_ledger_origin_backfill_uses_real_dossier_only` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fabricated_origin_is_rejected_even_without_a_dossier` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ordinary_entity_log_families_persist_origin_at_write_seam` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_power_backlash_from_allegiance_change_inherits_canonical_origin` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_missing_origins_are_rejected_at_entity_write_seams_without_logs` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_entity_origin_gate_does_not_replace_reference_shape_or_noop_classification` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_zero_manpower_origin_gate_matches_actual_arrears_writeoff` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_army_pay_source_classifies_before_origin_gate_and_never_writes_without_origin` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_empire_modifier_income_only_341.py`

- 规模：57 行 / 3 函数 / 3 节点 · 处置分布：`{'keep': 3}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_expenditure_not_amplified_by_legacy` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_income_still_modified_by_legacy` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_expenditure_zero_net_pct_unchanged` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_enrich_list_guards.py` 🔒

- 规模：84 行 / 7 函数 / 7 节点 · 处置分布：`{'keep': 7}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_enrich_buildings_non_list_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_economy_list_non_list_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_economy_list_valid_still_works` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_loads_effect_dict_coerces_non_dict` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_ongoing_non_dict_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_economy_list_skips_non_dict_items` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_metric_faction_class_dict_non_dict_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_env_isolation.py`

- 规模：19 行 / 1 函数 / 1 节点 · 处置分布：`{'keep': 1}` · 主注：④ 测试基建隔离 pin，保留

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_user_data_dir_is_isolated_from_repo_data` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_error_pack.py` 🔒

- 规模：434 行 / 18 函数 / 18 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_extractor_failure_raises_settlement_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_error_pack_written_with_five_files` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_abort_leaves_no_db_settlement_writes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_attempt_derived_from_existing_dirs` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_write_error_pack_inside_atomic_is_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pack_write_failure_does_not_mask_original` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_clear_for_resimulation_downgrades_context_keeps_settling` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_clear_for_resimulation_preserves_source` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_clear_for_resimulation_noop_when_no_context` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejections_jsonl_path_in_error_dir` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_attempt_never_overwrites_existing_pack` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_mirror_writes_to_rejections_jsonl_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pack_write_interrupt_propagates_as_interrupt` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_issue_endpoint_returns_structured_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_shape_garbage_extractor_product_is_sanitized_and_recorded` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_next_attempt_skips_malformed_and_foreign_entries` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_version_read_failure_falls_back_to_unknown` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_complete_ready_packs_match_database_turn_digest_and_manifest_shape` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_event_chain_cascade.py`

- 规模：360 行 / 16 函数 / 16 节点 · 处置分布：`{'keep': 16}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_positive_dependency_invalidates_when_upstream_expires` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_numeric_triggered_gt_zero_dependency_invalidates_when_upstream_expires` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_numeric_triggered_lt_one_dependency_invalidates_when_upstream_triggers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_positive_outcome_dependency_waits_for_frozen_outcome_label` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_terminal_state_expired_dependency_invalidates_when_upstream_obsolete` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_terminal_state_in_expired_or_obsolete_invalidates_when_upstream_triggered` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_terminal_state_including_triggered_preserves_expired_alternative` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_conjunctive_positive_terminal_state_predicates_are_intersected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_contradictory_positive_terminal_state_gate_fails_loud` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cascade_rolls_back_owned_transaction_on_later_write_failure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_negative_dependency_is_satisfied_by_upstream_expiry_not_invalidated` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_negative_dependency_invalidates_when_upstream_fired_forbidden_outcome` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_negative_dependency_is_satisfied_by_upstream_avoidance_not_invalidated` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_soft_gate_failure_does_not_invalidate_chain_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_transitive_cascade_invalidates_downstream_closure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_event_dependency_cycle_fails_loud` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_event_outcome_retry.py`

- 规模：117 行 / 3 函数 / 3 节点 · 处置分布：`{'keep': 3}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_event_outcome_label_retry_reruns_only_issues_extractor` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_event_outcome_label_alias_normalizes_without_retry` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_event_outcome_label_retry_cap_fails_loud` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_event_trigger_gate.py` 🔒

- 规模：5908 行 / 193 函数 / 203 节点 · 处置分布：`{'keep': 193}` · 主注：⑤🔒 闸类保留；参数化减 setup

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_gated_historical_event_excluded_when_unsatisfied` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gated_historical_event_included_when_satisfied` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_ungated_historical_event_unchanged` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_event_expires_after_latest_window_when_gate_unsatisfied` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_event_gate_can_read_event_triggered_record` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_event_latest_month_is_still_inside_window` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_event_triggered_gate_ignores_obsolete_terminal` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_open_window_historical_event_never_expires` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_open_window_historical_event_still_waits_for_earliest_time` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_seed_event_expires_after_latest_window_when_gate_unsatisfied` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_auto_trigger_seed_event_expires_after_latest_window_when_gate_unsatisfied` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gather_candidate_events_filters_expired_auto_trigger_seed_without_writing` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_apply_uses_pushed_candidate_snapshot_not_fresh_recompute` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_event_terminal_states_does_not_commit_existing_transaction` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_passed_tolerates_none` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_passed_tolerates_nonstring_cond` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_event_none_gate_no_crash` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_key_form_error_accepts_valid_forms` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_key_form_error_rejects_typo_metric_table_structure` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_cond_form_error_numeric_and_text` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_fail_loud_on_bad_gate_key` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_rejects_default_terminal_reason_outside_labels` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_requires_latest_or_open_window` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_rejects_non_boolean_open_window` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_rejects_strategic_foreign_situation` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_rejects_latest_before_earliest` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_event_rejects_month_out_of_range` | 4 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_typo_field_gate_raises_clear_not_operationalerror` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_cond_numeric_neq_rejected_text_neq_ok` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_key_rejects_empty_segments` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_typo_field_text_gate_raises_clear` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_key_rejects_empty_class_name` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_text_cond_requires_text_capable_key` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_load_fail_loud_on_text_cond_multi_id_key` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_text_cond_field_must_be_text_field` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gate_key_rejects_empty_region_after_at` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_numeric_cond_on_text_field_raises_clear` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_numeric_gate_supports_comparison` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_numeric_gate_supports_aggregation` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_army_numeric_gate_preserves_fractional_arrears_tail` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_gate_rejects_malformed_field_before_sql` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_numeric_field_text_gate_raises_clear` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_text_gate_supports_equality` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_typo_field_gate_raises_clear` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_text_typo_field_gate_raises_clear` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_text_gate_key_passes_content_validation` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_text_gate_rejects_serialized_list_field` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_character_text_gate_rejects_numeric_character_field` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_event_effect_uses_unified_person_change_key` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_auto_trigger_historical_event_to_issue_uses_outer_transaction` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_content_rejects_falsy_person_core_subjects` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_excluded_after_appeasement` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_excluded_after_player_relocates_mao` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_excluded_after_player_reassigns_yuan` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_trigger_lands_character_status` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_event_records_trigger_and_lands_soft_result_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_result_delta_is_all_or_nothing_on_rejected_item` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_missing_origin_rejects_whole_result_envelope` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_event_lands_new_army_soft_result_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_new_army_result_rejects_existing_army_collision` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_new_army_result_rejects_nonpositive_manpower` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_records_outcome_label_with_world_state_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_outcome_label_normalizes_known_synonym` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_outcome_retry_ignores_non_landable_event_without_world_state_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_delta_requires_outcome_label_without_mutation` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_outcome_label_unknown_fails_loud_without_mutation` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_anchored_strategic_new_army_without_event_trigger_is_rejected` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_anchored_strategic_region_outcome_without_reason_is_rejected` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_ordinary_jinzhou_preparedness_delta_is_not_rejected_as_songshan_outcome` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_event_survives_named_commander_death_with_soft_result_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_event_rejects_trigger_without_world_state_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_direct_issue_tracker_rejects_strategic_event_without_world_state_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_anchored_strategic_result_delta_without_event_trigger_is_rejected` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_ordinary_army_station_delta_with_strategic_place_anchor_is_not_rejected` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_194_lindan_xiqian_requires_world_state_main_ledger_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_lindan_xiqian_does_not_capture_untriggered_beizhili_border_policy_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_shared_jinzhou_result_does_not_double_consume_dalingghe_and_songshan` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_henan_place_policy_delta_does_not_capture_untriggered_fall_events` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_henan_bandit_policy_delta_does_not_capture_untriggered_luoyang_event` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_unrelated_region_delta_does_not_satisfy_strategic_event_result_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_target_region_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_unrelated_person_delta_does_not_satisfy_strategic_event_result_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_unrelated_person_delta_with_event_anchor_does_not_satisfy_strategic_event_result_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_target_person_delta_without_event_anchor_does_not_satisfy_strategic_event_result_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_noncandidate_strategic_event_with_unknown_label_preserves_unrelated_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_foreign_event_does_not_land_battle_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_foreign_event_preserves_unrelated_region_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_event_preserves_unanchored_target_region_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_event_preserves_unrelated_person_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_previously_triggered_strategic_event_rejects_duplicate_without_landing_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_event_does_not_land_substitute_commander_person_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_invalid_controlled_by_suppresses_sibling_deltas` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_invalid_strategic_event_result_delta_does_not_mark_event_triggered` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_cannon_clamp_noop_does_not_mark_event_triggered` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_army_clamp_noop_does_not_mark_event_triggered` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_person_travel_noop_does_not_mark_event_triggered` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_person_same_status_noop_does_not_mark_event_triggered` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_person_same_office_noop_does_not_mark_event_triggered` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_person_tenure_change_is_material_world_state` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_invalid_person_tenure_rejects_whole_result_envelope` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_accepts_power_update_as_material_world_state` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_power_update_requires_event_anchor` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_accepted_strategic_event_applies_power_updates_after_main_result` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_invalid_strategic_power_update_blocks_main_result` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_orphan_strategic_power_update_without_event_issue_is_rejected` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_jisi_border_contained_outcome_rejects_invasion_world_state` | 2 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_event_person_result_rejection_blocks_other_result_deltas` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_person_alias_stays_in_rejected_event_envelope` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_rejected_strategic_person_preflight_restores_content_power_id` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_person_backlash_rejection_blocks_event_result_envelope` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_event_lands_soft_result_person_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_trigger_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_rollback_restores_bound_content_when_content_omitted` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_rollback_removes_dynamic_character_attrs` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_metric_delta_restores_runtime_on_outer_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_situation_insert_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_pool_rechecks_gate_before_effect` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_person_core_event_obsoletes_when_named_subject_is_dead` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_yuan_xialing_event_excluded_without_jisi_triggered` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_yuan_xialing_event_excluded_after_jisi_border_contained_outcome` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_yuan_xialing_event_included_after_jisi_event_issue_triggers` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_legacy_event_pool_issue_backfills_trigger_without_guessing_outcome` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_legacy_event_trigger_terminal_reason_can_be_filled_by_real_outcome` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_person_write_state_restore_removes_dynamic_character_attrs` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_legacy_person_core_static_fields_backfill_reachability` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_person_core_static_backfill_preserves_relocated_mao` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_luoyang_fallen_not_obsoleted_when_fu_wang_is_dead` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_li_chenghai_event_opens_after_li_zicheng_historical_debut` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_zhangxianzhong_event_opens_after_historical_debut_and_surrender_path` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_191_person_core_events_are_explicitly_classified` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_194_strategic_foreign_events_are_explicitly_classified_and_gated` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_strategic_foreign_classification_requires_outcome_targets` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_194_dead_named_general_does_not_obsolete_strategic_foreign_event` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_194_dalingghe_requires_world_state_main_ledger_result` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_huabei_plague_auto_triggers_with_deterministic_core_effect` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_auto_trigger_core_effect_is_applied_once` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_auto_trigger_historical_events_use_preloaded_terminal_refs` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_auto_trigger_event_expires_after_latest_window` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_gated_auto_trigger_seed_event_can_recur_after_previous_issue_resolved` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_huabei_plague_keeps_soft_degree_axis_as_situation_issue` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_situation_auto_trigger_rolls_back_soft_issue_when_core_effect_fails` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_situation_auto_trigger_backfills_core_effect_for_existing_soft_issue` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_jingshi_plague_auto_triggers_and_weakens_capital_garrison` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_huangtaiji_chengdi_auto_triggers_and_renames_houjin` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_huangtaiji_chengdi_keeps_diplomatic_response_axis_as_situation_issue` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_historical_power_rename_tick_reads_huangtaiji_event_effect` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_pool_uses_candidate_snapshot_before_advances` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_uses_candidate_snapshot_before_top_level_metric_delta` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_rechecks_after_advances_close_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_rechecks_after_prior_event_effect_closes_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_decree_new_issue_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_advance_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_advance_effects_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_close_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_close_effects_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_close_entity_effects_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_close_legacy_expiry_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_issue_entities_person_changes_respect_commit_false` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_top_level_economy_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_fiscal_changes_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_class_delta_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_top_level_entity_deltas_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_fiscal_create_and_remove_respect_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_person_location_change_blocks_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_invalid_appointment_does_not_block_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_invalid_allegiance_change_does_not_block_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_disposition_clears_office_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_location_change_clears_transit_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_rejected_legacy_gate_change_does_not_block` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_legacy_power_change_blocks_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_same_power_allegiance_noop_does_not_block_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_allegiance_backlash_blocks_power_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_person_changes_are_simulated_sequentially` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_apply_score_extraction_registry_refresh_rolls_back_with_outer_transaction` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_alias_appointment_blocks_canonical_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_alias_disposition_blocks_canonical_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_pending_person_gate_prefetches_character_rows_for_displacement` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_gate_reuses_shadow_prefetch_across_new_issues` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_rejected_vassal_appointment_does_not_block_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_appointment_displacement_blocks_displaced_office_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_appointment_clears_reason_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_appointment_updates_office_type_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_pending_appointment_normalizes_equivalent_office` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_cancel_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_issue_tracker_cancel_cost_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_pool_rechecks_after_same_turn_loyalty_assessment` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_pool_rechecks_after_same_turn_yuan_dismissal` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_invalid_pending_person_change_does_not_block_event_gate` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_obsolete_when_core_subject_already_dead` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_excluded_when_yuan_unavailable` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_event_pool_current_candidate_recheck_cached_until_state_changes` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |
| `test_mao_wenlong_event_pool_duplicate_emit_is_idempotent` | 1 | **keep** | 🔒 事件前提门闸类负向不可删（文件级 rewrite=参数化减 setup） |

### `tests/test_extractor_misroute_surface.py`

- 规模：75 行 / 5 函数 / 5 节点 · 处置分布：`{'keep': 4, 'delete': 1}` · 主注：④⑤ 私有表断言删

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_misrouted_field_dropped_and_surfaced` | 1 | **keep** | 真行为 sanitize surface 可观测出口 |
| `test_in_module_fields_do_not_surface` | 1 | **keep** | 真行为 sanitize surface 可观测出口 |
| `test_issues_module_accepts_event_outcomes_alias_without_misroute` | 1 | **keep** | 真行为 sanitize surface 可观测出口 |
| `test_garbage_key_does_not_surface` | 1 | **keep** | 真行为 sanitize surface 可观测出口 |
| `test_field_owner_map_covers_all_modules` | 1 | **delete** | ④ 私有 _FIELD_OWNER_MODULE 表断言 |

### `tests/test_faction_class_section_rejections.py` 🔒

- 规模：266 行 / 11 函数 / 11 节点 · 处置分布：`{'keep': 11}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_unknown_faction_rejected_good_item_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unknown_class_rejected_good_item_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_illegal_faction_value_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_illegal_class_value_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_float_and_bool_class_values_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_float_and_bool_faction_values_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_panel_faction_delta_stays_applied_dict` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_valid_flat_int_faction_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_flat_class_delta_rejected_while_nested_sibling_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_zero_delta_faction_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_effect_faction_rejection_reaches_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_faction_leverage_9.py`

- 规模：1258 行 / 37 函数 / 37 节点 · 处置分布：`{'keep': 37}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_faction_leverage_drops_when_core_minister_ousted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_faction_leverage_rises_back_when_minister_restored` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_non_whitelist_faction_row_leverage_not_recomputed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_xixue_faction_in_whitelist_drops_when_member_ousted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rank_tier_modulates_impact` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_restore_uses_new_office_weight_not_old` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_promotion_via_set_character_office_raises_leverage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_failed_appointment_rolls_back_faction_leverage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_displaced_minister_faction_leverage_recomputed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_offset_not_re_anchored_on_reload_after_clamp` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_leverage_clamps_at_zero_no_negative` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_add_character_appointment_lifts_faction_leverage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_member_empty_office_contributes_zero_weight` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_recompute_all_reconciles_drift_from_unhooked_path` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_path_triggers_reconcile_before_next_period` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reconcile_runs_before_clear_gated_legacies_same_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_office_weight_takes_highest_domain_across_joint_offices` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_office_rank_deputy_titles_not_inflated_to_principal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_office_rank_aux_titles_audit_offices_json` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_jundadou_deputy_ouster_impact_is_half_of_principal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_xingbu_has_leverage_weight_like_other_ministries` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_neiting_has_leverage_weight_like_other_court_eunuchs` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_all_court_allowed_types_have_leverage_weight` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_weizhongxian_ouster_drops_yandang_by_sili_weight` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_whitelist_faction_delta_routes_to_offset_survives_reconcile` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_whitelist_faction_delta_survives_full_settlement` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_defection_through_settlement_reconciles_old_faction` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_non_whitelist_faction_delta_direct_leverage_survives_reconcile` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_legacy_save_calibrates_offset_via_driver_path` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_col_added_uncalibrated_save_recalibrates_on_open` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_calibrated_save_without_marker_not_re_anchored` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rollback_snapshot_restores_leverage_offset` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_calibrate_offset_flag_consumed_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_rollback_restores_faction_leverage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_power_id_defection_drops_faction_leverage_immediately` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_half_weight_odd_baseline_no_round_drift` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_old_integer_offset_migrated_to_float` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_featured_dossiers_494.py`

- 规模：100 行 / 4 函数 / 4 节点 · 处置分布：`{'rewrite': 4}` · 主注：②⑤ 长散文 contains

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_every_active_seven_faction_minister_has_featured_dossier` | 1 | **rewrite** | ②⑤ 长散文 contains |
| `test_seven_faction_dossiers_are_objective_and_identity_scoped` | 1 | **rewrite** | ②⑤ 长散文 contains |
| `test_north_star_ministers_have_distinct_featured_voices` | 1 | **rewrite** | ②⑤ 长散文 contains |
| `test_minister_agent_injects_faction_dossier_once` | 1 | **rewrite** | ②⑤ 长散文 contains |

### `tests/test_fiscal_levy_effect.py`

- 规模：1394 行 / 40 函数 / 49 节点 · 处置分布：`{'keep': 40}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_shaanxi_primary_source_liao_seed_keeps_opening_transport_cap` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_rise_triggers_and_updates_shadow_settle_before_fiscal_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_rise_triggers_on_no_edict_advance_before_fiscal_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_shadow_capstone_golden_all_seeded_provinces` | 4 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_memorial_estimate_payload_is_diegetic_national_scope` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_estimate_skips_rejected_positive_levy` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_memorial_estimate_uses_collectible_ming_controlled_revenue` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_shadow_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_shadow_skips_bad_settle_shape_without_blocking_other_regions` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_rewrites_nonnumeric_current_targets_from_meta` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_bad_region_does_not_redistribute_jiao_lian_targets` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_uses_stable_denominator_when_lost_region_breaks_later` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed` | 4 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_suppresses_share_estimate_without_complete_denominator` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_estimates_skip_malformed_region_fiscal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_labels_cumulative_army_arrears_as_wanliang_not_monthly` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_excludes_self_funded_tusi_from_army_gap` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_expired_pending_choice_is_terminalized` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lian_levy_start_triggers_and_updates_shadow_settle_before_fiscal_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_existing_terminal_reason_is_whitelist_validated` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_choice_row_rejection_controls_same_tick_effect` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_choice_resubmission_uses_latest_pending_label` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_pending_choice_label_is_canonicalized_for_db_consumers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_pending_stop_choice_keeps_jiao_in_force_same_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_pending_choice_waits_for_event_window` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_small_fractional_arrears_range_is_ordered` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_memorial_suppresses_jiao_start_when_stopped_same_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_liao_levy_rewrites_numeric_string_targets_to_canonical_numbers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_jiao_levy_rises_then_stops_and_keeps_base_transport` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_levy_retreat_recomputes_transport_without_active_rate_change` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_jiao_levy_stop_rejected_keeps_levy_in_force` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_jiao_stop_is_obsolete_when_start_was_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_jiao_stop_definition_missing_fails_loud` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lian_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_components_are_land_share_calibrated_and_marked_provisional` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lost_seeded_province_keeps_current_levy_rate_and_uses_it_on_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lian_levy_gate_waits_until_1639_and_needs_no_stop_event` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fiscal_levy_gate_waits_until_1631_and_generic_terminal_pass_skips_it` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_fiscal_substrate_bridge.py`

- 规模：5333 行 / 130 函数 / 184 节点 · 处置分布：`{'rewrite': 105, 'keep': 25}` · 主注：⑤🔒 seed 变体瘦身

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_seed_royal_stipends_use_wanli_accounting_by_province` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_region_loader_expands_shared_settle_meta_defaults` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_pay_source_spine_seed_splits_arrears_and_reconciles_tusi` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_self_funded_seed_arrears_log_preserves_fractional_delta` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fresh_save_pay_source_prefers_content_army_fields` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_province_tick_derives_due_and_allocates_province_arrears_by_pay_source` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_conservation_rejects_excluded_army_with_pay_source_debt` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_conservation_rejects_province_source_army_without_settle_base` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_fixed_flows_substrate_hub_retires_global_central_pay_route` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_legacy_engine_keeps_global_army_pay_route` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_does_not_allocate_legacy_central_pool` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_hub_dual_track_sanity_keeps_legacy_calc_as_reference` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_hub_cutover_runs_multi_tick_treasury_trajectory` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_ready_context_retry_does_not_recompute_substrate_hub_pre_settle` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_central_capacity_reduces_current_central_arrears` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_central_pay_shares_hub_tier_with_jingyun_grants` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_central_pay_carries_transport_loss_without_jingyun` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_books_split_treasury_income_and_central_losses` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_budget_projection_passes_copied_settle_snapshots_to_fiscal_tick` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_budget_lines_read_persisted_substrate_hub_income_source` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_hub_skip_uses_internal_marker_not_user_fixed_display` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_treasury_budget_summary_names_substrate_hub_surfaces` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_treasury_budget_summary_names_fixed_salary_display` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_hub_uses_month_opening_treasury_before_lower_priority_expenses` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_integer_allocation_drives_all_consumers` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_hub_debit_fails_loud_when_required_debit_not_booked` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_fixed_flows_substrate_hub_fractional_due_caps_integer_debit` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_region_army_pay_tick_treats_missing_breakdown_as_no_delta` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_substrate_hub_failure_rolls_back_cutover_writes` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_budget_lines_read_fiscal_engine_gate_for_army_pay` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_pre_s6_cutover_save_without_fiscal_engine_migrates_to_substrate_hub` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fiscal_config_v8_migration_preserves_deleted_old_keys` | 2 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_province_pay_shortfall_reduces_pure_province_army_morale` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_armies_provision_empty_mutiny_status_flag` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_zero_due_province_army_morale_short_circuits` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_tusi_self_funded_army_skips_pay_morale_channel` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_pay_morale_formula_clamps_shortfall_and_old_arrears_gate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flows_cutover_uses_total_source_shortfall_for_mixed_army_morale` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_arrears_splits_positive_and_rejects_negative_under_cutover` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_arrears_rejects_exempt_army_under_cutover` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_arrears_reconciles_pay_source_container_immediately` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_pay_source_conservation_rejects_per_army_derived_arrears_drift` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_army_delta_manpower_reconciles_pay_source_due_immediately` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_owner_power_to_ming_requires_same_delta_pay_source` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_rejects_unknown_owner_power_without_clearing_arrears` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_rejects_pay_source_without_ming_settle_substrate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_owner_power_from_ming_clears_pay_source_arrears` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_army_delta_rejects_ming_exempt_flag_before_pay_arrears_writeoff` | 2 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_economy_pay_arrears_from_central_account_splits_by_current_debt_ratio` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_economy_pay_arrears_from_central_account_can_repay_pure_province_source_army` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_economy_pay_arrears_preserves_fractional_pay_source_tail` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_economy_pay_arrears_clamps_integer_spend_and_preserves_tail` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_economy_pay_arrears_rejects_missing_or_unknown_target_without_repaying_other_armies` | 2 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_manpower_zero_writeoffs_pay_source_arrears_before_retiring_army` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_manpower_zero_then_arrears_delta_does_not_resurrect_writeoff_debt` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_new_ming_army_requires_valid_pay_source_under_cutover` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_new_ming_army_rejects_non_ming_pay_source_region` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_new_ming_army_stores_pay_source_columns_under_cutover` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_new_ming_army_rejects_initial_arrears_under_cutover` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_region_loader_rejects_bad_shared_settle_meta_defaults_container` | 3 | **keep** | 🔒 fail-loud 负向 |
| `test_region_loader_rejects_bad_plain_settle_meta` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_region_loader_rejects_bad_settle_meta_defaults` | 4 | **keep** | 🔒 fail-loud 负向 |
| `test_all_15_regular_provinces_first_tick_golden` | 15 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_zhongyuan_jingshi_primary_source_refinement` | 3 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_south_southwest_seeds_have_valid_historical_settle_substrate` | 6 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_south_southwest_settle_tick_golden_and_bridge_persist` | 6 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_shaanxi_seed_has_valid_settle_substrate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_shaanxi_seed_is_relabelled_to_historical_shadow_scale` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_border_remainder_seeds_have_valid_settle_substrate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_border_slice_raw_content_keeps_primary_source_anchors` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_liaodong_and_dongjiang_are_pure_military_pay_funnels` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_liaodong_primary_source_due_survives_fresh_db_pay_source_reconcile` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_liaodong_pay_source_rows_add_to_standalone_military_funnel` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_liaodong_settle_tick_keeps_standalone_funnel_deficit_out_of_pay_rows` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_dongjiang_content_pay_funnel_survives_fresh_db_pay_source_reconcile` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_old_dongjiang_pay_funnel_due_backfills_before_new_pay_rows` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_primary_source_army_pay_due_rejects_dirty_annual_amount` | 5 | **keep** | 🔒 fail-loud 负向 |
| `test_standalone_army_pay_funnel_rejects_malformed_settle_shapes` | 4 | **keep** | 🔒 fail-loud 负向 |
| `test_standalone_army_pay_container_total_uses_grouped_arrears` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_standalone_army_pay_container_total_rejects_malformed_region_shapes` | 2 | **keep** | 🔒 fail-loud 负向 |
| `test_jiangnan_core_seeds_have_positive_remittance_golden` | 4 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_zhongyuan_jingshi_seeds_have_valid_historical_settle` | 3 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_beizhili_huangzhuang_is_inner_treasury_not_transport_quota` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_henan_royal_grants_make_zonglu_due_heavy` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_zhongyuan_jingshi_settle_province_tick_golden` | 3 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_settle_province_tick_persists_shaanxi_historical_shadow_golden` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_settle_province_tick_persists_border_remainder_golden` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_settle_province_tick_qingzhang_action` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_settle_province_tick_port_lock_no_persist_on_raise` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_settle_province_tick_unknown_region_raises` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_settle_province_tick_nondict_fiscal_raises` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_apply_fixed_period_flows_advances_shaanxi_substrate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_uses_dynamic_ming_settle_spine` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_logs_border_remainder_substrate` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_logs_zhongyuan_jingshi_shadow_ticks` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_absent_does_not_break_flows` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_corrupt_isolated_from_flows` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_corrupt_due_isolated` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_corrupt_stock_isolated` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_malformed_settle_shape_is_logged_not_prefiltered` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_malformed_fiscal_container_is_logged_not_prefiltered` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_cutover_pay_source_errors_abort_fixed_flows` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_jingyun_gross_bool_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_outbound_debit_failure_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_taicang_loss_rate_bad_state_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_missing_human_loss_rate_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_cutover_structural_sink_rate_zero_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_pre_settle_cutover_substrate_bad_state_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_advance_without_edict_cutover_bad_state_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_resolve_directives_nested_cutover_bad_state_uses_settlement_abort_error_pack` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_apply_fixed_period_flows_malformed_fiscal_container_isolated` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_substrate_malformed_fiscal_json_is_logged_not_prefiltered` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_malformed_fiscal_json_isolated` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_malformed_fiscal_scalar_isolated` | 2 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flow_loader_accepts_already_decoded_fiscal_dict` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flow_loader_rejects_non_finite_numeric_values` | 3 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_fixed_flow_loader_rejects_decoded_non_dict_payloads` | 3 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_commits_shadow_substrate_when_standalone` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic` | 1 | **keep** | 🔒 fail-loud 负向 |
| `test_apply_fixed_period_flows_advances_and_logs_jiangnan_core` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_apply_fixed_period_flows_logs_south_southwest_shadow_ticks` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_all_ming_settle_substrates_advance_with_observable_shadow_tlog` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_shadow_spine_uses_batch_bridge_without_per_region_reload` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_seeded_substrates_keep_multi_tick_historical_trajectories` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_all_settle_substrate_provisional_meta_covers_virtual_fields` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |
| `test_jiangnan_core_uses_wanli_huiji_lu_primary_seed` | 1 | **rewrite** | ⑤ 重复 seed/账户变体可参数化合并 |

### `tests/test_fiscal_tick.py` 🔒

- 规模：177 行 / 5 函数 / 61 节点 · 处置分布：`{'keep': 5}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_fiscal_golden` | 23 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_fail_loud` | 35 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_g9_three_tick_death_spiral` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_nonfinite_derived_fails_loud` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_conservation_error_is_distinct_type` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_identity_seed_488.py`

- 规模：160 行 / 9 函数 / 11 节点 · 处置分布：`{'keep': 9}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_identity_and_seed_guilt_are_loaded_from_roster_and_seeded` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_identity_and_seed_guilt_survive_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_existing_save_migrates_seed_identity_and_inserts_missing_roster_member` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_required_dig_7_seed_roster_entries_are_persisted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_identity_and_seed_guilt_never_enter_minister_context` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_roster_has_no_cross_faction_aliases` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_roster_rejects_alias_colliding_with_other_faction_name` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_roster_rejects_duplicate_canonical_name` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_seed_schema_rejects_invalid_values` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_initiative_resolve_pairing.py` 🔒

- 规模：185 行 / 18 函数 / 18 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_military_initiative_without_army_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_military_initiative_with_new_armies_no_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_military_initiative_with_office_change_no_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_recurring_initiative_without_economy_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_recurring_with_ongoing_economy_no_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_neutral_initiative_no_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_military_effect_with_only_legacy_office_changes_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_invalid_economy_shell_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_raise_with_only_person_change_still_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_move_with_only_army_still_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_account_not_applied_by_flows_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_numeric_string_delta_no_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nonlist_economy_no_crash_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_malformed_pairing_shape_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_surfaces_pairing_warning_in_result` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_with_new_armies_no_warning_in_result` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_emit_preparsed_list_tags_still_warns` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_emit_preparsed_dict_ongoing_no_false_warn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_issue_entities.py` 🔒

- 规模：595 行 / 31 函数 / 32 节点 · 处置分布：`{'keep': 31}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_resolve_creates_army` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_changes_character_status` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_issue_status_change_uses_person_transition_matrix` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_issue_status_change_does_not_use_month_end_active_gate` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_character_status_syncs_content_travel_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_applies_unified_person_change_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_unified_person_change_shadows_legacy_person_effects` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_rejects_bad_unified_person_change_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_person_change_effect_rejects_malformed_shape` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_malformed_army_raises_not_silent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_bad_owner_power_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unknown_character_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bad_status_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_empty_effect_noop` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_splits_bad_nested_entity` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_accepts_flat_faction_scalar` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_nondict_power_second_level_per_entity` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_nondict_list_item_per_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_tolerates_null_field` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_unknown_top_level_key` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_army_delta_reinforces_existing` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_delta_unknown_army_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_non_dict_character_status_item_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_nondict_effect_fields_do_not_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_initiative_floor_applies_when_enrich_empty` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_runtime_cli_initiative_floor_applies_without_backend_env` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_api_channel_initiative_does_not_use_backend_env_floor` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_natural_resolve_applies_entities` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_natural_resolve_applies_unified_person_change_with_bound_content` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_resolve_person_effect_is_visible_to_effect_brief` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_natural_fail_applies_entities` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_junxin_alias_loyalty_313.py`

- 规模：92 行 / 3 函数 / 3 节点 · 处置分布：`{'keep': 3}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_junxin_alias_maps_to_loyalty_not_morale` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_shiqi_alias_still_maps_to_morale` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_junxin_and_shiqi_aliases_independent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_knowledge.py`

- 规模：467 行 / 17 函数 / 20 节点 · 处置分布：`{'merge': 17}` · 主注：③ 与 character_knowledge_489 同根 #489

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_regional_world_keeps_qualitative_and_countable_region_facts` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_knowledge_exclusion_reads_current_office_without_nameerror` | 4 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_knowledge_projects_gazette_and_chapter_sources_per_character` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_knowledge_projects_mixed_archive_from_durable_source_scope` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_rewritten_archive_cannot_reintroduce_restricted_source` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_archive_write_materializes_unmirrored_source_scope` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_public_counterpart_keeps_only_independent_public_sources` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_counterpart_never_uses_aggregate_when_sources_exist` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_turn_report_counterpart_never_uses_aggregate_when_sources_exist` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_counterpart_does_not_repeat_derived_turn_report_source` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_character_projection_shows_monthly_public_source_once_after_chapter_write` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_shared_archive_storage_never_writes_restricted_aggregate` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_character_added_after_archive_cannot_read_old_participant_source` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_with_only_derived_report_does_not_publish_its_body_again` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_counterpart_filters_derived_report_before_reaggregating_sources` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_chapter_counterpart_filters_settlement_narrative_derived_with_report` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |
| `test_883_legacy_aggregate_without_source_rows_does_not_authorize_knowledge` | 1 | **merge** | ③ 独有 archive/source_scope 迁 character_knowledge_489，重叠 exclusion/counterpart 删 |

### `tests/test_llm_channel_config.py`

- 规模：434 行 / 23 函数 / 23 节点 · 处置分布：`{'merge': 23}` · 主注：③ 与 runtime/web_llm 三叠

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_create_chat_model_respects_api_channel_over_backend_env` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_create_chat_model_uses_cli_channel_without_backend_env` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_load_llm_config_records_backend_env_as_cli_channel` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_loaded_api_config_is_not_rerouted_by_later_backend_env` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_load_llm_config_migrates_legacy_advanced_thinking_to_reasoning` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_load_llm_config_migrates_legacy_none_thinking_to_off` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_create_chat_model_maps_off_reasoning_to_openai_none` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_create_chat_model_leaves_openai_reasoning_default_unset` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_create_chat_model_maps_reasoning_strength_to_dashscope_thinking_budget` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_create_chat_model_maps_reasoning_strength_to_minimax_thinking` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_minimax_reasoning_strength_overrides_stale_thinking_level` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_legacy_backend_env_uses_runner_default_model_not_api_model` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_verify_llm_available_respects_api_channel_over_backend_env` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_verify_llm_available_smokes_cli_channel_without_backend_env` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_verify_llm_available_cli_channel_failure_raises` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_verify_llm_available_smokes_legacy_env_only_backend` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_verify_llm_available_legacy_env_only_failure_raises` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_for_role_preserves_cli_channel_fields_for_advanced_roles` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_config_constants_single_source_in_models` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_load_llm_config_cli_env_uses_cli_default_timeout_not_api` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_web_runtime_cli_no_saved_timeout_uses_cli_default` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_for_role_advanced_empty_cli_model_no_api_model_leak` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |
| `test_cli_empty_cli_model_does_not_leak_api_model_to_runner` | 1 | **merge** | ③ 共享 load/save/smoke 形状下沉一处；本文件作 channel 真源锚 |

### `tests/test_llm_key_helpers.py`

- 规模：45 行 / 5 函数 / 5 节点 · 处置分布：`{'delete': 5}` · 主注：④ 纯函数真值表

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_is_real_api_key_rejects_none_empty_placeholder_whitespace` | 1 | **delete** | ④ 纯函数真值表 |
| `test_is_real_api_key_rejects_keep_sentinel` | 1 | **delete** | ④ 纯函数真值表 |
| `test_is_real_api_key_accepts_real_key_trimmed` | 1 | **delete** | ④ 纯函数真值表 |
| `test_real_api_key_or_empty_normalizes_falsy_and_placeholder_to_empty` | 1 | **delete** | ④ 纯函数真值表 |
| `test_real_api_key_or_empty_returns_trimmed_real_key` | 1 | **delete** | ④ 纯函数真值表 |

### `tests/test_memory_person_changes.py`

- 规模：69 行 / 5 函数 / 5 节点 · 处置分布：`{'rewrite': 5}` · 主注：②⑤ effect_brief 精确中文

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_effect_brief_summarizes_unified_person_changes` | 1 | **rewrite** | ②⑤ effect_brief 精确中文 |
| `test_effect_brief_does_not_treat_raw_person_changes_as_applied` | 1 | **rewrite** | ②⑤ effect_brief 精确中文 |
| `test_effect_brief_merges_direct_and_issue_person_changes` | 1 | **rewrite** | ②⑤ effect_brief 精确中文 |
| `test_effect_brief_dedupes_persisted_issue_person_changes` | 1 | **rewrite** | ②⑤ effect_brief 精确中文 |
| `test_effect_brief_does_not_call_derived_release_punishment` | 1 | **rewrite** | ②⑤ effect_brief 精确中文 |

### `tests/test_menu_lifecycle_drain_396.py`

- 规模：838 行 / 21 函数 / 21 节点 · 处置分布：`{'keep': 21}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_drain_and_close_session_waits_for_gate_then_closes` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_exit_to_menu_returns_before_delayed_close_drains` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_returns_before_delayed_close_drains` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_switches_db_path_and_archives_old_after_drain` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_get_main_db_path_prefers_active_db_over_launch_env` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_failure_restores_old_game_and_main_db_path` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_archive_move_failure_keeps_wal_and_shm` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_archive_moves_wal_and_shm_with_main_db` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_archive_rolls_back_main_db_when_wal_move_fails` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_archive_skips_move_when_session_close_fails` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_restore_main_db_path_config_ignores_active_remove_failure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_active_write_failure_restores_env_and_old_game` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_shutdown_waits_for_drain_before_returning_or_killing` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_shutdown_without_web_game_skips_drain_and_kills` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_with_ming_sim_db_env_does_not_clobber_old_configured_db` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_waits_for_queued_chat_stream_not_just_gate_holder` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_drain_rejects_late_pending_write_before_gate_acquire` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_spawn_pending_write_thread_start_failure_releases_ownership` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_switches_db_path_when_web_game_is_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_switches_db_path_when_web_game_none_and_no_env` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_after_exit_does_not_clobber_old_db_while_detach_drains` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_mindreading_491.py`

- 规模：302 行 / 14 函数 / 14 节点 · 处置分布：`{'keep': 14}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_reader_is_selected_by_inner_court_post_not_name` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_only_exact_unique_attendant_slots_can_mindread` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_multi_office_attendant_survives_persistence_without_weakening_unique_slot` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_agent_has_no_minister_session_history_or_tools` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_and_scouting_consume_the_same_precision_contract` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_model_receives_complete_qualitative_sources_and_result_enters_payload` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_default_seed_mindreading_materials_do_not_expose_integration_markers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_reads_current_structured_ledger_without_raw_scores` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_mindreading_record_survives_restore_without_entering_shared_history` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_undo_chat_turn_permanently_removes_mindreading_record` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_runtime_uses_existing_model_config_factory` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reply_is_an_explicit_pipeline_input` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_reader_eligibility_uses_current_db_office_after_reassignment` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_empty_model_text_fails_without_keyword_fallback` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_minister_chat_timeout.py`

- 规模：181 行 / 5 函数 / 5 节点 · 处置分布：`{'delete': 2, 'rewrite': 3}` · 主注：⑤ kwargs 伪行为→公开超时

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_minister_chat_timeout_shorter_than_settlement_timeout` | 1 | **delete** | ④ 常量数值比较，非行为 |
| `test_minister_chat_timeout_reasonable_value` | 1 | **delete** | ④ 常量数值比较，非行为 |
| `test_minister_agent_cli_timeout_capped` | 1 | **rewrite** | ⑤ 断言 kwargs 键名=伪行为 → 经公开短超时 fail 观察 |
| `test_minister_agent_api_timeout_capped` | 1 | **rewrite** | ⑤ 断言 kwargs 键名=伪行为 → 经公开短超时 fail 观察 |
| `test_minister_agent_does_not_mutate_original_llm_config` | 1 | **rewrite** | ⑤ 断言 kwargs 键名=伪行为 → 经公开短超时 fail 观察 |

### `tests/test_minister_context.py`

- 规模：1019 行 / 40 函数 / 47 节点 · 处置分布：`{'rewrite': 38, 'keep': 2}` · 主注：⑤② mock+盯文→真 DB projection

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_region_brief_has_content` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_region_brief_characterizes_abstract_scores_and_rejects_injected_values` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_building_brief_has_content` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_building_brief_uses_chinese_region_not_pinyin` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_building_brief_characterizes_injected_abstract_values` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_minister_memorial_tools_show_commitment_fields_and_progress` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_memorial_tools_characterize_all_abstract_stop_conditions` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_memorial_tools_hide_unlisted_abstract_stop_thresholds` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_memorial_tools_hide_abstract_resolve_and_fail_conditions` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_tools_preserve_comparison_operator_for_countable_conditions` | 6 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_estimate_resistance_returns_only_qualitative_level` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_estimate_resistance_levels_are_reachable` | 3 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_character_context_never_exposes_other_faction_dossiers` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_context_is_characterized_without_abstract_numbers` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_character_context_does_not_repeat_intrigue_label` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_character_and_faction_zero_scores_use_lowest_qualitative_bucket` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_minister_context_falls_back_for_character_without_dossier` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_identity_bucket_selects_objective_faction_dossier` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_court_brief_does_not_bypass_character_identity_scope` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_characterized_court_brief_scopes_faction_dossier_to_current_identity` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_agent_uses_only_its_character_knowledge_projection` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_minister_context_uses_real_db_projection_and_hides_excluded_secret` | 1 | **keep** | 真行为 真 DB projection 接缝 |
| `test_minister_agents_use_distinct_real_db_world_slices_by_office` | 1 | **keep** | 真行为 真 DB projection 接缝 |
| `test_minister_context_secret_order_chain_filters_final_tools_and_instructions` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_secret_order_blacklist_overrides_assignee_brief_and_reference_candidate` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_secret_source_boundary_does_not_hide_unrelated_chapter_material` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_inspect_treasury_ledger_honors_account_and_turn_window` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_inspect_treasury_ledger_respects_treasury_knowledge_domain` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_near_minister_army_report_keeps_one_complete_qualitative_fact` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_final_minister_context_rejects_any_injected_abstract_value_shape` | 1 | **rewrite** | ⑤ mock 顶替后协作断言 → 真接缝 |
| `test_final_minister_context_qualifies_unmocked_faction_and_power_reports` | 1 | **rewrite** | ⑤ mock 顶替后协作断言 → 真接缝 |
| `test_audience_faction_and_power_reports_never_emit_raw_abstract_axes` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_secret_order_tool_preserves_long_title_without_formal_cap` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_minister_tools_characterize_region_army_and_issue_progress` | 1 | **rewrite** | ⑤ mock+盯文→真 DB projection |
| `test_scale_fallback_court_roster_uses_complete_structured_query` | 1 | **rewrite** | ⑤ mock 顶替后协作断言 → 真接缝 |
| `test_scale_fallback_court_roster_rejects_poison_without_personnel_authorization` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_scale_fallback_court_roster_excludes_noncurrent_rows` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_scale_fallback_army_roster_uses_complete_structured_query` | 1 | **rewrite** | ⑤ mock 顶替后协作断言 → 真接缝 |
| `test_minister_tools_characterize_building_and_metric_outputs` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |
| `test_court_brief_keeps_countable_money_but_hides_abstract_scores` | 1 | **rewrite** | ②⑤ rendered 长中文 contains → 结构字段 |

### `tests/test_multi_directive_502.py`

- 规模：671 行 / 17 函数 / 18 节点 · 处置分布：`{'keep': 17}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_mixed_batch_stages_supported_decree_without_capturing_acting_appointment` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_utterance_mixed_batch_preserves_per_item_mode` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_two_new_decrees_stage_as_independent_candidates` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_verbal_approve_targets_one_of_many` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_verbal_reject_targets_one_others_survive` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_ambiguous_command_returns_structured_state_no_silent_default` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_multi_confirm_none_result_does_not_stage_third_decree` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_named_clarification_clears_flag_frees_sibling_default` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_night_promulgated_directives_identifiable_by_night_and_range` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_needs_clarification_directive_skipped_by_default_commit` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_supplement_targets_named_candidate_others_unchanged` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unnamed_revise_multi_does_not_stage_third` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_directive_candidate_preserves_underscore_flags` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_prefix_two_decrees_stage_independently` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_nonstream_web_chat_surfaces_ambiguous` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_nonstream_web_chat_no_ambiguous_key_is_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_clarification_cue_many_candidates_no_indexerror` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_named_characters_seed_484.py`

- 规模：176 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 8}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_r3_named_characters_load_legal_guilt_and_historical_offices` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r4_hu_tingyan_loader_and_db_preserve_non_holder_seed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r4_named_characters_debut_in_historical_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r6_xu_yingqiu_uses_verified_ministry_line_and_opening_status` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r4_loader_rejects_seed_guilt_list` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r5_loader_rejects_nested_seed_guilt_crime_list` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r5_loader_rejects_nested_seed_guilt_severity_object` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_r5_loader_preserves_zero_identity` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_near_minister_reports_492.py`

- 规模：220 行 / 17 函数 / 17 节点 · 处置分布：`{'keep': 17}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_frontier_vacancies_are_seeded_and_restore_from_characters` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_vacancy_projection_recognises_acting_office_text` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_office_report_answers_authorized_seeds_and_returns_unknown_elsewhere` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_generic_office_queries_return_current_vacancies` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_return_report_records_source_and_keeps_countable_facts` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_report_source_is_derived_from_query_not_caller_label` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_domain_reports_reuse_existing_qualitative_readers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_return_report_interface_does_not_depend_on_minister_reply` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_production_report_is_durable_and_scoped_to_the_questioned_minister` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_firsthand_requires_a_persisted_witness_record` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_firsthand_witness_must_match_questioned_domain` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_firsthand_report_uses_the_matching_witness_body` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_question_wording_cannot_create_firsthand_provenance` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_explicit_inquiry_overrides_matching_firsthand_witness` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unsupported_inquiry_is_not_persisted_as_false_office_report` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_bandit_inquiry_uses_shipped_inner_rebellion_kind` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_firsthand_report_prefers_newest_matching_durable_witness` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_new_game_smoke.py`

- 规模：166 行 / 7 函数 / 7 节点 · 处置分布：`{'keep': 7}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_new_game_has_fiscal_substrate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_enforces_foreign_keys_without_seed_violations` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unknown_event_id_fails_without_synthesizing_parent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unknown_office_type_fails_without_synthesizing_parent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_person_title_kind_does_not_materialize_office_parent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_existing_office_fk_violation_is_normalized_on_reopen` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_new_game_three_turn_chain_advances_substrate_and_restores` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_new_issues_section_rejections.py` 🔒

- 规模：516 行 / 25 函数 / 42 节点 · 处置分布：`{'keep': 25}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_temp_events_replaces_same_id_and_restores_original` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_non_dict_item_rejected_not_crash` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_dirty_coercion_field_rejected` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_bad_kind_rejected` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_dirty_inertia_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_oversized_severity_clamped_not_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_infinity_field_rejected_not_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_infinity_expected_months_rejected_not_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_severity_zero_preserved` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_garbage_severity_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_bool_float_int_field_rejected` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_falsy_nonstring_kind_rejected` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_insert_code_exception_propagates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_valid_decree_still_creates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_event_to_issue_insert_exception_propagates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_event_pool_insert_exception_propagates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_event_to_issue_duplicate_returns_none_not_raise` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_event_pool_rejects_expired_event` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_authoritative_event_pool_rejects_same_batch_obsolete_event` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_scalar_string_tags_rejected` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_non_string_tag_element_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_valid_list_tags_preserved` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_non_dict_cancel_cost_tolerated` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_issue_valid_cancel_cost_preserved` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_office_hedge_504.py`

- 规模：197 行 / 5 函数 / 5 节点 · 处置分布：`{'keep': 5}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_reinstatement_cancels_staged_dismissal` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_dismissal_after_reassignment_cancels_appointment_but_still_stages` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cancellation_cancels_staged_appointment` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_plain_dismissal_without_opposing_pending_still_stages` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_secret_prefix_turn_runs_no_appointment_classifier` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_office_inference.py`

- 规模：267 行 / 10 函数 / 36 节点 · 处置分布：`{'rewrite': 1, 'keep': 9}` · 主注：④⑤ 表 lookup 瘦身

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_office_type_from_table` | 27 | **rewrite** | ④⑤ 大表 lookup parametrize 缩为代表性锚 |
| `test_后宫_current_type_short_circuits` | 1 | **keep** | 真行为 office 推断出口 |
| `test_unknown_falls_to_daiquan_without_backend` | 1 | **keep** | 真行为 office 推断出口 |
| `test_api_channel_unknown_office_does_not_use_backend_env` | 1 | **keep** | 真行为 office 推断出口 |
| `test_runtime_cli_unknown_office_uses_configured_runner_without_env` | 1 | **keep** | 真行为 office 推断出口 |
| `test_api_channel_unknown_office_ignores_cli_derived_cache` | 1 | **keep** | 真行为 office 推断出口 |
| `test_use_llm_false_skips_backend_and_trusts_content_type` | 1 | **keep** | 真行为 seed/session 不调 CLI |
| `test_fresh_seed_makes_no_office_type_backend_calls` | 1 | **keep** | 真行为 seed/session 不调 CLI |
| `test_fresh_gamesession_start_makes_no_backend_calls` | 1 | **keep** | 真行为 seed/session 不调 CLI |
| `test_sync_preserves_persisted_court_office_type_on_table_miss` | 1 | **keep** | 真行为 office 推断出口 |

### `tests/test_office_rank_562.py`

- 规模：421 行 / 18 函数 / 18 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_rank_table_covers_every_office_type_and_pins_ming_direction` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_white_body_high_appointment_is_marked_but_regular_first_office_is_not` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_appointment_dossier_uses_declared_type_for_uncommon_target_title` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_rank_demotion_and_two_band_promotion_follow_upward_formula` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_restoration_and_displaced_third_state_use_latest_historical_office` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_title_stems_keep_distinct_ming_bands_inside_same_office_type` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cabinet_titles_keep_nominal_ming_rank_instead_of_political_importance` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_concurrent_cabinet_office_uses_the_genuinely_higher_title` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_qualified_titles_match_the_requested_axis_not_an_institutional_stem` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_leverage_multiplier_uses_canonical_office_rank_table_only` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_unofficed_and_offstage_degree_labels_are_genuine_first_appointments` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_historical_military_commands_and_cabinet_fallback_use_nominal_bands` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_one_tokenizer_preserves_real_concurrent_offices_and_drops_only_pollution` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_leverage_uses_min_modifiers_within_title_and_max_across_offices` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_existing_proposed_appointment_dossier_gets_one_time_break_rank_backfill` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_recognizable_archive_title_survives_blank_or_legacy_office_type` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_seed_archives_clean_historical_office_for_dismissed_ministers` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_override_breach_costs_564.py` 🔒

- 规模：527 行 / 19 函数 / 25 节点 · 处置分布：`{'keep': 19}` · 主注：真行为🔒 新 #564 闸类

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_force_land_survey_charges_three_costs_without_eunuch_reaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_signed_reactions_use_typed_direction_not_narrative_words` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_midzhi_rejection_charges_only_parties_and_stigma_then_force_only_authority` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_midzhi_rejudgment_changed_party_list_has_group_level_idempotency` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_costs_are_idempotent_and_survive_restore` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_force_then_breach_charges_each_real_entry_independently` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_breach_excludes_stale_minister_faction_from_costs` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_breach_skips_dead_but_records_living_offstage_relations` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cancel_linked_issue_breaches_only_its_origin_dossier_once` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_apply_rejects_invalid_mode_decision_reaction_shape_before_writes` | 5 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_force_rejects_missing_or_stale_judge_reactions_before_any_cost` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_force_rejects_malformed_judge_reactions_before_any_cost` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_force_rejects_old_only_judge_reactions_atomically` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_false_breach_rolls_back_with_later_cancellation_failure` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_active_commitment_can_breach_closed_issued_dossier_but_not_never_issued` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_breach_charges_authority_ministers_and_related_factions_once` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_chosen_rescript_actions_settle_via_promulgation_path` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_parallel_extractors.py`

- 规模：317 行 / 14 函数 / 14 节点 · 处置分布：`{'keep': 14}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_parallel_extract_matches_serial` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_shared_new_issues_from_issues_and_personnel_secret_are_merged` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_merge_non_list_new_issues_does_not_clobber_merged_list` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_merge_dedups_same_origin_commitment_across_modules` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_merge_keeps_multiple_distinct_fundings_under_same_origin_ref` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_merge_keeps_distinct_non_recurring_commitments_under_same_origin_ref` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_parallel_extract_runs_concurrently` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_serial_extract_stays_serial` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_passes_parallel_for_cli_backend` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_serial_for_non_cli_backend` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_serial_for_non_codex_cli_runner` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cli_backend_parallel_safe_resolution` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cli_trace_concurrent_writes_not_corrupted` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_parallel_extract_propagates_extractor_error` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_pending_actions.py` 🔒

- 规模：2493 行 / 80 函数 / 80 节点 · 处置分布：`{'keep': 80}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_secret_order_update_intent_stages_not_mutates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_rush_intent_stages_and_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_rush_intent_preserves_zero_deadline` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_rush_deadline_zero_commits_immediate_review` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_submit_intent_stages_and_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_progress_intent_stages_and_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pre_settle_commits_pending_at_decree_front` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_silent_new_secret_order_lands_at_checkpoint_without_pending_visibility` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_endpoint_delegates_to_chat_confirmation_flow` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_api_create_secret_order_preserves_explicit_zero_deadline` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_api_create_secret_order_supports_pydantic_v1_fields_set` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_api_create_secret_order_ignores_malformed_tags` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_marks_unapplicable_failed_not_orphan` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_rejects_blank_new_secret_order_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_rejects_malformed_secret_order_deadline_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_rolls_back_secret_order_when_status_mark_fails` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_undo_chat_turn_removes_staged_pending_action` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_commits_staged` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_withdraw_pending_action_removes_before_decree` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_withdraw_pending_action_does_not_commit_outer_transaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_actions_endpoints` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_actions_endpoint_hides_new_secret_order_candidates` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_advance_without_edict_lands_hidden_pending_secret_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_advance_without_edict_returns_failed_secret_order_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_advance_without_edict_settlement_abort_returns_409` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_advance_without_edict_default_approves_into_one_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_turn_previews_only_canonical_default_eligible_directives` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_advance_without_edict_routes_existing_draft_to_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_consort_cultivate_stages_and_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_does_not_crash_when_action_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_no_stage_for_non_active_target` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_pending_actions_applies_staged_update_at_decree` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_appointment_intent_stages_office_action` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_decree_prefix_appointment_not_double_staged` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_applies_at_decree` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_affirm_commits_staged_now` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_affirm_does_not_restage_restated_action` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_reject_drops_staged` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_affirm_secret_order_landing_failure_is_reported` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_reuses_stored_payload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_rejects_settlement_recovery_phase` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_status_failure_rolls_back_created_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_apply_exception_rolls_back_side_effects` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_pending_action_false_rolls_back_side_effects` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_false_rolls_back_side_effects` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_conversational_draft_false_rolls_back_side_effects` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_drop_pending_actions_for_minister_does_not_commit_outer_transaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_api_retire_failure_rolls_back_created_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_refresh_failure_does_not_duplicate` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_retires_confirmation_chat_undo` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_retires_creation_and_confirmation_chat_undo` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_pending_action_endpoint_returns_fresh_undo_state` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_action_failures_endpoint_lists_all_failed_secret_orders` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_non_secret_pending_failure_payload_does_not_promise_retry` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settling_secret_failure_payload_is_not_retryable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_failed_secret_order_does_not_block_later_audience` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unresolved_failed_secret_order_is_ignored_after_turn_boundary` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_default_approval_secret_order_failure_surfaces_after_turn_boundary` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_retry_failed_secret_order_preserves_original_issue_turn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_successful_secret_order_confirmation_stays_quiet` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_affirm_commits_office_now` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_new_office_action_restores_when_post_create_helper_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_promotes_existing_minister` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_dismiss_clears_db_and_memory_office` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_affirm_filters_by_summoned_minister` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_no_response_keeps_staged` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_consort_gets_office_type` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_existing_minister_by_alias` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_reappoint_reactivates_dismissed_minister` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_rejects_dead_person` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_appointment_empty_office_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_dismiss_foreign_actor_noop` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_dismiss_nonactive_minister_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_displace_duplicate_offices_recomputes_office_type` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_dismiss_refreshes_registry` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_office_appointment_refreshes_displaced_holder` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dialogue_reject_filters_by_summoned_minister` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_chat_proposal_not_staged_at_front_half_done` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_chat_confirm_defers_commit_at_front_half_done` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_front_half_done_directive_confirmation_commits_without_second_review` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_person_archive_contract_index.py`

- 规模：233 行 / 7 函数 / 7 节点 · 处置分布：`{'delete': 2, 'rewrite': 5}` · 主注：④⑤ 常量矩阵→行为或删

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_person_archive_contract_index_exposes_canonical_terms_and_scenarios` | 1 | **delete** | ④ 常量矩阵/术语表自证，非 applier 行为 |
| `test_person_transition_matrix_covers_all_status_action_pairs` | 1 | **delete** | ④ 常量矩阵/术语表自证，非 applier 行为 |
| `test_contract_index_cross_checks_references` | 1 | **rewrite** | ⑤ 常量矩阵→行为或删 |
| `test_person_transition_resolver_applies_reason_code_special_cases_first` | 1 | **rewrite** | ⑤ 常量矩阵→行为或删 |
| `test_acceptance_scenario_transition_checks_match_resolver_outputs` | 1 | **rewrite** | ⑤ 常量矩阵→行为或删 |
| `test_active_transition_normalization_depends_on_current_title_kind` | 1 | **rewrite** | ⑤ 常量矩阵→行为或删 |
| `test_reason_code_normalization_keeps_missing_distinct_from_unknown` | 1 | **rewrite** | ⑤ 经 person_delta 公共出口测 reason_code |

### `tests/test_person_archive_schema.py`

- 规模：180 行 / 6 函数 / 6 节点 · 处置分布：`{'keep': 6}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_characters_table_has_person_archive_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_person_logs_table_records_person_archive_audit_chain` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_person_logs_accepts_audit_rows_for_existing_characters` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_add_character_persists_transit_to` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_old_save_schema_is_upgraded_for_person_archive_fields` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_north_star_named_figures_are_seeded_with_identity_metadata` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_person_delta_adapter.py` 🔒

- 规模：4135 行 / 113 函数 / 126 节点 · 处置分布：`{'keep': 113}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_normalize_person_changes_keeps_new_key_items` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_normalize_person_changes_translates_legacy_keys_in_replay_order` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_normalize_legacy_person_changes_preserves_origin` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_normalize_person_changes_ignores_non_item_shapes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_exposes_normalized_person_changes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_change_power_move` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_person_change_power_move_without_way` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_invalid_loyalty_assessment` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_clamps_loyalty_assessment_delta` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_loyalty_assessment_does_not_commit_inside_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_person_changes_disposition_does_not_commit_inside_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_one_time_grant_and_assessment_do_not_create_commitment_issue` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_malformed_power_move_backlash_before_writing` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_status_change_rejects_non_active_target_before_transition_matrix` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_forged_legacy_partial_power_way` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_power_move_without_backlash_side_effect` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_change_office_action` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_unknown_person_change_new_appointment` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_trapped_prisoner_appointment` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_legacy_trapped_prisoner_office_change` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_materializes_derived_release_before_appointment` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_materializes_displaced_holder_as_talent_pool_change` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_clears_displaced_reason_when_reappointed` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_does_not_release_when_derived_appointment_is_invalid` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_accepts_status_reason_as_person_reason` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rolls_back_derived_release_when_office_write_fails` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_derived_release_rejection_keeps_prior_person_change_in_atomic_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_derived_release_restores_when_post_office_helper_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_does_not_release_non_ming_when_derived_appointment_is_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_change_consort_title` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_preserves_legacy_consort_appointment_rejection` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_consort_title_for_unknown_candidate` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_change_disposition` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_change_banish` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_banish_from_imprisoned` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_offstage_disposition_clears_db_and_content_office` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_persists_reason_code_and_person_log` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_allegiance_change_rebinds_identity_title` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_treats_active_identity_title_as_unappointed` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_add_character_person_title_skips_office_type_scaffold` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_add_character_non_canonical_office_type_still_raises` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_seed_backfill_skips_person_title_character_offices` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_character_office_person_title_survives_stem_collision` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_invalid_person_dispositions` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_unknown_person_change` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_dead_status_outbound` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_applies_person_travel_and_exposes_transit_to` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_court_roster_is_active_only_dismissed_in_talent_pool` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_talent_pool_ming_noncourt_only` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_talent_pool_excludes_amnestied_rebel_by_faction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_court_roster_excludes_active_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extractor_active_ministers_excludes_active_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_talent_pool_excludes_prince_unfilled_and_future_debut` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_registry_and_tools_court_roster_exclude_active_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_office_appointment_rejects_vassal_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_list_ministers_excludes_active_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_rejects_vassal_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_rejects_vassal_prince_by_alias` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_persists_canonical_name` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_rejects_foreign_power` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_rejects_foreign_power_by_alias` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_secret_order_allows_returned_defector` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_dismiss_rejects_vassal_prince` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_extractor_active_ministers_ming_noncourt_only` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_person_log_normalized_not_truncated` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_invalid_person_travel` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_rejects_unknown_person_travel_region` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_person_disposition_clears_existing_transit_to` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_character_status_clears_transit_to_when_leaving_active` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_character_status_clears_office_for_offstage` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_character_status_clears_stale_reason_code_when_missing` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_status_change_clears_transit_to_after_person_travel` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_new_person_changes_shadow_legacy_person_keys` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_empty_new_person_change_key_does_not_shadow_legacy_normalization` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_personnel_secret_module_fields_only_advertise_unified_person_key` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_payload_talent_pool_includes_retired_dismissed_with_reason_code` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_political_marker_is_audit_only_no_status_premigration` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reappoint_nonactive_syncs_character_reason_to_db` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reappoint_rollback_restores_character_reason` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_disposition_manual_rollback_restores_memory_reason_fields` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unified_appointment_resolves_alias_before_hallucinated_guard` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_new_appointment_falsy_return_restores_snapshot` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_payload_talent_pool_includes_displaced_oncall_holder` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fresh_seed_migrates_legacy_office_pollution` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_office_pollution_migrated_on_load` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_legacy_office_pollution_resolves_transit_to_region_id` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_displaced_holder_transit_to_cleared` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_historical_death_tick_sets_reason_code` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_historical_death_tick_writes_person_log` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_historical_debut_tick_sets_reason_code_and_log` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_yizhu_sets_active_in_new_master_service` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_consort_candidate_falls_out_to_offstage` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_syncs_reason_code_status_reason_to_content` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_disposition_syncs_reason_code_to_content_in_txn` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reappointment_clears_displaced_mark_in_both_db_and_content` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_migration_does_not_write_nonregion_location` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_yizhu_clears_status_reason_in_db` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s2_reappointment_derives_qifu_from_retired` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s3_reappointment_derives_zhaoxue_from_dismissed` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s4_reappointment_derives_duoqing_when_mourning` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_person_change_rejects_unknown_action_not_silent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s9_consort_leaves_palace_clears_office` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s15_amnesty_to_ming_then_appoint` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bandit_amnesty_rejects_same_power_top_level_suppression` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bandit_amnesty_rejects_same_power_top_level_suppression_when_backlash_empty` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_bandit_amnesty_does_not_block_same_power_suppression` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_orphan_bandit_power_can_be_suppressed_when_dead_leader_amnesty_is_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bandit_amnesty_rejects_backlash_targeting_another_bandit_power` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_s8_demotion_release_then_lower_appointment_derives_qifu` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_office_appointment_new_person_person_title_no_dirty_office_row` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fresh_static_seed_person_title_character_no_offices_parent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_office_appointment_person_title_survives_stem_collision` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_person_write_inventory.py`

- 规模：108 行 / 5 函数 / 5 节点 · 处置分布：`{'delete': 5}` · 主注：④ AST 扫描器自测

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_person_write_inventory_covers_current_character_sql_writes` | 1 | **delete** | ④ AST 扫描器自测 |
| `test_person_write_inventory_classifies_each_write_point_disposition` | 1 | **delete** | ④ AST 扫描器自测 |
| `test_person_write_inventory_lists_pending_migration_locations` | 1 | **delete** | ④ AST 扫描器自测 |
| `test_person_write_inventory_scanner_fallbacks_are_explicit` | 1 | **delete** | ④ AST 扫描器自测 |
| `test_scanner_detects_fstring_character_write` | 1 | **delete** | ④ AST 扫描器自测 |

### `tests/test_personnel_origin_prompt_558.py`

- 规模：24 行 / 1 函数 / 1 节点 · 处置分布：`{'rewrite': 1}` · 主注：②⑤ prompt 字面钉

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_decree_driven_personnel_examples_reference_promulgated_dossier` | 1 | **rewrite** | ②⑤ prompt 字面钉 |

### `tests/test_player_payload_1022.py`

- 规模：155 行 / 3 函数 / 4 节点 · 处置分布：`{'keep': 3}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_history_payload_preserves_narrative_without_machine_ledger` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settlement_sse_routes_serialize_only_player_narrative` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_cli_skill_card_command_uses_qualitative_character_bands` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_power_section_rejections.py` 🔒

- 规模：272 行 / 12 函数 / 12 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_unknown_power_id_rejected_good_item_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_illegal_power_field_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_power_deltas_code_exception_aborts_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unknown_person_power_change_rejected_good_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_canonical_person_power_writer_code_exception_is_fail_loud` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_power_change_formatter_skips_rejected_items` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_power_value_rejected_sibling_field_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_power_value_string_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_ming_power_update_rejected_with_trace` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_float_and_bool_power_values_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reason_carrier_aliases_not_recorded_as_rejection` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_all_reason_aliases_consumed_as_reason` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_pre_settle_transaction.py` 🔒

- 规模：504 行 / 18 函数 / 18 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_crash_reload_at_settling_no_double_fiscal_tick` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settling_survives_begin_turn_phase_whitelist` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_due_secret_order_submission_rolls_back_on_pre_settle_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_driver_pre_settle_same_transaction_semantics` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_crash_inside_pre_settle_no_missing_fiscal` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_two_consecutive_driver_settles_both_get_fiscal_tick` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_enter_review_does_not_clobber_settling` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_refused_after_settling` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_fallback_tail_resets_settling` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_pause_persists_awaiting_phase_durably` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pre_settle_guard_covers_awaiting_decision` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_sticky_phases_cover_awaiting_decision` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_refused_at_awaiting` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resolve_turn_idempotent_at_awaiting` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_guarded_early_return_does_not_consume_pending` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_write_decree_raises_at_awaiting_not_resolveresult` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_hitl_pause_crash_reloads_memory` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_placeholder_save_crash_rolls_back_settling` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_production_person_key_contract_558.py`

- 规模：44 行 / 2 函数 / 2 节点 · 处置分布：`{'keep': 2}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_initiative_enrichment_guidance_only_names_canonical_person_writer` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_production_tool_guidance_only_names_canonical_person_writer` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_promulgation_judge_561.py` 🔒

- 规模：768 行 / 24 函数 / 39 节点 · 处置分布：`{'keep': 24}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_promulgation_context_is_deterministic_and_excludes_satisfaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_history_only_projects_forced_and_midzhi_markers` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_gate_extracts_actual_cli_judge_payload_and_rejects_ambiguous_capture` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_verdict_list_shape_has_one_canonical_authority` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_verdict_rejects_unknown_fields` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgated_verdict_rejects_rejection_only_fields` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_gate_reconsideration_removes_only_named_opponent_and_keeps_real_bench` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_gate_reconsideration_resolves_missing_target_to_land_survey` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_gate_evidence_reloads_dossier_after_reconsideration_mutation` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_gate_second_verdict_reads_pending_or_applied_history_strictly` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_judge_preserves_role_resolved_token_budget` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_promulgation_verdict_accepts_exact_keys_for_each_mode` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_exact_keys_accept_only_empty_legal_reason_slot` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_default_promulgation_judge_uses_one_batch_and_existing_validator` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_snapshot_must_equal_the_prepared_judge_input` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_appointment_tenure_is_the_rejection_snapshot_value` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_non_gatekeeper_character_cannot_be_named_as_gatekeeper` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_ordinary_rejection_cannot_claim_midzhi_unpromulgatable` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reviewed_and_palace_exempt_dossiers_close_in_one_default_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_review_exempt_actions_auto_promulgate_without_judge_contract_abort` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_default_rejected_verdict_is_validated_persisted_and_becomes_rescript_decision` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_malformed_default_top_level_preserves_parsed_payload_in_rejection_report` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_invalid_default_rejected_verdict_reaches_rejection_tracer` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_judge_gate_examples_and_simulator_rejection_narrative_boundary` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_promulgation_seam_560.py` 🔒

- 规模：579 行 / 18 函数 / 28 节点 · 处置分布：`{'keep': 18}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_default_promulgation_stub_passes_every_dossier_without_collaborators` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_injected_promulgation_batch_cannot_silently_omit_a_dossier` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_reuses_durable_batch_after_pre_simulation_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_wraps_corrupt_durable_verdict_on_real_recovery` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rejects_bad_shape_without_persisting` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_wraps_scalar_verdict_item_for_audit` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rejects_rejected_verdict_without_affected_parties` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rejects_reserved_or_malformed_rejection_before_pending` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_preserves_each_invalid_items_contract_reason` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_audits_numeric_verdict_rejection` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rejects_polluted_promulgated_verdict_without_mutation` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_audits_only_invalid_provider_item_not_valid_or_exempt` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_audits_only_provider_overreach_in_mixed_coverage_failure` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_records_missing_coverage_as_one_batch_evidence` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rejects_incomplete_persisted_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_rolls_back_partial_batch_persistence` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_public_resolve_seam_ignores_previous_turn_batch` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_qualitative.py`

- 规模：28 行 / 3 函数 / 3 节点 · 处置分布：`{'delete': 3}` · 主注：④ 纯函数 band/bucket

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_qualitative_band_preserves_zero_and_uses_default_only_for_missing_or_invalid` | 1 | **delete** | ④ 纯函数 band/bucket |
| `test_qualitative_bucket_preserves_zero_and_supports_three_way_identity_bucket` | 1 | **delete** | ④ 纯函数 band/bucket |
| `test_building_qualitative_fields_is_shared_public_interface` | 1 | **delete** | ④ 纯函数 band/bucket |

### `tests/test_recommendations.py`

- 规模：323 行 / 12 函数 / 14 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_recommendation_candidates_are_limited_to_faction_or_character_knowledge` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_low_identity_recommender_can_see_high_identity_same_faction_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_private_and_public_structured_hearing_exposes_cross_faction_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_public_structured_hearing_exclusion_hides_cross_faction_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_hearing_exclusion_hides_candidate_by_current_position` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_source_local_exclusion_preserves_same_faction_network_candidate` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_faction_future_debut_is_not_recommendable` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_adopted_recommendation_is_an_auditable_event_after_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_minister_tools_only_submit_recommendations` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_recommendation_appointment_preserves_kind_and_restores_both_types` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_listed_heard_for_selection_candidate_stays_recovery_type_through_context_and_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_hearing_title_without_displacement_reason_is_not_talent_pool_candidate` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_region_cannon_delta.py`

- 规模：100 行 / 6 函数 / 6 节点 · 处置分布：`{'keep': 6}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_cannon_has_chinese_display_label` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_city_cannon_delta_lands_clamped` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_city_cannon_capped_at_zero_for_low_city_level` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_city_cannon_lower_bound_clamp_audited_not_as_cap` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_zero_cannon_request_leaves_no_log` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_illegal_region_field_rejected_not_raised` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_region_citydefense.py`

- 规模：62 行 / 5 函数 / 5 节点 · 处置分布：`{'keep': 5}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_regions_have_city_level_and_cannon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_city_level_tiers_by_history` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_region_cannon_cap_by_city_level` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_region_cannon_level0_caps_zero` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_simulator_payload_includes_region_defense` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_region_citydefense_display.py`

- 规模：47 行 / 3 函数 / 5 节点 · 处置分布：`{'merge': 3}` · 主注：③② display 文案孪生 citydefense

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_region_report_shows_city_defense` | 1 | **merge** | ②③ 文案 contains 并入 citydefense 结构断言或删 |
| `test_region_detail_shows_city_level_and_cannon` | 1 | **merge** | ②③ 文案 contains 并入 citydefense 结构断言或删 |
| `test_region_detail_uses_the_discrete_city_defense_scale` | 3 | **merge** | ②③ 文案 contains 并入 citydefense 结构断言或删 |

### `tests/test_rejection_wiring.py` 🔒

- 规模：804 行 / 24 函数 / 24 节点 · 处置分布：`{'keep': 24}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_rejected_item_lands_in_reports_and_jsonl` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rollback_leaves_no_rows_and_no_jsonl` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_attempt_derived_from_error_pack_dirs` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_engine_extractor_path_stamps_player_decree` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_summary_nested_rejections_are_collected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nested_atomic_success_path_does_not_orphan_jsonl` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_attempt_derivation_failure_does_not_abort_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_noncancellable_cancel_rejection_carries_reason` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rejected_appointment_carries_rejection_cause` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_bridge_synthesizes_reason_when_producer_omits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_tolerated_rejections_reach_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_item_json_is_original_delta_item_when_producer_carries_it` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_person_change_rejection_item_json_keeps_original_delta_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_power_move_rejection_item_json_keeps_original_person_delta_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_office_change_rejection_item_json_keeps_original_person_delta_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_non_ming_appointment_rejection_keeps_original_person_delta_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_power_move_backlash_rejection_lands_in_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_close_power_move_backlash_rejection_is_not_duplicated` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_power_move_backlash_rejection_lands_in_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_resimulation_inherits_player_source_from_ctx` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_player_decree_rejection_surfaces_prompt_in_turn_report` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_system_rejection_stays_silent_and_keeps_system_provenance` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_provenance_from_stored_recovers_all_forms` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_settling_recovery_fallthrough_preserves_system_source` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_relation_store_632.py`

- 规模：195 行 / 5 函数 / 5 节点 · 处置分布：`{'keep': 5}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_directed_edge_events_are_stored_and_queryable` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_edge_event_kind_and_evidence_are_fail_closed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_credit_contract_fixture_reads_as_semantic_directed_edges` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_relation_edges_survive_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_record_relation_edge_event_respects_caller_owned_transaction` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_release_bundle_assets.py`

- 规模：34 行 / 2 函数 / 2 节点 · 处置分布：`{'rewrite': 2}` · 主注：②⑤ .spec 字符串 contains

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_pool_portrait_scan_falls_back_to_built_dist_when_public_absent` | 1 | **rewrite** | ②⑤ .spec 字符串 contains |
| `test_pyinstaller_spec_does_not_duplicate_vite_public_assets` | 1 | **rewrite** | ②⑤ .spec 字符串 contains |

### `tests/test_rescript_choices_563.py`

- 规模：276 行 / 10 函数 / 13 节点 · 处置分布：`{'keep': 10}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_real_midzhi_entry_reaches_provider_and_persists_stigma` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejected_unpromulgatable_midzhi_omits_force_at_public_resolve_seam` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_manual_mode_declaration_overrides_extractor` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_manual_edit_preserves_existing_mode_when_text_and_extractor_are_silent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_missing_dossier_mode_defaults_to_ordinary` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_explicit_staging_prefers_caller_authority_before_minister_text` | 2 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_presence_aware_mode_preserves_draft_until_explicit_override` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_held_dossier_rejection_stigma_is_idempotent_across_months` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejected_midzhi_and_force_promulgation_are_idempotent` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_rejected_ordinary_force_promulgation_adds_rescript_stigma` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_resolve_context_recovery.py`

- 规模：378 行 / 16 函数 / 16 节点 · 处置分布：`{'keep': 16}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_persist_resolve_context_stores_extracted_delta` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_persist_resolve_context_stores_source_for_recovery` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_persist_resolve_context_source_defaults_system_simulation` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_persist_sanitizes_malformed_delta_and_records_rejection` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_persist_accepts_person_change_delta_after_applier_is_wired` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_clears_resolve_context_on_completion` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_resolve_context_survives_mid_settle_crash` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_hitl_phase1_save_path_not_regressed` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_e2e_persist_happens_in_real_settle_flow` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_extractor_failure_never_persists_as_ready` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_hitl_phase1_placeholder_extracted_is_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_genuinely_empty_delta_distinguishable_from_placeholder` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_e2e_genuinely_empty_delta_persists_as_ready` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_advance_without_edict_clears_stale_context` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_corrupt_extracted_json_returns_none_not_empty` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_type_corrupt_extracted_json_returns_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_runtime_llm_config.py`

- 规模：472 行 / 22 函数 / 22 节点 · 处置分布：`{'merge': 22}` · 主注：③ 与 channel/web 三叠

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_load_runtime_llm_missing_file_keeps_empty_dict_contract` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_malformed_json_returns_empty` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_coerces_stringified_numeric_fields` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_garbage_numeric_fields_fall_back_to_default` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_non_dict_payload_returns_empty` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_migrates_flat_api_config` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_persists_channel_slots` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_persists_api_reasoning_strength` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_api_save_preserves_cli_reasoning_strength` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_cli_save_preserves_api_reasoning_strength` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_cli_save_can_seed_api_reasoning_strength` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_can_clear_reasoning_strength_to_default` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_exposes_api_aliases_when_cli_is_active` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_llm_preserves_cli_reasoning_strength` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_preserves_existing_cli_slot_when_saving_api` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_save_runtime_llm_preserves_existing_api_slot_when_saving_cli` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_runtime_flat_cli_backend_placeholder_not_api_channel` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_cli_backend_active_total_on_unsupported_runner` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_create_chat_model_unsupported_cli_runner_raises_unavailable` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_for_role_advanced_drops_placeholder_key` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |
| `test_load_llm_config_api_mode_clears_placeholder` | 1 | **merge** | ③ 持久化槽与 channel/web 重叠，独有 slot 案迁入锚后删重叠 |

### `tests/test_secret_order_injection.py`

- 规模：66 行 / 4 函数 / 4 节点 · 处置分布：`{'keep': 4}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_pending_review_not_starved_by_full_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_all_pending_review_kept_even_over_cap` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_capped_when_no_pending` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_fills_remaining_budget_after_pending` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_secret_order_isolation_883.py` 🔒

- 规模：2106 行 / 41 函数 / 42 节点 · 处置分布：`{'keep': 41}` · 主注：①🔒 闸类；P0 已 preclassified

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_883_two_turn_probe_secret_never_enters_shared_archives` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_shared_summary_write_seam_rejects_secret_order_source` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_audience_chat_path_does_not_leave_secret_in_shared_sources` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_audience_chat_paraphrase_does_not_leave_origin_in_shared_sources` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_shared_write_seam_keeps_public_assignee_audience` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_public_audience_same_turn_survives_secret_classification` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_post_brief_public_audience_enters_shared_sources` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_pure_public_archive_lands_while_secret_brief_active` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_cross_turn_chat_origin_withheld_on_late_secret_create` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_zero_overlap_semantic_rewrite_withholds_prior_audience_origin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_thematic_public_audience_survives_secret_create` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_minister_reply_not_shared_before_classification` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_pure_public_minister_reply_released_after_settle` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_secret_chat_turn_withholds_both_sides_but_public_turn_survives` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_withhold_does_not_yank_old_released_public_user` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_release_stamps_original_message_date` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_shared_archive_bypass_positive_and_negative` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_held_user_chat_released_when_never_classified_as_secret` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_only_explicit_leak_conclusion_promotes_secret_order_to_public` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_cross_turn_repeat_disclosed_does_not_mint_duplicate_public_event` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_883_public_llm_contexts_never_preload_secret_orders` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_cross_person_speaker_user_origin_withheld_not_shared` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_same_window_pure_public_user_survives_secret_classification` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_stage_confirm_pin_provenance_not_max_held_user` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_non_create_stage_commit_update_withholds_oral_pin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_non_create_stage_commit_rush_withholds_oral_pin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_non_create_pure_public_not_auto_pinned_as_secret_origin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_production_tools_non_create_no_pure_public_auto_pin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_production_session_tool_path_progress_not_shared` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_production_session_extract_update_withholds_oral` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_production_extract_rush_progress_no_pure_public_pin` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_pending_secret_pin_survives_partial_commit_same_minister` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_rt01_two_secret_orders_different_assignees_no_cross_track` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_rt02_misassigned_provenance_follows_origin_message` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_rt03_late_chat_after_create_same_turn` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_rt04_undo_chat_turn_secret_order_brief_consistent` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_1026_secret_order_update_rollback_restores_existing_brief` | 2 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_rt05_save_restore_between_hold_and_release` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |
| `test_976_message_level_origin_persisted_on_brief` | 1 | **keep** | 🔒① 密令隔离闸类负向；P0 已 preclassified，禁再裸跑 classify |

### `tests/test_secret_order_monthly_progress_566.py` 🔒

- 规模：714 行 / 19 函数 / 24 节点 · 处置分布：`{'keep': 19}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_cli_no_edict_runs_private_monthly_extractor_and_restores_history` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_only_private_extractor_context_reads_canonical_history` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_only_emperor_private_payload_shows_monthly_report` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_disclosure_promotes_monthly_report_to_public_event_only_after_disclosure` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_titles_do_not_classify_long_orders_and_short_orders_do_not_report` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_only_an_existing_monthly_chain_gets_terminal_progress` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_character_terminal_status_closes_secret_orders_through_canonical_progress_rail` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_real_module_extractor_traces_private_context_through_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_current_secret_order_deadline_controls_monthly_eligibility` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_long_secret_order_routes_real_cli_to_full_settlement` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pending_short_secret_order_uses_real_cli_fast_advance` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_no_edict_endpoint_routes_real_long_order_to_full_settlement` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_web_short_order_fast_path_never_calls_extractor` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_simulator_fallback_missing_private_report_aborts_without_advancing` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_no_eligible_dossier_unknown_report_aborts_atomically` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_no_eligible_dossier_bad_report_shape_aborts_but_empty_values_advance` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_eligible_missing_report_aborts_settlement_but_empty_month_succeeds` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_missing_bad_unknown_and_duplicate_reports_are_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_secret_order_refresh.py`

- 规模：49 行 / 1 函数 / 1 节点 · 处置分布：`{'keep': 1}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_refresh_rebuilds_agent_with_new_secret_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_secret_order_section_rejections.py` 🔒

- 规模：196 行 / 9 函数 / 9 节点 · 处置分布：`{'keep': 9}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_close_unknown_order_id_missing_ref` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_nonint_order_id_invalid_enum` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_close_bad_status_invalid_enum` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_update_nonint_order_id_invalid_enum` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_update_unknown_order_id_missing_ref` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_update_valid_active_order_applies_no_reject` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_secret_order_update_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_apply_score_extraction_secret_order_close_respects_outer_transaction_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_oversized_order_id_rejected_not_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_secret_order_status_cn.py`

- 规模：234 行 / 12 函数 / 12 节点 · 处置分布：`{'merge': 12}` · 主注：③② 状态桶盯文+隔离面与 883 重叠

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_group_buckets_by_status_into_cn_keys` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_strips_english_status_field` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_preserves_carry_fields_and_maps_progress` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_truncates_content_to_120` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_drops_done_and_failed_orders` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_empty_input_returns_both_empty_groups` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_hardens_against_malformed_input` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_simulator_payload_never_contains_secret_orders` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_build_simulator_payload_omits_secret_orders_when_none_are_present` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_group_reads_progress_from_legacy_progress_key` | 1 | **merge** | ②③ 中文状态桶盯文→结构枚举；文件并入密令簇 |
| `test_recovered_grouped_normalizes_legacy_list` | 1 | **merge** | ③ 隔离断言迁 isolation_883；状态标签改结构桶 |
| `test_resolve_context_roundtrips_grouped_secret_orders_as_dict` | 1 | **merge** | ③ 隔离断言迁 isolation_883；状态标签改结构桶 |

### `tests/test_secret_order_update.py`

- 规模：179 行 / 10 函数 / 12 节点 · 处置分布：`{'keep': 10}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_secret_order_update_persists_new_explicit_secrecy_wording` | 3 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_upsert_creates_then_updates` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_upsert_different_minister_creates_new` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_by_id_targets_exact_order_not_newest` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_by_id_preserves_tags_when_none` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_recanonicalizes_new_secrecy_clause_and_preserves_long_text` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_by_id_refreshes_assignee_only_brief_after_restore` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_by_id_keeps_assignee_brief_identical_to_persisted_order` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_creation_brief_uses_persisted_truncated_title` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_update_by_id_noop_on_non_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_section4_rejections.py` 🔒

- 规模：758 行 / 31 函数 / 47 节点 · 处置分布：`{'keep': 31}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_unknown_region_rejected_good_item_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_illegal_region_field_rejected_sibling_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_region_value_rejected_sibling_lands` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_controlled_by_rejects_non_power_id_and_preserves_region` | 6 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_controlled_by_accepts_existing_power_ids_and_restore_hook` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_controlled_by_mixed_invalid_and_valid_siblings_apply` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unknown_army_rejected_good_item_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_illegal_army_field_rejected_sibling_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_army_value_rejected_sibling_lands` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_unknown_owner_power_army_rejected_good_builds` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_missing_manpower_rejected_good_builds` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_duplicate_army_without_manpower_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_deltas_code_exception_aborts_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_deltas_code_exception_aborts_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_armies_code_exception_aborts_settlement` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_cannon_over_cap_clamps_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_cannon_over_cap_clamps_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_army_firearm_over_100_clamps_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_region_army_formatters_skip_rejected_items` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_duplicate_army_noninteger_manpower_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_region_cannon_value_rejected_not_abort` | 4 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_dirty_optional_army_field_rejects_item` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_absent_optional_army_fields_use_defaults` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_path_tolerates_previously_skipped_cases` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_path_still_strict_for_historically_fatal` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nondict_new_army_item_recorded_not_silent` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_all_score_fields_guarded_on_creation` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_issue_path_tolerated_rejections_reach_reports` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_inertia_natural_resolution_tolerated_rejection_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_float_bool_army_delta_tolerated_on_issue_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_required_field_historical_strictness_on_issue_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_section_fiscal_rejections.py` 🔒

- 规模：750 行 / 35 函数 / 44 节点 · 处置分布：`{'keep': 35}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_remove_unknown_fiscal_key_rejected_good_removal_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_remove_dynamic_tax_still_zeroes_region_field` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_remove_structural_sink_loss_rate_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_remove_central_human_loss_rate_rejected_as_loss_pair` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_remove_central_human_loss_rate_stem_rejected_as_loss_pair` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_direct_remove_central_human_loss_rate_stem_refuses_loss_pair` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_duplicate_key_rejected_good_create_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_illegal_account_rejected_sibling_lands` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_dirty_init_value_rejected_not_silent_zero` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_absent_init_value_defaults_zero` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_unknown_key_rejected_good_change_lands` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_dirty_delta_rejected_sibling_lands` | 3 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_zero_delta_no_op_not_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_empty_key_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_dynamic_tax_rate_scales_region_field` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_structural_sink_loss_rate_below_floor_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_central_loss_rate_pair_above_100_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_change_central_loss_rate_rebalance_uses_batch_final_total` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_falsy_dirty_delta_still_rejected` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cleaner_passes_dirty_delta_through` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_cleaner_passes_dirty_create_fields_through` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_rate_only_sibling_collision_rejected_not_abort` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_empty_key_rejected_even_with_noop_delta` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_remove_missing_key_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_create_with_rate_suffix_key_rejected` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_negative_init_value_rejected_not_clamped` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_double_suffix_key_rejected_no_phantom` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_double_suffix_remove_rejected_not_destructive` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_sanitizer_passes_empty_key_items_through` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_chinese_direction_alias_accepted_on_driver_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_whitespace_only_key_rejected_on_driver_path` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_lossless_int_string_same_verdict_both_paths` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_driver_path_display_defaults_from_key` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_garbage_key_category_consistent_across_sections` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_fiscal_change_reopens_with_value_origin_history_and_scaled_rows` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_session_cli_fallback.py`

- 规模：2957 行 / 85 函数 / 92 节点 · 处置分布：`{'keep': 57, 'rewrite': 28}` · 主注：①⑤ P0 泄漏已部分堵；巩固纪律+去盯文

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_non_streaming_path_surfaces_pending_action_id` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_draft_prefix_with_active_secret_order_runs_zero_llm` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_staged_action_reply_gets_confirmation_cue` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_tool_call_pending_directive_reply_gets_confirmation_cue` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_tool_call_pending_secret_order_reply_gets_confirmation_cue` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_generic_please_your_majesty_does_not_suppress_confirmation_cue` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_tool_call_staged_new_secret_order_merges_minister_reply` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_tool_call_staged_secret_order_merge_updates_reply_assignee` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_staged_secret_order_assignee_merge_uses_llm_field_contract` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_tool_call_staged_new_secret_order_merges_missing_metadata` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_tool_call_staged_new_secret_order_keeps_explicit_zero_deadline` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_secret_order_tool_progress_stages_pending_action_not_direct_write` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_chat_prompt_builder_internal_typeerror_is_not_retried_without_turn_scope` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_propose_directive_tool_arguments_stages_draft` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_api_channel_rejects_existing_pending_action` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_api_channel_uses_api_extractor_for_nonliteral_confirmation` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_mixed_rejection_and_approval_cues_uses_semantic_extractor` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_question_with_approval_words_uses_semantic_extractor` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_negated_approval_phrase_is_rejection` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_soft_negated_approval_phrase_is_rejection` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_negated_approval_rejects_when_extractor_fails` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_bubi_zhaoban_rejects_when_extractor_fails` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_mixed_directive_and_secret_confirmation_commits_both` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_midzhi_confirmation_updates_selected_dossier_mode` | 2 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_confirmation_preserves_invalid_payload_for_terminal_failure_owner` | 3 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_night_approved_midzhi_confirmation_keeps_mode_through_close` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_mixed_directive_secret_confirmation_does_not_commit_unmentioned_office` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_confirmation_all_regex_does_not_treat_preparing_as_all_targets` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_duchayuan_does_not_confirm_directive_as_all_targets` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_secret_confirmation_does_not_drop_office_pending` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_mixed_directive_and_secret_rejection_drops_both` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_mixed_directive_and_secret_bare_doubuzhun_drops_both` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_tool_staged_action_is_not_confirmed_in_same_chat_turn` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_non_streaming_appointment_tool_stages_pending_action` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_turn_ignores_same_turn_secret_order_tool_output` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_secret_prefix_ignores_mismatched_directive_tool_output` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_commit_only_visible_pending_ids` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_confirmation_reject_only_visible_pending_ids` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_legacy_registered_secret_order_marker_parser_restages` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_secret_order_extract_fallback_preserves_structured_metadata` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_order_extract_keeps_explicit_zero_deadline` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_draft_prefix_with_pending_confirmation_runs_zero_llm` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_prefix_confirmation_uses_recent_context_for_order_body` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_api_tool_created_secret_order_skips_prefix_fallback_extraction` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_api_tool_staged_secret_order_skips_prefix_fallback_extraction` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_legacy_registered_secret_order_marker_is_restaged` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_legacy_registered_secret_order_restaging_rolls_back_pending_if_delete_fails` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_noop_appointment_intent_is_not_staged` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_secret_prefix_keyao_confirmation_uses_recent_context` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_prefix_confirmation_with_supplement_keeps_recent_context` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_api_channel_secret_prefix_confirmation_uses_recent_context` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_api_channel_secret_prefix_extracts_deadline_without_cli_helper` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_api_channel_mixed_confirmation_keeps_supplement_when_extract_fails` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_secret_context_path_preserves_multiple_related_emperor_task_lines` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_preserves_related_bingming_continuation` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_order_body_excludes_audience_role_labels` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_preserves_prior_minister_supplement` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_ignores_unrelated_prior_conversation` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_ignores_unrelated_prior_task_like_command` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_ignores_prior_task_with_same_assignee` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_ignores_unrelated_prior_task_before_lingqian` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_preserves_confidentiality_constraint_line` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_path_keeps_offtopic_llm_guard` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_secret_context_feed_isolates_by_open_night` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_noop_appointment_alias_target_is_not_staged` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_committed_draft_followup_merges_even_when_classifier_says_none` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_committed_draft_followup_merges_even_when_classifier_says_draft` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_chat_starts_cli_action_classification_before_reply_finishes` | 1 | **keep** | 真行为 classifier 契约（已 mock，非泄漏） |
| `test_non_parallel_safe_runner_skips_concurrent_classifier` | 1 | **keep** | 真行为 classifier 契约（已 mock，非泄漏） |
| `test_non_parallel_safe_chat_serially_classifies_new_actions` | 4 | **keep** | 真行为 classifier 契约（已 mock，非泄漏） |
| `test_api_chat_never_calls_cli_classifier` | 1 | **keep** | 真行为 classifier 契约（已 mock，非泄漏） |
| `test_begin_turn_syncs_offices_with_runtime_llm_config` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_chat_rollback_refresh_syncs_offices_with_runtime_llm_config` | 1 | **keep** | 真行为 API 通道会话契约 |
| `test_no_backend_is_noop` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_draft_prefix_stages_directive` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_runtime_cli_channel_without_env_stages_directive` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_runtime_cli_secret_prefix_merges_via_configured_runner` | 1 | **keep** | 真行为 显式 mock _run_agy 的 CLI 错误/路径契约 |
| `test_secret_prefix_creates_order` | 1 | **keep** | 真行为 显式 mock _run_agy 的 CLI 错误/路径契约 |
| `test_secret_prefix_upserts_not_duplicates_and_refreshes` | 1 | **keep** | 真行为 显式 mock _run_agy 的 CLI 错误/路径契约 |
| `test_existing_directive_not_overwritten` | 1 | **rewrite** | ①⑤ 复核无 classify 裸路径；去掉自由文本钉 |
| `test_conversation_update_lands_via_session_path` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_secret_conversation_actions_persist_complete_minister_reply` | 2 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_preclassified_secret_update_uses_reply_aware_extractor` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |
| `test_runtime_cli_conversation_update_uses_configured_runner_without_env` | 1 | **keep** | 真行为 显式 mock _run_agy 的 CLI 错误/路径契约 |
| `test_conversation_rush_skips_pending_review` | 1 | **keep** | 真行为 会话动作契约且已堵 CLI 泄漏（preclassified） |

### `tests/test_settle_channel_injection.py`

- 规模：167 行 / 5 函数 / 5 节点 · 处置分布：`{'keep': 5}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_real_flow_injects_channel_enrichment_into_settle` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_driver_path_no_env_is_deterministic` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_none_branch_legacy_env_enriches` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_driver_run_settle_records_malformed_delta` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_driver_run_settle_deterministic_under_legacy_env` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_settle_core.py`

- 规模：386 行 / 11 函数 / 11 节点 · 处置分布：`{'keep': 11}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_settle_with_delta_applies_region_and_advances_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_with_delta_invokes_injected_callbacks` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_with_delta_includes_inertia_person_changes_in_chapter_brief` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_persists_public_and_restricted_sources_before_archive_projection` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_private_audience_does_not_erase_independent_public_settlement` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settlement_pure_public_narrative_excludes_secret_brief_from_public_view` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settlement_pure_public_narrative_lands_while_secret_brief_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settlement_archive_writes_rollback_on_later_failure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pre_settle_runs_fixed_fiscal_tick` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pre_settle_persists_event_terminal_states_in_write_path` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_settle_with_delta_enter_failure_preserves_original` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_settlement_write_guard_393.py` 🔒

- 规模：428 行 / 11 函数 / 62 节点 · 处置分布：`{'keep': 11}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_directive_capture_runs_outside_write_gate` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_directive_capture_result_is_rejected_after_turn_changes` | 2 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_direct_db_write_refused_by_phase` | 34 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_direct_db_write_refused_when_gate_held` | 17 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_serialized_web_write_cm_contract` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_refused_by_phase` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_advance_without_edict_refused_when_gate_held` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_endpoint_refused_by_phase_before_chat` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_endpoint_refused_when_gate_held_before_chat` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_secret_order_endpoint_offloads_chat_work` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_direct_db_write_succeeds_when_free` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_six_sciences_seed_608.py`

- 规模：70 行 / 3 函数 / 3 节点 · 处置分布：`{'keep': 3}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_six_sciences_offices_infer_to_own_category` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_fresh_seed_contains_sourced_six_sciences_censors` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_six_sciences_censor_exit_recomputes_its_faction_leverage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_state_reload.py` 🔒

- 规模：369 行 / 15 函数 / 15 节点 · 处置分布：`{'keep': 15}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_reload_refreshes_state_in_place` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_scrubs_next_period_advance` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_passthrough_content_registry_no_crash` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_scrubs_dirty_settling_phase` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_pre_settle_self_reloads_memory_on_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rollback_purges_content_character_ghost` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_skipped_inside_nested_atomic` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_metrics_refresh_never_empty_window` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rollback_restores_existing_character_attributes` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_reload_passes_llm_config_to_content_rebuild` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_and_reload_commits_on_success` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_and_reload_reloads_and_reraises_at_depth0` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_and_reload_skips_reload_when_nested` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_and_reload_chains_reload_failure` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_and_reload_runs_on_error_before_reload` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_suggestions_chips_527.py`

- 规模：18 行 / 1 函数 / 1 节点 · 处置分布：`{'delete': 1}` · 主注：④ 同义反复 helper

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_suggestions_for_returns_exactly_two_prefix_chips` | 1 | **delete** | ④ 同义反复 helper |

### `tests/test_transaction_boundary.py` 🔒

- 规模：581 行 / 27 函数 / 27 节点 · 处置分布：`{'keep': 27}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_game_db_owns_transaction_tracks_atomic_and_open_transactions` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_rolls_back_on_error` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_normal_exit_commits_to_disk` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_suspends_internal_method_commit` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nested_atomic_inner_commit_held_outer_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nested_atomic_both_succeed_commits_once` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_rollback_still_works_during_suspension` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_outside_atomic_commit_is_real` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_fiscal_config_respects_caller_owned_transaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_set_fiscal_config_batch_respects_caller_owned_transaction` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_reraises_original_exception` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_nested_atomic_inner_error_rolls_back_at_outer` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_connection_context_inside_atomic_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_connection_context_outside_atomic_still_commits` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_swallowed_inner_exception_forces_outer_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_backup_to_inside_atomic_fails_loud` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_connection_rollback_attempts_all_runtime_callbacks` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_connection_commit_attempts_all_runtime_callbacks` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_executescript_inside_atomic_fails_loud` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_swallowed_conn_context_exception_forces_outer_rollback` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_ddl_first_inside_atomic_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_failure_in_conn_context_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_commit_failure_at_atomic_exit_rolls_back` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_atomic_rejects_plain_connection` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_ddl_after_swallowed_conn_context_does_not_escape` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_ddl_after_explicit_midatomic_rollback_does_not_escape` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |
| `test_begin_failure_at_entry_restores_flags` | 1 | **keep** | 🔒 闸类/负向或主契约，默认保留 |

### `tests/test_transit_aging_346.py`

- 规模：380 行 / 12 函数 / 12 节点 · 处置分布：`{'keep': 12}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_force_transit_arrivals_forces_overdue` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_force_transit_arrivals_skips_fresh_transit` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_force_transit_arrivals_skips_one_month` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_force_transit_arrivals_legacy_zero_start` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_force_transit_arrivals_syncs_content_mirror` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_行止_sets_transit_start_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_行止_arrival_clears_transit_start_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_行止_reemit_same_dest_preserves_start_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_行止_change_dest_resets_start_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_行止_reemit_same_dest_preserves_legacy_zero_start` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_pre_settle_forces_arrival_before_terminal_states` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_snapshot_restore_preserves_transit_start_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_web_audience_night_498.py`

- 规模：784 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 5, 'merge': 3}` · 主注：③ 与 audience_night_498 同根 #498

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_asgi_inflight_reply_lands_then_issue_closes_and_advances` | 1 | **keep** | 真行为 web/ASGI 独有接缝，合并簇时保留 |
| `test_night_approved_directive_closes_into_month_end_without_second_review` | 1 | **merge** | ③ 与 core audience_night_498 交叉的 advance/close 断言可去重 |
| `test_web_issue_close_binds_endorsements_gate_free_after_same_night_dossier` | 1 | **merge** | ③ 与 core audience_night_498 交叉的 advance/close 断言可去重 |
| `test_legacy_pending_only_advances_to_durable_dossier_without_review_api` | 1 | **merge** | ③ 与 core audience_night_498 交叉的 advance/close 断言可去重 |
| `test_asgi_hanging_chat_makes_issue_fail_closed` | 1 | **keep** | 真行为 web/ASGI 独有接缝，合并簇时保留 |
| `test_sync_advance_endpoint_does_not_stall_event_loop` | 1 | **keep** | 真行为 web/ASGI 独有接缝，合并簇时保留 |
| `test_asgi_phase_flip_while_waiting_gate_rejected` | 1 | **keep** | 真行为 web/ASGI 独有接缝，合并簇时保留 |
| `test_asgi_dossiered_directive_has_no_retired_review_surface` | 1 | **keep** | 真行为 web/ASGI 独有接缝，合并簇时保留 |

### `tests/test_web_budget_payload.py`

- 规模：99 行 / 2 函数 / 2 节点 · 处置分布：`{'keep': 2}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_budget_payload_filters_central_army_pay_fixed_flow` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_budget_payload_filters_real_substrate_hub_fixed_flow` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_web_chat_serialization_393.py`

- 规模：404 行 / 8 函数 / 8 节点 · 处置分布：`{'keep': 8}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_identity_setup_failure_closes_durable_turn_and_pending_owner_as_terminal_error` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_lightweight_stream_seam_reaches_done_without_durable_identity_or_night_signature` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_chat_stream_sse_waits_for_sync_generator_in_executor` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_stream_prompt_builder_internal_typeerror_is_not_retried_as_legacy_signature` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_streamed_secret_order_preserves_blacklist_through_commit_restore_transfer_and_disclosure` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_streamed_secret_order_update_pins_held_oral_and_keeps_it_private` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_streamed_secret_order_progress_does_not_pin_public_held_message` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_web_court_visibility.py`

- 规模：449 行 / 22 函数 / 22 节点 · 处置分布：`{'keep': 22}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_active_ming_minister_visible` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_non_ming_character_not_in_court` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_db_offstage_excluded_even_if_memory_active` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_db_active_included_even_if_memory_offstage` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_vassal_prince_excluded_from_court` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_offstage_former_minister_in_talent_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_minister_not_in_talent_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_vassal_prince_excluded_from_talent_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_amnestied_rebel_excluded_from_talent_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_same_year_future_month_debut_excluded_from_talent_pool` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_consort_excluded_from_court` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_vassal_prince_chat_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_active_consort_chat_not_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_zongfan_cannot_be_summoned_via_can_summon` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_enemy_active_character_cannot_be_summoned` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_summon_power_check_uses_db_not_content` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_normal_ming_minister_still_summonable` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_list_ministers_uses_db_power_id` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_find_existing_minister_uses_db_power_id` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_db_resolve_power_id_authoritative` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_vassal_prince_secret_order_rejected` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_secret_order_endpoint_preserves_long_title_into_confirmation` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

### `tests/test_web_issue_condition_display.py`

- 规模：58 行 / 6 函数 / 9 节点 · 处置分布：`{'rewrite': 6}` · 主注：②⑤ humanize 精确中文句

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_humanize_character_loyalty_condition_hides_machine_threshold` | 1 | **rewrite** | ②⑤ humanize 精确中文句 |
| `test_humanize_character_loyalty_condition_variants` | 4 | **rewrite** | ②⑤ humanize 精确中文句 |
| `test_humanize_non_character_condition_keeps_existing_region_translation` | 1 | **rewrite** | ②⑤ humanize 精确中文句 |
| `test_humanize_character_status_condition_hides_machine_key` | 1 | **rewrite** | ②⑤ humanize 精确中文句 |
| `test_humanize_character_location_condition_uses_field_label_and_value_label` | 1 | **rewrite** | ②⑤ humanize 精确中文句 |
| `test_humanize_character_low_loyalty_condition_hides_machine_threshold` | 1 | **rewrite** | ②⑤ humanize 精确中文句 |

### `tests/test_web_llm_runtime_config.py`

- 规模：973 行 / 38 函数 / 38 节点 · 处置分布：`{'merge': 14, 'keep': 24}` · 主注：③ 共享槽下沉；HTTP 独有 keep

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_runtime_cli_slot_builds_cli_llm_config_without_backend_env` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_advanced_llm_verification_preserves_api_channel_over_backend_env` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_advanced_llm_verification_preserves_reasoning_strength` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_runtime_api_reasoning_strength_builds_llm_config` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_runtime_env_legacy_advanced_thinking_builds_reasoning_strength` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_build_llm_config_switches_to_api_on_real_key_over_backend_env` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_build_llm_config_recovers_preserved_api_key_on_switch_back` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_set_llm_config_cli_placeholder_not_real_api_key` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_api_set_llm_config_response_reports_reasoning_capability` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_api_set_llm_config_explicit_cli_channel_switch` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_api_set_llm_config_keep_sentinels_pass_none_to_build` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_commit_cli_seeds_api_slot_from_session_when_slot_empty` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_commit_cli_preserves_when_slot_already_has_key` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_api_set_llm_config_commit_runs_on_event_loop` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_api_set_llm_config_verify_runs_off_event_loop` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |
| `test_menu_status_active_cli_unsupported_runner_not_ready_despite_preserved_api_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_active_cli_placeholder_api_key_not_counted` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_reports_reasoning_strength_capability_for_cli_runner` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_reports_inactive_cli_reasoning_strength` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_uses_advanced_model_for_api_reasoning_capability` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_save_llm_persists_cli_channel_without_api_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_save_cli_verify_runs_off_event_loop` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_unsupported_cli_runner_not_ready` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_save_llm_cli_channel_rejects_empty_runner` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_save_llm_validates_api_channel_over_backend_env` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_status_treats_saved_cli_runtime_as_ready_without_api_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_game_llm_config_reports_active_cli_channel_without_fake_api_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_game_llm_config_reports_inactive_cli_reasoning_strength` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_game_llm_config_uses_advanced_model_for_api_reasoning_capability` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_fresh_start_without_llm_keeps_existing_main_db` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_fresh_start_verify_failure_keeps_existing_main_db` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_fresh_start_cli_verify_failure_keeps_existing_main_db` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_fresh_start_invalid_cli_runner_keeps_existing_main_db` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_reset_cli_verify_failure_keeps_existing_main_db` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_menu_save_llm_api_channel_rejects_placeholder_existing_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_build_llm_config_does_not_reuse_placeholder_as_api_key` | 1 | **keep** | 真行为 web/menu/HTTP 独有接缝 |
| `test_llm_config_from_runtime_api_channel_drops_placeholder_key` | 1 | **merge** | ③ 与 channel/runtime 共享 load/save/placeholder 下沉 |

### `tests/test_yuan_arrival_185.py`

- 规模：213 行 / 2 函数 / 2 节点 · 处置分布：`{'keep': 2}`

| 测试 | 节点 | 处置 | 理由 |
|---|---:|---|---|
| `test_yuan_arrears_paid_then_arrives_e2e` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |
| `test_arrival_clearing_is_not_noop_negative_control` | 1 | **keep** | 真行为 经公共接缝观察外部行为 |

---

## 5. Kill-list 精粹（过庭素材）

### 5.1 delete（节点级完整点名）

| 文件::测试 | 节点 | 理由 |
|---|---:|---|
| `test_cli_backend.py::test_extract_assignee_hint_does_not_corrupt_name_with_trailing_verb` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_hint_keeps_cao_surname_characters` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_hint_greedy_strip_handles_all_verb_tails` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_action_pulls_verb_after_name` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_action_uses_hint_match_when_name_repeats` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_hint_keeps_wei_and_si_surnames` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_extract_assignee_hint_prefers_long_compound_prefixes` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_infer_tag_each_branch` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_infer_tag_order_minister_wins_over_decree` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_cli_backend.py::test_infer_tag_chapter_memory_before_extractor` | 1 | ④ 私有 _extract_assignee/_infer_tag，无独立外部行为 |
| `test_distance_matrix.py::test_bake_uses_half_endpoint_weights_and_zero_diagonal` | 1 | ④ 纯矩阵数学无游戏接缝 |
| `test_distance_matrix.py::test_bake_selects_fastest_route_and_preserves_triangle_inequality` | 1 | ④ 纯矩阵数学无游戏接缝 |
| `test_distance_matrix.py::test_runtime_reader_is_lookup_only` | 1 | ④ 纯矩阵数学无游戏接缝 |
| `test_distance_matrix.py::test_baked_content_covers_all_regions_and_three_golden_anchors` | 1 | ④ 纯矩阵数学无游戏接缝 |
| `test_extractor_misroute_surface.py::test_field_owner_map_covers_all_modules` | 1 | ④ 私有 _FIELD_OWNER_MODULE 表断言 |
| `test_llm_key_helpers.py::test_is_real_api_key_rejects_none_empty_placeholder_whitespace` | 1 | ④ 纯函数真值表 |
| `test_llm_key_helpers.py::test_is_real_api_key_rejects_keep_sentinel` | 1 | ④ 纯函数真值表 |
| `test_llm_key_helpers.py::test_is_real_api_key_accepts_real_key_trimmed` | 1 | ④ 纯函数真值表 |
| `test_llm_key_helpers.py::test_real_api_key_or_empty_normalizes_falsy_and_placeholder_to_empty` | 1 | ④ 纯函数真值表 |
| `test_llm_key_helpers.py::test_real_api_key_or_empty_returns_trimmed_real_key` | 1 | ④ 纯函数真值表 |
| `test_minister_chat_timeout.py::test_minister_chat_timeout_shorter_than_settlement_timeout` | 1 | ④ 常量数值比较，非行为 |
| `test_minister_chat_timeout.py::test_minister_chat_timeout_reasonable_value` | 1 | ④ 常量数值比较，非行为 |
| `test_person_archive_contract_index.py::test_person_archive_contract_index_exposes_canonical_terms_and_scenarios` | 1 | ④ 常量矩阵/术语表自证，非 applier 行为 |
| `test_person_archive_contract_index.py::test_person_transition_matrix_covers_all_status_action_pairs` | 1 | ④ 常量矩阵/术语表自证，非 applier 行为 |
| `test_person_write_inventory.py::test_person_write_inventory_covers_current_character_sql_writes` | 1 | ④ AST 扫描器自测 |
| `test_person_write_inventory.py::test_person_write_inventory_classifies_each_write_point_disposition` | 1 | ④ AST 扫描器自测 |
| `test_person_write_inventory.py::test_person_write_inventory_lists_pending_migration_locations` | 1 | ④ AST 扫描器自测 |
| `test_person_write_inventory.py::test_person_write_inventory_scanner_fallbacks_are_explicit` | 1 | ④ AST 扫描器自测 |
| `test_person_write_inventory.py::test_scanner_detects_fstring_character_write` | 1 | ④ AST 扫描器自测 |
| `test_qualitative.py::test_qualitative_band_preserves_zero_and_uses_default_only_for_missing_or_invalid` | 1 | ④ 纯函数 band/bucket |
| `test_qualitative.py::test_qualitative_bucket_preserves_zero_and_supports_three_way_identity_bucket` | 1 | ④ 纯函数 band/bucket |
| `test_qualitative.py::test_building_qualitative_fields_is_shared_public_interface` | 1 | ④ 纯函数 band/bucket |
| `test_suggestions_chips_527.py::test_suggestions_for_returns_exactly_two_prefix_chips` | 1 | ④ 同义反复 helper |

### 5.2 merge 簇执行序建议

1. LLM 三叠（低风险、低时长）
2. 城防 display + status_cn 隔离迁徙
3. #498 web 去交叉
4. #489 knowledge 并入 489（中风险，需对照密令 exclusion）

### 5.3 rewrite 优先序

| 优先级 | 文件 | 刀口 |
|---|---|---|
| P0 纪律 | `test_session_cli_fallback.py` | 禁止新增无 preclassified/mock 的 CLI apply；CI 可加 lint 钩 |
| P1 | `test_cli_backend.py` | 删 `_extract_assignee*`/`_infer_tag*`；runner 保持 mock |
| P1 | `test_minister_context.py` / `test_minister_chat_timeout.py` | 去盯文与 kwargs 伪行为 |
| P2 | display/prompt 盯文簇 | 结构断言替换精确散文 |
| P2 | `test_event_trigger_gate.py` / `test_fiscal_substrate_bridge.py` / `test_conversational_draft.py` | 参数化 + 夹具池化减 setup |

---

## 6. 方法与局限

- 收集：`.venv/bin/python -m pytest --collect-only -q` → 3081 passed-collect / 4.08s
- 静态扫描：AST 切测试函数 + 启发式（apply/classify/subprocess/中文断言/私有符号）+ 人工复核泄漏嫌疑 10 路
- **未**重跑全量 `--durations`（避免与评审争资源、且 P0 烧额度路径已在一阶段堵；时长数字继承 `TEST_AUDIT_1185.md` 冻结基线）
- 未改任何 `tests/**`；本文件为二阶段唯一产物
- 参数化节点归到函数级处置（同函数同处置）；若单参需例外，过庭执行时再拆
- 分类误差：偏 keep（闸类从宽）；delete 仅在无独立外部契约时下手

## 7. 验收钩（执行阶段，非本腿）

- [ ] 过庭通过本 kill-list
- [ ] 分批 delete/merge/rewrite；闸类负向不删
- [ ] 家族收尾全量 `.venv/bin/python -m pytest -q` 一次绿灯
- [ ] 终线墙钟 ≤120s（含 xdist/夹具池化，另腿）

---

## 附录 A. 处置计数（节点）

```
keep=2551 rewrite=398 merge=99 delete=33 total=3081
funcs keep=2108 rewrite=320 merge=94 delete=33 total=2555
```

## 附录 B. 文件主处置一览

| 文件 | 节点 | keep | rewrite | merge | delete |
|---|---:|---:|---:|---:|---:|
| `test_action_cluster_registry_515.py` | 16 | 16 | 0 | 0 | 0 |
| `test_adr0015_per_item_rejection.py` | 8 | 8 | 0 | 0 | 0 |
| `test_advance_paths_atomic.py` | 35 | 35 | 0 | 0 | 0 |
| `test_advances_section_rejections.py` | 24 | 24 | 0 | 0 | 0 |
| `test_appease_mao_contract.py` | 6 | 6 | 0 | 0 | 0 |
| `test_applier_contract.py` | 23 | 23 | 0 | 0 | 0 |
| `test_appointment_tenure_607.py` | 13 | 13 | 0 | 0 | 0 |
| `test_army_display_173.py` | 9 | 7 | 2 | 0 | 0 |
| `test_army_firearms.py` | 16 | 16 | 0 | 0 | 0 |
| `test_army_maintenance_retire_173.py` | 12 | 12 | 0 | 0 | 0 |
| `test_army_pay_source_prompt_contract.py` | 1 | 1 | 0 | 0 | 0 |
| `test_army_salary_44.py` | 24 | 24 | 0 | 0 | 0 |
| `test_audience_background.py` | 22 | 22 | 0 | 0 | 0 |
| `test_audience_continuous_507.py` | 8 | 8 | 0 | 0 | 0 |
| `test_audience_extraction_501.py` | 35 | 35 | 0 | 0 | 0 |
| `test_audience_night_498.py` | 17 | 17 | 0 | 0 | 0 |
| `test_audience_pipeline_499.py` | 13 | 13 | 0 | 0 | 0 |
| `test_audience_presence_500.py` | 14 | 14 | 0 | 0 | 0 |
| `test_audience_restore_505.py` | 13 | 13 | 0 | 0 | 0 |
| `test_audience_scroll_539.py` | 18 | 18 | 0 | 0 | 0 |
| `test_audience_undo_506.py` | 17 | 17 | 0 | 0 | 0 |
| `test_authority_ledger_611.py` | 14 | 14 | 0 | 0 | 0 |
| `test_bandit_power_model_190.py` | 4 | 4 | 0 | 0 | 0 |
| `test_beat_orchestration_503.py` | 17 | 17 | 0 | 0 | 0 |
| `test_character_knowledge_489.py` | 52 | 52 | 0 | 0 | 0 |
| `test_character_projection_1023.py` | 2 | 2 | 0 | 0 | 0 |
| `test_chat_mutations_freeze.py` | 6 | 6 | 0 | 0 | 0 |
| `test_chat_stream_failpaths_393.py` | 3 | 0 | 3 | 0 | 0 |
| `test_cli_backend.py` | 137 | 37 | 90 | 0 | 10 |
| `test_cli_model_choices.py` | 12 | 12 | 0 | 0 | 0 |
| `test_cli_play_turn.py` | 17 | 17 | 0 | 0 | 0 |
| `test_close_issues_section_rejections.py` | 19 | 19 | 0 | 0 | 0 |
| `test_commitment_display_348.py` | 24 | 2 | 22 | 0 | 0 |
| `test_conversational_draft.py` | 77 | 71 | 6 | 0 | 0 |
| `test_db_broad_except_surface.py` | 8 | 8 | 0 | 0 | 0 |
| `test_decision_event_binding_389.py` | 6 | 6 | 0 | 0 | 0 |
| `test_decree_commitment_creation_136.py` | 33 | 33 | 0 | 0 | 0 |
| `test_decree_commitment_schema_136.py` | 34 | 34 | 0 | 0 | 0 |
| `test_decree_commitment_settlement_229.py` | 34 | 34 | 0 | 0 | 0 |
| `test_decree_dossiers_571.py` | 171 | 171 | 0 | 0 | 0 |
| `test_distance_matrix.py` | 4 | 0 | 0 | 0 | 4 |
| `test_dossier_endorsements_612.py` | 11 | 11 | 0 | 0 | 0 |
| `test_dossier_links_559.py` | 42 | 42 | 0 | 0 | 0 |
| `test_driver.py` | 35 | 35 | 0 | 0 | 0 |
| `test_economy_section_rejections.py` | 11 | 11 | 0 | 0 | 0 |
| `test_effect_origin_558.py` | 13 | 13 | 0 | 0 | 0 |
| `test_empire_modifier_income_only_341.py` | 3 | 3 | 0 | 0 | 0 |
| `test_enrich_list_guards.py` | 7 | 7 | 0 | 0 | 0 |
| `test_env_isolation.py` | 1 | 1 | 0 | 0 | 0 |
| `test_error_pack.py` | 18 | 18 | 0 | 0 | 0 |
| `test_event_chain_cascade.py` | 16 | 16 | 0 | 0 | 0 |
| `test_event_outcome_retry.py` | 3 | 3 | 0 | 0 | 0 |
| `test_event_trigger_gate.py` | 203 | 203 | 0 | 0 | 0 |
| `test_extractor_misroute_surface.py` | 5 | 4 | 0 | 0 | 1 |
| `test_faction_class_section_rejections.py` | 11 | 11 | 0 | 0 | 0 |
| `test_faction_leverage_9.py` | 37 | 37 | 0 | 0 | 0 |
| `test_featured_dossiers_494.py` | 4 | 0 | 4 | 0 | 0 |
| `test_fiscal_levy_effect.py` | 49 | 49 | 0 | 0 | 0 |
| `test_fiscal_substrate_bridge.py` | 184 | 38 | 146 | 0 | 0 |
| `test_fiscal_tick.py` | 61 | 61 | 0 | 0 | 0 |
| `test_identity_seed_488.py` | 11 | 11 | 0 | 0 | 0 |
| `test_initiative_resolve_pairing.py` | 18 | 18 | 0 | 0 | 0 |
| `test_issue_entities.py` | 32 | 32 | 0 | 0 | 0 |
| `test_junxin_alias_loyalty_313.py` | 3 | 3 | 0 | 0 | 0 |
| `test_knowledge.py` | 20 | 0 | 0 | 20 | 0 |
| `test_llm_channel_config.py` | 23 | 0 | 0 | 23 | 0 |
| `test_llm_key_helpers.py` | 5 | 0 | 0 | 0 | 5 |
| `test_memory_person_changes.py` | 5 | 0 | 5 | 0 | 0 |
| `test_menu_lifecycle_drain_396.py` | 21 | 21 | 0 | 0 | 0 |
| `test_mindreading_491.py` | 14 | 14 | 0 | 0 | 0 |
| `test_minister_chat_timeout.py` | 5 | 0 | 3 | 0 | 2 |
| `test_minister_context.py` | 47 | 2 | 45 | 0 | 0 |
| `test_multi_directive_502.py` | 18 | 18 | 0 | 0 | 0 |
| `test_named_characters_seed_484.py` | 8 | 8 | 0 | 0 | 0 |
| `test_near_minister_reports_492.py` | 17 | 17 | 0 | 0 | 0 |
| `test_new_game_smoke.py` | 7 | 7 | 0 | 0 | 0 |
| `test_new_issues_section_rejections.py` | 42 | 42 | 0 | 0 | 0 |
| `test_office_hedge_504.py` | 5 | 5 | 0 | 0 | 0 |
| `test_office_inference.py` | 36 | 9 | 27 | 0 | 0 |
| `test_office_rank_562.py` | 18 | 18 | 0 | 0 | 0 |
| `test_override_breach_costs_564.py` | 25 | 25 | 0 | 0 | 0 |
| `test_parallel_extractors.py` | 14 | 14 | 0 | 0 | 0 |
| `test_pending_actions.py` | 80 | 80 | 0 | 0 | 0 |
| `test_person_archive_contract_index.py` | 7 | 0 | 5 | 0 | 2 |
| `test_person_archive_schema.py` | 6 | 6 | 0 | 0 | 0 |
| `test_person_delta_adapter.py` | 126 | 126 | 0 | 0 | 0 |
| `test_person_write_inventory.py` | 5 | 0 | 0 | 0 | 5 |
| `test_personnel_origin_prompt_558.py` | 1 | 0 | 1 | 0 | 0 |
| `test_player_payload_1022.py` | 4 | 4 | 0 | 0 | 0 |
| `test_power_section_rejections.py` | 12 | 12 | 0 | 0 | 0 |
| `test_pre_settle_transaction.py` | 18 | 18 | 0 | 0 | 0 |
| `test_production_person_key_contract_558.py` | 2 | 2 | 0 | 0 | 0 |
| `test_promulgation_judge_561.py` | 39 | 39 | 0 | 0 | 0 |
| `test_promulgation_seam_560.py` | 28 | 28 | 0 | 0 | 0 |
| `test_qualitative.py` | 3 | 0 | 0 | 0 | 3 |
| `test_recommendations.py` | 14 | 14 | 0 | 0 | 0 |
| `test_region_cannon_delta.py` | 6 | 6 | 0 | 0 | 0 |
| `test_region_citydefense.py` | 5 | 5 | 0 | 0 | 0 |
| `test_region_citydefense_display.py` | 5 | 0 | 0 | 5 | 0 |
| `test_rejection_wiring.py` | 24 | 24 | 0 | 0 | 0 |
| `test_relation_store_632.py` | 5 | 5 | 0 | 0 | 0 |
| `test_release_bundle_assets.py` | 2 | 0 | 2 | 0 | 0 |
| `test_rescript_choices_563.py` | 13 | 13 | 0 | 0 | 0 |
| `test_resolve_context_recovery.py` | 16 | 16 | 0 | 0 | 0 |
| `test_runtime_llm_config.py` | 22 | 0 | 0 | 22 | 0 |
| `test_secret_order_injection.py` | 4 | 4 | 0 | 0 | 0 |
| `test_secret_order_isolation_883.py` | 42 | 42 | 0 | 0 | 0 |
| `test_secret_order_monthly_progress_566.py` | 24 | 24 | 0 | 0 | 0 |
| `test_secret_order_refresh.py` | 1 | 1 | 0 | 0 | 0 |
| `test_secret_order_section_rejections.py` | 9 | 9 | 0 | 0 | 0 |
| `test_secret_order_status_cn.py` | 12 | 0 | 0 | 12 | 0 |
| `test_secret_order_update.py` | 12 | 12 | 0 | 0 | 0 |
| `test_section4_rejections.py` | 47 | 47 | 0 | 0 | 0 |
| `test_section_fiscal_rejections.py` | 44 | 44 | 0 | 0 | 0 |
| `test_session_cli_fallback.py` | 92 | 64 | 28 | 0 | 0 |
| `test_settle_channel_injection.py` | 5 | 5 | 0 | 0 | 0 |
| `test_settle_core.py` | 11 | 11 | 0 | 0 | 0 |
| `test_settlement_write_guard_393.py` | 62 | 62 | 0 | 0 | 0 |
| `test_six_sciences_seed_608.py` | 3 | 3 | 0 | 0 | 0 |
| `test_state_reload.py` | 15 | 15 | 0 | 0 | 0 |
| `test_suggestions_chips_527.py` | 1 | 0 | 0 | 0 | 1 |
| `test_transaction_boundary.py` | 27 | 27 | 0 | 0 | 0 |
| `test_transit_aging_346.py` | 12 | 12 | 0 | 0 | 0 |
| `test_web_audience_night_498.py` | 8 | 5 | 0 | 3 | 0 |
| `test_web_budget_payload.py` | 2 | 2 | 0 | 0 | 0 |
| `test_web_chat_serialization_393.py` | 8 | 8 | 0 | 0 | 0 |
| `test_web_court_visibility.py` | 22 | 22 | 0 | 0 | 0 |
| `test_web_issue_condition_display.py` | 9 | 0 | 9 | 0 | 0 |
| `test_web_llm_runtime_config.py` | 38 | 24 | 0 | 14 | 0 |
| `test_yuan_arrival_185.py` | 2 | 2 | 0 | 0 | 0 |

## 附录 C. 与 `TEST_AUDIT_1185.md` 关系

- 一阶段冻结件：计时基线 + 文件主类 + 初版 kill-list（根目录 `TEST_AUDIT_1185.md`）
- 本文件：二阶段 **逐测试处置清单** + 泄漏复核 + 净增减账，路径 `docs/test-cleanup-audit-1185.md`
- 冲突时：以本文件处置列为执行票面；计时数字仍以冻结件为基线直至收尾全量复测

