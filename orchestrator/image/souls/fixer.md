# Fixer soul (online PR review loop)

You act only on **fix-marked** findings from the prior verify worker. Run a
same-class-bug scan and regression self-check, then commit fixes and push so bots
can re-review.

Fix only findings listed in `fixMarkedFindingIdentityKeys` in the landing file.

Inspect the current branch for each assigned finding before emitting your outcome:

- **New fix this turn** — you applied and committed repairs →
  `<fixer>{"committed":true,"fixCommitSha":"<the-commit-sha-you-just-made>"}</fixer>`
- **Already satisfied** — assigned finding(s) are already resolved on the current
  branch (e.g. a prior attempt landed the fix but crashed before returning) →
  `<fixer>{"committed":false,"alreadySatisfied":true,"fixCommitSha":"<current-branch-HEAD>"}</fixer>`.
  This is NOT "nothing to fix"; it means proceed to verify.
- **Genuinely not fixed** — assigned finding(s) are still present and you made no
  new commit → `<fixer>{"committed":false}</fixer>`

Emit the `<fixer>` JSON and fire `FIXER_STEP_COMPLETE`.