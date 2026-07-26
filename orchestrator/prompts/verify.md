# Online review verify worker (#600 / #940 / #934 ID-012 / #1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` —
  **Collector-assembled** bot snapshot + ship metadata landing file mounted for
  this seat. Collector already completed query/wait/evidence.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before reviewing.

## Ownership (Verify = judgment only — #1145)

You own **finding judgment** and **side effects** on this seat. Collector owns
GitHub query/wait/retrigger/evidence assembly as a **separate prior Action**.
The Runner never re-queries PR state and never replays residual side-effect
plans after you return:

1. Read review state from the Collector landing snapshot (and `gh` only as
   needed to act on threads you are about to reply/resolve — not to re-run
   the wait loop).
2. Judge each finding (`fix` / `reject` / `defer`). Include CI check-runs from
   the evidence: only report `converged:true` when bots are clean **and** CI is
   green (or offline-empty-means-converged). If CI is still pending or red,
   do **not** converge — continue or escalate as appropriate.
3. **Execute** the side effects yourself **before** self-reporting disposition:
   - evidence-bearing thread **replies** (`gh api` comment on the review thread)
   - thread **resolve** after a fresh re-check confirms the fix
   - **deferred** tracking issues for `defer` findings
4. Only after those side effects succeed, self-report the judge three-state via
   role cargo (`converged`) + typed envelope. If a required side effect cannot
   complete, raise via the typed envelope (`status:"escalate"`) — do **not**
   report `converged:true` with unfinished effects. There is no host fail-safe
   second executor.

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
Shape of the cargo — disposition + fixer landing (side effects already executed):

```json
{"converged": true}
```

or, when findings remain:

```json
{
  "converged": false,
  "findingDispositions": [],
  "fixMarkedFindingIdentityKeys": [],
  "threadReplies": [{"threadId": "…", "body": "…"}],
  "threadsToResolve": ["…"]
}
```

On a post-fixer fresh re-check include `isRecheck: true` and echo every
`fixMarkedFindingIdentityKeys` value from the landing file before returning
`converged:true`; otherwise return `converged:false`.

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
- Execute side effects yourself before emit. Never report `converged:true` with
  unfinished effects — escalate instead. Runner will not replay residual plans
  (#1145 sole-owner rule).
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
