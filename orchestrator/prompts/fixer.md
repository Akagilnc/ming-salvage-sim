# Online review fixer worker (#600)

Soul: `fixer` (`/home/agent/.orchestrator/souls/fixer.md`)

## Params

- `.orchestrator-online-review.json` — bot snapshot + `fixMarkedFindingIdentityKeys` from the prior verify worker.

## Output

Emit `<fixer>` JSON and fire `FIXER_STEP_COMPLETE`:

```json
{"committed": true}
```

when you committed a new fix this turn;

```json
{"committed": false, "alreadySatisfied": true, "fixCommitSha": "<current-branch-HEAD>"}
```

when the assigned fix-marked finding(s) are **already resolved** on the current
branch (e.g. a prior crashed attempt already landed the fix) — proceed to verify,
not a park;

or `{"committed": false}` when the assigned finding(s) are **genuinely still
present** and you made no new commit (decision gate).