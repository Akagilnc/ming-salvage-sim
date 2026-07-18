import {
  describe,
  expect,
  it,
  lastCorrectnessConvergedHeadFromLedger,
  recordCmrPassed,
  runFamily,
  runVerifyCmr,
  activeModelRoute,
  modelRouteFingerprint,
  QuotaWaitForResetError,
  legacyCmrScriptToWorkerOutput,
  legacyDispatchFamilyWorker,
  buildExplicitLandingLiveHooks,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  icQuotaParkError,
  currentRouteFingerprint,
  makeFamilyDocReleaseRepo,
  ChildBackend,
  CapableFamilyBackend,
} from "./incremental-correctness-961.shared.js";

describe("#961 lastCorrectnessConvergedHeadFromLedger — durable single source", () => {
  it("returns undefined when no correctness cmr_passed row exists", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "h1",
        routeFingerprint: "fp",
      },
    ];
    expect(lastCorrectnessConvergedHeadFromLedger(entries)).toBeUndefined();
  });

  it("returns the latest correctness cmr_passed familyHeadAfter (checkpoint or final)", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "correctness_checkpoint",
        cmrPass: "correctness",
        familyHeadAfter: "head-wave-1",
        routeFingerprint: "fp",
      },
      {
        status: "merged",
        childIssue: 2,
        familyHeadAfter: "head-wave-2",
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "correctness_checkpoint",
        cmrPass: "correctness",
        familyHeadAfter: "head-wave-2",
        routeFingerprint: "fp",
      },
    ];
    expect(lastCorrectnessConvergedHeadFromLedger(entries)).toBe("head-wave-2");
  });

});

describe("#961 spine — incremental IC after batch verify green", () => {
  const TWO_WAVES: FamilyEpic = {
    issue: 961,
    children: [
      { issue: 1001, blockedBy: [] },
      { issue: 1002, blockedBy: [1001] },
    ],
  };

  it("Runner admission/park path never reads lastCorrectnessConvergedHead", () => {
    // Import-surface / source-text guard: must fail if Runner starts importing
    // or calling the durable IC ledger helper for admission/park. IC Action /
    // verifyCmr owns lastCorrectnessConvergedHead; Runner comments may mention
    // the field name as a negative constraint, but must not bind the helper API.
    const runnerSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/runner.ts"),
      "utf8",
    );
    expect(runnerSrc).not.toMatch(/\blastCorrectnessConvergedHeadFromLedger\b/);
  });

});
