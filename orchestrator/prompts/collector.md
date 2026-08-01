# Online Review Collector worker (#1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` / `.orchestrator-online-review.json` — ship metadata landing
- `$ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH` — worker durable store + `bin.mjs`
- Round / PR / head from landing + env

**Method truth lives in the Collector soul** (`image/souls/collector.md`). This file is params + envelope only.

## Required output

Emit **one** typed `<onlineReview>` station-receipt envelope (tag `onlineReview`). JSON only inside the tag.

| field | meaning |
| --- | --- |
| `station` | `"onlineReview"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque evidence |
| `reason` / `diagnosis` | required when `status:"escalate"` |

Completed:

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalate:

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<block>"}</onlineReview>
```

Opaque evidence cargo (sidecar / handle) is optional on completed (ADR 0131 cargo ≠ fate). Single-iteration seat; clean exit + legal envelope.
