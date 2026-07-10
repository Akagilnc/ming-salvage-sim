// @ming/orchestrator — public surface (#244).
// The runner-driven step machine (ADR 0018), its Backend seam, route()
// decision function, and domain types. Slice #247 wires the happy path;
// later slices (#248–#256) layer on these seams.
export { runOrchestrator } from "./runner.js";
export { route } from "./route.js";
export type { RouteContext, RouteDecision } from "./route.js";
export {
  contractDriftStopSummary,
  findingDescriptor,
  infraFailureStopSummary,
  providerDegradedStopSummary,
  stopReasonForFindingDisposition,
  stopSummaryFromFindingDispositionEvidence,
  successStopSummary,
} from "./stopSummary.js";
export type {
  AcceptedSuppressionSummary,
  FindingDescriptor,
  HeadFreshnessSummary,
  ProviderDegradationSummary,
  ShipFailureSummary,
  StopReason,
  StopSummary,
  StopSummaryMetadata,
} from "./stopSummary.js";

// ── unified worker-dispatch seam (ADR 0026 / PRD #330, #331) ────────────────
export {
  dispatchWorker,
  dispatchWorkerWithMonitor,
  legacyDispatchWorker,
  workerResultToStep,
  stepSpecToWorkerSpec,
  shipWorkerSpec,
} from "./dispatchWorker.js";
export type { DispatchWorkerWithMonitorOutcome } from "./dispatchWorker.js";
export {
  collectPidTree,
  dispatchMonitoredCliWorker,
  hasCompletionSignalInLog,
  instanceMatchesHandle,
  isWorkerAlive,
  isWorkerIdle,
  killWorkerTree,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  readProcessInstanceId,
  validateMonitorHandle,
} from "./workerMonitor.js";
export type {
  KillWorkerTreeResult,
  LogActivitySnapshot,
  MonitoredCliDispatchInput,
  MonitoredCliDispatchResult,
  WorkerMonitorDeps,
} from "./workerMonitor.js";
export {
  dispatchFamilyWorker,
  legacyDispatchFamilyWorker,
  cmrWorkerSpec,
  familyShipWorkerSpec,
} from "./family/dispatchFamilyWorker.js";

// ── family integration layer (ADR 0022, #293) ──────────────────────────────
// The four independent extension modules + the spine that only CALLS them.
export { runFamily } from "./family/runner.js";
// The production family driver (#291 Unit B): the end-to-end assembly entry point.
export {
  runFamilyDriver,
  readFamilyEpic,
  buildFamilyEpic,
  parseSubIssueAdmission,
  parseSubIssueNumbers,
  cutFamilyBase,
} from "./familyDriver.js";
export type { FamilyDriverOptions, Sh, SubIssueAdmission } from "./familyDriver.js";
export { selectWave } from "./family/commander.js";
export { mergeChild } from "./family/merger.js";
export { recordMerged, recordAborted, mergedSet, recordPrMerged, familyPrMergedForHead } from "./family/ledger.js";
export type { MergedRecord, AbortedRecord, PrMergedRecord } from "./family/ledger.js";
export {
  runAutoMergeStage,
  assessMergeReadiness,
  isPrMergedMarker,
} from "./autoMerge.js";
export { reconcileFamilyLedger } from "./family/reconcile.js";
export { runVerifyCmr } from "./family/verifyCmr.js";
export type {
  VerifyCmrInput,
  VerifyCmrPhase,
  VerifyCmrResult,
} from "./family/verifyCmr.js";
export type {
  ChildSlice,
  ConflictResolveRequest,
  FamilyBackend,
  FamilyChildResult,
  FamilyChildStatus,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyRunInput,
  FamilyRunResult,
  FamilyRunStatus,
  MergeRequest,
  MergeResult,
  ReconcileGit,
  ReconcilePlan,
  // #296 verify-cmr seam I/O (ADR 0022 decision 3④/⑤/⑥/4).
  FamilyVerifyRequest,
  FamilyVerifyResult,
  FamilyVerifyErrorPackage,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  FamilyAbortedEvent,
  FamilyEscalation,
} from "./family/types.js";
export type {
  Backend,
  ContinueFixingEvent,
  CoderOutput,
  ErrorPackage,
  Escalation,
  FindingRepairScope,
  Finding,
  HandoffStatus,
  IssueMeta,
  IssueSnapshot,
  IssueSnapshotMeta,
  LedgerEntry,
  LedgerBookkeepingEvent,
  PersistentLedgerEntry,
  ReviewerOutput,
  RunInput,
  RunResult,
  StepId,
  StepOutput,
  StepResult,
  StepRole,
  StepSoul,
  StepSpec,
  ToolchainEntry,
  WorktreeHandle,
  // unified worker-dispatch seam (ADR 0026 / PRD #330, #331)
  WorkerSpec,
  WorkerKind,
  WorkerHost,
  WorkerSessionMode,
  WorkerContextRetention,
  DispatchContext,
  WorkerResult,
  WorkerOutput,
  CoderResult,
  ReviewerResult,
  CmrResult,
  ShipResult,
  MergeWorkerResult,
  WorkerMonitorHandle,
} from "./types.js";
