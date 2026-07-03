# Integrated CMR completeness worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/cmr_completeness.md
```

Then follow that soul and the worktree's `CLAUDE.md`. This is the runner-dispatched
step5 completeness gate. The runner only schedules you and writes `.cmr-focus.md`
plus `.cmr-route.json`; the CMR method lives in the baked soul and skill, not in
this prompt.

## Pass scope

Run only the completeness gate: verify the family base contains every required
slice surface and no slice was structurally swallowed before correctness review.
Do not run the correctness gate in this worker.

## Required output

When the completeness gate has converged (or you must escalate), write the single
JSON object to a draft file first. When `$ORCHESTRATOR_OUTCOME_PATH` is set, do
not write the sidecar or completion output yourself; run the versioned guard:

```bash
orchestrator-outcome-guard \
  --role "cmr" \
  --draft "<draft-json-path>" \
  --outcome "$ORCHESTRATOR_OUTCOME_PATH" \
  --evidence-root "$PWD" \
  --completion-signal "CMR_STEP_COMPLETE"
```

The guard emits the compatibility `<cmr>` tag and completion signal only after
validation passes. If `$ORCHESTRATOR_OUTCOME_PATH` is not set, use the same JSON
shape in the legacy tag/signal output.

Converged:

```text
<cmr>{"converged": true, "successfulLegs": ["opus", "gpt-5.5"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
CMR_STEP_COMPLETE
```

Not converged:

```text
<cmr>{"converged": false, "reason": "<short>", "successfulLegs": ["opus", "gpt-5.5"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "findings": [{"severity": "medium", "category": "correctness", "claim_quote": "<stable claim>", "location": "<file-or-scope>", "suggested_fix": "<next step>", "action": "fix_now", "disposition": {"kind": "same_module", "reason": "<why this is still in the family module>"}}], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
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
- On any converged or not-converged verdict, `evidencePaths` is REQUIRED and must
  list relative paths to existing review/test artifacts under the repo root. Do
  not use absolute paths or `..`; the guard rejects paths it cannot resolve under
  `$PWD`.
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
- Parsed module context comes only from the exact `## Module Declaration`
  fenced YAML block or runner-supplied route/run-option metadata. The supported
  YAML keys are `module` and `module_scope`; undeveloped cross-module targets
  must come from runner-supplied metadata, not issue-body prose or extra YAML
  fields.
- `accepted_suppressed` requires an explicit user/ADR/issue source, matching
  scope, reason, and `boundedReopen`. `findingIdentity` is optional; omit it
  unless a prior finding key was provided, because the runner derives it from
  category, location, and claim quote. `disposition.reason` is the canonical
  rationale; top-level `disposition_reason` may repeat it but is not required.
- When `$ORCHESTRATOR_OUTCOME_PATH` is set, let `orchestrator-outcome-guard` emit
  the `<cmr>` tag and `CMR_STEP_COMPLETE`; do not print them yourself.
- Without `$ORCHESTRATOR_OUTCOME_PATH`, emit the `<cmr>` tag LAST; if you iterate,
  the LAST tag is the one that counts, then print `CMR_STEP_COMPLETE` on its own
  line at the very end.
