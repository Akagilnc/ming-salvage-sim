# J6-r4 机械成员表：bb448254c..HEAD 新增/改写断言

基数提交：`bb448254c`；成员含修理 diff 新增/改写断言快照 + 本轮 FIX 新增行。
成员数：87

| # | file:line | disposition | post_fix | assert | rationale |
|---|---|---|---|---|---|
| 1 | `tests/test_advances_section_rejections.py:108` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 2 | `tests/test_audience_night_498.py:511` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 3 | `tests/test_audience_restore_505.py:811` | KEEP_STREAM_EVENT | PRESENT | `assert any(ev.get("type") == "accepted" for ev in events)` | chat_stream accepted 事件类型；替 OperationalError 措辞锁 |
| 4 | `tests/test_audience_translate_1837.py:257` | KEEP_CUTOFF_ORDER | PRESENT | `assert int(later) > int(source)` | 源轮/后轮 id 序结构化前置 |
| 5 | `tests/test_audience_translate_1837.py:319` | KEEP_CUTOFF_MARKER | PRESENT | `assert LEAK_MARKER["body"] not in bodies` | 源轮截止失效时结构化泄漏标记负向 |
| 6 | `tests/test_audience_travel_gating_670.py:597` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 7 | `tests/test_audience_travel_gating_670.py:791` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 8 | `tests/test_audience_travel_gating_670.py:1018` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 9 | `tests/test_cli_play_turn.py:242` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 10 | `tests/test_cli_play_turn.py:325` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 11 | `tests/test_cli_play_turn.py:371` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 12 | `tests/test_cli_runner_error_typed_1299.py:70` | KEEP_PASSTHROUGH | PRESENT | `assert captured["text"] == "臣遵旨，边事容臣细奏。"` | fixture 回传全文相等=CLI 文本透传契约，非生产措辞锁 |
| 13 | `tests/test_close_issues_section_rejections.py:165` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 14 | `tests/test_decree_commitment_settlement_229.py:562` | FIX_DELETE | REMOVED_BY_FIX | `assert int(progress.get("paid_total") or 0) >= 0` | 恒真占位（>=0）；允许仅保留 months_elapsed==1 |
| 15 | `tests/test_decree_commitment_settlement_229.py:563` | FIX_DELETE | REMOVED_BY_FIX | `assert "remaining_arrears" in progress` | 键存在占位；无独立准确期望 |
| 16 | `tests/test_decree_commitment_settlement_229.py:1448` | KEEP_NARRATIVE_PASSTHROUGH | PRESENT | `assert row["resolution_summary"] == "皇帝已复试孙承宗，此承诺已由圣裁处理。"` | resolution_summary 承接测试输入 narrative 原文无损 |
| 17 | `tests/test_decree_dossiers_571.py:1328` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 18 | `tests/test_due_review_621.py:744` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 19 | `tests/test_empire_modifier_income_only_341.py:34` | KEEP_INDEPENDENT_CONST | PRESENT | `assert net_pct == -12, f"前置条件：开局国库帝国修正应为 -12（实为 {net_pct}）"` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 20 | `tests/test_empire_modifier_income_only_341.py:40` | KEEP_INDEPENDENT_CONST | PRESENT | `assert actual == expected_income, (` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 21 | `tests/test_event_chain_cascade.py:244` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 22 | `tests/test_event_trigger_gate.py:2167` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 23 | `tests/test_executor_routing_721.py:360` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 24 | `tests/test_executor_routing_721.py:393` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 25 | `tests/test_faction_brew_637.py:292` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(sqlite3.OperationalError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 26 | `tests/test_faction_brew_637.py:305` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(sqlite3.OperationalError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 27 | `tests/test_fiscal_substrate_bridge.py:1317` | KEEP_INDEPENDENT_CONST | PRESENT | `assert net_pct == -12` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 28 | `tests/test_fiscal_substrate_bridge.py:1542` | FIX_REWRITE | REWRITTEN_BY_FIX | `assert len(colliding) >= 2  # hub 投影行 + 用户 fiscal_item 行` | 软下界占位 → len==2 准确期望 |
| 29 | `tests/test_fiscal_substrate_bridge.py:1549` | FIX_REWRITE | REWRITTEN_BY_FIX | `assert expected is not None, f"本案只覆盖开局 -12% 或净 0（实为 {net_pct}）"` | 分支占位 → 钉 net_pct==0 + expected=7（本案夹具） |
| 30 | `tests/test_fiscal_substrate_bridge.py:2030` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 31 | `tests/test_fiscal_substrate_bridge.py:4864` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 32 | `tests/test_llm_channel_config.py:474` | KEEP_ROUTE_KEY | PRESENT | `assert "model" in captured and "prompt" in captured` | smoke 触发：prompt/model 键存在；不锁正文/非空 |
| 33 | `tests/test_llm_channel_config.py:475` | FIX_DELETE | REMOVED_BY_FIX | `assert captured["prompt"]  # smoke 已触发` | prompt 非空占位；路由已由 model/CliChat 键覆盖 |
| 34 | `tests/test_llm_channel_config.py:503` | KEEP_ROUTE_CONFIG | PRESENT | `assert seen.get("config") is cfg` | CLI/legacy 渠道路由：config 对象与 verify tag |
| 35 | `tests/test_llm_channel_config.py:504` | KEEP_ROUTE_CONFIG | PRESENT | `assert seen.get("tag") == "verify"` | CLI/legacy 渠道路由：config 对象与 verify tag |
| 36 | `tests/test_llm_channel_config.py:505` | FIX_DELETE | REMOVED_BY_FIX | `assert seen.get("prompt")` | prompt 非空占位；路由已由 config/tag 覆盖 |
| 37 | `tests/test_llm_channel_config.py:544` | KEEP_ROUTE_CONFIG | PRESENT | `assert seen.get("tag") == "verify"` | CLI/legacy 渠道路由：config 对象与 verify tag |
| 38 | `tests/test_llm_channel_config.py:545` | FIX_DELETE | REMOVED_BY_FIX | `assert seen.get("prompt")` | prompt 非空占位；路由已由 config/tag 覆盖 |
| 39 | `tests/test_material_directory_1830.py:283` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 40 | `tests/test_month_chain_1843.py:401` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 41 | `tests/test_month_chain_1843.py:479` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 42 | `tests/test_month_chain_1843.py:713` | KEEP_INDEPENDENT_CONST | PRESENT | `assert ordered == 100` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 43 | `tests/test_month_chain_1843.py:715` | KEEP_INDEPENDENT_CONST | PRESENT | `assert recon["arrived_amount"] == expected_arrived` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 44 | `tests/test_month_chain_1843.py:716` | KEEP_INDEPENDENT_CONST | PRESENT | `assert recon["loss_amount"] == ordered - expected_arrived` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 45 | `tests/test_month_chain_1847.py:1801` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 46 | `tests/test_month_chain_1847.py:2256` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 47 | `tests/test_new_game_write_path_1749.py:465` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 48 | `tests/test_new_game_write_path_1749.py:500` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 49 | `tests/test_new_issues_section_rejections.py:311` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 50 | `tests/test_new_issues_section_rejections.py:354` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 51 | `tests/test_new_issues_section_rejections.py:373` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 52 | `tests/test_override_breach_costs_564.py:384` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 53 | `tests/test_override_breach_costs_564.py:453` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 54 | `tests/test_pihong_dossier_1490.py:830` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 55 | `tests/test_power_section_rejections.py:136` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(KeyError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 56 | `tests/test_pre_settle_transaction.py:103` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 57 | `tests/test_pre_settle_transaction.py:127` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 58 | `tests/test_pre_settle_transaction.py:154` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 59 | `tests/test_pre_settle_transaction.py:432` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 60 | `tests/test_refugee_loop_652.py:494` | KEEP_INDEPENDENT_CONST | PRESENT | `assert after == before - expected_transfer, (` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 61 | `tests/test_refugee_loop_652.py:588` | KEEP_INDEPENDENT_CONST | PRESENT | `assert arrived == expected_arrived, (` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 62 | `tests/test_refugee_loop_652.py:591` | KEEP_INDEPENDENT_CONST | PRESENT | `assert _pop(loaded, "流民", "shaanxi") == displaced_before - expected_transfer` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 63 | `tests/test_refugee_loop_652.py:592` | KEEP_INDEPENDENT_CONST | PRESENT | `assert _pop(loaded, "农民", "shaanxi") == farmer_before + expected_transfer` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 64 | `tests/test_rejection_wiring.py:94` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 65 | `tests/test_rejection_wiring.py:137` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 66 | `tests/test_relation_brew_636.py:465` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(sqlite3.OperationalError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 67 | `tests/test_relation_brew_636.py:488` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(sqlite3.OperationalError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 68 | `tests/test_relation_brew_636.py:507` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(sqlite3.OperationalError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 69 | `tests/test_relation_brew_636.py:522` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(KeyError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 70 | `tests/test_relation_brew_636.py:542` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(ValueError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 71 | `tests/test_relation_seed_638.py:278` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 72 | `tests/test_relation_seed_638.py:300` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(ValueError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 73 | `tests/test_rescript_draft_656.py:753` | FIX_DELETE | REMOVED_BY_FIX | `assert any("options_len=0" in msg for msg in logs)` | 日志字符串 token 锁；非结构化契约；保留 drafts+assert logs |
| 74 | `tests/test_rescript_draft_656.py:766` | FIX_DELETE | REMOVED_BY_FIX | `assert any("options_type=str" in msg and "options_len=n/a" in msg for msg in logs)` | 日志字符串 token 锁；非结构化契约；保留 drafts+assert logs |
| 75 | `tests/test_rescript_draft_656.py:838` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 76 | `tests/test_secret_order_monthly_progress_566.py:366` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 77 | `tests/test_session_write_queue_1353.py:525` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(AssertionError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 78 | `tests/test_session_write_queue_1353.py:536` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 79 | `tests/test_state_reload.py:125` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 80 | `tests/test_state_reload.py:166` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 81 | `tests/test_state_reload.py:258` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 82 | `tests/test_state_reload.py:301` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError):` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 83 | `tests/test_state_reload.py:345` | KEEP_RAISES_TYPE | PRESENT | `with pytest.raises(RuntimeError) as ei:` | 删 match= 措辞锁后保留异常类型；负向/回滚契约仍有效 |
| 84 | `web/src/useSettlementFlow.test.tsx:305` | KEEP_ERROR_PACK_PATH | PRESENT | `expect(alert?.textContent).toContain("/tmp/tail-error");` | UI 呈现 mechanical_tail_failure.error_pack_path 结构化字段 |
| 85 | `web/src/useSettlementFlow.test.tsx:309` | KEEP_POLL_STOP | PRESENT | `expect(vi.getTimerCount()).toBe(0);` | 失败后轮询停止（timer=0） |
| 86 | `tests/test_fiscal_substrate_bridge.py:1542` | KEEP_INDEPENDENT_CONST | NEW_FROM_FIX | `assert len(colliding) == 2  # hub 投影行 + 用户 fiscal_item 行` | 独立常量/准确数值期望；替方向比较或实现 oracle |
| 87 | `tests/test_fiscal_substrate_bridge.py:1548` | KEEP_INDEPENDENT_CONST | NEW_FROM_FIX | `assert net_pct == 0` | 独立常量/准确数值期望；替方向比较或实现 oracle |

## 计数
```
KEEP_RAISES_TYPE: 55
KEEP_INDEPENDENT_CONST: 12
FIX_DELETE: 7
KEEP_ROUTE_CONFIG: 3
FIX_REWRITE: 2
KEEP_STREAM_EVENT: 1
KEEP_CUTOFF_ORDER: 1
KEEP_CUTOFF_MARKER: 1
KEEP_PASSTHROUGH: 1
KEEP_NARRATIVE_PASSTHROUGH: 1
KEEP_ROUTE_KEY: 1
KEEP_ERROR_PACK_PATH: 1
KEEP_POLL_STOP: 1
```