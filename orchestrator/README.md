# Orchestrator checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as `npm run typecheck:test`) before Vitest. That TypeScript lane checks all of
`test/**`, so every test fixture and mock must satisfy the current production
contracts before the behavioral suite runs.

## Telemetry sidecar (#786)

Append-only JSONL at the durable ledger location
`<ledgerDir>/telemetry.jsonl`, parallel to the step ledger (`steps.jsonl`). For
single-slice runs this is `<dedicated-clone>/.ledger-<issue>/`; it is outside
Sandcastle's `.sandcastle/worktrees/` prune scope. Family runs use their
existing durable family `ledgerDir`. Raw per-leg stamps only — aggregation /
stats are out of scope for #786.

The durable telemetry directory is never automatically deleted. The former
`.sandcastle/worktrees/.ledger-<issue>/telemetry.jsonl` path is retained as a
read-only migration fallback for offline readers and is not a write target.

Phases (one JSON object per line):

| phase | when | contents |
| --- | --- | --- |
| `environment` | once per run | image / route lineup / CLI versions |
| `dispatch` | at spawn | identity / model / pool / `dispatched_at` |
| `collect` | at finish | terminal / tokens / session / log / `first_output_at` / `completed_at` |
| `review_round` | each integrated CMR verdict | pass / verdict / severity counts / identity-key recurrence / prior-finding dispositions |

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

### `review_round` semantics

`review_round` is an append-only observation after the integrated-CMR runner has
finished its terminal gates. `finalDisposition` says whether that runner accepted
the review result; rejected rows are telemetry only and never alter routing.
`findingsBySeverity`, identity-key lists, and closure dispositions are `null` when
the worker did not produce a parseable CMR payload. `identityMatch` is always
`exact_identity_match`: keys already present in earlier rows of the same pass are
`recurringExactIdentityMatchKeys`; the remainder are
`newExactIdentityMatchKeys`. This is exact matching on category, location, and
normalized `claim_quote`, not semantic deduplication: wording or line-number
drift can make a recurring finding appear new. Fresh re-review dispositions map
to `fixed`
(`verified-closed`), `refuted` (`accepted_suppressed`), or `deferred`
(`still-active` / `unable-to-assess`). These rows are telemetry only: they have no
review, fix-loop, or ADR 0062 routing authority.

Field-level JSDoc lives on `TelemetryCollectRecord.first_output_at` in
`src/telemetry.ts`; the stamp site is `noteFirstOutputIfPastBaseline` /
`reconcileFirstOutputAt` in `src/dispatchWorker.ts`.
