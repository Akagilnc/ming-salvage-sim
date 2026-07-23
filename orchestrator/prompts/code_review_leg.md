# Per-slice code-review leg task

Issue: `$ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`) in `$ORCHESTRATOR_REPO`.
Fixed point: the prepared worktree base (`main` / family base). Review the
three-dot range `fixed-point...HEAD`.

Task: run per-slice `/code-review` — Standards axis and Spec axis against the
originating issue. Emit non-empty prose evidence on stdout for the resident
judge. Do not emit runner verdict, degradation, retry, or repair instructions.
