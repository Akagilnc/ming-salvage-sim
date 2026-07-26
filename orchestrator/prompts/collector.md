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
| `evidence` | **required** on `completed` — transport envelope below |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Completed evidence envelope (schema pins only `prUrl` + `headOid`; other
business fields are your judgment and must not be invented by the host):

```json
{
  "station": "onlineReview",
  "status": "completed",
  "evidence": {
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
}
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
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope with evidence — no STEP_COMPLETE password.
