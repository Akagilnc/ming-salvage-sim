# Online review verify worker (#600 / #940 / #934 ID-012 / #1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` —
  **Collector-assembled** landing for this seat (may carry
  `onlineReviewSnapshot` body and/or `cargoPointer` handle). Collector already
  completed query/wait/evidence.
- Method truth (evidence resolve, judgment, side effects) lives in the Verify
  soul (`image/souls/verify.md`) — this promptFile is params + envelope/cargo
  contract only.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before reviewing.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set (role cargo only), the always-emitted typed `<onlineReview>` station-receipt
envelope, and any optional opaque `<verify>` cargo tag.

Emit **one** typed `<onlineReview>` station-receipt envelope. Sandcastle
validates the traffic shape via `Output.object` against the T2 contract in
`orchestrator/src/stationReceiptContracts.ts`
(`onlineReviewStationReceiptSchema` / `decodeOnlineReviewEnvelope`, tag
`onlineReview` / `ONLINE_REVIEW_RECEIPT_TAG`) — **do not invent a second field
vocabulary** and **do not emit a separate decision-gate dual tag**.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"onlineReview"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Thin gate only: completed \| escalate. Converged / findings narrative is cargo,
never a fate signal on this envelope.

### Role cargo (opaque; not SO-validated)

Write verify cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set (sidecar is cargo
transport). You may also emit opaque `<verify>` cargo JSON for the same body.
Shape of the cargo — disposition + fixer landing (side effects already executed
per soul):

```json
{"converged": true}
```

or, when findings remain:

```json
{
  "converged": false,
  "findingDispositions": [],
  "fixMarkedFindingIdentityKeys": [],
  "fixMarkedFindingThreads": [{"identityKey": "…", "threadId": "…"}]
}
```

When findings remain, emit the **opaque fixer packet** yourself:
`fixMarkedFindingIdentityKeys` + `fixMarkedFindingThreads`. Runner copies
that packet as-is and never derives threads from dispositions.

On a post-fixer fresh re-check include `isRecheck: true` (you own this flag;
Runner never overwrites it) and echo every `fixMarkedFindingIdentityKeys`
value from the landing file before returning `converged:true`; otherwise
return `converged:false`.

### Examples

Completed (role cargo carries converged / findings):

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalation:

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<what blocks the review>"}</onlineReview>
```

Rules:

- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Role cargo never carries escalate — fate is the typed envelope only.
- Execute side effects per Verify soul before emit. Never report
  `converged:true` with unfinished effects — escalate instead. Runner will not
  replay residual plans (#1145 DecisionGate A).
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
