# 文档发布 worker entrypoint (#735 / S12)

Soul: `docRelease` (`/home/agent/.orchestrator/souls/docRelease.md`)

Invoke the baked **`/gstack-document-release`** skill on the current PR head
branch (non-interactive / spawned session — auto-decide VERSION-bump style
prompts; do not hang waiting for a human). Do not invent a parallel doc-writing
method outside the skill.

## Success contract

- Skill finishes successfully, **including 文档发布空跑** (no doc debt, no
  commit) → report `released: true`.
- If the skill created a commit, **you** push it to the PR head branch before
  reporting success. Push is part of S12 success; a local-only commit must not
  unlock merge against a stale remote tip.
- **Retry / residual HEAD**: if local branch is **ahead of remote PR tip**
  (e.g. prior attempt committed then crashed before push, and mechanical retry
  preserved that commit), **push that ahead HEAD** even when this skill run is
  a 文档发布空跑 with no *new* commit. `released:true` requires remote tip to
  match local HEAD when local was ahead.
- Do **not** wait for CI green inside this step. Merge-stage live readiness is
  the single wait point for checks / threads / ruleset.

## Failure

Worker crash, non-interactive hang/block, explicit skill failure, or required
push failure → `released: false` (or no valid role cargo). Auto-merge must not
proceed. Use envelope `escalate` only when a human decision is required; ordinary
skill/push failure is process failure or `released:false` cargo with
`status:"completed"`.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set (role cargo only), the always-emitted typed `<onlineReview>` station-receipt
envelope, and any optional opaque `<docRelease>` cargo tag.

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

Thin gate only: completed \| escalate. Released flag is cargo, never a fate
signal on this envelope.

### Role cargo (opaque; not SO-validated)

Write docRelease cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set (sidecar is
cargo transport). You may also emit opaque `<docRelease>` cargo JSON. Thin
schema only:

```json
{"released": true}
```

or

```json
{"released": false}
```

### Examples

Completed:

```text
<onlineReview>{"station":"onlineReview","status":"completed"}</onlineReview>
```

Escalation (human decision required):

```text
<onlineReview>{"station":"onlineReview","status":"escalate","reason":"<short>","diagnosis":"<what blocks doc release>"}</onlineReview>
```

Rules:

- `kind` is implied by the role; JSON body is `{ "released": boolean }` only.
- No path-allowlist self-check is a success criterion (ADR 0123).
- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Role cargo never carries escalate — fate is the typed envelope only.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
