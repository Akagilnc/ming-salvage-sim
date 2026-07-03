# Reviewer worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/reviewer.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you; review method and input handling belong to the baked soul plus runner
parameters.

## Required output

When you are done (or are escalating), write the single JSON object to
`$ORCHESTRATOR_OUTCOME_PATH` when that env var is set. Then, for compatibility
with older runners, emit EXACTLY ONE `<review>` tag on its own containing the same
single JSON object, and print the completion signal on its own line.

The sidecar file must contain only the raw JSON object: no `<review>` tag, no
completion signal, and no surrounding prose. After writing it, run
`python3 -m json.tool "$ORCHESTRATOR_OUTCOME_PATH" >/dev/null`; if that command
fails, rewrite the sidecar and rerun the check. Do not emit the compatibility
tag or completion signal until this parser check succeeds.

Success:

```text
<review>{"findings":[]}</review>
REVIEWER_STEP_COMPLETE
```

With findings:

```text
<review>{"findings":[{"severity":"high","category":"correctness","claim_quote":"<short>","location":"path:line","suggested_fix":"<short>","action":"fix_now"}]}</review>
REVIEWER_STEP_COMPLETE
```

Deferred findings must carry a machine-verifiable `disposition`.
Use one of:
`same_module`, `cross_module`, `spec_conflict`, `infra_failure`,
`owning_issue_still_red`.

P0/P1 findings (`critical`/`high`) must always use `action:"fix_now"`.
For P2/P3 `action:"defer"`, only `cross_module` may pass without a fix, and it
must include `targetModule` and `reason`. Other disposition kinds must include
their parser-required fields: `same_module` needs `reason`;
`owning_issue_still_red` needs `owningIssue`, `missingSurface`, `nextStep`, and
`reason`; `spec_conflict` needs `source` and `reason`; `infra_failure` needs
`source` and `reason`. Same-module gaps, owning-issue still-red gaps, spec
conflicts, and infra failures fail closed through the runner rather than
silently passing.

Do not emit `accepted_suppressed`, `wont_fix`, or `rejected` from this standalone
reviewer worker. This runner path has no trusted suppression-source input, so an
accepted suppression emitted here would fail closed and create an unnecessary
fix loop. If an explicit user decision, accepted ADR, or named issue acceptance
text already accepts a bounded risk, omit that accepted risk as a finding unless
the current diff exceeds the accepted bound, changes scope, or increases
severity; in that case report the concrete active gap with `fix_now` or the
appropriate non-passing disposition above.

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
<review>{"findings":[],"priorFindingDispositions":[{"identityKey":"<prior-key>","status":"verified-closed","reason":"<short>"}]}</review>
REVIEWER_STEP_COMPLETE
```

Escalation:

```text
<review>{"findings":[],"escalate":{"reason":"<short>","diagnosis":"<what blocks review>"}}</review>
REVIEWER_STEP_COMPLETE
```
