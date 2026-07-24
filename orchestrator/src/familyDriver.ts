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
 *      verify-cmr hook) runs the family verify + integrated cmr, then continues
 *      through online review, automatic merge, and post-merge cleanup.
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

import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
  statSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import {
  admitCoderRec,
  admitPlannedRouteSmoke,
  admitRouteFromEnv,
  admitRouteSmoke,
  admissionRouteFailureDiagnosis,
  isGithubAuthFailure,
  readMetadataWithRetry,
} from "./admissionPreflight.js";
import {
  admitBaselineHealth,
  baselineHealthRepairHint,
  NOOP_BASELINE_FIX_ATTEMPT,
  runBaselineFullTestsInWorkerContainer,
  type BaselineFixAttempt,
  type BaselineFullTestResult,
  type BaselineFullTestRunner,
} from "./baselineHealthGate.js";
import { shWithClock } from "./externalCall.js";
import { gitExitStatus, isFileNotFound } from "./fsErrors.js";
import type { ResolvedModelRoute } from "./modelRoutes.js";
import {
  RealBackend,
  type RealBackendOptions,
  readBlockedByDualChannel,
  type GhBlockedBy,
  clonePathFor,
  repoSlug,
} from "./realBackend.js";
import {
  graphqlSubIssuesArgs,
  graphqlSubIssuesToNodeShape,
  logMetadataChannel,
  readGithubMetadataDualChannel,
  restSubIssuesArgs,
  type MetadataChannel,
} from "./githubMetadataChannel.js";
import {
  FAMILY_LEDGER_FILENAME,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "./family/realFamilyBackend.js";
import {
  familyEscalationState,
  isCompleteFamilyEscalation,
  isValidPostMergeCleanup,
  mergedSet,
  parseFamilyLedgerJsonl,
  recordBaselineHealthFailed,
} from "./family/ledger.js";
import { runFamily } from "./family/runner.js";
import { replayPriorFamilyEscalation } from "./family/terminalFinalizer.js";
import {
  parseModuleDeclaration,
  sourcedModuleDeclaration,
  type SourcedModuleDeclaration,
} from "./family/moduleDeclaration.js";
import { shouldReclaimFamilyHost } from "./hostReclaim.js";
import { logDriverStage } from "./stageLog.js";
import {
  configureProgressBroadcast,
  emitExitProgress,
} from "./progressBroadcast.js";
import {
  decisionGateParkStopSummary,
  infraFailureStopSummary,
} from "./stopSummary.js";
import type { Backend } from "./types.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyAdmissionSkippedChild,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyRunInput,
  FamilyRunResult,
  ReconcileGit,
} from "./family/types.js";
import { failedFamilyResult } from "./family/types.js";

// ════════════════════════════════════════════════════════════════════════════
// PURE epic-assembly logic (unit-tested without live GitHub)
// ════════════════════════════════════════════════════════════════════════════

/** One child excluded from this family run before wave scheduling. */
export interface SkippedFamilyChild {
  readonly issue: number;
  readonly reason:
    | "closed"
    | "not_ready_for_agent"
    | "parent_issue"
    | "open_external_blocker";
  readonly message: string;
}

export interface SubIssueAdmission {
  readonly admitted: ReadonlyArray<number>;
  readonly skipped: ReadonlyArray<SkippedFamilyChild>;
}

/**
 * Fail-closed sub-issues body decoder (#934 ID-003 / CR S-2).
 * REST native list OR GraphQL `{subIssues:{nodes:[]}}`. Schema garbage throws —
 * never soft-empty into family-of-one / vacuous parent-close.
 * Shared by family admission and post-merge cleanup (single helper).
 */
export function decodeSubIssueNodes(parsed: unknown): unknown[] {
  // REST native sub-issues endpoint: `gh api repos/O/R/issues/<epic>/sub_issues`.
  if (Array.isArray(parsed)) return parsed;
  // Older/newer gh GraphQL shape retained for pure parser compatibility.
  if (parsed !== null && typeof parsed === "object") {
    const sub = (parsed as { subIssues?: unknown }).subIssues;
    if (sub !== null && typeof sub === "object" && !Array.isArray(sub)) {
      const nodes = (sub as { nodes?: unknown }).nodes;
      if (Array.isArray(nodes)) return nodes;
    }
  }
  throw new Error(
    `sub_issues schema error: expected array or {subIssues:{nodes:[]}}, got ${
      parsed === null ? "null" : Array.isArray(parsed) ? "array" : typeof parsed
    }`,
  );
}

/**
 * Fail-closed single sub-issue entry decoder (#934 R6 N2 / ID-003).
 * Shared by family admission and post-merge cleanup — one object+number court.
 * `state` is optional here: post-merge cleanup requires it for close decisions;
 * family admission uses {@link skipReason} soft-state (CLOSED label path).
 */
export function decodeSubIssueEntry(
  node: unknown,
  index: number,
): { readonly number: number; readonly state?: string } {
  if (node === null || typeof node !== "object" || Array.isArray(node)) {
    throw new Error(
      `sub_issues entry schema error: sub_issue[${index}]: expected object entry, got ${
        node === null ? "null" : Array.isArray(node) ? "array" : typeof node
      }`,
    );
  }
  const number = (node as { number?: unknown }).number;
  if (typeof number !== "number" || !Number.isFinite(number)) {
    throw new Error(
      `sub_issues entry schema error: sub_issue[${index}]: missing or non-finite number (got ${
        number === undefined
          ? "undefined"
          : typeof number === "number"
            ? String(number)
            : typeof number
      })`,
    );
  }
  const rawState = (node as { state?: unknown }).state;
  if (typeof rawState === "string" && rawState.trim().length > 0) {
    return { number, state: rawState };
  }
  return { number };
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
    case "open_external_blocker":
      return `family admission skipped child #${issue}: open external blocker(s)`;
  }
}

/**
 * Split native sub-issues into runnable children vs visible skips.
 *
 * The production reader uses GitHub's REST native sub-issues endpoint because it
 * carries the metadata needed for the family admission rule: state, labels, and
 * whether the child is itself a parent. A child is runnable when it is open,
 * labelled `ready-for-agent`, and leaf-like. Entry-level schema garbage
 * (missing/non-finite `number`, non-object nodes) fails closed as deterministic
 * metadata error — never soft-skips into all-filtered success (#934 ID-003).
 * Optional label/parent fields remain soft for S0 backstop compatibility.
 */
export function parseSubIssueAdmission(parsed: unknown): SubIssueAdmission {
  const nodes = decodeSubIssueNodes(parsed);
  const seen = new Set<number>();
  const admitted: number[] = [];
  const skipped: SkippedFamilyChild[] = [];
  const entryErrors: string[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    let num: number;
    try {
      num = decodeSubIssueEntry(n, i).number;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      entryErrors.push(
        msg.replace(/^sub_issues entry schema error:\s*/, ""),
      );
      continue;
    }
    if (seen.has(num)) continue;
    seen.add(num);
    const reason = skipReason(n);
    if (reason === undefined) {
      admitted.push(num);
    } else {
      skipped.push({ issue: num, reason, message: skipMessage(num, reason) });
    }
  }
  if (entryErrors.length > 0) {
    throw new Error(
      `sub_issues entry schema error: ${entryErrors.join("; ")}`,
    );
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

/**
 * #934 ID-002 / root epic OPEN blocker: park the whole family before
 * clone/smoke/worksite (ID-001 wait-for-external). Distinct from ordinary
 * per-child external blockers, which only produce a visible filter.
 *
 * Optional `diagnostics` carries sibling metadata-read failures collected
 * before the park decision (ID-002/003: full read + aggregate, no first-error
 * return). They do not change the park edge — only complete the inventory.
 */
export class FamilyRootBlockerError extends Error {
  constructor(
    readonly openBlockers: ReadonlyArray<number>,
    readonly diagnostics: ReadonlyArray<string> = [],
  ) {
    const base =
      `family admission parked: root epic has open blocker(s) ` +
      openBlockers.map((n) => `#${n}`).join(", ");
    super(
      diagnostics.length > 0
        ? `${base}; metadata diagnostics (${diagnostics.length}): ${diagnostics.join("; ")}`
        : base,
    );
    this.name = "FamilyRootBlockerError";
  }
}

/**
 * Family-admission external-blocker filter (#934 ID-002 supersedes the older
 * whole-family reject). An EXTERNAL `blocked_by` is never merged into the family
 * ledger, so the wave scheduler cannot clear it. Ordinary external blockers only
 * produce a **visible per-child filter** — runnable siblings continue. Closed
 * (satisfied) external blockers drop out; the scheduler gates only on intra-family
 * blockers. A child's S0 remains a mid-run backstop if an external blocker re-opens.
 */
export function filterExternalBlockedChildren(
  childNumbers: ReadonlyArray<number>,
  blockedByByChild: ReadonlyMap<number, ReadonlyArray<GhBlockedBy>>,
): {
  readonly runnable: ReadonlyArray<number>;
  readonly skipped: ReadonlyArray<SkippedFamilyChild>;
  readonly openBlockers: ReadonlyArray<OpenExternalBlocker>;
} {
  const family = new Set(childNumbers);
  const runnable: number[] = [];
  const skipped: SkippedFamilyChild[] = [];
  const openBlockers: OpenExternalBlocker[] = [];
  for (const child of childNumbers) {
    const childOpen: number[] = [];
    for (const b of blockedByByChild.get(child) ?? []) {
      if (!family.has(b.number) && b.state !== "closed") {
        openBlockers.push({ child, blocker: b.number });
        childOpen.push(b.number);
      }
    }
    if (childOpen.length > 0) {
      skipped.push({
        issue: child,
        reason: "open_external_blocker",
        message:
          `family admission skipped child #${child}: open external blocker(s) ` +
          childOpen.map((n) => `#${n}`).join(", "),
      });
    } else {
      runnable.push(child);
    }
  }
  return { runnable, skipped, openBlockers };
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
 * holds a package.json *file* (a verifiable Node project) — e.g. `["orchestrator",
 * "web"]`. The root's own package.json (if any) is intentionally NOT included as a
 * subproject token here: a changed file is attributed to `<subproject>/…`, and a
 * root project would match everything; the verify default already covers the root.
 *
 * #934 ID-011 / #939: operational readdir / package.json probe errors fail closed
 * (never soft-skip into "no Node subproject"). Only precise absence (ENOENT) of
 * package.json omits a directory. package.json must be a file (`isFile`).
 */
export function discoverSubprojects(workingRepo: string): string[] {
  let entries: import("node:fs").Dirent[];
  try {
    entries = readdirSync(workingRepo, { withFileTypes: true });
  } catch (err) {
    const d = err instanceof Error ? err.message : String(err);
    // #934 CR: one canonical reason token (no dual-era slash-joined phrases).
    throw new Error(
      `family verify: failed to readdir subprojects at "${workingRepo}": ${d}`,
    );
  }
  const found: string[] = [];
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const pkg = join(workingRepo, e.name, "package.json");
    try {
      if (statSync(pkg).isFile()) found.push(e.name);
    } catch (err) {
      if (isFileNotFound(err)) continue;
      const d = err instanceof Error ? err.message : String(err);
      throw new Error(
        `family verify: package.json probe failed at "${pkg}": ${d}`,
      );
    }
  }
  return found.sort();
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
export function readFamilyEpic(
  epicIssue: number,
  repo: string,
  sh: Sh,
  issueBodies: Map<number, string> = new Map(),
  recordChannel: (resource: string, issue: number, channel: MetadataChannel) => void =
    logMetadataChannel,
): FamilyEpic {
  // #1063: `sh` is the RAW host seam. The dual-channel reads (sub_issues /
  // blocked_by) own their REST retry budget internally and keep GraphQL to a
  // single fallback round; the non-dual body reads keep the #936 retry via
  // this local wrapper.
  const metadataSh: Sh = (file, args) => readMetadataWithRetry(() => sh(file, args));
  // #934 ID-002/003: live metadata errors aggregate — sub-issues throw must not
  // abort before independently readable root blocked_by (and reachable child deps).
  const errors: string[] = [];
  let admission: SubIssueAdmission = { admitted: [], skipped: [] };
  try {
    admission = readSubIssueAdmission(epicIssue, repo, sh, (c) =>
      recordChannel("sub_issues", epicIssue, c),
    );
  } catch (err) {
    errors.push(
      `sub_issues #${epicIssue}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  const childNumbers = [...admission.admitted];
  const blockedByByChild = new Map<number, GhBlockedBy[]>();

  // #934 ID-002: read ROOT epic blocked_by, but do NOT first-error return on
  // OPEN blockers — finish enumerable child metadata first, then park with
  // the complete inventory (root blocker fact + sibling diagnostics).
  let openRootBlockers: ReadonlyArray<number> | undefined;
  try {
    const rootBlockedBy = readBlockedByDualChannel(sh, repo, epicIssue, (c) =>
      recordChannel("blocked_by", epicIssue, c),
    );
    const openRoot = rootBlockedBy
      .filter((b) => b.state !== "closed")
      .map((b) => b.number);
    if (openRoot.length > 0) {
      openRootBlockers = openRoot;
    }
  } catch (err) {
    errors.push(
      `root #${epicIssue} blocked_by: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  for (const child of childNumbers) {
    try {
      blockedByByChild.set(
        child,
        readBlockedByDualChannel(sh, repo, child, (c) =>
          recordChannel("blocked_by", child, c),
        ),
      );
    } catch (err) {
      errors.push(`child #${child} blocked_by: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  // #934 ID-002: ordinary external blockers → visible per-child filter only.
  const externalFilter = filterExternalBlockedChildren(childNumbers, blockedByByChild);
  for (const skipped of externalFilter.skipped) {
    console.warn(skipped.message);
  }
  const runnableChildren = [...externalFilter.runnable];

  let moduleDeclarations: ReturnType<typeof readFamilyModuleDeclarations> = {
    children: new Map(),
  };
  try {
    moduleDeclarations = readFamilyModuleDeclarations(
      epicIssue,
      runnableChildren,
      repo,
      metadataSh,
      issueBodies,
    );
  } catch (err) {
    errors.push(`issue bodies: ${err instanceof Error ? err.message : String(err)}`);
  }
  // OPEN root blocker parks (ID-001) after the full metadata pass; sibling
  // read failures ride along as diagnostics, not a first-error short-circuit.
  if (openRootBlockers !== undefined) {
    throw new FamilyRootBlockerError(openRootBlockers, errors);
  }
  if (errors.length > 0) {
    throw new Error(`issue metadata unavailable (${errors.length} errors): ${errors.join("; ")}`);
  }
  return buildFamilyEpic(
    epicIssue,
    runnableChildren,
    blockedByByChild,
    moduleDeclarations,
    [...admissionSkippedChildren(admission), ...externalFilter.skipped],
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

function readIssueBodyCached(
  issue: number,
  repo: string,
  sh: Sh,
  issueBodies: Map<number, string>,
): string {
  const cached = issueBodies.get(issue);
  if (cached !== undefined) return cached;
  const body = readIssueBody(issue, repo, sh);
  issueBodies.set(issue, body);
  return body;
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
  issueBodies: Map<number, string> = new Map(),
): {
  readonly family?: SourcedModuleDeclaration;
  readonly children: ReadonlyMap<number, SourcedModuleDeclaration>;
} {
  const errors: string[] = [];
  let family: SourcedModuleDeclaration | undefined;
  try {
    family = sourcedModuleDeclaration(
      parseModuleDeclaration(readIssueBodyCached(epicIssue, repo, sh, issueBodies)),
      "family_issue",
      epicIssue,
    );
  } catch (err) {
    errors.push(`issue #${epicIssue}: ${err instanceof Error ? err.message : String(err)}`);
  }
  const children = new Map<number, SourcedModuleDeclaration>();
  for (const child of childNumbers) {
    try {
      const declaration = sourcedModuleDeclaration(
        parseModuleDeclaration(readIssueBodyCached(child, repo, sh, issueBodies)),
        "child_issue",
        child,
      );
      if (declaration !== undefined) children.set(child, declaration);
    } catch (err) {
      errors.push(`issue #${child}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  if (errors.length > 0) {
    throw new Error(`issue body aggregation failed: ${errors.join("; ")}`);
  }
  return { ...(family !== undefined ? { family } : {}), children };
}

/**
 * Read native children and normalize a leaf issue to a family-of-one. Existing
 * families whose children are all non-runnable still fail closed; only the
 * absence of native sub-issues selects the degenerate one-child family.
 */
function readSubIssueAdmission(
  epicIssue: number,
  repo: string,
  sh: Sh,
  onChannel: (channel: MetadataChannel) => void = (c) =>
    logMetadataChannel("sub_issues", epicIssue, c),
): SubIssueAdmission {
  // #1063: REST-primary (paginated, each page owns the retry budget) with a
  // single GraphQL-round fallback; both channels normalize through the one
  // `decodeSubIssueNodes` shape source before `parseSubIssueAdmission`.
  const allSubIssueNodes = readGithubMetadataDualChannel<unknown[]>({
    rest: () => {
      const nodes: unknown[] = [];
      for (let page = 1; ; page += 1) {
        const subRaw = readMetadataWithRetry(() =>
          sh("gh", restSubIssuesArgs(repo, epicIssue, page)),
        );
        const pageNodes = decodeSubIssueNodes(JSON.parse(subRaw));
        nodes.push(...pageNodes);
        if (pageNodes.length < 100) break;
      }
      return nodes;
    },
    graphql: () =>
      decodeSubIssueNodes(graphqlSubIssuesToNodeShape(sh("gh", graphqlSubIssuesArgs(repo, epicIssue)))),
    decode: (nodes) => nodes as unknown[],
    onChannel,
  });
  const admission = parseSubIssueAdmission(allSubIssueNodes);
  for (const skipped of admission.skipped) {
    console.warn(skipped.message);
  }
  if (allSubIssueNodes.length === 0) {
    return { admitted: [epicIssue], skipped: [] };
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
  /** A parent epic or leaf issue number — leaf issues become a family-of-one. */
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
  readonly realBackendFactory?: (
    options: RealBackendOptions,
  ) => Backend & { workingRepoPath(): string };
  /**
   * Override construction of the production family backend. The driver passes
   * the complete resolved options so tests can exercise the production assembly
   * without starting a container.
   */
  readonly realFamilyBackendFactory?: (
    options: RealFamilyBackendOptions,
  ) => FamilyBackend & { reconcileGit(): ReconcileGit };
  /**
   * #1006 — injectable baseline full-suite runner (unit/e2e). Production leaves
   * this unset → worker-image container full gate. Injected backends without a
   * runner get a green no-op so zero-container fixtures do not wall-clock docker.
   */
  readonly baselineFullTestRunner?: BaselineFullTestRunner;
  /**
   * #1006 — one-round baseline fix (owner shape: red → fix once → recheck).
   * Production always wires a one-shot hook: inject a real attempt, or leave
   * unset to use {@link NOOP_BASELINE_FIX_ATTEMPT} (attempted:false → fail-closed
   * 报错 path; never invents green). Auto LLM fixer is out of this slice —
   * the seam is present so a later slice can inject without rewiring admission.
   */
  readonly baselineFixAttempt?: BaselineFixAttempt;
}

/**
 * Family Scene Recovery (#934 ID-005 / #936): read resident durable family
 * truth before admission/network/worksite. Typed outcomes:
 *   - fresh: neither ledger nor worksite residue → continue productive path
 *   - resident: parseable ledger + worksite, OR terminal-replayable ledger alone
 *   - corrupted: partial residue, nonterminal ledger-without-worksite, or
 *     unreadable/unparseable ledger (preserve, fail loud)
 */
export type FamilySceneDiscovery =
  | { readonly kind: "fresh" }
  | { readonly kind: "resident"; readonly ledger: ReadonlyArray<FamilyLedgerEntry> }
  | { readonly kind: "corrupted"; readonly reason: string };

export interface FamilySceneDiscoveryOptions {
  /** Deterministic family clone path (ADR 0024); presence of `.git` is worksite residue. */
  readonly clonePath?: string;
}

/**
 * Whether a parseable family ledger can terminal-replay without worksite
 * residue (completed cleanup, or unresolved park/fail escalation). Nonterminal
 * mid-run / answered-decision / incomplete-escalation ledgers need worksite
 * (or are corrupted) and must not soft-resume as terminal without worksite.
 */
function isFamilyLedgerTerminalWithoutWorksite(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): boolean {
  if (shouldReclaimFamilyHost(ledger)) return true;
  const prior = familyEscalationState(ledger);
  if (prior === undefined) return false;
  // Incomplete escalated rows are durable damage, not terminal park/fail truth.
  if (!isCompleteFamilyEscalation(prior.escalation)) return false;
  // Answered decision reopens productive work — not terminal without worksite.
  if (prior.escalation.escalationKind === "decision" && prior.answer !== undefined) {
    return false;
  }
  return true;
}

/**
 * Fail-closed path probe (#934 ID-005 / ID-011 pattern): precise ENOENT = absent;
 * any other FS operational error is damage, never soft-absence.
 */
function probePathPresent(
  path: string,
): { readonly present: true } | { readonly present: false } | { readonly error: string } {
  try {
    statSync(path);
    return { present: true };
  } catch (err) {
    if (isFileNotFound(err)) return { present: false };
    return {
      error: `${path}: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/**
 * Discover resident family durable truth — zero GitHub, zero smoke.
 * Typed fresh only when BOTH ledger and worksite residue are absent (ID-005).
 * Worksite residue = family-base start-head file and/or resident clone `.git`.
 * Ledger without worksite is only legal when terminal-replayable; nonterminal
 * ledger-without-worksite is corrupted (must not recreate worksite over lineage).
 */
export function discoverFamilyResidentScene(
  ledgerDir: string,
  opts: FamilySceneDiscoveryOptions = {},
): FamilySceneDiscovery {
  const ledgerPath = join(ledgerDir, FAMILY_LEDGER_FILENAME);
  const startHeadPath = join(ledgerDir, FAMILY_BASE_START_HEAD_FILENAME);
  const ledgerProbe = probePathPresent(ledgerPath);
  if ("error" in ledgerProbe) {
    return {
      kind: "corrupted",
      reason: `resident family ledger path probe failed (operational FS error, not absence): ${ledgerProbe.error}`,
    };
  }
  const startHeadProbe = probePathPresent(startHeadPath);
  if ("error" in startHeadProbe) {
    return {
      kind: "corrupted",
      reason: `resident family start-head path probe failed (operational FS error, not absence): ${startHeadProbe.error}`,
    };
  }
  let hasClone = false;
  if (opts.clonePath !== undefined) {
    const cloneGitProbe = probePathPresent(join(opts.clonePath, ".git"));
    if ("error" in cloneGitProbe) {
      return {
        kind: "corrupted",
        reason: `resident family clone path probe failed (operational FS error, not absence): ${cloneGitProbe.error}`,
      };
    }
    hasClone = cloneGitProbe.present;
  }
  const hasLedger = ledgerProbe.present;
  const hasStartHead = startHeadProbe.present;
  const hasWorksiteResidue = hasStartHead || hasClone;

  if (!hasLedger && !hasWorksiteResidue) return { kind: "fresh" };
  if (!hasLedger && hasWorksiteResidue) {
    const cloneHint =
      opts.clonePath !== undefined ? `, clone=${opts.clonePath}` : "";
    return {
      kind: "corrupted",
      reason:
        `resident family worksite exists without readable ledger at ${ledgerDir}` +
        `${cloneHint}; refusing to treat partial residue as fresh (#936 / #934 ID-005)`,
    };
  }

  let raw: string;
  try {
    raw = readFileSync(ledgerPath, "utf8");
  } catch (err) {
    return {
      kind: "corrupted",
      reason: `resident family ledger unreadable at ${ledgerPath}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }
  let ledger: FamilyLedgerEntry[];
  try {
    // #934 S-3: per-line shape gate (not bare JSON.parse cast).
    ledger = parseFamilyLedgerJsonl(raw);
  } catch (err) {
    return {
      kind: "corrupted",
      reason: `resident family ledger corrupt at ${ledgerPath}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }

  // Incomplete escalated rows are never terminal durable truth (#934 ID-005).
  const priorEscalation = familyEscalationState(ledger);
  if (
    priorEscalation !== undefined &&
    !isCompleteFamilyEscalation(priorEscalation.escalation)
  ) {
    return {
      kind: "corrupted",
      reason:
        `resident family ledger has incomplete status:escalated row ` +
        `(missing event:escalated and/or decision|failure kind) at ${ledgerDir}; ` +
        `refusing terminal replay of damaged park state (#934 ID-005)`,
    };
  }

  if (!hasWorksiteResidue && !isFamilyLedgerTerminalWithoutWorksite(ledger)) {
    return {
      kind: "corrupted",
      reason:
        `resident family ledger exists without worksite residue at ${ledgerDir}; ` +
        `nonterminal ledger-without-worksite cannot safely resume ` +
        `(#936 / #934 ID-005)`,
    };
  }
  return { kind: "resident", ledger };
}

/**
 * Rebuild production-admission skip audit from durable ledger rows (#934 ID-005 /
 * online CR C1). Terminal replay must not drop `admission_skipped` inventory that
 * the original run exposed on `FamilyRunResult.admissionSkipped`.
 */
export function admissionSkippedFromLedger(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlyArray<FamilyAdmissionSkippedChild> {
  const out: FamilyAdmissionSkippedChild[] = [];
  const seen = new Set<number>();
  for (const entry of ledger) {
    if (entry.status !== "admission_skipped" || entry.event !== "admission_skipped") {
      continue;
    }
    if (typeof entry.childIssue !== "number" || !Number.isFinite(entry.childIssue)) {
      continue;
    }
    if (seen.has(entry.childIssue)) continue;
    seen.add(entry.childIssue);
    const reason =
      typeof entry.reason === "string" && entry.reason.trim().length > 0
        ? entry.reason
        : "admission_skipped";
    const message =
      typeof entry.message === "string" && entry.message.trim().length > 0
        ? entry.message
        : reason;
    out.push({ issue: entry.childIssue, reason, message });
  }
  return out;
}

/** Current-schema terminal replay (ID-005); undefined when non-terminal. */
function replayCompletedCleanup(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  familyBase: string,
): FamilyRunResult {
  let familyHead: string | undefined;
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (isValidPostMergeCleanup(entry) && entry.cleanupOutput.terminal && entry.cleanupOutput.ok) {
      familyHead = entry.familyHeadAfter;
      break;
    }
  }
  const admissionSkipped = admissionSkippedFromLedger(ledger);
  for (const skipped of admissionSkipped) {
    console.warn(
      `family child #${skipped.issue} skipped: admission_skipped`,
    );
  }
  const children = [
    ...[...mergedSet(ledger)].map((issue) => ({
      issue,
      status: "already_done" as const,
    })),
    ...admissionSkipped.map((s) => ({
      issue: s.issue,
      status: "skipped" as const,
      reason: "admission_skipped" as const,
    })),
  ];
  const headsMeta =
    familyHead !== undefined
      ? {
          heads: {
            actualFamilyHead: familyHead,
            sources: {
              actualFamilyHead: "post_merge_cleanup ledger row",
            },
          },
        }
      : {};
  const metadata = {
    ...headsMeta,
    ...(admissionSkipped.length > 0 ? { admissionSkipped } : {}),
  };
  return {
    status: "completed",
    familyBase,
    ...(familyHead !== undefined ? { familyHead } : {}),
    stopSummary: {
      reason: "already_done",
      summary:
        "family durable terminal replay: post_merge_cleanup already completed",
      ...(Object.keys(metadata).length > 0 ? { metadata } : {}),
    },
    children,
    ...(admissionSkipped.length > 0 ? { admissionSkipped } : {}),
  };
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
 * spine through the final barrier, including online review, automatic merge to
 * main, and post-merge cleanup.
 *
 * @returns the {@link FamilyRunResult} — the per-child outcomes + the merged
 *   family base HEAD + public status completed|parked|failed (#942 / ID-001).
 *   Stage diagnostics stay on stopSummary / cause, never as public status.
 */
export async function runFamilyDriver(
  options: FamilyDriverOptions,
): Promise<FamilyRunResult> {
  const sh = options.sh ?? defaultSh;
  // #1063: raw `sh` feeds readFamilyEpic (its dual-channel reads own retry);
  // metadataSh keeps the #936 retry for the non-dual body reads below.
  const metadataSh: Sh = (file, args) =>
    readMetadataWithRetry(() => sh(file, args));
  const codexFast = resolveCodexFast(options);
  console.log(codexFastRunLog(codexFast));

  // #1007: bind progress feed for the whole family driver (stage + status).
  configureProgressBroadcast({
    ledgerDir: options.ledgerDir,
    epic: options.epicIssue,
  });

  // #936 / #934 ID-005: Scene Recovery FIRST — resident family durable truth
  // before route admission, GitHub metadata, smoke, or clone/worksite. Terminal
  // completed/failed replay with zero external calls; corrupted residue fails
  // loud and preserves the scene. Typed fresh only when ledger AND worksite
  // residue (clone / start-head) are both absent.
  logDriverStage("recovery", `family scene epic #${options.epicIssue}`, {
    epic: options.epicIssue,
  });
  const home = options.home ?? homedir();
  const familyClonePath = clonePathFor(
    home,
    repoSlug(options.sourceRepo, options.remote),
    options.epicIssue,
  );
  const familyScene = discoverFamilyResidentScene(options.ledgerDir, {
    clonePath: familyClonePath,
  });
  if (familyScene.kind === "corrupted") {
    const stopSummary = infraFailureStopSummary({
      summary: familyScene.reason,
      repairHint:
        "repair or clear the resident family ledger/worksite before re-entry",
    });
    // #1007: family driver early fail after configureProgressBroadcast.
    emitExitProgress({
      epic: options.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return failedFamilyResult({
      cause: "resume_state_invalid",
      familyBase: options.familyBase,
      escalation: {
        reason: "resume state invalid",
        diagnosis: familyScene.reason,
      },
      stopSummary,
      children: [],
    });
  }
  if (familyScene.kind === "resident") {
    const prior = familyEscalationState(familyScene.ledger);
    const terminal = shouldReclaimFamilyHost(familyScene.ledger)
      ? replayCompletedCleanup(familyScene.ledger, options.familyBase)
      : prior !== undefined &&
          isCompleteFamilyEscalation(prior.escalation) &&
          (prior.escalation.escalationKind !== "decision" ||
            prior.answer === undefined)
        ? await replayPriorFamilyEscalation({
            epicIssue: options.epicIssue,
            familyBase: options.familyBase,
            escalation: prior.escalation,
          })
        : undefined;
    if (terminal !== undefined) {
      // #1007: durable terminal replay must self-describe this invocation's feed.
      emitExitProgress({
        epic: options.epicIssue,
        status: terminal.status,
        stopReason: terminal.stopSummary?.reason,
        gateSummary: terminal.stopSummary?.summary,
      });
      return terminal;
    }
  }

  // #936 / #934 ID-002: route Admission/Preflight BEFORE any GitHub metadata
  // read or family clone/worksite creation. Tight/unknown route fails closed
  // with zero network and zero worksite side effects.
  logDriverStage("admission", `route preflight epic #${options.epicIssue}`);
  const admitted = admitRouteFromEnv();
  if (admitted.kind === "stop") {
    const diagnosis = admissionRouteFailureDiagnosis(admitted.escalation.diagnosis);
    const stopSummary = infraFailureStopSummary({
      summary: `${admitted.escalation.reason}: ${diagnosis}`,
      repairHint:
        "repair ORCHESTRATOR_ROUTE preset or issue Coder-Rec staffing before rerun",
    });
    // #1007: route preflight fail — dual-write terminal.
    emitExitProgress({
      epic: options.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return failedFamilyResult({
      cause: "route_config_invalid",
      familyBase: options.familyBase,
      escalation: {
        reason: admitted.escalation.reason,
        diagnosis,
      },
      stopSummary,
      children: [],
    });
  }

  // 1. Read the already-cut children from live GitHub (the explicit dependency
  //    edges a `to-issues` step wrote — decision 1, no LLM inference). Live
  //    metadata is part of Admission after route preflight (ID-002/003).
  logDriverStage("admission", `epic #${options.epicIssue}`);
  let epic: FamilyEpic;
  const issueBodies = new Map<number, string>();
  try {
    epic = readFamilyEpic(options.epicIssue, options.repo, sh, issueBodies);
  } catch (err) {
    if (err instanceof FamilyRootBlockerError) {
      const diagnosis =
        `root epic #${options.epicIssue} is blocked by open upstream issue(s): ` +
        err.openBlockers.map((n) => `#${n}`).join(", ");
      const stopSummary = decisionGateParkStopSummary({
        summary: err.message,
        repairHint:
          "close or unblock the root epic blocked_by dependencies, then re-feed",
      });
      // #1007: root epic blocked_by park — dual-write park+terminal (notify).
      emitExitProgress({
        epic: options.epicIssue,
        status: "parked",
        stopReason: stopSummary.reason,
        gateSummary: stopSummary.summary,
      });
      return {
        status: "parked",
        familyBase: options.familyBase,
        escalation: { reason: err.message, diagnosis },
        stopSummary,
        children: [],
      };
    }
    const diagnosis = err instanceof Error ? err.message : String(err);
    // #934 ID-003: GitHub auth/login needs external human login — zero retry
    // already (durable class) + typed decision gate; not infra_failure /
    // issue_metadata_unavailable (deterministic bad data / exhausted durable).
    if (isGithubAuthFailure(err)) {
      const stopSummary = decisionGateParkStopSummary({
        summary: `GitHub authentication required: ${diagnosis}`,
        repairHint:
          "run `gh auth login` (or restore GH_TOKEN) on the host, then re-feed",
      });
      // #1007: GitHub auth park — dual-write park+terminal (notify).
      emitExitProgress({
        epic: options.epicIssue,
        status: "parked",
        stopReason: stopSummary.reason,
        gateSummary: stopSummary.summary,
      });
      return {
        status: "parked",
        familyBase: options.familyBase,
        escalation: {
          reason: "GitHub authentication required",
          diagnosis,
        },
        stopSummary,
        children: [],
      };
    }
    // #942 / #934 ID-001: metadata read failure is issue_metadata_unavailable,
    // not coder_rec_invalid (staffing/route mark class).
    const metaStop = infraFailureStopSummary({
      summary: diagnosis,
      repairHint: "repair GitHub metadata access and rerun",
    });
    // #1007: metadata fail — dual-write terminal.
    emitExitProgress({
      epic: options.epicIssue,
      status: "failed",
      stopReason: metaStop.reason,
      gateSummary: metaStop.summary,
    });
    return failedFamilyResult({
      cause: "issue_metadata_unavailable",
      familyBase: options.familyBase,
      escalation: { reason: "issue metadata unavailable", diagnosis },
      stopSummary: metaStop,
      children: [],
    });
  }
  // #934 ID-002 / ID-003: all-filtered is unconditional completed/0 with full
  // skip inventory. Parent is not a planned runnable slice on this path — do
  // not gate success on parent Coder-Rec validity or worksite creation.
  if (epic.children.length === 0) {
    // #1007: all-filtered completed early return — dual-write terminal.
    emitExitProgress({
      epic: options.epicIssue,
      status: "completed",
      stopReason: "already_done",
      gateSummary:
        "family admission skipped every native child; no worksite was created",
    });
    return {
      status: "completed",
      familyBase: options.familyBase,
      stopSummary: {
        reason: "already_done",
        summary: "family admission skipped every native child; no worksite was created",
        metadata: { admissionSkipped: epic.admissionSkipped ?? [] },
      },
      children: [],
      ...(epic.admissionSkipped !== undefined
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  }

  // #934 ID-003: parent + every planned child Coder-Rec aggregated once.
  // Parent failure must not short-circuit the child pass — decide only after
  // the full planned-issue inventory is collected.
  const coderRecErrors: string[] = [];
  const plannedRoutes: ResolvedModelRoute[] = [];
  const parentCoderRec = admitCoderRec(
    admitted.route,
    issueBodies.get(options.epicIssue),
  );
  if (parentCoderRec.kind === "stop") {
    coderRecErrors.push(
      `issue #${options.epicIssue}: ${parentCoderRec.escalation.diagnosis}`,
    );
  } else {
    plannedRoutes.push(parentCoderRec.route);
  }

  for (const child of epic.children) {
    try {
      const body = readIssueBodyCached(
        child.issue,
        options.repo,
        metadataSh,
        issueBodies,
      );
      const childAdmission = admitCoderRec(admitted.route, body);
      if (childAdmission.kind === "stop") {
        coderRecErrors.push(
          `issue #${child.issue}: ${childAdmission.escalation.diagnosis}`,
        );
      } else {
        plannedRoutes.push(childAdmission.route);
      }
    } catch (err) {
      coderRecErrors.push(
        `issue #${child.issue}: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
  if (coderRecErrors.length > 0) {
    const diagnosis = `planned Coder-Rec admission failed (${coderRecErrors.length} errors): ${coderRecErrors.join("; ")}`;
    const stopSummary = infraFailureStopSummary({
      summary: diagnosis,
      repairHint: "repair every listed owner-authored Coder-Rec before rerun",
    });
    // #1007: Coder-Rec admission fail — dual-write terminal.
    emitExitProgress({
      epic: options.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return failedFamilyResult({
      cause: "coder_rec_invalid",
      familyBase: options.familyBase,
      escalation: { reason: "Coder-Rec admission failure", diagnosis },
      stopSummary,
      children: [],
      ...(epic.admissionSkipped !== undefined
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
  }
  // All planned issues admitted — parent is ready (errors would have returned).
  if (parentCoderRec.kind !== "ready") {
    // Unreachable: empty errors + parent stop is contradictory, but keep the
    // exhaustiveness net for the type checker.
    const diagnosis = parentCoderRec.escalation.diagnosis;
    const stopSummary = infraFailureStopSummary({
      summary: `${parentCoderRec.escalation.reason}: ${diagnosis}`,
      repairHint: "repair the owner-authored Coder-Rec before rerun",
    });
    emitExitProgress({
      epic: options.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return failedFamilyResult({
      cause: "coder_rec_invalid",
      familyBase: options.familyBase,
      escalation: { reason: parentCoderRec.escalation.reason, diagnosis },
      stopSummary,
      children: [],
    });
  }
  const coderRec = parentCoderRec;

  // 2. The single-slice RealBackend: keyed on the PARENT epic so all children
  //    share ONE family clone (ADR 0024). Constructing it CLONES the source (pure
  //    git, no container) — that clone is the family clone every git op anchors on.
  //    `familyBase` makes a child cut from the LOCAL family base (decision 7).
  //    Only reached after route admission succeeds.
  const realBackendOptions: RealBackendOptions = {
    codexFast,
    sourceRepo: options.sourceRepo,
    remote: options.remote,
    runKey: options.epicIssue,
    repo: options.repo,
    imageName: options.imageName,
    promptsDir: options.promptsDir,
    soulsDir: options.soulsDir,
    home: options.home,
    familyBase: options.familyBase,
  };
  const realSingleSlice =
    options.realBackendFactory?.(realBackendOptions) ?? new RealBackend(realBackendOptions);
  logDriverStage("smoke-k", `route=${coderRec.route.routeName}`);
  let smoke:
    | Extract<Awaited<ReturnType<typeof admitRouteSmoke>>, { readonly kind: "ready" }>
    | undefined;
  if (options.singleSliceBackendFactory === undefined) {
    const result = await admitPlannedRouteSmoke(realSingleSlice, plannedRoutes);
    if (result.kind === "stop") return routeSmokeFailureResult(options, result.escalation);
    smoke = result;
  }
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
  if (smoke === undefined) {
    logDriverStage("smoke-k", `route=${coderRec.route.routeName}`);
    const result = await admitPlannedRouteSmoke(singleSliceBackend, plannedRoutes);
    if (result.kind === "stop") return routeSmokeFailureResult(options, result.escalation);
    smoke = result;
  }

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

  // 5b. #1006 baseline health gate — admission hot-check member (with smoke):
  // family base must be full-green under the worker container class before any
  // child fan-out. Red → ledger + fail-closed (optional one fix round first).
  //
  // #1017 C1: gate semantics = *fresh pre-fan-out* base health only. A resident
  // non-terminal family that already has durable child progress (merged onto
  // familyBase) must not re-admit the advanced base as "baseline disease" —
  // that mislabels post-merge suite red as baseline_health_failed and skips
  // every remaining child forever. Fresh / resident-without-progress keep the
  // fail-closed path below.
  const skipBaselineHealthGate =
    familyScene.kind === "resident" &&
    mergedSet(familyScene.ledger).size > 0;
  if (skipBaselineHealthGate) {
    logDriverStage(
      "admission",
      `baseline health gate skipped (resident child progress) epic #${options.epicIssue}`,
    );
  } else {
    logDriverStage("admission", `baseline health gate epic #${options.epicIssue}`);
    const baselineRunner = resolveBaselineFullTestRunner(options, {
      workingRepo,
      familyBase: options.familyBase,
      imageName: options.imageName,
      verifyCwd:
        options.verifyCwd ?? resolveBaselineVerifyCwd(workingRepo),
      // Same warm template as family verify installDeps (#746).
      depsTemplateRoot: options.sourceRepo,
    });
    const baseline = await admitBaselineHealth({
      runFullTests: baselineRunner,
      // Always wire the one-shot path (owner: 红 → 一轮 fixer 或报错). Default
      // NOOP returns attempted:false → fail-closed without inventing green.
      tryFix: options.baselineFixAttempt ?? NOOP_BASELINE_FIX_ATTEMPT,
    });
    if (baseline.kind === "stop") {
      await recordBaselineHealthFailed(familyBackend, {
        reason: baseline.escalation.reason,
        message: baseline.escalation.diagnosis,
        familyHeadAfter: familyBaseStartHead,
      });
      const children = epic.children.map((child) => {
        console.warn(
          `family child #${child.issue} skipped: baseline_health_failed`,
        );
        return {
          issue: child.issue,
          status: "skipped" as const,
          reason: "baseline_health_failed" as const,
        };
      });
      const stopSummary = infraFailureStopSummary({
        summary: baseline.escalation.diagnosis,
        // Suite red → one pre-fix ticket; infra red → tooling/deps repair only.
        repairHint: baselineHealthRepairHint(baseline.failure),
      });
      // #1007 / #1009: baseline admission fail must dual-write terminal progress
      // like sibling early exits (fail-open). Residual call-site risk remains
      // elsewhere — no global exit framework this round.
      emitExitProgress({
        epic: options.epicIssue,
        status: "failed",
        stopReason: stopSummary.reason,
        gateSummary: stopSummary.summary,
      });
      return failedFamilyResult({
        cause: "baseline_health_failed",
        familyBase: options.familyBase,
        familyHead: familyBaseStartHead,
        escalation: baseline.escalation,
        stopSummary,
        children,
        ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
          ? { admissionSkipped: epic.admissionSkipped }
          : {}),
      });
    }
  }

  // 6. Assemble the run input + the resume seams, and run the spine.
  // reconcile stage is logged inside runFamily immediately before the real
  // reconcile work (not here) so a hang after smoke-k is still attributable.
  const input: FamilyRunInput = {
    epic,
    familyBackend,
    singleSliceBackend,
    admittedRoute: { route: smoke.route, dropped: smoke.dropped },
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
 * #1006 — resolve the baseline full runner.
 * Production (no backend factories) → worker-image container full.
 * Injected/zero-container test paths without an explicit runner → green no-op
 * so fixtures keep the pre-#1006 success shape without wall-clock docker.
 */
function resolveBaselineFullTestRunner(
  options: FamilyDriverOptions,
  req: {
    readonly workingRepo: string;
    readonly familyBase: string;
    readonly imageName: string;
    readonly verifyCwd: string;
    readonly depsTemplateRoot?: string;
  },
): BaselineFullTestRunner {
  if (options.baselineFullTestRunner !== undefined) {
    return options.baselineFullTestRunner;
  }
  const injectedBackend =
    options.singleSliceBackendFactory !== undefined ||
    options.familyBackendFactory !== undefined ||
    options.realBackendFactory !== undefined ||
    options.realFamilyBackendFactory !== undefined;
  if (injectedBackend) {
    return async (): Promise<BaselineFullTestResult> => ({ ok: true });
  }
  return () =>
    runBaselineFullTestsInWorkerContainer({
      imageName: req.imageName,
      workingRepo: req.workingRepo,
      familyBase: req.familyBase,
      verifyCwd: req.verifyCwd,
      ...(req.depsTemplateRoot !== undefined
        ? { depsTemplateRoot: req.depsTemplateRoot }
        : {}),
    });
}

/** Prefer orchestrator/ subproject when present; else clone root. */
function resolveBaselineVerifyCwd(workingRepo: string): string {
  const orchestrator = join(workingRepo, "orchestrator");
  if (existsSync(join(orchestrator, "package.json"))) return orchestrator;
  return workingRepo;
}

function routeSmokeFailureResult(
  options: Pick<FamilyDriverOptions, "familyBase" | "epicIssue">,
  escalation: { readonly reason: string; readonly diagnosis: string },
): FamilyRunResult {
  const stopSummary = infraFailureStopSummary({
    summary: escalation.diagnosis,
    repairHint: "repair the selected model×pipe smoke before rerun",
  });
  // #1007: shared driver smoke-fail helper dual-writes terminal.
  emitExitProgress({
    epic: options.epicIssue,
    status: "failed",
    stopReason: stopSummary.reason,
    gateSummary: stopSummary.summary,
  });
  return failedFamilyResult({
    // #942 public cause: same smoke-stop as family/single-slice runners
    // (not worktree_prepare_failed — PR #982 C2).
    cause: "route_smoke_failed",
    familyBase: options.familyBase,
    escalation,
    stopSummary,
    children: [],
  });
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

// Public exit map re-export for launchers that only import familyDriver (#942).
export {
  PUBLIC_EXIT_CODES,
  PUBLIC_RUN_RESULTS,
  exitCodeForPublicResult,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isPublicRunResult,
  publicResultExitCode,
  runResultExitCode,
} from "./publicResult.js";
export type { PublicRunResult } from "./publicResult.js";

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
  // Fresh cut: a configured origin makes fetch authoritative. Only a clone with
  // no origin is local-only; a failed configured remote must never select stale
  // local state (#934 ID-009 / ID-015 precise Git predicate).
  let hasRemote = false;
  try {
    git("remote", "get-url", "origin");
    hasRemote = true;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // Precise missing-origin only (git: "fatal: No such remote 'origin'").
    // Any other get-url failure is operational — fail closed, never stale local.
    if (/no such remote/i.test(msg)) {
      hasRemote = false;
    } else {
      throw new Error(
        `cutFamilyBase: git remote get-url origin failed (not a precise ` +
          `missing-origin); refusing stale local base fallback (#934 ID-009). ` +
          `(${msg})`,
      );
    }
  }
  if (hasRemote) {
    git("fetch", "origin", base);
    git("branch", familyBase, `origin/${base}`);
  } else {
    git("branch", familyBase, base);
  }
  const startHead = git("rev-parse", familyBase);
  // Persist the cut SHA durably (outside the worktree) so a resume reads it back.
  mkdirSync(ledgerDir, { recursive: true });
  writeFileSync(startHeadFile, startHead + "\n", "utf8");
  return startHead;
}

/**
 * Does a local branch exist on the clone? (`-q`: no stderr noise when absent.)
 *
 * #934 ID-015 / ID-009: precise missing-ref only (`git rev-parse --verify` exit 1)
 * → false. Any other failure (exit 128 / spawn / broken repo) fails closed — never
 * soft as "absent" (that would re-cut over a live base).
 */
function branchExists(workingRepo: string, branch: string, sh: Sh): boolean {
  try {
    sh("git", ["-C", workingRepo, "rev-parse", "-q", "--verify", `refs/heads/${branch}`]);
    return true;
  } catch (err) {
    if (gitExitStatus(err) === 1) return false;
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `cutFamilyBase: git rev-parse --verify refs/heads/${branch} failed ` +
        `(not a precise missing-ref/exit 1); refusing to treat the branch as ` +
        `absent (#934 ID-015/ID-009). (${msg})`,
    );
  }
}
