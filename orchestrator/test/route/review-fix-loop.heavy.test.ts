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

  it("keeps routing by fresh reviewer declarations across repeated coder receipts", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
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
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const srcDir = join(wt.path, "src");
        mkdirSync(srcDir, { recursive: true });
        writeFileSync(
          join(srcDir, "runner.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "src/runner.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `fix attempt ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
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

  it("continues to fresh review when the best-effort HEAD read fails after S5", async () => {
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        { kind: "completed", output: { kind: "judge", status: "converged" } },
      ],
      undefined,
      [{ kind: "coder", committed: true, commitsAdded: 1 }],
      worktree,
      (_attempt, wt) => {
        renameSync(join(wt.path, ".git"), join(wt.path, ".git-unavailable"));
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("does not derive progress from coder receipt details", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
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
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const testDir = join(wt.path, "test");
        mkdirSync(testDir, { recursive: true });
        writeFileSync(
          join(testDir, "per-slice-cmr-369.test.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "test/per-slice-cmr-369.test.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `test evidence ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
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

  it("does not derive changed paths from coder receipt cargo", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
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
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const srcDir = join(wt.path, "src");
        mkdirSync(srcDir, { recursive: true });
        writeFileSync(
          join(srcDir, "runner.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "src/runner.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `source movement ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
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

  it.each([
    {
      name: "severity decreases",
      initial: [{ ...blocking, severity: "high" as const }],
      firstAfterFix: [{ ...blocking, severity: "medium" as const }],
      firstDispositions: [
        { identityKey: blockingKey, status: "still-active" as const },
      ],
      secondAfterFix: [{ ...blocking, severity: "medium" as const }],
      secondDispositions: [
        { identityKey: blockingKey, status: "still-active" as const },
      ],
      finalDispositions: [
        { identityKey: blockingKey, status: "verified-closed" as const },
      ],
    },
  ])("counts reviewer-observed progress when $name", async (sample) => {
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.initial,
          findingsCount: sample.initial.length,
          fixPacketBody: "fixture residual authored body",
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.firstAfterFix,
          findingsCount: sample.firstAfterFix.length,
          fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: sample.firstDispositions,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.secondAfterFix,
          findingsCount: sample.secondAfterFix.length,
          fixPacketBody: "fixture residual authored body",
          priorFindingDispositions: sample.secondDispositions,
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("completed");
    expect(result.errorPackage).toBeUndefined();
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

});
