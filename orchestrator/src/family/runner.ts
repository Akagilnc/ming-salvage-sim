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
import { mintRunId } from "../runId.js";
import {
  applyRuntimeTightRoutePolicy,
  printableRouteLineup,
  resolveActiveModelRoute,
  routeSmokeFailure,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import type {
  Backend,
  EscalationAnswerPayload,
  LedgerEntry,
  PersistentLedgerEntry,
  StepId,
} from "../types.js";
import { escalateOf, isValidEscalation } from "../validate.js";
import { assertAcyclic, selectWave } from "./commander.js";
import {
  childEscalationAnswer,
  familyEscalationState,
  familyReviewLoopConvergedForHead,
  familyShippedRecordForReviewLoopResume,
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  hasBoundShippedMarker,
  hasUnboundLegacyShippedMarker,
  isMergedAccountingEntry,
  mergedSet,
  recordAdmissionSkipped,
  recordChildDecisionParked,
  recordFamilyEscalated,
  recordMerged,
  recordReviewLoopConverged,
  unansweredChildEscalations,
} from "./ledger.js";
import { mergeChild } from "./merger.js";
import { reconcileFamilyLedger } from "./reconcile.js";
import { convergenceHeadToRecord } from "../evidenceAdmissibility.js";
import {
  ensureFamilyPostMergeCleanup,
  runFamilyOnlineReviewLoop,
  runVerifyCmr,
} from "./verifyCmr.js";
import {
  familyAutoMergeIncomplete,
  isFamilyPrLiveMerged,
  runFamilyAutoMergeStage,
} from "./familyAutoMerge.js";
import { buildFamilyModuleContext } from "./moduleDeclaration.js";
import {
  decisionGateParkStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyChildEscalation,
  FamilyChildResult,
  FamilyLedgerEntry,
  FamilyRunInput,
  FamilyRunResult,
  FamilyRunStatus,
  IntegratedCmrPass,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

function filled(value: string | undefined): string | undefined {
  if (value == null) return undefined;
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
    reportedFamilyHead == null &&
    actualFamilyHead == null &&
    verifiedCmrHead == null
  ) {
    return undefined;
  }
  const sources: Record<string, string> = {};
  if (reportedFamilyHead != null) {
    sources.reportedFamilyHead = "FamilyRunResult.familyHead";
  }
  if (actualFamilyHead != null) {
    sources.actualFamilyHead =
      input.actualFamilyHeadSource ?? "family runner current head";
  }
  if (verifiedCmrHead != null) {
    sources.verifiedCmrHead = "latest cmr_passed ledger row";
  }
  return {
    heads: {
      ...(reportedFamilyHead != null ? { reportedFamilyHead } : {}),
      ...(actualFamilyHead != null ? { actualFamilyHead } : {}),
      ...(verifiedCmrHead != null ? { verifiedCmrHead } : {}),
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
  /**
   * B-class (#604 F2, ADR 0062 A/B分家): a HUMAN DECISION GATE parked this run
   * awaiting an answer (a child's own single-slice decision题). When true the
   * `escalated`-status summary carries the `decision_gate_park` reason instead of
   * the A-class `infra_failure` word — a park is answerable + resumable, not a
   * failure to repair.
   */
  readonly decisionGatePark?: boolean;
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
      metadata?.heads != null ||
      (input.admissionSkipped?.length ?? 0) > 0 ||
      (input.alreadyDone?.length ?? 0) > 0;
    return successStopSummary(
      hasMetadata
        ? {
            ...(metadata?.heads != null ? { heads: metadata.heads } : {}),
            ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
              ? { admissionSkipped: input.admissionSkipped }
              : {}),
            ...(input.alreadyDone != null && input.alreadyDone.length > 0
              ? { alreadyDone: input.alreadyDone }
              : {}),
          }
        : undefined,
    );
  }
  if (input.status === "verify_failed") {
    if (input.barrierStopSummary != null) return input.barrierStopSummary;
    return infraFailureStopSummary({
      summary: `family ${input.failedPhase ?? "unknown"} verify/cmr barrier failed`,
      repairHint: "inspect the family ledger aborted entry, repair the failing barrier, and rerun",
      ...(metadata?.heads != null ? { heads: metadata.heads } : {}),
    });
  }
  if (input.status === "incomplete") {
    const blocked = input.children
      .filter((child) => child.status !== "merged" && child.status !== "already_done")
      .map((child) => `#${child.issue}:${child.status}`)
      .join(", ");
    return {
      reason: "owning_issue_still_red",
      summary: `family run is incomplete; unmerged children: ${blocked}`,
      repairHint: "repair or complete the listed child slices and rerun the family",
    };
  }
  // B-class: a human decision gate parked the run (#604 F2). Answerable +
  // resumable — never the A-class `infra_failure` word.
  if (input.decisionGatePark === true) {
    return {
      reason: "decision_gate_park",
      summary: input.escalationReason ?? "family run parked on a decision gate",
      repairHint:
        "append an escalation_answered ledger row carrying the parked childIssue, then rerun the family to resume in place",
      ...(metadata !== undefined ? { metadata } : {}),
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
/**
 * Read a child's PARKED decision escalation off its single-slice RunResult (#604
 * slice 5). The caller has already checked `result.status==="escalate"`. This
 * distinguishes the DECISION bucket (a well-shaped Escalation on the escalated
 * agent step → answerable, parkable) from the FAILURE bucket (an
 * infra/retries-exhausted escalate with no valid Escalation → returns undefined,
 * so the caller keeps the CURRENT `"failed"` behaviour — A/B分家). The reason /
 * diagnosis come from the escalated agent step's Escalation payload; the sessionId
 * (for 原地 resume, ADR 0062) is read from the persisted child ledger by the
 * caller — the lean in-memory RunResult ledger carries no session id.
 *
 * NOTE: `escalationKindForHandoff` in runner.ts (single-slice) mirrors this exact
 * decision-vs-failure split (a valid Escalation ⇒ "decision", else "failure"); this
 * is the family-layer read of the same truth off the lean RunResult ledger.
 *
 * #604 correctness r5 (E2): the in-memory RunResult ledger now carries the escalated
 * agent step's `sessionId` (the runner records it on the in-memory entry, not only
 * the persisted one), so the parked escalation FORWARDS the real child session id
 * for 原地 resume. It is absent only when the provider surfaced no id.
 */
function readChildDecisionEscalation(
  ledger: ReadonlyArray<LedgerEntry>,
): FamilyChildEscalation | undefined {
  // The escalated agent step carries the Escalation payload (the S8 handoff entry
  // in the lean RunResult ledger carries no handoffStatus/escalationKind — those
  // live only on the PERSISTED ledger written via writeLedger).
  const agentEntry = [...ledger]
    .reverse()
    .find((e) => {
      const esc = escalateOf(e.output);
      return esc != null && isValidEscalation(esc);
    });
  const escalation = escalateOf(agentEntry?.output);
  if (escalation == null || !isValidEscalation(escalation)) return undefined;
  // #604 correctness r1 (P1-a): a RUNNER-synthesized failure escalate (malformed
  // reviewer output exhausted / retries exhausted — marked `synthesizedFailure`)
  // is a PROTOCOL FAILURE, not a worker-proactive decision. The child must keep
  // the A-class `"failed"` behaviour (return undefined), never be parked as a
  // B-class decision. Only a genuine worker-emitted escalate parks.
  if (escalation.synthesizedFailure === true) return undefined;
  return {
    reason: escalation.reason,
    diagnosis: escalation.diagnosis,
    escalationKind: "decision",
    ...(agentEntry?.sessionId !== undefined ? { sessionId: agentEntry.sessionId } : {}),
  };
}

/**
 * The escalated (last non-terminal) step in a child's parked single-slice ledger
 * (#604 slice 5) — the `forStep` a family-level answer must target so the child's
 * own `planResume` reopens THAT step in its recorded session.
 */
function escalatedChildStep(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    if (ledger[i]!.step !== "S8") return ledger[i]!.step;
  }
  return undefined;
}

async function runChild(
  child: ChildSlice,
  singleSliceBackend: Backend,
  parentIssue: number,
  familyBase: string,
  familyChildIssues: ReadonlySet<number>,
  /**
   * A family-level human answer to THIS child's parked decision escalation (#604
   * slice 5). When present, it is INJECTED into the child's own single-slice ledger
   * (as an `escalation_answered` row targeting the escalated step) BEFORE re-running
   * `runOrchestrator`, so the child's `planResume` reopens the paused step in its
   * recorded session (原地 resume). Absent ⇒ a normal fresh/continued child run.
   */
  escalationAnswer?: EscalationAnswerPayload,
): Promise<FamilyChildResult> {
  // ── #604 slice 5 resume: inject the answer into the child's single-slice ledger
  // so the reused runOrchestrator's planResume → resumeSession reopens the paused
  // step IN PLACE (原 sessionId), never from scratch. We only inject when the child
  // actually has parked residue (findResumeState returns a ledger) whose last
  // non-terminal step is the one to reopen.
  if (escalationAnswer !== undefined) {
    const resumeState = await singleSliceBackend.findResumeState(child.issue);
    const forStep =
      resumeState !== undefined ? escalatedChildStep(resumeState.ledger) : undefined;
    if (resumeState !== undefined && forStep !== undefined) {
      const answerEntry: PersistentLedgerEntry = {
        step: forStep,
        sessionId: `family-answer-${child.issue}`,
        prompt_hash: "family-answer",
        branchHEAD: resumeState.worktree.branch,
        ts: new Date().toISOString(),
        event: "escalation_answered",
        forStep,
        answer: escalationAnswer.answer,
        source: "human",
        ...(escalationAnswer.note !== undefined ? { note: escalationAnswer.note } : {}),
      } as PersistentLedgerEntry;
      await singleSliceBackend.writeLedger(answerEntry, resumeState.stateDir);
    } else {
      // #604 correctness r1 (P1-b): a human answered THIS child's decision gate,
      // but its parked resume state is MISSING (findResumeState returned undefined,
      // or no re-openable non-terminal step exists). We MUST NOT fall through to a
      // fresh `runOrchestrator` (that would re-run the child FROM SCRATCH, losing
      // committed progress and violating 原地-resume / never-from-scratch, ADR 0062).
      // Fail-closed: return `"failed"` (A-class incomplete) so a human repairs the
      // missing state and reruns — never a silent from-scratch run.
      return { issue: child.issue, status: "failed" };
    }
  }
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
  // #604 slice 5 (A/B分家): a child that PARKED on a product/design DECISION题
  // (`escalationKind:"decision"`) is `"escalated"`, NOT `"failed"` — an answerable
  // pause the family can resume IN PLACE. Only the decision bucket parks; a
  // `"failure"` escalate (infra / retries exhausted) and every other non-success
  // outcome keep the current `"failed"` behaviour below.
  if (result.status === "escalate") {
    const escalation = readChildDecisionEscalation(result.stepLedger);
    if (escalation !== undefined) {
      return { issue: child.issue, status: "escalated", escalation };
    }
  }
  // #293 thinnest: a non-success child does not merge (a failure escalate / error
  // stays failed). The spine records it honestly, not silently dropped.
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

/**
 * #603 — already_done / resume success is allowed only when the head has a
 * terminal+ok `post_merge_cleanup` ledger row (or cleanup re-enters successfully).
 * Returns an escalated FamilyRunResult when cleanup cannot complete; undefined
 * means the caller may report already_done.
 */
async function requirePostMergeCleanupForAlreadyDone(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId: string;
  readonly familyHeadAfter: string;
  readonly prUrl: string;
  readonly familyIssue: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
}): Promise<FamilyRunResult | undefined> {
  const ledger = await input.familyBackend.readFamilyLedger();
  if (
    familyPostMergeCleanupForHead(ledger, input.familyHeadAfter) !== undefined
  ) {
    return undefined;
  }
  if (familyPrMergedForHead(ledger, input.familyHeadAfter) === undefined) {
    return undefined;
  }
  const cleanup = await ensureFamilyPostMergeCleanup({
    familyBackend: input.familyBackend,
    familyBase: input.familyBase,
    runId: input.runId,
    familyHeadAfter: input.familyHeadAfter,
    prUrl: input.prUrl,
    familyIssue: input.familyIssue,
    resolvedRoute: input.resolvedRoute,
    recordAbortOnFailure: false,
  });
  if (cleanup.ok) return undefined;
  const reason =
    cleanup.reason ??
    "family post-merge cleanup did not reach a terminal success outcome";
  await recordFamilyEscalated(input.familyBackend, {
    escalationKind: "failure",
    phase: "final",
    reason,
    familyHeadAfter: input.familyHeadAfter,
  });
  return {
    status: "escalated",
    familyBase: input.familyBase,
    familyHead: input.familyHeadAfter,
    stopSummary: familyStopSummary({
      status: "escalated",
      familyBase: input.familyBase,
      familyHead: input.familyHeadAfter,
      children: input.children,
      escalationReason: reason,
    }),
    children: [...input.children],
    ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
      ? { admissionSkipped: input.admissionSkipped }
      : {}),
  };
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

export function pendingPriorCmrFindingIdentityKeysByPass(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  currentFamilyHead?: string,
): Partial<Record<IntegratedCmrPass, ReadonlyArray<string>>> {
  const keysByPass: Partial<Record<IntegratedCmrPass, string[]>> = {};
  const closedPasses = new Set<string>();
  const processedPasses = new Set<string>();
  // #604 correctness r1 (P1-e): passes marked processed ONLY by an empty
  // not_converged classified abort. An OLDER `cmr_fix_committed` for such a pass
  // still contributes its pending claimed-fixed keys (ADR 0030 closure); a pass in
  // `processedPasses` for any OTHER reason still blocks the fix-commit as before.
  const emptyAbortProcessedPasses = new Set<string>();
  const passesWithUnclosedFixCommits = new Set<string>();
  const unclassifiedAbortHeadByPass = new Map<string, string | undefined>();
  for (let index = ledger.length - 1; index >= 0; index--) {
    const entry = ledger[index]!;
    if (entry.status === "shipped") break;
    if (entry.status === "cmr_passed") {
      if (entry.cmrPass == null) break;
      closedPasses.add(entry.cmrPass);
      continue;
    }
    if (entry.status === "cmr_fix_committed") {
      const pass = entry.cmrPass;
      const keys = entry.blockingFindingIdentityKeys;
      // #604 correctness r1 (P1-e): a pass that is processed ONLY because of an
      // empty not_converged abort must NOT block this older fix-commit's pending
      // keys — they are still awaiting ADR 0030 closure. `processedPasses` for any
      // other reason (a real classified abort / cmr_reviewed) still blocks it.
      const blockedByProcessed =
        pass != null &&
        processedPasses.has(pass) &&
        !emptyAbortProcessedPasses.has(pass);
      if (
        pass == null ||
        closedPasses.has(pass) ||
        blockedByProcessed ||
        keys == null ||
        keys.length === 0
      ) {
        continue;
      }
      passesWithUnclosedFixCommits.add(pass);
      const existing = keysByPass[pass] ?? [];
      const seen = new Set(existing);
      const merged = [...existing];
      for (let keyIndex = keys.length - 1; keyIndex >= 0; keyIndex--) {
        const key = keys[keyIndex]!;
        if (seen.has(key)) continue;
        seen.add(key);
        merged.unshift(key);
      }
      keysByPass[pass] = merged;
      continue;
    }
    if (entry.status === "cmr_reviewed") {
      const pass = entry.cmrPass;
      const reviewedHead = filled(entry.familyHeadAfter);
      // #604 slice 3 / ADR 0062: the runner reads ONLY the thin envelope
      // (`blockingFindingIdentityKeys`) off a CMR row — never the finding content.
      const keys = entry.blockingFindingIdentityKeys;
      if (
        pass === undefined ||
        closedPasses.has(pass) ||
        processedPasses.has(pass)
      ) {
        continue;
      }
      if (passesWithUnclosedFixCommits.has(pass)) {
        continue;
      }
      const hasUnclassifiedAbort = unclassifiedAbortHeadByPass.has(pass);
      const abortHead = unclassifiedAbortHeadByPass.get(pass);
      if (
        hasUnclassifiedAbort &&
        (reviewedHead === undefined ||
          abortHead === undefined ||
          abortHead === reviewedHead)
      ) {
        continue;
      }
      processedPasses.add(pass);
      if (
        currentFamilyHead === undefined ||
        reviewedHead === undefined ||
        currentFamilyHead === reviewedHead ||
        keys == null ||
        keys.length === 0
      ) {
        continue;
      }
      keysByPass[pass] = [...keys];
      continue;
    }
    // #604 slice 3 / ADR 0062: an aborted row without a `blockingFindingIdentityKeys`
    // envelope is an UNCLASSIFIED abort (e.g. an infra failure) — it carries no CMR
    // blocking envelope. A not_converged abort carries `[]` (defined), so it stays
    // in the classified branch below and simply yields no keys.
    if (entry.status === "aborted" && entry.blockingFindingIdentityKeys == null) {
      const pass = entry.cmrPass;
      if (
        pass == null ||
        closedPasses.has(pass) ||
        processedPasses.has(pass)
      ) {
        continue;
      }
      if (!unclassifiedAbortHeadByPass.has(pass)) {
        unclassifiedAbortHeadByPass.set(pass, filled(entry.familyHeadAfter));
      }
      continue;
    }
    if (entry.status !== "aborted" || entry.blockingFindingIdentityKeys == null) {
      continue;
    }
    if (
      entry.cmrPass != null &&
      (closedPasses.has(entry.cmrPass) ||
        processedPasses.has(entry.cmrPass) ||
        unclassifiedAbortHeadByPass.has(entry.cmrPass))
    ) {
      continue;
    }
    const pass = entry.cmrPass;
    if (pass == null) continue;
    if (passesWithUnclosedFixCommits.has(pass)) {
      continue;
    }
    // #604 correctness r1 (P1-e): a not_converged sentinel abort carries an EMPTY
    // classified envelope (`blockingFindingIdentityKeys: []`). It yields no keys of
    // its own. It still marks the pass processed (its short-circuit semantics — an
    // older `cmr_reviewed` must NOT be revived as stale evidence past a
    // not_converged abort), but it is tracked as an EMPTY-ABORT processed pass so
    // it does NOT MASK an OLDER `cmr_fix_committed` row scanned later in this
    // newest-first loop. Those claimed-fixed keys are still pending ADR 0030
    // closure and must survive an empty not_converged abort — otherwise the next
    // fresh reviewer would no longer be told to cover them (silent DROP).
    if (entry.blockingFindingIdentityKeys.length === 0) {
      processedPasses.add(pass);
      emptyAbortProcessedPasses.add(pass);
      continue;
    }
    processedPasses.add(pass);
    const keys = keysByPass[pass] ?? [];
    const seen = new Set(keys);
    // #604 slice 2/3 / ADR 0062: pull EVERY blocking finding's identity key straight
    // off the thin envelope — no content classification is read.
    for (const identityKey of entry.blockingFindingIdentityKeys) {
      if (!seen.has(identityKey)) {
        seen.add(identityKey);
        keys.push(identityKey);
      }
    }
    keysByPass[pass] = keys;
  }
  return Object.fromEntries(
    Object.entries(keysByPass).map(([pass, values]) => [pass, values]),
  ) as Partial<Record<IntegratedCmrPass, ReadonlyArray<string>>>;
}

function latestAbortedStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  phase: VerifyCmrPhase | undefined,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "aborted" &&
      (phase === undefined || entry.phase === phase) &&
      entry.stopSummary != null
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

function isMaterialCmrStopSummary(stopSummary: StopSummary): boolean {
  if (stopSummary.reason !== "success") return true;
  const metadata = stopSummary.metadata;
  return (
    (metadata?.acceptedSuppressions?.length ?? 0) > 0 ||
    (metadata?.providerDegraded?.length ?? 0) > 0
  );
}

function latestSuccessfulFinalCmrStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "cmr_passed" &&
      entry.event === "cmr_passed" &&
      entry.phase === "final" &&
      entry.stopSummary != null &&
      isMaterialCmrStopSummary(entry.stopSummary)
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

function latestSuccessfulFinalShippedStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "shipped" &&
      entry.event === "shipped" &&
      entry.phase === "final" &&
      entry.stopSummary != null &&
      isMaterialCmrStopSummary(entry.stopSummary)
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
  const { familyBackend, singleSliceBackend, familyBase } = input;
  // A durable family sidecar is shared across restarts, so it needs an
  // invocation-scoped identity just like the single-slice runner.
  const runId = mintRunId();
  let modelRoute: ResolvedModelRoute;
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
  if (typeof singleSliceBackend.smokeModelRoute !== "function") {
    const reason =
      "route smoke executor is required before family dispatch; backend did not provide smokeModelRoute";
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: reason },
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint: "provide a real model×pipe smoke executor before dispatching family workers",
      }),
      children,
    };
  }
  let currentCliVersions: Readonly<Record<string, string | undefined>>;
  try {
    currentCliVersions = singleSliceBackend.currentCliVersions
      ? await singleSliceBackend.currentCliVersions(modelRoute)
      : {};
    modelRoute = await singleSliceBackend.smokeModelRoute(modelRoute, currentCliVersions);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: `route smoke failed: ${reason}` },
      stopSummary: infraFailureStopSummary({
        summary: `route smoke failed: ${reason}`,
        repairHint: "repair the selected model×pipe tool smoke before dispatching family workers",
      }),
      children,
    };
  }
  const smokeFailure = routeSmokeFailure(modelRoute, Date.now(), undefined, currentCliVersions);
  if (smokeFailure !== undefined) {
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: smokeFailure },
      stopSummary: infraFailureStopSummary({
        summary: smokeFailure,
        repairHint: "rerun the route smoke or repair the selected model×pipe",
      }),
      children,
    };
  }
  const activeRoutePolicy = { ...routePolicy, route: modelRoute };
  console.info(
    `[orchestrator:family] model route lineup\n${printableRouteLineup(activeRoutePolicy.route)}`,
  );
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
            status: ledgerMerged.has(child.issue) ? "already_done" : "skipped",
          })),
          escalationReason:
            typeof escalation.reason === "string" && escalation.reason.trim().length > 0
              ? escalation.reason
              : "family escalation is not answered",
          // #604 F2 / ADR 0062 A/B分家 (PR#643 R2): an UNANSWERED family-level
          // DECISION escalation is an answerable park, not an A-class repair
          // failure — carry `decision_gate_park`, mirroring the child-park path
          // (F8). A `failure`/missing-kind escalation stays `infra_failure`.
          decisionGatePark: escalation.escalationKind === "decision",
        }),
        children: input.epic.children.map((child) => ({
          issue: child.issue,
          status: ledgerMerged.has(child.issue) ? "already_done" : "skipped",
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
  // ── #604 slice 5: child decision-escalation re-entry ────────────────────────
  // Read the family ledger for children PARKED on a decision题 (a `child_decision_parked`
  // row). For each, look up whether a later `escalation_answered` row (bound to the
  // SAME childIssue) reopened it:
  //   - ANSWERED → the answer is fed into runChild, which injects it into the
  //     child's single-slice ledger so its own planResume → resumeSession reopens
  //     the paused step IN PLACE (原 sessionId, 退出-重入 per ADR 0062).
  //   - UNANSWERED → the family stays PAUSED: return `status:"escalated"` before the
  //     wave loop rather than fruitlessly re-running the parked child (which would
  //     just re-escalate). Supports multiple children parked + answered separately.
  const parkedChildAnswers = new Map<number, EscalationAnswerPayload>();
  {
    // `unansweredChildEscalations` returns ONLY the still-unanswered parked
    // children. To also resume the ANSWERED ones we look up each parked child's
    // answer directly: answered → feed it into runChild (resume in place);
    // unanswered → keep the family paused (return escalated). A parked child is one
    // with a `child_decision_parked` row; iterate them by scanning the ledger for that.
    const parkedIssues = new Set<number>();
    for (const entry of initialFamilyLedger) {
      if (
        entry.status === "child_decision_parked" &&
        entry.event === "child_decision_parked" &&
        typeof entry.childIssue === "number"
      ) {
        parkedIssues.add(entry.childIssue);
      }
    }
    const unanswered: (FamilyLedgerEntry & { readonly childIssue: number })[] = [];
    const stillUnanswered = new Set(
      unansweredChildEscalations(initialFamilyLedger).map((e) => e.childIssue),
    );
    for (const childIssue of parkedIssues) {
      if (stillUnanswered.has(childIssue)) {
        const row = [...initialFamilyLedger]
          .reverse()
          .find(
            (e) =>
              e.status === "child_decision_parked" &&
              e.event === "child_decision_parked" &&
              e.childIssue === childIssue,
          ) as (FamilyLedgerEntry & { readonly childIssue: number }) | undefined;
        if (row !== undefined) unanswered.push(row);
        continue;
      }
      const answer = childEscalationAnswer(initialFamilyLedger, childIssue);
      if (answer !== undefined) parkedChildAnswers.set(childIssue, answer);
    }
    if (unanswered.length > 0) {
      const ledgerMerged = mergedSet(initialFamilyLedger);
      const first = unanswered[0]!;
      // #604 F8: an UNANSWERED parked child re-entered before the wave loop must
      // map to `"escalated"` (its decision-gate park state), NOT `"skipped"`. The
      // wave-loop parking path finalizes these via `finalizeDecisionPark` →
      // `"escalated"`; the early-exit re-entry path must stay consistent, else the
      // driver sees the parked child as skipped and mis-reads the run. Carry the
      // escalation payload read from the `child_decision_parked` ledger row so the
      // driver has the same reason/diagnosis/sessionId either path.
      const parkedByIssue = new Map<number, FamilyChildEscalation>();
      for (const row of unanswered) {
        parkedByIssue.set(row.childIssue, {
          reason: row.reason ?? "(no reason recorded)",
          diagnosis:
            row.diagnosis ??
            "Append an escalation_answered ledger row carrying this childIssue to reopen the parked child.",
          escalationKind: "decision",
          ...(typeof row.sessionId === "string" && row.sessionId.length > 0
            ? { sessionId: row.sessionId }
            : {}),
        });
      }
      const children: FamilyChildResult[] = epic.children.map((c) => {
        if (ledgerMerged.has(c.issue)) {
          return { issue: c.issue, status: "already_done" as const };
        }
        const escalation = parkedByIssue.get(c.issue);
        if (escalation !== undefined) {
          return { issue: c.issue, status: "escalated" as const, escalation };
        }
        return { issue: c.issue, status: "skipped" as const };
      });
      const escalationReason = `child #${first.childIssue} decision gate is not answered: ${first.reason ?? "(no reason recorded)"}`;
      return {
        status: "escalated",
        familyBase,
        ...(typeof first.familyHeadAfter === "string" && first.familyHeadAfter.trim().length > 0
          ? { familyHead: first.familyHeadAfter }
          : {}),
        escalation: {
          reason: escalationReason,
          diagnosis:
            first.diagnosis ??
            "Append an escalation_answered ledger row carrying this childIssue to reopen the parked child.",
        },
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          ...(typeof first.familyHeadAfter === "string" && first.familyHeadAfter.trim().length > 0
            ? { familyHead: first.familyHeadAfter }
            : {}),
          children,
          escalationReason,
          decisionGatePark: true,
        }),
        children,
      };
    }
  }
  const moduleContext = buildFamilyModuleContext({
    childModules: epic.children.map((child) => child.moduleDeclaration),
    familyModule: epic.moduleDeclaration,
    runOptionModule: input.moduleDeclaration,
    undevelopedModules: input.undevelopedModules,
    acceptedSuppressionSources: input.acceptedSuppressionSources,
  });
  const declaredModuleContext =
    moduleContext.currentModules.length > 0 ||
    moduleContext.childModules.length > 0 ||
    (moduleContext.undevelopedModules?.length ?? 0) > 0 ||
    (moduleContext.acceptedSuppressionSources?.length ?? 0) > 0
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
  //     invocation — #298's resume truth), it is `"already_done"` (per the
  //     FamilyChildStatus contract: "merged" ⇔ merged this invocation;
  //     "already_done" ⇔ an earlier run's ledger truth), NOT `"skipped"`. Only a
  //     child absent from BOTH this run's results AND the
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
    barrierLedgerStartIndex = 0,
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
        ? (latestAbortedStopSummary(
            familyLedger,
            verifyFailedPhase,
            barrierLedgerStartIndex,
          ) ??
          latestAbortedStopSummary(familyLedger, undefined, barrierLedgerStartIndex))
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
    const materialSuccessStopSummary =
      status === "success"
        ? (latestSuccessfulFinalShippedStopSummary(
            familyLedger,
            barrierLedgerStartIndex,
          ) ??
          latestSuccessfulFinalCmrStopSummary(familyLedger, barrierLedgerStartIndex))
        : undefined;
    const resultStopSummary =
      materialSuccessStopSummary !== undefined
        ? {
            ...materialSuccessStopSummary,
            metadata: {
              ...(materialSuccessStopSummary.metadata ?? {}),
              ...(computedStopSummary.metadata ?? {}),
            },
          }
        : computedStopSummary;
    return {
      status,
      ...(verifyFailedPhase !== undefined ? { failedPhase: verifyFailedPhase } : {}),
      familyBase,
      familyHead,
      stopSummary: allChildrenAlreadyDone
        ? {
            ...resultStopSummary,
            reason: "already_done",
            summary: "family resume found every child already merged and skipped rerun",
          }
        : resultStopSummary,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  };

  // #604 slice 5: build the family result when a CHILD decision escalation parked
  // the run. Every epic child gets a record (the parked child carries its
  // `escalation`; already-merged children in `recorded` keep their status; the rest
  // are `"skipped"`). The family status is `"escalated"` (the answerable pause), NOT
  // verify_failed / incomplete.
  const finalizeDecisionPark = async (
    parked: FamilyChildResult & { escalation: FamilyChildEscalation },
    recordedResults: ReadonlyArray<FamilyChildResult>,
  ): Promise<FamilyRunResult> => {
    const recorded = new Map(recordedResults.map((c) => [c.issue, c]));
    // LEDGER-AWARE (不静默吞, runner.ts ~958-968): a child MERGED in a prior
    // invocation is skipped by `selectWave`, so it is absent from this run's
    // `recordedResults`. It must report "already_done": the durable ledger truth
    // is present, but this invocation did not merge it. It must not be "skipped"
    // — mirroring the early-exit park path (~900) and finalize().
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) => {
      const rec = recorded.get(c.issue);
      if (rec !== undefined) return rec;
      if (ledgerMerged.has(c.issue)) return { issue: c.issue, status: "already_done" as const };
      return { issue: c.issue, status: "skipped" as const };
    });
    const escalationReason = `child #${parked.issue} escalated a decision: ${parked.escalation.reason}`;
    return {
      status: "escalated",
      familyBase,
      familyHead,
      escalation: {
        reason: escalationReason,
        diagnosis: parked.escalation.diagnosis,
      },
      stopSummary: familyStopSummary({
        status: "escalated",
        familyBase,
        familyHead,
        children,
        escalationReason,
        decisionGatePark: true,
      }),
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
          ? { issue: c.issue, status: "already_done" as const }
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
          // #604 slice 5: a parked child that a human answered resumes IN PLACE.
          parkedChildAnswers.get(child.issue),
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
          modelRoute: activeRoutePolicy.route,
          runId,
        });
        if (mergeResult.escalation !== undefined) {
          familyHead = mergeResult.familyHead;
          childResults.push({ issue: r.issue, status: "failed", branch: r.branch });
          const ledgerMerged = await currentMerged(familyBackend);
          const children = epic.children.map((child) => {
            const recorded = childResults.find((entry) => entry.issue === child.issue);
            if (recorded !== undefined) return recorded;
            return ledgerMerged.has(child.issue)
              ? { issue: child.issue, status: "already_done" as const }
              : { issue: child.issue, status: "skipped" as const };
          });
          const escalation = mergeResult.escalation;
          const stopSummary = familyStopSummary({
            status: "escalated",
            familyBase,
            familyHead,
            children,
            escalationReason: escalation.reason,
          });
          await familyBackend.escalateFamily?.({
            ...escalation,
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
            stopSummary,
            escalationKind: "decision",
            phase: "wave",
          });
          return {
            status: "escalated" as const,
            familyBase,
            familyHead,
            escalation: {
              reason: escalation.reason,
              diagnosis: escalation.diagnosis ?? escalation.reason,
            },
            stopSummary,
            children,
          };
        }
        if (mergeResult.conflicted === true) {
          // A merger step that exhausted its bounded mechanical re-dispatch is
          // a family-level escalation boundary, not an uncaught run exception.
          // The merge result is intentionally not ledger-recorded by merger.ts;
          // preserve the Git-observed head and stop before scheduling another
          // wave on an unresolved MERGE_HEAD/conflict state.
          familyHead = mergeResult.familyHead;
          childResults.push({ issue: r.issue, status: "failed", branch: r.branch });
          const ledgerMerged = await currentMerged(familyBackend);
          const children = epic.children.map((child) => {
            const recorded = childResults.find((entry) => entry.issue === child.issue);
            if (recorded !== undefined) return recorded;
            return ledgerMerged.has(child.issue)
              ? { issue: child.issue, status: "already_done" as const }
              : { issue: child.issue, status: "skipped" as const };
          });
          const escalationReason =
            `merger step for child #${r.issue} exhausted bounded still-conflicted retries`;
          const stopSummary = familyStopSummary({
            status: "escalated",
            familyBase,
            familyHead,
            children,
            escalationReason,
          });
          await familyBackend.escalateFamily?.({
            reason: escalationReason,
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
            stopSummary,
            escalationKind: "failure",
            phase: "wave",
          });
          return {
            status: "escalated" as const,
            familyBase,
            familyHead,
            escalation: {
              reason: escalationReason,
              diagnosis:
                "Git still reports an unresolved merge after the bounded merger-step re-dispatch; repair the conflict and rerun the family.",
            },
            stopSummary,
            children,
          };
        }
        familyHead = mergeResult.familyHead;
        childResults.push({ issue: r.issue, status: "merged", branch: r.branch });
      } else {
        childResults.push({
          issue: r.issue,
          status: r.status,
          branch: r.branch,
          ...(r.escalation !== undefined ? { escalation: r.escalation } : {}),
        });
      }
    }

    // ── #604 slice 5: a CHILD decision escalation PARKS the family (stop-wave) ───
    // A child that returned `"escalated"` hit a product/design题. Record an
    // INDEPENDENT `child_decision_parked` ledger row (bound to childIssue, carrying the
    // child's sessionId for 原地 resume) and STOP: do NOT run the wave barrier or
    // select a next wave (sub-decision ②). The `"ran"` siblings this wave already
    // merged above stay durable; the un-answered child pauses the whole family
    // until a later `escalation_answered` row reopens it (退出-重入, ADR 0062). The
    // failure bucket never reaches here — runChild returned `"failed"` for it.
    const escalatedChildren = ran.filter(
      (r): r is FamilyChildResult & { escalation: FamilyChildEscalation } =>
        r.status === "escalated" && r.escalation !== undefined,
    );
    if (escalatedChildren.length > 0) {
      // #604 correctness r1 (P1-a ②): A-class failure优先于 B-class decision park.
      // A wave can carry BOTH a real `failed` child (infra/protocol failure — the
      // A-class incomplete/failure outcome) AND a decision-escalated child. The
      // old code parked (B-class) as soon as ANY decision-escalated child existed,
      // silently MASKING the real failure behind an answerable park. If this wave
      // produced a genuine failure, do NOT park: fall through to the honest
      // `incomplete` finalize (the failed child is never merged, the run is not
      // shippable) rather than a `decision_gate_park` that hides it.
      const hasRealFailure = ran.some((r) => r.status === "failed");
      if (!hasRealFailure) {
        for (const child of escalatedChildren) {
          await recordChildDecisionParked(familyBackend, {
            childIssue: child.issue,
            reason: child.escalation.reason,
            diagnosis: child.escalation.diagnosis,
            ...(child.escalation.sessionId !== undefined
              ? { sessionId: child.escalation.sessionId }
              : {}),
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
          });
        }
        return await finalizeDecisionPark(escalatedChildren[0]!, childResults);
      }
      // A real failure is present: finalize honestly as incomplete (A-class). The
      // escalated child's payload is preserved in `childResults` (recorded above
      // via the else branch of the merge loop), so the driver still sees it.
      return await finalize();
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
      runId,
      modelRoute: activeRoutePolicy.route,
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

  // ── already-converged resume guard (#596) ───────────────────────────────────
  // If a prior invocation already ran the full final barrier (verify → cmr →
  // ship → review loop) for the SAME family HEAD, a complete
  // `review_loop_converged` ledger entry exists. Re-running the final barrier
  // would re-verify, re-cmr, re-ship, and re-loop — duplicating work. An older
  // converged marker for a different head must NOT hide a later live-base
  // advance; that new head needs a fresh final barrier.
  const preFinalLedger = await familyBackend.readFamilyLedger();
  const preFinalLedgerLength = preFinalLedger.length;
  const preFinalFamilyHead =
    familyHead ?? (await readCurrentFamilyHead(familyBackend, familyBase));
  const convergedRecord = familyReviewLoopConvergedForHead(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (convergedRecord != null) {
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) =>
      ledgerMerged.has(c.issue)
        ? { issue: c.issue, status: "already_done" as const }
        : { issue: c.issue, status: "skipped" as const },
    );
    if (familyBackend.verifyFamilyShippedPr == null) {
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason:
          "family ledger contains a review_loop_converged marker but this backend cannot verify the PR still covers the current family HEAD",
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
            "family ledger contains a review_loop_converged marker but this backend cannot verify the PR still covers the current family HEAD",
        }),
        children,
      };
    }

    const priorPrMerged = familyPrMergedForHead(preFinalLedger, preFinalFamilyHead);
    if (priorPrMerged !== undefined) {
      familyHead = preFinalFamilyHead;
      const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
        familyBackend,
        familyBase,
        runId,
        familyHeadAfter: preFinalFamilyHead!,
        prUrl: priorPrMerged.pr,
        familyIssue: epic.issue,
        resolvedRoute: activeRoutePolicy.route,
        children,
        ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
          ? { admissionSkipped: epic.admissionSkipped }
          : {}),
      });
      if (cleanupBlocked !== undefined) return cleanupBlocked;
      const convergedVerifiedCmrHead =
        convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
        preFinalFamilyHead;
      const alreadyDoneSummary: StopSummary = {
        reason: "already_done",
        summary: "family run already converged for the current family HEAD",
        metadata: {
          heads: {
            actualFamilyHead: preFinalFamilyHead,
            reportedFamilyHead: convergedRecord.familyHeadAfter,
            verifiedCmrHead: convergedVerifiedCmrHead,
            sources: {
              actualFamilyHead: "current family head",
              reportedFamilyHead: "review_loop_converged ledger row",
              verifiedCmrHead:
                typeof convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ===
                "string"
                  ? "review_loop_converged ledger stop summary"
                  : "review_loop_converged ledger row",
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
        ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
          ? { admissionSkipped: epic.admissionSkipped }
          : {}),
      };
    }

    if (
      isFamilyPrLiveMerged(convergedRecord.pr) &&
      preFinalFamilyHead !== undefined
    ) {
      const mergedBackfill = await runFamilyAutoMergeStage({
        familyBackend,
        familyBase,
        convergedHeadOid: preFinalFamilyHead,
        prUrl: convergedRecord.pr,
      });
      if (!familyAutoMergeIncomplete(mergedBackfill)) {
        familyHead = preFinalFamilyHead;
        const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
          familyBackend,
          familyBase,
          runId,
          familyHeadAfter: preFinalFamilyHead,
          prUrl: convergedRecord.pr,
          familyIssue: epic.issue,
        resolvedRoute: activeRoutePolicy.route,
          children,
          ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        });
        if (cleanupBlocked !== undefined) return cleanupBlocked;
        const convergedVerifiedCmrHead =
          convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
          preFinalFamilyHead;
        const alreadyDoneSummary: StopSummary = {
          reason: "already_done",
          summary: "family run already converged for the current family HEAD",
          metadata: {
            heads: {
              actualFamilyHead: preFinalFamilyHead,
              reportedFamilyHead: convergedRecord.familyHeadAfter,
              verifiedCmrHead: convergedVerifiedCmrHead,
              sources: {
                actualFamilyHead: "current family head",
                reportedFamilyHead: "review_loop_converged ledger row",
                verifiedCmrHead:
                  typeof convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ===
                  "string"
                    ? "review_loop_converged ledger stop summary"
                    : "review_loop_converged ledger row",
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
          ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        };
      }
      const stopSummary =
        mergedBackfill.stopSummary ??
        decisionGateParkStopSummary({
          summary: `family auto-merge did not complete (${mergedBackfill.terminalState})`,
          repairHint:
            "resolve merge blockers or answer the decision gate, then re-feed the family run",
        });
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: stopSummary.summary,
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
          escalationReason: stopSummary.summary,
        }),
        children,
      };
    }

    const shippedPr = await familyBackend.verifyFamilyShippedPr({
      pr: convergedRecord.pr,
      familyBase,
      expectedHead: preFinalFamilyHead!,
    });
    if (!shippedPr.ok) {
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: `family review_loop_converged marker no longer verifies: ${shippedPr.reason}`,
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
          escalationReason: `family review_loop_converged marker no longer verifies: ${shippedPr.reason}`,
        }),
        children,
      };
    }

    const autoMerge = await runFamilyAutoMergeStage({
      familyBackend,
      familyBase,
      convergedHeadOid: preFinalFamilyHead!,
      prUrl: convergedRecord.pr,
    });
    if (familyAutoMergeIncomplete(autoMerge)) {
      const stopSummary =
        autoMerge.stopSummary ??
        decisionGateParkStopSummary({
          summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
          repairHint:
            "resolve merge blockers or answer the decision gate, then re-feed the family run",
        });
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: stopSummary.summary,
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
          escalationReason: stopSummary.summary,
        }),
        children,
      };
    }

    familyHead = preFinalFamilyHead;
    const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
      familyBackend,
      familyBase,
      runId,
      familyHeadAfter: preFinalFamilyHead!,
      prUrl: convergedRecord.pr,
      familyIssue: epic.issue,
      resolvedRoute: activeRoutePolicy.route,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (cleanupBlocked !== undefined) return cleanupBlocked;
    const convergedVerifiedCmrHead =
      convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
      preFinalFamilyHead;
    const alreadyDoneSummary: StopSummary = {
      reason: "already_done",
      summary: "family run already converged for the current family HEAD",
      metadata: {
        heads: {
          actualFamilyHead: preFinalFamilyHead,
          reportedFamilyHead: convergedRecord.familyHeadAfter,
          verifiedCmrHead: convergedVerifiedCmrHead,
          sources: {
            actualFamilyHead: "current family head",
            reportedFamilyHead: "review_loop_converged ledger row",
            verifiedCmrHead:
              convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead != null
                ? "review_loop_converged ledger stop summary"
                : "review_loop_converged ledger row",
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

  // ── #596 shipped-only resume: continues into review-loop (F1) ─────────────────
  // Per AC: `shipped` means "PR opened, review-loop pending". A ledger with ONLY
  // the intermediate shipped marker (bound to live head) must "continue into the
  // review-loop" rather than re-verify/re-cmr/re-ship. In this skeleton the
  // review-loop segment is the stub write of `review_loop_converged`.
  // This also closes the post-ship crash window (shipped written, converged not
  // yet) without duplicate PR. (Ruled against AC text; re-open PR cannot satisfy
  // "continues into review-loop" clause — we must resume *from* the shipped state
  // by writing the terminal marker.)
  const shippedRecord = familyShippedRecordForReviewLoopResume(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (shippedRecord != null) {
    if (familyBackend.verifyFamilyShippedPr == null) {
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason:
          "family ledger contains a shipped marker but this backend cannot verify the PR still covers the current family HEAD",
        familyHeadAfter: preFinalFamilyHead,
      });
      const ledgerMerged = await currentMerged(familyBackend);
      const children: FamilyChildResult[] = epic.children.map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
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
      const ledgerMerged = await currentMerged(familyBackend);
      const children: FamilyChildResult[] = epic.children.map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
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

    // #600: continue into the live online review-loop stage (not a stub marker).
    const reviewLoop = await runFamilyOnlineReviewLoop({
      familyBackend,
      familyBase,
      runId,
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
      ship: {
        kind: "ship",
        branch: familyBase,
        pr: shippedRecord.pr,
        prHead: preFinalFamilyHead,
        status: "pr_opened",
      },
    });
    if (!reviewLoop.ok) {
      const postReviewLoopFamilyHead =
        (await readCurrentFamilyHead(familyBackend, familyBase)) ??
        preFinalFamilyHead;
      const escalationFamilyHead =
        convergenceHeadToRecord({
          shipHead: shippedRecord.familyHeadAfter,
          postFixHead:
            postReviewLoopFamilyHead !== shippedRecord.familyHeadAfter
              ? postReviewLoopFamilyHead
              : undefined,
        }) ?? postReviewLoopFamilyHead;
      const escalationReason =
        reviewLoop.stopSummary?.summary ??
        (reviewLoop.terminalState === "round_budget_exhausted"
          ? "family online review loop exhausted the 3-round budget during resume"
          : reviewLoop.terminalState === "contract_drift"
            ? "family online review verify worker moved HEAD during resume"
            : "family online review loop did not converge during resume");
      // #744: a true human park is answerable + re-feedable (escalationKind
      // "decision"); hard-writing "failure" made re-feed impossible.
      // R1: terminalState "decision_gate_raised" is overloaded — onlineReviewLoop
      // returns it for both B-class parks (stopSummary.reason decision_gate_park)
      // and A-class infra failures (stopSummary.reason infra_failure). Key
      // escalationKind off verifiable park semantics (StopSummary reason), not
      // terminalState alone. decision_gate_raised + infra_failure stays failure.
      const isDecisionGatePark =
        reviewLoop.stopSummary?.reason === "decision_gate_park";
      const ledgerMerged = await currentMerged(familyBackend);
      const children: FamilyChildResult[] = epic.children.map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
      const stopSummary =
        reviewLoop.stopSummary ??
        familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead: escalationFamilyHead ?? preFinalFamilyHead,
          children,
          escalationReason,
          decisionGatePark: isDecisionGatePark,
        });
      await recordFamilyEscalated(familyBackend, {
        escalationKind: isDecisionGatePark ? "decision" : "failure",
        phase: "final",
        reason: escalationReason,
        familyHeadAfter: escalationFamilyHead,
        stopSummary,
      });
      return {
        status: "escalated",
        familyBase,
        familyHead: escalationFamilyHead ?? preFinalFamilyHead,
        stopSummary,
        children,
      };
    }
    const postReviewLoopFamilyHead =
      (await readCurrentFamilyHead(familyBackend, familyBase)) ??
      preFinalFamilyHead;
    const convergedFamilyHead =
      convergenceHeadToRecord({
        shipHead: shippedRecord.familyHeadAfter,
        postFixHead:
          postReviewLoopFamilyHead !== undefined &&
          postReviewLoopFamilyHead !== shippedRecord.familyHeadAfter
            ? postReviewLoopFamilyHead
            : undefined,
      }) ??
      postReviewLoopFamilyHead ??
      shippedRecord.familyHeadAfter;
    await recordReviewLoopConverged(familyBackend, {
      pr: shippedRecord.pr,
      familyHeadAfter: convergedFamilyHead,
      ...(shippedRecord.stopSummary != null
        ? { stopSummary: shippedRecord.stopSummary }
        : {}),
    });

    const postConvergedLedger = await familyBackend.readFamilyLedger();
    const priorPrMerged = familyPrMergedForHead(
      postConvergedLedger,
      convergedFamilyHead,
    );
    if (priorPrMerged === undefined) {
      const autoMerge = await runFamilyAutoMergeStage({
        familyBackend,
        familyBase,
        convergedHeadOid: convergedFamilyHead,
        prUrl: shippedRecord.pr,
      });
      if (familyAutoMergeIncomplete(autoMerge)) {
        const stopSummary =
          autoMerge.stopSummary ??
          decisionGateParkStopSummary({
            summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
            repairHint:
              "resolve merge blockers or answer the decision gate, then re-feed the family run",
          });
        await recordFamilyEscalated(familyBackend, {
          escalationKind: "failure",
          phase: "final",
          reason: stopSummary.summary,
          familyHeadAfter: convergedFamilyHead,
        });
        const ledgerMergedAfterEscalation = await currentMerged(familyBackend);
        const childrenAfterEscalation: FamilyChildResult[] = epic.children.map((c) =>
          ledgerMergedAfterEscalation.has(c.issue)
            ? { issue: c.issue, status: "already_done" as const }
            : { issue: c.issue, status: "skipped" as const },
        );
        return {
          status: "escalated",
          familyBase,
          familyHead: convergedFamilyHead,
          stopSummary: familyStopSummary({
            status: "escalated",
            familyBase,
            familyHead: convergedFamilyHead,
            children: childrenAfterEscalation,
            escalationReason: stopSummary.summary,
          }),
          children: childrenAfterEscalation,
        };
      }
    }

    familyHead = postReviewLoopFamilyHead;
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) =>
      ledgerMerged.has(c.issue)
        ? { issue: c.issue, status: "already_done" as const }
        : { issue: c.issue, status: "skipped" as const },
    );
    const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
      familyBackend,
      familyBase,
      runId,
      familyHeadAfter: convergedFamilyHead,
      prUrl: shippedRecord.pr,
      familyIssue: epic.issue,
      resolvedRoute: activeRoutePolicy.route,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (cleanupBlocked !== undefined) return cleanupBlocked;
    const shippedVerifiedCmrHead =
      shippedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
      preFinalFamilyHead;
    const alreadyDoneSummary: StopSummary = {
      reason: "already_done",
      summary: "family review-loop converged during resume for the current family HEAD",
      metadata: {
        heads: {
          actualFamilyHead: postReviewLoopFamilyHead,
          reportedFamilyHead: convergedFamilyHead,
          verifiedCmrHead: shippedVerifiedCmrHead,
          sources: {
            actualFamilyHead: "current family head",
            reportedFamilyHead: "review_loop_converged ledger row",
            verifiedCmrHead:
              shippedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead != null
                ? "shipped ledger stop summary"
                : "shipped ledger row",
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
        ? { issue: c.issue, status: "already_done" as const }
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
    runId,
    modelRoute: activeRoutePolicy.route,
    // #291 缺口 1: derive the LLM-resolved children from the durable ledger and
    // hand them to the final-phase integrated cmr 承重闸 (via runVerifyCmr →
    // IntegratedCmrRequest.llmResolvedChildren), so it sees which merges a machine
    // touched. The wave barrier is verify-only (no cmr), so only the final call
    // needs it; an empty list ⇒ the cmr request omits the field.
    llmResolvedChildren: await llmResolvedChildren(familyBackend),
    ...(() => {
      const priorKeysByPass = pendingPriorCmrFindingIdentityKeysByPass(
        preFinalLedger,
        preFinalFamilyHead,
      );
      return Object.keys(priorKeysByPass).length > 0
        ? { priorCmrFindingIdentityKeysByPass: priorKeysByPass }
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
    return await finalize("final", preFinalLedgerLength);
  }

  // Every barrier passed. finalize() derives "success" only if EVERY child
  // merged, else "incomplete" (a child failed / stayed blocked — not shippable).
  return await finalize(undefined, preFinalLedgerLength);
}
