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

import { execFileSync } from "node:child_process";

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
export function parseSubIssueNumbers(parsed: { subIssues?: unknown }): number[] {
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
  const subRaw = sh("gh", [
    "issue",
    "view",
    String(epicIssue),
    "--repo",
    repo,
    "--json",
    "subIssues",
  ]);
  const childNumbers = parseSubIssueNumbers(JSON.parse(subRaw) as { subIssues?: unknown });
  const blockedByByChild = new Map<number, GhBlockedBy[]>();
  for (const child of childNumbers) {
    const depRaw = sh("gh", [
      "api",
      `repos/${repo}/issues/${child}/dependencies/blocked_by`,
    ]);
    blockedByByChild.set(child, parseBlockedBy(JSON.parse(depRaw)));
  }
  return buildFamilyEpic(epicIssue, childNumbers, blockedByByChild);
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
 * A {@link RealFamilyBackend} whose integrated-cmr seam can be INJECTED by the
 * driver (the main orchestrator pins the real `ak-cross-m-review` bridge; the e2e
 * pins a controlled one). Everything else is the real implementation.
 */
class DriverFamilyBackend extends RealFamilyBackend {
  constructor(
    opts: ConstructorParameters<typeof RealFamilyBackend>[0],
    private readonly cmrImpl?: (req: IntegratedCmrRequest) => Promise<IntegratedCmrResult>,
  ) {
    super(opts);
  }
  protected override async runCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    if (this.cmrImpl !== undefined) return this.cmrImpl(req);
    // No injected cmr ⇒ the real `ak-cross-m-review` skill-bridge is unset; defer
    // to the base seam, which throws a precise "must be pinned by the driver /
    // manual-smoke path" message (never a fabricated convergence).
    return super.runCmr(req);
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
  const familyBaseStartHead = cutFamilyBase(workingRepo, options.familyBase, sh);

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
 * Cut the LOCAL family base branch from the just-fetched `origin/main` on the
 * family clone and return its start HEAD (the reconcile baseline). Idempotent: if
 * the branch already exists (a crash-resume re-entry on the same clone), reuse it
 * and read its current HEAD instead of re-cutting. The base is LOCAL (no
 * `git push`), accumulated onto by the merger.
 */
export function cutFamilyBase(workingRepo: string, familyBase: string, sh: Sh): string {
  const git = (...args: string[]): string => sh("git", ["-C", workingRepo, ...args]);
  // Already present (resume) ⇒ reuse; read its current HEAD as the baseline.
  if (branchExists(workingRepo, familyBase, sh)) {
    return git("rev-parse", familyBase);
  }
  // Fresh cut: refresh origin/main, then branch the local family base from it.
  // Best-effort fetch (an offline / local-only source must not block the cut).
  try {
    git("fetch", "origin", "main");
    git("branch", familyBase, "origin/main");
  } catch {
    // No remote main (a local-only source) ⇒ cut from the local main.
    git("branch", familyBase, "main");
  }
  return git("rev-parse", familyBase);
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
