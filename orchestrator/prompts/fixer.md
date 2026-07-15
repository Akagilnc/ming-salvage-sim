# Online review fixer worker (#600)

Soul: `fixer` (`/home/agent/.orchestrator/souls/fixer.md`)

## Params

- `.orchestrator-online-review.json` — bot snapshot + `fixMarkedFindingIdentityKeys` from the prior verify worker.
- `.fix-focus.md` (when present) — pattern-level `findingFamilies` briefs from the prior verify worker (#711).

After repairing the listed findings, sweep the touched code and same-mechanism
sites within the assigned family base for other instances of the same defect
class; repair each live in-scope instance in this round. When two or more
findings share a deeper cause, name its underlying invariant and repair to that
invariant so the class closes as a whole within the assigned scope. Record the self-audit checklist in the fixing commit message body:
every in-scope site checked, `file:line` — `fixed` or `already-correct`, giving
the next reviewer coverage to verify. Record same-class sites noticed outside
the assigned family base as `file:line` — `out-of-scope observation` for the
runner; never edit them.
The `<fixer>` outcome remains only the JSON envelope defined below.

## Output

Always emit `<decision>{}</decision>` (or with `escalate`) before the role cargo tag.
When `$ORCHESTRATOR_OUTCOME_PATH` is set, write the same cargo JSON object
directly to that path (sidecar is cargo transport for the runner). Also emit
`<fixer>` cargo JSON:

On the final multi-iter step you MUST print FIXER_STEP_COMPLETE on its own
final line (sandcastle iteration terminator — not optional telemetry).

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
