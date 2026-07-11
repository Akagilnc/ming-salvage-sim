# Ming Orchestrator — operator's manual

Multi-agent build pipeline for `Akagilnc/ming-salvage-sim`. A **runner** walks a
ledger-backed step machine (S0–S12) and dispatches sandboxed CLI **workers**
(coder, reviewer, merger, ship, …) into containers. Two entry shapes:

- **single-slice** — one issue through S0(rfa gate) → S2(code) → S3(review) →
  S5(fix loop) → S7(ship) → S9(verify) → S10(fixer) → S12(docRelease) →
  S11(cleanup) → S8(terminal).
- **family** — an epic's children built in waves on a shared `family/<epic>`
  base, merged by a merger worker, closed by an integrated CMR
  (completeness + correctness + cross-model review legs) and a family ship.

## Constitution (ADR 0062 — the envelope rules)

The runner is a pure dispatcher. It counts exactly three signals and **never
reads worker prose**:

1. **exit 0/1** → abnormal exit gets a step-level mechanical retry; normal exit
   continues.
2. **findings count 0 / non-0** → zero passes the gate; non-zero routes back to
   the coder/fixer loop. Whether work is "good" is decided only by the next
   reviewer/verify worker, never by parsing the previous worker's words.
3. **decision-gate signal** → durable park; the answer resumes the SAME worker
   session in place (`resumeSessionId`).

Corollaries, all mechanically enforced by
`test/adr-0062-regression-825.test.ts`:

- A worker that did real work but delivered a defective report (bad JSON,
  missing sidecar, wrong self-count, no sentinel) is a **shape failure**:
  bounded mechanical redispatch of that step → exhausted = escalate. Never a
  run abort, never fabricated success (a missing result is never synthesized
  into `findings: []` / `converged: true`).
- **Git/host truth over worker words.** Commit evidence comes from
  `git rev-list <headBefore>..HEAD` (final-graph reachability); a
  worker-reported PR URL is an advisory hint that is verified
  (open + head branch + head repository owner) or discarded — a rejected hint
  never reaches downstream steps. Self-reported numbers are telemetry only.
- **`*_STEP_COMPLETE` sentinels are optional telemetry.** In every prompt/soul
  they may appear only inside the canonical optional-telemetry sentence; the
  sweep test fails any other mention, so no prompt edit can silently restore a
  lie-detector gate.
- **Mutating dispatches are exactly-once.** Family ship writes a durable
  two-phase attempt marker (reserve before launch, confirm on spawn), a durable
  `ship_completed` record before host observation, and re-dispatches only when
  host truth confirms `pr_missing`. A mismatch (e.g. a deliberately closed PR)
  escalates durably instead of re-shipping. Retry budgets live in the ledger
  (`mechanical_redispatch_attempt` rows) and survive crash/re-feed;
  legitimate repeated rounds (slow-CI S9 re-polls) never consume them.
- **Observation failure ≠ confirmed absence.** A failed `gh`/git lookup is a
  retryable observation problem (its own bounded lane), never proof that the
  mutation didn't land and never a reason to abort a resume.

## Igniting a family run (cold start — everything a fresh session needs)

### 0. Prerequisites

- Docker running; `gh auth status` green; node ≥ 22.
- Host CLI auth valid for every family in the chosen route: `codex` (login),
  `claude` (login — headless cannot refresh an expired OAuth), `~/.grok/auth.json`
  if grok is on the route. The backend copies/mounts auth into per-worker temp
  dirs itself; you only keep the host logins fresh.
- A source clone of the repo (canonical: `~/WorkSpace/Ming_LLM`). The driver
  cuts an isolated per-run clone from it automatically
  (`~/.sc-orchestrator/<owner>_<repo>-iso-<epic>`), so the source clone stays
  untouched.

### 1. Issue prerequisites (what the run reads from GitHub)

- The **parent epic** issue number is the run key. Its children must be
  attached as **native sub-issues** (not just task-list mentions).
- Children the run may build carry the `ready-for-agent` label — the S0 gate
  (rfa) refuses anything else. Pull the label to hold a child out.
- Native `blocked_by` dependencies between children drive wave order
  (`commander.selectWave`; the graph must be acyclic). Independent children
  land in the same wave and run **concurrently**
  (`Promise.allSettled(wave.map(runChild))`), each in its own worktree; the
  merger serializes them onto the family base afterwards.

### 2. Freshness ritual — unconditional, BOTH halves (#372)

Skipping the image rebake after a merge that touched `image/`, prompts, or
souls costs you a dead launch (learned twice on 2026-07-11):

```bash
cd orchestrator && git pull && npx tsc     # 1. rebuild dist
cd image && ./build.sh                     # 2. rebake the worker image
```

Souls are mounted live (not baked), prompts ship with the repo, dev skills are
baked into the image at build time.

### 3. Create the run directory and driver

One dir per epic: `~/.sc-orchestrator/run-<EPIC>/`, holding a small driver
script that calls `runFamilyDriver` from the built dist. Template (this is the
entire file — replace `<EPIC>`):

```js
// driver-<EPIC>.mjs
import { runFamilyDriver } from "/Users/akagilnc/WorkSpace/Ming_LLM/orchestrator/dist/familyDriver.js";

const EPIC = <EPIC>;
const SOURCE = "/Users/akagilnc/WorkSpace/Ming_LLM";
const ORCH = `${SOURCE}/orchestrator`;

const result = await runFamilyDriver({
  epicIssue: EPIC,
  sourceRepo: SOURCE,
  remote: "https://github.com/Akagilnc/ming-salvage-sim.git",
  repo: "Akagilnc/ming-salvage-sim",
  familyBase: `family/${EPIC}`,
  base: "main",
  promptsDir: `${ORCH}/prompts`,
  familyPromptsDir: `${ORCH}/prompts`,
  soulsDir: `${ORCH}/image/souls`,
  ledgerDir: `/Users/akagilnc/.sc-orchestrator/family-${EPIC}-ledger`,
  imageName: "ming-orchestrator-coder:latest",
  skillsMount: "/Users/akagilnc/sc-pipeline/skills-mount",
});
console.log(JSON.stringify(result, null, 2));
```

Full option contract: `FamilyDriverOptions` JSDoc in `src/familyDriver.ts`.
Existing driver to crib from: `~/.sc-orchestrator/run-485/driver-485.mjs`.
Include the 485 guard (refuse to start if `ORCHESTRATOR_CODER_MODEL` is set)
whenever per-issue Coder-Rec should pick the coder — omit it only when you
deliberately pin one coder for the whole run.

**Resuming a PRIOR lineage vs starting fresh (check before writing the
driver):** `ledgerDir` + `familyBase` ARE the run lineage. If this epic was
run before (look for an existing `~/.sc-orchestrator/*-ledger` with rows for
it, and an `…-iso-<epic>` clone), point the driver at the EXISTING
`ledgerDir` and `familyBase` values to resume — already-merged children
re-admit as `already_done`. Writing new values starts a parallel lineage that
cannot see the old ledger and will rebuild its children. A pre-existing iso
clone from another lineage may hold unpushed merged work on its family
branch: never delete it without checking `git -C <iso> log
origin/main..HEAD` first (uncommitted/unpushed worker output is
non-recoverable — adopt it or set it aside, don't wipe).

### 3.5 Pre-ignition lineup audit (mandatory)

Before igniting, read the FINAL lineup (preset + your overrides) against the
seating rules. These are enforced by maintaining the route table itself —
deliberately NO validator machinery (owner ruling 2026-07-11):

- **Judging seats are sol-only**: `reviewer`, `cmrCompleteness`,
  `cmrCorrectness`, `verify` sit gpt-5.6-sol. terra does not review.
- **Coding seats stay terra**: `coder`, `coderFix`.
- If sol ever holds a fixing seat, the floor reviewer for its output is
  cross-family (opus).

The lineup echoes at the top of `run.log` on every launch — audit it there,
don't trust the preset name.

### 4. Ignite

```bash
cd ~/.sc-orchestrator/run-<EPIC>
ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS="gpt-5.6-sol,opus" \
  node driver-<EPIC>.mjs >> run.log 2>&1
```

`ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS` here is an OVERRIDE example, not
mandatory: the `normal` preset's own legs are codex sol + claude opus + agy;
the override above drops the agy leg (use it when agy quota is dead). Omit
the variable to take the preset's legs. Add further route/slot env overrides
from the table below as needed.

Rules of engagement:

- **One family run per machine at a time.** Runs share the docker daemon,
  host CLI auth, and model quota; do not ignite a second family while one is
  active (`docker ps` + a fresh `run.log` mtime tell you).
- **Resume must reuse the byte-identical ignition command** — same env
  overrides included — or the route lineup (and its smoke) changes mid-run.
- Auth freshness probes (cheap, before igniting): codex —
  `echo "reply with exactly: OK" | codex exec --skip-git-repo-check -m gpt-5.6-terra -c model_reasoning_effort=low -`;
  claude — `claude -p "reply OK" --model claude-haiku-4-5-20251001`. An
  expired OAuth fails here in seconds instead of killing the route smoke.
- No need to run the test suite before igniting from a pulled main — the
  route smoke plus the merged gates are the launch bar (`npm test` is the bar
  for MERGING orchestrator changes, not for launching).

Startup is fail-closed: if the route smoke fails, the run records an
`infra_failure` escalation, skips every child, and exits 0 — read the
`stopSummary` in `run.log` for the reason.

### 5. Monitor

| where | what |
| --- | --- |
| `run.log` | route lineup echo, per-phase progress, final JSON result |
| `~/.sc-orchestrator/family-<EPIC>-ledger/family-ledger.jsonl` | append-only family events (`worker_dispatched`, `merged`, `cmr_*`, parks) |
| `.../family-<EPIC>-ledger/worker-logs/S*.log` | live worker output (tail these) |
| `.../family-<EPIC>-ledger/telemetry.jsonl` | per-leg raw stats (#786) |
| `docker ps` | live sandcastle worker containers |

The driver process itself is quiet between phase boundaries — a silent
half-hour with a running container is normal work, not a hang. Judge a hang by
worker-log idleness (> 15 min without growth), and kill only that worker's own
pid tree; the relay successor continues on its uncommitted drift.

### 6. Decision gates (parks) and answers

A worker that raises a decision gate parks durably: the family ledger gets a
`child_decision_parked` row carrying `childIssue`, `diagnosis`, and the
worker's `sessionId`, and the run finishes the rest of the wave and exits. To
answer, append ONE JSON line to `family-ledger.jsonl`:

```json
{"status":"escalation_answered","event":"escalation_answered","phase":"final","childIssue":494,"answer":"<your adjudication, plain text>"}
```

…then re-run the same ignition command. The runner routes the answer into the
parked child's own ledger and resumes the SAME worker session
(`resumeSessionId`) — the worker continues its conversation where it stopped.

### 7. Resume semantics

The driver is idempotent: state lives in the durable ledgers, so re-running
the identical command after a crash, kill, or park continues from the last
durable row. Children already merged re-admit as `already_done`; retry budgets
carry over (no fresh windfall); completed mutating steps (ship) short-circuit
on their durable completion records instead of re-dispatching.

## Routes and per-role model selection

Every role slot is independently overridable. Precedence:

```
preset (ORCHESTRATOR_ROUTE, default "normal")
  → per-slot env override (ORCHESTRATOR_<ROLE>_MODEL)
  → leg-collection env override (ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS)
  → startup route smoke validates the FINAL lineup, slot by slot
```

Presets (`src/modelRoutes.ts` `ROUTE_PRESETS`):

| preset | coder/coderFix | reviewer | verify + cmr gates | ship/merger/fixer/cleanup/docRelease | cmrReview legs |
| --- | --- | --- | --- | --- | --- |
| `normal` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-terra | sonnet | codex sol + claude opus (+agy) |
| `codex-cheap` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-terra | sonnet | opus + agy + codex sol |
| `codex-tight` | sonnet | opus | opus | sonnet | opus + agy (codex family excluded) |
| `claude-cheap` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-terra | gpt-5.6-terra | codex-side legs |
| `claude-tight` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-terra | gpt-5.6-terra | codex sol + agy (claude family excluded) |

`*-tight` presets declare `tightFamilies` — the family whose quota is scarce is
kept off every slot and leg. Pick the preset whose scarce pool matches
reality, then fine-tune single slots:

| slot | env var |
| --- | --- |
| coder | `ORCHESTRATOR_CODER_MODEL` |
| reviewer | `ORCHESTRATOR_REVIEWER_MODEL` |
| coderFix | `ORCHESTRATOR_CODER_FIX_MODEL` |
| ship | `ORCHESTRATOR_SHIP_MODEL` |
| merger | `ORCHESTRATOR_MERGER_MODEL` |
| cmrCompleteness | `ORCHESTRATOR_CMR_COMPLETENESS_MODEL` |
| cmrCorrectness | `ORCHESTRATOR_CMR_CORRECTNESS_MODEL` |
| verify | `ORCHESTRATOR_VERIFY_MODEL` |
| fixer (S10) | `ORCHESTRATOR_FIXER_MODEL` |
| cleanup | `ORCHESTRATOR_CLEANUP_MODEL` |
| docRelease | `ORCHESTRATOR_DOCRELEASE_MODEL` |
| cmrReview legs | `ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS` (comma list) |

Role vocabulary worth keeping straight:

- **coderFix** = in-loop fix worker during the build (responds to S3 reviewer
  findings until the review is clean).
- **fixer** = S10, the post-ship repair worker (eats verify/CI/online-review
  failures after S7). Different seat, independently staffed.

Roster conventions (from the exam/marathon evidence, 2026-07):

- Reviewer is always a **different checkpoint** from the coder.
- When a top-checkpoint codex coder (sol) writes the fix, the floor reviewer is
  **cross-family (opus)** — a same-family sibling is a weak gate.
- Reasoning-effort dials don't buy quality on mechanical work; run cheap tiers
  for mechanical seats. Structural judgment is a model property, not an effort
  property.
- Capacity errors (`Selected model is at capacity`) mean server congestion,
  not quota: switch checkpoint immediately (relay continues on the same
  uncommitted drift — never reset a worker's tree), don't wait, don't retry
  the congested checkpoint.

## Route smoke (startup gate)

Before any real work each selected model×pipe must prove it can act inside the
container: the smoke prompt carries a random `{{NONCE}}` and a
`{{NONCE_FILE}}` path (sandcastle substitutes `{{KEY}}` placeholders from
`promptArgs` — placeholders in `prompts/route-smoke.md` are load-bearing; a
regression test drives the REAL rendering and a text-only-obedient agent, plus
a negative case proving a value-less prompt fails). The worker must create the
evidence file with exactly the nonce. Any slot failing smoke = fail-closed
startup escalation; nothing mutates.

Providers with unavailable auth (e.g. grok without a mounted `auth.json`) are
rejected **before** dispatch — fail-closed preflight, never an unauthenticated
launch. Same pattern for capabilities: a backend without a required
verification seam (`verifyFamilyShippedPr`) is refused before the mutating
ship, not after.

## Review loops

1. **Per-slice loop** (runner-visible, ADR 0030): coder → fresh read-only
   reviewer over the current full diff → coder-fix (new commit, never amend) →
   fresh reviewer again, until findings reach zero. Review fixes are always
   NEW commits: round-by-round history is part of the record.
2. **Integrated CMR** (family close): completeness gate, correctness gate, and
   cross-model review legs (`cmrReview`, e.g. codex sol + claude opus) over the
   assembled family base — it exists to catch cross-slice seams that
   per-slice green cannot see.
3. **Online bot rounds** (after a PR opens): sourcery / codex-connector /
   gemini / coderabbit threads are worked finding-by-finding — fix as a new
   commit, reply with the commit hash, resolve the thread; refutations are
   replied with verifiable evidence instead of code. Merge requires
   mergeState CLEAN **and** zero unresolved threads.

Ticket discipline for fix rounds: every ticket carries a sweep clause ("fix the
finding, then sweep for the same class and print a self-audit checklist").
When reviews deepen the same invariant chain two rounds in a row, the next
ticket states the FULL target invariant (not the single hole) and goes to a
structural-judgment coder. Any slice reaching round 5 triggers a mandatory
stop-and-rethink before the next dispatch.

Testing discipline (hard-won): fixtures must consume only real rendered
artifacts (the rendered prompt text, the actual envelope) — a fixture that
peeks at internal parameters is a psychic model and will greenlight broken
value-chains. Every positive e2e pairs with a negative case that would have
caught the original bug. Assert on the run's OUTPUT (result/ledger/files),
never on input the test itself seeded.

## Durability and resume

- The step ledger (`steps.jsonl`) is the single source of resume truth;
  bookkeeping rows (`mechanical_redispatch_attempt`, ship streak/attempt
  records) use dedicated kinds that step consumers ignore but the budget
  scanner rebuilds from.
- Re-feed after a crash continues retry budgets (no fresh 3-attempt windfall)
  and never re-runs a mutating dispatch whose durable completion record is
  present.
- Killing a worker never destroys its uncommitted worktree drift; a relay
  successor continues on the drift as-is.

## Telemetry sidecar (#786)

Append-only JSONL at the durable ledger location
`<ledgerDir>/telemetry.jsonl`, parallel to the step ledger (`steps.jsonl`). For
single-slice runs this is `<dedicated-clone>/.ledger-<issue>/`; it is outside
Sandcastle's `.sandcastle/worktrees/` prune scope. Family runs use their
existing durable family `ledgerDir`. Raw per-leg stamps only — aggregation /
stats are out of scope for #786.

The durable telemetry directory is never automatically deleted. The former
`.sandcastle/worktrees/.ledger-<issue>/telemetry.jsonl` path is retained as a
read-only migration fallback for offline readers and is not a write target.

Phases (one JSON object per line):

| phase | when | contents |
| --- | --- | --- |
| `environment` | once per run | image / route lineup / CLI versions |
| `dispatch` | at spawn | identity / model / pool / `dispatched_at` |
| `collect` | at finish | terminal / tokens / session / log / `first_output_at` / `completed_at` |
| `review_round` | each integrated CMR verdict | pass / verdict / severity counts / identity-key recurrence / prior-finding dispositions |
| `commit` | each coder commit | worker identity (stepId + modelSlug) / size metrics / escape-hatch counts (code files only) |
| `verification` | each family typecheck or test command | typecheck / wave-unit / final-full pass-fail, structured count when supplied, monotonic duration |

Join key: `legId` on a dispatch+collect pair. Unobtainable fields are `null`;
telemetry I/O is fail-open and must never block the worker path — collection is
fully async (boundaries frozen at schedule time from SHAs the runner already
holds, per-ledger ordered appends, subprocess timeouts, a failed stamp never
blocks the next one).

### `first_output_at` precision (poll granularity — not true TTFB)

`first_output_at` is the wall-clock when the orchestrator **first observed**
worker log growth past the post-spawn marker. It is **not** true first-byte /
time-to-first-token.

| scenario | what the stamp means | error bound |
| --- | --- | --- |
| Long-running worker | Idle monitor poll that first sees `log size > baseline` | ≈ `pollIntervalMs` (default **250ms** in `dispatchWorker`) |
| Quick-exit (exit wins race before any poll sees growth) | One-shot post-exit reconcile re-read | ≈ **process exit time** (may be much later than true first byte) |
| No post-marker growth by collect time | Field is `null` | — |

Consumers computing "time-to-first-output" as
`first_output_at − dispatched_at` must treat the result as **poll-quantized**,
not sub-poll TTFB. When non-null the monotonic order holds:

`dispatched_at ≤ first_output_at ≤ completed_at`.

### `review_round` semantics

`review_round` is an append-only observation after the integrated-CMR runner has
finished its terminal gates. `finalDisposition` says whether that runner accepted
the review result; rejected rows are telemetry only and never alter routing.
`findingsBySeverity`, identity-key lists, and closure dispositions are `null` when
the worker did not produce a parseable CMR payload. `identityMatch` is always
`exact_identity_match`: keys already present in earlier rows of the same pass are
`recurringExactIdentityMatchKeys`; the remainder are
`newExactIdentityMatchKeys`. This is exact matching on category, location, and
normalized `claim_quote`, not semantic deduplication: wording or line-number
drift can make a recurring finding appear new. Fresh re-review dispositions map
to `fixed`
(`verified-closed`), `refuted` (`accepted_suppressed`), or `deferred`
(`still-active` / `unable-to-assess`). These rows are telemetry only: they have no
review, fix-loop, or ADR 0062 routing authority.

Field-level JSDoc lives on `TelemetryCollectRecord.first_output_at` in
`src/telemetry.ts`; the stamp site is `noteFirstOutputIfPastBaseline` /
`reconcileFirstOutputAt` in `src/dispatchWorker.ts`.

## Checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as
`npm run typecheck:test`) before Vitest. That TypeScript lane checks all of
`test/**`, so every test fixture and mock must satisfy the current production
contracts before the behavioral suite runs.

Caveat: repository CI currently runs only the Python engine tests and the web
build — the orchestrator vitest suite is NOT a required check yet (#838), so
run `npx vitest run` locally before merging anything that touches
`orchestrator/`. Individually-green branches can still combine into a red
main across cross-slice seams; the integrated gates exist precisely for that.

## Known failure signatures

| symptom | likely cause | fix |
| --- | --- | --- |
| startup `route smoke failed … did not complete an observable bash smoke` (every launch) | smoke prompt lost its `{{NONCE}}`/`{{NONCE_FILE}}` placeholders, or model at capacity | check `prompts/route-smoke.md` placeholders; switch checkpoint |
| image build fails at `npm install -g` with EACCES | global install under non-root user without npm prefix | prefix is scoped inside the install RUN layer; runtime resolves `/usr/local/bin/grok` |
| run dies with "budget exhausted" during normal slow CI | retry markers counted without a budget-breaking canonical row | fixed on main (#824); ensure dist is fresh |
| resume raw-rejects out of the driver | unguarded host observation on the resume path | fixed on main (#824); transient gh failure is a resumable error |
| worker looks hung | judge by idle threshold (>15 min with no new output), then kill only that worker's own pid tree; capacity/quota errors are not hangs | relay a successor onto the surviving drift |
