# Online review verify worker (#600)

Soul: `verify` (`/home/agent/.orchestrator/souls/verify.md`)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` — bot snapshot + ship metadata landing file mounted by the runner.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, resolve the PR yourself with `gh pr view <branch>` before reviewing.

## Output

Emit `<verify>` JSON. Shape:

For optional telemetry, you may print VERIFY_STEP_COMPLETE on its own final line.

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

`findingFamilies` is optional. Malformed families are dropped by the host —
they never block your verdict.

On a post-fixer fresh re-check include `isRecheck: true` and echo every
`fixMarkedFindingIdentityKeys` value from the landing file before returning
`converged:true`; otherwise return `converged:false`.
