# Orchestrator checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as `npm run typecheck:test`) before Vitest. That TypeScript lane checks all of
`test/**`, so every test fixture and mock must satisfy the current production
contracts before the behavioral suite runs.

## Telemetry sidecar (#786)

Append-only JSONL at `<ledgerDir>/telemetry.jsonl`, parallel to the step ledger
(`steps.jsonl`). Raw per-leg stamps only — aggregation / stats are out of scope
for #786.

Phases (one JSON object per line):

| phase | when | contents |
| --- | --- | --- |
| `environment` | once per run | image / route lineup / CLI versions |
| `dispatch` | at spawn | identity / model / pool / `dispatched_at` |
| `collect` | at finish | terminal / tokens / session / log / `first_output_at` / `completed_at` |

Join key: `legId` on a dispatch+collect pair. Unobtainable fields are `null`;
telemetry I/O is fail-open and must never block the worker path.

### `first_output_at` precision (poll granularity — not true TTFB)

`first_output_at` is the wall-clock when the orchestrator **first observed**
worker log growth past the post-spawn marker. It is **not** true first-byte /
time-to-first-token.

| scenario | what the stamp means | error bound |
| --- | --- | --- |
| Long-running worker | Idle monitor poll that first sees `log size > baseline` | ≈ `pollIntervalMs` (default **250ms** in `dispatchWorker`) |
| Quick-exit (exit wins race before any poll sees growth) | One-shot post-exit reconcile re-read | ≈ **process exit time** (may be much later than true first byte) |
| No post-marker growth by collect time | Field is `null` | — |

Consumers computing “time-to-first-output” as
`first_output_at − dispatched_at` must treat the result as **poll-quantized**,
not sub-poll TTFB. When non-null the monotonic order holds:

`dispatched_at ≤ first_output_at ≤ completed_at`.

Field-level JSDoc lives on `TelemetryCollectRecord.first_output_at` in
`src/telemetry.ts`; the stamp site is `noteFirstOutputIfPastBaseline` /
`reconcileFirstOutputAt` in `src/dispatchWorker.ts`.
