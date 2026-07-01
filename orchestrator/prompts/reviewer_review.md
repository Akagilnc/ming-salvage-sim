# Reviewer worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/reviewer.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; review method and input handling belong to the baked soul plus runner
parameters.

## Required output

When you are done (or are escalating), emit EXACTLY ONE `<review>` tag on its
own, containing a single JSON object, then print the completion signal on its own
line.

Success:

```text
<review>{"findings":[]}</review>
REVIEWER_STEP_COMPLETE
```

With findings:

```text
<review>{"findings":[{"severity":"high","category":"correctness","claim_quote":"<short>","location":"path:line","suggested_fix":"<short>","action":"fix_now"}]}</review>
REVIEWER_STEP_COMPLETE
```

Deferred or suppressed findings must carry a machine-verifiable `disposition`.
Use one of:
`same_module`, `cross_module`, `spec_conflict`, `infra_failure`,
`owning_issue_still_red`, `accepted_suppressed`.

P0/P1 findings (`critical`/`high`) must always use `action:"fix_now"`.
For P2/P3 `action:"defer"`, only `cross_module` may pass without a fix, and it
must include `targetModule` and `reason`. Same-module gaps, owning-issue still-red
gaps, spec conflicts, and infra failures must be classified explicitly and will
fail closed through the runner rather than silently passing.

`accepted_suppressed` is not a reviewer-created defer. Only use it when there is
an explicit user decision, accepted ADR, or named issue acceptance text, and
include `source`, `scope`, `reason`, `findingIdentity`, optional `targetModule`,
and `boundedReopen`.

When the runner supplies prior claimed-fixed findings for a fresh re-review,
it exposes them at `$ORCHESTRATOR_FIX_FINDINGS_PATH` as JSON. Read that file,
classify every prior finding explicitly in `priorFindingDispositions`, and use the
runner-provided `identityKey` and one of:
`still-active`, `verified-closed`, `unable-to-assess`. Do not rely on omitting a
finding to mean it is closed.

The same JSON may contain `escalationAnswer` when this is a resumed reviewer
decision escalation. Apply that human answer before reviewing, and do not repeat
the same escalation unless the answer leaves a concrete blocker unresolved.

```text
<review>{"findings":[],"priorFindingDispositions":[{"identityKey":"<prior-key>","status":"verified-closed","reason":"<short>"}]}</review>
REVIEWER_STEP_COMPLETE
```

Escalation:

```text
<review>{"findings":[],"escalate":{"reason":"<short>","diagnosis":"<what blocks review>"}}</review>
REVIEWER_STEP_COMPLETE
```
