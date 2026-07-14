# Ming Orchestrator — operator's manual

Multi-agent build pipeline for `Akagilnc/ming-salvage-sim`. Production has one
entry shape: `runFamilyDriver`. A leaf issue is normalized to a
**family-of-one**; an epic becomes a multi-child family. Both build on a shared
family base and close through merger, integrated CMR (completeness,
correctness, and cross-model review legs), verify/fix, family ship, and cleanup.
The S0–S8 slice runner remains internal child machinery, not a second public
entry or terminal-delivery topology.

This is the current legacy runtime. #863 tracks its replacement by one
Canonical Delivery Flow; #896 replaces family-of-one normalization with a true
standalone scene. Exact target delivery order has one design source (#869) and
executable flow tests; this README does not define a second copy.

## Constitution (ADR 0131 — three channels, zero judgment; lineage ADR 0062)

The runner is a pure dispatcher. It accepts exactly three signals and **never
reads worker prose or completion evidence**:

1. **exit code** — process life or death; only a real process failure enters
   the mechanical retry lane.
2. **reviewer self-declared blocking open-count** — `0` closes the current review gate;
   `>0` follows the fixed topology defined only in #869. This README does not
   restate the intermediate repair/verification/finalization route, and the
   runner never derives or reconciles the number. P4 findings remain recorded
   as non-blocking terminal rows and are not part of this count.
3. **worker-raised decision gate** — relayed to the human unchanged; the runner
   never presses or interprets the gate itself.

Commits, HEAD, diffs, PRs, tests, findings, report shape and external-effect
evidence are never runner inputs. Each Action performs and verifies its own
side effects; the next professional worker judges empty work or a false fix.
Detailed operational rules live in `orchestrator/CLAUDE.md`; professional
methods live in versioned souls/skills/actions; delivery topology lives in
#869 and executable flow tests.

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

- A **parent epic** or **leaf issue** number is the run key. Parent epic
  children must be attached as **native sub-issues** (not just task-list
  mentions). In the current runtime, a leaf issue is normalized automatically
  to a family-of-one; #896 replaces this with one standalone scene.
- Issues the run may build carry the `ready-for-agent` label — the current S0 gate
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

**Current legacy runtime only:** the driver process itself is quiet between
phase boundaries, so a silent half-hour with a running container can be normal
work. The current monitor uses worker-log idleness (> 15 min without growth)
and a worker-local PID kill before relaying onto the surviving drift. This is
not the canonical contract: Sandcastle owns idle/completion timeout and cancel,
Policy owns relay/wait/decision, and #898 removes the PID-based path.

### 6. Decision gates (parks) and answers

A worker that raises a decision gate parks durably: the family ledger gets a
`child_decision_parked` row carrying `childIssue`, `diagnosis`, and the
worker's `sessionId`, and the run finishes the rest of the wave and exits. To
answer, append ONE JSON line to `family-ledger.jsonl`:

```json
{"status":"escalation_answered","event":"escalation_answered","phase":"final","childIssue":494,"answer":"<your adjudication, plain text>"}
```

…then re-run the same ignition command. In the current legacy runtime the
runner routes the answer into the parked child's own ledger and supplies a
captured `resumeSessionId` when one exists. The same conversation resumes only
when Sandcastle captured the session and the provider supports resume. Codex
and Grok currently disable session capture, so this runtime cannot promise
same-session continuation for those providers. The canonical target preserves
the scene/worktree and starts a new invocation/relay when resume is unavailable.

### 7. Resume semantics

The current legacy driver is idempotent: state lives in its durable ledgers, so re-running
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
| `normal` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-sol | sonnet | codex sol + claude opus (+agy) |
| `codex-cheap` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-sol | sonnet | opus + agy + codex sol |
| `codex-tight` | sonnet | opus | opus | sonnet | opus + agy (codex family excluded) |
| `claude-cheap` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-sol | gpt-5.6-terra | codex-side legs |
| `claude-tight` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-sol | gpt-5.6-terra | codex sol + agy (claude family excluded) |

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
| delivery fixer | `ORCHESTRATOR_FIXER_MODEL` |
| cleanup | `ORCHESTRATOR_CLEANUP_MODEL` |
| docRelease | `ORCHESTRATOR_DOCRELEASE_MODEL` |
| cmrReview legs | `ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS` (comma list) |

Role vocabulary worth keeping straight:

- **coderFix** = repair worker used by per-slice and family-integration review
  scopes.
- **fixer** = repair worker used by delivery/shared-tail review scopes. It is a
  different seat and is independently staffed. Exact dispatch positions live
  only in #869.

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
container: the smoke prompt carries a random `{{NONCE}}` (sandcastle substitutes
`{{KEY}}` placeholders from `promptArgs` — placeholders in
`prompts/route-smoke.md` are load-bearing). The worker must print exactly that
nonce to stdout; no shell command or evidence file is part of the contract. A
regression test drives the real rendering and a text-only-obedient agent, plus a
negative case proving a value-less prompt fails. Any slot failing smoke =
fail-closed startup escalation; nothing mutates.

Providers with unavailable auth (e.g. grok without a mounted `auth.json`) are
rejected **before** dispatch — fail-closed preflight, never an unauthenticated
launch.

OpenCode is baked into the worker image and the route-selectable `glm-5.2`
slug resolves to `opencode-go/glm-5.2`. Its Go-subscription credential remains
on the host at `~/.local/share/opencode/auth.json` and is mounted read-only at
runtime. Only that file is shared: OpenCode's SQLite database, WAL, logs, and
other writable state live in each container's isolated ephemeral home, avoiding
the CLI's concurrent shared-data-dir lock crash. Credential provisioning is
uniform across worker roles and routes: when host `auth.json` and `GLM_KEY` are
present, every sandbox receives the same read-only mount and environment value.
The dispatcher never inspects credential metadata or contents. Every ignition
runs a fresh route smoke with the provisioned credentials; that live call is the
only credential oracle. Expiry, rate limits, and server failures after startup
flow through the ordinary leg degrade/park paths. `GLM_KEY` is never baked into
the image or written to orchestrator state.

## Review roles

Exact gate order and repair re-entry live only in #869. This README records the
role boundaries:

- Per-slice coder, reviewer and fixer are independent workers. The reviewer
  reports its own blocking unresolved open-count; the runner never reads the findings or
  checks the repair.
- Integrated completeness and correctness remain distinct professional review
  actions over the assembled delivery base (a single slice branch or family
  base). Their methods live in the versioned
  review skills, not in the runner or this README.
- Online review, repair, document release and merge use the same shared tail for
  single and family delivery. GitHub evidence is owned by the corresponding
  Action, never by the runner.

Each fixer performs the same-class scan and introduced-regression check, leaves
its materials, and stops. Commit/no-op finalization, independent Verification,
and fresh originating review occur only where #869 places them; this README
defines no alternate order or round cap.

Testing discipline (hard-won): fixtures must consume only real rendered
artifacts (the rendered prompt text and production worker artifacts) — a
fixture that peeks at internal parameters is a psychic model and will greenlight broken
value-chains. Every positive e2e pairs with a negative case that would have
caught the original bug. Assert on the run's OUTPUT (result/ledger/files),
never on input the test itself seeded.

## Durability and resume

- **Current legacy runtime only:** the step ledger (`steps.jsonl`) is the
  single source of resume truth. The canonical target makes Lineage the sole
  durable source and keeps the step ledger as a Flow projection; #867 owns the
  migration and #898 removes this legacy path.
- In that current legacy runtime,
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
`<ledgerDir>/telemetry.jsonl`, parallel to the step ledger (`steps.jsonl`). Both
family-of-one and multi-child runs use the durable family `ledgerDir`, outside
Sandcastle's `.sandcastle/worktrees/` prune scope. Raw per-leg stamps only —
aggregation / stats are out of scope for #786.

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

Join key: `legId` on a dispatch+collect pair. Unobtainable fields are `null`.
In the current legacy runtime, telemetry I/O is fail-open and fully async;
boundaries are frozen from SHAs already held by the legacy driver, appends are
ordered per ledger, and a failed stamp never blocks the next one. This is not
Generic Runner authority. In the canonical target, the mutating Action or an
external observation surface supplies commit boundaries; Generic Runner never
reads commit, HEAD, diff, or PR state for telemetry or routing.

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

This section documents the legacy implementation until #898 makes its control
path unreachable; it is not target Generic Runner authority. `review_round` is
an append-only observation after the legacy integrated-CMR path has finished its
current terminal gates. `finalDisposition` records whether that legacy path
accepted the review result; rejected rows are telemetry only and never alter routing.
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

The canonical cutover must remove Runner-side review-payload parsing; retained
telemetry, if any, is emitted outside Generic Runner.

Field-level JSDoc lives on `TelemetryCollectRecord.first_output_at` in
`src/telemetry.ts`; the stamp site is `noteFirstOutputIfPastBaseline` /
`reconcileFirstOutputAt` in `src/dispatchWorker.ts`.

## Checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as
`npm run typecheck:test`) before Vitest. That TypeScript lane checks all of
`test/**`, so every test fixture and mock must satisfy the current production
contracts before the behavioral suite runs.

Repository CI now runs orchestrator `npm test` as its own job, in addition to
the Python engine and web jobs. This README does not assert which jobs the
GitHub ruleset marks as required, so still run `npm test` locally before
merging orchestrator changes. Individually-green branches can still combine
into a red main across cross-slice seams; the integrated gates exist precisely
for that.

## Known failure signatures

This table documents the current pre-cutover runtime. It is operational help,
not the canonical target contract; #898 removes the retired paths after the
replacement Actions and Sandcastle controls land.

| symptom | likely cause | fix |
| --- | --- | --- |
| startup `route smoke failed … did not echo the expected nonce` (every launch) | smoke prompt lost its `{{NONCE}}` placeholder, or model at capacity | check `prompts/route-smoke.md` placeholder; switch checkpoint |
| image build fails at `npm install -g` with EACCES | global install under non-root user without npm prefix | prefix is scoped inside the install RUN layer; runtime resolves `/usr/local/bin/grok` |
| run dies with "budget exhausted" during normal slow CI | retry markers counted without a budget-breaking canonical row | fixed on main (#824); ensure dist is fresh |
| resume raw-rejects out of the driver | unguarded host observation on the resume path | fixed on main (#824); transient gh failure is a resumable error |
| worker looks hung (legacy path) | the current monitor judges by idle threshold (>15 min with no new output), then kills only that worker's own pid tree; capacity/quota errors are not hangs | current-runtime recovery is to relay a successor onto the surviving drift; the canonical target delegates idle/completion timeout and cancellation to Sandcastle, with Policy owning relay/wait/decision |
