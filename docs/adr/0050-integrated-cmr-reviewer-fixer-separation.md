# Integrated CMR reviewer / fixer separation

Status: Proposed

Current authority: ADR 0131 定义 Runner 三通道，#869 定义现行接力拓扑。本 ADR 只保留 reviewer / fixer 角色分离与 fresh re-review 决策。

Integrated completeness/correctness workers are reviewer workers over the assembled delivery base, whether that base is a single slice branch or a family base. They may gather review evidence, run the needed tests, and summarize or adjudicate the raw prose from fresh legs dispatched only by the Runner, but they must not dispatch legs or repair blocking findings themselves. They write findings state under their versioned authority and submit only a judge typed tri-state or an active decision gate; every intermediate repair, verification, finalization, and re-review transition is owned only by #869. A fresh originating CMR reviewer always reviews the current full diff.

Scope: this decision applies to integrated CMR passes in the shared tail for both single and family delivery. It does not reopen the per-slice coder/reviewer/fixer separation already decided by 0030.

## Why

Issue #258 dogfood showed the failure mode clearly: an integrated CMR worker found correctness issues and then moved into a same-session fix loop before all review legs had completed. That is fast when the finding is cheap, but it hides the review -> fix -> re-review state machine inside one agent context, erases the independent reviewer/coder boundary, and makes ledger/resume evidence too weak.

Professional workers inspect commits, tests, and repair evidence. The Runner is not a semantic judge; it only handles ADR 0131's exit code, judge typed tri-state, or worker-raised decision gate.

## Decision

- CMR workers stop at findings, raw review evidence, and relevant test logs.
- Integrated reviewer Action 提交 judge typed tri-state 后，Runner 只按 #869 固定拓扑接力；本 ADR 不保存任何中间顺序，Runner 不读取 finding 内容。
- Finding Repair Action 完成修复或逐条证伪并执行 same-class scan 与 introduced-regression check 后停止，不自行提交、复审或推进流程。
- The fixer updates the corresponding finding as fixed or refuted; only a fresh originating reviewer may confirm closure or reopen it.
- Fresh CMR re-review always reviews the current full diff. It must not only check whether the last finding appears closed.

## Tradeoff

Rejected alternative: let CMR workers fix cheap same-module findings themselves. That reduces orchestration overhead, but it recreates the exact class of hidden self-fix loops the orchestrator exists to prevent. The chosen design spends extra worker launches and findings state store entries to preserve role separation, auditability, resumability, and independent review.

## Consequences

- Reviewer workers, including CMR pass workers, must be treated as read/review producers, not persistent fixers.
- Commits, tests, review artifacts, and repair evidence are materials for the next professional worker, not runner gates.
