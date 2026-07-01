# Integrated CMR worker entrypoint

Read the baked role soul first:

```text
/home/agent/.orchestrator/souls/cmr.md
```

Then follow that soul and the worktree's `CLAUDE.md`. The runner only schedules
you and writes `.cmr-focus.md`; the CMR method lives in the baked soul and skill,
not in this prompt.

## Required output

When the review has converged (or you must escalate), emit a single `<cmr>` tag on
its own line containing a single JSON object, then print the completion signal on
its own line as the final line.

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
  `still-active`, `verified-closed`, or `unable-to-assess`.
- On any not-converged verdict, `reason`, `successfulLegs`,
  `claimedFixedFindingIdentityKeys`, and `priorFindingDispositions` are REQUIRED;
  `findings` is optional but must use reviewer finding shape when present.
- For `findings[].disposition.kind`, use exactly one of `same_module`,
  `cross_module`, `spec_conflict`, `infra_failure`,
  `owning_issue_still_red`, or `accepted_suppressed`. Only `cross_module`
  defer may pass without a fix, and only when `.cmr-focus.md` /
  `.cmr-route.json` contain parsed module context supporting it. Do not infer
  module boundaries from titles, prose, or logs.
- `accepted_suppressed` requires an explicit user/ADR/issue source, matching
  scope, reason, finding identity, and bounded reopen condition.
- Emit the `<cmr>` tag LAST; if you iterate, the LAST tag is the one that counts.
- Always print `CMR_STEP_COMPLETE` on its own line at the very end.
