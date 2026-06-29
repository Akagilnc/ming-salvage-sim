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

When you are done (or are escalating), emit EXACTLY ONE `<reviewer>` tag on its
own, containing a single JSON object, then print the completion signal on its own
line.

Success:

```text
<reviewer>{"findings":[]}</reviewer>
REVIEWER_STEP_COMPLETE
```

With findings:

```text
<reviewer>{"findings":[{"severity":"high","category":"correctness","claim_quote":"<short>","location":"path:line","suggested_fix":"<short>","action":"fix_now"}]}</reviewer>
REVIEWER_STEP_COMPLETE
```

Escalation:

```text
<reviewer>{"findings":[],"escalate":{"reason":"<short>","diagnosis":"<what blocks review>"}}</reviewer>
REVIEWER_STEP_COMPLETE
```
