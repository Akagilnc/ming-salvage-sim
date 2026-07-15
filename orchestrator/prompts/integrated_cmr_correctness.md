# Integrated CMR correctness worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/cmr_correctness.md
```

Then follow that soul (审卷官 character; symlink → `verify.md`) and the
worktree's `CLAUDE.md`. This is the runner-dispatched step6 correctness gate.
The runner only schedules you after step5 completeness has passed and writes
`.cmr-focus.md` plus `.cmr-route.json`.

**Invoke `ak-cmr-correctness` only** (this pass's skill). Do not re-run
completeness. You judge the review surface; do not repair code or create fix
commits.

## Pass scope

Run only the correctness gate over the complete family base: review behavioral
correctness, cross-slice contracts, and regressions. Do not re-run the completeness
gate in this worker.

## Required output

When the review is complete, emit `findings = x` on its own line, replacing `x`
with the number of findings. This fragment is required even when the count is 0.
A converged judgement declares `findings = 0`. A not-converged judgement declares
at least `findings = 1`; without an itemized finding list, declare `findings = 1`
and explain the reason in the review body, which the fixer reads.

Converged:

```text
<cmr>{"converged": true, "findingsCount": 0, "successfulLegs": ["opus", "gpt-5.6-sol"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
```

Not converged:

```text
<cmr>{"converged": false, "reason": "<short>", "findingsCount": 1, "successfulLegs": ["opus", "gpt-5.6-sol"], "skippedLegs": [{"slug": "agy", "reason": "quota unavailable"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "findings": [{"severity": "medium", "category": "correctness", "claim_quote": "<stable claim>", "location": "<file-or-scope>", "suggested_fix": "<next step>", "action": "fix_now"}], "evidencePaths": ["cmr/review-summary.json"]}</cmr>
```

Escalation:

```text
<cmr>{"escalate": {"reason": "<short>", "diagnosis": "<why the worker cannot converge>"}}</cmr>
```

Rules:

- The JSON should match one of the shapes above. **Typed SO (Sandcastle
  maxRetries) only requires `findingsCount`** (plus optional decision-gate
  `escalate`). Other fields below are **soft cargo** — emit them for
  downstream workers, but they are not SO schema gates (#899).
- On any converged verdict, `successfulLegs` **should** list the CMR
  leg slugs that actually produced usable reviews in this pass. Use `opus` for
  the Claude/Opus reviewer leg, `gpt-5.6-sol` for the codex leg, and `agy` for the
  Gemini/agy leg.
- If a declared leg was unavailable at runtime, omit it from `successfulLegs` and
  include it in `skippedLegs` with a short visible flag reason. Omit
  `skippedLegs` only when no declared leg was skipped.
- When review-leg coverage is missing because quota exhaustion or provider
  degradation prevents cross-vendor coverage, report the jury shortfall through
  your decision gate, or emit `findings = x`, where `x >= 1`, and explain the
  absent legs in the review body.
- On any converged verdict, `claimedFixedFindingIdentityKeys` and
  `priorFindingDispositions` **should** be emitted as soft cargo. Use empty arrays
  only when no claimed-fixed findings occurred in the CMR loop. If a prior
  claimed-fixed finding exists, include its stable identity key and an explicit
  disposition using the exact JSON field name `status`, for example
  `{"identityKey":"<key>","status":"verified-closed","reason":"<short>"}`.
  Valid `status` values are `still-active`, `verified-closed`, and
  `unable-to-assess`. Do not use a field named `disposition`.
  Runner-supplied claimed-fixed findings are protected blockers: do not use
  `accepted_suppressed` to close them. If an owner/ADR/issue-backed scope
  exception is now implemented in code/docs/tests, mark the prior finding
  `verified-closed` and cite that source in `reason`; otherwise mark it
  `still-active`.
- On any not-converged verdict, emit soft cargo `reason`, `successfulLegs`,
  `claimedFixedFindingIdentityKeys`, and `priorFindingDispositions` when you can;
  `findings` is optional but must use reviewer finding shape when present.
  Any `priorFindingDispositions` entries in this not-converged shape must use the
  same `{"identityKey":"<key>","status":"...","reason":"<short>"}` contract
  above; valid `status` values remain `still-active`, `verified-closed`, and
  `unable-to-assess`. Do not use a field named `disposition`.
- On any converged or not-converged verdict, `evidencePaths` **should** list
  relative paths to existing review/test artifacts under the repo root (soft
  cargo). Do not use absolute paths or `..`.
- On any converged or not-converged verdict, `findingsCount` is **REQUIRED**
  (typed SO fate channel) and must equal the `x` declared in the standalone
  `findings = x` line. This is the reviewer-declared open count; do not derive
  it from or reconcile it against structured finding cargo.
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
- Always emit the typed `<cmr>` tag (even when `$ORCHESTRATOR_OUTCOME_PATH` is
  set and you write the same JSON object to the sidecar). Production CMR seats
  bind Sandcastle `Output.object` to the `cmr` tag with `maxRetries`; the tag is
  the traffic-signal channel, not an optional compatibility fallback. If you
  iterate, the last typed `<cmr>` tag is the one that counts.

This seat is single-iteration. Completion is clean exit + legal sidecar / typed receipt — no STEP_COMPLETE password.
