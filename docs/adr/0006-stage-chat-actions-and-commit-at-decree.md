# 结构化聊天动作暂存、颁诏批量落库

Status: accepted

细化 [ADR 0002](0002-use-action-candidates-instead-of-tool-calls-as-game-rules.md)。0002 定了「聊天写动作先成动作候选、过确认闸门才改游戏状态」，但没定确认闸门的形态。实践发现：对**话说明确**的命令（「内库再给你一百万两，速速去办」）逐条点「准」是画蛇添足；而让结构化动作直写真实表、再靠快照式「撤回召对」回退，机制复杂且只能撤最后一轮、颁诏后失效。因此对密令、任命、后宫这类**结构化**聊天写动作，采用「召对期进暂存、颁诏时批量落库」的提交模型，确认闸门 = **颁诏批量同意**（不拒绝即允许）；拟旨这类叙事诏书继续走显式准/驳。

## Considered Options

- 逐条确认闸门（每个动作点准/驳）：最稳，但对明确命令是多余摩擦，伤体验。
- 乐观直写 + 撤回召对 undo：保留现有直写，但撤回靠前后快照差异还原，只能撤全局最后一轮、颁诏后不可撤，且「未颁诏草案广播给所有大臣」是 roleplay 硬伤。
- 暂存 + 颁诏批量同意：结构化动作召对期写 `pending_actions` 暂存表、不动真实表；颁诏（`resolve_turn` 最前）`commit_pending_actions` 一次性落库。撤回 = 删暂存行（任意一条、免快照）；颁诏即同意。多一层暂存与一处提交逻辑，但撤回免费、和拟旨「draft→颁诏」节律统一、明确命令零摩擦。

## Consequences

- **落地机制按数据性质分**：密令/任命/后宫是结构化记录，颁诏时 `commit_pending_actions` **直接 INSERT/UPDATE 真实表**；拟旨是叙事诏书，继续走 simulator→extractor→`apply_score_extraction`。不强求统一（保留口子，见 docs/TODO.md T7：理由不足则后续统一）。
- **提交时机**：`commit_pending_actions` 在 `resolve_turn` 最前、跑 LLM 结算管线之前执行——**先提交再结算**，使 simulator/extractor 读到的盘面与旧「召对期直写」时序一致，不破坏邸报连贯；幂等（落库即标 committed，HITL phase2 resume 不重跑）。
- **可见性**：暂存动作对话之外的大臣**看不到**（皇帝 UI 可见以供复核/撤回，对话中的大臣靠对话记忆）。不依赖、不扩展现有 `build_draft_line` 广播（该广播本身的去留是独立问题，见 docs/TODO.md T6）。
- **暂存内冲突**：新建实体颁诏前编辑 = upsert 同一暂存行（面板一条草稿）；对已落库旧实体的操作（更新/催办/提交核议/记进展）= 各自一行、颁诏时按 id 序 apply（保操作语义）。
- **决策即落库（CLAUDE.md P1 铁律）仍满足**：暂存表是真实 DB 表，待确认动作落在 `pending_actions`，context 压缩后 restore 仍可无损接续。
- **颁诏后反悔**不是 undo，是新的游戏内命令（有代价），照局势 `cancellable=decree`+`cancel_cost` 范式，属本 ADR 范围外（见 docs/TODO.md T5）。
