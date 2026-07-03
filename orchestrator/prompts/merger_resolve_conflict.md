# Merger worker entrypoint — resolve one family-merge conflict

Read the baked role soul first:

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

When you are done (or are escalating), write the single JSON object to
`$ORCHESTRATOR_OUTCOME_PATH` when that env var is set. Then, for compatibility
with older runners, emit a single `<merger>` tag on its own line containing the
same single JSON object, and print the completion signal on its own line as the
final line.

Success / resolved:

```text
<merger>{"resolved": true, "tradeoffs": "<one line: any side picked / note, or empty>"}</merger>
MERGER_STEP_COMPLETE
```

- `resolved` (boolean): did you resolve the conflict and commit the merge?
- `tradeoffs` (string): a one-line note of any incompatible hunk where you had to
  pick one side (empty string if both intents were preserved cleanly).

Escalation (a conflict you must NOT guess at — surface it to a human):

```text
<merger>{"resolved": false, "escalate": {"reason": "<short>", "diagnosis": "<why this conflict cannot be resolved without a decision>"}}</merger>
MERGER_STEP_COMPLETE
```

Rules:

- The JSON must be valid and match one of the shapes above exactly.
- Emit the `<merger>` tag LAST, then `MERGER_STEP_COMPLETE` on its own final line.
- Never `git merge --abort`. Never invent behaviour. Resolve or escalate.
