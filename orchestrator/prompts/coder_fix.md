# Coder fix worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/coder.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; the issue is live truth. Use `ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`)
and `ORCHESTRATOR_REPO` to fetch the current issue body and comments with `gh`.
Retry transient network failures. If GitHub auth is missing or the issue cannot be
read after retry, escalate instead of guessing from stale local context.

Fix the blocking review findings supplied by the runner for this round. In normal
runner executions the file is in the sibling ledger directory:
`../.ledger-${ORCHESTRATOR_ISSUE_NUMBER}/fix-findings.json` (or
`../.ledger-${ISSUE_NUMBER}/fix-findings.json`). A legacy compatibility fallback
may provide `.orchestrator-fix-findings.json` at the worktree root. Prefer the
sibling ledger file when it exists. Keep the fix scoped, run the relevant tests,
run the mandatory self-check 二连, and create a new commit for this review round.
Never amend a prior commit.

Do not use `.orchestrator-snapshot.json` as execution input.

## Required output

When you are done (or are escalating), emit EXACTLY ONE `<coder>` tag on its own,
containing a single JSON object, then print the completion signal on its own line.

Success:

```text
<coder>{"committed": true, "commitsAdded": 1}</coder>
CODER_STEP_COMPLETE
```

Escalation:

```text
<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "<short>", "diagnosis": "<what blocks the fix>"}}</coder>
CODER_STEP_COMPLETE
```
