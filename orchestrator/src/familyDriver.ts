/**
 * familyDriver.ts — the PRODUCTION family-run entry point (#291 Unit B).
 *
 * This is the first end-to-end assembly of the #291 family orchestration: it
 * takes a PARENT EPIC issue number (the family run key, ADR 0024) and:
 *
 *   1. reads the epic's already-cut children from LIVE GitHub via `gh` (the
 *      native sub-issues + each child's native `blocked_by` edges) and builds the
 *      {@link FamilyEpic} the commander schedules — NO LLM inference, just the
 *      explicit dependency metadata a `to-issues` step wrote (decision 1);
 *   2. constructs the two real seams keyed on the SAME family clone (ADR 0024):
 *      the single-slice {@link RealBackend} every child fan-out reuses (with the
 *      `familyBase` option so a child cuts from the LOCAL family base, decision 7)
 *      and the {@link RealFamilyBackend} (real `git merge --no-ff` + family ledger
 *      + verify + reconcile);
 *   3. cuts the LOCAL family base branch from main on the family clone, recording
 *      its start HEAD (the reconcile baseline when the ledger is empty);
 *   4. assembles the {@link FamilyRunInput} — wiring the RealFamilyBackend's
 *      `reconcileGit()` resume seam and a live `refetchEpic` rebuild hook — and
 *      calls {@link runFamily}, which fans the children out in dependency waves,
 *      serially merges each reviewed branch into the family base, and (via the
 *      verify-cmr hook) runs the family verify + integrated cmr + STOPS at the PR.
 *
 * SEAM BOUNDARY — what the driver does NOT hardcode:
 *   - The integrated cmr command form. `ak-cross-m-review` is a Claude *skill*
 *     orchestrated through the agent harness, NOT a single subprocess with a
 *     stable `{converged}` verdict to parse. So the REAL cmr invocation form is a
 *     decision for the MAIN orchestrator, not this driver: `runCmr` on the
 *     RealFamilyBackend stays the protected TODO-seam (it throws a precise message
 *     by default). The driver lets the caller INJECT a `runIntegratedCmr` impl
 *     (the e2e supplies a controlled one; a future wiring supplies the real
 *     skill-bridge), so the assembly is exercised end-to-end without pinning an
 *     unproven cmr subprocess contract.
 *   - The merger agent container / `gh pr create` / real push stay behind the
 *     RealFamilyBackend's protected seams (unchanged); the driver only assembles.
 */

import { execFile, execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { RealBackend } from "./realBackend.js";
import { parseBlockedBy, type GhBlockedBy } from "./realBackend.js";
import { RealFamilyBackend } from "./family/realFamilyBackend.js";
import { runFamily } from "./family/runner.js";
import type { Backend } from "./types.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyEpic,
  FamilyRunInput,
  FamilyRunResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  ReconcileGit,
} from "./family/types.js";

// ════════════════════════════════════════════════════════════════════════════
// PURE epic-assembly logic (unit-tested without live GitHub)
// ════════════════════════════════════════════════════════════════════════════

/**
 * Extract the child issue NUMBERS from `gh issue view <epic> --json subIssues`.
 *
 * The real shape is `{"subIssues":{"nodes":[{"number":N},…],"totalCount":N}}` (an
 * OBJECT — the same shape {@link parseSubIssueCount} reads the count off). The
 * driver needs the NUMBERS (each a child slice), so it reads `nodes[].number`.
 * Tolerates a non-object / non-array / missing-number value by skipping it (a
 * future/odd shape must not crash the assembly); de-dupes, preserving first-seen
 * order. Pure (parses a value only) so it is unit-tested without `gh`.
 */
export function parseSubIssueNumbers(parsed: { subIssues?: unknown } | null | undefined): number[] {
  // online R2 (Gemini): `JSON.parse` can yield null/undefined/a non-object — guard
  // before the property read so a malformed `gh` payload returns [] not a TypeError.
  if (parsed === null || typeof parsed !== "object") return [];
  const sub = parsed.subIssues;
  if (sub === null || typeof sub !== "object") return [];
  const nodes = (sub as { nodes?: unknown }).nodes;
  if (!Array.isArray(nodes)) return [];
  const seen = new Set<number>();
  const out: number[] = [];
  for (const n of nodes) {
    const num = (n as { number?: unknown })?.number;
    if (typeof num === "number" && Number.isFinite(num) && !seen.has(num)) {
      seen.add(num);
      out.push(num);
    }
  }
  return out;
}

/**
 * Build the {@link FamilyEpic} from the epic issue + each child's `blocked_by`
 * edges (decision 1). A child's `blockedBy` is the FULL native blocked_by number
 * list — the commander/spine itself splits intra-family vs external (it never
 * decomposes the epic, only reads these explicit edges). Pure: composes the
 * descriptor only, so the assembly is unit-tested without `gh`.
 */
export function buildFamilyEpic(
  epicIssue: number,
  childNumbers: ReadonlyArray<number>,
  blockedByByChild: ReadonlyMap<number, ReadonlyArray<GhBlockedBy>>,
): FamilyEpic {
  const children: ChildSlice[] = childNumbers.map((issue) => ({
    issue,
    blockedBy: (blockedByByChild.get(issue) ?? []).map((b) => b.number),
  }));
  return { issue: epicIssue, children };
}

/** A family child blocked by an EXTERNAL (non-family) issue still open at admission. */
export interface OpenExternalBlocker {
  readonly child: number;
  readonly blocker: number;
}

/** Fail-closed family admission: one or more external blockers are still open. */
export class FamilyExternalBlockerError extends Error {
  constructor(readonly openBlockers: ReadonlyArray<OpenExternalBlocker>) {
    super(
      `family admission rejected: ${openBlockers.length} external blocker(s) still open — ` +
        openBlockers.map((b) => `child #${b.child} blocked_by #${b.blocker}`).join("; "),
    );
    this.name = "FamilyExternalBlockerError";
  }
}

/**
 * Family-admission external-blocker gate (online R1 #1; user 2026-06-22, refines ADR
 * 0022 dec6③). An EXTERNAL `blocked_by` (an issue that is NOT one of this epic's
 * children) is never merged into the family ledger, so the commander's wave scheduler
 * cannot clear it. We do NOT lean on each child's family-mode S0 to reject an open
 * external blocker: dec6③ REWIRED the S0 `blocked_by`-closed check to the
 * ledger-merged口径, so an external open blocker is NOT reliably caught at S0 (and
 * relying on that indirection is fragile). Instead, validate them EXPLICITLY here,
 * up front, against the live `state` GitHub returned: ANY external blocker still open
 * fails-closed the WHOLE family run with the concrete offending list (which child,
 * which external issue) so the rejection is actionable. Closed (satisfied) external
 * blockers drop out, and the scheduler (selectWave) then gates ONLY on intra-family
 * blockers — those are the ones the family base can actually merge. A child's S0 still
 * runs against live GitHub as a backstop if an external blocker re-opens mid-run.
 */
export function assertExternalBlockersCleared(
  childNumbers: ReadonlyArray<number>,
  blockedByByChild: ReadonlyMap<number, ReadonlyArray<GhBlockedBy>>,
): void {
  const family = new Set(childNumbers);
  const openBlockers: OpenExternalBlocker[] = [];
  for (const child of childNumbers) {
    for (const b of blockedByByChild.get(child) ?? []) {
      if (!family.has(b.number) && b.state !== "closed") {
        openBlockers.push({ child, blocker: b.number });
      }
    }
  }
  if (openBlockers.length > 0) throw new FamilyExternalBlockerError(openBlockers);
}

// ════════════════════════════════════════════════════════════════════════════
// gh reader (a thin injectable subprocess seam)
// ════════════════════════════════════════════════════════════════════════════

/**
 * Run a host `gh` command, returning trimmed stdout. Injectable
 * ({@link FamilyDriverOptions.sh}) so the epic-read is testable without live
 * GitHub — the same `execFileSync` seam pattern RealBackend uses.
 */
export type Sh = (file: string, args: string[]) => string;

const defaultSh: Sh = (file, args) =>
  execFileSync(file, args, {
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf8",
  }).trim();

/**
 * Read the epic's children (native sub-issues + each child's blocked_by) from
 * live GitHub and build the {@link FamilyEpic}. Reuses the `gh` argv RealBackend's
 * S0 path uses (`gh issue view --json subIssues`, `gh api …/dependencies/blocked_by`).
 */
export function readFamilyEpic(epicIssue: number, repo: string, sh: Sh): FamilyEpic {
  const childNumbers = readChildNumbers(epicIssue, repo, sh);
  const blockedByByChild = new Map<number, GhBlockedBy[]>();
  for (const child of childNumbers) {
    const depRaw = sh("gh", [
      "api",
      `repos/${repo}/issues/${child}/dependencies/blocked_by`,
    ]);
    blockedByByChild.set(child, parseBlockedBy(JSON.parse(depRaw)));
  }
  // Family-admission gate (online R1 #1): fail-closed up front if any EXTERNAL blocker
  // is still open — runs on the initial admission AND on every resume refetch, so a
  // re-opened external blocker re-rejects on re-entry.
  assertExternalBlockersCleared(childNumbers, blockedByByChild);
  return buildFamilyEpic(epicIssue, childNumbers, blockedByByChild);
}

/**
 * Read the epic's child issues, failing closed if there are NONE (online R2 Codex
 * P2): a leaf issue mis-passed as an epic — or an empty/odd `subIssues` payload —
 * yields zero children, which `runFamily` would treat as already-complete (`every`
 * over `[]` is vacuously true) → a final verify/cmr on a base with no slices → an
 * empty PR. Reject it at admission with a concrete message.
 */
function readChildNumbers(epicIssue: number, repo: string, sh: Sh): number[] {
  const subRaw = sh("gh", ["issue", "view", String(epicIssue), "--repo", repo, "--json", "subIssues"]);
  const childNumbers = parseSubIssueNumbers(JSON.parse(subRaw) as { subIssues?: unknown });
  if (childNumbers.length === 0) {
    throw new Error(
      `family admission rejected: epic #${epicIssue} has no child issues ` +
        `(not an epic, or its native sub-issues are empty) — nothing to orchestrate`,
    );
  }
  return childNumbers;
}

// ════════════════════════════════════════════════════════════════════════════
// the production driver
// ════════════════════════════════════════════════════════════════════════════

/** Tunables for {@link runFamilyDriver}. */
export interface FamilyDriverOptions {
  /** The PARENT EPIC issue number — the family run key (ADR 0024). */
  readonly epicIssue: number;
  /** The SOURCE repo to clone (path or URL) — the family clone is cut from it. */
  readonly sourceRepo: string;
  /** The repo's git remote URL (clone-path slug derivation; optional local-only). */
  readonly remote?: string;
  /** GitHub repo slug for `gh` (`owner/name`). */
  readonly repo: string;
  /** The LOCAL family base branch the merger accumulates onto (decision 7). */
  readonly familyBase: string;
  /** The branch the family PR targets (e.g. "main"). */
  readonly base: string;
  /** Dir holding the versioned single-slice promptFiles (absolute). */
  readonly promptsDir: string;
  /** Dir holding the family-layer promptFiles (the merger conflict prompt). */
  readonly familyPromptsDir: string;
  /** Where the append-only family ledger + escalation records live (outside the worktree). */
  readonly ledgerDir: string;
  /** The profile image (toolchain + souls + model CLIs baked in). */
  readonly imageName: string;
  /** Host dir holding the baked dev skills to bind-mount. */
  readonly skillsMount: string;
  /** Override $HOME (tests / non-default auth root). */
  readonly home?: string;
  /** The `gh` subprocess seam (default `execFileSync gh …`; injected in tests). */
  readonly sh?: Sh;
  /**
   * The integrated-cmr impl injected onto the RealFamilyBackend (the SEAM the main
   * orchestrator pins). When absent, the RealFamilyBackend's protected `runCmr`
   * TODO-seam throws (the real `ak-cross-m-review` skill-bridge is the main
   * orchestrator's decision — see the file header). The e2e supplies a controlled
   * one so the assembly is exercised without an unproven cmr subprocess contract.
   */
  readonly runIntegratedCmr?: (req: IntegratedCmrRequest) => Promise<IntegratedCmrResult>;
  /**
   * Override the single-slice Backend each child fan-out uses. Production leaves
   * this unset → the driver builds the real {@link RealBackend} on the family clone
   * (the `sc.run` child container path). The e2e injects a controlled
   * container-free Backend that produces a REAL committed child branch on the
   * family clone (so the family-LEVEL real merge / ledger / reconcile are exercised
   * end-to-end without starting a container). The factory receives the family
   * clone path the family base was cut on, so the injected Backend commits there.
   */
  readonly singleSliceBackendFactory?: (workingRepo: string) => Backend;
  /**
   * Override the family-LEVEL Backend. Production leaves this unset → the driver
   * builds the real {@link RealFamilyBackend} (real merge / ledger / verify /
   * reconcile) with the injected `runIntegratedCmr`. The e2e may inject one whose
   * verify / cmr / PR seams are controlled (no container, no real PR), while its
   * merge / ledger / reconcile stay REAL — the "true family backend串起来" proof.
   * The factory receives the family clone path so it anchors its git ops there.
   */
  readonly familyBackendFactory?: (
    workingRepo: string,
    familyBaseStartHead: string,
  ) => FamilyBackend & { reconcileGit(): ReconcileGit };
}

/**
 * A {@link RealFamilyBackend} whose integrated-cmr 承重闸 is a REAL autonomous
 * 3-leg reviewer-CLI orchestration (#291 last gap).
 *
 * The integrated cmr is ship-pre-grade: it must catch the 跨片接缝 (field-name /
 * type / 阈值口径 / 组合 e2e) that per-slice cmr cannot see. `ak-cross-m-review`
 * is a Claude *skill* orchestrated through the agent harness, NOT stably invocable
 * from inside this runtime — so the thin封装 that IS right here is to spawn the
 * three reviewer CLIs DIRECTLY (`claude` + `codex` + `agy`, 1+1+1), each reviewing
 * the family base diff independently, and parse their convergence verdicts.
 *
 * KEY: the parse is over PROSE, NOT a sentinel-JSON format gate. codex is a prose
 * reviewer; demanding a sentinel-JSON envelope would synthesise an empty verdict
 * and throw away the strongest leg (the `codex-no-sentinel-is-prose-not-empty`
 * lesson). So each leg's stdout is read as prose and classified by
 * {@link parseReviewerVerdict}.
 *
 * DEGRADATION: a leg whose CLI exits non-zero / emits empty output / is auth/quota
 * down (agy is commonly down on this host) is FLAGGED missing and the verdict is
 * judged from the remaining legs — a missing reviewer is NOT a finding (the cmr
 * 降级链). This is ONE pass: a non-convergence is handed to the spine's escalate
 * seam, not looped here.
 *
 * The driver may still INJECT a `cmrImpl` (the e2e pins a controlled one); when
 * absent, the real 3-leg path runs.
 */
export class DriverFamilyBackend extends RealFamilyBackend {
  constructor(
    opts: ConstructorParameters<typeof RealFamilyBackend>[0],
    private readonly cmrImpl?: (req: IntegratedCmrRequest) => Promise<IntegratedCmrResult>,
  ) {
    super(opts);
  }

  /**
   * The integrated cmr 承重闸: pin the family base diff, fan it out to the three
   * reviewer legs, and aggregate their prose verdicts (all pass → converged; any
   * findings → red + reason; a down leg degrades; never a fabricated pass).
   */
  protected override async runCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    // An injected impl (the e2e's controlled cmr) wins — the assembly stays
    // exercisable without spawning the real squad.
    if (this.cmrImpl !== undefined) return this.cmrImpl(req);

    // 1. Pin the family base diff vs the PR target (`git diff <base>...<familyBase>`,
    //    the symmetric-difference form: the commits on the family base since it
    //    diverged from the target). This is what every leg reviews.
    const diff = this.familyBaseDiff(req.familyBase);

    // 2. Fan the SAME diff out to all three reviewer legs concurrently, each through
    //    the protected `runReviewer` seam (fixtured in unit tests; the real CLIs on
    //    the driver / manual-smoke path). A leg that throws/dies is caught into a
    //    down output (degrade, never crash the whole gate).
    const vendors: ReviewerVendor[] = ["codex", "claude", "agy"];
    const outputs = await Promise.all(
      vendors.map(async (vendor): Promise<ReviewerLeg> => {
        let out: ReviewerOutput;
        try {
          out = await this.runReviewer(vendor, diff);
        } catch (err) {
          out = { ok: false, reason: err instanceof Error ? err.message : String(err) };
        }
        return reviewerLegFromOutput(vendor, out);
      }),
    );

    // 3. Aggregate the three prose verdicts into the load-bearing converged/red gate.
    return aggregateCmr(outputs);
  }

  /**
   * The family base diff every reviewer leg reviews — `git diff
   * <familyBaseStartHead>...<familyBase>` (the symmetric-difference: the commits the
   * family base added since it was CUT). `protected` so a unit test pins it without a
   * real repo.
   *
   * cmr R2 #1: this used `<opts.base>...<familyBase>`, the LOCAL `base` ref — but the
   * family base is cut from the just-fetched `origin/<base>` while the local `base`
   * ref is NOT refreshed, so a stale local base shows the upstream's own commits as
   * spurious family additions and the reviewers审 upstream code as family changes. The
   * recorded cut SHA (`familyBaseStartHead`) is the exact point the family base
   * diverged — the cleanest, drift-proof left side. Fail-closed when it is absent: a
   * cmr 承重闸 must not silently fall back to a ref that pollutes the reviewed diff.
   */
  protected familyBaseDiff(familyBase: string): string {
    const startHead = this.opts.familyBaseStartHead;
    if (startHead === undefined) {
      throw new Error(
        "familyBaseDiff: no familyBaseStartHead was recorded at run setup — it is " +
          "the cut point the integrated cmr diffs the family base against; refusing " +
          "to fall back to the local base ref (which can be stale and would pollute " +
          "the reviewed diff with upstream commits). Provide " +
          "RealFamilyBackendOptions.familyBaseStartHead.",
      );
    }
    return this.sh("git", ["diff", `${startHead}...${familyBase}`]);
  }

  /**
   * Spawn ONE reviewer CLI over the family base diff and return its prose output.
   * `protected` so a unit test fixtures the prose without a real claude/codex/agy
   * (the real CLIs only run on the driver / manual-smoke path). The三个 invocations
   * mirror the per-slice cmr reviewer legs:
   *   - codex (承重, xhigh): `codex exec --ephemeral -c model_reasoning_effort=xhigh
   *     --model gpt-5.5 -o <file>` — read the last-message散文 off `<file>`;
   *   - claude:             `claude -p --model <最强> --output-format json` — read
   *     the `.result`散文 off the JSON;
   *   - agy:                `agy --sandbox --print '' --print-timeout 15m --log-file
   *     <log>` — read the printed散文.
   * Each prompt = "review THIS family base diff, 专抓跨片接缝, review only, 收敛就出
   * `CMR-VERDICT: converged`". A non-zero exit / empty output / auth-quota death
   * returns `{ok:false}` so the leg degrades (a missing reviewer ≠ a finding).
   */
  protected async runReviewer(vendor: ReviewerVendor, diff: string): Promise<ReviewerOutput> {
    const prompt = reviewerPrompt(diff);
    try {
      const prose = await this.spawnReviewer(vendor, prompt);
      return { ok: true, prose };
    } catch (err) {
      // CLI non-zero exit / spawn failure / auth-quota death ⇒ this leg is down
      // (degrade, never a finding). Carry the reason for the audit trail.
      return { ok: false, reason: err instanceof Error ? err.message : String(err) };
    }
  }

  /**
   * Spawn the concrete reviewer CLI for one vendor and return its prose verdict.
   * `protected` so the wiring is overridable; the default forms mirror the
   * per-slice cmr legs. Reads the vendor's natural prose sink (codex's `-o`
   * last-message file, claude's `.result`, agy's printed stdout).
   */
  protected async spawnReviewer(vendor: ReviewerVendor, prompt: string): Promise<string> {
    const repo = this.opts.workingRepo;
    if (vendor === "codex") {
      // codex (承重, xhigh): the prompt is piped in; the last-message散文 is written
      // to `-o <file>` (the clean output; logs go to stderr).
      // A per-spawn `randomUUID()` (not just `Date.now()`): the three legs run
      // concurrently, so two same-millisecond codex spawns would otherwise pick the
      // SAME out-file and clobber each other's last-message散文 (cmr R2 #5).
      const outFile = join(this.opts.ledgerDir, `cmr-codex-${Date.now()}-${randomUUID()}.txt`);
      await this.shStdin(
        "codex",
        [
          "exec",
          "--ephemeral",
          "--skip-git-repo-check",
          "-c",
          "model_reasoning_effort=xhigh",
          "--model",
          "gpt-5.5",
          "-o",
          outFile,
        ],
        prompt,
        repo,
      );
      return readFileSync(outFile, "utf8").trim();
    }
    if (vendor === "claude") {
      // claude: `-p --output-format json`; the散文 is the `.result` field.
      const raw = await this.shStdin(
        "claude",
        ["-p", "--model", CMR_CLAUDE_MODEL, "--output-format", "json"],
        prompt,
        repo,
      );
      const parsed = JSON.parse(raw) as { result?: unknown };
      return typeof parsed.result === "string" ? parsed.result.trim() : "";
    }
    // agy: `--sandbox --print '' --print-timeout 15m --log-file <log>`; the散文 is
    // the printed stdout (logs go to the log file).
    const logFile = join(this.opts.ledgerDir, `cmr-agy-${Date.now()}-${randomUUID()}.log`);
    return (
      await this.shStdin(
        "agy",
        ["--sandbox", "--print", "", "--print-timeout", "15m", "--log-file", logFile],
        prompt,
        repo,
      )
    ).trim();
  }

  /**
   * Run a host command feeding `stdin`, returning trimmed stdout — ASYNCHRONOUSLY
   * (cmr R2 #3). The reviewer prompt (which carries the whole diff) goes on STDIN,
   * not argv — too large / unsafe for an argument. `protected` so a unit test
   * intercepts the spawn (the fixtured backend overrides `runReviewer` /
   * `spawnReviewer` above this层 anyway).
   *
   * It MUST be async: `runCmr` fans the three legs out with `Promise.all`, but a
   * synchronous `execFileSync` would BLOCK the event loop for the whole CLI run, so
   * the three "concurrent" legs ran strictly SERIALLY (total = sum, not max — a
   * 3× latency hit on the ship-pre 承重闸). `promisify(execFile)` lets the three
   * child processes run truly concurrently.
   */
  protected async shStdin(file: string, args: string[], input: string, cwd?: string): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      // `execFile` (callback form) returns the ChildProcess SYNCHRONOUSLY, so we can
      // feed the prompt on stdin (it is too large / unsafe for argv) AND get the
      // async completion — unlike `promisify(execFile)`, which loses the stdin
      // handle, and unlike `execFileSync`, which blocks the event loop (the假并发).
      const child = execFile(
        file,
        args,
        { cwd: cwd ?? this.opts.workingRepo, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
        (err, stdout) => {
          if (err !== null) reject(err);
          else resolve(stdout.trim());
        },
      );
      // Write the prompt to stdin and close it so the CLI sees EOF. A child that
      // failed to spawn has no stdin — guard so we surface the spawn error (via the
      // callback), not an unrelated "write after end".
      if (child.stdin !== null) {
        // online R3 (Gemini): a reviewer CLI that dies mid-write (timeout / crash —
        // common on the runIntegratedCmr path feeding a large prompt) makes this
        // write emit `'error'` (EPIPE / ERR_STREAM_WRITE_AFTER_END). An UNHANDLED
        // stream `'error'` crashes the whole Node process; swallow it here — the real
        // failure already surfaces via the execFile callback's `err`.
        child.stdin.on("error", () => {});
        child.stdin.end(input);
      }
    });
  }
}

/**
 * Run one family orchestration end-to-end (#291 Unit B).
 *
 * Reads the epic's children from live GitHub, constructs the two real seams on the
 * SAME family clone, cuts the local family base from main, and runs the family
 * spine. STOPS at the PR (the family orchestrator's autonomy ends there; online
 * bot cmr + merge to main are the separate pr-review-loop stage).
 *
 * @returns the {@link FamilyRunResult} — the per-child outcomes + the merged
 *   family base HEAD + the honest run status (success / verify_failed / incomplete
 *   / escalated).
 */
export async function runFamilyDriver(
  options: FamilyDriverOptions,
): Promise<FamilyRunResult> {
  const sh = options.sh ?? defaultSh;

  // 1. Read the already-cut children from live GitHub (the explicit dependency
  //    edges a `to-issues` step wrote — decision 1, no LLM inference).
  const epic = readFamilyEpic(options.epicIssue, options.repo, sh);

  // 2. The single-slice RealBackend: keyed on the PARENT epic so all children
  //    share ONE family clone (ADR 0024). Constructing it CLONES the source (pure
  //    git, no container) — that clone is the family clone every git op anchors on.
  //    `familyBase` makes a child cut from the LOCAL family base (decision 7).
  const realSingleSlice = new RealBackend({
    sourceRepo: options.sourceRepo,
    remote: options.remote,
    runKey: options.epicIssue,
    repo: options.repo,
    imageName: options.imageName,
    skillsMount: options.skillsMount,
    promptsDir: options.promptsDir,
    home: options.home,
    familyBase: options.familyBase,
  });
  const workingRepo = realSingleSlice.workingRepoPath();

  // 3. Cut the LOCAL family base branch from main on the family clone, recording
  //    its start HEAD (the reconcile baseline when the ledger is empty). The base
  //    is a LOCAL branch the merger accumulates onto, with no remote counterpart.
  //    The cut SHA is PERSISTED in the ledgerDir (a sibling of the family ledger,
  //    OUTSIDE the worktree) so a RESUME reads back the ORIGINAL start head, not the
  //    (advanced) live HEAD — the empty-ledger crash-window net depends on it (#2).
  const familyBaseStartHead = cutFamilyBase(
    workingRepo,
    options.familyBase,
    options.base,
    sh,
    options.ledgerDir,
  );

  // 4. The single-slice Backend each child fan-out actually uses: the real
  //    RealBackend in production (the `sc.run` child container path), or the e2e's
  //    injected container-free Backend committing a real child branch on the clone.
  const singleSliceBackend: Backend =
    options.singleSliceBackendFactory !== undefined
      ? options.singleSliceBackendFactory(workingRepo)
      : realSingleSlice;

  // 5. The family-LEVEL seam (real merge + ledger + verify + reconcile), anchored
  //    on the SAME family clone. The integrated-cmr impl is injected (the main
  //    orchestrator's pinned `ak-cross-m-review` bridge / the e2e's controlled one).
  //    The e2e may inject the whole family backend (controlled verify/cmr/PR, real
  //    merge/ledger/reconcile).
  const familyBackend =
    options.familyBackendFactory !== undefined
      ? options.familyBackendFactory(workingRepo, familyBaseStartHead)
      : new DriverFamilyBackend(
          {
            workingRepo,
            // The orchestrator Node project (package.json / vitest config) is the
            // `orchestrator/` subdir of the full-repo clone — verify runs THERE,
            // not the clone root (online R2 Codex P1).
            verifyCwd: join(workingRepo, "orchestrator"),
            familyBase: options.familyBase,
            ledgerDir: options.ledgerDir,
            repo: options.repo,
            base: options.base,
            promptsDir: options.familyPromptsDir,
            imageName: options.imageName,
            skillsMount: options.skillsMount,
            familyBaseStartHead,
          },
          options.runIntegratedCmr,
        );

  // 6. Assemble the run input + the resume seams, and run the spine.
  const input: FamilyRunInput = {
    epic,
    familyBackend,
    singleSliceBackend,
    familyBase: options.familyBase,
    // The crash-window reconcile resume seam (decision 5): on a re-entry the spine
    // compares the ledger末条 head to the live family-base HEAD and补账/escalates.
    reconcileGit: familyBackend.reconcileGit(),
    // The escalate-resume rebuild hook (decision 4): a re-entry rebuilds the
    // dependency graph from LIVE GitHub, not the cached epic.
    refetchEpic: async () => readFamilyEpic(options.epicIssue, options.repo, sh),
  };
  return runFamily(input);
}

/**
 * The persisted family-base start-head filename (under the `ledgerDir`, a sibling of
 * the family ledger and OUTSIDE the worktree, so a worktree clean cannot touch it —
 * the ADR 0022 decision-5 resume-truth location).
 */
export const FAMILY_BASE_START_HEAD_FILENAME = "family-base-start-head";

/**
 * Cut the LOCAL family base branch from the just-fetched `origin/<base>` on the
 * family clone and return its START HEAD (the reconcile baseline). `base` is the
 * PR TARGET branch the family run was configured with (`options.base`) — NOT a
 * hardcoded "main": the family base must be cut from the SAME ref `familyBaseDiff`
 * diffs against, else a non-`main` target would both cut from the wrong branch AND
 * show the target's own commits as spurious family additions (agy cmr R1). The base
 * is LOCAL (no `git push`), accumulated onto by the merger.
 *
 * The start HEAD is PERSISTED in `ledgerDir` on the FRESH cut and RE-READ on RESUME
 * (cmr R2 #2). The earlier code returned `git rev-parse <familyBase>` on resume —
 * i.e. the CURRENT (post-merge, advanced) HEAD — so the empty-ledger crash-window
 * net (reconcile.ts: escalate iff `liveHead !== startHead`) saw `liveHead ===
 * startHead` trivially and was SILENTLY DISABLED (fail-OPEN: a base that moved with
 * no child to explain it would not escalate). The persisted SHA keeps the start head
 * pinned to the divergence point across resumes. Idempotent on the branch itself: an
 * existing family base is REUSED (no re-cut, no lost waves). Fail-CLOSED if the
 * branch exists but the persisted head is gone (no fall-back to the live HEAD).
 */
export function cutFamilyBase(
  workingRepo: string,
  familyBase: string,
  base: string,
  sh: Sh,
  ledgerDir: string,
): string {
  const git = (...args: string[]): string => sh("git", ["-C", workingRepo, ...args]);
  const startHeadFile = join(ledgerDir, FAMILY_BASE_START_HEAD_FILENAME);
  // Already present (resume) ⇒ reuse the branch (no re-cut), but return the PERSISTED
  // original start head, NOT the advanced HEAD. Missing/unreadable persisted head ⇒
  // fail closed (do not fall back to the live HEAD, which defeats the crash net).
  if (branchExists(workingRepo, familyBase, sh)) {
    let persisted: string;
    try {
      persisted = readFileSync(startHeadFile, "utf8").trim();
    } catch (err) {
      throw new Error(
        `cutFamilyBase: the family base "${familyBase}" already exists (resume) but the ` +
          `persisted start head at ${startHeadFile} is missing/unreadable — refusing to ` +
          `fall back to the live HEAD (which would silently disable the empty-ledger ` +
          `crash-window net). Fail-closed. (${err instanceof Error ? err.message : String(err)})`,
      );
    }
    if (persisted.length === 0) {
      throw new Error(
        `cutFamilyBase: the persisted start head at ${startHeadFile} is empty — ` +
          `fail-closed (cannot trust an empty baseline).`,
      );
    }
    return persisted;
  }
  // Fresh cut: refresh origin/<base>, then branch the local family base from it.
  // Best-effort fetch (an offline / local-only source must not block the cut).
  try {
    git("fetch", "origin", base);
    git("branch", familyBase, `origin/${base}`);
  } catch {
    // No remote <base> (a local-only source) ⇒ cut from the local <base>.
    git("branch", familyBase, base);
  }
  const startHead = git("rev-parse", familyBase);
  // Persist the cut SHA durably (outside the worktree) so a resume reads it back.
  mkdirSync(ledgerDir, { recursive: true });
  writeFileSync(startHeadFile, startHead + "\n", "utf8");
  return startHead;
}

/** Does a local branch exist on the clone? (`-q`: no stderr noise when absent.) */
function branchExists(workingRepo: string, branch: string, sh: Sh): boolean {
  try {
    sh("git", ["-C", workingRepo, "rev-parse", "-q", "--verify", `refs/heads/${branch}`]);
    return true;
  } catch {
    return false;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// integrated cmr 承重闸 — the 3-leg reviewer-CLI orchestration (#291 last gap)
// ════════════════════════════════════════════════════════════════════════════

/** The reviewer the integrated cmr spawns (one CLI per vendor, 1+1+1). */
export type ReviewerVendor = "codex" | "claude" | "agy";

/** The claude reviewer leg runs on the strongest reviewer model. */
const CMR_CLAUDE_MODEL = "claude-opus-4-8";

/**
 * One reviewer CLI's raw outcome. `ok:false` ⇒ the CLI died (non-zero exit /
 * spawn failure / auth-quota death) — the leg degrades, it is NOT a finding.
 */
export interface ReviewerOutput {
  /** Did the reviewer CLI run and produce output? `false` ⇒ down (degrade). */
  readonly ok: boolean;
  /** The reviewer's PROSE verdict (read off its natural sink). */
  readonly prose?: string;
  /** Why the leg is down (a CLI error message), for the audit trail. */
  readonly reason?: string;
}

/** One reviewer leg's classified verdict after parsing its prose. */
export interface ReviewerLeg {
  readonly vendor: ReviewerVendor;
  /**
   * - `"pass"`     — the leg converged / found nothing (counts toward convergence);
   * - `"findings"` — the leg flagged a cross-slice seam issue (blocks convergence);
   * - `"down"`     — the CLI did not run / emitted nothing (degrade, never a finding).
   */
  readonly status: "pass" | "findings" | "down";
  /** The finding prose (on `"findings"`) or the down reason (on `"down"`). */
  readonly reason?: string;
}

/** The integrated cmr reviewer prompt for one family base diff. */
export function reviewerPrompt(diff: string): string {
  return (
    "You are an independent integrated cross-model reviewer (ship-pre 承重闸) for a " +
    "FAMILY base branch — the accumulation of several reviewed vertical-slice child " +
    "branches merged together.\n\n" +
    "REVIEW ONLY — do not edit any file. Focus on the CROSS-SLICE SEAMS that " +
    "per-slice review cannot see: field-name / type mismatches between slices, " +
    "inconsistent thresholds / units, contract drift, and behaviour that only " +
    "emerges once the slices are combined (e2e).\n\n" +
    "When you are done, end with EXACTLY ONE verdict line:\n" +
    "  `CMR-VERDICT: converged`      — if you found NO blocking cross-slice issue;\n" +
    "  `CMR-VERDICT: not converged`  — followed by your findings, if you did.\n\n" +
    "Here is the family base diff to review:\n\n" +
    "```diff\n" +
    diff +
    "\n```\n"
  );
}

/**
 * Classify ONE reviewer leg from its raw CLI output. A down CLI (`ok:false`) or an
 * empty-prose run degrades to `"down"` (a missing reviewer is NEVER a finding —
 * the cmr 降级链); otherwise the prose is read by {@link parseReviewerVerdict}.
 * Pure so the degrade vs parse split is unit-tested without a CLI.
 */
export function reviewerLegFromOutput(vendor: ReviewerVendor, out: ReviewerOutput): ReviewerLeg {
  if (!out.ok || out.prose === undefined || out.prose.trim().length === 0) {
    return { vendor, status: "down", reason: out.reason ?? "reviewer produced no output" };
  }
  const v = parseReviewerVerdict(vendor, out.prose);
  return v.pass
    ? { vendor, status: "pass" }
    : { vendor, status: "findings", reason: v.reason };
}

/** One reviewer leg's parsed prose verdict. */
export interface ReviewerVerdict {
  readonly vendor: ReviewerVendor;
  /** Did the leg converge (no blocking finding)? */
  readonly pass: boolean;
  /** The finding prose when `pass` is false. */
  readonly reason?: string;
}

/**
 * Parse a reviewer's PROSE verdict (NOT a sentinel-JSON gate — codex is a prose
 * reviewer; demanding sentinel-JSON would throw the strongest leg away). A leg is
 * a PASS iff it explicitly converged: the `CMR-VERDICT: converged` sentinel, or —
 * absent the sentinel — a "converged" / "no findings" signal that is NOT negated.
 * An explicit `not converged` / `no[t] converged` always wins over an incidental
 * "converged" substring. Pure so the verdict口径 is unit-tested without a CLI.
 */
export function parseReviewerVerdict(vendor: ReviewerVendor, prose: string): ReviewerVerdict {
  const text = prose.trim();
  const lower = text.toLowerCase();
  // The explicit sentinel is authoritative when present.
  if (/cmr-verdict:\s*not\s+converged/.test(lower)) {
    return { vendor, pass: false, reason: text };
  }
  if (/cmr-verdict:\s*converged/.test(lower)) {
    return { vendor, pass: true };
  }
  // No sentinel ⇒ read the prose. An explicit NEGATED convergence is a finding,
  // even though "converged" appears as a substring — so it must be caught BEFORE the
  // positive `\bconverged\b` fallback below (else the negation false-passes). The
  // naive `\b(not|no)\s+converge` missed two real forms (cmr R1):
  //   - the AFFIX form `non-converged` / `unconverged`: `-` is a non-word char, so a
  //     plain `\bconverged\b` matches the `converged` inside `non-converged` (codex);
  //   - an INTERPOSED adverb `not yet/fully/completely converged`: the adverb breaks
  //     a `\s+`-adjacency guard, so the positive fallback fires (agy).
  // So allow up to 3 interposed words between the negator and `converg`, plus the
  // affix and `fail(ed) to converge` forms. The interposed gap uses `(?:\s+\w+)`
  // (whitespace-then-word), so punctuation (a comma / period / semicolon) breaks the
  // chain — a separate clause like "no findings; converged" does NOT trip it.
  const negated =
    /\b(?:non|un)-?converg/.test(lower) || // non-converged / unconverged
    /\b(?:not|never|cannot)\b(?:\s+\w+){0,3}[\s-]+converg/.test(lower) || // not [adv]{0,3} converge (online R1 Gemini: a HYPHEN-joined adverb `not fully-converged` must also negate)
    /n't\b(?:\s+\w+){0,3}[\s-]+converg/.test(lower) || // didn't / doesn't / can't … converge
    /\bfail(?:s|ed|ing|ure)?\s+to\s+converg/.test(lower); // fail(ed/s/ure) to converge
  if (negated) {
    return { vendor, pass: false, reason: text };
  }
  if (/\bconverged\b/.test(lower) || /\bno findings?\b/.test(lower)) {
    return { vendor, pass: true };
  }
  // Neither converged nor an explicit no-findings signal ⇒ treat the prose as
  // findings (fail-closed: an ambiguous reviewer is not waved through).
  return { vendor, pass: false, reason: text };
}

/**
 * Aggregate the three reviewer legs into the load-bearing converged/red gate
 * (decision 3⑥). RULES:
 *   - ANY leg with `"findings"` ⇒ NOT converged, reason = the findings legs joined;
 *   - else if at least one leg `"pass"`ed (the rest down) ⇒ converged (degrade: a
 *     missing reviewer is not a finding);
 *   - else (ALL legs down) ⇒ NOT converged FAIL-CLOSED — no reviewer ran, so the
 *     gate must never fabricate a pass.
 * One pass only: a non-convergence is handed to the spine's escalate seam, not
 * looped here. Pure so the口径 is unit-tested without spawning the squad.
 */
export function aggregateCmr(legs: ReadonlyArray<ReviewerLeg>): IntegratedCmrResult {
  const findings = legs.filter((l) => l.status === "findings");
  if (findings.length > 0) {
    const reason = findings
      .map((l) => `[${l.vendor}] ${l.reason ?? "findings"}`)
      .join("\n\n");
    return { converged: false, reason };
  }
  const passed = legs.filter((l) => l.status === "pass");
  if (passed.length > 0) {
    // At least one reviewer ran and converged; any down legs degraded (the
    // 降级链). The remaining-leg verdict converges.
    return { converged: true };
  }
  // Every leg is down — no reviewer ran. Fail-closed: never a fabricated pass.
  const downReasons = legs
    .map((l) => `[${l.vendor}] ${l.reason ?? "down"}`)
    .join("; ");
  return {
    converged: false,
    reason: `integrated cmr could not run: all reviewer legs were down (no reviewer ran) — ${downReasons}`,
  };
}
