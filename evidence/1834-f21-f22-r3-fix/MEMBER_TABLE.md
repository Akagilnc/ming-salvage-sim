#1834 F21/F22 r3 成员表

## F21 自由正文搬运链裁字（补交反馈外壳嵌原旨）
类定义：共享搬运/供料接缝对自由正文裁剪后作为传输或写入值；嵌入反馈外壳后的模型供料同属此类。判空与传输值分离。

| 成员 | 处置 |
|---|---|
| `extract_draft_intent` `correction_block=str(...).strip()` | FIX：判空与传输分离；`raw_correction` 保真 |
| `build_participant_correction_feedback` roster_facts strip→反馈块 | FIX：同模式保真 |
| `_existing_draft_text` strip 供料 | DELETE（随 F22 补充模式退役） |
| `candidates_context` `[:40]` 截候选正文 | DELETE（随 F22 多候选模式退役） |
| `合并草案` strip→`merged` | DELETE（随 F22 补充/合并模式退役） |
| `build_draft_admission_resubmit_feedback` 嵌原旨 | KEEP 已保原文；空检用 strip 副本 |
| `resubmit` / `initial_correction` 过手 | KEEP 不 strip |
| `_narrative_context` / `title_c` 写入 | KEEP 上轮已修 |
| `reason_code[:40]` / env/path / 闭集键 | KEEP 机器键非自由正文 |
| 空检门（`if not x.strip()` / `x if x.strip() else y`） | KEEP 判空合法 |

## F22 退役旧模式及专属测试
类定义：被替代旧模式参数/分支/独占辅助及专属测试仍藏在现役共享定义；共享校验/名册纠错多道专属按依赖闭包处置。

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
