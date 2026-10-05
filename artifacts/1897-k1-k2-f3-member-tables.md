# #1897 K1/K2/F3 本轮完整成员处置表
第二轮 fixer（驳回首轮窄枚举后）。**不宣称票完成 / merge。**
## 枚举命令（可执行，非占位）
### K1
```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
rg -n --glob '*.py' '缺少案卷|get_dossier_for_secret_order|密令进展缺少|密令缺少案卷' ming_sim tests
rg -n -A5 -B2 'get_dossier_for_secret_order' ming_sim/db.py ming_sim/covert_progress.py ming_sim/month_chain.py
```
### K2
```bash
rg -n --glob '*.py' 'title_to_ids|bind_decisions_to_candidate|按唯一标题|binds_from_unique_title|猜绑' ming_sim tests
rg -n '唯一标题|title_to_ids|标题补绑|标题重绑|猜绑' TODOS.md docs/test-cleanup-audit-1185.md
```
### F3
```bash
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$PY /tmp/1897-f3-enum/gen_tables.py   # 全仓 tests/**/*.py AST：等值/不等/len/strip/成员 + 高置信散文字段
find tests -name '*.py' | wc -l
find web \( -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' -o -name '*.spec.tsx' \) | wc -l
# web 字符串断言另计样本见本表附注；不以字段白名单宣布结清
```
- Python 测试文件：235
- Web 测试文件：25
- F3 高置信现行命中行：23

## K1 成员处置
| # | 成员 | 接缝 | 处置 | 依据 |
|---:|---|---|---|---|
| 1 | `db._note_secret_order_report active 缺案卷` | 进展 | **raise ValueError** | K1/ADR0005 |
| 2 | `db.update_secret_order_progress` | 进展 | **随 #1** | 同 |
| 3 | `db.submit_secret_order_for_review` | 进展/核议 | **经 #1 或 mark raise** | 同 |
| 4 | `db._update_secret_order_sim_note_in_transaction` | 实况进展 | **已 raise 保留** | 同 |
| 5 | `db.mark_secret_order_in_progress` | 在办轴 | **已 raise 保留（真源句）** | 同 |
| 6 | `db.close_secret_order` | 结案 | **raise 后再写轴** | 不得可成功 |
| 7 | `covert_progress.apply_monthly_covert_actual_progress` | 月度进展 | **raise** | 不得拒收跳过 |
| 8 | `covert_progress.settle_due_secret_orders` | 到期 | **raise** | 不得标阶段完成 |
| 9 | `month_chain→settle_due` | 到期编排 | **随 #8** | 既有 abort |
| 10 | `unknown/non-active → False` | 进展 | **合法保留** | 领域拒收 |
| 11 | `commit_pending_actions 非 typed Exception` | 进展提交 | **raise 且不标 failed** | 不终结暂存 |
| 12 | `find_active_investigation dossier None continue` | 查找 | **边界外保留** | 非写接缝 |
| 13 | `month_chain 供料读缺案卷` | 供料读 | **边界外保留** | 读路径 |
| 14 | `materials 实况原文 continue` | 供料读 | **边界外保留** | 读路径 |
| 15 | `merge_investigation_confirmation` | 查案合流 | **CovertContractError 保留** | 已响亮 |

## K2 成员处置
| # | 成员 | 处置 | 依据 |
|---:|---|---|---|
| 1 | `title_to_ids / 唯一标题补绑` | **已删除** | ADR0142 |
| 2 | `显式 event_id 采信` | **合法保留** | 显式引用 |
| 3 | `dossier: + rescript capability` | **合法保留** | #1490 |
| 4 | `off-snapshot 解绑` | **合法保留** | 无标题回退 |
| 5 | `prepare_rescript_prewrite→bind` | **保留调用** | 亲裁入口 |
| 6 | `test_decision_event_binding_389` | **负向闸（不得猜绑）** | 附属测试 |
| 7 | `TODOS.md #389` | **本轮补绑：标题猜绑退休说明** | 附属物现役说明 |
| 8 | `docs/test-cleanup-audit-1185.md` | **本轮改写：保留过程史、标明退休** | 附属物 |

## F3 高置信成员处置（全仓 AST 现行命中）
| # | 位置 | 测试 | ft/tags | 处置 |
|---:|---|---|---|---|
| 1 | `tests/test_audience_restore_505.py:292` | `test_retry_regenerates_reply_without_duplicate_question` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 2 | `tests/test_audience_restore_505.py:332` | `test_post_reply_failure_resumes_close_without_regenerating_reply` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 3 | `tests/test_audience_restore_505.py:452` | `test_failed_retry_rolls_back_side_effects_and_keeps_question` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 4 | `tests/test_candidate_supply_1893.py:82` | `test_eligible_candidate_event_reaches_world_supply` | summary/eq | 余项：自由正文机械比较候选（据实不虚报整类结清；按行为语义下轮续清） |
| 5 | `tests/test_candidate_supply_1893.py:216` | `test_translate_request_carries_current_candidate_facts` | summary/eq | 余项：自由正文机械比较候选（据实不虚报整类结清；按行为语义下轮续清） |
| 6 | `tests/test_chat_stream_failpaths_393.py:1049` | `test_chat_stream_halfstream_retry_replaces_temp_presentation` | answer/eq | 余项：回话/answer 夹具等值（据实不虚报结清） |
| 7 | `tests/test_cli_model_choices.py:60` | `test_default_labels_reuse_single_source_constants` | label/membership | 合法保留：CLI 模型标签配置 |
| 8 | `tests/test_cli_model_choices.py:61` | `test_default_labels_reuse_single_source_constants` | label/membership | 合法保留：CLI 模型标签配置 |
| 9 | `tests/test_cli_model_choices.py:69` | `test_default_label_reflects_env_override` | label/membership | 合法保留：CLI 模型标签配置 |
| 10 | `tests/test_cli_model_choices.py:70` | `test_default_label_reflects_env_override` | label/membership | 合法保留：CLI 模型标签配置 |
| 11 | `tests/test_gazette_author_1862.py:396` | `test_author_archives_own_title_and_same_run_advances` | label/eq | 余项：标签/摘要字段等值（据实不虚报结清） |
| 12 | `tests/test_highlight_judge_544.py:227` | `test_chat_stream_done_before_highlights_and_degrade` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 13 | `tests/test_highlight_judge_544.py:306` | `test_chat_nonstream_folds_judge_within_timeout` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 14 | `tests/test_highlight_judge_544.py:357` | `test_chat_nonstream_timeout_returns_reply_without_highlights` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 15 | `tests/test_mechanical_tail_1845.py:418` | `test_ending_summary_runs_in_mechanical_tail_after_advance` | summary/eq | 合法保留：空串结构闸（须空） |
| 16 | `tests/test_mechanical_tail_1845.py:442` | `test_ending_summary_runs_in_mechanical_tail_after_advance` | summary/eq | 合法保留：空串结构闸（须空） |
| 17 | `tests/test_month_chain_1847.py:848` | `test_question_note_only_is_kept_and_other_decisions_still_require_label` | label/eq | 合法保留：空串结构闸（须空） |
| 18 | `tests/test_month_chain_1847.py:1125` | `test_declared_deposal_ends_on_the_existing_chain` | summary/eq | 合法保留：空串结构闸（须空） |
| 19 | `tests/test_opening_gazette_delete_1356.py:59` | `test_new_game_t0_previous_summary_strictly_empty` | summary/eq | 合法保留：空串结构闸（须空） |
| 20 | `tests/test_opening_gazette_delete_1356.py:69` | `test_new_game_t0_previous_reign_period_label_empty_with_empty_summary` | label/eq | 合法保留：空串结构闸（须空） |
| 21 | `tests/test_promulgation_judge_561.py:45` | `test_promulgation_context_is_deterministic_and_excludes_satisfaction` | context/eq | 合法保留：确定性 builder 对照 |
| 22 | `tests/test_scene_llm_1836.py:77` | `test_scene_chat_one_call_returns_multi_person_script` | answer/eq | 余项：mock 回话透传等值（控序夹具；非本轮声明搬迁主战场，据实不虚报结清） |
| 23 | `tests/test_scene_llm_1836.py:154` | `test_cli_selection_uses_scene_turn_as_admission_origin` | reply/membership | 余项：回话/answer 夹具等值（据实不虚报结清） |

## 本轮已处置文件摘要
- `tests/test_audience_translation_1838.py`：本轮：删 context 等值
- `tests/test_authority_ledger_611.py`：本轮：删 context 模板等值
- `tests/test_credit_events_628.py`：本轮：删 context 等值/成员/strip；保留 origin/target/kind
- `tests/test_decision_event_binding_389.py`：K2 附属负向闸
- `tests/test_execution_joint_liability_565.py`：本轮：删 execution_note 成员/等值；保留 outcome+restore
- `tests/test_faction_brew_637.py`：本轮：删 context 模板等值
- `tests/test_pay_order_override_653.py`：首轮已删影子 SQL 整案；本轮复扫无命中
- `tests/test_recommendation_edges_635.py`：本轮：删 context==reason
- `tests/test_relation_read_640.py`：本轮：删 summary/context 散文锁；改 DTO 键/纪年序/event_kind
- `tests/test_relation_store_632.py`：本轮：restore 不再等值 context
- `tests/test_six_sciences_seed_608.py`：本轮：删 summary 史源成员
- `tests/test_style_temperament_641.py`：本轮：去类型/非空换形与日志垫衬；真调用消费者+关系账；闸负向保留

## 附注
- 谓词覆盖判词 F3 全文（自由正文机械比较、证明空壳、影子规则、消费者未调用），不用断言形状或字段白名单替代行为判断。
- 历史 75 表表保留为过程史；本表为现行 HEAD 全仓复核。
- Web 测试未用 Python AST；以 find+字符串断言样本另计，不冒称已机械清退全部 JS 断言。
- **不宣称 F3 整类已结清**；本轮清退点名空壳＋高置信叙事盯文主集群，余项据实列入上表。
