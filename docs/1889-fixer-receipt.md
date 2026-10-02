# #1889 修内司回执：冻结判词 J1–J8

本轮基线 `7c52adc06`，按冻结判词八类施工，不以原判点名文件代替类别范围。旧轮回执及其证据仍可由 `git show 7c52adc06:docs/1889-fixer-receipt.md` 读取；其「九类」不是本轮结算。

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a0fa36-dbad-7667-a858-8fa1102fd587@fixer/fix-packet.md`；冻结判词为同目录 `attachments/00-1889-judge-7c52adc06.json`。本文件是施工证据，不另立 authority。

## 逐类结算

| 类 | 根因、正确行为、整类处置 | 保留项依据 |
|---|---|---|
| J1 持久事实 SQL 职责拆分 | 默认军队读、正式拟旨生命周期、离心债账、荐举历史、动态参与者事实均归实体 Store；扩扫发现的 next_audience_todos 与催办历史同样迁入 DossierStore。调用方保留计算、编排与事务。 | schema/PRAGMA/事务语句、聊天/夜/暂存动作/恢复/拒收报告/agno 会话等技术载体保留；不能以实体名白名单漏掉动态 SQL。实体事实跨表 roster 发现与查询一起放入 CharacterKnowledgeStore。 |
| J2 同形读取合并 | 删十三组 Store 平行 SELECT；扩扫再合并聊天轮、回滚项、agno blob、候选版本/payload/待拟旨、背书存在性、事务声明定位、夜序号、故事账 tags/origin。当前全 ming_sim 字面 SELECT 经空白/逗号/等号归一化后，无重复组。 | 不合并不同筛选、投影、排序、公私载体或绑定语义；不造通用查询框架。 |
| J3 财政损坏负向契约 | 原测试把吞掉持久 fiscal 损坏、继续修改别省写成正确行为。复用原案改为异常、原坏载荷仍在、别省不变；扩及 settle/p/st/_meta/田亩/份额基线坏形，修复生产 try/except+continue。空数组/null _meta 不再借 falsy 默认伪装成字典。修复后完整财政负向/修复后重算案仍在。 | 复用前半段既有 fixed_fiscal marker 与回滚后错误包出口，三个入口错误包测试不放松。直接历史饷率入口仍抛 ValueError，front-half 保留 cause。合法没有 settle 的非底盘省及独立摘要不混作坏形。 |
| J4 注入异常识别 | 恢复本轮前误删的自造故障识别；同类扩至模型/财政/事务/聊天/夜/拟旨/关系/恢复/尾链。直接异常识别 sentinel，包装异常识别 cause；callback 包装检查原 RuntimeError 与 callback boom，而非生产包装文案。补齐月链、酿制尾链、模型 smoke、邸报等遗漏。 | 保留原对象 identity、专用异常类及结构化故障字段的有效识别；外层 rollback-only 错误的原 sentinel 在内层已核。不锁生产错误措辞。 |
| J5 去叙事锁定、完整原载荷 | 删 deficit 姓名/数字/正则叙事约束；长知识 body 与财政 note 改完整原值等式；删拒收 reason 散文断言，保留 section/category/item_json。 | 完整 opaque 输入等值、结构化 ID/分类/状态、合法选项与原自造故障不是叙事模板。移除的 test_old_save_schema_is_upgraded_for_person_archive_fields 是退役旧档迁移契约，不为恢复兼容而改 schema；新档字段契约仍在。 |
| J6 确定性测试入口及意外并发 | canned 过月公共 harness 和真实玩家入口辅助缝改用即时执行的原生 Future，覆盖机械尾复用案；先前 finish_prior 人造 Thread 改在入口前确定性完成。没有改生产线程策略、写队列或新增锁。 | 有意测试 Future/写队列/机械尾 join 的 deferred seam 和专属并发案保留；不是把真实并发测试改名冒充小测。 |
| J7 自由文本保真 | 删除自由正文、长 note、阶段/判词/情况/理由、经历/关系来源/载荷、旨意/事务名与起因的固定截断及写入前 strip；空白判定和保存原文分开。扩扫补齐 actual_progress、draft candidate、due commitment content、memorial_text。 | 结构引用归一化、枚举值与数值 clamp 保留；名单数量限制、hash/路径/ID、日志/错误诊断预览、显式 summary/brief 卡独立摘要保留，不覆盖原事实。随同删除 FieldSpec.max_len 与全部 34 个失效 catalog 长度参数；未新增长度拒收机制。 |
| J8 退役生成合计旧补偿及自等式 | 删 flows 的 arrears 列滞后补偿、db derived_bad 自等式校验和专用 ArmyStore 读取。 | SQLite generated arrears 保留；真源省/中央欠饷、容器跨实体独立守恒、非适用军队零值约束、rollback 过滤不可写 generated 列均保留。 |

### J2 权威读取成员对应

| 被删/被替代入口 | 唯一读口 |
|---|---|
| PowerStore.read_transition_army_owner_power | read_apply_issue_entities |
| CharacterStore.read_sponsor_dismissed | read_dead_person_core_subjects |
| CharacterStore.read_apply_dossier_promulgation | read_resolve_power_id |
| CharacterStore.read_materialize_office_appointment_dossier | read_find_pacification_target |
| CharacterStore.read_appointment_intent_is_current_office_noop | read_sponsor_transferred |
| ArmyStore.read_map_rescript_option_or_choice | read_apply_military_order_station_effect |
| ArmyStore.read_apply_fixed_period_flows_consecutive_pay_shortfall_months | read_apply_region_army_pay_tick |
| PersonLogStore.read_existing_edge_id | read_existing_leg_id |
| FactionStore.read_calibrate_faction_offsets | read_faction_leverage |
| RegionStore.read_require_valid_pay_source_region | read_apply_surcharge_decrees |
| RegionStore.read_add_building | read_assert_commission_grant_target_exists |
| ReignStateStore.read_record_dossier_decision | read_current_settle_turn |
| ReignStateStore.read_pay_order_grounding_facts | read_record_claim_flow_logs |
| retry/fail/truncate/undo 聊天读取 | GameDB.read_chat_turn / _chat_turn_rollback_items |
| agno legacy blob 重写前读 | GameDB._agno_legacy_runs_blob |
| 变更待拟旨/payload/候选版本的平行读取 | GameDB._pending_directive_row / pending_action_payload_row / _directive_candidate_version_row |
| 背书目标、源轮、人物存在性读取 | DossierStore.exists / source_chat_turn_exists / CharacterStore.read_assert_characters_exist |
| AffairStore.resolve_declaration 的 birth_key 读 | peek_declared_id |
| audience_night._allocate_seq | GameDB.allocate_night_seq |
| 三处夜 tags 读、两处 session origin 读 | audience_night.ledger_tags / _ledger_by_origin_ref（直接传解码后的 entry，不转 Python repr） |

## 枚举命令与复扫

范围先取全部生产 Python（包括动态 SQL），全部 Python 测试、tracked 前端测试；再按事实 owner、输入是否自由文本、是否原自造故障、是否故意并发人工归类。候选不等于缺陷，不能将上述保留项暗中从原谓词排除。

```sh
rg -n 'execute\(|executemany\(|executescript\(' ming_sim --glob '*.py'
rg -n 'json.loads|except .*Error|except Exception|continue' ming_sim --glob '*.py'
rg -n 'pytest.raises|raise |__cause__|assert .*str\(' tests --glob '*.py'
rg -n 'assert |re.search|re.match|startswith|endswith' tests --glob '*.py'
rg -n 'toContain\(|toMatch\(|textContent|innerText' web/src --glob '*test*'
rg -n 'Thread\(|ThreadPoolExecutor|submit\(|run_in_executor' tests --glob '*.py'
rg -n 'strip\(\)|lstrip\(\)|rstrip\(\)|\[:|len\(' ming_sim --glob '*.py'
rg -n 'arrears|derived_bad|滞后|GENERATED ALWAYS' ming_sim tests --glob '*.py'
git diff --check
```

最终全 tracked Python 的 AST 枚举：384 文件，3979 SQL 调用（含动态）、12558 Assert、1730 Raise、532 raises、256 Slice、1848 trim、1099 len、108 调度候选；输出 `/tmp/1889-final-inventory.json`，命令 `python3 /tmp/1889-final-inventory.py`。候选包含脚本/测试，不将数量当缺陷数；动态查询、断言与裁剪按本节原范围归类。

AST 复扫不用自由文本正则作生产/测试闸。SQL 枚举含 execute/executemany/executescript 的 Constant、JoinedStr、Name 查询，记录完整所属函数；测试枚举 Assert、Raise、pytest.raises；J7 枚举所有 Slice、strip/lstrip/rstrip、len 调用及比较；J6 枚举所有 Thread/Executor/submit 调用。扫描文件：`/tmp/1889-{sql-now,slices-now,dynamic-slices,store-trims,length,threads,removed-identities,injections-final,fixedcuts-final,web-text-final,arrears-now}.txt`。这些是检索候选，不是把未判成员自动算作正确的机械门。

J2 复扫可直接复现（结果零重复组，含所有实体及技术载体字面读取）：

```sh
python3 - <<'PY'
import ast, pathlib, collections, re
queries = collections.defaultdict(list)
for path in pathlib.Path('ming_sim').rglob('*.py'):
    tree = ast.parse(path.read_text())
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == 'execute' and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            continue
        sql = ' '.join(call.args[0].value.lower().split())
        sql = re.sub(r'\s*([,=()])\s*', r'\1', sql)
        if sql.startswith('select'):
            queries[sql].append((str(path), call.lineno))
for sql, members in queries.items():
    if len(members) > 1:
        print(sql, members)
PY
```

下表为本轮改变/新增/删除入口的完整 AST 成员索引（包含删去的旧名字，不表示仍有双轨）；不是只列判词样本。生成法：对 `git diff --name-only -- '*.py'` 每个文件，分别 `ast.parse(git show 7c52adc06:<file>)` 与当前文件；按 class/function 全名比较 `ast.dump(..., include_attributes=False)`，列出两边不相等的所有入口。J1/J2 的转调使用方与 J7 的正文成员均在生产表；测试表中 J3 财政、J5 完整载荷/叙事、J6 harness 各已在上表点明，其余故障案为 J4。未改变成员的分类依据在逐类保留栏。

## 完整入口成员表

| 文件 | 本轮全部改变/新增/删除入口成员 |
|---|---|
| `ming_sim/action_clusters.py` | `assert_action_candidate_shape`，另删除 schema 成员 `FieldSpec.max_len` |
| `ming_sim/action_materialize.py` | `_build_catalog`（34 个失效长度参数），`_apply_existing_appointment_hit`, `_persist_appointment_summon`, `_resolve_xiexang_army_id`, `stage_assignment_candidate`, `stage_authorization_candidate`, `stage_grant_allocation_candidate`, `stage_pacification_candidate`, `stage_punishment_candidate`, `stage_referral_candidate`, `stage_revoke_authority_candidate`, `stage_revoke_decree_candidate` |
| `ming_sim/audience_night.py` | `_allocate_seq`, `_mark_summon_entries_in_transit`, `ledger_tags`, `retire_unsettled_summons_for_inactive`, `settle_summon_origin`, `update_summon_travel_tone` |
| `ming_sim/breach_plea.py` | `_apply_halfway_national_setback`, `_merge_plea_kind_into_todo`, `_sponsor_dismissed`, `_stages_passed_from_records`, `finalize_persist`, `try_defer_revoke_to_breach_plea`, `write_breach_plea_todo` |
| `ming_sim/centrifuge_ledger.py` | `_accrue_centrifuge`, `_load_namespace`, `rebuild_centrifuge_cache` |
| `ming_sim/cli_backend.py` | `_ground_relative_pay_order_deadlines`, `_pay_order_grounding_facts`, `capture_manual_directive_payload`, `extract_draft_intent` |
| `ming_sim/content.py` | `load_character_content`, `load_event_content`, `load_opening_legacies`, `load_powers` |
| `ming_sim/covert_progress.py` | `_current_game_turn`, `apply_monthly_covert_actual_progress`, `decide_secret_order_settlement` |
| `ming_sim/credit_events.py` | `_existing_edge_id`, `write_credit_event` |
| `ming_sim/db.py` | `GameDB._append_secret_order_line`, `GameDB._apply_military_order_station_effect`, `GameDB._apply_pay_order_override_effect`, `GameDB._apply_pending_action`, `GameDB._apply_revoke_decree_verdict_effect`, `GameDB._calibrate_faction_offsets`, `GameDB._character_knowledge_events`, `GameDB._chat_turn_rollback_items`, `GameDB._commit_office_action`, `GameDB._create_grant_fiscal_item`, `GameDB._directive_candidate_version_row`, `GameDB._discard_pending_decree_forecast`, `GameDB._has_complete_province_pay_containers`, `GameDB._initiative_title_and_body`, `GameDB._materialize_office_appointment_dossier`, `GameDB._maybe_write_backing_betray_credit`, `GameDB._merge_directive_payload`, `GameDB._participant_roster_tables`, `GameDB._pending_directive_row`, `GameDB._require_valid_pay_source_region`, `GameDB._restore_chat_rollback_items_in_tx`, `GameDB._rewrite_session_legacy_runs_blob`, `GameDB.add_building`, `GameDB.add_directive`, `GameDB.apply_army_deltas`, `GameDB.apply_building_deltas`, `GameDB.apply_character_power_changes`, `GameDB.apply_dossier_promulgation`, `GameDB.apply_execution_joint_liability`, `GameDB.apply_power_deltas`, `GameDB.apply_power_rename`, `GameDB.apply_region_deltas`, `GameDB.army_rows`, `GameDB.assert_army_pay_source_container_conservation`, `GameDB.attach_pending_action_endorsement`, `GameDB.build_faction_denunciation_facts`, `GameDB.clear_directive_needs_clarification`, `GameDB.close_secret_order`, `GameDB.confirm_directive`, `GameDB.count_pending_directives`, `GameDB.create_armies_from_extraction`, `GameDB.create_fiscal_item`, `GameDB.delete_directive`, `GameDB.fail_chat_turn`, `GameDB.flag_directive_needs_clarification`, `GameDB.get_directive`, `GameDB.insert_legacy`, `GameDB.insert_next_audience_todo`, `GameDB.list_monthly_archives`, `GameDB.list_next_audience_todos`, `GameDB.list_night_promulgated_directives`, `GameDB.list_promulgated_directives`, `GameDB.mark_directives_issued`, `GameDB.mark_event_avoided`, `GameDB.mark_event_obsolete`, `GameDB.mark_event_triggered`, `GameDB.mark_next_audience_todo_status`, `GameDB.merge_execution_note`, `GameDB.pending_action_payload_row`, `GameDB.read_chat_turn`, `GameDB.record_dossier_decision`, `GameDB.record_dossier_progress`, `GameDB.record_event_decision_choice`, `GameDB.record_fiscal_config_change`, `GameDB.record_monthly_dossier_progress`, `GameDB.record_monthly_grant_reconciliations`, `GameDB.reject_directive`, `GameDB.remove_building`, `GameDB.remove_fiscal_item`, `GameDB.restore_interrupted_after_failed_retry`, `GameDB.seed_opening_crises`, `GameDB.set_character_status`, `GameDB.submit_secret_order_for_review`, `GameDB.transition_army_owner_power`, `GameDB.truncate_chat_turn_agno_runs`, `GameDB.undo_chat_turn`, `GameDB.update_directive_text`, `GameDB.upsert_pending_directive` |
| `ming_sim/decree.py` | `_rescript_decisions`, `pre_settle`, `write_decree_with_agno` |
| `ming_sim/due_review.py` | `build_due_review_input`, `decide_due_review_verdict`, `project_due_review_scene` |
| `ming_sim/entities/affair/store.py` | `AffairStore.open`, `AffairStore.resolve_declaration`, `parse_affair_declaration` |
| `ming_sim/entities/army/store.py` | `ArmyStore.ordered_rows`, `ArmyStore.read_apply_fixed_period_flows_consecutive_pay_shortfall_months`, `ArmyStore.read_assert_army_pay_source_container_conservation_id_arrears_province_pay_arrears_central_pay_arrears`, `ArmyStore.read_map_rescript_option_or_choice` |
| `ming_sim/entities/character/store.py` | `CharacterStore.read_apply_dossier_promulgation`, `CharacterStore.read_appointment_intent_is_current_office_noop`, `CharacterStore.read_materialize_office_appointment_dossier`, `CharacterStore.read_sponsor_dismissed`, `CharacterStore.recommendation_events` |
| `ming_sim/entities/character_knowledge/store.py` | `CharacterKnowledgeStore.participant_record_rows` |
| `ming_sim/entities/dossier/store.py` | `DossierStore._validate_endorsement`, `DossierStore.add_links`, `DossierStore.append_commitment_urge`, `DossierStore.audience_todo`, `DossierStore.audience_todos`, `DossierStore.count_audience_todos`, `DossierStore.exists`, `DossierStore.insert_audience_todo`, `DossierStore.record_actual_progress`, `DossierStore.set_audience_todo_origin`, `DossierStore.set_audience_todo_status`, `DossierStore.source_chat_turn_exists`, `DossierStore.update_payload`, `DossierStore.urge_history` |
| `ming_sim/entities/faction/store.py` | `FactionStore.add_axis_debt`, `FactionStore.append_centrifuge_log`, `FactionStore.centrifuge_axis_totals`, `FactionStore.centrifuge_namespace`, `FactionStore.centrifuge_overdraw_totals`, `FactionStore.clear_axis_debt`, `FactionStore.insert_axis_debt`, `FactionStore.read_calibrate_faction_offsets` |
| `ming_sim/entities/issue/store.py` | `IssueStore.count_pending_directives`, `IssueStore.delete_draft_directive`, `IssueStore.directive`, `IssueStore.directive_archive_months`, `IssueStore.directives_by_ids`, `IssueStore.insert_directive`, `IssueStore.mark_directives_issued`, `IssueStore.set_directive_status`, `IssueStore.update_directive_text` |
| `ming_sim/entities/person_log/store.py` | `PersonLogStore.append`, `PersonLogStore.read_existing_edge_id`, `_clip` |
| `ming_sim/entities/power/store.py` | `PowerStore.read_transition_army_owner_power` |
| `ming_sim/entities/region/store.py` | `RegionStore.read_add_building`, `RegionStore.read_require_valid_pay_source_region` |
| `ming_sim/entities/reign_state/store.py` | `ReignStateStore.read_pay_order_grounding_facts`, `ReignStateStore.read_record_dossier_decision` |
| `ming_sim/flows.py` | `_apply_economy_list`, `_apply_population_transfers`, `apply_fixed_period_flows` |
| `ming_sim/issues.py` | `_apply_fiscal_levy_targets`, `_apply_score_extraction_body`, `_apply_surcharge_decrees`, `_pending_person_changes_block_event_gate`, `_spawn_legacy_from_effect`, `_strategic_event_result_preflight_error`, `apply_issue_tracker_output`, `apply_office_appointment`, `event_to_issue` |
| `ming_sim/month_chain.py` | `_consume_rescript_answers`, `_question_as_decision` |
| `ming_sim/pay_order.py` | `prepare_pay_order_entries`, `restore_pay_order_override` |
| `ming_sim/recommendations.py` | `list_recommendation_events` |
| `ming_sim/relations.py` | `credit_event_to_edge` |
| `ming_sim/rescript_actions.py` | `map_rescript_option_or_choice` |
| `ming_sim/session.py` | `GameSession._iter_unconsumed_decided_summons`, `GameSession.finish_rescript_phase2`, `GameSession.prepare_rescript_prewrite`, `_appointment_intent_is_current_office_noop`, `_target_active_officeholder` |
| `ming_sim/settlement_payload.py` | `list_due_commitments`, `parse_decision_blocks` |
| `ming_sim/staged_commitment.py` | `list_due_grant_report_dossiers_for_scan`, `normalize_commitment_stages` |
| `ming_sim/urge_lever.py` | `_record_commitment_urge`, `apply_distortion_to_verdict`, `collect_urge_history` |
| `tests/month_chain_helpers.py` | `InlineExecutor.submit`, `canned_full_settlement` |
| `tests/test_advances_section_rejections.py` | `test_advance_code_exception_propagates` |
| `tests/test_affairs_1831.py` | `test_new_issue_affair_attach_failure_leaves_no_partial_product` |
| `tests/test_applier_contract.py` | `test_rejected_item_fields` |
| `tests/test_audience_night_498.py` | `test_open_night_atomic_on_dead_roster_injection` |
| `tests/test_audience_restore_505.py` | `test_657_rescript_summon_atomic_on_enter_failure` |
| `tests/test_audience_translate_1837.py` | `test_pending_round_approval_endorsed_before_close_or_after_month_join` |
| `tests/test_audience_travel_gating_670.py` | `test_consume_open_night_and_recorder_share_one_transaction`, `test_multi_origin_fresh_closes_once_per_person_and_retries`, `test_waiting_active_departure_settle_failure_rolls_back_all_four_sides` |
| `tests/test_audience_undo_506.py` | `test_attach_origin_bind_atomic_no_orphan_enter_on_midway_crash`, `test_undo_reversal_is_atomic_on_midway_crash` |
| `tests/test_centrifuge_ledger_690.py` | `test_t11_rebuild_clears_dirty_and_write_path_rolls_back` |
| `tests/test_character_knowledge_489.py` | `test_long_knowledge_bodies_survive_storage_without_brief_card_cap` |
| `tests/test_cli_backend.py` | `test_run_backend_for_config_traces_on_backend_error` |
| `tests/test_cli_play_turn.py` | `test_terminal_minister_chat_preserves_chat_error_when_rollback_fails`, `test_terminal_minister_chat_removes_user_message_when_session_chat_fails`, `test_terminal_minister_chat_reply_persist_failure_keeps_user_message` |
| `tests/test_close_issues_section_rejections.py` | `test_close_issue_code_exception_propagates` |
| `tests/test_declaration_dispatch_1835.py` | `test_reference_to_nonexistent_entity_is_rejected_without_killing_sibling_item` |
| `tests/test_decree_dossiers_571.py` | `test_secret_order_and_dossier_roll_back_as_one_unit`, `test_secret_order_close_failure_rolls_back_only_its_two_axes`, `test_secret_order_progress_rolls_back_both_axes_in_outer_atomic` |
| `tests/test_due_review_621.py` | `test_takeover_guard_fail_closed_on_ownership_error` |
| `tests/test_event_chain_cascade.py` | `test_cascade_rolls_back_owned_transaction_on_later_write_failure` |
| `tests/test_event_trigger_gate.py` | `test_apply_score_extraction_appointment_rolls_back_with_outer_transaction`, `test_historical_situation_auto_trigger_rolls_back_soft_issue_when_core_effect_fails` |
| `tests/test_executor_routing_721.py` | `test_directive_routing_rejection_rolls_back_with_outer_owner`, `test_rolled_back_collector_reuse_does_not_mirror_orphan` |
| `tests/test_faction_brew_637.py` | `test_faction_apply_db_error_propagates_loudly_not_disguised`, `test_faction_claim_db_error_propagates_loudly` |
| `tests/test_fiscal_levy_effect.py` | `test_fiscal_levy_bad_first_pass_aborts_then_repair_derives_share_seed`, `test_fiscal_levy_bad_region_aborts_then_repair_preserves_share_targets`, `test_fiscal_levy_bad_region_does_not_redistribute_jiao_lian_targets`, `test_fiscal_levy_bad_share_meta_aborts_then_repair_derives_targets`, `test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass`, `test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed`, `test_fiscal_levy_rejects_bad_settle_shape_atomically`, `test_fiscal_levy_rejects_malformed_region_fiscal`, `test_fiscal_levy_shadow_skips_bad_settle_shape_without_blocking_other_regions`, `test_fiscal_levy_shadow_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass` |
| `tests/test_fiscal_substrate_bridge.py` | `test_advance_province_fiscal_substrate_rolls_back_inside_outer_atomic`, `test_fixed_flows_substrate_hub_failure_rolls_back_cutover_writes`, `test_region_loader_expands_shared_settle_meta_defaults` |
| `tests/test_gazette_author_1862.py` | `test_gazette_failure_retries_report_only` |
| `tests/test_llm_channel_config.py` | `test_verify_llm_available_cli_channel_failure_raises`, `test_verify_llm_available_legacy_env_only_failure_raises` |
| `tests/test_material_directory_1830.py` | `test_secret_order_material_read_failure_propagates` |
| `tests/test_mechanical_tail_1845.py` | `test_exhausted_mechanical_tail_fails_and_blocks_next_month`, `test_non_exhausted_tail_failure_stays_pending_and_retries`, `test_real_brew_failure_reaches_tail_failure_and_retry`, `test_web_barrier_resumes_pending_tail_before_join` |
| `tests/test_month_call_recovery_1846.py` | `test_code_exception_during_world_commit_keeps_phase_and_settled_edicts`, `test_error_pack_failure_keeps_original_fault_and_retry_phase`, `test_escape_hatch_discards_world_segment_only_on_second_player_retry`, `test_forecast_exhaustion_does_not_overwrite_prior_ending`, `test_settlement_recovery_projects_month_call_failure`, `test_world_commit_failure_after_alongside_retries_uncommitted_segment`, `test_world_text_exhaustion_stops_month_keeps_settled_edicts`, `test_world_translate_exhaustion_keeps_text_resume_retries_translate_only` |
| `tests/test_month_chain_1843.py` | `_prepare_player_month`, `test_advance_reloads_memory_after_transaction_rollback`, `test_failed_declaration_commit_reloads_memory_from_db`, `test_held_dossier_settlement_failure_retry_and_reentry_isolation`, `test_player_month_entry_settles_prepushed_edicts_then_world_once` |
| `tests/test_month_chain_1847.py` | `test_midzhi_verdict_and_metadata_roll_back_together`, `test_pending_disclosures_share_commit_boundary_with_effects`, `test_settle_edicts_persists_pending_disclosures_in_same_transaction`, `test_step_4a_crash_recovery_resumes_without_re_running_supply`, `test_step_4a_non_validation_failure_keeps_product_on_retry` |
| `tests/test_month_open_snapshot_1234.py` | `test_capture_before_mutation_on_advance_without_edict`, `test_capture_before_mutation_on_resolve_turn_entry` |
| `tests/test_new_game_write_path_1749.py` | `test_gamesession_load_state_failure_closes_partial_resources`, `test_new_game_construct_failure_keeps_old_writable` |
| `tests/test_new_issues_section_rejections.py` | `test_event_to_issue_insert_exception_propagates`, `test_new_issue_event_pool_insert_exception_propagates`, `test_new_issue_insert_code_exception_propagates` |
| `tests/test_person_archive_schema.py` | `test_old_save_schema_is_upgraded_for_person_archive_fields` |
| `tests/test_pihong_dossier_1490.py` | `test_657_prewrite_failure_zero_db_writes`, `test_657_record_event_choice_failure_rolls_back_batch` |
| `tests/test_power_section_rejections.py` | `test_canonical_person_power_writer_code_exception_is_fail_loud`, `test_power_deltas_code_exception_aborts_settlement` |
| `tests/test_pre_settle_transaction.py` | `test_crash_inside_pre_settle_no_missing_fiscal`, `test_due_secret_order_submission_rolls_back_on_pre_settle_crash`, `test_placeholder_save_crash_rolls_back_settling`, `test_pre_settle_rolls_back_on_seed_issue_failure` |
| `tests/test_qa_1281_issue_audience_case_facts.py` | `test_event_audience_read_failure_escapes_material_preparation` |
| `tests/test_qa_h1_seed_data.py` | `test_deficit_stage_text_aligns_with_opening_treasury_and_hubu` |
| `tests/test_recommendation_edges_635.py` | `test_second_leg_failure_rolls_back_everything` |
| `tests/test_refugee_loop_652.py` | `test_outer_atomic_rolls_back_surcharge_and_absorption` |
| `tests/test_rejection_wiring.py` | `test_inertia_power_move_backlash_rejection_lands_in_reports`, `test_issue_close_power_move_backlash_rejection_is_not_duplicated`, `test_nested_atomic_success_path_does_not_orphan_jsonl`, `test_power_move_backlash_rejection_lands_in_reports`, `test_rollback_leaves_no_rows_and_no_jsonl` |
| `tests/test_relation_brew_636.py` | `test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure`, `test_brew_fn_value_error_is_program_error_propagates_loudly`, `test_brew_program_error_propagates_loudly_not_degraded`, `test_mark_failure_after_llm_failure_propagates_loudly`, `test_prepare_claim_db_error_propagates_loudly` |
| `tests/test_relation_seed_638.py` | `test_seed_founding_write_does_not_swallow_execute_error_with_bad_rollback` |
| `tests/test_rescript_draft_656.py` | `test_generate_rescript_draft_program_error_propagates` |
| `tests/test_secret_order_monthly_progress_566.py` | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` |
| `tests/test_secret_order_payoff_1504.py` | `test_monthly_actual_progress_preserves_selected_fidelity_in_sqlite` |
| `tests/test_section4_rejections.py` | `test_army_deltas_code_exception_aborts_settlement`, `test_create_armies_code_exception_aborts_settlement`, `test_region_deltas_code_exception_aborts_settlement` |
| `tests/test_session_write_queue_1353.py` | `test_wait_pending_writes_fail_loud_on_false_and_exception` |
| `tests/test_settlement_write_guard_393.py` | `test_serialized_web_write_cm_contract` |
| `tests/test_state_reload.py` | `test_atomic_and_reload_chains_reload_failure`, `test_atomic_and_reload_reloads_and_reraises_at_depth0`, `test_atomic_and_reload_runs_on_error_before_reload`, `test_atomic_and_reload_skips_reload_when_nested`, `test_pre_settle_self_reloads_memory_on_rollback`, `test_reload_skipped_inside_nested_atomic`, `test_rollback_purges_content_character_ghost`, `test_rollback_restores_existing_character_attributes` |
| `tests/test_transaction_boundary.py` | `test_atomic_rolls_back_on_error`, `test_atomic_suspends_internal_method_commit`, `test_begin_failure_at_entry_restores_flags`, `test_commit_failure_at_atomic_exit_rolls_back`, `test_commit_failure_in_conn_context_rolls_back`, `test_connection_commit_attempts_all_runtime_callbacks`, `test_connection_context_inside_atomic_rolls_back`, `test_connection_rollback_attempts_all_runtime_callbacks`, `test_ddl_after_explicit_midatomic_rollback_does_not_escape`, `test_ddl_first_inside_atomic_rolls_back`, `test_nested_atomic_inner_commit_held_outer_rolls_back`, `test_nested_atomic_inner_error_rolls_back_at_outer` |

## 自验与变异证据

所有测试与变异均使用七个 false BIN，未写真席位表、宿主配置或安装：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
 MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
 MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
export PYTHONDONTWRITEBYTECODE=1
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
 $(git diff 7c52adc06 --name-only -- 'tests/test_*.py') \
 tests/test_urge_lever_624.py tests/test_breach_plea_623.py
```

主体触及面：**1663 passed, 2 skipped, 1 warning / 54.24s**，退出 0，`/tmp/1889-focus-final2.log`。其后将 todo 查询条件构造一起收进 owner（不让调用者传 SQL fragment），`rg -l 'list_next_audience_todos|mark_next_audience_todo_status|insert_next_audience_todo' tests --glob 'test_*.py'` 定位文件聚焦：229 passed / 3.55s，`/tmp/1889-todo-owner-final.log`。最后删除失效 FieldSpec/catalog 长度元数据：executor_routing_721、manual_directive_institution_normalize_1279、manual_directive_locality_1685、cli_backend 四文件聚焦 183 passed / 2.07s，`/tmp/1889-catalog-final.log`。两次追加验证均同七变量、`-q -p no:cacheprovider`、退出 0；不是再次跑全量。warning 是既有 Starlette/httpx 弃用警告。中途修复了 origin tags 解码回归及 callback cause 识别；J3 扩扫后发现三个财政入口错误包契约，修的是生产复用 marker，不放松这些测试。一次误写旧测试文件号的命令退出 4、未跑测试，随后改正确文件号；不记作通过。

Python 全部 `ming_sim` / `tests` **351 文件 AST parse 通过**，`git diff --check` 通过。本片无 TypeScript 改动；仓内未声明 Python typecheck 命令，不把 AST 解析冒称静态类型检查。没有跑全量或真实模型验收。

变异命令：七变量前缀下 `../Ming_LLM/.venv/bin/python /tmp/1889-mutations.py J3`（或 J4、J7）。仅在测试进程替换函数并 finally 恢复，无工作树改写：

| 类 | 装回旧行为的真实入口结果 | 恢复后 |
|---|---|---|
| J3 | 从冻结提交取旧 _apply_fiscal_levy_targets；原历史饷率入口坏 _meta/land 两案 `DID NOT RAISE`，2 failed / 1.73s，退出 1。日志 `/tmp/1889-mutation-J3.log` | 当前坏形四参数及 JSON 损坏、修复后重算、三个前半段错误包入口均绿，纳入最终 1663 案 |
| J4 | 将 atomic_and_reload 原异常替换成同类型 replacement failure；原异常/cause 既有入口 1 failed / 0.56s，退出 1。日志 `/tmp/1889-mutation-J4.log` | 原异常与 reload cause 识别绿 |
| J7 | 装回 record_actual_progress note[:240]；原密令执行入口完整 note 持久化案 1 failed / 1.00s，退出 1。日志 `/tmp/1889-mutation-J7.log` | 包含长 note 与首尾空白的完整原值等式绿 |

## 复杂度、必要成本与合法性

- 没有新增证明性测试：复用故障、财政和完整载荷既有案；财政参数新增空数组/null 是现有直接饷率入口此前未覆盖的 falsy 坏形，必要成本两参数，非平行测试。没有删除有效失败路径或 mock 被测行为。
- 无生产锁/重试/恢复层/通用查询框架/串行 LLM。SQL 主要是既有语句移入事实 owner，平行读口与合计旧补偿删除；八类全仓派单不可按样本收窄，故改动超过 400 行。测试识别多为单行恢复，正文保真多为删除 strip/slice，不是新增业务策略。
- 唯一测试技术缝 InlineExecutor：仓内搜索 `class .*Executor|Future\(|set_result\(`，已有 _DeferredExecutor 专门保留未执行任务、不能用于即时 canned 投影；复用标准库 Future 的 result/exception 契约，不手造 Future。pytest monkeypatch 负责替换外部调度缝，不需新包。官方复核 https://docs.python.org/3/library/concurrent.futures.html（本局下载 `/tmp/1889-futures-official.html`）；无新增通用 runtime 件。
- 本轮八类处置已完成，保留项依据见逐类栏；无需 owner 新设计决定。独立 forward commit，不 amend、不改历史、不 push、不建 PR。真实宿主与模型验收留给调用者，不以施工期真实调用补证。
