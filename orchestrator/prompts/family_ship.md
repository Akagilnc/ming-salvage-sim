# Family ship worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/ship.md
```

Then read `.ship-focus.md` at the repo root. It is required and pins the family
base branch, PR target base, and repo. Invoke the baked `gstack-ship` skill with
those runner parameters. The soul and skill own all delivery method and checks.

## Required output

The real completion evidence is the single JSON object written to
`$ORCHESTRATOR_OUTCOME_PATH` when that env var is set, the always-emitted typed
`<decision>` signal, the opaque `<ship>` cargo tag, and the actual family
branch/PR git state.

**Always emit both tags** (order: decision, then cargo):

PR opened (no gate):

```text
<decision>{}</decision>
<ship>{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}</ship>
```

Escalation:

```text
<decision>{"escalate": {"reason": "<short>", "diagnosis": "<what a human must decide>"}}</decision>
<ship>{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}</ship>
```

(If no PR was opened before escalating, cargo may be `{}` or a failure report.)

Failure cargo (no gate):

```text
<decision>{}</decision>
<ship>{"failed": {"reason": "<short>", "diagnosis": "<the hard failure>"}}</ship>
```

Rules:

- Always emit `<decision>` (even `{}`) — typed gate only; never bind cargo shape to SO.
- `status` is `pr_opened` and must include `pr` on successful delivery cargo.
- Emit `<ship>` as the last cargo tag; if you iterate, the last pair counts.
- This seat is single-iteration. Completion is clean exit + legal sidecar /
  typed gate — no STEP_COMPLETE password.
