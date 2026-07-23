# Coder worker entrypoint

Runtime issue inputs are `ORCHESTRATOR_ISSUE_NUMBER` (or `ISSUE_NUMBER`) and
`ORCHESTRATOR_REPO`.

`.orchestrator-fix-findings.json`, when present, carries the runner transports
`builderBeat`, `fixPacketBody`, and `builderPlanBody`.

Do not use `.orchestrator-snapshot.json` as execution input.

If `ORCHESTRATOR_RELAY_BRIEF` is set, read that ephemeral baton handoff brief
(`state_summary` / remaining) from a prior resource-relay before continuing.
Continue from that scene — do not reset or discard uncommitted work that the
previous baton left.

If `ORCHESTRATOR_FIX_FINDINGS_PATH` is set, read that runner-owned JSON file
before acting. On a resumed decision escalation it may contain
`escalationAnswer`; apply that human answer and do not repeat the same escalation
unless the answer leaves a concrete blocker unresolved.

## Required output

When you are done (or are escalating / refusing), the real completion evidence
is the single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env
var is set (same payload as the typed tag), the always-emitted typed `<coder>`
station-receipt envelope, and the worker's actual git state.

Emit **one** typed `<coder>` station-receipt envelope. Sandcastle validates the
traffic shape via `Output.object` against the T2 contract in
`orchestrator/src/stationReceiptContracts.ts` (`coderStationReceiptSchema` /
`decodeCoderEnvelope`) — **do not invent a second field vocabulary**.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"coder"` for implement (this seat); fix seat uses `"coderFix"` |
| `status` | `"completed"` \| `"refused"` \| `"escalate"` |
| `refusedFindingIdentityKeys` | required non-empty string[] when `status:"refused"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Canonical refuse vocabulary is **`refused*` only** — never `refuted*` envelope keys.

### Cargo body (opaque; not SO-validated)

- `committed` (boolean) + `commitsAdded` (integer ≥ 0) — real git state.
- On refuse: **四理由** (违宪 / 过度防御 / 事实不成立 / 越权加戏 —
  machine tokens `unconstitutional` / `over_defense` / `not_established` /
  `scope_creep` from the same T2 module) + evidence prose for the judge live in
  cargo / the file at `cargoPointer`, **not** as extra envelope fields.
- You may put cargo siblings on the same `<coder>` JSON object; the framework
  only re-asks illegal **traffic** shapes.

### Examples

Completed:

```text
<coder>{"station":"coder","status":"completed","committed":true,"commitsAdded":3}</coder>
```

Escalation (real commit count even when escalating):

```text
<coder>{"station":"coder","status":"escalate","reason":"<short>","diagnosis":"<what blocks you>","committed":false,"commitsAdded":0}</coder>
```

Rules:

- Emit exactly one final `<coder>` envelope (last wins if you iterate).
- **`committed` / `commitsAdded` always mirror real git**, including on escalate.
- Illegal traffic shape is re-asked in-session by Sandcastle; do not rely on the
  runner to guess a status.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
