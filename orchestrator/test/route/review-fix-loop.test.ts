import {
  describe,
  expect,
  it,
  execFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  writeFileSync,
  tmpdir,
  join,
  legacyDispatchWorker,
  skeletonReviewLoopWorkerResult,
  MAX_DISPATCH_ATTEMPTS,
  findingIdentityKey,
  route,
  runOrchestrator,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  PersistentLedgerFixture,
  ResumeStateFixture,
  materializeResumeState,
  WORKTREE,
  makeGitWorktree,
  RetryReviewBackend,
} from "./review-fix-loop.shared.js";

describe("#369 per-slice runner-visible review/fix loop", () => {
  it("keeps non-accepted-suppressed follow-up findings blocking across fix rounds", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix before shipping",
      location: "src/runner.ts:10",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const followUpFinding: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "track this later",
      location: "src/runner.ts:11",
      suggested_fix: "file follow-up",
      action: "fix_now",
    };
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [blocking, followUpFinding], findingsCount: 2, fixPacketBody: "fixture residual authored body" },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("completed");
  });

});

describe("#427 ADR0030 claimed-fixed adjudication", () => {
  const blocking: Finding = {
    severity: "high",
    category: "Correctness",
    claim_quote: "absence is not closure",
    location: "src/runner.ts:427",
    suggested_fix: "require explicit disposition",
    action: "fix_now",
  };
  const blockingKey = "correctness|src/runner.ts:427|absence is not closure";

  it("routes S3/S6 from judge status; residual open-count 0 is unusable not clean", () => {
    // #919 CR P1 / #925: residual findingsCount=0 is unusable → S5 (never S7).
    // Disposition prose is ignored either way; only explicit judge converged cleans.
    expect(
      route({
        from: "S3",
        output: {
          kind: "reviewer",
          findings: [],
          findingsCount: 0,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(
      route({
        from: "S6",
        output: { kind: "judge", status: "converged" },
      }),
    ).toEqual({ kind: "next", step: "S7" });
  });

  it("routes a completed S5 no-commit report to resident judge hub (#1083)", () => {
    expect(
      route({
        from: "S5",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("#877: S6 empty findings without disposition ships (disposition court demolished)", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
      { kind: "completed", output: { kind: "judge", status: "converged" } },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(result.errorPackage?.reason ?? "").not.toMatch(
      /omitted required disposition/i,
    );
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("ships only after the fresh re-review explicitly verifies a claimed-fixed finding closed", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("threads judge finding dispositions through live re-review and persists them", async () => {
    const acceptedRisk: Finding = {
      severity: "medium",
      category: "Correctness",
      claim_quote: "accepted risk remains same severity",
      location: "src/runner.ts:736",
      suggested_fix: "do not reopen without a material severity upgrade",
      action: "wont_fix",
      disposition_reason: "Accepted as out of scope for this slice",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #428 acceptance criteria",
        scope: "out-of-scope accepted risk",
        reason: "Accepted as out of scope for this slice",
        findingIdentity:
          "correctness|src/runner.ts:736|accepted risk remains same severity",
        boundedReopen: "reopen on material severity upgrade",
      },
    };
    const acceptedRiskKey =
      "correctness|src/runner.ts:736|accepted risk remains same severity";
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [blocking, acceptedRisk], findingsCount: 2, fixPacketBody: "fixture residual authored body" },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          // #604 correctness r1 (P2-a): a REOPENED finding is a plain blocking
          // `fix_now` — it must NOT carry the accepted_suppressed disposition
          // (that is only valid on wont_fix/rejected). Strip the disposition when
          // reopening so the reviewer output stays contract-valid.
          findings: [
            {
              severity: acceptedRisk.severity,
              category: acceptedRisk.category,
              claim_quote: acceptedRisk.claim_quote,
              location: acceptedRisk.location,
              suggested_fix: acceptedRisk.suggested_fix,
              action: "fix_now",
            },
          ],
          findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
            {
              identityKey: acceptedRiskKey,
              status: "still-active",
              reason: "reviewer-only suppression must be repaired",
            },
          ],
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
    // #925: dispositions land on S3/S6 judge rows (S4 dissolved).
    const firstJudgeWrite = backend.ledgerWrites.find(
      (entry) => entry.step === "S3" || entry.step === "S6",
    );
    expect(firstJudgeWrite).toBeDefined();
  });

  it("#877: repeated still-active disposition prose no longer no-progress-kills; findings-count continues", async () => {
    // Pre-#877: two still-active rounds without progress → escalate at S4.
    // Post-#877: no-progress court demolished; loop follows findings count until
    // the scripted backend falls through to empty findings and ships.
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(result.errorPackage?.reason ?? "").not.toMatch(/no progress/i);
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("#877: empty S6 still-active disposition on resume closes via findings-count (no reopen court)", async () => {
    // Pre-#877: still-active disposition reopened priors → S5 fix loop.
    // Post-#877: findings=[] closes; resume after S5 ships without reopening.
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-427",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: { kind: "judge", status: "converged" },
        },
        { step: "S4" },
        {
          step: "S5",
          output: {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          },
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual(["S6:verify"]);
  });

  it("does not count reviewer claim narrowing as implementation progress", async () => {
    const originalFinding = {
      ...blocking,
      claim_quote: "module parser leaves inline yaml accepted in invalid declarations",
    };
    const firstNarrowedFinding = {
      ...blocking,
      claim_quote: "inline yaml accepted",
    };
    const secondNarrowedFinding = {
      ...blocking,
      claim_quote: "yaml accepted",
    };
    const originalKey = findingIdentityKey(originalFinding);
    const firstNarrowedKey = findingIdentityKey(firstNarrowedFinding);

    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [originalFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [firstNarrowedFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [secondNarrowedFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
            { identityKey: firstNarrowedKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    // #877: no-progress court demolished; findings-count continues until empty fallback ships.
    expect(result.status).toBe("completed");
    expect(result.stopSummary.reason).not.toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("does not count omitted still-active prior findings as blocking-count progress", async () => {
    const primaryFinding = {
      ...blocking,
      claim_quote: "primary blocker stays active through dispositions",
    };
    const secondaryFinding = {
      ...blocking,
      claim_quote: "secondary blocker remains in reviewer findings",
      location: "src/secondary.ts:1",
    };
    const primaryKey = findingIdentityKey(primaryFinding);
    const secondaryKey = findingIdentityKey(secondaryFinding);

    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [primaryFinding, secondaryFinding], findingsCount: 2, fixPacketBody: "fixture residual authored body" },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [{ ...secondaryFinding, severity: "medium" }], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [{ ...secondaryFinding, severity: "low" }], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    // #877: omitted still-active disposition prose does not reopen or no-progress-kill.
    // Secondary re-emitted findings keep the fix loop via findings-count until empty.
    expect(result.status).toBe("completed");
    expect(result.stopSummary.reason).not.toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("does not treat source-less continue-fixing bookkeeping as an executable human resume", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "parked", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingIdentityKey: blockingKey,
          findingScope: { identityKeys: [blockingKey] },
          ts: "2026-07-01T00:00:02.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("parked");
    expect(backend.dispatched).toEqual([]);
  });

  it("does not reopen an S4 decision escalation for stale or scope-mismatched continue-fixing bookkeeping", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "parked", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingIdentityKey: blockingKey,
          findingScope: { identityKeys: [blockingKey] },
          source: "coordinator",
          ts: "2026-07-01T00:00:02.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("parked");
    expect(backend.dispatched).toEqual([]);
  });

  it("ignores malformed finding scopes on resume bookkeeping without throwing", async () => {
    const baseLedger = [
      { step: "S0" },
      { step: "S1" },
      { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
      { step: "S4" },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S6",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      { step: "S4" },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S6",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      { step: "S4" },
      { step: "S8", handoffStatus: "parked", escalationKind: "decision" },
    ] as const;
    const malformedEvents: PersistentLedgerFixture[] = [
      {
        step: "S4",
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        // Deliberately omit the required scope key for the parser boundary.
        findingScope: {},
        source: "resume_input",
        ts: "2026-07-01T00:00:03.000Z",
      },
    ];

    for (const event of malformedEvents) {
      const backend = new RetryReviewBackend([], {
        worktree: WORKTREE,
        stateDir: "/resident/worktrees/.ledger-446",
        ledger: [...baseLedger, event],
      });

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("parked");
      expect(backend.dispatched).toEqual([]);
    }
  });

  it("does not map unscoped escalation answers to continue-fixing repair intent", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "parked", escalationKind: "decision" },
        {
          step: "S4",
          event: "escalation_answered",
          forStep: "S4",
          answer: "继续修",
          source: "human",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("parked");
    expect(backend.dispatched).toEqual([]);
  });

  it("preserves a persisted terminal error stop summary on already-done re-feed", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446-error",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: false, commitsAdded: 0 } },
        {
          step: "S8",
          handoffStatus: "failed",
          stopSummary: {
            reason: "contract_drift",
            summary: "persisted malformed coder output",
            repairHint: "repair the coder contract and rerun",
          },
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("failed");
    expect(result.stopSummary).toMatchObject({
      reason: "contract_drift",
      summary: "persisted malformed coder output",
    });
    expect(backend.dispatched).toEqual([]);
  });

  it("#982: S8(failed)+decision is terminal — answer does not reopen as answerable decision", async () => {
    // failed is terminal ABI; only parked+decision reopens. An answer after a
    // failed S8 must not re-enter the escalated step (no dispatch).
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446-failed-decision",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S3",
          sessionId: "session-escalated",
          output: {
            kind: "judge",
            status: "escalate",
            reason: "product decision needed",
            diagnosis: "needs owner call",
            escalate: {
              reason: "product decision needed",
              diagnosis: "needs owner call",
            },
          },
        },
        {
          step: "S8",
          handoffStatus: "failed",
          escalationKind: "decision",
          stopSummary: {
            reason: "infra_failure",
            summary: "failed while writing decision park",
            repairHint: "inspect S8 write path; do not reopen as answerable",
          },
        },
        {
          step: "S3",
          event: "escalation_answered",
          forStep: "S3",
          answer: "ship the simpler option",
          source: "human",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("failed");
    expect(backend.dispatched).toEqual([]);
  });

  it("does not treat scoped coordinator or peripheral escalation answers as executable continue-fixing input", async () => {
    for (const source of ["coordinator", "peripheral"] as const) {
      const resumeState: ResumeStateFixture = {
        worktree: WORKTREE,
        stateDir: `/resident/worktrees/.ledger-446-${source}`,
        ledger: [
          { step: "S0" },
          { step: "S1" },
          { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body",
              priorFindingDispositions: [
                { identityKey: blockingKey, status: "still-active" },
              ],
            },
          },
          { step: "S4" },
          { step: "S8", handoffStatus: "parked", escalationKind: "decision" },
          {
            step: "S4",
            event: "escalation_answered",
            forStep: "S4",
            answer: "继续修",
            source,
            findingScope: { identityKeys: [blockingKey] },
          },
        ],
      };
      const backend = new RetryReviewBackend([], resumeState);

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("parked");
      expect(backend.dispatched).toEqual([]);
    }
  });

});

describe("#369 runner resume/retry review fixes", () => {
  it("#877/#925: resume after empty S6 (findingsCount=0) ships without re-dispatch", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "resumed S6 still needs disposition",
      location: "src/runner.ts:950",
      suggested_fix: "remember that the last reviewer step was S6",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        // #925: empty open-count / converged projects to S7 without S4.
        { step: "S6", output: { kind: "judge", status: "converged" } },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("completed");
    expect(result.errorPackage?.reason ?? "").not.toMatch(
      /omitted required disposition/i,
    );
    expect(backend.dispatched).toEqual([]);
  });

  it("#877/#925: resume after converged S6 with still-active prose ships (no reopen)", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "persisted S4 still has the prior blocker",
      location: "src/runner.ts:960",
      suggested_fix: "route the adjudicated still-open finding to S5",
      action: "fix_now",
    };
    const key = "correctness|src/runner.ts:960|persisted s4 still has the prior blocker";
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          // #925: clean resume requires explicit judge converged (residual
          // findingsCount=0 is unusable, not silent clean).
          output: { kind: "judge", status: "converged" },
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([]);
  });

  it("replays persisted S4 finding dispositions on resume", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "fix this first",
      location: "src/runner.ts:970",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const blockingKey = "correctness|src/runner.ts:970|fix this first";
    const acceptedRiskKey =
      "correctness|src/runner.ts:971|accepted risk survives resume";
    const acceptedRisk: Finding = {
      severity: "medium",
      category: "Correctness",
      claim_quote: "accepted risk survives resume",
      location: "src/runner.ts:971",
      suggested_fix: "do not reopen at the same severity",
      action: "wont_fix",
      disposition_reason: "Accepted outside this slice",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #369 resume fixture",
        scope: "accepted risk survives resume",
        reason: "Accepted outside this slice",
        findingIdentity: acceptedRiskKey,
        boundedReopen: "reopen on material severity upgrade",
      },
    };
    const acceptedRiskDisposition = {
      identityKey: acceptedRiskKey,
      status: "accepted_suppressed" as const,
      reason: "Accepted outside this slice",
      severity: "medium" as const,
      source: "issue #369 resume fixture",
      scope: "accepted risk survives resume",
      boundedReopen: "reopen on material severity upgrade",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S3",
          output: { kind: "reviewer", findings: [blocking, acceptedRisk], findingsCount: 2, fixPacketBody: "fixture residual authored body" },
        },
        { step: "S4", findingDispositions: [acceptedRiskDisposition] },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            // #604 correctness r1 (P2-a): a reopened finding is a plain blocking
            // fix_now with NO accepted_suppressed disposition (that is only valid
            // on wont_fix/rejected).
            findings: [
              {
                severity: acceptedRisk.severity,
                category: acceptedRisk.category,
                claim_quote: acceptedRisk.claim_quote,
                location: acceptedRisk.location,
                suggested_fix: acceptedRisk.suggested_fix,
                action: "fix_now",
              },
            ],
            findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
              {
                identityKey: acceptedRiskKey,
                status: "still-active",
                reason: "reviewer-only suppression must be repaired",
              },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  // #604 slice 4 (ADR 0062): re-feeding a terminal success run stays terminal
  // and dispatches nothing.
  it("keeps a re-fed terminal success run terminal", async () => {
    const followUpFinding: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "terminal resume still reports this follow-up",
      location: "src/runner.ts:926",
      suggested_fix: "surface the follow-up finding",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [followUpFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { step: "S4" },
        { step: "S7" },
        { step: "S8", handoffStatus: "completed" },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([]);
  });

  it("reviewer process throw uses mechanical dispatch budget only (no format escalate)", async () => {
    class LegacyThrowingReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      readonly calls: string[] = [];
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return WORKTREE;
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if ((spec.role === "reviewer" || spec.role === "verify")) {
          this.reviewerAttempts += 1;
          throw new Error("container failed to start");
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
    }
    const backend = new LegacyThrowingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    // Process crash path: mechanical redispatch, not runner format court.
    expect(backend.reviewerAttempts).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(result.status).toBe("failed");
  });

  it("retries a reviewer non-structured crash, then surfaces a persistent one as an S8 error (#598)", async () => {
    class FailingReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return WORKTREE;
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if ((spec.role === "reviewer" || spec.role === "verify")) {
          this.reviewerAttempts += 1;
          throw new Error("container failed to start");
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
    }
    const backend = new FailingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    // Process crash path only (not findings-schema court): mechanical budget then stop.
    expect(result.status).toBe("failed");
    expect(backend.reviewerAttempts).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

describe("#369 finding identity", () => {
  const finding: Finding = {
    severity: "medium",
    category: "Correctness",
    claim_quote: "  Missing   full diff review ",
    location: "src/runner.ts:120",
    suggested_fix: "review current full diff",
    action: "fix_now",
  };
  it("uses a normalized category/location/claim identity key, not an object hash", () => {
    const sameFindingDifferentWording: Finding = {
      ...finding,
      category: " correctness ",
      claim_quote: "missing full diff review",
      suggested_fix: "different wording should not change identity",
    };

    expect(findingIdentityKey(sameFindingDifferentWording)).toBe(
      findingIdentityKey(finding),
    );
  });

  it("escapes identity-key separators so distinct findings cannot collide", () => {
    const categoryCarriesSeparator: Finding = {
      ...finding,
      category: "Correct|ness",
      location: "src/runner.ts",
      claim_quote: "same claim",
    };
    const locationCarriesSeparator: Finding = {
      ...finding,
      category: "Correct",
      location: "ness|src/runner.ts",
      claim_quote: "same claim",
    };

    expect(findingIdentityKey(categoryCarriesSeparator)).not.toBe(
      findingIdentityKey(locationCarriesSeparator),
    );
  });

  // #1076 L2 / ADR 0131: identityKey short-circuit must not re-derive from
  // sparse cargo prose (would crash on undefined .trim()). Lock the explicit-
  // key branch + the loud typed fallback for missing prose fields.
  it("#1076: sparse finding with explicit identityKey returns it verbatim (no prose crash)", () => {
    const sparse = {
      identityKey: "x",
      severity: "medium",
      title: "t",
    } as unknown as Finding;
    expect(findingIdentityKey(sparse)).toBe("x");
  });

  it("#1076: missing identityKey with undefined category throws a loud typed field-name error (not TypeError)", () => {
    const noKeySparse = {
      severity: "medium",
      location: "src/x.ts:1",
      claim_quote: "claim",
      // category deliberately omitted
    } as unknown as Finding;
    let caught: unknown;
    try {
      findingIdentityKey(noKeySparse);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    expect(caught).not.toBeInstanceOf(TypeError);
    expect((caught as Error).message).toMatch(/category/);
  });

});

describe("#369 legacy S5 landing file", () => {
  it("materializes blocking findings in the runner-owned state dir, not the worktree-root spoofable file", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "fix-findings-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "fix-findings-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "fix me",
      location: "src/x.ts:1",
      suggested_fix: "patch it",
      action: "fix_now",
    };
    let observedLanding: unknown;
    writeFileSync(
      join(worktree.path, ".orchestrator-fix-findings.json"),
      '{"blockingFindings":[],"blockingFindingIdentityKeys":[]}\n',
      "utf8",
    );
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep() {
        observedLanding = JSON.parse(
          readFileSync(
            join(stateDir, "fix-findings.json"),
            "utf8",
          ),
        );
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    const result = await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
        blockingFindingCount: 1,
        escalationAnswer: {
          event: "escalation_answered",
          forStep: "S4",
          answer: "continue-same-class",
          note: "human approved another targeted fix round",
          source: "human",
        },
      },
      {
        fixPacketBody: "live: correctness|src/x.ts:1|fix me",
        blockingFindings: [finding],
      },
    );

    expect(result.kind).toBe("completed");
    expect(observedLanding).toEqual({
      // ADR 0138: bare findings packing deleted; body + keys + transport only.
      fixPacketBody: "live: correctness|src/x.ts:1|fix me",
      blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
      escalationAnswer: {
        event: "escalation_answered",
        forStep: "S4",
        answer: "continue-same-class",
        note: "human approved another targeted fix round",
        source: "human",
      },
    });
    expect(JSON.parse(readFileSync(join(worktree.path, ".orchestrator-fix-findings.json"), "utf8"))).toEqual({
      blockingFindings: [],
      blockingFindingIdentityKeys: [],
    });
  });

  it("passes the runner-owned findings file as sandbox-visible S5 mount metadata", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "fix-findings-mount-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "fix-findings-mount-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "mount me",
      location: "src/x.ts:2",
      suggested_fix: "make visible in sandbox",
      action: "fix_now",
    };
    let observedLanding:
      | { readonly path: string; readonly sandboxPath: string }
      | undefined;
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep(_spec, _worktree, options) {
        observedLanding = options?.fixFindingsLanding;
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:2|mount me"],
        blockingFindingCount: 1,
      },
      {
        fixPacketBody: "live: correctness|src/x.ts:2|mount me",
        blockingFindings: [finding],
      },
    );

    expect(observedLanding).toEqual({
      path: join(stateDir, "fix-findings.json"),
      sandboxPath: ".orchestrator-fix-findings.json",
    });
  });

  it("materializes prior claimed-fixed findings for S6 reviewers through the same protected mount", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "prior-findings-mount-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "prior-findings-mount-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "verify me",
      location: "src/x.ts:3",
      suggested_fix: "confirm closure",
      action: "fix_now",
    };
    let observedLanding: unknown;
    let observedMount:
      | { readonly path: string; readonly sandboxPath: string }
      | undefined;
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep(_spec, _worktree, options) {
        observedMount = options?.fixFindingsLanding;
        observedLanding = JSON.parse(
          readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
        );
        return { kind: "judge", status: "converged" };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S6",
      kind: "verify",
      role: "verify",
      host: "codex",
      session: "fresh",
      contextRetention: "clean",
      skill: "/verify",
      promptFile: "judge_station.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "verify",
      toolchain: [],
    };

    await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:3|verify me"],
        blockingFindingCount: 1,
      },
      { blockingFindings: [finding] },
    );

    expect(observedLanding).toEqual({
      // ADR 0138: bare blockingFindings packing deleted.
      blockingFindingIdentityKeys: ["correctness|src/x.ts:3|verify me"],
    });
    expect(observedMount).toEqual({
      path: join(stateDir, "fix-findings.json"),
      sandboxPath: ".orchestrator-fix-findings.json",
    });
  });
});
