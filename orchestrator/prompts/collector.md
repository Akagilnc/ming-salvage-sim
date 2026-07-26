# Online Review Collector worker (#1145)

## Params

- `$ORCHESTRATOR_ONLINE_REVIEW_PATH` or `.orchestrator-online-review.json` —
  ship metadata + optional prior round fix-marked keys. May lack evidence on
  first entry; you assemble it.
- Round / PR URL / head from the landing file and env.

If ship metadata carries `pr://slice/branch-cargo/<encoded-branch>` instead of a
PR URL, URL-decode `<encoded-branch>` first, then resolve the PR yourself with
`gh pr view <decoded-branch>` before collecting.

## Ownership (Collector only — #1145)

You own **GitHub query, necessary wait, post-fix retrigger, and evidence
assembly**. You do **not** judge findings and you do **not** emit judge enum
(`converged` / fix dispositions). Verify is a separate seat.

1. Read landing ship metadata (PR URL, round, fix-marked keys when recheck).
2. When round ≥ 2 or a fresh fix head is present, post the bot re-trigger
   comment yourself if one is not already admissible for this head.
3. Query PR comments / reviews / reactions / check-runs / threads via single
   `gh` / `gh api` fetches. Between fetches you may sleep once; **you** decide
   when to fetch again and when this round's evidence is complete. Do not rely
   on a host loop to judge pending / valid / unavailable / missing / terminal.
4. When evidence is complete, write opaque evidence cargo and exit cleanly.
5. If you cannot continue (auth, rate limit, missing PR), escalate via the
   typed `<onlineReview>` envelope — never invent a green judgment.

Shared GitHub retry helpers (if present in the image) are single-call transport
only. Completeness is your call.

## Required output

Emit **one** typed `<onlineReview>` station-receipt envelope
(`station:"onlineReview"`, `status:"completed"|"escalate"`) — same T2 contract
as other online-review seats. Role cargo is opaque evidence only:

Write collector cargo to `$ORCHESTRATOR_OUTCOME_PATH` when set, and/or emit
opaque `<collector>` cargo JSON:

```json
{
  "evidence": {
    "prUrl": "…",
    "headOid": "…",
    "totalFindingCount": 0,
    "quiescent": true,
    "bots": {},
    "droppedBots": [],
    "threads": [],
    "checkRuns": [],
    "checkRunsEmptyMeans": "converged"
  }
}
```

Rules:

- Emit exactly one final `<onlineReview>` envelope (last wins if you iterate).
- Role cargo never carries escalate or judge enum — fate is the typed envelope;
  judgment is Verify's job.
- Do not set `converged`, `findingDispositions`, or fixer plan fields.
- This seat is single-iteration. Completion is clean exit + legal typed
  envelope / sidecar — no STEP_COMPLETE password.
