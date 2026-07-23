# Judge open court (resident slice birth) — #1081 / ADR 0147

Follow the worktree's `CLAUDE.md`.

## Runtime inputs

- Issue / repo env for live-fetch when the soul requires it at birth.
- This beat is lifecycle bookkeeping only (open court); later S3/S6 resume the
  same session.

## Typed receipt

Emit a court-ready ack on the official `<judge>` tag. Reuse existing
`converged` (zero new JudgeVerdictStatus — ADR 0147). This ack is **not**
product convergence; the runner treats open-court completion as lifecycle
bookkeeping only and never routes it through the S3/S6 edge table.

```xml
<judge>{"station":"judge","status":"converged"}</judge>
```

Completion is clean exit + legal typed envelope / sidecar — no STEP_COMPLETE
password. Finish inside the single iteration.
