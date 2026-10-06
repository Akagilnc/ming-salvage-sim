#1834 F21/F22 r3 成员表

## F21 自由正文搬运链裁字（补交反馈外壳嵌原旨）
| 成员 | 处置 |
|---|---|
| `extract_draft_intent` correction_block=`str(...).strip()` | FIX：判空与传输值分离；raw_correction 保真，仅空则空块 |
| `build_draft_admission_resubmit_feedback` 嵌原旨 | KEEP 已保原文；空检用 strip 副本 |
| `resubmit_draft_admission_payload` / `initial_correction` 过手 | KEEP 不 strip |
| `build_participant_correction_feedback` roster_facts | KEEP 名册机器事实，非自由正文旨文 |
| `_narrative_context` / title_c 写入 | KEEP 上轮已修 |
| 机器键/闭集/env/path strip | KEEP 非自由正文 |

## F22 退役旧模式及专属测试
| 成员 | 处置 |
|---|---|
| `extract_draft_intent` 参数 draft_count/has_pending_draft/existing_draft_text/existing_candidates/harvest_participants | DELETE |
| 多道 `draft_count>1` / 成品旨稿批抽分支 | DELETE |
| 候选/补充模式（existing_candidates/合并草案/目标草案） | DELETE |
| `require_execution_lead` + `_lead_gate` + harvest 注入 | DELETE |
| `MissingExecutionLeadError` / `_extract_result_has_execution_lead` / `_missing_execution_lead_feedback` / `_participant_fields_from_draft_obj` | DELETE |
| 共享 combo/roster 多道 `drafts`/`draft_combo_flags`/`draft_failures` 闭包 | DELETE |
| `StructuredDecreeCombinationError.draft_failures` | DELETE |
| `test_batch_draft_extraction_preserves_each_mechanical_payload` | DELETE |
| `test_multi_pay_order_capture_preserves_reverse_non_tied_priorities` | DELETE |
| `test_batch_combo_correction_real_wrapper` | DELETE |
| `test_draft_extraction_does_not_capture_acting_appointment` 多道参数 | 收窄为单道 KEEP |
| 现役单道 extract / capture / resubmit / combo+roster heal | KEEP |
| `require_execution_lead_or_raise`（executor_routing 现役路由） | KEEP 非本旧模式 |
