import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import { decodeReviewerOpenCountReceipt } from "../../src/receiptRecovery.js";
import {
  dispatchWorker,
  landingWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
  workerResultToStep,
} from "../../src/dispatchWorker.js";
import { familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";
import { CODER_ROSTER } from "../../src/coderRoster.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import {
  readTelemetryRecords,
  type TelemetryCommitRecord,
  type TelemetryEnvironmentRecord,
} from "../../src/telemetry.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerOutcomeLandingFile,
  WorkerResult,
  WorkerSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "../../src/types.js";

const SMOKED_ROUTE = resolveRouteModels(
  "normal",
  {},
  {},
  Object.fromEntries(
    routeSmokeEntries(resolveRouteModels("normal", {})).map((entry) => [
      entry.key,
      { state: "passed", at: new Date().toISOString(), cliVersion: "test" },
    ]),
  ),
);

/**
 * #331 — the unified worker-dispatch seam.
 *
 * A fake Backend that implements ONLY the new `dispatchWorker` seam (plus the S0/S1
 * read seams the runner needs to reach the worker steps). It records every
 * dispatched WorkerSpec so we can assert the SEQUENCE + each spec — replacing the
 * old per-method (runStep/push) assertions (PRD #330 Testing Decisions).
 */
class DispatchBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  /** Ordered log of every worker dispatched: "id:kind:role:session:skill". */
  readonly dispatched: string[] = [];
  /** The full WorkerSpec of each dispatch, in order. */
  readonly specs: WorkerSpec[] = [];
  /** The DispatchContext of each dispatch, in order. */
  readonly ctxs: DispatchContext[] = [];
  /** Durable runner ledger rows, including the buffered S0 start row. */
  readonly persistedLedger: PersistentLedgerEntry[] = [];
  /** Asserts the runner NEVER reaches for the legacy methods directly. */
  legacyRunStepCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-331",
    base: "main",
    path: "/resident/worktrees/issue-331",
  };

  async findResumeState(): Promise<
    | undefined
    | {
        worktree: WorktreeHandle;
        stateDir: string;
        ledger: PersistentLedgerEntry[];
      }
  > {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession should not be called directly (#331)");
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

  async runStep(): Promise<StepOutput> {
    this.legacyRunStepCount += 1;
    throw new Error("runStep should not be called directly (#331)");
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.persistedLedger.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.dispatched.push(
      `${spec.id}:${spec.kind}:${spec.role}:${spec.session}:${spec.contextRetention}:${spec.skill ?? "—"}`,
    );
    this.specs.push(spec);
    this.ctxs.push(ctx);
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    throw new Error(`unexpected child worker kind: ${spec.kind}`);
  }
}

describe("#331 unified worker-dispatch seam — happy path", () => {

  it("mechanical-retries StructuredOutputError at S2 then continues without a decision park", async () => {
    // #899: SOE exhaust is process-level #598 redispatch, not silent advance.
    const root = mkdtempSync(join(tmpdir(), "orch-786-malformed-coder-"));
    const telemetryDir = join(root, ".ledger-786");
    execFileSync("git", ["init", "--initial-branch=main", root]);
    execFileSync("git", ["-C", root, "config", "user.email", "test@example.com"]);
    execFileSync("git", ["-C", root, "config", "user.name", "Test User"]);
    execFileSync("git", ["-C", root, "commit", "--allow-empty", "-m", "initial"]);

    class MalformedCoderTelemetryBackend extends DispatchBackend {
      private coderAttempts = 0;
      override readonly worktree: WorktreeHandle = {
        branch: "feat/orchestrator/issue-786",
        base: "main",
        path: root,
      };

      resolveTelemetryDir(): string {
        return telemetryDir;
      }

      async installTelemetryRunEnvironment(): Promise<void> {}

      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        this.specs.push(spec);
        this.ctxs.push(ctx);
        if (spec.kind === "coder") {
          this.coderAttempts += 1;
          execFileSync("git", ["-C", root, "commit", "--allow-empty", "-m", "worker commit"]);
          if (this.coderAttempts === 1) {
            const err = new Error("coder outcome JSON was truncated");
            err.name = "StructuredOutputError";
            throw err;
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        return {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        };
      }
    }

    try {
      const backend = new MalformedCoderTelemetryBackend();
      const result = await runOrchestrator({ issueNumber: 786, backend });
      expect(result.status).toBe("completed");
      expect(backend.specs.filter((spec) => spec.id === "S2").length).toBeGreaterThanOrEqual(2);
      expect(backend.specs.filter((spec) => spec.id === "S3")).toHaveLength(1);
      expect(result.stepLedger.find((entry) => entry.step === "S2")?.output)
        .toMatchObject({ kind: "coder", committed: true, commitsAdded: 1 });
      let commits: TelemetryCommitRecord[] = [];
      await vi.waitFor(() => {
        commits = readTelemetryRecords(telemetryDir).filter(
          (record): record is TelemetryCommitRecord => record.phase === "commit",
        );
        expect(commits.length).toBeGreaterThanOrEqual(1);
      });
      expect(commits[0]).toMatchObject({ issue: 786, runId: backend.ctxs[0]?.runId });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("ADR 0131 reviewer count envelope", () => {

  it.each([
    ["missing findings cargo", undefined],
    ["empty findings cargo", [] as const],
  ])(
    "positive findingsCount with %s still hands raw reviewer artifacts to S5",
    async (_label, findings) => {
      class PositiveCountMissingCargoBackend extends DispatchBackend {
        readonly landings: Array<WorkerLandingPayload | undefined> = [];
        reviewerCalls = 0;
        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          this.landings.push(landing);
          if ((spec.kind === "reviewer" || spec.kind === "verify")) {
            this.reviewerCalls += 1;
            if (this.reviewerCalls > 1) return super.dispatchWorker(spec, ctx);
            this.specs.push(spec);
            this.ctxs.push(ctx);
            return {
              kind: "completed",
              // Legal open-count with sparse/missing findings rows — fixer must
              // still receive raw artifact pointers (not an empty no-op landing).
              output: {
                kind: "reviewer",
                findingsCount: 2,
                ...(findings !== undefined ? { findings: [...findings] } : { findings: [] }),
                fixPacketBody: "fixture residual authored body",
              },
              sessionId: "reviewer-session-positive-missing-cargo",
            };
          }
          if (spec.id === "S5") {
            this.specs.push(spec);
            this.ctxs.push(ctx);
            return {
              kind: "completed",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            };
          }
          return super.dispatchWorker(spec, ctx);
        }
      }

      const backend = new PositiveCountMissingCargoBackend();
      const result = await runOrchestrator({ issueNumber: 899, backend });

      expect(result.status).toBe("completed");
      const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
      expect(s5Index).toBeGreaterThan(-1);
      expect(backend.ctxs[s5Index]?.blockingFindingCount).toBe(2);
      expect(backend.landings[s5Index]).toMatchObject({
        fixPacketBody: "fixture residual authored body",
        rawReviewerArtifacts: {
          reviewerSessionId: "reviewer-session-positive-missing-cargo",
          statement: "the previous reviewer raw artifacts are here",
        },
      });
      expect(backend.landings[s5Index]?.fixPacketBody ?? "").not.toContain(
        "[residual] open-count continue",
      );
      expect(backend.landings[s5Index]?.blockingFindings).toBeUndefined();
    },
  );

});

describe("#796 Coder-Rec host dispatch", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  class CoderRecDispatchBackend extends DispatchBackend {
    constructor(private readonly coderRecBody: string) {
      super();
    }

    override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        ...(await super.fetchIssueMeta(issueNumber)),
        body: this.coderRecBody,
      };
    }
  }

  it.each([
    ["gpt-5.6-terra", undefined, "codex"],
    ["sonnet", undefined, "claude"],
    ["grok-4.5", undefined, "grok"],
    ["agy", undefined, "agy"],
    ["grok-4.5", "grok-build", "grok"],
    // #905: pool rewrite cannot transit grok-4.5 off SuperGrok CLI.
    ["grok-4.5", "codex-5h", "grok"],
  ] as const)(
    "derives host %s/%s from the registered provider",
    (model, billingPool, host) => {
      const worker = stepSpecToWorkerSpec(
        {
          id: "S2",
          role: "coder",
          promptFile: "coder_implement.md",
          model,
          maxIter: 1,
          soul: "coder",
          toolchain: [],
        },
        "fresh",
        billingPool,
      );

      expect(worker.host).toBe(host);
    },
  );

});

describe("#331 legacyDispatchWorker — forwards to the existing methods", () => {
  /** A minimal legacy backend exposing only runStep/resumeSession (no dispatchWorker). */
  class LegacyBackend {
    runStepCalls: StepSpec[] = [];
    resumeCalls: string[] = [];
    runStepOutcomeLandings: Array<WorkerOutcomeLandingFile | undefined> = [];
    resumeOutcomeLandings: Array<WorkerOutcomeLandingFile | undefined> = [];
    worktree: WorktreeHandle = {
      branch: "b",
      base: "main",
      path: "/wt",
    };
    async runStep(
      spec: StepSpec,
      _wt: WorktreeHandle,
      options?: { outcomeLanding?: WorkerOutcomeLandingFile },
    ): Promise<StepOutput> {
      this.runStepCalls.push(spec);
      this.runStepOutcomeLandings.push(options?.outcomeLanding);
      return spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 1 }
        : { kind: "judge", status: "converged" };
    }
    async resumeSession(
      _spec: StepSpec,
      _wt: WorktreeHandle,
      sid: string,
      options?: { outcomeLanding?: WorkerOutcomeLandingFile },
    ): Promise<StepOutput> {
      this.resumeCalls.push(sid);
      this.resumeOutcomeLandings.push(options?.outcomeLanding);
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
  }

  const coderWorker: WorkerSpec = {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "claude",
    session: "resume",
    contextRetention: "retain",
    skill: "/tdd",
    promptFile: "coder_implement.md",
    maxIter: 1,
    model: "sonnet",
    soul: "coder",
    toolchain: ["python"],
  };

  it("writes the fix-findings landing file exclude into the target worktree git exclude", async () => {
    const worktreePath = mkdtempSync(join(tmpdir(), "dispatch-exclude-worktree-"));
    const wrongCwd = mkdtempSync(join(tmpdir(), "dispatch-exclude-cwd-"));
    const originalCwd = process.cwd();
    try {
      execFileSync("git", ["init"], { cwd: worktreePath, stdio: "ignore" });
      process.chdir(wrongCwd);

      const be = new LegacyBackend();
      const worktree = { ...be.worktree, path: worktreePath };
      await legacyDispatchWorker(
        be,
        { ...coderWorker, id: "S5", session: "fresh" },
        {
          worktree,
          blockingFindingIdentityKeys: [],
          blockingFindingCount: 0,
        },
      );

      const exclude = readFileSync(
        join(worktreePath, ".git", "info", "exclude"),
        "utf8",
      );
      expect(exclude.split(/\r?\n/)).toContain(".orchestrator-fix-findings.json");
    } finally {
      process.chdir(originalCwd);
      rmSync(worktreePath, { recursive: true, force: true });
      rmSync(wrongCwd, { recursive: true, force: true });
    }
  });

  it("derives fixer identity keys from findings cargo at the landing writer", async () => {
    // #899: runner pass-throughs findings rows; dispatchWorker derives keys
    // for the fixer landing — not a runner identity-key court.
    const worktreePath = mkdtempSync(join(tmpdir(), "dispatch-identity-worktree-"));
    const stateDir = mkdtempSync(join(tmpdir(), "dispatch-identity-state-"));
    try {
      execFileSync("git", ["init"], { cwd: worktreePath, stdio: "ignore" });

      const be = new LegacyBackend();
      const worktree = { ...be.worktree, path: worktreePath };
      const finding = {
        severity: "high" as const,
        category: "Correctness",
        claim_quote: "derive me at the landing writer",
        location: "src/x.ts:1",
        suggested_fix: "fix",
        action: "fix_now" as const,
      };
      await legacyDispatchWorker(
        be,
        { ...coderWorker, id: "S5", session: "fresh" },
        {
          worktree,
          stateDir,
          // ADR 0138: identity keys stay on thin ctx; body is judge-authored.
          blockingFindingIdentityKeys: [
            "correctness|src/x.ts:1|derive me at the landing writer",
          ],
          blockingFindingCount: 1,
        },
        {
          fixPacketBody:
            "high correctness @ src/x.ts:1: derive me at the landing writer",
          // Bare findings packing path deleted — must not appear on disk.
          blockingFindings: [finding],
        },
      );

      // stateDir path keeps the landing (no post-dispatch cleanup).
      const landing = JSON.parse(
        readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
      );
      expect(landing.fixPacketBody).toBe(
        "high correctness @ src/x.ts:1: derive me at the landing writer",
      );
      expect(landing.blockingFindings).toBeUndefined();
      expect(landing.blockingFindingIdentityKeys).toEqual([
        "correctness|src/x.ts:1|derive me at the landing writer",
      ]);
    } finally {
      rmSync(worktreePath, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("does not expose unsupported outcome sidecars to fresh coder/reviewer workers", async () => {
    const worktreePath = mkdtempSync(join(tmpdir(), "dispatch-outcome-worktree-"));
    const stateDir = mkdtempSync(join(tmpdir(), "dispatch-outcome-state-"));
    try {
      execFileSync("git", ["init"], { cwd: worktreePath, stdio: "ignore" });
      const be = new LegacyBackend();
      const worktree = { ...be.worktree, path: worktreePath };

      await legacyDispatchWorker(be, { ...coderWorker, session: "fresh" }, {
        worktree,
        stateDir,
      });

      expect(be.runStepOutcomeLandings).toEqual([undefined]);
    } finally {
      rmSync(worktreePath, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("passes the runner-owned outcome sidecar through resumeSession alongside the session id", async () => {
    const worktreePath = mkdtempSync(join(tmpdir(), "dispatch-outcome-resume-worktree-"));
    const stateDir = mkdtempSync(join(tmpdir(), "dispatch-outcome-resume-state-"));
    try {
      execFileSync("git", ["init"], { cwd: worktreePath, stdio: "ignore" });
      const be = new LegacyBackend();

      await legacyDispatchWorker(be, { ...coderWorker, id: "S5" }, {
        worktree: { ...be.worktree, path: worktreePath },
        stateDir,
        resumeSessionId: "sess-abc",
      });

      expect(be.resumeCalls).toEqual(["sess-abc"]);
      expect(be.resumeOutcomeLandings).toEqual([undefined]);
    } finally {
      rmSync(worktreePath, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

});
