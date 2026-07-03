# Family CMR findings return to runner before fixes

Status: Accepted (#533/#553, 2026-07-03)

Family CMR completeness/correctness workers are reviewer workers: they may gather review evidence, run the needed tests, dispatch review legs, and emit findings/outcome, but they must not repair blocking findings themselves. A blocking finding returns control to the runner, which dispatches a separate coder-fix worker; only after that worker produces a new fix commit and repair evidence does the runner dispatch a fresh CMR reviewer over the current full diff.

Scope: this decision applies to family integrated CMR passes. It does not reopen the per-slice coder/reviewer/coder-fix separation already decided by 0030.

## Why

#258 dogfood showed the failure mode clearly: an integrated CMR worker found correctness issues and then moved into a same-session fix loop before all review legs had completed. That is fast when the finding is cheap, but it hides the review -> fix -> re-review state machine inside one agent context, erases the independent reviewer/coder boundary, and makes ledger/resume evidence too weak.

The runner is not a semantic judge. It must not decide whether a finding is "really true", nor infer route from reviewer prose with regex or keywords. It can only enforce mechanical control: worker outcome shape, completion signal, git head movement, independent fix commit, repair evidence, test logs, and fresh re-review after the fix.

## Decision

- CMR workers stop at review artifacts: structured findings/outcome, raw review evidence, and relevant test logs.
- Any blocking finding is routed back to the runner before repair.
- The runner dispatches coder-fix for repair; the coder-fix worker must create a new commit and provide repair evidence, including same-class bug scan and introduced-regression check.
- If repair evidence is missing or inconsistent with git truth, the runner sends the fix back to coder-fix for evidence/commit repair. It does not guess semantic correctness.
- If worker outcome is malformed, missing, or schema-incompatible, that is an outcome protocol failure, not a business finding. Outcome validation belongs in a versioned image-level guard/tool, not in copied prompt prose. The guard is generic worker infrastructure from the start, not a CMR-only prompt patch; family CMR is simply the first painful consumer this ADR needs to close. Workers should validate their terminal report before emitting the completion signal; ideally the worker entrypoint forces this through a shared outcome guard. The guard validates format, role schema, required fields, and referenced evidence paths; the runner still owns git-truth checks and routing, and reviewers/CMR workers still own semantic judgment. If malformed outcome still reaches the runner, the runner asks the same producing worker to rewrite a valid outcome from existing artifacts, preserving that worker's local memory; the retry cap is 2 before infrastructure escalation.
- Fresh CMR re-review always reviews the current full diff. It must not only check whether the last finding appears closed.

## Tradeoff

Rejected alternative: let CMR workers fix cheap same-module findings themselves. That reduces orchestration overhead, but it recreates the exact class of hidden self-fix loops the orchestrator exists to prevent. The chosen design spends extra worker launches and ledger entries to preserve role separation, auditability, resumability, and independent review.

## Consequences

- Family CMR ledger must expose each review -> fix -> re-review round as separate evidence.
- Reviewer workers, including CMR pass workers, must be treated as read/review producers, not persistent fixers.
- Worker outcome JSON is a control envelope, not a semantic truth source.
- Commits, heads, test logs, review artifacts, and repair evidence are the hard evidence runner may enforce.
- A CMR reviewer that writes off-schema self-fix state is rejected by the outcome guard; a CMR reviewer that moves the family head is contract drift, not a valid review or fix round.
