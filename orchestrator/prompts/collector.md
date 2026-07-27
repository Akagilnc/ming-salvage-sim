# Online Review Collector worker (#1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` —
  ship metadata + optional prior round fix-marked keys. May lack evidence on
  first entry; you assemble it.
- Round / PR URL / head from the landing file and env.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before collecting.

## Required output

Emit **one** typed `<onlineReview>` station-receipt envelope. Sandcastle
validates via `Output.object` against
`collectorOnlineReviewStationReceiptSchema` in
`orchestrator/src/stationReceiptContracts.ts` (tag `onlineReview` /
`ONLINE_REVIEW_RECEIPT_TAG`). **JSON only** inside the tag — never YAML or prose.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"onlineReview"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Thin gate only: completed \| escalate. **Business evidence is never a typed
traffic field** — sparse cargo does not change process fate (ADR 0131).

### Role cargo (opaque; not SO-validated)

Write collector evidence cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set
(sidecar is cargo transport). You may also emit opaque `<collector>` cargo JSON
for the same body. Shape of the cargo body (when evidence is ready):

```json
{
  "prUrl": "…",
  "headOid": "…",
  "totalFindingCount": 0,
  "quiescent": true,
  "bots": {},
  "droppedBots": [],
  "threads": [],
  "checkRuns": [],
  "checkRunsEmptyMeans": "converged"
}
```

Completed thin envelope (evidence is optional opaque cargo on sidecar /
cargoPointer / `<collector>` — never a typed traffic field):

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalate:

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<what blocks collection>"}</onlineReview>
```

Rules:

- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Role cargo never carries escalate or judge enum — fate is the typed envelope;
  judgment is Verify's job.
- Do not set `converged`, `findingDispositions`, or fixer plan fields.
- Evidence cargo is **optional** on completed (ADR 0131 cargo ≠ fate). Sparse
  or missing evidence does not fail the process; escalate yourself when you
  cannot continue collection.
- Post-fix retrigger / limited wait / overdue exit are **your** methods (see
  collector soul + `collectorPostFixRetriggerPlan` /
  `ONLINE_REVIEW_BOT_RETRIGGER_COMMENT`). Host does not poll or re-trigger.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope — no STEP_COMPLETE password.
