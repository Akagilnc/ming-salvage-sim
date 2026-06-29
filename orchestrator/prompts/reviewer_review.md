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

When the runner supplies prior claimed-fixed findings for a fresh re-review,
it exposes them at `$ORCHESTRATOR_FIX_FINDINGS_PATH` as JSON. Read that file,
classify every prior finding explicitly in `priorFindingDispositions`, and use the
runner-provided `identityKey` and one of:
`still-active`, `verified-closed`, `unable-to-assess`. Do not rely on omitting a
finding to mean it is closed.

```text
<review>{"findings":[],"priorFindingDispositions":[{"identityKey":"<prior-key>","status":"verified-closed","reason":"<short>"}]}</review>
REVIEWER_STEP_COMPLETE
```

Escalation:

```text
<review>{"findings":[],"escalate":{"reason":"<short>","diagnosis":"<what blocks review>"}}</review>
REVIEWER_STEP_COMPLETE
```
