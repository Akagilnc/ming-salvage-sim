// @ming/orchestrator — public surface. Production execution enters through
// runFamilyDriver; runOrchestrator remains an internal child-slice machine.
export { route } from "./route.js";
export type { RouteContext, RouteDecision } from "./route.js";
export {
  contractDriftStopSummary,
  infraFailureStopSummary,
  providerDegradedStopSummary,
  successStopSummary,
} from "./stopSummary.js";
export type {
  AcceptedSuppressionSummary,
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
} from "./dispatchWorker.js";
export type {
  DispatchWorkerWithMonitorOptions,
  DispatchWorkerWithMonitorOutcome,
  LegacyDispatchBackend,
} from "./dispatchWorker.js";
// ── #786 telemetry sidecar (append-only JSONL; stats deferred) ──────────────
export {
  TELEMETRY_FILENAME,
  TELEMETRY_SCHEMA_VERSION,
  appendTelemetryRecord,
  buildCollectStamp,
  buildCommitStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  buildReviewRoundStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  clearTelemetryRunEnvironment,
  collectCommitDiffAuditAsync,
  collectCommitMetricsAsync,
  commitsBetweenAsync,
  configureTelemetryFromWorkerImage,
  configureTelemetryRunEnvironment,
  durableTelemetryDirForSingleSlice,
  ensureEnvironmentStamp,
  mentionsHttp429,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  hashDirectoryContents,
  newLegId,
  readDispatchLogSlice,
  readTelemetryRecords,
  telemetryPath,
  tryAppendTelemetryRecord,
} from "./telemetry.js";
export type {
  TelemetryCollectRecord,
  TelemetryCommitRecord,
  TelemetryCommitFileDistribution,
  TelemetryCommitMetrics,
  TelemetryEscapeHatchCounts,
  TelemetryCoderRecProvenance,
  TelemetryDispatchRecord,
  TelemetryEnvironmentRecord,
  TelemetryErrorCategory,
  TelemetryModelStamp,
  TelemetryRecord,
  TelemetryReviewRoundRecord,
  TelemetryRunEnvironment,
  TelemetryTerminal,
  TelemetryTokenUsage,
} from "./telemetry.js";
export {
  dispatchMonitoredCliWorker,
  logSilenceWholeMinutes,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  readProcessInstanceId,
  silenceWholeMinutes,
  terminateSpawnedChild,
  validateMonitorHandle,
  waitForChildExit,
  WorkerTerminationFailedError,
  isWorkerTerminationFailedError,
} from "./workerMonitor.js";
export type {
  ChildExit,
  LogActivitySnapshot,
  MonitoredCliDispatchInput,
  MonitoredCliDispatchResult,
  WorkerMonitorDeps,
} from "./workerMonitor.js";
export {
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  legacyDispatchFamilyWorker,
  cmrWorkerSpec,
  familyShipWorkerSpec,
} from "./family/dispatchFamilyWorker.js";
export type {
  DispatchFamilyWorkerWithMonitorOptions,
  DispatchFamilyWorkerWithMonitorOutcome,
} from "./family/dispatchFamilyWorker.js";
export {
  buildCliMonitorSpawnSpec,
  isCliMonitorChildProcess,
  isMonitoredWorkerKind,
  resolveMonitorLogDir,
  isMissingMonitorSidecarResult,
  workerResultFromMonitorSidecar,
} from "./cliMonitorHooks.js";

// ── family integration layer (ADR 0022, #293) ──────────────────────────────
// The four independent extension modules + the spine that only CALLS them.
export { runFamily } from "./family/runner.js";
// The production family driver (#291 Unit B): the end-to-end assembly entry point.
export {
  runFamilyDriver,
  readFamilyEpic,
  buildFamilyEpic,
  parseSubIssueAdmission,
  cutFamilyBase,
  resolveCodexFast,
} from "./familyDriver.js";
export type { FamilyDriverOptions, Sh, SubIssueAdmission } from "./familyDriver.js";
export { selectWave } from "./family/commander.js";
export { mergeChild } from "./family/merger.js";
export { recordMerged, recordAborted, mergedSet, recordPrMerged, familyPrMergedForHead } from "./family/ledger.js";
export type { MergedRecord, AbortedRecord, PrMergedRecord } from "./family/ledger.js";
export {
  assessMergeReadiness,
  confirmPrMergedLive,
  executePrMergeCommit,
  fetchPrMergeLiveState,
  isPrMergedMarker,
  mergeRecordIfHeadAligned,
} from "./autoMerge.js";
export type { MergeRecordAlignment } from "./autoMerge.js";
export { runLandingAction } from "./family/landing.js";
export { reconcileFamilyLedger } from "./family/reconcile.js";
export { runVerifyCmr } from "./family/verifyCmr.js";
export type {
  VerifyCmrInput,
  VerifyCmrPhase,
  VerifyCmrResult,
} from "./family/verifyCmr.js";
export {
  FAMILY_STAGE_FAILURE_STATUSES,
  isFamilyStageFailureStatus,
  resolveFamilyStageTerminal,
  stageFailureStopSummary,
  syncStopSummaryToStageFailure,
} from "./family/familyTerminal.js";
export type { FamilyStageFailureStatus } from "./family/familyTerminal.js";
// #942 public result + OS exit ABI (supersedes #929)
export {
  PUBLIC_EXIT_CODES,
  PUBLIC_FAILED_CAUSES,
  PUBLIC_RUN_RESULTS,
  LEGACY_929_PUBLIC_STATUS_TOKENS,
  causeFromStageFailure,
  exitCodeForPublicResult,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isLegacy929PublicStatusToken,
  isPublicRunResult,
  runResultExitCode,
} from "./publicResult.js";
export type { PublicFailedCause, PublicRunResult } from "./publicResult.js";
export {
  TERMINAL_EXIT_CODES,
  TERMINAL_EXIT_STATUSES,
  exitCodeForTerminal,
  isTerminalExitStatus,
} from "./terminalExitCode.js";
export type { TerminalExitStatus } from "./terminalExitCode.js";
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
  FamilyAbortedEvent,
  FamilyEscalation,
} from "./family/types.js";
// ── #683 / #937 explicit quota wait-for-reset (no idle→probe machinery) ─────
export {
  buildQuotaWaitForResetLedgerEntry,
  isAgentIdleTimeoutError,
  poolForModelRef,
  QuotaWaitForResetError,
  serializeQuotaWaitForResetBridge,
  tryParseQuotaWaitForResetBridge,
  isQuotaWaitForResetError,
} from "./quotaProbe.js";
export type {
  ApplyIdleDispositionResult,
  IdleDisposition,
  QuotaPoolId,
  QuotaWaitForResetLedgerEvent,
} from "./quotaProbe.js";

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
  LedgerEntry,
  LedgerBookkeepingEvent,
  QuotaWaitForResetEvent,
  RelayBatonHandoffEvent,
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

// ── design-time Coder-Rec roster (#767) ─────────────────────────────────────
export {
  CODER_ROSTER,
  CODER_ROSTER_VERSION,
  CoderRecError,
  DEFAULT_CODER_REC_ORDER,
  lookupCoderRosterEntry,
  parseCoderRec,
  resolveAdvanceCoderSuggestion,
  resolveCoderRecOrder,
  selectCoderRecEntry,
} from "./coderRoster.js";
export type {
  AdvanceCoderDecision,
  CoderPoolId,
  CoderRosterEntry,
} from "./coderRoster.js";
// ── #919 / #926 one advanceCoder execution path (slice + family) ────────────
export { executeAdvanceCoderSuggestion } from "./advanceCoderEffect.js";
export type {
  AdvanceCoderEffectResult,
  AdvanceCoderProbe,
} from "./advanceCoderEffect.js";
export {
  applyCoderRecToRoute,
  applyRelayBatonToRoute,
  familyRelaySlotsForWall,
  knownLiveBillingPoolsFromRoute,
  relaySlotForSingleSliceWallStep,
  withCoderSlot,
} from "./modelRoutes.js";

// ── relay dispatch (#686 / ADR 0124–0126) ───────────────────────────────────
export {
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
} from "./quotaPoolTable.js";
export type {
  BillingPoolEntry,
  BillingPoolId,
  BillingPoolStatus,
  NextRelayBaton,
  ParkOrRelayDecision,
  PoolTable,
  RelayPoolOverride,
  SelectNextRelayBatonInput,
} from "./quotaPoolTable.js";
export {
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  capacityRelayErrorFrom,
  countRelayHandoffsInLedger,
  forkQuotaWallAt683Point,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  renderEphemeralRelayBrief,
  resumeRelayFromLedger,
  CapacityRelayError,
} from "./relayDispatch.js";
export type {
  ApplyResourceFailureHandoffInput,
  LegacyRelayHandoffTrigger,
  RelayDispositionResult,
  RelayHandoffLedgerEvent,
  RelayHandoffTrigger,
} from "./relayDispatch.js";
export {
  POOL_DISPATCH_BINDINGS,
  isBillingPoolDispatchId,
  resolveModelSlugForPool,
  agentForSlug,
  resolveModelSlug,
} from "./modelRegistry.js";
export type { BillingPoolDispatchId } from "./modelRegistry.js";
