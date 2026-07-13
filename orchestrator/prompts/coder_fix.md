# Coder fix worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/coder.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you. Use the runner parameters `ORCHESTRATOR_ISSUE_NUMBER` / `ISSUE_NUMBER`,
`ORCHESTRATOR_REPO`, `.orchestrator-fix-findings.json`, optional `.fix-focus.md`,
and optional `.relay-focus.md`; the fix-findings path may carry an
`escalationAnswer`. Invoke the baked skills selected by the soul.
The soul and skills own finding validation, issue lookup, tests, self-checks,
commit verification, and all repair method.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set, the typed `<coder>` outcome, and the worker's actual git state. For
compatibility with older runners, emit EXACTLY ONE `<coder>` tag
on its own containing the same single JSON object. The completion signal is
optional telemetry and may be printed as an extra line.

For optional telemetry, you may print CODER_STEP_COMPLETE on its own final line.

Success:

```text
<coder>{"committed": true, "commitsAdded": 1}</coder>
```

`commitsAdded` must equal the number of actual `git commit` commands you made in
this worker run; if you made multiple commits, report the full count.

Escalation:

```text
<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "<short>", "diagnosis": "<what blocks the fix>"}}</coder>
```
