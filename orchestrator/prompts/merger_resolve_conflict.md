# Merger worker entrypoint — resolve one family-merge conflict

The runner attempted a deterministic `git merge --no-ff` of a reviewed child
slice into the family base, hit a conflict, and left the markers in the working
tree. Resolve **this one in-progress merge** and return.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set (resolve cargo only), the always-emitted typed `<merger>` station-receipt
envelope, and the actual merge/git state.

Emit **one** typed `<merger>` station-receipt envelope. Sandcastle validates the
traffic shape via `Output.object` against the T2 contract in
`orchestrator/src/stationReceiptContracts.ts` (`mergerStationReceiptSchema` /
`decodeMergerEnvelope`, tag `merger` / `MERGER_RECEIPT_TAG`) — **do not invent a
second field vocabulary** and **do not emit a separate decision-gate dual tag**.

### Envelope traffic fields (schema-validated)

| field | meaning |
| --- | --- |
| `station` | `"merger"` |
| `status` | `"completed"` \| `"escalate"` |
| `cargoPointer` | optional non-empty path/URI to opaque cargo body |
| `reason` / `diagnosis` | required non-empty when `status:"escalate"` |

Thin gate only: completed \| escalate. Resolve narrative is never a fate signal.

### Resolve cargo (opaque; not SO-validated)

Write resolve cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set. Prefer the sidecar
over inventing a second SO schema — resolve cargo stays outside Output.object.

Success / resolved (sidecar):

```json
{"resolved": true, "tradeoffs": "<one line: any side picked / note, or empty>"}
```

- `resolved` (boolean): did you resolve the conflict and commit the merge?
- `tradeoffs` (string, optional): a one-line note of any incompatible hunk where
  you had to pick one side (empty string if both intents were preserved cleanly).

Unresolved / escalate cargo (sidecar; pair with envelope `escalate`):

```json
{"resolved": false}
```

### Examples

Completed (conflict resolved + merge commit):

```text
<merger>{"station":"merger","status":"completed"}</merger>
```

(+ sidecar `{"resolved":true,"tradeoffs":"..."}` when
`$ORCHESTRATOR_OUTCOME_PATH` is set)

Escalation (a conflict you must NOT guess at — surface it to a human):

```text
<merger>{"station":"merger","status":"escalate","reason":"<short>","diagnosis":"<why this conflict cannot be resolved without a decision>"}</merger>
```

Rules:

- Emit exactly one final `<merger>` envelope (last wins if you iterate).
- Never `git merge --abort`. Never invent behaviour. Resolve or escalate.
- Illegal traffic shape is re-asked in-session by Sandcastle; do not rely on the
  runner to guess a status.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
