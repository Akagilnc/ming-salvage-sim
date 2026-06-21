// @ming/orchestrator — public surface (#244).
// The runner-driven step machine (ADR 0018), its Backend seam, route()
// decision function, and domain types. Slice #247 wires the happy path;
// later slices (#248–#256) layer on these seams.
export { runOrchestrator } from "./runner.js";
export { route } from "./route.js";
export type { RouteContext, RouteDecision } from "./route.js";

// ── family integration layer (ADR 0022, #293) ──────────────────────────────
// The four independent extension modules + the spine that only CALLS them.
export { runFamily } from "./family/runner.js";
export { selectWave } from "./family/commander.js";
export { mergeChild } from "./family/merger.js";
export { recordMerged, recordAborted, mergedSet } from "./family/ledger.js";
export type { MergedRecord, AbortedRecord } from "./family/ledger.js";
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
  CoderOutput,
  ErrorPackage,
  Escalation,
  Finding,
  HandoffStatus,
  IssueMeta,
  IssueSnapshot,
  IssueSnapshotMeta,
  LedgerEntry,
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
} from "./types.js";
