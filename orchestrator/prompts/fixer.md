# Online review fixer worker (#600)

Soul: `fixer` (`/home/agent/.orchestrator/souls/fixer.md`)

## Params

- `.orchestrator-online-review.json` — bot snapshot + `fixMarkedFindingIdentityKeys` from the prior verify worker.
- `.fix-focus.md` (when present) — pattern-level `findingFamilies` briefs from the prior verify worker (#711).

After repairing the listed findings, sweep each touched file and every file
sharing its mechanism for other instances of the same defect class; repair each
live instance in this round. When two or more findings share a deeper cause,
name its underlying invariant and repair to that invariant so the class closes
as a whole. Close your summary with a self-audit checklist: every site checked,
`file:line` — `fixed` or `already-correct`, giving the next reviewer coverage to
verify.

## Output

Emit `<fixer>` JSON:

For optional telemetry, you may print FIXER_STEP_COMPLETE on its own final line.

```json
{"committed": true, "fixCommitSha": "<the-commit-sha-you-just-made>"}
```

when you committed a new fix this turn (report the fixing commit SHA you just
created);

```json
{"committed": false, "alreadySatisfied": true, "fixCommitSha": "<current-branch-HEAD>"}
```

when the assigned fix-marked finding(s) are **already resolved** on the current
branch (e.g. a prior crashed attempt already landed the fix) — proceed to verify,
not a park;

or `{"committed": false}` when the assigned finding(s) are **genuinely still
present** and you made no new commit (decision gate).
