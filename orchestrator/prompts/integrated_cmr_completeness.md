# Integrated CMR completeness worker entrypoint

Read the role soul first (live-mounted):

```text
/home/agent/.orchestrator/souls/cmr_completeness.md
```

Then follow that soul (判官 soul; symlink → `verify.md`) and the
worktree's `CLAUDE.md`. This is the runner-dispatched step5 completeness gate.
The runner only schedules you and writes `.cmr-focus.md` plus `.cmr-route.json`.

**Invoke `ak-cmr-completeness` only** (this pass's skill). Do not run correctness.
You judge the review surface; do not repair code or create fix commits.

## Pass scope

Run only the completeness gate: verify the family base contains every required
slice surface and no slice was structurally swallowed before correctness review.
Do not run the correctness gate in this worker.

## Required output

You are a **family court** of the shared verify judge machine (#930 / ADR 0132):
closure is the T2 judge tri-state `converged | continue | escalate`, not open-count.
Emit the official judge station envelope (same contract as single-slice S3/S6).
CMR leg cargo (successfulLegs / skippedLegs / evidencePaths / prior dispositions)
may ride as soft siblings — runner routes only on `status`.

Also emit `findings = x` on its own line for human readability (`x` = live open
count after kills). Never declare `converged` while any finding remains live.

Converged (no further fix rounds on this court):

```text
<judge>{"station":"judge","status":"converged"}</judge>
```

Continue (send **live** findings to family coder-fix, then this court resumes):

```text
<judge>{"station":"judge","status":"continue","findingDispositions":[{"identityKey":"<stable-key>","action":"live"}],"findings":[{"severity":"medium","category":"correctness","claim_quote":"<stable claim>","location":"<file-or-scope>","suggested_fix":"<next step>","action":"fix_now"}]}</judge>
```

Escalation (decision-kind park — resume in place after owner answers):

```text
<judge>{"station":"judge","status":"escalate","reason":"<short>","diagnosis":"<why the court cannot decide>"}</judge>
```

Soft cargo siblings (optional, not traffic):

```text
{"successfulLegs":["opus","gpt-5.6-sol"],"skippedLegs":[{"slug":"agy","reason":"quota unavailable"}],"claimedFixedFindingIdentityKeys":[],"priorFindingDispositions":[],"evidencePaths":["cmr/review-summary.json"]}
```

Rules:

- **Typed SO traffic is the T2 judge verdict** (`status` tri-state + dispositions
  on continue). Residual `findingsCount` / `<cmr>` shapes are not family closers
  (#930). Other fields below are **soft cargo**.
- On any converged verdict, `successfulLegs` **should** list the CMR
  leg slugs that were **present** this pass (ADR 0141: transport success =
  exit 0 + non-empty raw stdout; pure prose / unanchored candidates still
  count). Use `opus` for the Claude/Opus reviewer leg, `gpt-5.6-sol` for the
  Codex Sol officer leg, and `agy` for the Gemini/agy leg.
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
- Always emit the typed `<judge>` tag (even when `$ORCHESTRATOR_OUTCOME_PATH` is
  set and you write cargo siblings to the sidecar). Production family courts
  bind Sandcastle `Output.object` to the `judge` tag with the T2 station schema
  (`station:"judge"` + status tri-state) — same live seat as single-slice S3/S6.
  Residual open-count / `<cmr>` shapes are not family closers. If you iterate,
  the last typed `<judge>` tag is the one that counts.

This seat is single-iteration. Completion is clean exit + legal sidecar / typed receipt — no STEP_COMPLETE password.

## 腿运行契约(2026-07-21 钉,#1091 实证)

panel 腿一律**前台**运行(阻塞等待或原地循环轮询),判词交出前**不得停手**。
停手=散场:本 run 立即结束、沙箱容器销毁(后台进程与 /tmp 全灭),resume 只带回对话记忆、不带回现场。
禁用「后台 nohup + 停下等唤醒」模式——那是宿主常驻会话的习惯,不适用于你的处境。
