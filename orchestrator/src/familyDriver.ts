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
 *   - The integrated cmr is a CONTAINER cmr WORKER (#335): the
 *     {@link RealFamilyBackend}'s `dispatchWorker` runs the 2b container's
 *     top-level claude invoking the real `ak-cross-m-review` skill (1 Agent + 2
 *     CLI legs, FRESH each round). The driver no longer手搓 the three reviewer
 *     CLIs nor injects a cmr impl — it just builds the RealFamilyBackend, whose
 *     unified worker seam owns the cmr leg.
 *   - The merger agent container / cmr worker / `gh pr create` / real push stay
 *     behind the RealFamilyBackend's protected seams; the driver only assembles.
 */

import { execFileSync } from "node:child_process";
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
   * reconcile + the container cmr worker via `dispatchWorker`, #335). The e2e may
   * inject one whose verify / cmr / PR seams are controlled (no container, no real
   * PR), while its merge / ledger / reconcile stay REAL — the "true family backend
   * 串起来" proof. The factory receives the family clone path so it anchors its git
   * ops there.
   */
  readonly familyBackendFactory?: (
    workingRepo: string,
    familyBaseStartHead: string,
  ) => FamilyBackend & { reconcileGit(): ReconcileGit };
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

  // 5. The family-LEVEL seam (real merge + ledger + verify + reconcile + the
  //    container cmr WORKER via `dispatchWorker`, #335), anchored on the SAME
  //    family clone. The integrated cmr is no longer手搓 / injected — the
  //    RealFamilyBackend's unified worker seam runs the real `ak-cross-m-review`
  //    container worker. The e2e may inject the whole family backend (controlled
  //    verify/cmr/PR, real merge/ledger/reconcile).
  const familyBackend =
    options.familyBackendFactory !== undefined
      ? options.familyBackendFactory(workingRepo, familyBaseStartHead)
      : new RealFamilyBackend({
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
          familyBaseStartHead,
          home: options.home,
        });

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

