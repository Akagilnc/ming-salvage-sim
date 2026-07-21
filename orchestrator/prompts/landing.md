# Landing worker entrypoint (#941 / S12 — atomic rename+expand of docRelease)

Soul: `landing` (`/home/agent/.orchestrator/souls/landing.md`)

Invoke the baked **`/gstack-document-release`** skill on the current PR head
branch (non-interactive / spawned session). Do not invent a parallel doc-writing
method outside the skill. After you report `released:true`, the host Landing
Action continues with merge / live MERGED confirm / issue close / cleanup
(ID-013) — you do not open a second seat or flow baton.

## Success contract

- Skill finishes successfully, **including empty-run** (no doc debt, no
  commit) → report `released: true`.
- If the skill created a commit, **you** push it to the PR head branch before
  reporting success.
- **Retry / residual HEAD**: if local branch is **ahead of remote PR tip**,
  push that ahead HEAD even when this skill run is empty. `released:true`
  requires remote tip to match local HEAD when local was ahead.

## Failure

Worker crash, non-interactive hang/block, explicit skill failure, or required
push failure → `released: false` (or no valid role cargo). Use envelope
`escalate` only when a human decision is required.

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
