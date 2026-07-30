# Ming Orchestrator — operator's manual

Multi-agent build pipeline for `Akagilnc/ming-salvage-sim`. Production has one
entry shape: `runFamilyDriver`. A leaf issue is normalized to a
**family-of-one**; an epic becomes a multi-child family. Both build on a shared
family base and close through merger, integrated CMR (completeness,
correctness, and cross-model review legs), verify/fix, family ship, and cleanup.
The S0–S8 slice runner remains internal child machinery, not a second public
entry or terminal-delivery topology.

**Resident judge hub (ADR 0147 / #1081–#1086):** each child slice opens a
verify-seat court at S1 (`judge_open_court`). Every builder beat — coder plan
or construct (#1082), and every fixer beat (#1083) — dumb-relays back to that
same judge session (S3/S6 resume; `forbidFreshRetry`). Plan-phase `continue`
resumes S2 until a construct beat lands; `converged` dismisses the court;
`escalate` parks for a human answer then resumes in place. Fresh outer-gate
panel legs still run after pure-judge receive when the topology requires them.
If the backend explicitly reports that the judge session is unrecoverable, the
seat reopens fresh at S6 with its durable prior verdicts. After an answered S6
park, moving the verify seat to a different resume-capable model follows the
same boundary: persist `session_continuity_lost`, then fresh-reopen with the
durable prior verdicts and owner answer. Unknown network, authentication, and
protocol failures still fail loudly.
Operator truth for the child loop lives in the per-issue step ledger
(`court_opened` / `court_dismissed`, plan|construct beat tags, progress
`beat` events).

This is the current legacy runtime. #863 tracks its replacement by one
Canonical Delivery Flow; #896 replaces family-of-one normalization with a true
standalone scene. Read live #869 for the exact target delivery order; executable
pins land through the implementation tickets identified by #869 Testing Decisions.
This README does not define a second copy.

## Constitution (ADR 0131 — three channels, zero judgment; lineage ADR 0062)

The runner is a pure dispatcher. It accepts exactly three signals and **never
reads worker prose or completion evidence**:

1. **exit code** — process life or death; only a real process failure enters
   the mechanical retry lane.
2. **judge self-declared tri-state** — `converged | continue | escalate`
   (ADR 0131 channel (b) / ADR 0132 / #925 / #930 / #934 ID-006). The runner
   follows the fixed topology in #869 only; it never derives status from
   findings text, severity, or array length. Historical residual open-count
   paper may still appear on legacy seats and projects once at the typed
   boundary into the same judge machine — it is **not** a second live channel.
3. **worker-raised decision gate** — relayed to the human unchanged; the runner
   never presses or interprets the gate itself.

Commits, HEAD, diffs, PRs, tests, findings, report shape and external-effect
evidence are never runner inputs. Each Action performs and verifies its own
side effects; the next professional worker judges empty work or a false fix.
Online Review splits across two seats (#1145): **Collector** owns GH
query/wait/retrigger/evidence; **Verify** owns finding judgment plus GitHub
reply/resolve/deferred side effects, then self-reports judge three-state.
Runner never replays residual cargo after either Action returns. There is no
mechanical round cap (#940 / #934 ID-012).
Detailed operational rules live in `orchestrator/CLAUDE.md`; professional
methods live in versioned souls/skills/actions. Read live #869 for the target
delivery topology; its Testing Decisions identify the implementation tickets
that will land the executable pins.

The canonical Action contract will be landed by #899: typed traffic signals use
Sandcastle structured-output retry inside the owning Action, and retry
exhaustion makes that Action exit non-zero. The Runner sees only the exit code;
it neither judges the bad envelope nor hands raw artifacts to a fixer.

**Current legacy exception, not constitution:** until #899 and #898 remove the
old path, `verifyCmr` and the review fix loops can still hand raw reviewer
artifact pointers to a fixer. This records current operator truth only; it is
not an ADR 0131 corollary or a basis for future implementation, and must not be
copied or expanded.

Canonical corollaries are locked by positive routing tests under
`test/constitution/`, not by forbidden-source-text sweeps. In particular see
`reviewer-open-count.test.ts`, `review-closure-behavior.test.ts`, and
`worker-reporting.test.ts`:
- **The worker's OK is OK — no git verdicts.** A coder or ship worker's
  exit-zero completion routes forward as-is; self-verification (real commit /
  PR exists) and idempotency live in the worker soul, an empty diff is judged
  by the next reviewer, and any reported PR URL is cargo for downstream
  workers, not a runner verdict input. The runner never runs
  `git rev-list` / `ls-remote` / `gh pr view` to adjudicate a worker.
- **Completion = clean exit + legal sidecar / typed envelope (#928 / ADR 0131).**
  `*_STEP_COMPLETE` passwords and `completionSignal` fields are retired. All
  seats are single-iteration (`maxIter=1`); host monitor silence is observational
  only (log last-activity whole minutes — never kill/retry/relay/park; #937).
  Exit 0 without a usable sidecar must not masquerade as completed.
- **Ship dispatch is worker-idempotent.** On re-feed after a ship park, the
   runner dispatches ship again. The worker verifies whether the branch's exact
   delivery already exists and returns success without duplicate push, PR, or
   version bump. Process failures use durable `mechanical_redispatch_attempt`
   rows; decision gates are transported unchanged.

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

**Target hygiene (2026-07-18):** the integrated CMR refuses a dirty target —
the iso clone must be a clean committed snapshot (`git status --porcelain=v1
--untracked-files=all` empty). Long campaigns accumulate untracked runtime
droppings (`.sandcastle/` leg scratch, `*.draft.json` outcome envelopes, core
dumps; 485 hit 9,889 paths). Clean by **moving** them to a quarantine dir
outside the repo — never `rm` (uncommitted worker output is unrecoverable),
and move the exact untracked paths, not top-level segments (a lone untracked
file inside a tracked dir must not drag the whole tracked dir out).

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
Per-issue Coder-Rec and the selected route preset are the staffing inputs;
deleted per-slot environment variables are ignored.

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

- **Judging seats are sol** (`verify` + `cmrCompleteness` + `cmrCorrectness`
  — collectively "the judge"; #923). terra does not review.
- **Coding/fix seats follow the owner's current route order** (2026-07-18:
  sol-low across coder/coderFix/fixer; judge-nameable bench sol@med/sol@high
  via the roster — repair-seat advanceCoder is live for coderFix and
  online-review fixer, including ledger sticky re-hold on re-entry (#1002)).
- If sol ever holds a fixing seat, the floor reviewer for its output is
  cross-family (opus).

The lineup echoes at the top of `run.log` on every launch — audit it there,
don't trust the preset name.

### 4. Ignite

```bash
cd ~/.sc-orchestrator/run-<EPIC>
node driver-<EPIC>.mjs >> run.log 2>&1
```

Current practice (2026-07): launchers live at
`~/.sc-orchestrator/launch-<epic>.mjs` (sed-copy of `launch-485.mjs`; exactly
three epic-specific fields: `epicIssue`, `familyBase`, `ledgerDir`), ignited
with the route env pair — omitting either is a dead launch:

```bash
cd ~/.sc-orchestrator && PATH="$HOME/.sc-orchestrator/bin:$PATH" \
  ORCHESTRATOR_ROUTE=<preset> \
  ORCHESTRATOR_ROUTE_PRESETS_PATH=$HOME/.sc-orchestrator/route-presets.json \
  node launch-<epic>.mjs > flight.log 2>&1
```

Rules of engagement:

- **Concurrent family runs: two max (owner-approved 2026-07-18, first twin
  flight 485+969).** Flights share the docker daemon, host CLI auth, and model
  quota; expect CPU contention to inflate test wall-clocks and fire
  load-sensitive flakes (#986-class e2e timeouts). Three+ concurrent launchers
  is not advised.
- **Resume must reuse the byte-identical ignition command** — same env
  overrides included — or the route lineup (and its smoke) changes mid-run.
- Auth freshness probes (cheap, before igniting): codex —
  `echo "reply with exactly: OK" | codex exec --skip-git-repo-check -m gpt-5.6-terra -c model_reasoning_effort=low -`;
  claude — `claude -p "reply OK" --model claude-haiku-4-5-20251001`. An
  expired OAuth fails here in seconds instead of killing the route smoke.
- No need to run the test suite before igniting from a pulled main — the
  route smoke plus the merged gates are the launch bar (`npm test` is the bar
  for MERGING orchestrator changes, not for launching).

Startup is fail-closed: if the required route smoke fails, the run records an
`infra_failure` stop summary, public status **`failed`** with cause
`route_smoke_failed`, and OS exit **1** (`completed→0` / `parked→2` /
`failed→1` — see `publicResult.ts`) — read the `stopSummary` in `run.log`
for the reason.

### 5. Monitor

| where | what |
| --- | --- |
| `run.log` | route lineup echo, per-phase progress, final JSON result |
| `~/.sc-orchestrator/family-<EPIC>-ledger/family-ledger.jsonl` | append-only family events (`worker_dispatched`, `merged`, `cmr_*`, parks) |
| `.../family-<EPIC>-ledger/progress.jsonl` | #1007 active progress feed (issue-numbered stage / judge / park / merge / ship / terminal) |
| `.../family-<EPIC>-ledger/worker-logs/S*.log` | live worker output (tail these) |
| `.../family-<EPIC>-ledger/telemetry.jsonl` | per-leg raw stats (#786) |
| `docker ps` | live sandcastle worker containers |

**Status command (#1007):** from `orchestrator/`,
`npm run status -- ~/.sc-orchestrator/family-<EPIC>-ledger` renders per-issue
station / rounds / latest judge verdict / disposition counts / parks from
`progress.jsonl` (+ merge markers from `family-ledger.jsonl`). No hand-scanning
`steps.jsonl`. Optional desktop notify: set `ORCHESTRATOR_NOTIFY_CMD` (default
off) — fires on park / terminal only; fail-open.

**Truth sources per layer (2026-07-18 monitoring-misread lesson):** the family
ledger above records FAMILY-station events only (merger / integrated CMR /
verify / parks). Per-child single-slice truth lives in the iso clone:
`<iso>/.sandcastle/worktrees/.ledger-<issue>/steps.jsonl` (authoritative step
outcomes) plus `.ledger-<issue>/worker-logs/*.result.json` and `S*.log`.
Stage lines and `progress.jsonl` now carry issue numbers (#1007 / #975 debt ④).
During a wave the family branch tip does NOT move: children merge serially
only after the whole wave settles (`Promise.allSettled` barrier) — a static
family tip is expected behavior, not a stall signal.

**Worker silence (#937 / #934 ID-007):** a quiet half-hour with a running
container can be normal work. Host-side silence reporting reuses existing
dispatch/agent-stream/worker-log last-activity and is observational only —
it never probes quota, kills a PID tree, retries, relays, parks, or fails.
Process ownership is the exact ChildProcess / process-group handle at spawn
(adoption-failure cleanup only; no idle kill / spawn-ack wall clock). #928:
completion is clean exit + legal sidecar (no completion-signal password).

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
and Grok both capture sessions natively (Codex via Sandcastle `sc.codex`
default capture; Grok via #955 sessionStorage). Host-side CMR parallel legs
still use `--ephemeral` (shared `~/.codex` collision risk); container workers
do not. When resume is unavailable, the canonical target preserves the
scene/worktree and starts a new invocation/relay via existing fresh-session
recovery (#936/#937/#942).

The family's own FINAL-phase gates (integrated-CMR jury failures, dirty-target
refusals) park as phase-level `escalated` rows with no `childIssue`; answer
them with the same append-one-line shape minus `childIssue` (add
`"source":"human"`). Infra misfires are legitimate adjudications — e.g. a
review leg killed by an operator `docker stop` (grok exit 137) is answered
"transient, retry as-is", ideally with a host bare-ping as evidence. The
ledger is append-only: answer rows, never edits.

### 7. Resume semantics

The current legacy driver is idempotent: state lives in its durable ledgers, so re-running
the identical command after a crash, kill, or park continues from the last
durable row. Children already merged re-admit as `already_done`; retry budgets
carry over (no fresh windfall); completed mutating steps (ship) short-circuit
on their durable completion records instead of re-dispatching.

## Routes and model selection

Staffing is resolved before worksite creation:

```text
config file preset (sole table: config/route-presets.json, selected by
ORCHESTRATOR_ROUTE; ORCHESTRATOR_ROUTE_PRESETS_PATH may select another table)
  → owner-authored issue Coder-Rec for coder/coderFix
    (roster ids + registry data rows from config/model-data.json;
     ORCHESTRATOR_MODEL_DATA_PATH may select another file — read-at-use)
  → startup host bare-ping smoke validates the FINAL lineup (unique models)
```

Two config files, both env-overridable like each other:

- **Route slots / lineup** — edit `config/route-presets.json` (or point
  `ORCHESTRATOR_ROUTE_PRESETS_PATH` at another file).
- **Coder roster + model registry data rows** — edit
  `config/model-data.json` (or point `ORCHESTRATOR_MODEL_DATA_PATH`).
  Every load re-reads the file (no process cache); missing or bad shape
  fail-closes. See `docs/CODER_ROSTER.md` (pointer) and ADR 0146.

Provider factory wiring and the quota pool table stay in code. Code changes
only when adding a new provider/CLI seam or pool semantics — not when adding
a roster id or registry data row.

Presets (factory content of `config/route-presets.json`):

| preset | coder/coderFix | verify (judge; S1 open court + S3/S6 resume + verify) + cmr gates | ship/merger/fixer/cleanup/landing | cmrReview legs |
| --- | --- | --- | --- | --- |
| `normal` | gpt-5.6-terra | gpt-5.6-sol | sonnet | codex sol + claude opus (+agy) |
| `codex-cheap` | gpt-5.6-terra | gpt-5.6-sol | sonnet | opus + agy + codex sol |
| `codex-tight` | sonnet | opus | sonnet | opus + agy (codex family excluded) |
| `claude-cheap` | gpt-5.6-terra | gpt-5.6-sol | gpt-5.6-terra | codex-side legs |
| `claude-tight` | grok-4.5 | gpt-5.6-sol | gpt-5.6-sol-low | codex sol + grok-4.5 + agy (claude family excluded) |

The operative table is whatever `ORCHESTRATOR_ROUTE_PRESETS_PATH` points at —
in practice `~/.sc-orchestrator/route-presets.json`, which the owner edits
directly (2026-07-18 `claude-cheap` there: coder/coderFix/fixer = sol-low,
judge = sol-med, ship/merger/cleanup/landing = grok-4.5, cmrReview legs
grok + agy(optional) + opus). The factory table above is only the in-repo
default.

`*-tight` presets declare `tightFamilies` — the family whose quota is scarce is
kept off every slot and leg. Pick the preset whose scarce pool matches
reality. Change the preset table for deliberate non-coder lineup changes; use
Coder-Rec for a planned issue's coder order.

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

Before any real work each selected model must prove host bare-ping auth
(#884 / #934 ID-003) — one-shot host CLI per unique model×pipe, empty workspace,
no container/tool loop. The smoke prompt carries a random `{{NONCE}}`
(placeholders in `prompts/route-smoke.md` are load-bearing). The CLI must print
exactly that nonce to stdout; no shell command or evidence file is part of the
contract. A regression test drives the real rendering and a text-only-obedient
agent, plus a negative case proving a value-less prompt fails. Any required
smoke failing = fail-closed startup (`failed` / OS exit 1); nothing mutates.

Providers with unavailable auth (e.g. grok without a mounted `auth.json`) are
rejected **before** dispatch — fail-closed preflight, never an unauthenticated
launch.

OpenCode is **not** an orchestrator transport (#905): it is not baked into the
worker image, has no registry slug (`glm-5.2` / `opencode-grok` removed), and
receives no auth mount. The optional CMR `agy` leg runs the real Antigravity /
Gemini CLI; when that leg is dead, optional-leg degrade applies — never a
substituted vendor model under the `agy` name. `grok-4.5` always dispatches via
the SuperGrok CLI (`provider: "grok"`).

## Review roles

Exact gate order and repair re-entry live only in #869. This README records the
role boundaries:

- Per-slice coder, reviewer and fixer are independent workers. Review closure is
  the judge tri-state (`converged | continue | escalate`); residual open-count
  paper is historical transport only. The runner never reads findings text or
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
| Long-running worker | One-shot / post-exit reconcile that first sees `log size > baseline` | ≈ process-exit granularity after #937 (no idle poll race) |
| Quick-exit | One-shot post-exit reconcile re-read | ≈ **process exit time** (may be much later than true first byte) |
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

ADR 0140 splits the canonical test entry into two obligations:

| command | what runs | who uses it |
| --- | --- | --- |
| `npm run test:fast` | `tsconfig.test.json` typecheck + Vitest **fast** project (pure logic / unit) | coder / fixer 交卷自检 |
| `npm test` | same typecheck + **all** Vitest projects (fast + heavy) | wave/final verify, CI, ship gate |

Heavy (real process / real sandcastle SO / e2e-class tax) is classified by
mechanical path/name conventions plus a harness-nature scan in
`vitest.config.ts` — not a hand-curated smoke list. Both scripts run the
TypeScript compile gate first (`npm run typecheck:test` equivalent) over all of
`test/**`, so every fixture and mock must satisfy current production contracts
before the behavioral suite runs.

Repository CI runs orchestrator full `npm test` as its own job, in addition to
the Python engine and web jobs. This README does not assert which jobs the
GitHub ruleset marks as required; still run full `npm test` locally before
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
| worker looks hung | host silence is observational only (#937) — no idle kill / PID-tree; capacity/quota walls still park or relay via durable ledger + ephemeral baton brief (no `.relay-focus.md`); completion is clean exit + legal sidecar (#928) | wait for process exit / typed outcome; on explicit 429/capacity use the existing park/relay owner; never invent hang-kill from log quiet |
| historical content-shape CMR parks (pre-#1005 / ADR 0141) | older monorepo paths could void prose / unanchored leg paper and park under content-shape gates; those strings and gates are **gone** after ADR 0141 / #1005 (presence = exit0 + non-empty stdout only). Live parks are decision-gate / dirty-target / real transport death — never "prose is illegal paper" | do not blind-retry the same prose shape; if transports are dead, hand-run the integrated CMR and answer the gate with its verdict |
| `parked: completeness target is not a clean committed snapshot` | untracked runtime droppings in the iso clone | quarantine by `mv` (see Target hygiene), answer the gate, re-ignite |
| startup smoke `CLI version changed from X to Y` on an optional leg | host↔container CLI version drift invalidating the recorded smoke | re-ignition refreshes the recorded version; an OPTIONAL leg blocking launch is #846-class degrade debt |
| every slice in a wave red on the SAME test | inherited baseline defect fanned out N ways — each fixer repairs it independently, merger later reconciles N same-shape patches | pre-fix the family base first (#1006 gate); container-env-only reds exist (GitHub-CI-green ≠ container-green, e.g. `/dev/stdin` os error 6) |

---

## 领航员运维手册(2026-07-23,交接版)

> 本章给接棒的 runner(人或 AI)。上文是机器的设计文;本章是**开机器的人**的操作规程。判卷法理真源=`image/souls/verify.md`(判前必重读,含裁 park/立票);宪法=容器全局 CLAUDE.md 三句话+一套机制(scope 是参数,无庭际分层);基本架构=**runner 按信封起容器、递信息;worker 永不起 worker;判官经 typed 判词向 runner 要腿**(切片庭与纯庭同源,#1126/#1094)。

### 点火

```bash
cd ~/.sc-orchestrator && PATH="$HOME/.sc-orchestrator/bin:$PATH" \
  ORCHESTRATOR_ROUTE=w3-blitz \
  ORCHESTRATOR_ROUTE_PRESETS_PATH=$HOME/.sc-orchestrator/route-presets.json \
  ORCHESTRATOR_MODEL_DATA_PATH=$HOME/.sc-orchestrator/model-data.json \
  ORCHESTRATOR_SMOKE_IDLE_SECONDS=180 \
  caffeinate -i node launch-<epic>.mjs
```

- launcher 模板=复制既有 `launch-*.mjs` 改 `epicIssue`/`familyBase`/`ledgerDir` 三处;epic 必须是**直接挂着 ready-for-agent 子票**的那张(方向票→PRD→切片层级里选 PRD 层,#471/#513 踩过)。
- **同一 ORCH 树的 launcher 严禁并发起飞**:每个 launcher 都重建共享 `dist/`,并发=swap 竞态双爆(ERR_MODULE_NOT_FOUND,07-23 实证)。串行法:先起 A,`grep "admission route preflight" A.log` 出现后再起 B(参考 scratchpad 牧羊人脚本形状)。
- 点火战报第一时间引 `model route lineup` 原文核对阵容;派单型号唯一真源=owner 现役口令,runner 零自改权。

### grok 凭证(#1115 机制化前的人肉规程)

- access 凭证寿命 **6 小时**(auth.json `expires_at`);副本制(每 worker 抄一份,无回写)+ 多副本各自刷新会互杀令牌线 → **全系统只许宿主一个刷新者**。
- 过夜/长跑前让 owner `grok login --device-code` 现场新登;挂护航脚本:每 3 分钟剥新副本 `refresh_token` + 临期宿主单点续期(轻量 `grok --single` 触发隐式刷新)+ 新 `key`/`expires_at` 原子写进各在飞副本。脚本形状见 session scratchpad `grok-night-guard.sh`。
- 掉登录症状=worker `provider auth death` park;复燃=owner 重登 → 杀旧 launcher → 重点火(driver 依法不拿死凭证重派)。

### park 处置(铁律)

1. park 行在 `family-ledger.jsonl`(`child_decision_parked`/家族级 `escalated`),**上报 owner 必引 reason+diagnosis 原文全文**,禁转述禁截断(监控管道会截,回台账取原文)。
2. 人类唯一合理回答=「重试」的 park(瞬断/限流/腿哑火)不上抛,runner 自决复燃。
3. 应答行(append-only 写进 family-ledger.jsonl):
   - 家族级:`{"status":"escalation_answered","event":"escalation_answered","phase":"final","answer":"…","source":"human"}`(**不带 childIssue**)
   - 子级:`{"status":"escalation_answered","event":"escalation_answered","childIssue":<N>,"answer":"…","source":"human"}`
   落行后重跑同一 launcher=原地复庭。

### #936 fail-closed(工地/台账不匹配)

症状:`resident family worksite exists without readable ledger`。已知成因:失败 run 不写 `family-ledger.jsonl`(只留 start-head+progress)。处置三步:**审计开箱**(每个 git 找 unpushed/dirty,grep/文件名不算证据)→ **搬隔离**(`mv` 到 `quarantine-*`,永不 rm 未审内容;`quarantine-iso-497-preW1freeze` owner 令永不删)→ 重点火。

### 修复工作流(手派全禁)

PR/bot 冒 code finding → **立子票挂对应 epic(native sub-issue + ready-for-agent)→ 重跑 family,admission 自动收编**。票面只写 finding+不变式+验收,修法不写(已拍决策除外)。诊断腿(`/diagnosing-bugs`,只诊不修)是唯一手派例外,逐次经 owner 批。admission 认原生 blocked_by(OPEN 外部 blocker 自动跳过该子票)。landing Action(#941)管 bot 轮询→终判→merge→关票→清理——**别手抢它的活**。

### 当前战线快照(2026-07-23 13:00,易过期)

- 在飞:1117-r3(#1118/#1119,整合庭陪审 resume 修复)、1124-r2(#1125,决策门双接缝,owner 已批)。**跑完即全面暂停**(owner 令,额度不足)。
- 压队:两舰落 main → 513 复飞(#516/#523/#525 已有 C 裁决应答在台账+#1123 丢旨修复)→ PR #1120 收环 → 1115 复燃(凭证根治)→ PR #1121 CI 终绿即 merge。
- 挂账:#1102 #1104 #1108 #1113 #526;依赖族 6 片(#517/518/520/521/524/528)等 #474 的 #571→#560。
