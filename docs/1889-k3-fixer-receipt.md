# #1889 K3 修内司重交回执

- 派单：`/Users/akagilnc/.ak-roles/books/Ming_LLM/1889/runs/01a10858-3646-7193-a4b4-8f1007247730@fixer/fix-packet.md`
- 本轮 continue 判词原文：`/tmp/1889-k3-continue-verdict.json`。
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`；分支：`ak-roles/1889-k3-text-contracts`。
- 本轮基线：`fe70b4db7`。前轮处置及测试记录可用 `git show fe70b4db7:docs/1889-k3-fixer-receipt.md` 核对。
- 本回执是施工证据，不另立 authority。修内司建立新提交；不 amend、不 stash、不 push、不建 PR。

## 根因与更正

前轮把宽候选枚举及启发式保留冒称全类核尽，结论不成立；遗漏生产 prompt、文档正文、生产结果和报错文案。撤销前轮「无其它漏项」结论。

本轮仍只处置 K3：生产 prompt/docs 正文、生产结果/报错、材料标题、内部标签、拼装 context 和种子叙事的非契约文案依赖。保留机器字段/枚举/路径、实体身份、同案注入保真、注入失败传播及现役拒收/保密负向。

撤销 `/tmp/1889-k3-file-ledger*.json` 的全 KEEP 结论；`VERIFIED_KEEP_BASIS.txt` 常只取比较中的字段键，不能证明实际值合法。自建分类/openbook 脚本已移至 `/tmp/1889-k3-nav-scripts-20261005052452/`，不进提交。仅复用已存在的标准 AST 候选枚举，不增加生产机制、兼容入口或证明测试。

## 枚举与复扫

```sh
python3 scripts/1889_k3_enumerate.py
```

范围为全仓 git 跟踪的 Python 测试及辅助文件、JS/TS test/spec 文件。枚举所有 Assert/Compare（包括变量、多行和嵌套列表/字典），raises match、字符串操作、pass，以及 TS expect/DOM/string 选择。扫描失败抛出；输出仅是冻结源码候选，不是运行时护栏，也不是自动分类裁决。

基线输出：255 文件，Python 26396、JS/TS 3913、总候选 30309。

来源导航采用完整谓词及所属函数，追到输入 Assign/Raise/helper 或生产定义；不以短字串、ASCII、同函数任意 Call、source-window 或第一个字段键判 KEEP。诊断消息、SQL 和 schema 键不是文案值依赖，按方法归类，不重复立账。英文、中文、prompt 分段选择、docs 读取、完整字典/列表、context/status/summary/title/result 与报错 match 均在复核范围。

修后实际输出：255 文件，Python 26337、JS/TS 3913、总候选 30250；Compare 13251、Assert 12496、raises_match 90、pass 44。

完整临时路径：`/var/folders/nb/ml2z6k013psg7rdtt0t6g91m0000gn/T/1889-k3-enum-c3_2vyaa/candidates.jsonl`。

候选数量不等于 finding 数量，亦不作为「类净」证明。处置全集如下，行号相对 `fe70b4db7`，函数名可直接定位；保留依据另列。

## 本轮成员表

### prompt/docs、结果/报错、标题与 context

| 文件（tests/ 下） | 修前行 / 函数 | 处置 |
|---|---|---|
| test_pay_order_override_extraction_653.py | 49、50、52 / test_single_pay_order_capture_grounds_relative_deadline_at_current_turn | 删除相对期限整句、until_turn 人话公式负向及默认优先级整句；保留机器标识及落账期限结果 |
| test_surcharge_causal_chain_650.py | 85–92 / test_surcharge_schema_only_teaches_effect_eligible_dossiers | 删除整条 docs 章节切片/文案用例及失效 Path import；保留真实加派落账案 |
| test_secret_order_monthly_progress_566.py | 183 / test_character_terminal_status_closes_secret_orders_through_canonical_progress_rail | 删除「人物终态：dead；途中病故」；保留 order/dossier/progress 状态 |
| test_decree_dossiers_571.py | 1112、1175 / 两个 manual_directive_capture_rejects 用例 | 删除 HTTP detail「参与人」；保留 409、异常类型与零写入 |
| test_decree_dossiers_571.py | 995–996 / test_manual_directive_capture_reaches_structured_dossier | 删除「【皇帝】」「【大臣回话】」分段及「请据此拟旨」闸；保留注入 directive_text 的传入检查 |
| test_decree_dossiers_571.py | 1297–1298 / test_cli_edit_replaces_text_and_mechanics_before_promulgation | 同上，保留 revised_text 保真 |
| test_manual_directive_institution_normalize_1279.py | 42–43 / _mock_draft_intent.backend | 同上，保留 text 保真与名册机制 |
| test_recommendations.py | 283 / test_listed_heard_for_selection_candidate_stays_recovery_type_through_context_and_restore | 删除 brief「荐起复」及失效 import；保留 candidate_kind、验证与重载 |
| test_month_chain_1847.py | 828、863 / test_question_note_only_is_kept_and_other_decisions_still_require_label | 报错「选项不在当前 options」改为 ValueError 类型；保留 staged questions / pending |
| test_material_directory_1830.py | 227 / test_read_material_stays_inside_directory | 删除「无法读取：」；保留 FileNotFoundError 与注入正文不泄漏 |
| test_fiscal_tick.py | 149 / test_fiscal_fail_loud；RAISE_CASES | 删除报错子串比较和 35 条案例的失效 msg 列；保留原 name/st/p/actions 与 ValueError 负向输入全集 |
| test_audience_scroll_539.py | 265、267 / test_real_http_scroll_merges_ministers_asides_and_story_without_raw_character_stats | 删除未注入的作保/雨声文案负向；保留注入对话及 DTO 字段边界 |
| test_audience_scroll_539.py | 359–360 / test_extractor_open_tags_do_not_drive_beat_or_soft_boundary | 删除未注入的入殿/告退旧事文案负向；保留 beat/divider 负向 |
| test_audience_scroll_539.py | 457–459 / test_closed_night_archive_derives_stable_titles_people_and_no_content | 删除整组拼装档案 title；保留 night_id、audience_type、people 与正文边界 |
| test_audience_travel_gating_670.py | 295、309 / test_multi_origin_same_person_dedupes_consumer_projections_not_ledger | 两处整字典移除 required_fact「抵原地后续赴京」全文锁；保留身份、目的地、origin、entry 及字段类型 |
| test_audience_travel_gating_670.py | 821 / test_continuation_arrival_settles_origin_without_waiting | 同上，保留后续抵达/结清行为 |
| test_authority_ledger_611.py | 141 / test_production_path_grant_restore_revoke_impression_tracer | 删除「收权·罢差·便宜行事·…」context；保留 origin 与实际 privilege/scope |
| test_faction_brew_637.py | 463 / test_authority_revoke_edge_reaches_holder_faction_with_emperor_target | 同上；保留酿制选对及关联身份 |
| test_llm_channel_config.py | 473、499、538 / 三个 test_verify_llm_available 用例 | 删除「输出 ok」整句锁；保留 prompt 有效输入、路由与配置结果 |
| test_opening_gazette_delete_1356.py | 73–74、109 / 两个 t0 previous-summary 用例 | 删除已空 label 上重复的「九月」「天启」负向；保留空态契约 |
| test_pre_settle_transaction.py | 113 / test_due_secret_order_submission_rolls_back_on_pre_settle_crash | 生产「[期限届满]」前缀负向改为回滚前后 result 原值相等；保留 active 及真实崩溃路径 |
| test_relation_seed_638.py | 170–171 / test_seeded_pair_flows_into_month_end_brew_selection | 删除「二十四大罪」context 锁及 contexts 夹具；对已有 pair_events 与真实 collect_new_edge_events 的事件 id 检查包含关系 |
| test_relation_seed_638.py | 353 / test_reverse_chronological_seed_keeps_latest_event_readable | 删除「后事。（天启六年二月）」拼装全文锁；保留注入 context 前缀及独立纪年值 |
| test_gazette_author_1862.py | 369 / test_author_archives_own_title_and_same_run_advances | 删除「密令账」标题负向；保留全部注入 _SECRET_* 和 SECRET_LEDGER 隔离 |
| test_fiscal_substrate_bridge.py | 115 / test_seed_royal_stipends_use_wanli_accounting_by_province | 删除 source 说明全文锁；保留字段存在与 conversion/items 数值 |
| test_fiscal_substrate_bridge.py | 4455 / test_jiangnan_core_uses_wanli_huiji_lu_primary_seed | 删除 source.title 人话锁；保留 source 结构、chapter/scan_checked/财政数值 |

### fact-brief 内部 detail 标签（test_pay_order_override_653.py）

复用一个测试侧结构查询 `_fact_brief_entries`，不增加生产机制。NewDebt/Repaid 从 origin_ref 指向的 region_logs.field 读取机器记号，不以按正负过滤再断言正负制造循环证明；保留具体数值及归因结果。

| 修前行 / 函数 | 全部原谓词与处置 |
|---|---|
| 661–663 / test_f23_region_logs_flow_sign_domain_repaid_negative | 省池_、_Repaid、_NewDebt 三个标签过滤 → region_logs 来源、科目及真实 field；保留两种符号断言 |
| 704 / test_fact_brief_levy_uses_civil_arrears_breakdown_relation | 删除「三饷加派净额」；保留 levy 数值及被替代公式反例 |
| 742、752–753 / test_fact_brief_attributes_priority_displacement_to_dossier | 本次与重开两处「旨序让位_」过滤 → metric/class/region/origin；保留 value 与重开结果 |
| 867、869–871、874–875 / test_fact_brief_attributes_arrears_order_displacement_to_dossier | 「旧欠序让位_」过滤及整 tuple 标签、另一「旨序让位_」负向 → 官僚/军户、origin；保留 1.93 与零混入 |
| 904 / test_fact_brief_priority_provenance_falls_back_to_nationwide_scope | 「旨序让位_军饷」→ 结构化来源选择；保留唯一性与 nationwide dossier |
| 928 / test_fact_brief_priority_provenance_prefers_winning_scoped_over_later_nationwide | 同上；保留 scoped dossier |
| 975 / test_fact_brief_arrears_provenance_prefers_winning_scoped_over_nationwide | 「旧欠序让位_官俸欠」→ 结构化来源选择 |
| 999 / test_fact_brief_priority_provenance_ignores_later_noncausal_dossier | 「旨序让位_军饷」→ 结构化来源；保留 causal dossier |
| 1048–1053、1066 / test_fiscal_fact_brief_haircut_and_relief_facts | 「折发_」「折发_军饷#central」「补发_」过滤 → metric/class/origin 与军队身份；保留实值方向 |
| 1414 / test_fact_brief_zero_need_army_region_attribution_not_gated | 「省源偿欠」→ army_logs 来源；保留 -3 与属地 |
| 1443 / test_fact_brief_central_haircut_floor_per_army_matches_real_accounting | 「折发_军饷#central」→ dossier/class/metric；保留实际 floor 数值 |
| 1467 / test_fact_brief_unmet_relief_is_current_turn_damage | 「赈济未敷」→ region:shaanxi:settle.st.unmet_relief 机器指针；保留 5 与农民受损 |
| 1489 / test_fact_brief_province_auto_repaied_is_beneficiary_fact | 「省源偿欠」→ army_logs 来源；保留 -6 与属地 |
| 1625–1632 / test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e | 省池_过滤、_NewDebt/_Repaid 文案后缀判符号、detail/value 集合预期 → 原始日志机器 flow、affected_class/value；保留来源、window 与存读保真 |

## 保留依据与自检

- 653 的 `陕西=@shaanxi`、`"duration_months":3` 是机器标识，末判明确可留。
- `test_world_materials_1834.py:75` 的「历月邸报正文」由同函数 `save_turn_report(..., body, title="辽东告急")` 注入；INDEX 保标题、不含正文是实际公私/供料边界，不是标题文案锁。
- error_pack、中文/英文 raises match 均追到测试注入失败；不把生产报错正文保留为失败契约。
- _SECRET_*、SECRET_LEDGER、用户对话与急务 title 追到同案注入；保留其读写/隔离结果。
- 纯纪年是 `tests/test_reign_period_label.py` 的机器格式契约。撤销施工中对 relation_read/seed 独立日期预期改成同一生产 helper 的变更，避免同源 oracle；只有 appended context 全文被删。
- 财政科目、动作、状态、路径/schema 键和实体身份不因中文而归盯文；也不因短串/ASCII 自动放行。
- 已删旧物随删：docs 用例 import、RAISE_CASES msg、brief import、context 夹具及重复标题观察。没有新增测试用例或为删除换形造证明。

## 验证（七个 false BIN）

所有游戏导入/测试命令均设置：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
PY=../Ming_LLM/.venv/bin/python
```

### 修内司核验：本轮变更文件聚焦（非全仓 suite）

```sh
/usr/bin/time -p "$PY" -m pytest -q -p no:cacheprovider --tb=line \
  $(git diff --name-only fe70b4db7 -- tests) \
  > /tmp/1889-k3-final-focused.out 2>&1
```

实际：`29 failed, 697 passed, 1 skipped, 1 warning in 34.70s`；`real 36.41`，exit 1。

原始输出完整保留。29 个失败的根部为：3 个 list_closed_night_archives 缺失、12 个 knowledge_items_for_turn 缺失、13 个 list_supervision_history 缺失，以及 1 个期望注入异常但先遇 list_supervision_history 的失败；部分包装为 SettlementAbort。未靠改负向契约、恢复退役包装或补功能将它们洗绿。skip 为 saved_game 缺 gitignored data/probe.db。判词明定功能红灯不作为本切片门槛。

此轮未改 Web 测试，未重跑 Web 或全仓 suite。

### 保留独立纪年契约核验

```sh
/usr/bin/time -p "$PY" -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_relation_seed_638.py::test_fresh_seed_summary_is_readable_with_seed_event_clock \
  tests/test_relation_seed_638.py::test_reverse_chronological_seed_keeps_latest_event_readable \
  tests/test_relation_seed_638.py::test_pre_tianqi_seed_event_projects_honest_calendar_label \
  tests/test_relation_read_640.py::test_updated_at_period_is_era_label_not_bare_turn
```

实际：`4 passed in 2.58s`，`real 3.55`。

中间各轮已有测量原样留存，不充最终全绿证据：`/tmp/1889-k3-continue-pytest.out`（67绿/2红）、`/tmp/1889-k3-quality-full-touch.out`（414绿/21红）、`/tmp/1889-k3-honest-focus-prior.out`（100绿/1红）、`/tmp/1889-k3-honest-focus.out`（2绿/2红）、`/tmp/1889-k3-honest-trace/pytest-b3-touch.out`（2绿/1跳过）、`pytest-b4-seed-title-touch.out`（7绿/1红）。

## 交卷结论

末判点名及本轮自扫发现的 K3 同类均已按成员表处理；生产零改动。保留输入保真、机器契约和现役负向。不以候选数量或启发式 KEEP 宣告收敛，不署已合并/关票；提交后再由庭审裁断。功能缺口及缺档 skip 原样留存。
