# Reviewer worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/reviewer.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; review method and input handling belong to the role soul (live-mounted) plus runner
parameters.

## Required output

When you are done (or are escalating), the real completion evidence is the
single JSON object written to `$ORCHESTRATOR_OUTCOME_PATH` when that env var is
set and the typed `<review>` outcome. For compatibility with older runners,
emit EXACTLY ONE `<review>` tag on its own containing the same single JSON
object. The completion signal is optional telemetry and may be printed as an
extra line.

Success:

```text
<review>{"findingsCount":0,"findings":[]}</review>
```

With findings:

```text
<review>{"findingsCount":1,"findings":[{"severity":"high","category":"correctness","claim_quote":"<short>","location":"path:line","suggested_fix":"<short>","action":"fix_now"}]}</review>
```

`findingsCount` is the self-reported open-count the runner routes on (ADR 0131 /
#899). It is required on every verdict. `findings` rows are cargo for the next
fixer and must not be used by the runner as a substitute for a missing count.

Report each active finding with only its body (`severity`, `category`,
`claim_quote`, `location`, `suggested_fix`) plus an `action`. Do not emit routing
disposition kinds — there are none. P0/P1 findings (`critical`/`high`) must always
use `action:"fix_now"`. Every finding you report is blocking: the runner reads
your `findingsCount` and sends cargo back through coder-fix. There is no pass to another module — if a gap is real, report it as a concrete fix.

Do not emit `accepted_suppressed`, `wont_fix`, or `rejected` from this standalone
reviewer worker. This runner path has no trusted suppression-source input, so an
accepted suppression emitted here would fail closed and create an unnecessary
fix loop. If an explicit user decision, accepted ADR, or named issue acceptance
text already accepts a bounded risk, omit that accepted risk as a finding unless
the current diff exceeds the accepted bound, changes scope, or increases
severity; in that case report the concrete active gap with `fix_now`.

When the runner supplies prior claimed-fixed findings for a fresh re-review,
it exposes them at `$ORCHESTRATOR_FIX_FINDINGS_PATH` as JSON. Read that file,
classify every prior finding explicitly in `priorFindingDispositions`, and use the
runner-provided `identityKey` and one of:
`still-active`, `verified-closed`, or `unable-to-assess`. Do not emit
`accepted_suppressed` in `priorFindingDispositions`; if the only apparent closure
is an owner-accepted risk that the runner did not supply as trusted data, classify
it as `unable-to-assess` with a short reason instead of inventing a terminal
suppression. Do not rely on omitting a finding to mean it is closed.

The same JSON may contain `escalationAnswer` when this is a resumed reviewer
decision escalation. Apply that human answer before reviewing, and do not repeat
the same escalation unless the answer leaves a concrete blocker unresolved.

```text
<review>{"findingsCount":0,"findings":[],"priorFindingDispositions":[{"identityKey":"<prior-key>","status":"verified-closed","reason":"<short>"}]}</review>
```

Escalation:

```text
<review>{"findingsCount":0,"findings":[],"escalate":{"reason":"<short>","diagnosis":"<what blocks review>"}}</review>
```

For optional telemetry, you may print REVIEWER_STEP_COMPLETE on its own final line.
