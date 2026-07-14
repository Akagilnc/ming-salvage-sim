# Online review verify worker (#600)

Soul: `verify` (`/home/agent/.orchestrator/souls/verify.md`)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` — bot snapshot + ship metadata landing file mounted by the runner.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before reviewing.

## Output

When `$ORCHESTRATOR_OUTCOME_PATH` is set, write the same terminal JSON object
directly to that path (sidecar is authoritative for the runner). For
compatibility, also emit `<verify>` JSON. Shape:

On the final multi-iter step you MUST print VERIFY_STEP_COMPLETE on its own
final line (sandcastle iteration terminator — not optional telemetry).

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
