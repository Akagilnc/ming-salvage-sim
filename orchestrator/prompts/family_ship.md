# Family ship worker entrypoint

Read `.ship-focus.md` at the repo root. It is required and pins the family base
branch, PR target base, and repo.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set (delivery cargo only), the always-emitted typed `<ship>` station-receipt
envelope, and the actual family branch/PR git state.

Emit **one** typed `<ship>` station-receipt envelope. Sandcastle validates the
traffic shape via `Output.object` against the T2 contract in
`orchestrator/src/stationReceiptContracts.ts` (`shipStationReceiptSchema` /
`decodeShipEnvelope`, tag `ship` / `SHIP_RECEIPT_TAG`) — **do not invent a
second field vocabulary** and **do not emit a separate decision-gate dual tag**.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"ship"` |
| `status` | `"shipped"` \| `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

- `shipped` — a PR was opened (or equivalent delivery landed).
- `completed` — clean exit with no useful delivery cargo (no PR / no push cargo).
- `escalate` — genuine block a human must decide (not a re-runnable flake).

### Delivery cargo (opaque; not SO-validated)

Write delivery cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set. Cargo is **not**
the fate channel — process fate is exit code + the typed `<ship>` envelope only.
Do not put cargo `status` on the envelope object (that key is reserved for
traffic `shipped|completed|escalate`).

Successful PR open (sidecar):

```json
{"status": "pr_opened", "branch": "<the family base branch>", "pr": "<the PR url>"}
```

Failure / no-PR report (sidecar; pair with envelope `completed` or `escalate`
as appropriate):

```json
{"failed": {"reason": "<short>", "diagnosis": "<the hard failure>"}}
```

or `{}` when there is nothing useful to report.

### Examples

Shipped (PR opened):

```text
<ship>{"station":"ship","status":"shipped"}</ship>
```

(+ sidecar `{"status":"pr_opened","branch":"...","pr":"..."}` when
`$ORCHESTRATOR_OUTCOME_PATH` is set)

Completed (no delivery cargo):

```text
<ship>{"station":"ship","status":"completed"}</ship>
```

Escalation:

```text
<ship>{"station":"ship","status":"escalate","reason":"<short>","diagnosis":"<what a human must decide>"}</ship>
```

Rules:

- Emit exactly one final `<ship>` envelope (last wins if you iterate).
- Traffic `status` is only `shipped` \| `completed` \| `escalate` — never
  `pr_opened` / `failed` on the envelope (those are cargo tokens).
- Illegal traffic shape is re-asked in-session by Sandcastle; do not rely on the
  runner to guess a status.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
