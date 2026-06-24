# Ship worker entrypoint

Invoke the baked `gstack-ship` skill on the current reviewed slice branch. The
runner only schedules you; delivery method belongs to `gstack-ship`, not this
prompt. Do not hand-roll push or PR creation.

Self-rerun only when the skill offers a rerun-able path. Escalate only for a real
human-decision block; report a hard failure when the ship command/tests fail and no
rerun clears it.

## Required output

Emit a single `<ship>` tag on its own line, then print the completion signal on its
own line as the final line.

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
- Emit the `<ship>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `SHIP_STEP_COMPLETE` on its own line at the very end.
