# Judge station (S3 establish / S6 resume) — #925 / #1081–#1083 hub

Follow the worktree's `CLAUDE.md`.

## Runtime inputs

- Landing / fix-findings transport from the runner (`$ORCHESTRATOR_FIX_FINDINGS_PATH`
  when set, else `.orchestrator-fix-findings.json`) — builder beat cargo,
  `priorJudgeVerdicts`, refuse records, panel-leg transports as applicable.
- Issue / repo env for live-fetch when the soul requires it.

## Typed receipt (traffic only)

Always emit the official station envelope on the `<judge>` tag (Sandcastle
`Output.object` on tag `judge` — schema from `stationReceiptContracts`). Cargo
(findings rows, essays) may ride as siblings / sidecar or at
`$ORCHESTRATOR_OUTCOME_PATH` when set; the runner routes only on `status`.

```xml
<judge>{"station":"judge","status":"converged"}</judge>
```

Completion is clean exit + legal typed envelope / sidecar — no STEP_COMPLETE
password. Finish inside the single iteration (`maxIterations=1`).

### Plan pre-review (#1082) / fresh legs

- Landing with `builderPlanBody` (plan beat, no construction): answer on the
  receive step with existing status enum only — `continue` + non-empty
  `fixPacketBody` (准 / 退 / 索证 / boundaries in that prose; 0 live findings
  legal). `converged` only on full withdraw (全撤). Never invent a second
  pre-review status token. Never dispatch fresh review legs on a plan beat.
- Dispatch **fresh** review legs only after accepting construction (never
  resume a prior leg session). Prepend the full `reviewer.md` soul text at
  the head of every leg prompt. Fresh findings return here for disposition —
  never straight to the fixer.

### Converged (no further fix rounds)

```json
{"station":"judge","status":"converged"}
```

Never emit `converged` while any finding remains live. If live findings remain,
use `continue`.

### Continue (send live findings to S5)

```json
{
  "station": "judge",
  "status": "continue",
  "findingDispositions": [
    {
      "identityKey": "<stable-key>",
      "action": "refute",
      "reason": "unconstitutional",
      "evidence": "<non-empty evidence>"
    },
    {
      "identityKey": "<stable-key-2>",
      "action": "live"
    },
    {
      "identityKey": "<stable-key-3>",
      "action": "suppress",
      "evidence": "<non-empty evidence>",
      "groundTicket": 949
    }
  ],
  "fixPacketBody": "<judge-authored fix packet body — verbatim to fixer>",
  "advanceCoder": "<optional roster suggestion>",
  "findings": []
}
```

- `findingDispositions` is required on continue (may be empty when no opens).
- Kill rows: `action:"refute"` + one of
  `unconstitutional | over_defense | not_established | scope_creep` + non-empty
  `evidence`.
- Live rows: `action:"live"` only (no reason/evidence smuggled).
- Suppress rows (#952): `action:"suppress"` + non-empty `evidence` + **exactly
  one** ground — either `groundTicket` (positive int issue number) **or**
  `ownerRecordPointer` (non-empty string). Do **not** invent a `reason` field
  on suppress rows. Suppressed keys are archived terminals — they are **not**
  sent to the fixer (only `live` enters S5).
- **`fixPacketBody` is required on continue** (ADR 0138 / #978): the
  judge-authored coder-fix packet body. Runner transports it **verbatim** as
  the sole packet content path — never packs bare `findings` rows.
- `advanceCoder` is an optional suggestion; runner stay-put policy is #926.
- `findings` cargo is optional opaque siblings (identity/telemetry only after
  ADR 0138 — not the fixer packet path).

### Escalate (decision-kind park — not a new channel, not a terminal kill)

```json
{
  "station": "judge",
  "status": "escalate",
  "reason": "<short>",
  "diagnosis": "<what blocks the ring>"
}
```

Escalate parks via the existing decision gate; owner answers and the run
resumes in place. Do not invent a second escalate path.
