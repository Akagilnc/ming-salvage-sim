# Family ship worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/ship.md
```

Then read `.ship-focus.md` at the repo root. It is required and pins the family
base branch, PR target base, and repo. If it is missing or contradictory, fail
closed instead of guessing.

Invoke the baked `gstack-ship` skill on the checked-out family base and stop at PR
creation. Use the PR target base from `.ship-focus.md` when opening the PR; never
merge the PR and never push directly to the target base. Do not hand-roll push or
PR creation except where `gstack-ship` itself instructs a fixed command.

Self-rerun only when the skill offers a rerun-able path. Escalate only for a real
human-decision block; report a hard failure when the ship command/tests fail and no
rerun clears it.

## Required output

Emit a single `<ship>` tag on its own line, then print the completion signal on its
own line as the final line.

PR opened:

```text
<ship>{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}</ship>
SHIP_STEP_COMPLETE
```

Escalation:

```text
<ship>{"escalate": {"reason": "<short>", "diagnosis": "<what a human must decide>"}}</ship>
SHIP_STEP_COMPLETE
```

Failure:

```text
<ship>{"failed": {"reason": "<short>", "diagnosis": "<the hard failure>"}}</ship>
SHIP_STEP_COMPLETE
```

Rules:

- The JSON must match one of the shapes above exactly.
- `status` is `pr_opened` and must include `pr`.
- Emit the `<ship>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `SHIP_STEP_COMPLETE` on its own line at the very end.
