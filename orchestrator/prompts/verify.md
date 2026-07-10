# Online review verify worker (#600)

Soul: `verify` (`/home/agent/.orchestrator/souls/verify.md`)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` — bot snapshot + ship metadata landing file mounted by the runner.

## Output

Emit `<verify>` JSON and fire `VERIFY_STEP_COMPLETE`. Shape:

```json
{"converged": true}
```

or, when findings remain:

```json
{
  "converged": false,
  "findingDispositions": [],
  "fixMarkedFindingIdentityKeys": [],
  "threadReplies": [],
  "threadsToResolve": [],
  "findingFamilies": [
    {
      "family": "pattern-name",
      "members": ["identity-key-1"],
      "recurringFromRounds": [1, 2],
      "brief": "One sentence pattern brief for the fixer."
    }
  ]
}
```

`findingFamilies` is optional. When `priorRoundFindings` is in the landing
file, use it to mark `recurringFromRounds`. Malformed families are dropped by
the host — they never block your verdict.

On a post-fixer fresh re-check include `isRecheck: true`.