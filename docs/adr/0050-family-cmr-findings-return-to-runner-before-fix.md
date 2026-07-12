# Family CMR findings return to runner before fixes

Status: Accepted (#533/#553, 2026-07-03)

Revised by: ADR 0129（findings 改由状态库行状态流转；reviewer/fixer 分离决定不变）

Family CMR completeness/correctness workers are reviewer workers: they may gather review evidence, run the needed tests, dispatch review legs, and write findings to the findings state store, but they must not repair blocking findings themselves. A blocking finding returns control to the runner, which dispatches a separate coder-fix worker; after that worker updates the finding, the runner dispatches a fresh CMR reviewer over the current full diff.

Scope: this decision applies to family integrated CMR passes. It does not reopen the per-slice coder/reviewer/coder-fix separation already decided by 0030.

## Why

#258 dogfood showed the failure mode clearly: an integrated CMR worker found correctness issues and then moved into a same-session fix loop before all review legs had completed. That is fast when the finding is cheap, but it hides the review -> fix -> re-review state machine inside one agent context, erases the independent reviewer/coder boundary, and makes ledger/resume evidence too weak.

Professional workers inspect commits, tests, and repair evidence. The runner is not a semantic judge; it routes only on unresolved findings count or a human-decision signal.

## Decision

- CMR workers stop at findings, raw review evidence, and relevant test logs.
- Any blocking finding is routed back to the runner before repair.
- The runner dispatches coder-fix for repair.
- The coder-fix worker must create a new commit and provide repair evidence, including same-class bug scan and introduced-regression check.
- The fixer updates the corresponding finding as fixed or refuted; only a fresh reviewer may confirm closure or reopen it.
- Fresh CMR re-review always reviews the current full diff. It must not only check whether the last finding appears closed.

## Tradeoff

Rejected alternative: let CMR workers fix cheap same-module findings themselves. That reduces orchestration overhead, but it recreates the exact class of hidden self-fix loops the orchestrator exists to prevent. The chosen design spends extra worker launches and findings state store entries to preserve role separation, auditability, resumability, and independent review.

## Consequences

- Reviewer workers, including CMR pass workers, must be treated as read/review producers, not persistent fixers.
- Commits, tests, review artifacts, and repair evidence are materials for the next professional worker, not runner gates.
