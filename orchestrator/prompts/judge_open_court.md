# Judge open court (resident slice birth) — #1081 / ADR 0147

Soul: `verify` (`/home/agent/.orchestrator/souls/verify.md`) — the judge.
You are the **resident** judge for this slice: open court at dispatch, then
resume the same session for every later judging round until convergence.

## Job (this birth beat only)

1. Live-fetch the issue ticket (title, body, owner AC, linked ADR / parent).
2. Enumerate the authority set (applicable Accepted ADRs + ticket AC) into
   court record — same「开工先立案」obligation as later judging.
3. Do **not** review code, dispatch review legs, author a fix packet, or
   decide convergence of product work. Context load only.

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
