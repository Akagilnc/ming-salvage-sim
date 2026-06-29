# Reviewer worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/reviewer.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; the issue is live truth. Use `ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`)
and `ORCHESTRATOR_REPO` to fetch the current issue body and comments with `gh`.
Retry transient network failures. If GitHub auth is missing or the issue cannot be
read after retry, escalate instead of guessing from stale local context.

Review the current full slice diff every time you run. Do not limit review to the
prior finding or fix commit.

Do not use `.orchestrator-snapshot.json` as execution input.

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
classify every prior finding explicitly in `priorFindingDispositions`. Use the
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
