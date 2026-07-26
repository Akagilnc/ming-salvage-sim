# Coder fix worker entrypoint

## Runtime inputs

- `ORCHESTRATOR_ISSUE_NUMBER` / `ISSUE_NUMBER`, `ORCHESTRATOR_REPO`
- `.orchestrator-fix-findings.json` (judge-authored `fixPacketBody` verbatim —
  ADR 0138; may also carry `escalationAnswer` — when present, apply that human
  answer; do not repeat the same escalation unless a concrete new blocker
  remains)
- optional `ORCHESTRATOR_RELAY_BRIEF` — when set, continue from that baton
  handoff; do not reset or discard uncommitted work

This seat is **construct/repair only**. Never emit `beat:"plan"` (plan-beat
prose is exclusive to S2; `stampBuilderBeatOnOutput` persists every S5 output
as `construct`).

## Required output

When you are done (or are escalating / refusing), the real completion evidence
is the single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env
var is set (same payload as the typed tag), the always-emitted typed `<coder>`
station-receipt envelope, and the worker's actual git state.

Emit **one** typed `<coder>` station-receipt envelope. Sandcastle validates
traffic via `Output.object` against the T2 contract in
`orchestrator/src/stationReceiptContracts.ts` (`coderStationReceiptSchema` /
`decodeCoderEnvelope`) — **do not hand-copy a second schema**.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"coderFix"` for this fix seat (`"coder"` only on implement) |
| `status` | `"completed"` \| `"refused"` \| `"escalate"` |
| `refusedFindingIdentityKeys` | required non-empty string[] when `status:"refused"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Canonical refuse vocabulary is **`refused*` only** — never `refuted*` envelope keys.

### Cargo body (opaque; not SO-validated)

- `committed` (boolean) + `commitsAdded` (integer ≥ 0) — real git state for
  **this worker run**. Every `completed` / `refused` / `escalate` hand-in
  reports them truthfully.
- On refuse: place **complete** four-reason/evidence `refuseRecords` in the
  **consumed** cargo channel — `$ORCHESTRATOR_OUTCOME_PATH` when set, and/or
  same-object siblings on the `<coder>` payload (what
  `cargoRawFor` / `familyCoderCargoRaw` → `projectCoderStationReceipt` read).
  Tokens/shape: `stationReceiptContracts.ts` (`LEGAL_REFUSE_REASONS` / refuse
  cargo) — **do not** invent envelope fields or hand-copy a second schema.
  Envelope `refusedFindingIdentityKeys` remains sole traffic authority (cargo
  never invents keys). Do **not** rely on `cargoPointer` alone: production
  projection does not dereference it for refuse evidence.
- Cargo siblings on the same `<coder>` object are allowed; only illegal
  **traffic** re-asks.

### Examples

Completed:

```text
<coder>{"station":"coderFix","status":"completed","committed":true,"commitsAdded":1}</coder>
```

Refused (envelope keys = traffic; complete `refuseRecords` on consumed cargo —
write the same object to `$ORCHESTRATOR_OUTCOME_PATH` when set):

```text
<coder>{"station":"coderFix","status":"refused","refusedFindingIdentityKeys":["correctness|src/x.ts:1|claim"],"committed":true,"commitsAdded":1,"refuseRecords":[{"identityKey":"correctness|src/x.ts:1|claim","finding":"<claim>","acceptanceCriterion":"<AC under dispute>","conflictReason":"<why refuse>","reason":"not_established","evidence":"<clause-anchored evidence>"}]}</coder>
```

Escalation:

```text
<coder>{"station":"coderFix","status":"escalate","reason":"<short>","diagnosis":"<what blocks the fix>","committed":false,"commitsAdded":0}</coder>
```

Rules:

- Emit exactly one final `<coder>` envelope (last wins if you iterate).
- `commitsAdded` equals the number of commits created in this worker run.
- **`committed` / `commitsAdded` always mirror real git**, including on escalate
  and refuse.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
