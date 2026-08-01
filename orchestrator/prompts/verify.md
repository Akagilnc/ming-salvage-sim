# Online review verify worker (#600 / #940 / #1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` / `.orchestrator-online-review.json` — Collector landing (snapshot / handle / ship metadata / fixerResult)
- `$ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH` — worker durable store + `bin.mjs`
- `$ORCHESTRATOR_OUTCOME_PATH` — role cargo sidecar when set

**Method truth lives in the Verify soul** (`image/souls/verify.md`). This file is params + envelope only.

## Required output

Emit **one** typed `<onlineReview>` station-receipt envelope (tag `onlineReview`). JSON only inside the tag.

| field | meaning |
| --- | --- |
| `station` | `"onlineReview"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo |
| `reason` / `diagnosis` | required when `status:"escalate"` |

Completed (role cargo carries typed `status: converged | continue | escalate`
and optional single opaque `onlineReviewFixPacket` on sidecar):

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalate:

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<block>"}</onlineReview>
```

Role cargo is opaque (not SO-validated). Fate is the typed envelope only. Single-iteration seat; clean exit + legal envelope.
