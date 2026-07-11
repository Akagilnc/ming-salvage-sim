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
export type {
  DispatchWorkerWithMonitorOptions,
  DispatchWorkerWithMonitorOutcome,
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
  getTelemetryRunEnvironment,
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
  collectPidTree,
  dispatchMonitoredCliWorker,
  hasCompletionSignalInLog,
  instanceMatchesHandle,
  isWorkerAlive,
  isWorkerIdle,
  killWorkerTree,
  monitorHandleFromLedger,
  pidSafeToSignal,
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
  parseSubIssueNumbers,
  cutFamilyBase,
  resolveCodexFast,
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
// ── #683 quota probe (idle → probe 429 → wait-for-reset | hang) ─────────────
export {
  applyIdleDisposition,
  buildQuotaWaitForResetLedgerEntry,
  decideIdleAfterProbe,
  handleIdleThreshold,
  isAgentIdleTimeoutError,
  parseZaiResetAt,
  poolForModelRef,
  probeConfigForPool,
  QuotaWaitForResetError,
  runPoolProbe,
  serializeQuotaWaitForResetBridge,
  tryParseQuotaWaitForResetBridge,
  isQuotaWaitForResetError,
} from "./quotaProbe.js";
export type {
  ApplyIdleDispositionResult,
  HandleIdleThresholdInput,
  HandleIdleThresholdResult,
  IdleDisposition,
  IdleHangActions,
  IdleWorkerHandle,
  PoolProbeConfig,
  PoolProbeDeps,
  PoolProbeKind,
  QuotaPoolId,
  QuotaProbeResult,
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
  IssueSnapshot,
  IssueSnapshotMeta,
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
  CODER_REC_FALLBACK_AFTER_ROUNDS,
  CODER_ROSTER,
  CODER_ROSTER_VERSION,
  DEFAULT_CODER_REC_ORDER,
  lookupCoderRosterEntry,
  parseCoderRec,
  poolSeparationViolation,
  resolveCoderRecOrder,
  reviewerSlugsFromRoute,
  selectCoderRecEntry,
} from "./coderRoster.js";
export type { CoderPoolId, CoderRosterEntry, SelectCoderRecOptions } from "./coderRoster.js";
export { applyCoderRecToRoute, withCoderSlot } from "./modelRoutes.js";

// ── relay dispatch (#686 / ADR 0124–0126) ───────────────────────────────────
export {
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
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
  SelectNextRelayBatonInput,
} from "./quotaPoolTable.js";
export {
  RELAY_FOCUS_FILENAME,
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayFocusFile,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  capacityRelayErrorFrom,
  classifyFailureForRetryOrRelay,
  countRelayHandoffsInLedger,
  decideRelayAfterIdle,
  forkQuotaWallAt683Point,
  isHangWithLivePoolError,
  isCapacityRelayError,
  isRelayCandidateExhaustion,
  isRelayChainReadyForReviewGate,
  isSelfReportedRelayError,
  parseRelayTag,
  resumeRelayFromLedger,
  tryBuildRelayFocusFile,
  tryParseActionableRelayTag,
  HangWithLivePoolError,
  CapacityRelayError,
  SelfReportedRelayError,
} from "./relayDispatch.js";
export type {
  ApplyResourceFailureHandoffInput,
  DecideRelayAfterIdleInput,
  FailureClassKind,
  RelayDispositionResult,
  RelayHandoffLedgerEvent,
  RelayHandoffTrigger,
  RelayTagOutcome,
  RetryOrRelayClass,
} from "./relayDispatch.js";
export {
  POOL_DISPATCH_BINDINGS,
  isBillingPoolDispatchId,
  resolveModelSlugForPool,
  agentForSlug,
  resolveModelSlug,
} from "./modelRegistry.js";
export type { BillingPoolDispatchId } from "./modelRegistry.js";
