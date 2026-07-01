# Integrated CMR correctness worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/cmr_correctness.md
```

Then follow that soul and the worktree's `CLAUDE.md`. This is the runner-dispatched
step6 correctness gate. The runner only schedules you after step5 completeness has
passed and writes `.cmr-focus.md` plus `.cmr-route.json`; the CMR method lives in
the baked soul and skill, not in this prompt.

## Pass scope

Run only the correctness gate over the complete family base: review behavioral
correctness, cross-slice contracts, and regressions. Do not re-run the completeness
gate in this worker.

## Required output

When the correctness gate has converged (or you must escalate), emit a single
`<cmr>` tag on its own line containing a single JSON object, then print the
completion signal on its own line as the final line.

Converged:

```text
<cmr>{"converged": true, "successfulLegs": ["opus", "gpt-5.5"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": []}</cmr>
CMR_STEP_COMPLETE
```

Not converged:

```text
<cmr>{"converged": false, "reason": "<short>", "successfulLegs": ["opus", "gpt-5.5"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "findings": [{"severity": "medium", "category": "correctness", "claim_quote": "<stable claim>", "location": "<file-or-scope>", "suggested_fix": "<next step>", "action": "defer", "disposition": {"kind": "same_module", "reason": "<why this is still in the family module>"}}]}</cmr>
CMR_STEP_COMPLETE
```

Escalation:

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<why the worker cannot converge>"}}</cmr>
CMR_STEP_COMPLETE
```

Rules:

- The JSON must match one of the shapes above exactly.
- On any converged verdict, `successfulLegs` is REQUIRED and must list the CMR
  leg slugs that actually produced usable reviews in this pass. Use `opus` for
  the Claude/Opus reviewer leg, `gpt-5.5` for the codex leg, and `agy` for the
  Gemini/agy leg.
- If a declared leg was unavailable at runtime, omit it from `successfulLegs` and
  include it in `skippedLegs` with a short visible flag reason. Omit
  `skippedLegs` only when no declared leg was skipped.
- On any converged verdict, `claimedFixedFindingIdentityKeys` and
  `priorFindingDispositions` are REQUIRED. Use empty arrays only when no
  claimed-fixed findings occurred in the CMR loop. If a prior claimed-fixed
  finding exists, include its stable identity key and an explicit disposition:
  `still-active`, `verified-closed`, `unable-to-assess`, or
  `accepted_suppressed`. `accepted_suppressed` requires `source`, `scope`,
  `reason`, and `boundedReopen`.
- On any not-converged verdict, `reason`, `successfulLegs`,
  `claimedFixedFindingIdentityKeys`, and `priorFindingDispositions` are REQUIRED;
  `findings` is optional but must use reviewer finding shape when present.
- For `findings[].disposition.kind`, use exactly one of `same_module`,
  `cross_module`, `spec_conflict`, `infra_failure`,
  `owning_issue_still_red`, or `accepted_suppressed`. Only `cross_module`
  defer may pass without a fix, and only when `.cmr-focus.md` /
  `.cmr-route.json` contain parsed module context supporting it. Do not infer
  module boundaries from titles, prose, or logs. Parser-required fields:
  `same_module` needs `reason`; `cross_module` needs `targetModule` and
  `reason`; `owning_issue_still_red` needs `owningIssue`, `missingSurface`,
  `nextStep`, and `reason`; `spec_conflict` needs `source` and `reason`;
  `infra_failure` needs `source` and `reason`.
- `accepted_suppressed` requires an explicit user/ADR/issue source, matching
  scope, reason, and `boundedReopen`. `findingIdentity` is optional; omit it
  unless a prior finding key was provided, because the runner derives it from
  category, location, and claim quote. `disposition.reason` is the canonical
  rationale; top-level `disposition_reason` may repeat it but is not required.
- Emit the `<cmr>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `CMR_STEP_COMPLETE` on its own line at the very end.
