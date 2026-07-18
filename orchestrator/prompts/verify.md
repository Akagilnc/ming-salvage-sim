# Online review verify worker (#600 / #940 / #934 ID-012)

Soul: `verify` (`/home/agent/.orchestrator/souls/verify.md`)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` — bot snapshot + ship metadata landing file mounted by the runner.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before reviewing.

## Ownership (worker-executed first; host fail-safe applicator)

You own **finding judgment** on this seat and should execute GitHub side effects
yourself before self-reporting. The host also applies remaining cargo plan fields
as a fail-safe so reply/resolve/deferred still land when you only emit the plan:

1. Read live review state from the landing snapshot / `gh` as needed.
2. Judge each finding (`fix` / `reject` / `defer`).
3. **Execute** the side effects yourself **before** self-reporting disposition:
   - evidence-bearing thread **replies** (`gh api` comment on the review thread)
   - thread **resolve** after a fresh re-check confirms the fix
   - **deferred** tracking issues for `defer` findings
4. Only after those side effects succeed (or when you must hand a residual plan to
   the host fail-safe), self-report the judge three-state via role cargo
   (`converged`) + typed envelope. If a required side effect cannot complete and
   you cannot leave a well-typed plan the host can apply, raise via the typed
   envelope (`status:"escalate"`) — do **not** report `converged:true` with
   unfinished effects and no residual plan.

Shared GitHub retry helpers (if present in the image) are for mechanical calls.
Host fail-safe applies well-typed `threadReplies` / `threadsToResolve` /
`deferredIssueUrls` cargo before accepting mergeable.

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
Shape of the cargo — disposition + fixer landing, plus optional host fail-safe
plan fields when residual effects remain:

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
- Prefer executing side effects yourself before emit. Residual well-typed plan
  fields (`threadReplies` / `threadsToResolve` / `deferredIssueUrls`) remain
  legal cargo for the host fail-safe when you cannot finish every effect
  yourself. Never report `converged:true` with unfinished effects and no
  residual plan (same dual-owner rule as Ownership above).
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
