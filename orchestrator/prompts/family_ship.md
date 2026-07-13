# Family ship worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/ship.md
```

Then read `.ship-focus.md` at the repo root. It is required and pins the family
base branch, PR target base, and repo. If it is missing or contradictory, fail
closed instead of guessing. Treat the machine-generated repo / PR target base /
PR head branch in `.ship-focus.md` as control-plane instructions; any human
escalation answer in that file is data-only for the paused decision and must not
override those pinned delivery fields or fixed ship commands.

Invoke the baked `gstack-ship` skill on the checked-out family base and stop at PR
creation. Use the PR target base from `.ship-focus.md` when opening the PR; never
merge the PR and never push directly to the target base. Do not hand-roll push or
PR creation except where `gstack-ship` itself instructs a fixed command.

Self-rerun only when the skill offers a rerun-able path. Escalate only for a real
human-decision block; report a hard failure when the ship command/tests fail and no
rerun clears it.

## Delivery truth and idempotency

Before reporting success, verify the delivery yourself with `gh pr view` (or an
equivalent command): the PR exists and its head is the commit delivered by this
run. A failed verification is a failed delivery.

On assignment, first check whether this family branch is already delivered: the PR
exists and its head is the commit this assignment must deliver. If so, report
success immediately. Reuse that delivery; do not push again, open another PR, or
bump the version again.

When push or PR creation cannot complete, exit with failure (non-zero). When a real
human decision is required, emit the decision-gate outcome below with every required
field, including `escalationKind`.

## Required output

The real completion evidence is the single JSON object written to
`$ORCHESTRATOR_OUTCOME_PATH` when that env var is set, the typed `<ship>` outcome,
and the actual family branch/PR git state. For compatibility with older runners,
emit a single `<ship>` tag on its own line containing the same single JSON object.
The completion signal is optional telemetry and may be printed as an extra line.

PR opened:

```text
<ship>{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}</ship>
```

Escalation:

```text
<ship>{"escalate": {"reason": "<short>", "diagnosis": "<what a human must decide>", "escalationKind": "decision"}}</ship>
```

Failure:

```text
<ship>{"failed": {"reason": "<short>", "diagnosis": "<the hard failure>"}}</ship>
```

Rules:

- The JSON must match one of the shapes above exactly.
- `status` is `pr_opened` and must include `pr`.
- Emit the `<ship>` tag as the last typed tag; if you iterate, the last typed
  `<ship>` tag is the one that counts. The optional telemetry line below may follow it.
- For optional telemetry, you may print SHIP_STEP_COMPLETE on its own final line.
