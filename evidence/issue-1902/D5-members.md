# D5 全成员表（全仓测试路径 265，人工+临时AST实读分类）

## 类定义（判词两条 D5 + 现行票面 + #1812，**未收窄**）

D5：测试清退——非法文本／信号约束，以及失效／重复／内部退役证明。

### D5-A 非法文本／信号约束（命中即成员）
1. 在呈现文本（detail/report/roster/label/condition/textContent/summary）上扫描机器字段名或词黑名单。
2. 以整段呈现文本相等／不等作契约（含 `text != raw`、detail/report 差分）。
3. 以呈现文数字集合／正则抽数作契约（`_ints` / `findall\\d+`）。
4. 锁定 formatter 固定措辞或 helper 生成物嵌入呈现（如「城防炮N门」、`city_defense_description in detail`、`population_wan_kou_label in detail`、`arrears_text in detail` 若非模型输入来源缝）。
5. 以诊断 tlog／实现信号条数或异常类名筛选为契约。
6. 无契约价值的弱自由文本约束（人物子串 + 文本不等）及专用夹具。

**合法保留（非「helper源标签泛化例外」）**：
- 闸类隔离：密令／知识／P4 HUD 不得泄漏。
- 结构化 ABI：payload/dict **键集合**缺席、账本 `army_logs` 等。
- **实际模型调用输入来源**／原始输出透传（如 #321 sit 字段进入 materials/report）。
- 固定界面铬字（菜单／按钮／设置页标签）——属 UI 固定话语，非叙事生成物（P7 射程外）。

### D5-B 失效／重复／内部退役证明
1. 仅查 `app.routes`／OpenAPI／`_registered` 的退役证明。
2. 与既有真实 HTTP 负向案同根重复的注册表证明。
3. 路径写错致变异仍绿的失效证明。
4. 只建数据再断言自己写入、未走旁路的「无旁路」伪证明。
5. 与既有结构化真实行为案重复的平行证明。

## 枚举原命令（全仓，非仅触及子集）

```bash
PRED='(^|/)(tests?/|__tests__/|conftest\.py$|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$|fixtures?/)'
git ls-files | rg -i "$PRED" | sort -u
# → 265 paths（本轮磁盘删除 2 个后现存 263；表仍覆盖 tracked 265）
```

临时调查（**/tmp only，不入仓**）：AST/正则枚举断言于 `/tmp/d5-audit-1902/`；最终仅本表与回执入卷。

分类代号：`R`保留/修理来源或真入口 · `W`盯文/呈现退役 · `H`helper/内部/重复 · `C`仅调用/夹具/未触及无残留 · `A`新增 · `D`退役整删 · `X`Web全仓纳入（保留依据见回执）

| # | 路径 | st | Δ/标记 | 类 | 依据（实读） |
|---:|---|---|---|---|---|
| 1 | `tests/README.md` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 2 | `tests/army_pay_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 3 | `tests/audience_chat_helpers.py` | A | FILE_ADD | A | 共享召对入口 helper 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 4 | `tests/cli_process_doubles.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 5 | `tests/conftest.py` | M | a-0/+1 | C | D7 原生任务 join/wait; 非 D5 来源类 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 6 | `tests/directive_entry_helpers.py` | A | FILE_ADD | A | 共享拟旨/草稿准备 helper 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 7 | `tests/dossier_test_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 8 | `tests/fiscal_test_utils.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 9 | `tests/fixtures/agno-2.7.3-py3-none-any.whl` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 10 | `tests/game_fixture_retained_inventory.tsv` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 11 | `tests/issue_stream_helpers.py` | A | FILE_ADD | A | SSE/issue 流 helper 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 12 | `tests/legacy_staging_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 13 | `tests/month_chain_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 14 | `tests/offline_audience_reply.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 15 | `tests/section_rejection_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 16 | `tests/sse_helpers.py` | A | FILE_ADD | A | parse_sse 共享 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 17 | `tests/test_adr0015_per_item_rejection.py` | M | a-7/+8 | R | 断言重组 -7/+8（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 18 | `tests/test_advance_paths_atomic.py` | M | a-4/+0 | H | inspect.getsource/hasattr 内部缺席证明 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 19 | `tests/test_advance_without_edict_token_1351.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 20 | `tests/test_advances_section_rejections.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 21 | `tests/test_affairs_1831.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 22 | `tests/test_applier_contract.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 23 | `tests/test_appointment_tenure_607.py` | M | a-1/+0 | W | 固定 ValueError 包装句≠注入来源; 回滚行为仍在 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 24 | `tests/test_army_card_status_1501.py` | M | a-6/+1 | R | 断言重组 -6/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 25 | `tests/test_army_display_173.py` | M | ROUND | R | 去 arrears_text in detail（helper 嵌入呈现）；保留军牌 ABI 键缺席+arrears_text 结构化变化 |
| 26 | `tests/test_army_firearms.py` | M | ROUND | H | 删 test_army_public_exits_surface_firearm_and_cannon：与既有 DB/抽取结构化案重复 |
| 27 | `tests/test_army_maintenance_retire_173.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 28 | `tests/test_army_pay_source_prompt_contract.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 29 | `tests/test_army_salary_44.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 30 | `tests/test_audience_background.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 31 | `tests/test_audience_continuous_507.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 32 | `tests/test_audience_draft_grant_once_1777.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 33 | `tests/test_audience_extraction_501.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 34 | `tests/test_audience_night_498.py` | M | a-1/+3 | R | 断言重组 -1/+3（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 35 | `tests/test_audience_presence_500.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 36 | `tests/test_audience_restore_505.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 37 | `tests/test_audience_scroll_539.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 38 | `tests/test_audience_translate_1837.py` | M | a-2/+1 | R | 断言重组 -2/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 39 | `tests/test_audience_translate_1837_reopen.py` | M | a-0/+1 | R | 新增 assert 1 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 40 | `tests/test_audience_translation_1838.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 41 | `tests/test_audience_travel_gating_670.py` | M | a-12/+0 | W | 净删 assert 12（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 42 | `tests/test_audience_undo_506.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 43 | `tests/test_authority_ledger_611.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 44 | `tests/test_bandit_power_model_190.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 45 | `tests/test_breach_plea_623.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 46 | `tests/test_centrifuge_ledger_690.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 47 | `tests/test_character_knowledge_489.py` | M | a-5/+5 | R | 断言重组 -5/+5（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 48 | `tests/test_chat_stream_failpaths_393.py` | M | a-5/+1 | R | 断言重组 -5/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 49 | `tests/test_cli_backend.py` | M | a-43/+17 | C | 入口/合并路径重构断言重组 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 50 | `tests/test_cli_entry_1902.py` | A | FILE_ADD | A | 1902 CLI 入口契约新案 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 51 | `tests/test_cli_model_choices.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 52 | `tests/test_cli_play_turn.py` | M | a-16/+17 | R | 断言重组 -16/+17（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 53 | `tests/test_cli_runner_error_typed_1299.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 54 | `tests/test_cli_transport_1465.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 55 | `tests/test_close_issues_section_rejections.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 56 | `tests/test_commitment_backlash_626.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 57 | `tests/test_commitment_display_348.py` | M | ROUND | W | 清退 _ints 数字集合同整类 display 盯文；保留 timed_bar/progress 结构化案 |
| 58 | `tests/test_court_break_player_lock_1727.py` | M | a-1/+6 | R | 断言重组 -1/+6（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 59 | `tests/test_court_layout_1290.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 60 | `tests/test_covert_levy_651.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 61 | `tests/test_credit_events_628.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 62 | `tests/test_db_broad_except_surface.py` | M | FINAL | W | 提交前自验：去 `_capture_tlog`/`assert msgs`（D5-A 诊断信号）；保留损坏 JSON 回退真实结果案 |
| 63 | `tests/test_decision_event_binding_389.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 64 | `tests/test_declaration_dispatch_1835.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 65 | `tests/test_decree_commitment_creation_136.py` | M | a-23/+1 | R | 断言重组 -23/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 66 | `tests/test_decree_commitment_schema_136.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 67 | `tests/test_decree_commitment_settlement_229.py` | M | a-6/+1 | R | 断言重组 -6/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 68 | `tests/test_decree_dossiers_571.py` | M | ROUND | H | 删 test_final_decree_edit_path_removed_no_bypass：只建草稿自证、无旁路、失效重复 |
| 69 | `tests/test_decree_forecast_1861.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 70 | `tests/test_deepseek_thinking_disable_1797.py` | M | a-6/+3 | R | 改走 _dump_value 序列化入口携带原始 reasoning/usage/finish; 非锁 dump 模板 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 71 | `tests/test_deformation_dual_rail_622.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 72 | `tests/test_distance_matrix.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 73 | `tests/test_dossier_endorsements_612.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 74 | `tests/test_dossier_links_559.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 75 | `tests/test_dossier_reported_progress_619.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 76 | `tests/test_draft_admission_resubmit_1769.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 77 | `tests/test_due_review_621.py` | M | a-6/+1 | R | prepare_scene_materials 真入口+origin/criterion 实际输入; wait jobs; 删 helper/extractor hasattr 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 78 | `tests/test_economy_section_rejections.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 79 | `tests/test_effect_origin_558.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 80 | `tests/test_empire_modifier_income_only_341.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 81 | `tests/test_enrich_list_guards.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 82 | `tests/test_enter_settlement_period_1235.py` | M | a-10/+5 | R | 断言重组 -10/+5（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 83 | `tests/test_env_isolation.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 84 | `tests/test_error_pack.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 85 | `tests/test_event_chain_cascade.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 86 | `tests/test_event_trigger_gate.py` | M | a-37/+0 | W | reason/summary 中文模板大删; 触发/落库行为保留 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 87 | `tests/test_execution_joint_liability_565.py` | M | a-8/+1 | R | 断言重组 -8/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 88 | `tests/test_execution_pressure_654.py` | M | a-12/+0 | W | 净删 assert 12（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 89 | `tests/test_execution_tenure_613.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 90 | `tests/test_executor_routing_721.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 91 | `tests/test_faction_brew_637.py` | M | a-14/+0 | W | 净删 assert 14（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 92 | `tests/test_faction_class_section_rejections.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 93 | `tests/test_faction_denunciation_627.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 94 | `tests/test_faction_leverage_9.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 95 | `tests/test_family_tail_615.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 96 | `tests/test_family_tail_642.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 97 | `tests/test_family_tail_restore_570.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 98 | `tests/test_featured_dossiers_494.py` | M | a-11/+7 | W | 档料标题/键名盯文→dossier 非空且进入 context 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 99 | `tests/test_fiscal_beyond_intent_1260.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 100 | `tests/test_fiscal_levy_effect.py` | M | FINAL | W | 提交前自验：删四处死 msgs→静默换形；保留隔离行为断言；incomplete 案 HEAD 原 silent 仍在 |
| 101 | `tests/test_fiscal_substrate_bridge.py` | M | ROUND | W | 去 turn_army_summary 标签嵌入/机器键缺席盯文；保留 army_logs 结构化；tlog 条数案已删 |
| 102 | `tests/test_fiscal_tick.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 103 | `tests/test_gazette_author_1862.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 104 | `tests/test_grant_reconciliation_567.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 105 | `tests/test_highlight_judge_544.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 106 | `tests/test_history_decree_text_1843_reopen.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 107 | `tests/test_identity_seed_488.py` | M | ROUND | R | 去「95」数字盯文；保留 character_context 机器字段隔离闸 |
| 108 | `tests/test_impeachment_surge_655.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 109 | `tests/test_initiative_resolve_pairing.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 110 | `tests/test_issue_decree_token_1277.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 111 | `tests/test_issue_entities.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 112 | `tests/test_junxin_alias_loyalty_313.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 113 | `tests/test_junxin_monthly_tick_314.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 114 | `tests/test_llm_channel_config.py` | M | a-22/+0 | H | 内部配置形状/重复证明清退 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 115 | `tests/test_llm_key_helpers.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 116 | `tests/test_loyalty_soft_adjust_clamp_320.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 117 | `tests/test_manual_directive_institution_normalize_1279.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 118 | `tests/test_manual_directive_locality_1685.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 119 | `tests/test_material_directory_1830.py` | M | a-8/+0 | W | 净删 assert 8（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 120 | `tests/test_mechanical_tail_1845.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 121 | `tests/test_memorial_inbox_1726.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 122 | `tests/test_menu_continue_stream_1195.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 123 | `tests/test_menu_lifecycle_drain_396.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 124 | `tests/test_mindreading_491.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 125 | `tests/test_minister_chat_timeout.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 126 | `tests/test_month_call_recovery_1846.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 127 | `tests/test_month_chain_1843.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 128 | `tests/test_month_chain_1847.py` | M | a-5/+5 | R | 断言重组 -5/+5（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 129 | `tests/test_month_loop_tracer_1468.py` | M | a-3/+2 | R | 断言重组 -3/+2（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 130 | `tests/test_month_open_snapshot_1234.py` | M | a-2/+1 | R | 断言重组 -2/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 131 | `tests/test_month_translate_1840.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 132 | `tests/test_mutiny_actual_residence_659.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 133 | `tests/test_mutiny_latch_315.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 134 | `tests/test_mutiny_noop_whitelist_319.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 135 | `tests/test_mutiny_progression_316.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 136 | `tests/test_mutiny_redemption_317.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 137 | `tests/test_mutiny_third_strike_318.py` | M | a-7/+0 | W | 净删 assert 7（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 138 | `tests/test_named_characters_seed_484.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 139 | `tests/test_new_game_dependency_mismatch_1721.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 140 | `tests/test_new_game_smoke.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 141 | `tests/test_new_game_write_path_1749.py` | M | a-3/+6 | C | 改走玩家召对真写入口+stage_draft 数据准备 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 142 | `tests/test_new_issues_section_rejections.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 143 | `tests/test_no_edict_full_settlement_1274.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 144 | `tests/test_office_inference.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 145 | `tests/test_office_rank_562.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 146 | `tests/test_on_scene_immediate_write_1839.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 147 | `tests/test_opening_gazette_delete_1356.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 148 | `tests/test_override_breach_costs_564.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 149 | `tests/test_p4_guard_new_surfaces_547.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 150 | `tests/test_pay_order_override_653.py` | M | a-8/+0 | W | 净删 assert 8（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 151 | `tests/test_pay_order_override_extraction_653.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 152 | `tests/test_person_archive_contract_index.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 153 | `tests/test_person_archive_schema.py` | M | a-15/+0 | W | 净删 assert 15（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 154 | `tests/test_person_delta_adapter.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 155 | `tests/test_person_transit_write_667.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 156 | `tests/test_pihong_dossier_1490.py` | M | a-14/+3 | R | label/hint==server_option; note==lying.note; wait_idle; 删 match/批红句 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 157 | `tests/test_player_army_projection_321.py` | M | ROUND | R | 保留：sit 源字段嵌入 report/materials=实际模型调用输入来源（非 formatter 自证） |
| 158 | `tests/test_player_payload_1022.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 159 | `tests/test_population_transfers_649.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 160 | `tests/test_population_transfers_662.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 161 | `tests/test_population_unit_648.py` | M | ROUND | W | 删 sub-wan label 嵌入与旧档「N万人」盯文；保留 DB 刻度/载荷 ABI 案 |
| 162 | `tests/test_power_section_rejections.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 163 | `tests/test_pre_settle_transaction.py` | M | a-8/+0 | H | inspect.getsource 内部缺席证明 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 164 | `tests/test_promulgation_judge_561.py` | M | a-9/+0 | W | 净删 assert 9（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 165 | `tests/test_promulgation_seam_560.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 166 | `tests/test_public_character_place_1683.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 167 | `tests/test_public_sayings_1829.py` | M | a-1/+1 | R | 断言重组 -1/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 168 | `tests/test_qa_1281_issue_audience_case_facts.py` | M | a-0/+0 | W | raises 去 match 盯文; 行为 raises 仍在 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 169 | `tests/test_qa_a3_seed_data.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 170 | `tests/test_qa_b3_409_ux.py` | M | a-13/+1 | R | 断言重组 -13/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 171 | `tests/test_qa_c2_phase_settlement_mask_1374.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 172 | `tests/test_qa_c2_settlement_display_lifecycle_1343.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 173 | `tests/test_qa_c3_secret_order_path_1357_1376.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 174 | `tests/test_qa_d1_decree_normalize_1274.py` | M | ROUND | H | 注册表/常量盯文已删；保留 DEFAULT_TIME_OF_DAY 与 people 过滤 |
| 175 | `tests/test_qa_e1_numeric_presentation.py` | M | a-21/+1 | R | 断言重组 -21/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 176 | `tests/test_qa_h1_seed_data.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 177 | `tests/test_qa_s2_copy_prompts_1356_1402.py` | M | a-11/+0 | W | 净删 assert 11（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 178 | `tests/test_qa_t1_extraction_dual_source_1353.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 179 | `tests/test_qa_u2_liaodong_buildings.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 180 | `tests/test_qa_u3_map_nodes_1401.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 181 | `tests/test_recommendation_batch_snapshot_1583.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 182 | `tests/test_recommendation_edges_635.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 183 | `tests/test_recommendations.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 184 | `tests/test_refugee_loop_652.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 185 | `tests/test_region_cannon_delta.py` | M | ROUND | W | 删 REGION_FIELD_LABELS==城防炮 专用 formatter 常量证明；保留 clamp 落库 |
| 186 | `tests/test_region_citydefense.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 187 | `tests/test_region_citydefense_display.py` | D | ROUND | D | 整文件删除：锁「城防炮N门」/city_defense_description 嵌入=formatter 证明；不变形再造 |
| 188 | `tests/test_reign_period_label.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 189 | `tests/test_rejection_wiring.py` | M | a-4/+0 | W | 净删 assert 4（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 190 | `tests/test_relation_brew_636.py` | M | a-22/+3 | R | 断言重组 -22/+3（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 191 | `tests/test_relation_capture_633.py` | M | a-19/+0 | R | 坏端点名→reason 本轮以变量补回; 其余拒句 match 盯文维持删; 零边行为保留 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 192 | `tests/test_relation_read_640.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 193 | `tests/test_relation_seed_638.py` | M | a-19/+1 | R | 断言重组 -19/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 194 | `tests/test_relation_store_632.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 195 | `tests/test_release_bundle_assets.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 196 | `tests/test_rescript_choices_563.py` | M | a-4/+1 | R | 断言重组 -4/+1（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 197 | `tests/test_rescript_draft_656.py` | M | a-23/+1 | R | reason==str(unavailable); title-in-tlog 本轮补回; 删 prompt/SQL/match 盯文 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 198 | `tests/test_rescript_heal_isolation_1801.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 199 | `tests/test_rescript_option_field_heal_1746.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 200 | `tests/test_run_agent_text_transport_1465.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 201 | `tests/test_runtime_llm_config.py` | M | a-18/+7 | R | 断言重组 -18/+7（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 202 | `tests/test_scene_llm_1836.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 203 | `tests/test_secret_dossier_participants_1252.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 204 | `tests/test_secret_order_isolation_883.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 205 | `tests/test_secret_order_monthly_progress_566.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 206 | `tests/test_secret_order_payoff_1504.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 207 | `tests/test_secret_order_section_rejections.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 208 | `tests/test_secret_order_update.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 209 | `tests/test_section4_rejections.py` | M | a-5/+0 | W | 净删 assert 5（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 210 | `tests/test_section_fiscal_rejections.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 211 | `tests/test_session_write_queue_1353.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 212 | `tests/test_settle_core.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 213 | `tests/test_settlement_write_guard_393.py` | M | a-6/+0 | W | 净删 assert 6（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 214 | `tests/test_shared_resource_order_1844.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 215 | `tests/test_six_sciences_seed_608.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 216 | `tests/test_start_sh_deps_1721.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 217 | `tests/test_state_reload.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 218 | `tests/test_structured_decree_contract_1624.py` | M | a-2/+0 | W | 净删 assert 2（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 219 | `tests/test_style_temperament_641.py` | M | a-3/+2 | R | payload_summary==item[reason] 来源相等; 删 or 固定句兜底 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 220 | `tests/test_supervision_625.py` | M | a-10/+0 | W | 净删 assert 10（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 221 | `tests/test_surcharge_causal_chain_650.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 222 | `tests/test_textual_facts_1828.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 223 | `tests/test_transaction_boundary.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 224 | `tests/test_transit_aging_346.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 225 | `tests/test_transit_countdown_668.py` | M | a-1/+0 | W | 净删 assert 1（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 226 | `tests/test_urge_lever_624.py` | M | a-0/+0 | C | 断言行未变：调用/夹具/wait/helper 重接 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 227 | `tests/test_value_matrix_691.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 228 | `tests/test_verify_llm_clocks_884.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 229 | `tests/test_web_audience_night_498.py` | M | ROUND | R | 改真实 HTTP 404/405；删 registered_paths |
| 230 | `tests/test_web_budget_payload.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 231 | `tests/test_web_chat_serialization_393.py` | M | a-4/+2 | R | 断言重组 -4/+2（保留/改写行为或来源面） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 232 | `tests/test_web_court_visibility.py` | M | a-7/+2 | R | choose_minister 真实选择→Character/None; 删 print 名册与拒因中文子串 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 233 | `tests/test_web_entry_1902.py` | M | ROUND | H | 注册表退役证明已删；保留菜单删档共享校验 |
| 234 | `tests/test_web_issue_condition_display.py` | D | ROUND | D | 整文件删除：text!=raw + 人物子串弱断言无结构化契约价值；专用夹具随删 |
| 235 | `tests/test_web_llm_runtime_config.py` | M | a-3/+0 | W | 净删 assert 3（拒句/match/呈现/内部；行为断言复核仍在） 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 236 | `tests/test_world_materials_1834.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 237 | `tests/test_yuan_arrival_185.py` | - | UNTOUCHED | C | 0ca77fecc→HEAD 未触及；实读无 D5-A/B 清退命中 |
| 238 | `tests/wait_utils.py` | - | SUPPORT | C | 测试支撑/夹具/说明，无断言契约；非 D5 清退对象 |
| 239 | `tests/web_audience_test_doubles.py` | M | a-0/+0 | C | 双端替身/调用面调整 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 240 | `web/src/appDurableWiring.test.tsx` | M | e-95/+1 | W | 拟诏台/局部文案大删; 保留 alert==detail.message 等来源; 空疏改 empty-note 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 241 | `web/src/buildResources.test.ts` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 242 | `web/src/chatFailures.test.ts` | M | e-4/+0 | W | 赴京/SUMMON 缺席盯文 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 243 | `web/src/cliRunners.test.ts` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 244 | `web/src/components/cliRunnerDropdown.consistency.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 245 | `web/src/components/decisionModal.test.tsx` | M | e-4/+0 | W | hint 固定提示文案 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 246 | `web/src/components/drawers.test.tsx` | M | e-21/+0 | W | 抽屉数值/欠饷呈现盯文 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 247 | `web/src/components/electronLayout.medium.test.tsx` | M | e-4/+2 | C | 布局不相交度量键更名 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 248 | `web/src/components/gameMenu.test.tsx` | M | e-1/+0 | W | runner 列表含 grok 盯文 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 249 | `web/src/components/map.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 250 | `web/src/components/menuPage.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 251 | `web/src/components/modals.test.tsx` | M | e-8/+3 | W | 固定报警句→有文案; 删按钮含「删」 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 252 | `web/src/components/settlementFaces.test.tsx` | M | e-4/+0 | W | 邸报/起居注固定标签 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 253 | `web/src/components/settlementGazettePanel.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 254 | `web/src/components/situation.test.tsx` | M | ROUND | W | 已去 progress/progress_band textContent 黑名单；保留奏疏正文来源相等 |
| 255 | `web/src/decisionRouting.test.tsx` | M | e-1/+0 | W | error 不含「重新拉取」 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 256 | `web/src/escClose.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 257 | `web/src/mindreading.test.ts` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 258 | `web/src/mindreadingDelivery.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 259 | `web/src/ministerScrollLens.test.ts` | M | e-4/+0 | W | 密令/神色等缺席盯文 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 260 | `web/src/reasoningSupport.test.ts` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 261 | `web/src/settleStream.test.ts` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 262 | `web/src/settlementPresentation.test.ts` | M | e-23/+0 | W | 年月/王承恩条固定句与 formatter 证明 〔旧表沿用；本轮复读无新增 D5 清退〕 |
| 263 | `web/src/staleGuard.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 264 | `web/src/useDurableProjection.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |
| 265 | `web/src/useSettlementFlow.test.tsx` | - | WEB_FULL | X | 本轮全仓纳入；textContent 多为 UI 铬字/按钮/来源透传或 P4 负向闸，见回执 Web 保留表；无机器字段黑名单残留 |

## 计数

- `R`: 37
- `W`: 84
- `H`: 7
- `C`: 116
- `A`: 5
- `D`: 2
- `X`: 14
- **合计成员**: 265

## 本轮（工作树未提交）点名清退摘要

详见 `d5-current-receipt.md`。关键纠正：禁止把「helper 源标签在呈现文」泛化成合法例外；formatter 产出嵌入与 `_ints`/锁措辞/弱 text!=raw 一律清退；禁止以「可观测」洗白 tlog/`assert msgs` 内部信号证明。
