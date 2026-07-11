# Integrated CMR correctness worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/cmr_correctness.md
```

Then follow that soul and the worktree's `CLAUDE.md`. This is the runner-dispatched
step6 correctness gate. The runner only schedules you after step5 completeness has
passed and writes `.cmr-focus.md` plus `.cmr-route.json`; the CMR method lives in
the role soul (live-mounted) and baked skill, not in this prompt.

## Pass scope

Run only the correctness gate over the complete family base: review behavioral
correctness, cross-slice contracts, and regressions. Do not re-run the completeness
gate in this worker.

## Required output

When the correctness gate has converged (or you must escalate), write the single
JSON object to a draft file first. When `$ORCHESTRATOR_OUTCOME_PATH` is set, do
not write the sidecar or completion output yourself; run the versioned guard:

```bash
orchestrator-outcome-guard \
  --role "cmr" \
  --draft "<draft-json-path>" \
  --outcome "$ORCHESTRATOR_OUTCOME_PATH" \
  --evidence-root "$PWD" \
  --completion-signal "<COMPLETION_SIGNAL>"
```

After validation, the guard may emit the compatibility `<cmr>` tag and completion
signal as optional telemetry. If `$ORCHESTRATOR_OUTCOME_PATH` is not set, use the
same JSON shape in the legacy tag/signal output.

Converged:

```text
<cmr>{"converged": true, "successfulLegs": ["opus", "gpt-5.6-sol"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
```

Not converged:

```text
<cmr>{"converged": false, "reason": "<short>", "successfulLegs": ["opus", "gpt-5.6-sol"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "findings": [{"severity": "medium", "category": "correctness", "claim_quote": "<stable claim>", "location": "<file-or-scope>", "suggested_fix": "<next step>", "action": "fix_now"}], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
```

Escalation:

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<why the worker cannot converge>"}}</cmr>
```

Rules:

- The JSON must match one of the shapes above exactly.
- On any converged verdict, `successfulLegs` is REQUIRED and must list the CMR
  leg slugs that actually produced usable reviews in this pass. Use `opus` for
  the Claude/Opus reviewer leg, `gpt-5.6-sol` for the codex leg, and `agy` for the
  Gemini/agy leg.
- If a declared leg was unavailable at runtime, omit it from `successfulLegs` and
  include it in `skippedLegs` with a short visible flag reason. Omit
  `skippedLegs` only when no declared leg was skipped.
- On any converged verdict, `claimedFixedFindingIdentityKeys` and
  `priorFindingDispositions` are REQUIRED. Use empty arrays only when no
  claimed-fixed findings occurred in the CMR loop. If a prior claimed-fixed
  finding exists, include its stable identity key and an explicit disposition
  using the exact JSON field name `status`, for example
  `{"identityKey":"<key>","status":"verified-closed","reason":"<short>"}`.
  Valid `status` values are `still-active`, `verified-closed`, and
  `unable-to-assess`. Do not use a field named `disposition`.
  Runner-supplied claimed-fixed findings are protected blockers: do not use
  `accepted_suppressed` to close them. If an owner/ADR/issue-backed scope
  exception is now implemented in code/docs/tests, mark the prior finding
  `verified-closed` and cite that source in `reason`; otherwise mark it
  `still-active`.
- On any not-converged verdict, `reason`, `successfulLegs`,
  `claimedFixedFindingIdentityKeys`, and `priorFindingDispositions` are REQUIRED;
  `findings` is optional but must use reviewer finding shape when present.
  Any `priorFindingDispositions` entries in this not-converged shape must use the
  same `{"identityKey":"<key>","status":"...","reason":"<short>"}` contract
  above; valid `status` values remain `still-active`, `verified-closed`, and
  `unable-to-assess`. Do not use a field named `disposition`.
- On any converged or not-converged verdict, `evidencePaths` is REQUIRED and must
  list relative paths to existing review/test artifacts under the repo root. Do
  not use absolute paths or `..`; the guard rejects paths it cannot resolve under
  `$PWD`.
- Report each active finding with only its body (`severity`, `category`,
  `claim_quote`, `location`, `suggested_fix`) plus an `action`. Do not emit routing
  disposition kinds — there are none. Every finding you report that is not an
  accepted suppression is blocking: the runner counts it and routes it through
  coder-fix. There is no pass to another module — if a family-scope gap is real,
  report it with `action:"fix_now"`. The only `findings[].disposition.kind` you may
  emit is `accepted_suppressed`.
- Any module-scope judgement you make (which files/surfaces belong to the family
  module, whether a target is an out-of-scope undeveloped module, whether an
  `accepted_suppressed` scope matches) draws its module context ONLY from the exact
  `## Module Declaration` fenced YAML block (supported keys `module` and
  `module_scope`) or runner-supplied route/run-option metadata. Do not infer module
  boundaries from issue-body prose, titles, or logs. Undeveloped out-of-scope
  targets come from runner-supplied metadata, not issue-body prose or extra YAML
  fields, and must never be written into the issue-body YAML.
- `accepted_suppressed` requires an explicit user/ADR/issue source, matching
  scope, reason, and `boundedReopen`. `findingIdentity` is optional; omit it
  unless a prior finding key was provided, because the runner derives it from
  category, location, and claim quote. `disposition.reason` is the canonical
  rationale; top-level `disposition_reason` may repeat it but is not required.
  Use `accepted_suppressed` only for new reviewer findings that are outside the
  runner-supplied claimed-fixed closure set. An `accepted_suppressed` disposition
  MUST be paired with `action:"wont_fix"` or `action:"rejected"` — never with
  `action:"fix_now"` (that would silently turn the governance suppression into a
  blocker).
- When `$ORCHESTRATOR_OUTCOME_PATH` is set, completion is judged by the validated
  sidecar JSON and typed CMR outcome; let `orchestrator-outcome-guard` emit the
  `<cmr>` tag and optional completion telemetry.
- Without `$ORCHESTRATOR_OUTCOME_PATH`, emit the `<cmr>` tag LAST; if you iterate,
  the LAST tag is the one that counts.
- For optional telemetry, you may print CMR_STEP_COMPLETE on its own final line.
