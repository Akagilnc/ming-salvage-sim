/**
 * runFamily — the family spine (ADR 0022 decisions 1/2/3②/6, #293).
 *
 * The thinnest complete family closure:
 *   parent epic (children already cut + blocked_by)             [ADR 0022 dec.1]
 *     → commander.selectWave → the unblocked wave
 *     → fan out each child through the REUSED single-slice runOrchestrator,
 *       in family mode (cut from family base, S7 push = local no-op)  [dec.2/7]
 *     → merger.mergeChild → serial `git merge --no-ff` into family base [dec.3②]
 *       (which writes the append-only family-ledger entry)             [dec.5]
 *     → verify-cmr hook (no-op in #293)                            [dec.3④/⑥ seam]
 *     → loop until the commander returns an empty wave.
 *
 * The spine is a THIN scheduler: it OWNS none of the four extension modules'
 * logic — it only CALLS them (selectWave / runOrchestrator / mergeChild /
 * runVerifyCmr). That is the acceptance-4 boundary: #294 (waves), #295 (merge
 * conflict), #296 (verify+cmr), #298 (ledger) each grow THEIR module and the
 * spine keeps calling the same functions. #293 does NOT process conflicts, run
 * verify/cmr, or do crash-resume reconcile (those are the later slices).
 *
 * The wave loop is written generally (re-select after each wave from the merged
 * set) so #294's multi-wave dependency scheduling drops in WITHOUT a spine
 * rewrite — but #293's children are all independent, so it converges in one wave.
 */

import { runOrchestrator } from "../runner.js";
import {
  applyRuntimeTightRoutePolicy,
  printableRouteLineup,
  resolveActiveModelRoute,
} from "../modelRoutes.js";
import type { Backend } from "../types.js";
import { assertAcyclic, selectWave } from "./commander.js";
import {
  familyEscalationState,
  familyShippedRecordForHead,
  hasBoundShippedMarker,
  hasUnboundLegacyShippedMarker,
  isMergedAccountingEntry,
  mergedSet,
  recordAdmissionSkipped,
  recordFamilyEscalated,
  recordMerged,
} from "./ledger.js";
import { mergeChild } from "./merger.js";
import { reconcileFamilyLedger } from "./reconcile.js";
import { runVerifyCmr } from "./verifyCmr.js";
import { buildFamilyModuleContext } from "./cmrClassification.js";
import {
  contractDriftStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyChildResult,
  FamilyLedgerEntry,
  FamilyRunInput,
  FamilyRunResult,
  FamilyRunStatus,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

function filled(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function familyHeadMetadata(input: {
  readonly reportedFamilyHead?: string;
  readonly actualFamilyHead?: string;
  readonly actualFamilyHeadSource?: string;
  readonly verifiedCmrHead?: string;
}): StopSummary["metadata"] | undefined {
  const reportedFamilyHead = filled(input.reportedFamilyHead);
  const actualFamilyHead = filled(input.actualFamilyHead);
  const verifiedCmrHead = filled(input.verifiedCmrHead);
  if (
    reportedFamilyHead === undefined &&
    actualFamilyHead === undefined &&
    verifiedCmrHead === undefined
  ) {
    return undefined;
  }
  const sources: Record<string, string> = {};
  if (reportedFamilyHead !== undefined) {
    sources.reportedFamilyHead = "FamilyRunResult.familyHead";
  }
  if (actualFamilyHead !== undefined) {
    sources.actualFamilyHead =
      input.actualFamilyHeadSource ?? "family runner current head";
  }
  if (verifiedCmrHead !== undefined) {
    sources.verifiedCmrHead = "latest cmr_passed ledger row";
  }
  return {
    heads: {
      ...(reportedFamilyHead !== undefined ? { reportedFamilyHead } : {}),
      ...(actualFamilyHead !== undefined ? { actualFamilyHead } : {}),
      ...(verifiedCmrHead !== undefined ? { verifiedCmrHead } : {}),
      sources,
    },
  };
}

function familyStopSummary(input: {
  readonly status: FamilyRunStatus;
  readonly failedPhase?: VerifyCmrPhase;
  readonly familyHead?: string;
  readonly headMetadata?: StopSummary["metadata"];
  readonly barrierStopSummary?: StopSummary;
  readonly familyBase: string;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly escalationReason?: string;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
  readonly alreadyDone?: ReadonlyArray<{
    readonly issue: number;
    readonly status: "merged" | "shipped" | "completed";
    readonly source: string;
  }>;
}): StopSummary {
  const metadata =
    input.headMetadata ??
    familyHeadMetadata({
      reportedFamilyHead: input.familyHead,
      actualFamilyHead: input.familyHead,
    });
  if (input.status === "success") {
    const hasMetadata =
      metadata?.heads !== undefined ||
      (input.admissionSkipped?.length ?? 0) > 0 ||
      (input.alreadyDone?.length ?? 0) > 0;
    return successStopSummary(
      hasMetadata
        ? {
            ...(metadata?.heads !== undefined ? { heads: metadata.heads } : {}),
            ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
              ? { admissionSkipped: input.admissionSkipped }
              : {}),
            ...(input.alreadyDone !== undefined && input.alreadyDone.length > 0
              ? { alreadyDone: input.alreadyDone }
              : {}),
          }
        : undefined,
    );
  }
  if (input.status === "verify_failed") {
    if (input.barrierStopSummary !== undefined) return input.barrierStopSummary;
    return infraFailureStopSummary({
      summary: `family ${input.failedPhase ?? "unknown"} verify/cmr barrier failed`,
      repairHint: "inspect the family ledger aborted entry, repair the failing barrier, and rerun",
      ...(metadata?.heads !== undefined ? { heads: metadata.heads } : {}),
    });
  }
  if (input.status === "incomplete") {
    const blocked = input.children
      .filter((child) => child.status !== "merged")
      .map((child) => `#${child.issue}:${child.status}`)
      .join(", ");
    return {
      reason: "owning_issue_still_red",
      summary: `family run is incomplete; unmerged children: ${blocked}`,
      repairHint: "repair or complete the listed child slices and rerun the family",
    };
  }
  return {
    reason: "infra_failure",
    summary: input.escalationReason ?? "family run escalated",
    repairHint: "inspect the family ledger escalation entry and repair before rerun",
    ...(metadata !== undefined ? { metadata } : {}),
  };
}

/**
 * Run a child slice through the reused single-slice runner in FAMILY MODE.
 *
 * Family context (ADR 0022 decision 2) is passed via RunInput.family so the
 * single-slice runner cuts from the family base + no-ops S7 push. The child is a
 * leaf (no sub-issues) so its own S0 gate passes unchanged; #293's wave is
 * all-unblocked children so the ledger口径 dependency check (dec.6③) is trivially
 * satisfied (empty blocked_by).
 */
async function runChild(
  child: ChildSlice,
  singleSliceBackend: Backend,
  parentIssue: number,
  familyBase: string,
  familyChildIssues: ReadonlySet<number>,
): Promise<FamilyChildResult> {
  const result = await runOrchestrator({
    issueNumber: child.issue,
    backend: singleSliceBackend,
    // #294 (ADR 0022 decision 6③): hand the child its ledger-merged blockers so
    // its OWN single-slice S0 `blocked_by` gate uses the ledger-merged口径, not
    // GitHub `closed`. runChild only runs a child the commander released — selectWave
    // confirmed every INTRA-FAMILY `blocked_by` is in the merged set — so each such
    // blocker IS merged into the family base for this child. We pass ONLY the
    // intra-family subset (a `blocked_by` issue that is itself a family sibling):
    // those are the blockers the commander can possibly have ledger-merged. An
    // EXTERNAL `blocked_by` (not a family child) is never in the family ledger, so it
    // is NOT excused here — but it is also NOT relied upon at S0: the family-admission
    // gate (`assertExternalBlockersCleared`, online R1 #1) already fail-closed the run
    // up front unless every external blocker was closed, and selectWave no longer
    // gates on external blockers. Passing only the intra-family subset keeps S0 from
    // seeing a non-family number it has no ledger evidence for; the live S0 fetch
    // remains a backstop should an external blocker RE-open mid-run. For an
    // intra-family blocker that IS ledger-merged, the child's S0 treats a
    // still-open-on-GitHub blocker as satisfied, so a just-released child is not
    // re-rejected (the agy R2 deadlock).
    family: {
      parentIssue,
      familyBase,
      noPush: true,
      mergedBlockers: child.blockedBy.filter((b) => familyChildIssues.has(b)),
    },
  });
  if (result.status === "success" && result.branch !== undefined) {
    // The single-slice run succeeded and produced a reviewed branch — but it is
    // NOT merged yet (the spine's serial-merge step does that, then flips this to
    // "merged" once the merge commit lands — ADR 0022 decision 5). So runChild
    // returns the transient "ran", never a premature "merged".
    return { issue: child.issue, status: "ran", branch: result.branch };
  }
  // #293 thinnest: a non-success child does not merge. (Richer per-child
  // failure / escalate handling is downstream; the spine records it as failed
  // so the wave's outcome is honest, not silently dropped.)
  return { issue: child.issue, status: "failed" };
}

/**
 * Read the current merged set from the family ledger (the commander's unblock
 * truth, ADR 0022 decision 6②). Re-read each wave so #294's dependency
 * scheduling sees the freshly-merged children.
 */
async function currentMerged(
  familyBackend: FamilyBackend,
): Promise<ReadonlySet<number>> {
  return mergedSet(await familyBackend.readFamilyLedger());
}

async function readCurrentFamilyHead(
  familyBackend: FamilyBackend,
  familyBase: string,
): Promise<string | undefined> {
  if (familyBackend.readFamilyHead === undefined) return undefined;
  try {
    const head = (await familyBackend.readFamilyHead(familyBase)).trim();
    return head.length > 0 ? head : undefined;
  } catch {
    return undefined;
  }
}

function latestVerifiedCmrHead(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "cmr_passed" &&
      entry.event === "cmr_passed" &&
      entry.phase === "final" &&
      filled(entry.familyHeadAfter) !== undefined
    ) {
      return filled(entry.familyHeadAfter);
    }
  }
  return undefined;
}

function pendingPriorCmrFindingIdentityKeys(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlyArray<string> {
  const keys: string[] = [];
  const seen = new Set<string>();
  for (let index = ledger.length - 1; index >= 0; index--) {
    const entry = ledger[index]!;
    if (entry.status === "shipped" || entry.status === "cmr_passed") break;
    if (entry.status !== "aborted" || entry.cmrFindingClassification === undefined) {
      continue;
    }
    for (const result of entry.cmrFindingClassification.results) {
      if (
        result.classification === "cross_module_defer" ||
        result.classification === "accepted_suppressed" ||
        result.classification === "not_converged"
      ) {
        continue;
      }
      if (!seen.has(result.identityKey)) {
        seen.add(result.identityKey);
        keys.push(result.identityKey);
      }
    }
  }
  return keys.reverse();
}

function latestAbortedStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  phase: VerifyCmrPhase | undefined,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "aborted" &&
      (phase === undefined || entry.phase === phase) &&
      entry.stopSummary !== undefined
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

/**
 * Derive the child issue numbers whose merge into the family base was LLM-resolved
 * (#291 缺口 1), read from the DURABLE family ledger — the only truth that survives
 * a context compaction. The spine hands this to the final-phase integrated cmr 承重闸
 * so it can focus its cross-slice review on the merges a machine touched
 * ("不静默吞"). Reads `conflictResolvedByLlm===true` `merged` entries; a clean merge
 * / reconcile補账条 / aborted event is excluded. In ledger write order, deduped.
 */
async function llmResolvedChildren(
  familyBackend: FamilyBackend,
): Promise<readonly number[]> {
  const ledger = await familyBackend.readFamilyLedger();
  const seen = new Set<number>();
  const out: number[] = [];
  for (const e of ledger) {
    if (
      isMergedAccountingEntry(e) &&
      e.conflictResolvedByLlm === true &&
      !seen.has(e.childIssue)
    ) {
      seen.add(e.childIssue);
      out.push(e.childIssue);
    }
  }
  return out;
}

/**
 * The family spine entry point (#293).
 *
 * @returns the family base branch + its HEAD after all merges + per-child
 *   outcomes. Acceptance 1: N independent ready children → one wave → serially
 *   merged into the family base.
 */
export async function runFamily(
  input: FamilyRunInput,
): Promise<FamilyRunResult> {
  let modelRoute;
  try {
    modelRoute = resolveActiveModelRoute();
  } catch (err) {
    const reason =
      err instanceof Error ? err.message : `failed to resolve active model route: ${String(err)}`;
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase: input.familyBase,
      escalation: {
        reason: "startup route failure",
        diagnosis: reason,
      },
      stopSummary: infraFailureStopSummary({
        summary: `startup route failure: ${reason}; route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}, ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS=${process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS ?? "(unset)"}`,
        repairHint: "repair the family runner route environment before rerun",
      }),
      children,
      ...(input.epic.admissionSkipped !== undefined &&
      input.epic.admissionSkipped.length > 0
        ? { admissionSkipped: input.epic.admissionSkipped }
        : {}),
    };
  }
  const routePolicy = await applyRuntimeTightRoutePolicy(modelRoute, {
    interactive: process.stdin.isTTY === true && process.stdout.isTTY === true,
    warn: (message) => console.warn(`[orchestrator:family] ${message}`),
  });
  if (routePolicy.kind === "stop") {
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase: input.familyBase,
      escalation: routePolicy.escalation,
      stopSummary: familyStopSummary({
        status: "escalated",
        familyBase: input.familyBase,
        children,
        escalationReason: `${routePolicy.escalation.reason}: ${routePolicy.escalation.diagnosis}`,
      }),
      children,
    };
  }
  console.info(
    `[orchestrator:family] model route lineup\n${printableRouteLineup(routePolicy.route)}`,
  );
  const { familyBackend, singleSliceBackend, familyBase } = input;
  let initialFamilyLedger = await familyBackend.readFamilyLedger();
  for (const skipped of input.epic.admissionSkipped ?? []) {
    const alreadyRecorded = initialFamilyLedger.some(
      (entry) =>
        entry.status === "admission_skipped" &&
        entry.event === "admission_skipped" &&
        entry.childIssue === skipped.issue &&
        entry.reason === skipped.reason,
    );
    if (!alreadyRecorded) {
      await recordAdmissionSkipped(familyBackend, skipped);
    }
  }
  if ((input.epic.admissionSkipped?.length ?? 0) > 0) {
    initialFamilyLedger = await familyBackend.readFamilyLedger();
  }
  const priorEscalation = familyEscalationState(initialFamilyLedger);
  if (priorEscalation !== undefined) {
    const { escalation, answer } = priorEscalation;
    if (escalation.escalationKind !== "decision" || answer === undefined) {
      const ledgerMerged = mergedSet(initialFamilyLedger);
      return {
        status: "escalated",
        familyBase,
        ...(typeof escalation.familyHeadAfter === "string" &&
        escalation.familyHeadAfter.trim().length > 0
          ? { familyHead: escalation.familyHeadAfter }
          : {}),
        escalation: {
          reason:
            typeof escalation.reason === "string" && escalation.reason.trim().length > 0
              ? escalation.reason
              : "family escalation is not answered",
          diagnosis:
            escalation.escalationKind === "failure"
              ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
              : escalation.escalationKind !== "decision"
                ? "Prior family escalation kind is missing or invalid; append-only answers only reopen decision escalations."
              : "Prior family decision escalation has no later valid escalation_answered ledger event.",
        },
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead:
            typeof escalation.familyHeadAfter === "string" &&
            escalation.familyHeadAfter.trim().length > 0
              ? escalation.familyHeadAfter
              : undefined,
          children: input.epic.children.map((child) => ({
            issue: child.issue,
            status: ledgerMerged.has(child.issue) ? "merged" : "skipped",
          })),
          escalationReason:
            typeof escalation.reason === "string" && escalation.reason.trim().length > 0
              ? escalation.reason
              : "family escalation is not answered",
        }),
        children: input.epic.children.map((child) => ({
          issue: child.issue,
          status: ledgerMerged.has(child.issue) ? "merged" : "skipped",
        })),
      };
    }
  }
  const escalationAnswer = priorEscalation?.answer;
  // ── #298 escalate-resume dependency-graph rebuild (ADR 0022 decision 4) ─────
  // APPEND-ONLY resume entry: when a `refetchEpic` hook is injected (a re-entry
  // after escalation — cmr non-convergence / a cycle a human edited in GitHub),
  // REBUILD the dependency graph from LIVE GitHub metadata, NOT the cached epic
  // (decision 4 不信缓存; else a stale cycle re-escalates, agy R2). Absent ⇒ the
  // passed `epic` is used unchanged (a fresh run). The commander then schedules
  // off the live graph below — and #294's cycle guard validates THIS live graph
  // (so a re-entry whose human edit broke the cycle is NOT re-rejected off the
  // stale cached edges).
  const epic =
    input.refetchEpic !== undefined ? await input.refetchEpic() : input.epic;
  // ── #294: fail-closed cycle guard (ADR 0022 decisions 3①/4) ────────────────
  // BEFORE any scheduling (but AFTER the #298 live re-fetch above, so the guard
  // sees the live graph): validate the children's intra-family `blocked_by`
  // graph is acyclic. A cycle makes selectWave return an empty wave forever (a
  // SILENT deadlock — the members never unblock), so the commander throws a
  // DependencyCycleError here and runFamily fails closed (the caller escalates to
  // a human per decision 4, who fixes the to-issues edges and re-runs). This runs
  // up front so nothing is fanned out / merged before the deadlock is caught.
  assertAcyclic(epic.children);
  // The set of THIS family's child issue numbers — used to split a child's
  // `blocked_by` into intra-family blockers (the commander can ledger-merge them)
  // vs external blockers (never in the family ledger; cleared up front at family
  // admission per `assertExternalBlockersCleared`, online R1 #1 — NOT relied upon at
  // S0). Invariant for the run (epic.children is fixed), so computed once.
  const familyChildIssues = new Set(epic.children.map((c) => c.issue));
  const moduleContext = buildFamilyModuleContext({
    childModules: epic.children.map((child) => child.moduleDeclaration),
    familyModule: epic.moduleDeclaration,
    runOptionModule: input.moduleDeclaration,
    undevelopedModules: input.undevelopedModules,
    acceptedSuppressionSources: input.acceptedSuppressionSources,
  });
  const declaredModuleContext =
    moduleContext.currentModules.length > 0 || moduleContext.childModules.length > 0
      ? moduleContext
      : undefined;
  // The verify-cmr hook: the injected impl (#296 / tests) or the #293 no-op module
  // default. The spine's call sites + fail-fast on `ok===false` are identical
  // either way (ADR 0022 decision 3④/⑤/⑥; acceptance-4 seam boundary).
  const verifyCmr = input.verifyCmr ?? runVerifyCmr;
  const childResults: FamilyChildResult[] = [];
  let familyHead: string | undefined;

  // Build the family result, accounting for EVERY epic child, and deriving an
  // HONEST family status (decision 3⑤ "不静默吞" — the result must not silently
  // look like success):
  //
  //   - every epic child gets a record. A child not run this invocation is
  //     LEDGER-AWARE: if it has a `merged` ledger entry (e.g. merged in a prior
  //     invocation — #298's resume truth), it is `"merged"` (per the
  //     FamilyChildStatus contract: "merged" ⇔ a merged ledger entry exists), NOT
  //     `"skipped"`. Only a child absent from BOTH this run's results AND the
  //     merged ledger (a blocker never merged / a fail-fast wave aborted before
  //     it ran) is `"skipped"`.
  //   - `status` is the verify outcome ONLY when a barrier was red
  //     (`verify_failed`, the most urgent). Otherwise the run is `"success"` iff
  //     EVERY child is merged, else `"incomplete"` (a child `failed`/`skipped` —
  //     the run did not fully close; the caller must not treat it as shippable).
  //
  // #293's happy path (all independent children merge, no-op verify passes) is
  // always `"success"`; the `incomplete`/`verify_failed`/ledger-merged branches
  // guard honesty for the failure + #294/#298 paths.
  const finalize = async (
    verifyFailedPhase?: VerifyCmrPhase,
  ): Promise<FamilyRunResult> => {
    const recorded = new Set(childResults.map((c) => c.issue));
    const ledgerMerged = await currentMerged(familyBackend);
    const familyLedger = await familyBackend.readFamilyLedger();
    const extra: FamilyChildResult[] = epic.children
      .filter((c) => !recorded.has(c.issue))
      .map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
    const children = [...childResults, ...extra];
    const status: FamilyRunStatus =
      verifyFailedPhase !== undefined
        ? "verify_failed"
        : children.every((c) => c.status === "merged" || c.status === "already_done")
          ? "success"
          : "incomplete";
    const actualFamilyHead = await readCurrentFamilyHead(familyBackend, familyBase);
    const headMetadata = familyHeadMetadata({
      reportedFamilyHead: familyHead,
      actualFamilyHead: actualFamilyHead ?? familyHead,
      actualFamilyHeadSource:
        actualFamilyHead !== undefined
          ? "familyBackend.readFamilyHead"
          : "family runner current head",
      verifiedCmrHead: latestVerifiedCmrHead(familyLedger),
    });
    const barrierStopSummary =
      status === "verify_failed"
        ? (latestAbortedStopSummary(familyLedger, verifyFailedPhase) ??
          latestAbortedStopSummary(familyLedger, undefined))
        : undefined;
    const alreadyDone = extra
      .filter((child) => child.status === "already_done")
      .map((child) => ({
        issue: child.issue,
        status: "merged" as const,
        source: "family child already_done result",
      }));
    const allChildrenAlreadyDone =
      status === "success" &&
      childResults.length === 0 &&
      children.length > 0 &&
      alreadyDone.length === children.length;
    const computedStopSummary = familyStopSummary({
      status,
      failedPhase: verifyFailedPhase,
      familyBase,
      familyHead,
      headMetadata,
      barrierStopSummary,
      children,
      admissionSkipped: epic.admissionSkipped,
      alreadyDone,
    });
    return {
      status,
      ...(verifyFailedPhase !== undefined ? { failedPhase: verifyFailedPhase } : {}),
      familyBase,
      familyHead,
      stopSummary: allChildrenAlreadyDone
        ? {
            ...computedStopSummary,
            reason: "already_done",
            summary: "family resume found every child already merged and skipped rerun",
          }
        : computedStopSummary,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  };

  // ── #298 crash-window reconcile (the RESUME ENTRY, ADR 0022 decision 5) ─────
  // APPEND-ONLY into the spine: this runs BEFORE the wave loop and does NOT touch
  // its structure. When a `reconcileGit` seam is injected (a resume), compare the
  // ledger末条 head to the live family-base HEAD and:
  //   - branch ② (live HEAD leads — a merge landed but its `merged` write
  //     crashed): APPEND a reconcile補账条 (`status:"merged"` + `event:"reconciled"`)
  //     for each ancestor-confirmed child, so `currentMerged` (re-read each wave)
  //     skips it (no double-merge); a never-merged child (childHead absent / not an
  //     ancestor) is left OUT and the existing wave loop re-runs it (no漏合);
  //   - branch ③ (inconsistent live HEAD): bail fail-closed to `status:"escalated"`
  //     BEFORE any merge (decision 5 真有未落/不一致 → 升级; decision 4 escalate).
  // Absent ⇒ a fresh run, the #293 behaviour unchanged. The reconcile LOGIC lives
  // in reconcile.ts; the spine only CALLS it + appends its补账条 (acceptance-4
  // seam boundary — the spine never carries the reconcile algorithm).
  if (input.reconcileGit !== undefined) {
    const ledger = await familyBackend.readFamilyLedger();
    const plan = await reconcileFamilyLedger(
      ledger,
      epic.children,
      input.reconcileGit,
    );
    if (plan.escalate) {
      // Fail-closed (decision 5 branch ③): do not proceed to the wave loop. The
      // family base + ledger are left for human triage (decision 3⑤ 不静默吞);
      // the run is observably `escalated`, NOT a fabricated success.
      const children: FamilyChildResult[] = epic.children.map((c) =>
        plan.merged.has(c.issue)
          ? { issue: c.issue, status: "merged" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: "family reconcile found the live family-base HEAD inconsistent with the ledger",
        familyHeadAfter: plan.liveHead,
      });
      return {
        status: "escalated",
        familyBase,
        familyHead,
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead,
          children,
          escalationReason:
            "family reconcile found the live family-base HEAD inconsistent with the ledger",
        }),
        children,
      };
    }
    // Append each reconcile補账条 (status:"merged" + event:"reconciled") through
    // the ledger seam so the wave loop's `currentMerged` counts it (codex R3) and
    // never re-merges the already-landed child.
    //
    // Baseline-advance only on the LAST補账条 (cmr R2: agy). The append loop is
    // itself a crash window: if EVERY補账条 stamped `familyHeadAfter: plan.liveHead`
    // and the process died after writing補账条 i but before i+1, the next resume's
    // `lastRecordedHead` would return liveHead (from补账条 i) → reconcile branch ①
    // (baseline === liveHead) → it would TRUST the incomplete merged set and the
    // un-appended landed children (i+1 …) would be re-run + re-merged (a
    // double-merge). By stamping `familyHeadAfter` ONLY on the final補账条, a
    // mid-loop-crash residue ends in a补账条 WITHOUT a head → `lastRecordedHead`
    // falls back to the PRIOR real baseline → live still LEADS it → branch ②
    // re-reconciles the remaining landed children idempotently (the already-written
    // ones are `status:"merged"` → skipped, the missing ones re-补账ed), no
    // double-merge. The final補账条 advances the baseline to the verified live HEAD
    // so a clean (non-crashed) resume's `lastRecordedHead` is correct (cmr R1).
    const lastReconciledIdx = plan.reconciled.length - 1;
    for (let i = 0; i < plan.reconciled.length; i++) {
      const r = plan.reconciled[i]!;
      await recordMerged(familyBackend, {
        childIssue: r.childIssue,
        childHead: r.childHead,
        ...(i === lastReconciledIdx
          ? { familyHeadAfter: plan.liveHead }
          : {}),
        event: "reconciled",
      });
    }
    // Step6 cmr (codex #3 + Claude): `familyHead` is otherwise assigned ONLY inside
    // the wave merge loop. On a resume where reconcile accounts for EVERY remaining
    // child (its补账 + the prior ledger cover the whole epic), `currentMerged` skips
    // them all → the wave loop runs NO merge → `familyHead` would leak `undefined`,
    // even though the family base真实 leads at the reconcile-verified `liveHead`.
    // Seed it from `plan.liveHead` whenever the base already has merges (`merged`
    // non-empty), so a no-new-merge resume's FINAL-barrier durable `aborted`
    // familyHeadAfter baseline (#291 缺口 2) AND the returned `FamilyRunResult`
    // report the真实 head; a later wave merge (:familyHead = mergeResult.familyHead)
    // overwrites it. A truly fresh run (empty ledger, nothing merged) leaves it
    // `undefined` — `plan.merged` is empty there, so the guard does not fire.
    if (plan.merged.size > 0) familyHead = plan.liveHead;
  }

  // The wave loop. Re-select from the merged set after each wave so a future
  // multi-wave epic (#294) advances as blockers merge; #293's all-unblocked
  // children converge in a single pass. Guard against a no-progress wave (a
  // child that failed to merge would otherwise re-select forever) by tracking
  // the set of children the spine has already ATTEMPTED.
  const attempted = new Set<number>();
  for (;;) {
    const merged = await currentMerged(familyBackend);
    const wave = selectWave(epic.children, merged).filter(
      (c) => !attempted.has(c.issue),
    );
    if (wave.length === 0) break;

    // ── fan out the wave: each child through the reused single-slice runner ──
    // ADR 0022 decision 2 (native fork + distinct branch) is the RealBackend's
    // job (each child run cuts its own distinct branch in the shared clone). The
    // wave-level fan-out POLICY — how the wave's children are run relative to each
    // other — lives in THIS loop, not in the Backend (the Backend interface is
    // per-child: prepareWorktree / runStep / push; it has no whole-wave method).
    //
    // #291 B7 (the deferred US7 work this comment foretold): the wave's children
    // run CONCURRENTLY — `Promise.allSettled(wave.map(runChild))` — so their LLM
    // work overlaps instead of串行. This is the local fan-out change the seam
    // boundary anticipated: the wave/MERGE/verify structure around it is unchanged
    // (the merge loop below is still serial + in wave order). Distinct child
    // branches isolate the LOGICAL work but NOT git-level locks; concurrent
    // `git worktree add` / ref updates on the one shared clone contend on
    // `.git/index.lock`, so the git-MUTATING critical sections are serialised by a
    // per-clone mutex INSIDE the RealBackend (gitMutex, NOT the spine) — LLM
    // concurrent, git临界区 serial. `allSettled` preserves input order, so `ran` is
    // still in wave order for the serial merge.
    //
    // FAIL-CLOSED preservation: a child whose single-slice run THROWS (e.g. its own
    // S0 backstop rejects a blocker that RE-opened after the admission gate cleared
    // it — decision 6③ soundness) must still fail the whole run, exactly as the prior
    // `for…await` let the throw propagate. So after settling we RE-THROW the first
    // rejection before recording any wave result (nothing is merged on a thrown wave —
    // the cycle / admission external-blocker guards stay fail-closed).
    for (const child of wave) attempted.add(child.issue);
    const settled = await Promise.allSettled(
      wave.map((child) =>
        runChild(
          child,
          singleSliceBackend,
          epic.issue,
          familyBase,
          familyChildIssues,
        ),
      ),
    );
    const firstRejected = settled.find((s) => s.status === "rejected");
    if (firstRejected !== undefined && firstRejected.status === "rejected") {
      throw firstRejected.reason;
    }
    const ran: FamilyChildResult[] = settled.map((s) => {
      // Every entry is fulfilled here (a rejection re-threw above); the cast is
      // narrowing for TS, not a runtime assumption.
      return (s as PromiseFulfilledResult<FamilyChildResult>).value;
    });

    // ── serial merge: each reviewed child branch into the family base ──────────
    // merger.mergeChild does the `git merge --no-ff` (via the FamilyBackend seam)
    // AND writes the merged ledger entry (decision 5 order). The spine never does
    // the merge itself — that is the #295 seam boundary. A child is recorded
    // `"merged"` ONLY AFTER its merge commit lands (decision 5): runChild returns
    // `"ran"` (single-slice success, not yet merged), and we flip it to `"merged"`
    // here once mergeChild resolves — so a future #295 merge failure can leave the
    // child as `"ran"`/`"failed"` instead of a stale `"merged"`.
    for (const r of ran) {
      if (r.status === "ran" && r.branch !== undefined) {
        const mergeResult = await mergeChild(familyBackend, {
          childIssue: r.issue,
          childBranch: r.branch,
        });
        familyHead = mergeResult.familyHead;
        childResults.push({ issue: r.issue, status: "merged", branch: r.branch });
      } else {
        childResults.push({ issue: r.issue, status: r.status, branch: r.branch });
      }
    }

    // ── verify-cmr hook: per-wave barrier (#293 no-op seam, #296 fills) ─────────
    // Decision 3④: a red wave fails-fast — abort BEFORE selecting the next wave.
    // #293's no-op returns ok:true so the loop continues; the spine ALREADY acts
    // on `ok` and passes the phase + context, so #296 fills only the hook body
    // (run typecheck + tests in the family base) without touching this loop.
    const waveVerify = await verifyCmr({
      phase: "wave",
      familyBase,
      familyBackend,
      // #291 缺口 2: hand the abort-time family head to the hook so a RED wave verify
      // records it on the PHASE-LEVEL durable aborted entry's `familyHeadAfter`
      // (reconcile's baseline read covers the abort). `familyHead` is the head after
      // this wave's last merge — undefined only if nothing merged this run.
      familyHeadAfter: familyHead,
      familyIssue: epic.issue,
      ...(declaredModuleContext !== undefined
        ? { moduleContext: declaredModuleContext }
        : {}),
    });
    if (!waveVerify.ok) {
      // Fail-fast (decision 3④): do not排下一波. #296's red wave lands here; the
      // family base + ledger are left for triage (decision 3⑤ "不静默吞"). Children
      // not yet run are recorded "skipped"/"merged" by finalize(); the run is
      // observably `verify_failed` at the "wave" phase (NOT an indistinguishable
      // success).
      return await finalize("wave");
    }
  }

  // ── completeness gate (online R1 Codex P1): the final barrier is meaningful ONLY
  // for a COMPLETE family base ────────────────────────────────────────────────
  // A child can leave the wave loop UNMERGED without throwing (its single-slice run
  // returned "failed", or it stayed blocked) — finalize() then marks the run
  // "incomplete". Running the final barrier (全量 verify → integrated cmr → 止于-PR)
  // on that PARTIAL base would open a family PR missing slices, even though the
  // returned status is not shippable. So gate it: if not EVERY epic child is
  // ledger-merged, skip the barrier and finalize() honestly returns "incomplete"
  // with NO verify / cmr / PR (decision 3⑤ 不静默吞 + decision 4 止于-PR only when whole).
  const mergedNow = await currentMerged(familyBackend);
  if (!epic.children.every((c) => mergedNow.has(c.issue))) {
    return await finalize();
  }

  // ── already-shipped resume guard (online review r2, codex P1) ────────────────
  // If a prior invocation already ran the terminal 止于-PR family ship for the SAME
  // family HEAD (a complete `shipped` ledger entry with matching `familyHeadAfter`),
  // the family PR is open and covers the current base. Re-running the final barrier
  // would re-verify, re-cmr, and re-invoke the ship worker — a duplicate VERSION bump
  // / PR attempt. But an older shipped marker for a different head must NOT hide a
  // later live-base advance; that new head needs a fresh final barrier / ship.
  const preFinalLedger = await familyBackend.readFamilyLedger();
  const preFinalFamilyHead =
    familyHead ?? (await readCurrentFamilyHead(familyBackend, familyBase));
  const shippedRecord = familyShippedRecordForHead(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (shippedRecord !== undefined) {
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) =>
      ledgerMerged.has(c.issue)
        ? { issue: c.issue, status: "already_done" as const }
        : { issue: c.issue, status: "skipped" as const },
    );
    if (familyBackend.verifyFamilyShippedPr === undefined) {
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason:
          "family ledger contains a shipped marker but this backend cannot verify the PR still covers the current family HEAD",
        familyHeadAfter: preFinalFamilyHead,
      });
      return {
        status: "escalated",
        familyBase,
        familyHead: preFinalFamilyHead,
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead: preFinalFamilyHead,
          children,
          escalationReason:
            "family ledger contains a shipped marker but this backend cannot verify the PR still covers the current family HEAD",
        }),
        children,
      };
    }
    const shippedPr = await familyBackend.verifyFamilyShippedPr({
      pr: shippedRecord.pr,
      familyBase,
      expectedHead: preFinalFamilyHead!,
    });
    if (!shippedPr.ok) {
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: `family shipped marker no longer verifies: ${shippedPr.reason}`,
        familyHeadAfter: preFinalFamilyHead,
      });
      return {
        status: "escalated",
        familyBase,
        familyHead: preFinalFamilyHead,
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead: preFinalFamilyHead,
          children,
          escalationReason: `family shipped marker no longer verifies: ${shippedPr.reason}`,
        }),
        children,
      };
    }
    familyHead = preFinalFamilyHead;
    const alreadyDoneSummary: StopSummary = {
      reason: "already_done",
      summary: "family run already shipped for the current family HEAD",
      metadata: {
        heads: {
          actualFamilyHead: preFinalFamilyHead,
          reportedFamilyHead: shippedRecord.familyHeadAfter,
          verifiedCmrHead: preFinalFamilyHead,
          sources: {
            actualFamilyHead: "current family head",
            reportedFamilyHead: "shipped ledger row",
            verifiedCmrHead: "shipped ledger row",
          },
        },
      },
    };
    return {
      status: "success",
      familyBase,
      familyHead,
      stopSummary: alreadyDoneSummary,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  }
  if (
    hasUnboundLegacyShippedMarker(preFinalLedger) ||
    (preFinalFamilyHead === undefined && hasBoundShippedMarker(preFinalLedger))
  ) {
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) =>
      ledgerMerged.has(c.issue)
        ? { issue: c.issue, status: "merged" as const }
        : { issue: c.issue, status: "skipped" as const },
    );
    await recordFamilyEscalated(familyBackend, {
      escalationKind: "failure",
      phase: "final",
      reason:
        preFinalFamilyHead === undefined && hasBoundShippedMarker(preFinalLedger)
          ? "family ledger contains a shipped marker but current family HEAD could not be resolved"
          : "family ledger contains a legacy shipped marker without familyHeadAfter; cannot prove which family HEAD the prior PR covered",
      familyHeadAfter: preFinalFamilyHead,
    });
    return {
      status: "escalated",
      familyBase,
      familyHead: preFinalFamilyHead,
      stopSummary: familyStopSummary({
        status: "escalated",
        familyBase,
        familyHead: preFinalFamilyHead,
        children,
        escalationReason:
          preFinalFamilyHead === undefined && hasBoundShippedMarker(preFinalLedger)
            ? "family ledger contains a shipped marker but current family HEAD could not be resolved"
            : "family ledger contains a legacy shipped marker without familyHeadAfter; cannot prove which family HEAD the prior PR covered",
      }),
      children,
    };
  }

  // ── verify-cmr hook: end-of-run barrier (#293 no-op seam, #296 fills) ─────────
  // Decision 3⑤/⑥: after all waves merge, run the 全量 verify + the load-bearing
  // integrated cross-model cmr (catches 跨片接缝). #293 no-op; the call site is
  // wired now so #296 fills only the "final" hook body, not the spine.
  const finalVerify = await verifyCmr({
    phase: "final",
    familyBase,
    familyBackend,
    // #291 缺口 1: derive the LLM-resolved children from the durable ledger and
    // hand them to the final-phase integrated cmr 承重闸 (via runVerifyCmr →
    // IntegratedCmrRequest.llmResolvedChildren), so it sees which merges a machine
    // touched. The wave barrier is verify-only (no cmr), so only the final call
    // needs it; an empty list ⇒ the cmr request omits the field.
    llmResolvedChildren: await llmResolvedChildren(familyBackend),
    ...(() => {
      const priorKeys = pendingPriorCmrFindingIdentityKeys(preFinalLedger);
      return priorKeys.length > 0
        ? { priorCmrFindingIdentityKeys: priorKeys }
        : {};
    })(),
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    // #291 缺口 2: the abort-time head for a RED final verify's durable aborted entry.
    familyHeadAfter: familyHead,
    familyIssue: epic.issue,
    ...(declaredModuleContext !== undefined
      ? { moduleContext: declaredModuleContext }
      : {}),
  });
  if (!finalVerify.ok) {
    // #296's failing integrated cmr lands here. #293 no-op never trips it. The
    // result carries the merged children AND `status:"verify_failed"`/`failedPhase:
    // "final"` so a red final verify is OBSERVABLY distinct from success — the
    // caller / PR step must NOT ship it (decision 3⑤ "不静默吞"); the family base +
    // ledger are left for triage.
    return await finalize("final");
  }

  // Every barrier passed. finalize() derives "success" only if EVERY child
  // merged, else "incomplete" (a child failed / stayed blocked — not shippable).
  return await finalize();
}
