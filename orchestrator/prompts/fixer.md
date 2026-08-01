# Online review fixer worker (#600)

## Params

- `.orchestrator-online-review.json` — Collector evidence plus the judge's single opaque `onlineReviewFixPacket`.

After the fixing commit lands, push it to the PR branch for bot re-review —
this loop's submission transport (the worker performs the push).
The role cargo remains only the JSON body defined below.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set (role cargo only), the always-emitted typed `<onlineReview>` station-receipt
envelope, and any optional opaque `<fixer>` cargo tag.

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

Thin gate only: completed \| escalate. Commit narrative is cargo, never a fate
signal on this envelope.

### Role cargo (opaque; not SO-validated)

Write fixer cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set (sidecar is cargo
transport). You may also emit opaque `<fixer>` cargo JSON for the same body:

```json
{"committed": true, "fixCommitSha": "<the-commit-sha-you-just-made>"}
```

when you committed a new fix this turn (report the fixing commit SHA you just
created);

```json
{"committed": false, "alreadySatisfied": true, "fixCommitSha": "<current-branch-HEAD>"}
```

when the assigned fix-marked finding(s) are **already resolved** on the current
branch (e.g. a prior crashed attempt already landed the fix) — proceed to verify,
not a park;

or `{"committed": false}` when the assigned finding(s) are **genuinely still
present** and you made no new commit (pair with envelope `completed`; runner
routes on process + envelope, not cargo shape).

### Examples

Completed:

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalation:

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<what blocks the fix>"}</onlineReview>
```

Rules:

- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Role cargo never carries escalate — fate is the typed envelope only.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
