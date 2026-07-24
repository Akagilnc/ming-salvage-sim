# Per-slice Spec-axis review leg

Issue: `$ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`) in `$ORCHESTRATOR_REPO`.
Fixed point: `$ORCHESTRATOR_REVIEW_FIXED_POINT`. Confirm it resolves
(`git rev-parse`), then review the three-dot range
`$ORCHESTRATOR_REVIEW_FIXED_POINT...HEAD` (and
`git log $ORCHESTRATOR_REVIEW_FIXED_POINT..HEAD --oneline`).

Task: Spec axis only — does the code faithfully implement the originating
issue / PRD / spec? Live-fetch the issue. Report (a) requirements missing or
partial; (b) behaviour not asked for (scope creep); (c) requirements that look
implemented but wrong. Quote the spec line for each finding. If no spec is
available, say so briefly. Under 400 words. Emit non-empty prose on stdout for
the resident judge.

Do not emit runner verdict, degradation, retry, or repair instructions.
