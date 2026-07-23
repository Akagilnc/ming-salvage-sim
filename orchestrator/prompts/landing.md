# Landing worker entrypoint (#941 / S12)

## Required output

Write landing cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set:

```json
{"released": true}
```

or

```json
{"released": false}
```

Emit **one** typed `<onlineReview>` station-receipt envelope
(`status:"completed"` | `"escalate"`). Role cargo never carries escalate.

Sandcastle validates the traffic shape via `Output.object` against the T2
contract (`onlineReviewStationReceiptSchema` / tag `onlineReview`). Emit
**JSON only** inside the tag — never YAML or prose.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"onlineReview"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

### Completed (no decision gate)

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

### Escalate (decision gate)

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<what blocks landing>"}</onlineReview>
```

- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Do not invent a second field vocabulary or a separate decision-gate dual tag.
