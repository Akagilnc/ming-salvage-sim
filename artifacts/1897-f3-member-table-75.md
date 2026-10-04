# #1897 F3 原 75 候选逐成员表（纠正：P6 测试锁文豁免作废）

- 原表 tip：清 17 / 保留 58（含错误的 P6/朱笔 note·title 保真豁免）
- **更正史**：P6 生产保真 ≠ 允许测试锁文；27/30/38/56 等自由文本机械断言清退
- **#39 终裁**：helper-only `normalize_stop_condition` 换形案**整案删除**；入口 bad `stop_condition` 闸负向留存于 `test_657_abi_mapper_matrix_a1_a12`
- DB CHECK `form IN ('会签','当面站台','御笔手敕')`：`ming_sim/db.py` 真源闭集 → FORM_ENUM **保留**合法
- 终表真源见回执「F3 最终语义复核」真正成员完整表 + 保留例外（本 75 表为历史过程；#39 行已按终裁更正）

| # | 成员 | 形状 | 处置 | 理由 |
|---:|---|---|---|---|
| 1 | `test_audience_translate_1837.py:238` `test_pending_round_approval_endorsed_before_close_or_after_month_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 2 | `test_declaration_dispatch_1835.py:654` `test_registration_adds_new_person_to_roster_and_rejects_existing_name` | ROSTER | **保留** | 名册身份 content.characters，非密令进展盯文 |
| 3 | `test_dossier_endorsements_612.py:90` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 4 | `test_dossier_endorsements_612.py:97` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 5 | `test_dossier_endorsements_612.py:101` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 6 | `test_dossier_endorsements_612.py:184` `test_undo_chat_turn_removes_source_bound_endorsements_from_judge` | OTHER | **保留** | 结构化背书行/闭集 form；_extract 入参扫描误报 |
| 7 | `test_event_trigger_gate.py:1405` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | TITLE_LOCK | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 8 | `test_event_trigger_gate.py:1406` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 9 | `test_event_trigger_gate.py:1410` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 10 | `test_event_trigger_gate.py:1411` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 11 | `test_event_trigger_gate.py:150` `test_historical_event_expires_after_latest_window_when_gate_unsatisfied` | TITLE_LOCK | **清** | terminal 改 id+terminal_state；删 title 整对象 |
| 12 | `test_execution_pressure_654.py:607` `test_path3_locality_fail_keeps_draft_no_text_in_rejection` | GATE_NEG | **保留** | 闸类负向：拒收载荷不得带 text 键 |
| 13 | `test_fiscal_levy_effect.py:1455` `test_non_event_world_question_is_not_bound_to_the_only_due_levy` | TITLE_LOCK | **清** | 世界问绑定改 event_id；删请愿标题 |
| 14 | `test_fiscal_levy_effect.py:1468` `test_non_event_world_question_is_not_bound_to_the_only_due_levy` | TITLE_LOCK | **清** | 世界问绑定改 event_id；删请愿标题 |
| 15 | `test_mechanical_tail_1845.py:569` `test_mechanical_tail_missing_llm_config_surfaces_retry` | SUMMARY_LOCK | **清** | 删 summary 散文锁；保留 mechanical_tail status=done |
| 16 | `test_mechanical_tail_1845.py:497` `test_chapter_memory_retired_from_three_readers` | KEY_EXIST | **保留** | 邸报供料 body schema（章节记忆退役） |
| 17 | `test_menu_lifecycle_drain_396.py:599` `test_drain_waits_for_queued_chat_stream_not_just_gate_holder` | KEY_EXIST | **保留** | 流式 delta 结构键 content，控序脚手架 |
| 18 | `test_new_issues_section_rejections.py:332` `test_new_issue_valid_decree_still_creates` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 19 | `test_person_delta_adapter.py:235` `test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 20 | `test_person_delta_adapter.py:240` `test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 21 | `test_pihong_dossier_1490.py:311` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 22 | `test_pihong_dossier_1490.py:312` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 23 | `test_pihong_dossier_1490.py:322` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 24 | `test_pihong_dossier_1490.py:323` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 25 | `test_pihong_dossier_1490.py:372` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 26 | `test_pihong_dossier_1490.py:373` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 27 | `test_pihong_dossier_1490.py:379` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | NOTE_EQ | **清** | 更正：P6 豁免非法；删 note/label 散文等值；保留 decided + 无 dossier_decision |
| 28 | `test_pihong_dossier_1490.py:397` `test_lying_label_rebuilt_from_server_option` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 29 | `test_pihong_dossier_1490.py:398` `test_lying_label_rebuilt_from_server_option` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 30 | `test_pihong_dossier_1490.py:405` `test_lying_label_rebuilt_from_server_option` | NOTE_EQ | **清** | 再更正：`!=` 仍非法；只留 dossier_id/decision 结构闸 |
| 31 | `test_pihong_dossier_1490.py:443` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 32 | `test_pihong_dossier_1490.py:444` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 33 | `test_pihong_dossier_1490.py:454` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 34 | `test_pihong_dossier_1490.py:462` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 35 | `test_pihong_dossier_1490.py:463` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 36 | `test_pihong_dossier_1490.py:493` `test_ordinary_event_with_hallucinated_capability_submits` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 37 | `test_pihong_dossier_1490.py:494` `test_ordinary_event_with_hallucinated_capability_submits` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 38 | `test_pihong_dossier_1490.py:500` `test_ordinary_event_with_hallucinated_capability_submits` | NOTE_EQ | **清** | 更正：P6 豁免非法；删 note/label 散文等值；保留无 dossier_decision |
| 39 | `test_pihong_dossier_1490.py` 原 `test_657_p6_mapper_deliberate_preserve_free_text` / 后改名杂糅 / 再换 `test_657_stop_condition_normalize_schema_negative` | TITLE_LOCK→helper-only | **清整案（删换形）** | 保真锁文与 helper-only `normalize_stop_condition` 独测均删；**不**新建平行证明。入口闸负向留存：`test_657_abi_mapper_matrix_a1_a12` 对 `map_rescript_option_or_choice(... stop_condition='')` 的 `ValueError` 拒收 |
| 40 | `test_pihong_dossier_1490.py:1456` `test_1621_http_follow_draft_uses_catalog_army_id` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 41 | `test_pihong_dossier_1490.py:1457` `test_1621_http_follow_draft_uses_catalog_army_id` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 42 | `test_pihong_dossier_1490.py:1603` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 43 | `test_pihong_dossier_1490.py:1604` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 44 | `test_pihong_dossier_1490.py:1610` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 45 | `test_pihong_dossier_1490.py:1634` `test_657_s6_http_present_target_gets_unique_origin_entry` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 46 | `test_pihong_dossier_1490.py:1707` `test_657_web_http_hitl_lock_boundary_same_gate` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 47 | `test_pihong_dossier_1490.py:1727` `test_657_illegal_summon_target_http_zero_writes` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 48 | `test_pihong_dossier_1490.py:1728` `test_657_illegal_summon_target_http_zero_writes` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 49 | `test_pihong_dossier_1490.py:1755` `test_1620_http_follow_draft_office_token_routes_to_person` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 50 | `test_pihong_dossier_1490.py:1756` `test_1620_http_follow_draft_office_token_routes_to_person` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 51 | `test_pihong_dossier_1490.py:1792` `test_1620_http_follow_draft_grant_uses_stored_amount` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 52 | `test_pihong_dossier_1490.py:1793` `test_1620_http_follow_draft_grant_uses_stored_amount` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 53 | `test_pihong_dossier_1490.py:1850` `test_657_follow_draft_ignores_client_field_overlay` | TITLE_LOCK | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 54 | `test_pihong_dossier_1490.py:1851` `test_657_follow_draft_ignores_client_field_overlay` | TITLE_LOCK | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 55 | `test_pihong_dossier_1490.py:1934` `test_657_summon_missing_tag_enter_blocks_phase2_then_retry` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 56 | `test_pihong_dossier_1490.py:2010` `test_657_default_hold_preserves_red_pen_note` | NOTE_EQ | **清整案** | 专为朱笔 note 保真；整案删除（default_hold 闸已由 `test_657_default_hold_missing_and_empty_action` 覆盖） |
| 57 | `test_pihong_dossier_1490.py:2461` `test_658_deliberate_backed_and_stalled_dossier_first` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 58 | `test_pihong_dossier_1490.py:2624` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 59 | `test_pihong_dossier_1490.py:2628` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 60 | `test_pihong_dossier_1490.py:2802` `test_658_ordinary_edit_does_not_inherit_push_target` | OTHER | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 61 | `test_pihong_dossier_1490.py:2901` `<module>` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 62 | `test_pihong_dossier_1490.py:2902` `<module>` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 63 | `test_pihong_dossier_1490.py:1345` `test_657_s10_http_five_actions_and_1490_no_regress` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 64 | `test_pihong_dossier_1490.py:1346` `test_657_s10_http_five_actions_and_1490_no_regress` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 65 | `test_pihong_dossier_1490.py:2640` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 66 | `test_rescript_heal_isolation_1801.py:133` `test_1801_item_utf8_heals_then_drops_only_bad_item` | CROSS_TITLE | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 67 | `test_rescript_heal_isolation_1801.py:138` `test_1801_item_utf8_heals_then_drops_only_bad_item` | TITLE_LOCK | **保留** | heal 失败字段图 schema（title/summary 键存在，非值锁） |
| 68 | `test_rescript_heal_isolation_1801.py:153` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 69 | `test_rescript_heal_isolation_1801.py:159` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | KEY_EXIST | **保留** | heal 失败字段图 schema（title/summary 键） |
| 70 | `test_rescript_heal_isolation_1801.py:163` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | SUMMARY_LOCK | **保留** | heal 失败字段图 schema（summary 键，非值锁） |
| 71 | `test_rescript_heal_isolation_1801.py:190` `test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 72 | `test_rescript_heal_isolation_1801.py:212` `test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 73 | `test_rescript_heal_isolation_1801.py:230` `test_1801_eight_items_all_pass_no_heal_no_trim` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 74 | `test_web_chat_serialization_393.py:217` `test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn` | WHOLE_OBJ | **清** | 删流式/问话散文锁；改 type=delta 与 user 轮次条数 |
| 75 | `test_web_chat_serialization_393.py:266` `test_identity_setup_failure_preserves_question_and_releases_pending_owner` | WHOLE_OBJ | **清** | 删流式/问话散文锁；改 type=delta 与 user 轮次条数 |

## 词表扩扫（本轮）新增命中与处置摘要

旧词表缺 `label`/`hint`/`decree_text`/`stage_text`/`stop_condition`/`reason`/`detail`/`message` 等 → 扩扫后授权自由文本 **113**（旧窄词表曾报 58）。

| 类 | 处置 |
|---|---|
| 同形 label/note/decree_text 散文等值（pihong + decree_dossiers_571） | **本轮已清** |
| FORM_ENUM / SSE / GATE_NEG / heal 键 schema / ROSTER | **保留**（闭集或线协议） |
| `reason` 机器码（`already_revoked` / `commitment_due` / `option_missing_fields_heal_exhausted` 等） | **保留**（非自由散文；闭集/typed code） |
| `stop_condition` JSON 结构化条件 | **保留**（结构化条件对象，非邸报散文） |
| events.json #189 软判 title/summary 哨兵 | **保留**（独立内容域） |
| `test_1778_*` 以 `decree_text` 作文案身份键的 `set(round_*)` | **剩余范围**（重构成本大；未本轮空心替换） |
| person_delta / fiscal detail / urge / relation 等 CJK `reason`/`detail` 散文 | **剩余范围**（扩扫新见；非本票声明写入盯文主战场，据实不虚报结清） |


## 本轮（废弃词表 / 113 结清）附注

- 枚举：`/tmp/1897-f1f3-corr4/enum_f3_nofield.py`（**无** `TEXT_ATTRS`）；语义裁决不按字段名。
- 已报 113：SSE/FORM/typed/heal/独立域/结构化条件 **保留并举证**；其余点名散文锁（1778 decree_text 键、person_delta reason、fiscal detail、urge/relation、#30/#39、style 保真）**清**。
- 预存失败：`test_1682_phase2_surfaces_ambiguous_stored_choice`（HEAD 无本轮 diff 亦红）→ deselect 记账。
