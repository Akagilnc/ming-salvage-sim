# #1897 T1 apply 回执（整类补完）

- **角色**：修内司（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **新判词真源**：`artifacts/1897-t1-review-input.json`（全文已读）
- **范围**：T1 整类——`21651f2d0`→工作树全部被改写 Python／Web 测试逐案处置。**K1/K2 不动生产。**
- **禁止项**：无 amend／stash／rewrite／push／PR；七变量 BIN=/usr/bin/false；不全量；不真模型；不改法；不改宿主席位。

**不宣称 merge 或关票。**

---

## 本轮纠正（相对 bc7426bba／467625a91）

1. 复扫全 diff 谓词命中，不再只修 494／641 样本。
2. `test_founding_summary_survives_consecutive_brews`（改名伪装）**整案删除**，不保水位壳。
3. `test_scene_llm_1836`：删 `len(readings)>=2` 与 readings 收集；admission origin 结构保留；削 `assert result.answer` 真值壳。
4. brew 并行／prepare：裸 `is not None` 改为 `dimension`＋`last_event_id`；无事月删 `is not None` 填料。
5. Web：删 `detail modal renders supplied bar meanings`（恒 2 head）；删 `#1280` markdown 壳；`useSettlementFlow` 删落地后 `summary() notNull` 充数。
6. **494 静态身份闸保留**；**641 style before/after 不恢复**。
7. 成员表禁止「等」笼统；完整 168 行见下（副本 `artifacts/1897-t1-member-table-full.md`）。

---

## 判词要点

T1：要么最短结构化断言（含静态资产身份分桶闸），要么删失去独立契约的壳；不得键在／非空／len／strip／before-after 散文充数；闸类负向不得误删；不恢复正文逐字锁；不得改名伪装；节点存在可证布局、不能证正文交付／身份隔离选择。

---

## 枚举命令（精确，已实跑）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5

# 1) 谓词新增行起点（非白名单）
git diff 21651f2d0 -U0 -- tests web \
  | rg -n '^\+' \
  | rg -i ' in .*keys|is not None|isinstance|\.strip\(\)|len\(.*\) *[<>]|toBeGreaterThan|not\.toBeNull|toBeTruthy|toHaveLength|querySelector|fetchone\(\) is not None'

# 2) 改写／删除案全集（函数体 diff）
# 产出：artifacts/1897-t1-changed-cases.txt
# 候选：artifacts/1897-t1-pred-candidates.txt
# 处置表：artifacts/1897-t1-member-table-full.md
```

实跑统计：改写文件 44；函数体变更案 167（改写 141／整案删除 21／相对 base 更名替案 5）+ 中间改名壳 `test_founding_summary_survives_consecutive_brews` 1 = **表内 168 行**。

---

## 完整成员表

共 168 行（含中间改名壳 1 行）。


## `tests/test_audience_continuous_507.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_qianqing_continuous_night_skeleton_runs` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `test_scene_recap_excludes_dialogue_before_person_entered` | 合法保留 | 负向闸 |
| `test_scene_recap_quotes_public_dialogue_within_presence_interval` | 合法保留 | 负向闸 |

## `tests/test_audience_restore_505.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_failed_retry_rolls_back_side_effects_and_keeps_question` | 合法保留 | 结构化字段 |
| `test_post_reply_failure_resumes_close_without_regenerating_reply` | 合法保留 | 结构化字段 |
| `test_pure_audience_zero_ledger_turn_survives_reopen` | 合法保留 | 结构化字段 |
| `test_reopen_reconcile_unblocks_and_keeps_question` | 合法保留 | 结构化字段 |
| `test_retry_regenerates_reply_without_duplicate_question` | 合法保留 | 结构化字段 |

## `tests/test_audience_scroll_539.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_live_and_closed_night_share_the_real_http_contract` | 合法保留 | 结构化字段 |
| `test_personal_projection_only_reads_the_current_open_night` | 合法保留 | 结构化字段 |
| `test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats` | 合法保留 | 结构化字段 |
| `test_scroll_contract_merges_both_stores_with_container_and_coda` | 合法保留 | 结构化字段 |
| `test_translation_segments_replace_neutral_reply_in_real_scroll` | 合法保留 | 结构化字段 |

## `tests/test_audience_translation_1838.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_edge_event_and_public_saying_attach_affair` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_authority_ledger_611.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_production_path_grant_restore_revoke_impression_tracer` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_candidate_supply_1893.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_eligible_candidate_event_reaches_world_supply` | 合法保留 | 负向闸 |
| `test_translate_request_carries_current_candidate_facts` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_cli_backend.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_clichat_invoke_builds_prompt_and_completion_structure` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `test_extract_secret_order_preserves_long_title_without_formal_cap` | 整案删除 | title 正文保真锁；无独立非散文契约 |
| `test_extract_secret_order_returns_assignee_without_title_prose_lock` | 合法保留（替删） | 替原 long_title 正文锁：只验 assignee 结构化字段，不锁 title 散文 |

## `tests/test_cli_play_turn.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_terminal_minister_chat_accepts_retry_reply_command` | 合法保留 | 负向闸；结构化字段 |

## `tests/test_credit_events_628.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_disposition_scapegoat_cover_prosecute_on_transformed` | 合法保留 | 负向闸；结构化字段；拒收／失败形态 |
| `test_fulfill_back_and_urge_three_decisions` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_idempotent_narrative_restore_write_only` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_decision_event_binding_389.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_ambiguous_title_remains_unbound` | 整案删除 | 标题猜绑路径已退役（K2）；负向改由 stays_unbound_without_title_guess 承接 |
| `test_missing_event_id_binds_from_unique_title` | 整案删除 | 标题补绑正向已退役（K2） |
| `test_missing_event_id_stays_unbound_without_title_guess` | 合法保留（替删） | 替标题猜绑负向：缺 event_id→unbound；`event_id not in out[0]` 结构闸 |
| `test_offsnapshot_echoed_event_id_does_not_win_over_snapshot` | 整案删除 | 旧标题胜出语义退役；改 unbound 结构闸 |
| `test_offsnapshot_echoed_event_id_is_unbound` | 合法保留（替删） | 替旧 offsnapshot 标题胜出案：快照外 id 一律 unbound |
| `test_offsnapshot_id_with_no_title_match_is_unbound` | 整案删除 | 标题匹配路径退役 |
| `test_offsnapshot_id_with_unrelated_title_is_unbound` | 合法保留（替删） | 替旧 no_title_match 案：无标题猜绑路径 |
| `test_valid_echoed_event_id_is_trusted_unchanged` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_deepseek_thinking_disable_1797.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_dump_llm_messages_records_reasoning_usage_finish_reason` | 合法保留 | 负向闸 |

## `tests/test_draft_admission_resubmit_1769.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_draft_admission_exhaust_keeps_draft_and_advances` | 合法保留 | 负向闸；拒收／失败形态 |
| `test_draft_admission_resubmit_success_advances_month` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_execution_joint_liability_565.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_execution_note_merge_interface_and_restore` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_faction_brew_637.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_authority_revoke_edge_reaches_holder_faction_with_emperor_target` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_highlight_judge_544.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_chat_nonstream_folds_judge_within_timeout` | 合法保留（削 answer 正文） | done payload 取 minister_message_id 结构；高亮事件后置 |
| `test_chat_nonstream_timeout_returns_reply_without_highlights` | 合法保留（削 answer 正文） | done 存在 + 无有效 highlights 事件 |
| `test_chat_stream_done_before_highlights_and_degrade` | 合法保留（削 answer 正文） | 事件类型序 + highlights 不在流内 + 空高亮落库 |
| `test_chat_stream_slow_success_attaches_after_done` | 合法保留（削 reply 正文） | 事件序 done<highlights<end + highlights==[军务] 落库；len(seen_reply)==1 仅作调用次数 |

## `tests/test_month_call_recovery_1846.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_settlement_recovery_projects_month_call_failure` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_on_scene_immediate_write_1839.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_kill_lands_status_and_next_materials_show_it` | 合法保留 | 负向闸 |

## `tests/test_opening_gazette_delete_1356.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_new_game_t0_previous_summary_strictly_empty` | 合法保留 | 负向闸 |
| `test_old_save_exact_purge_keeps_real_with_phrase_counterexample` | 合法保留 | 负向闸 |

## `tests/test_pay_order_override_653.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_turn_region_summary_claim_audit_rows_do_not_consume_limit` | 整案删除 | 失去独立外部契约／影子消费限额证明 |

## `tests/test_qa_s2_copy_prompts_1356_1402.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_gazette_header_cross_year_december_report_under_january_state` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `test_gazette_header_uses_report_own_month_not_current_turn` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `test_require_active_minister_rejects_offstage_via_can_summon` | 合法保留（替删） | 替 reason 正文锁：经 can_summon 拒收离场大臣 |
| `test_require_active_minister_uses_can_summon_reason` | 整案删除 | reason 正文锁；改结构拒收案 |
| `test_state_payload_projects_previous_reign_period_label` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_qa_t1_extraction_dual_source_1353.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_dispatch_exception_after_persist_retains_reply_recovery` | 合法保留 | 结构化字段 |

## `tests/test_recommendation_edges_635.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_approved_recommendation_writes_both_edges_atomically` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_real_entry_persists_raw_reason_verbatim` | 整案删除 | reason 逐字锁无独立非散文契约 |
| `test_replay_same_event_with_changed_reason_stays_two_rows` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_relation_brew_636.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_batch_of_five_relations_all_enter_call_seam_concurrently` | 合法保留（削 is not None） | 五线程并发结构 + dimension/last_event_id 写入 |
| `test_brew_batch_runs_items_in_parallel_not_serialized` | 合法保留（削 is not None） | 并行线程数 + brewed 计数；摘要行改验 dimension/last_event_id，不再裸 is not None |
| `test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical` | 整案删除 | 32700 字节正文保真无独立可结构化契约 |
| `test_build_brew_input_projects_prior_event_fields` | 合法保留 | 负向闸；结构化字段；拒收／失败形态 |
| `test_duplicate_json_objects_rejected_not_first_object_picked` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_failed_month_degrades_to_pending_and_rebrews_next_month` | 合法保留 | 负向闸；结构化字段；拒收／失败形态 |
| `test_flip_brew_input_must_contain_new_edge_events` | 合法保留 | 负向闸；结构化字段；拒收／失败形态 |
| `test_founding_segment_survives_consecutive_brews_byte_identical` | 整案删除 | 奠基段逐字锁无独立可结构化契约；中间改名 test_founding_summary_survives_consecutive_brews 属伪装，本轮连改名壳一并删 |
| `test_historical_events_alone_do_not_select_in_later_month` | 合法保留 | 负向闸；结构化字段；拒收／失败形态 |
| `test_merge_founding_segment_append_only_and_dedup` | 整案删除 | merge_founding 正文拼装专属证明 |
| `test_merge_founding_segment_exact_old_entry_re_report_appended_verbatim` | 整案删除 | merge_founding 正文拼装专属证明 |
| `test_merge_founding_segment_never_infers_by_lines` | 整案删除 | merge_founding 正文拼装专属证明 |
| `test_merge_founding_segment_preserves_bytes_exactly` | 整案删除 | merge_founding 正文拼装专属证明 |
| `test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews` | 合法保留（削 is not None 填料） | selected==0 + calls==[] + last_event_id/dimension 水位不变 |
| `test_prepare_attaches_prior_events_only_via_history_seam` | 合法保留（削 is not None） | prior/new origin 互斥 + history 读缝；首月摘要改验 dimension/水位 |
| `test_provider_fault_becomes_typed_brew_failure` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_relation_read_640.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_dto_shape_summary_plus_recent_context_with_backref` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |
| `test_judge_face_reads_edges_invisible_to_role_view` | 合法保留 | 负向闸 |
| `test_load_relation_history_before_returns_full_stable_prior_stream` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_relation_seed_638.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_existing_save_is_never_touched_by_seed_import` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |
| `test_new_save_seed_founding_events_enter_founding_segment` | 合法保留 | 结构化字段 |
| `test_repeated_import_is_idempotent_no_double_write` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_reverse_chronological_seed_keeps_latest_event_readable` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_seed_replay_does_not_overwrite_later_brew_summary` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_seeded_pair_flows_into_month_end_brew_selection` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_relation_store_632.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_relation_edges_survive_restore` | 合法保留 | 结构化字段；拒收／失败形态 |

## `tests/test_scene_llm_1836.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_cli_selection_uses_scene_turn_as_admission_origin` | 合法保留（削 readings 壳） | 保留 admission origin：origin_chat_turn_id>0 + minister_message_id>0 + calls 序；删 len(readings)>=2 与 opening 正文壳 |
| `test_retire_via_scene_chat_closes_night_and_keeps_last_turn` | 合法保留（削 answer 真值壳） | court_break + 封夜 status=closed + 尾轮 id/minister_message_id 续存 |
| `test_scene_chat_one_call_returns_multi_person_script` | 合法保留（削正文） | 保留单次调用与输入身份；删 answer 正文等值 |
| `test_xuan_lands_enter_then_present_on_next_prepare` | 合法保留（削 answer 真值壳） | TAG_ENTER 账 + present_names + 材料子树；court_action=="" |

## `tests/test_secret_order_isolation_883.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_883_shared_archive_bypass_positive_and_negative` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `tests/test_six_sciences_seed_608.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_fresh_seed_contains_sourced_six_sciences_censors` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |

## `tests/test_structured_decree_contract_1624.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_combo_correction_preserves_first_draw_roster` | 合法保留 | 负向闸；拒收／失败形态 |

## `tests/test_style_temperament_641.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_apply_score_extraction_rejects_invalid_temperament` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_apply_score_extraction_writes_temperament_style_and_log` | 整案删除 | 正向 style 写入壳；不恢复 before/after |
| `test_character_context_with_db_reads_own_style_and_viewer_ledger` | 整案删除 | 所称消费者未调用 |
| `test_inertia_natural_resolve_applies_temperament_style` | 整案删除 | 正向 style 写入壳；不恢复 before/after 正文列比较 |
| `test_relation_edge_events_do_not_mutate_style` | 合法保留 | 拒收／失败形态 |
| `test_temperament_blank_style_rejected_keeps_prior` | 合法保留 | 结构化字段；拒收／失败形态 |
| `test_temperament_committed_style_survives_reload` | 整案删除 | reload style 专属壳；日志计数对 reload 恒真 |
| `test_temperament_does_not_write_relation_edges` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |
| `test_temperament_outer_tx_rollback_restores_db_and_runtime` | 整案删除 | reload/rollback style 专属壳 |

## `tests/test_surcharge_causal_chain_650.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_exact_levy_fact_stays_out_of_public_read_chain_and_free_report_enters_it` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |

## `web/src/appDurableWiring.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `#1276 邸报木牌重开 gazette；史册头起居注另入口解析近臣像` | 合法保留 | 负向闸；拒收／失败形态 |
| `#1620 settling recovery：重开后按持久恢复投影选入口` | 合法保留 | 负向闸；拒收／失败形态 |
| `#1726 非核账：奏疏模态呈真实奏疏正文，不借局势议题` | 合法保留 | 负向闸；拒收／失败形态 |
| `#1764 成案只读投影：state.cased_directives 以 phase=cased 留桌且无改删` | 合法保留 | 负向闸；焦点／忙态／回调 |
| `#1796 有草案点盖玺：拟诏台立即收起，核账期面，灰钮不可见` | 合法保留 | 负向闸；拒收／失败形态 |
| `#1852 写成即推进：本面邸报落位；朕知道了只关阅读；刷新不自动弹` | 合法保留 | 负向闸；拒收／失败形态 |
| `#1852 真实页面：服务端已推进但载入新月失败时邸报可读可关、旧月入口不可提交` | 合法保留 | 负向闸 |
| `accepted 后普通流中断重读持久问话与原位重试，不回填输入框` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `awaiting_decision + 合法 pending：DecisionModal 可点；刷新重挂后仍在` | 合法保留 | 负向闸；批红文书布局 |
| `gazette：仅有 last_attendant_message 时亦不自动弹；木牌可开空卷轴+递话` | 合法保留 | 负向闸 |
| `gazette：核账期上月邸报经木牌可读；正文=状态口 previous_summary（#1852 不自动弹）` | 合法保留（布局+纪年，不宣称正文等值） | 木牌开 dialog + masthead 纪年 + attendant 在 document 外 + 半程 list 负向；pre 槽非正文等值 |
| `只读组逐面可达且吃月初叠影；关闭组不可达且半程面不泄漏` | 合法保留 | 负向闸 |
| `密令召见从真实入口在同一殿上卷宣人，不再打开按大臣实时会话 (#1849)` | 合法保留 | 负向闸；结构化字段 |
| `月完后 settlement_display=false：关闭组入口恢复；递话条收；局势半程面重现` | 合法保留 | 负向闸 |
| `真实 App 只从统一召对入口开夜卷，具体在役大臣卡不再开面板 (#1849)` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |

## `web/src/chatFailures.test.ts`

| 成员 | 处置 | 依据 |
|---|---|---|
| `delta.replace 触发 onStreamReset，后续 delta 不叠旧半句` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `done+end 携带 admission 机面码时不抛错、不走 error 事件` | 合法保留 | 结构化字段 |

## `web/src/components/decisionModal.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `assembles each decision as ordered sections of one red-seal document` | 合法保留 | 负向闸；批红文书布局 |
| `moves focus to the next memorial when continuing to the next decision` | 合法保留 | 负向闸；焦点／忙态／回调；批红文书布局 |

## `web/src/components/modals.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `#1280 scene/attendant 角色气泡同走 stripOrganicMarkdown` | 整案删除 | 宣称 markdown 清理，只剩 scene/attendant 节点存在，不能证明清理契约 |
| `#1732 failed-only：页脚就地确认；取消零调用；确认后退朝` | 合法保留 | 负向闸；焦点／忙态／回调 |
| `#671 attendant-only 月档列表标签为递话、不冒充奏报` | 合法保留 | 负向闸；拒收／失败形态 |
| `#671 史册月档经 HistoryModal fetch 呈现独立递话原文` | 合法保留 | 负向闸；拒收／失败形态；焦点／忙态／回调 |
| `#671 王承恩递话在邸报纸面外独立区，不经 stripOrganicMarkdown；空则不渲染` | 合法保留 | 负向闸 |
| `adds translated roles and minister emphasis inside the same unchanged turn block` | 合法保留 | turn-id 身份节点；结构化字段 |
| `does not merge personal history while the canonical scroll refresh is delayed` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `does not treat an ordinary history reduction as a withdrawal` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `groups only adjacent rows of a turn without moving an interleaved scene row` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `keeps the last-known scroll without importing personal history when refresh fails` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `keeps the selected night when an earlier night's translation retry finishes late` | 合法保留 | turn-id 身份节点；负向闸；结构化字段；拒收／失败形态 |
| `refreshes the canonical scroll after a non-streaming completed chat update` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `renders a streaming reply as a neutral scene block` | 合法保留 | 负向闸；结构化字段 |
| `renders entrance and exit facts as scene beats, not system notes` | 合法保留 | 负向闸 |
| `renders narrative without an account page` | 合法保留 | 负向闸 |
| `renders role variants and derives the private aside only from audibility` | 合法保留 | 负向闸；结构化字段 |
| `retires the pre-withdrawal snapshot when a successful undo identifies its turn` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `retires the whole old-night snapshot when the persisted player-entry identity changes before refresh fails` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `selects closed scenes through the shared scroll endpoint without a composer` | 合法保留 | turn-id 身份节点；负向闸；结构化字段；拒收／失败形态；焦点／忙态／回调 |
| `shows #505 system-layer reply retry control when replyRetry is set` | 合法保留 | 负向闸；结构化字段；焦点／忙态／回调 |
| `shows the whole chronological night instead of a selected-minister window` | 合法保留 | turn-id 身份节点；负向闸 |
| `切回有记录大臣：语义轮完整含朕问/回话/递话` | 合法保留 | turn-id 身份节点；负向闸 |
| `半轮 replyRetry：保留同 turn user 气泡且不重复 pending 气泡` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |

## `web/src/components/settlementFaces.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `核账期：王承恩递话条出现；关闭组导航 aria-disabled；密令角标清零；半程局势藏、上月已结只读可达` | 合法保留 | 负向闸 |

## `web/src/components/settlementGazettePanel.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `本面落位：正文直写；朕知道了只调 onDismiss` | 合法保留（布局+dismiss，不宣称正文） | panel/非 dialog/pre 槽/attendant 槽布局 + 朕知道了→onDismiss×1；不证明正文交付 |

## `web/src/components/situation.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `SituationPanel 真渲染有议题时不返回 null` | 合法保留 | 负向闸 |
| `detail modal renders supplied bar meanings` | 整案删除 | outcome-head 恒渲染 2 个，toHaveLength(2) 对宣称『supplied meanings』无独立契约 |
| `shows commitment progress in the issue board` | 合法保留 | 承诺进度控件类名闸；负向闸 |
| `shows commitment progress in the situation detail` | 合法保留 | 承诺进度控件类名闸；负向闸 |
| `shows commitment progress in the situation hover tooltip` | 合法保留 | 承诺进度控件类名闸；负向闸 |
| `uses a styled fallback when a commitment has progress but no text` | 合法保留 | 承诺进度控件类名闸；负向闸 |
| `呈真实奏疏正文与上疏人；不借局势 issues；不渲染结构化字段` | 合法保留（身份+负向，不宣称正文） | 上疏人「杨嗣昌」身份 + 不借局势/不渲染 progress 键；pre 槽布局；不锁 memorial 正文 |

## `web/src/mindreadingDelivery.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `accepted 后 provider failure 以持久 identity 淘汰 generating 快照且保留其它轮` | 合法保留 | 结构化字段 |
| `accepted 后普通流中断会移除未持久化的半段回话` | 合法保留 | 结构化字段 |
| `宣召落账先于回话重读主角，end 后仍重读尾随场景` | 合法保留 | turn-id 身份节点；负向闸；结构化字段 |
| `无夜 identity 不接纳猜测出的旧卷，新夜回话失败也不回闪` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |
| `重叠流归属：旧流尾巴（finally）不清掉更新请求的 busy / 待答文` | 合法保留 | 改写后无 hollow 谓词主导；保留既有结构断言 |
| `陈旧同大臣历史响应：更旧的 GET 迟到不抹掉新完成的轮（generation 守卫）` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |

## `web/src/ministerScrollLens.test.ts`

| 成员 | 处置 | 依据 |
|---|---|---|
| `empty-speaker scene still binds the soft stretch to the turn principal` | 合法保留 | 结构化字段 |
| `具名 divider 段内后续他臣正式 turn：前臣窗移除、后臣窗完整、无 turn 殿侧插话仍随软段` | 合法保留 | 结构化字段 |
| `切回有记录大臣：该臣语义轮完整（朕问/回话/递话/scene 同进）` | 合法保留 | 结构化字段 |
| `半轮 claim：无 minister 气泡的 user 问话按 claimedTurnId 留在本窗` | 合法保留 | 结构化字段 |
| `场景/divider 软段 + 殿侧他臣插话：不串窗且不误删本段上下文` | 合法保留 | 结构化字段 |
| `归属反例：本臣轮内非本臣 speaker 保留；他臣轮不泄漏；无主不泛留` | 合法保留 | 结构化字段 |
| `无锚轮按 chat_turn_id 绑定具名 minister，整轮同进同退` | 合法保留 | 结构化字段 |
| `现行单场景轮按参与臣过滤时保留殿上正式对话` | 合法保留 | 结构化字段 |

## `web/src/staleGuard.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `未切人时历史正常加载不被误丢` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `未切人时响应正常应用不被守卫误丢` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |
| `未切人时离开实时观察正常提示但不恢复已发问话` | 合法保留 | 改写后仍含可报红结构断言（非仅 exists） |

## `web/src/useSettlementFlow.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `opens with a pending summary and shows it when the tail lands` | 合法保留（削 notNull 充数） | 保留 aria-busy 忙→清 + loadState 一次；删落地后 summary() notNull（节点 pending 时已在） |

## `tests/test_relation_brew_636.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_founding_summary_survives_consecutive_brews` | 整案删除（纠中间改名伪装） | HEAD 曾把 byte_identical 改名为 summary_survives 并只留水位；判词点名改名未删；本轮整案删除，不恢复 |

---

## 聚焦测试（七变量）

前缀：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

### 八文件聚焦（主席历史口径对应集；勿与更宽聚焦混记）

主席实跑所列 8 文件曾记 **74 passed in 3.23s**（含当时仍在的 founding 改名壳）。本轮删该壳后同八文件：

```bash
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-t1-fullclass-8 \
  tests/test_featured_dossiers_494.py \
  tests/test_style_temperament_641.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_relation_read_640.py \
  tests/test_scene_llm_1836.py \
  tests/test_six_sciences_seed_608.py \
  tests/test_opening_gazette_delete_1356.py
```

输出：**`73 passed in 5.27s`**（相对主席 74：−1 = founding 改名壳整案删除）。

### 更宽 Python 触及面（另记，勿与 73／74 混）

```bash
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-t1-fullclass-py \
  tests/test_featured_dossiers_494.py \
  tests/test_style_temperament_641.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_relation_read_640.py \
  tests/test_relation_store_632.py \
  tests/test_scene_llm_1836.py \
  tests/test_highlight_judge_544.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translation_1838.py \
  tests/test_cli_backend.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_execution_joint_liability_565.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  tests/test_recommendation_edges_635.py \
  tests/test_six_sciences_seed_608.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_secret_order_isolation_883.py
```

输出：**`334 passed, 1 warning in 14.98s`**

### Web 触及面

```bash
cd web && npm test -- --run \
  src/components/situation.test.tsx \
  src/components/decisionModal.test.tsx \
  src/components/settlementGazettePanel.test.tsx \
  src/components/modals.test.tsx \
  src/useSettlementFlow.test.tsx \
  src/appDurableWiring.test.tsx
```

输出：**`Test Files 6 passed (6) / Tests 160 passed (160)`**，Duration ~7.35s

未跑全量／真模型。未为已删无契约案再造变异证明。

### 自查二连

- 同类型：复扫 `len(readings)>=2`／`founding_summary_survives`／brew 裸 `is not None`／situation 恒 2-head／modals #1280／useSettlementFlow 落地 notNull——均已清；494 身份闸仍在；641 无 `_style_row`／style before-after。
- 引入 bug：未改 `ming_sim/`；未恢复非法 style 比较；未改名伪装正向壳；未新增平行证明体系。

---

## 残留项

- K1／K2：不动生产。
- 不宣称 T1 已由御史台／大理寺复审结清。
- 历史提交不 amend；以本 commit 纠正。

---

## Seal

```text
branch=ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628
parent=bc7426bba49e2cf814c7281d370004da23ea937d
eight_file_focus=73 passed in 5.27s（主席历史同集曾 74；−1 founding 壳）
wide_py_focus=334 passed in 14.98s
web_focus=160 passed in ~7.35s
member_table_rows=168
生产 ming_sim/：无改动
未 push／未开 PR／未关票
```


---

## #1897 本轮 T1 纠偏（相对 241a121dc）

枚举边界：底座 `10e64fbef` → 当前工作树全部改写 Python／Web 测试（不限末轮 168 行表）。

| 成员 | 处置 |
|---|---|
| `test_relation_edges_survive_restore` | 去掉 founding/recent 正文等值，只锁水位／dimension |
| `test_per_route_storage_restore_and_escort_split` | 去掉整对象与 memorial_text 等值，只锁 turn/band/escort 结构 |
| `test_long_knowledge_bodies_survive_storage_without_brief_card_cap` | 整案删除（存在性壳） |
| `test_883_shared_archive_bypass_positive_and_negative` | 整案删除（存在性壳） |
| `test_gazette_author_1862` 材料路径 strip 非空 | 改为路径身份 |
| `test_month_chain_1843` index/board strip | 改为类型／目录结构 |
| `test_secret_order_payoff_1504` read_material strip/正文等值 | 改为路径集合结构 |
| `web/src/mindreadingDelivery.test.tsx` pending 正文 | 改为槽位占用布尔 + 固定 busy UI |
| `web/src/components/situation.test.tsx` fallback | 恢复固定 UI「未知进度」；去 issue.title 散文负向哨兵 |

