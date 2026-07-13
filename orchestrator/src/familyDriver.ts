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

import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { shWithClock } from "./externalCall.js";
import { RealBackend, type RealBackendOptions } from "./realBackend.js";
import { parseBlockedBy, type GhBlockedBy } from "./realBackend.js";
import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "./family/realFamilyBackend.js";
import { runFamily } from "./family/runner.js";
import {
  parseModuleDeclaration,
  sourcedModuleDeclaration,
  type SourcedModuleDeclaration,
} from "./family/moduleDeclaration.js";
import { logDriverStage } from "./stageLog.js";
import type { Backend } from "./types.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyAdmissionSkippedChild,
  FamilyEpic,
  FamilyRunInput,
  FamilyRunResult,
  ReconcileGit,
} from "./family/types.js";

// ════════════════════════════════════════════════════════════════════════════
// PURE epic-assembly logic (unit-tested without live GitHub)
// ════════════════════════════════════════════════════════════════════════════

/** One child excluded from this family run before wave scheduling. */
export interface SkippedFamilyChild {
  readonly issue: number;
  readonly reason: "closed" | "not_ready_for_agent" | "parent_issue";
  readonly message: string;
}

export interface SubIssueAdmission {
  readonly admitted: ReadonlyArray<number>;
  readonly skipped: ReadonlyArray<SkippedFamilyChild>;
}

function subIssueNodes(parsed: unknown): unknown[] {
  // REST native sub-issues endpoint: `gh api repos/O/R/issues/<epic>/sub_issues`.
  if (Array.isArray(parsed)) return parsed;
  // Older/newer gh GraphQL shape retained for pure parser compatibility.
  if (parsed === null || typeof parsed !== "object") return [];
  const sub = (parsed as { subIssues?: unknown }).subIssues;
  if (sub === null || typeof sub !== "object") return [];
  const nodes = (sub as { nodes?: unknown }).nodes;
  return Array.isArray(nodes) ? nodes : [];
}

function labelNames(node: unknown): string[] | undefined {
  const raw = (node as { labels?: unknown })?.labels;
  if (raw === undefined) return undefined;
  const labels = Array.isArray(raw)
    ? raw
    : raw !== null && typeof raw === "object" && Array.isArray((raw as { nodes?: unknown }).nodes)
      ? (raw as { nodes: unknown[] }).nodes
      : undefined;
  return labels
    ?.map((l) => (l as { name?: unknown })?.name)
    .filter((name): name is string => typeof name === "string");
}

function subIssueCount(node: unknown): number | undefined {
  const restSummary = (node as { sub_issues_summary?: unknown })?.sub_issues_summary;
  if (restSummary !== null && typeof restSummary === "object") {
    const total = (restSummary as { total?: unknown }).total;
    if (typeof total === "number" && Number.isFinite(total)) return total;
  }
  const graphSubIssues = (node as { subIssues?: unknown })?.subIssues;
  if (graphSubIssues !== null && typeof graphSubIssues === "object") {
    const total = (graphSubIssues as { totalCount?: unknown }).totalCount;
    if (typeof total === "number" && Number.isFinite(total)) return total;
  }
  return undefined;
}

function skipReason(node: unknown): SkippedFamilyChild["reason"] | undefined {
  const state = (node as { state?: unknown })?.state;
  if (typeof state === "string" && state.toUpperCase() === "CLOSED") return "closed";

  const labels = labelNames(node);
  if (labels !== undefined && !labels.includes("ready-for-agent")) return "not_ready_for_agent";

  const children = subIssueCount(node);
  if (children !== undefined && children > 0) return "parent_issue";

  return undefined;
}

function skipMessage(issue: number, reason: SkippedFamilyChild["reason"]): string {
  switch (reason) {
    case "closed":
      return `family admission skipped child #${issue}: issue is CLOSED`;
    case "not_ready_for_agent":
      return `family admission skipped child #${issue}: missing ready-for-agent label`;
    case "parent_issue":
      return `family admission skipped child #${issue}: issue is a parent issue`;
  }
}

/**
 * Split native sub-issues into runnable children vs visible skips.
 *
 * The production reader uses GitHub's REST native sub-issues endpoint because it
 * carries the metadata needed for the family admission rule: state, labels, and
 * whether the child is itself a parent. A child is runnable when it is open,
 * labelled `ready-for-agent`, and leaf-like. Missing metadata is tolerated and
 * left to the single-slice S0 backstop, preserving the older pure parser behavior
 * for odd/GraphQL payloads.
 */
export function parseSubIssueAdmission(parsed: unknown): SubIssueAdmission {
  const nodes = subIssueNodes(parsed);
  const seen = new Set<number>();
  const admitted: number[] = [];
  const skipped: SkippedFamilyChild[] = [];
  for (const n of nodes) {
    const num = (n as { number?: unknown })?.number;
    if (typeof num !== "number" || !Number.isFinite(num) || seen.has(num)) continue;
    seen.add(num);
    const reason = skipReason(n);
    if (reason === undefined) {
      admitted.push(num);
    } else {
      skipped.push({ issue: num, reason, message: skipMessage(num, reason) });
    }
  }
  return { admitted, skipped };
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
  moduleDeclarations: {
    readonly family?: SourcedModuleDeclaration;
    readonly children?: ReadonlyMap<number, SourcedModuleDeclaration>;
  } = {},
  admissionSkipped: ReadonlyArray<FamilyAdmissionSkippedChild> = [],
): FamilyEpic {
  const children: ChildSlice[] = childNumbers.map((issue) => ({
    issue,
    blockedBy: (blockedByByChild.get(issue) ?? []).map((b) => b.number),
    ...(moduleDeclarations.children?.get(issue) !== undefined
      ? { moduleDeclaration: moduleDeclarations.children.get(issue)! }
      : {}),
  }));
  return {
    issue: epicIssue,
    children,
    ...(moduleDeclarations.family !== undefined
      ? { moduleDeclaration: moduleDeclarations.family }
      : {}),
    ...(admissionSkipped.length > 0 ? { admissionSkipped } : {}),
  };
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
// verifyCwd inference (#4: verify the project the change actually landed in)
// ════════════════════════════════════════════════════════════════════════════

/**
 * Infer the verify cwd from the family diff (#4). The dogfood verified
 * `orchestrator/` while the change was in `web/` — verifying the WRONG project.
 *
 * `subprojects` is the ordered list of top-level dirs that hold a package.json
 * (a verifiable Node project), RELATIVE to the clone root — e.g.
 * `["orchestrator", "web"]`. A changed file is attributed to a subproject when
 * its path starts with `<subproject>/`. We pick the subproject the MOST changed
 * files land in (ties resolved by the `subprojects` order — "the first containing
 * package.json"); a single-project change therefore trivially wins. This first
 * slice deliberately picks ONE project (the dominant one), not "verify all" (the
 * user's chosen scope — option 1, not option 2).
 *
 * Returns the ABSOLUTE verify cwd (`join(workingRepo, <subproject>)`), or
 * `undefined` when no changed file maps to a known subproject (or the diff is
 * empty) — the caller then falls back to the explicit option / the default.
 * Pure → unit-tested without git.
 */
export function inferVerifyCwd(
  changedFiles: ReadonlyArray<string>,
  subprojects: ReadonlyArray<string>,
  workingRepo: string,
): string | undefined {
  const counts = new Map<string, number>();
  for (const file of changedFiles) {
    for (const sub of subprojects) {
      if (sub.length > 0 && file.startsWith(sub + "/")) {
        counts.set(sub, (counts.get(sub) ?? 0) + 1);
        break; // a file belongs to the first matching subproject only
      }
    }
  }
  if (counts.size === 0) return undefined;
  // Most-changed wins; ties broken by the subprojects order (stable: iterate
  // subprojects, keep the running best only when STRICTLY greater).
  let best: string | undefined;
  let bestCount = 0;
  for (const sub of subprojects) {
    const c = counts.get(sub) ?? 0;
    if (c > bestCount) {
      best = sub;
      bestCount = c;
    }
  }
  return best === undefined ? undefined : join(workingRepo, best);
}

/**
 * Discover the clone's top-level subprojects (#4): every immediate child dir that
 * holds a `package.json` (a verifiable Node project) — e.g. `["orchestrator",
 * "web"]`. The root's own package.json (if any) is intentionally NOT included as a
 * subproject token here: a changed file is attributed to `<subproject>/…`, and a
 * root project would match everything; the verify default already covers the root.
 * Best-effort: an unreadable clone dir yields [] (the resolver then returns
 * undefined and verify falls back to the clone root).
 */
function discoverSubprojects(workingRepo: string): string[] {
  let entries: import("node:fs").Dirent[];
  try {
    entries = readdirSync(workingRepo, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((e) => e.isDirectory() && existsSync(join(workingRepo, e.name, "package.json")))
    .map((e) => e.name)
    .sort();
}

/**
 * The family diff's changed file paths (#4): `git diff --name-only
 * <familyBaseStartHead>...<familyBase>` — the files the merged children added
 * since the base was cut. Run at verify TIME (the children have merged).
 *
 * Does NOT swallow git errors (R1 T3 codex): a clean git run with no diff returns
 * [] (a legitimate "no changes" the caller treats as nothing-to-verify), but a git
 * FAILURE (bad ref / repo error) must THROW so the verify FAILS CLOSED — an
 * inference failure must never be mistaken for "no Node subproject changed" and
 * silently green-light an un-verified merge.
 */
function familyDiffFiles(
  workingRepo: string,
  familyBaseStartHead: string,
  familyBase: string,
  sh: Sh,
): string[] {
  const out = sh("git", [
    "-C",
    workingRepo,
    "diff",
    "--name-only",
    `${familyBaseStartHead}...${familyBase}`,
  ]);
  return out.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
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
  // Host sh with clock only (#884).
  shWithClock(file, args, { stage: `admission:${file}` });

/**
 * Read the epic's children (native sub-issues + each child's blocked_by) from
 * live GitHub and build the {@link FamilyEpic}. Reads native sub-issues through
 * REST (`gh api …/sub_issues`) so family admission can skip non-runnable children
 * before the single-slice S0 gate would abort the whole family run.
 */
export function readFamilyEpic(epicIssue: number, repo: string, sh: Sh): FamilyEpic {
  const admission = readSubIssueAdmission(epicIssue, repo, sh);
  const childNumbers = [...admission.admitted];
  const blockedByByChild = new Map<number, GhBlockedBy[]>();
  for (const child of childNumbers) {
    const depRaw = sh("gh", [
      "api",
      `repos/${repo}/issues/${child}/dependencies/blocked_by`,
    ]);
    blockedByByChild.set(child, parseBlockedBy(JSON.parse(depRaw)));
  }
  const moduleDeclarations = readFamilyModuleDeclarations(
    epicIssue,
    childNumbers,
    repo,
    sh,
  );
  // Family-admission gate (online R1 #1): fail-closed up front if any EXTERNAL blocker
  // is still open — runs on the initial admission AND on every resume refetch, so a
  // re-opened external blocker re-rejects on re-entry.
  assertExternalBlockersCleared(childNumbers, blockedByByChild);
  return buildFamilyEpic(
    epicIssue,
    childNumbers,
    blockedByByChild,
    moduleDeclarations,
    admissionSkippedChildren(admission),
  );
}

function readIssueBody(issue: number, repo: string, sh: Sh): string {
  try {
    const raw = sh("gh", [
      "issue",
      "view",
      String(issue),
      "--repo",
      repo,
      "--json",
      "number,body,author",
    ]);
    const parsedValue: unknown = JSON.parse(raw);
    if (
      parsedValue === null ||
      typeof parsedValue !== "object" ||
      Array.isArray(parsedValue)
    ) {
      throw new Error(`unexpected gh issue payload for #${issue}`);
    }
    const parsed = parsedValue as {
      readonly body?: unknown;
      readonly author?: { readonly login?: unknown };
    };
    const repoOwnerLogin = repo.split("/", 1)[0];
    const repoOwner = repoOwnerLogin?.toLowerCase();
    const authorLogin =
      typeof parsed.author?.login === "string"
        ? parsed.author.login.toLowerCase()
        : undefined;
    const body = typeof parsed.body === "string" ? parsed.body : "";
    if (repoOwner === undefined || authorLogin !== repoOwner) {
      const declaration = body.length > 0 ? parseModuleDeclaration(body) : undefined;
      if (declaration !== undefined) {
        if (isTrustedIssueAssociation(readIssueAuthorAssociation(issue, repo, sh))) {
          return body;
        }
        console.warn(
          `family module declaration ignored for issue #${issue}: author ${
            typeof parsed.author?.login === "string" ? parsed.author.login : "<unknown>"
          } is not trusted owner ${repoOwnerLogin ?? "<unknown>"}`,
        );
      }
      return "";
    }
    return body;
  } catch (err) {
    throw new Error(
      `readIssueBody: failed to read issue #${issue} body from ${repo}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

function readIssueAuthorAssociation(issue: number, repo: string, sh: Sh): string {
  try {
    return sh("gh", [
      "api",
      `repos/${repo}/issues/${issue}`,
      "--jq",
      ".author_association",
    ]).trim();
  } catch (err) {
    throw new Error(
      `failed to read issue #${issue} author association from ${repo}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

function isTrustedIssueAssociation(association: string): boolean {
  const upper = association.trim().toUpperCase();
  return upper === "OWNER";
}

function readFamilyModuleDeclarations(
  epicIssue: number,
  childNumbers: ReadonlyArray<number>,
  repo: string,
  sh: Sh,
): {
  readonly family?: SourcedModuleDeclaration;
  readonly children: ReadonlyMap<number, SourcedModuleDeclaration>;
} {
  const family = sourcedModuleDeclaration(
    parseModuleDeclaration(readIssueBody(epicIssue, repo, sh)),
    "family_issue",
    epicIssue,
  );
  const children = new Map<number, SourcedModuleDeclaration>();
  for (const child of childNumbers) {
    const declaration = sourcedModuleDeclaration(
      parseModuleDeclaration(readIssueBody(child, repo, sh)),
      "child_issue",
      child,
    );
    if (declaration !== undefined) children.set(child, declaration);
  }
  return { ...(family !== undefined ? { family } : {}), children };
}

/**
 * Read native children and normalize a leaf issue to a family-of-one. Existing
 * families whose children are all non-runnable still fail closed; only the
 * absence of native sub-issues selects the degenerate one-child family.
 */
function readSubIssueAdmission(epicIssue: number, repo: string, sh: Sh): SubIssueAdmission {
  const allSubIssueNodes: unknown[] = [];
  for (let page = 1; ; page += 1) {
    const subRaw = sh("gh", [
      "api",
      `repos/${repo}/issues/${epicIssue}/sub_issues?per_page=100&page=${page}`,
    ]);
    const nodes = subIssueNodes(JSON.parse(subRaw));
    allSubIssueNodes.push(...nodes);
    if (nodes.length < 100) break;
  }
  const admission = parseSubIssueAdmission(allSubIssueNodes);
  for (const skipped of admission.skipped) {
    console.warn(skipped.message);
  }
  const childNumbers = [...admission.admitted];
  if (allSubIssueNodes.length === 0) {
    return { admitted: [epicIssue], skipped: [] };
  }
  if (childNumbers.length === 0) {
    throw new Error(
      `family admission rejected: epic #${epicIssue} has no runnable child issues ` +
        `(all native children were skipped) — nothing to orchestrate`,
    );
  }
  return admission;
}

function admissionSkippedChildren(
  admission: SubIssueAdmission,
): ReadonlyArray<FamilyAdmissionSkippedChild> {
  return admission.skipped.map((child) => ({
    issue: child.issue,
    reason: child.reason,
    message: child.message,
  }));
}

// ════════════════════════════════════════════════════════════════════════════
// the production driver
// ════════════════════════════════════════════════════════════════════════════

/** Tunables for {@link runFamilyDriver}. */
export interface FamilyDriverOptions {
  /** Resolved once per run from ORCHESTRATOR_CODEX_FAST (or an explicit option). */
  readonly codexFast?: boolean;
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
  /**
   * EXPLICIT per-run override of the verify cwd (#4) — the absolute dir the family
   * verify (`npm ci` + `npx tsc`/`vitest`) runs in. When set it WINS over the
   * diff-based inference and the default. Leave unset to auto-infer from the family
   * diff (the dominant changed subproject), falling back to the clone root.
   */
  readonly verifyCwd?: string;
  /** Dir holding the versioned single-slice promptFiles (absolute). */
  readonly promptsDir: string;
  /** Dir holding the family-layer promptFiles (the merger conflict prompt). */
  readonly familyPromptsDir: string;
  /** Host dir of souls/*.md to mount live (unconditional rebuild #372). */
  readonly soulsDir: string;
  /** Where the append-only family ledger + escalation records live (outside the worktree). */
  readonly ledgerDir: string;
  /** The profile image (toolchain + skills + model CLIs baked in; souls mounted #372). */
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
  /**
   * Override construction of the production single-slice backend. The driver
   * passes the complete resolved options so tests can exercise the production
   * assembly without starting a container.
   */
  readonly realBackendFactory?: (options: RealBackendOptions) => RealBackend;
  /**
   * Override construction of the production family backend. The driver passes
   * the complete resolved options so tests can exercise the production assembly
   * without starting a container.
   */
  readonly realFamilyBackendFactory?: (
    options: RealFamilyBackendOptions,
  ) => FamilyBackend & { reconcileGit(): ReconcileGit };
}

/** Resolve the run-level Codex fast switch once, honoring an explicit option. */
export function resolveCodexFast(options: Pick<FamilyDriverOptions, "codexFast">): boolean {
  return options.codexFast ?? process.env.ORCHESTRATOR_CODEX_FAST === "1";
}

/** Stable run-level attribution line for post-run pool accounting. */
export function codexFastRunLog(codexFast: boolean): string {
  return `[orchestrator] run fast=${codexFast ? "on" : "off"}`;
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
  const codexFast = resolveCodexFast(options);
  console.log(codexFastRunLog(codexFast));

  // 1. Read the already-cut children from live GitHub (the explicit dependency
  //    edges a `to-issues` step wrote — decision 1, no LLM inference).
  logDriverStage("admission", `epic #${options.epicIssue}`);
  const epic = readFamilyEpic(options.epicIssue, options.repo, sh);

  // 2. The single-slice RealBackend: keyed on the PARENT epic so all children
  //    share ONE family clone (ADR 0024). Constructing it CLONES the source (pure
  //    git, no container) — that clone is the family clone every git op anchors on.
  //    `familyBase` makes a child cut from the LOCAL family base (decision 7).
  const realBackendOptions: RealBackendOptions = {
    codexFast,
    sourceRepo: options.sourceRepo,
    remote: options.remote,
    runKey: options.epicIssue,
    repo: options.repo,
    imageName: options.imageName,
    skillsMount: options.skillsMount,
    promptsDir: options.promptsDir,
    soulsDir: options.soulsDir,
    home: options.home,
    familyBase: options.familyBase,
  };
  const realSingleSlice =
    options.realBackendFactory?.(realBackendOptions) ?? new RealBackend(realBackendOptions);
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
  const familyBackendOptions: RealFamilyBackendOptions = {
    codexFast,
    workingRepo,
    // #4: verify the project the change ACTUALLY landed in, not a hardcoded
    // `orchestrator/`. Precedence: an explicit per-run `verifyCwd` wins;
    // otherwise infer LAZILY at verify time from the family diff (the
    // dominant changed subproject), falling back to the clone root. The
    // dogfood verified orchestrator/ while the change was in web/ — verifying
    // the WRONG project. (The inference is lazy because at construction the
    // family base is freshly cut → an empty diff; the change exists only once
    // children have merged.)
    verifyCwd: options.verifyCwd,
    // #746: clonefile node_modules from the source monorepo when lockfiles match.
    depsTemplateRoot: options.sourceRepo,
    resolveVerifyCwd: () =>
      inferVerifyCwd(
        familyDiffFiles(workingRepo, familyBaseStartHead, options.familyBase, sh),
        discoverSubprojects(workingRepo),
        workingRepo,
      ),
    familyBase: options.familyBase,
    ledgerDir: options.ledgerDir,
    repo: options.repo,
    base: options.base,
    promptsDir: options.familyPromptsDir,
    soulsDir: options.soulsDir,
    imageName: options.imageName,
    familyBaseStartHead,
    home: options.home,
  };
  const familyBackend =
    options.familyBackendFactory?.(workingRepo, familyBaseStartHead) ??
    options.realFamilyBackendFactory?.(familyBackendOptions) ??
    new RealFamilyBackend(familyBackendOptions);

  // 6. Assemble the run input + the resume seams, and run the spine.
  // reconcile stage is logged inside runFamily immediately before the real
  // reconcile work (not here) so a hang after smoke-k is still attributable.
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
    refetchEpic: async () => {
      logDriverStage("admission", `refetch epic #${options.epicIssue}`);
      return readFamilyEpic(options.epicIssue, options.repo, sh);
    },
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
 * Single source of truth for the default worker image tag (#372).
 * Both build.sh (via IMAGE_TAG env) and dispatch (via imageName) must use the
 * same resolved value so unconditional rebuild + dispatch always hit the just-built tag.
 */
export const DEFAULT_IMAGE_TAG = "ming-orchestrator-coder:latest";

/**
 * Resolve one tag for end-to-end: launcher reads IMAGE_TAG (or default) once,
 * passes to build (explicit env) and to driver.imageName.
 */
export function resolveImageTag(envTag: string | undefined): string {
  return envTag && envTag.length > 0 ? envTag : DEFAULT_IMAGE_TAG;
}

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
