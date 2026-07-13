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
set, the typed `<coder>` outcome, the repair evidence, and the worker's actual
git state. For compatibility with older runners, emit EXACTLY ONE `<coder>` tag
on its own containing the same single JSON object. The completion signal is
optional telemetry and may be printed as an extra line.

For optional telemetry, you may print CODER_STEP_COMPLETE on its own final line.

Success:

```text
<coder>{"committed": true, "commitsAdded": 1, "repairEvidence": {"findingScope": {"identityKeys": ["<fixed-finding-identity-key>"], "locations": ["<fixed-location-or-file>"]}, "changedFiles": ["<file-you-changed>"], "tests": ["<test command you ran>"], "sameClassBugScan": "<same-class bug scan command or artifact>", "introducedRegressionCheck": "<introduced-regression check command or artifact>", "patchSummary": "<short summary of the scoped repair>"}}</coder>
```

For a fix round, include `repairEvidence` whenever you committed a fix for a
runner-supplied finding. The fresh reviewer uses it as context while judging the
current full diff. Use the
identity keys and locations from the fix-findings JSON when available:

- `findingScope.identityKeys`: the fixed finding identity key(s).
- `findingScope.locations`: the fixed finding location(s) or file paths.
- `changedFiles`: files actually changed by this fix.
- `tests` / `fixtures` / `patchSummary`: concise evidence for what changed and
  how it was checked.
- `sameClassBugScan`: command/log/artifact showing the required same-class bug scan.
- `introducedRegressionCheck`: command/log/artifact showing the required regression check.
- `commitsAdded` must equal the number of actual `git commit` commands you made in
  this worker run; if you made multiple commits, report the full count.

Escalation:

```text
<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "<short>", "diagnosis": "<what blocks the fix>", "escalationKind": "decision"}}</coder>
```
