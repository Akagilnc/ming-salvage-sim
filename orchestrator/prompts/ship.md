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

## Required output

Write the single JSON object to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set. Then, for compatibility with older runners, emit a single `<ship>` tag on its
own line containing the same single JSON object, and print the completion signal
on its own line as the final line.

PR opened:

```text
<ship>{"status": "pr_opened", "branch": "<the shipped branch>", "pr": "<the PR url>"}</ship>
SHIP_STEP_COMPLETE
```

Pushed but no PR:

```text
<ship>{"status": "pushed", "branch": "<the shipped branch>"}</ship>
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
- `status` is `pr_opened` or `pushed`; `pr_opened` must include `pr`.
- Every string field you emit (`branch`, `pr`, `reason`, `diagnosis`) must be
  non-empty after trimming — the runner validates them as trimmed-non-empty
  (`shipOutcome.ts`) and rejects a blank/whitespace value.
- Emit the `<ship>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `SHIP_STEP_COMPLETE` on its own line at the very end.
