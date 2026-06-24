# Coder worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/coder.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; the issue is live truth. Use `ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`)
and `ORCHESTRATOR_REPO` to fetch the current issue body and comments with `gh`.
Retry transient network failures. If GitHub auth is missing or the issue cannot be
read after retry, escalate instead of guessing from stale local context.

Do not use `.orchestrator-snapshot.json` as execution input.

## Required output

When you are done (or are escalating), emit EXACTLY ONE `<coder>` tag on its own,
containing a single JSON object, then print the completion signal on its own line.

Success:

```text
<coder>{"committed": true, "commitsAdded": 3}</coder>
CODER_STEP_COMPLETE
```

Escalation:

```text
<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "<short>", "diagnosis": "<what is wrong and why you cannot proceed>"}}</coder>
CODER_STEP_COMPLETE
```

Rules:

- `committed` is a boolean and `commitsAdded` is an integer >= 0.
- `escalate`, when present, contains `reason` and `diagnosis`.
- Emit the `<coder>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `CODER_STEP_COMPLETE` on its own line at the very end.
