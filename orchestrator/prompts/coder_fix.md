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
set, the always-emitted typed `<decision>` signal, the opaque `<coder>` cargo
tag, and the worker's actual git state.

**Always emit both tags** (order: decision, then cargo):

Success (no gate):

```text
<decision>{}</decision>
<coder>{"committed": true, "commitsAdded": 1}</coder>
```

`commitsAdded` must equal the number of actual `git commit` commands you made in
this worker run; if you made multiple commits, report the full count.

Escalation:

```text
<decision>{"escalate": {"reason": "<short>", "diagnosis": "<what blocks the fix>"}}</decision>
<coder>{"committed": false, "commitsAdded": 0}</coder>
```

Always emit `<decision>` (even `{}`) so the optional gate uses a dedicated
typed tag; keep ordinary cargo outside that tag.

For optional telemetry, you may print CODER_STEP_COMPLETE on its own final line.
