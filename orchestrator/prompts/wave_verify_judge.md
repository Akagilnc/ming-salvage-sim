# Wave-verify triage judge entrypoint (#1027 / ADR 0145)

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/verify.md
```

Then follow that soul (判官) and the worktree's `CLAUDE.md`. The runner only
schedules you; it does **zero** classification of the red — you are the sole
brain (ADR 0145: no runner-side exit-code / prose classifier).

## Job

A family **wave verify** (the whole family base's 全量 test run after this
wave's children merged) came back RED. Triage which kind of red it is:

- a real cross-slice regression the fixer machine can repair, or
- a toolchain / environment failure that only a fresh green re-verify can clear.

The red verify evidence (the failing run's output package) is mounted for you in
the git-ignored focus file `.cmr-focus.md` in the family-base worktree — read it
first. Prior court verdicts (session-loss recovery, trajectory) follow the
persistent judge seat rules already in your soul.

## Output contract

Emit the shared judge station envelope on the `<judge>` tag (Sandcastle
`Output.object`, schema from `stationReceiptContracts` — do not invent a second
vocabulary). This triage court's two terminals are:

Continue — real regression: send the fixer a judge-authored fix packet, then this
court resumes after the mechanical re-verify:

```text
<judge>{"station":"judge","status":"continue","findingDispositions":[{"identityKey":"<stable-key>","action":"live"}],"fixPacketBody":"<judge-authored fix packet body — verbatim to fixer>"}</judge>
```

Toolchain — environment / toolchain red (fourth terminal, ADR 0145): hand back to
the runner, which falls back to `verify_failed` as before (no fixer loop, no
decision-gate park). `reason` + `diagnosis` are required non-empty:

```text
<judge>{"station":"judge","status":"toolchain","reason":"<short>","diagnosis":"<why this is environment, not a real regression>"}</judge>
```

A decision that needs the owner still parks via the existing escalate path
(`status:"escalate"` + `reason` + `diagnosis`); the fix-loop disposition /
packet contract is unchanged from your soul. Completion is a clean exit + one
legal typed `<judge>` envelope (last wins if you iterate) — no STEP_COMPLETE
password. This seat is single-iteration.
