# Ship worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/ship.md
```

Then invoke the baked `gstack-ship` skill on the current reviewed slice branch. The
runner only schedules you; delivery method belongs to `gstack-ship`, not this
prompt. Do not hand-roll push or PR creation. If `.ship-focus.md` is present at
the repo root, read it first and apply its runner-supplied focus (for example, an
answered S7 decision escalation). A single-slice ship can also run without a
`.ship-focus.md` (the soul does not block on its absence — let `gstack-ship` detect
the base).

Self-rerun only when the skill offers a rerun-able path. Escalate only for a real
human-decision block; report a hard failure when the ship command/tests fail and no
rerun clears it.

## Delivery truth and idempotency

Before reporting success, verify the delivery yourself with `gh pr view` (or an
equivalent command): the PR exists and its head is the commit delivered by this
run. A failed verification is a failed delivery.

On assignment, first check whether this branch is already delivered: the PR exists
and its head is the commit this assignment must deliver. If so, report success
immediately. Reuse that delivery; do not push again, open another PR, or bump the
version again.

When push or PR creation cannot complete, exit with failure (non-zero). When a real
human decision is required, emit the decision-gate outcome below with every required
field, including `escalationKind`.

## Required output

The real completion evidence is the single JSON object written to
`$ORCHESTRATOR_OUTCOME_PATH` when that env var is set, the typed `<ship>` outcome,
and the actual branch/PR git state. For compatibility with older runners, emit a
single `<ship>` tag on its own line containing the same single JSON object. The
completion signal is optional telemetry and may be printed as an extra line.

PR opened:

```text
<ship>{"status": "pr_opened", "branch": "<the shipped branch>", "pr": "<the PR url>"}</ship>
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
- Success is only `status: "pr_opened"` and must include `pr`; if no PR exists,
  emit failure and exit non-zero.
- Every string field you emit (`branch`, `pr`, `reason`, `diagnosis`) must be
  non-empty after trimming — the runner validates them as trimmed-non-empty
  (`shipOutcome.ts`) and rejects a blank/whitespace value.
- Emit the `<ship>` tag as the last typed tag; if you iterate, the last typed
  `<ship>` tag is the one that counts. The optional telemetry line below may follow it.
- For optional telemetry, you may print SHIP_STEP_COMPLETE on its own final line.
