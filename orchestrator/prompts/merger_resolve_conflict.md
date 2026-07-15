# Merger worker entrypoint — resolve one family-merge conflict

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/merger.md
```

Then follow that soul and the worktree's `CLAUDE.md ## Skill routing`. The runner
only schedules you: it attempted a deterministic `git merge --no-ff` of a reviewed
child slice into the family base, hit a conflict, and left the markers in the
working tree — resolve **this one in-progress merge** and return. The
conflict-resolution method, the both-sides-preservation rule, the commit-don't-push
rule, and the escalate-don't-guess policy all live in the soul + the
`resolving-merge-conflicts` skill; do not restate or hand-write them here.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set, the always-emitted typed `<decision>` signal, the opaque `<merger>` cargo
tag, and the actual merge/git state.

**Always emit both tags** (order: decision, then cargo):

Success / resolved (no gate):

```text
<decision>{}</decision>
<merger>{"resolved": true, "tradeoffs": "<one line: any side picked / note, or empty>"}</merger>
```

- `resolved` (boolean): did you resolve the conflict and commit the merge?
- `tradeoffs` (string): a one-line note of any incompatible hunk where you had to
  pick one side (empty string if both intents were preserved cleanly).

Escalation (a conflict you must NOT guess at — surface it to a human):

```text
<decision>{"escalate": {"reason": "<short>", "diagnosis": "<why this conflict cannot be resolved without a decision>"}}</decision>
<merger>{"resolved": false}</merger>
```

Rules:

- Always emit `<decision>` (even `{}`) — typed gate only.
- The cargo JSON must be valid and match one of the shapes above exactly.
- Emit `<merger>` as the last cargo tag. On the final multi-iter step you MUST
  print MERGER_STEP_COMPLETE on its own final line (sandcastle iteration
  terminator — not optional telemetry).
- Never `git merge --abort`. Never invent behaviour. Resolve or escalate.
