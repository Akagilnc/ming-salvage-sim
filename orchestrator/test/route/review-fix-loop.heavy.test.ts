import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { legacyDispatchWorker } from "../../src/dispatchWorker.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { findingIdentityKey } from "../../src/findings.js";
import { route } from "../../src/route.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
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
} from "../../src/types.js";

type PersistentLedgerFixture = Omit<
  PersistentLedgerEntry,
  "sessionId" | "prompt_hash" | "branchHEAD" | "ts"
> & Partial<Pick<PersistentLedgerEntry, "sessionId" | "prompt_hash" | "branchHEAD" | "ts">>;

type ResumeStateFixture = Omit<ResumeState, "ledger"> & {
  readonly ledger: ReadonlyArray<PersistentLedgerFixture>;
};

function materializeResumeState(fixture: ResumeStateFixture): ResumeState {
  return {
    ...fixture,
    ledger: fixture.ledger.map((entry) => ({
      ...entry,
      sessionId: entry.sessionId ?? "fixture-session",
      prompt_hash: entry.prompt_hash ?? "fixture-prompt",
      branchHEAD: entry.branchHEAD ?? "fixture-head",
      ts: entry.ts ?? "2026-07-01T00:00:00.000Z",
    })),
  };
}

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-369",
  base: "main",
  path: "/resident/worktrees/issue-369",
};

function makeGitWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "runner-progress-"));
  execFileSync("git", ["init", "-b", "main"], {
    cwd: path,
    stdio: "ignore",
  });
  writeFileSync(join(path, "README.md"), "base\n", "utf8");
  execFileSync("git", ["add", "."], { cwd: path, stdio: "ignore" });
  execFileSync(
    "git",
    [
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.com",
      "commit",
      "-m",
      "base",
    ],
    { cwd: path, stdio: "ignore" },
  );
  execFileSync("git", ["checkout", "-b", WORKTREE.branch], {
    cwd: path,
    stdio: "ignore",
  });
  return { ...WORKTREE, path };
}

class RetryReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;
  coderAttempts = 0;

  constructor(
    private readonly reviewerResults: ReadonlyArray<WorkerResult>,
    private readonly resumeState?: ResumeStateFixture,
    private readonly coderOutputs: ReadonlyArray<StepOutput> = [],
    private readonly worktree: WorktreeHandle = WORKTREE,
    private readonly onCoderDispatch?: (
      attempt: number,
      worktree: WorktreeHandle,
    ) => void,
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.resumeState && materializeResumeState(this.resumeState);
  }
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
    return this.worktree;
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if ((spec.role === "reviewer" || spec.role === "verify")) return { kind: "judge", status: "converged" };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);
    if (spec.kind === "coder" && spec.id === "S5") {
      const attempt = this.coderAttempts;
      const scripted = this.coderOutputs[this.coderAttempts];
      this.coderAttempts += 1;
      this.onCoderDispatch?.(attempt, this.worktree);
      if (scripted !== undefined) {
        return { kind: "completed", output: scripted };
      }
    }
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      const result = this.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      return result ?? { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

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
