import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import {
  dispatchWorker,
  docReleaseWorkerSpec,
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
  IssueSnapshot,
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeSnapshot(): Promise<void> {}

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
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
    }
    throw new Error(`unexpected child worker kind: ${spec.kind}`);
  }
}

describe("#331 unified worker-dispatch seam — happy path", () => {
  it("continues from a completed empty coder report to a fresh reviewer", async () => {
    class AdvisoryDiscrepancyBackend extends DispatchBackend {
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "coder") {
          this.dispatched.push(
            `${spec.id}:${spec.kind}:${spec.role}:${spec.session}:${spec.contextRetention}:${spec.skill ?? "—"}`,
          );
          this.specs.push(spec);
          this.ctxs.push(ctx);
          return {
            kind: "completed",
            output: {
              kind: "coder",
              committed: false,
              commitsAdded: 0,
            },
          };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const backend = new AdvisoryDiscrepancyBackend();
    const result = await runOrchestrator({ issueNumber: 818, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched.slice(0, 2)).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:reviewer:reviewer:fresh:clean:/code-review",
    ]);
  });

  it("routes S2/S3 through dispatchWorker, never the legacy methods", async () => {
    const backend = new DispatchBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });

    expect(result.status).toBe("success");
    expect(result.branch).toBe("feat/orchestrator/issue-331");

    // Every productive child worker went through the unified seam.
    expect(backend.legacyRunStepCount).toBe(0);
  });

  it("dispatches S2→S3 before the local S7 handoff", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    // ADR 0030: implementation and review are separate runner-visible workers.
    // S7 is not a worker: the family merger consumes the local child commit.
    expect(backend.dispatched).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:reviewer:reviewer:fresh:clean:/code-review",
    ]);
  });

  it("each worker spec keeps the versioned promptFile (ADR 0018 #4 — no ad-hoc prompts)", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    const byId = Object.fromEntries(backend.specs.map((s) => [s.id, s]));
    expect(byId.S2.promptFile).toBe("coder_implement.md");
    expect(byId.S3.promptFile).toBe("reviewer_review.md");
  });

  it("hands the resident worktree to every single-slice worker via DispatchContext", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    for (const ctx of backend.ctxs) {
      expect(ctx.worktree).toEqual(backend.worktree);
    }
  });

  it("keeps two full runner invocations distinct in one durable telemetry sidecar", async () => {
    const root = mkdtempSync(join(tmpdir(), "orch-809-runner-sidecar-"));
    const durable = join(root, ".ledger-809");
    class TelemetryBackend extends DispatchBackend {
      resolveTelemetryDir(): string {
        return durable;
      }
      async installTelemetryRunEnvironment(): Promise<void> {}
    }
    const first = new TelemetryBackend();
    const second = new TelemetryBackend();

    try {
      await runOrchestrator({ issueNumber: 331, backend: first });
      await runOrchestrator({ issueNumber: 331, backend: second });
      await new Promise((resolve) => setImmediate(resolve));

      const environments = readTelemetryRecords(durable).filter(
        (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
      );
      const firstRunId = first.ctxs[0]?.runId;
      const secondRunId = second.ctxs[0]?.runId;
      expect(environments.map((record) => record.runId)).toEqual([firstRunId, secondRunId]);
      expect(firstRunId).toEqual(expect.any(String));
      expect(secondRunId).toEqual(expect.any(String));
      expect(firstRunId).not.toBe(secondRunId);
      expect(first.ctxs.every((ctx) => ctx.runId === firstRunId)).toBe(true);
      expect(second.ctxs.every((ctx) => ctx.runId === secondRunId)).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

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
          output: { kind: "reviewer", findings: [], findingsCount: 0 },
        };
      }
    }

    try {
      const backend = new MalformedCoderTelemetryBackend();
      const result = await runOrchestrator({ issueNumber: 786, backend });
      expect(result.status).toBe("success");
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

describe("#331 non-completed WorkerResult routing", () => {
  /** A backend whose S2 coder worker ESCALATES (model-judged stuck). */
  class EscalateBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      if (spec.kind === "coder") {
        return {
          kind: "escalated",
          escalation: { reason: "design blocker", diagnosis: "need a human" },
        };
      }
      return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
    }
  }

  it("an escalated worker → S8(escalate), NOT S8(error) (high cmr finding)", async () => {
    const backend = new EscalateBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    // The escalate edge is preserved through the unified seam.
    expect(result.status).toBe("escalate");
  });

  /** A backend whose S2 coder worker FAILS (crash / hard error). */
  class FailedBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      if (spec.kind === "coder") {
        return { kind: "failed", reason: "container crashed" };
      }
      return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
    }
  }

  it("a failed worker → S8(error) with the reason surfaced", async () => {
    const backend = new FailedBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.reason).toContain("container crashed");
  });
});

describe("ADR 0131 reviewer count envelope", () => {
  it("routes by findingsCount when findings cargo is non-array (no shape court)", async () => {
    // #899 / ADR 0131: runner never re-dispatches from findings-array shape.
    // Non-array cargo is empty landing cargo; positive count still opens S5.
    class NonArrayFindingsBackend extends DispatchBackend {
      readonly landings: Array<WorkerLandingPayload | undefined> = [];
      reviewerCalls = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        this.landings.push(landing);
        if (spec.kind === "reviewer") {
          this.reviewerCalls += 1;
          if (this.reviewerCalls > 1) return super.dispatchWorker(spec, ctx);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          return {
            kind: "completed",
            output: {
              kind: "reviewer",
              findingsCount: 1,
              // Illegal cargo shape — must not zero count or skip S5.
              findings: "not-an-array",
            } as unknown as StepOutput,
            sessionId: "reviewer-session-non-array",
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

    const backend = new NonArrayFindingsBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });

    expect(result.status).toBe("success");
    expect(backend.specs.filter((spec) => spec.kind === "reviewer")).toHaveLength(2);
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThan(-1);
    expect(backend.ctxs[s5Index]?.blockingFindingCount).toBe(1);
    expect(backend.landings[s5Index]).toMatchObject({
      blockingFindings: [],
      rawReviewerArtifacts: { reviewerSessionId: "reviewer-session-non-array" },
    });
    expect(JSON.stringify(backend.persistedLedger)).not.toContain('"escalationKind":"decision"');
  });

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
          if (spec.kind === "reviewer") {
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

      expect(result.status).toBe("success");
      const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
      expect(s5Index).toBeGreaterThan(-1);
      expect(backend.ctxs[s5Index]?.blockingFindingCount).toBe(2);
      expect(backend.landings[s5Index]).toMatchObject({
        blockingFindings: [],
        rawReviewerArtifacts: {
          reviewerSessionId: "reviewer-session-positive-missing-cargo",
          statement: "the previous reviewer raw artifacts are here",
        },
      });
    },
  );

  it("positive findingsCount with structured cargo still preserves raw reviewer artifacts", async () => {
    const finding = {
      severity: "high" as const,
      category: "correctness" as const,
      claim_quote: "structured row survives",
      location: "src/a.ts:1",
      suggested_fix: "keep raw pointers too",
      action: "fix_now" as const,
    };
    class PositiveCountWithCargoBackend extends DispatchBackend {
      readonly landings: Array<WorkerLandingPayload | undefined> = [];
      reviewerCalls = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        this.landings.push(landing);
        if (spec.kind === "reviewer") {
          this.reviewerCalls += 1;
          if (this.reviewerCalls > 1) return super.dispatchWorker(spec, ctx);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          return {
            kind: "completed",
            output: {
              kind: "reviewer",
              findingsCount: 1,
              findings: [finding],
            },
            sessionId: "reviewer-session-positive-with-cargo",
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

    const backend = new PositiveCountWithCargoBackend();
    const result = await runOrchestrator({ issueNumber: 899, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThan(-1);
    expect(backend.ctxs[s5Index]?.blockingFindingCount).toBe(1);
    expect(backend.landings[s5Index]).toMatchObject({
      blockingFindings: [finding],
      rawReviewerArtifacts: {
        reviewerSessionId: "reviewer-session-positive-with-cargo",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
  });

  it("dispatches S5 when the reviewer returns the wrong role kind", async () => {
    class WrongReviewerKindBackend extends DispatchBackend {
      reviewerCalls = 0;
      override async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "reviewer") {
          this.reviewerCalls += 1;
          if (this.reviewerCalls > 1) return super.dispatchWorker(spec, ctx);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          return {
            kind: "completed",
            output: { kind: "coder", committed: false, commitsAdded: 0 },
            sessionId: "reviewer-session-wrong-kind",
          };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const backend = new WrongReviewerKindBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });

    expect(result.status).toBe("success");
    expect(backend.specs.some((spec) => spec.id === "S5")).toBe(true);
    expect(JSON.stringify(backend.persistedLedger)).not.toContain('"escalationKind":"decision"');
  });

  it("rebuilds raw reviewer artifact pointers when resuming after a persisted S4 boundary", async () => {
    // #899: positive open-count artifacts live only in process memory during a
    // live run; crash/resume after S4 must rebuild them from the preceding
    // reviewer ledger row so sparse cargo cannot produce a no-op fixer landing.
    const finding = {
      severity: "high" as const,
      category: "correctness" as const,
      claim_quote: "resume must keep raw pointers",
      location: "src/runner.ts:2731",
      suggested_fix: "rebuild from reviewer ledger entry",
      action: "fix_now" as const,
    };
    const monitorHandle = {
      pid: 4242,
      logPath: "/host/ledger/S3.stdout",
      resultPath: "/host/ledger/S3.sidecar.json",
      poolId: "claude/sonnet",
      completionSignal: "REVIEWER_STEP_COMPLETE",
      stepId: "S3",
      dispatchedAt: "2026-07-15T00:00:00.000Z",
      instanceId: "spawned:4242:2026-07-15T00:00:00.000Z",
    };
    class ResumeAfterS4Backend extends DispatchBackend {
      readonly landings: Array<WorkerLandingPayload | undefined> = [];
      // Widen the base's Promise<undefined> return so resume fixtures typecheck.
      override async findResumeState(): Promise<
        | undefined
        | {
            worktree: WorktreeHandle;
            stateDir: string;
            ledger: PersistentLedgerEntry[];
          }
      > {
        return {
          worktree: this.worktree,
          stateDir: "/resident/worktrees/.ledger-899-s4-resume",
          ledger: [
            {
              step: "S0",
              sessionId: "run",
              prompt_hash: "h0",
              branchHEAD: "abc",
              ts: "2026-07-15T00:00:00.000Z",
            },
            {
              step: "S1",
              sessionId: "run",
              prompt_hash: "h1",
              branchHEAD: "abc",
              ts: "2026-07-15T00:00:01.000Z",
            },
            {
              step: "S2",
              sessionId: "coder-s2",
              prompt_hash: "h2",
              branchHEAD: "abc",
              ts: "2026-07-15T00:00:02.000Z",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            },
            {
              step: "S3",
              sessionId: "reviewer-session-s4-resume",
              prompt_hash: "h3",
              branchHEAD: "abc",
              ts: "2026-07-15T00:00:03.000Z",
              output: {
                kind: "reviewer",
                findingsCount: 1,
                findings: [finding],
              },
              monitorHandle,
            },
            {
              step: "S4",
              sessionId: "run",
              prompt_hash: "h4",
              branchHEAD: "abc",
              ts: "2026-07-15T00:00:04.000Z",
            },
          ],
        };
      }
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        this.landings.push(landing);
        this.specs.push(spec);
        this.ctxs.push(ctx);
        this.dispatched.push(
          `${spec.id}:${spec.kind}:${spec.role}:${spec.session}:${spec.contextRetention}:${spec.skill ?? "—"}`,
        );
        if (spec.id === "S5") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer") {
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [], findingsCount: 0 },
          };
        }
        if (spec.kind === "coder") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        return {
          kind: "completed",
          output: { kind: "coder", committed: false, commitsAdded: 0 },
        };
      }
    }

    const backend = new ResumeAfterS4Backend();
    const result = await runOrchestrator({ issueNumber: 899, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThan(-1);
    expect(backend.ctxs[s5Index]?.blockingFindingCount).toBe(1);
    expect(backend.landings[s5Index]).toMatchObject({
      blockingFindings: [finding],
      rawReviewerArtifacts: {
        reviewerSessionId: "reviewer-session-s4-resume",
        stdoutPath: "/host/ledger/S3.stdout",
        sidecarPath: "/host/ledger/S3.sidecar.json",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
  });
});

describe("#331 an escalated agent worker preserves its sessionId in the ledger (codex R4)", () => {
  class EscalateWithSidBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      // S2 coder escalates and surfaces its real per-step session id.
      return {
        kind: "escalated",
        escalation: { reason: "design blocker", diagnosis: "need a human" },
        sessionId: "sess-coder-42",
      };
    }
  }

  it("records the escalated worker's sessionId on the step ledger entry", async () => {
    const backend = new EscalateWithSidBackend();
    // Capture the persisted ledger entries via a writeLedger spy.
    const persisted: { step: string; sessionId: string }[] = [];
    const spy = backend.writeLedger.bind(backend);
    backend.writeLedger = async (entry, dir): Promise<void> => {
      persisted.push({ step: entry.step, sessionId: entry.sessionId });
      return spy(entry, dir);
    };
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("escalate");
    const s2 = persisted.find((e) => e.step === "S2");
    expect(s2?.sessionId).toBe("sess-coder-42");
  });
});

describe("#331 stepSpecToWorkerSpec — builds the worker spec from a StepSpec", () => {
  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "sonnet",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: ["python", "typescript"],
  };

  it("maps a coder StepSpec to a coder worker (fresh by default, retain context, invoke /tdd)", () => {
    const w = stepSpecToWorkerSpec(coderSpec);
    expect(w.kind).toBe("coder");
    // Default dispatch is fresh; retention is retain (ADR 0026 — decoupled).
    expect(w.session).toBe("fresh");
    expect(w.contextRetention).toBe("retain");
    expect(w.skill).toBe("/tdd");
    expect(w.host).toBe("claude");
    expect(w.promptFile).toBe("coder_implement.md");
    expect(w.completionSignal).toBe("CODER_STEP_COMPLETE");
  });

  it("marks session:'resume' ONLY when the runner threads a resume (crash/escalate path)", () => {
    const w = stepSpecToWorkerSpec(coderSpec, "resume");
    expect(w.session).toBe("resume");
    // Even on the resume path, retention stays a separate by-kind concern.
    expect(w.contextRetention).toBe("retain");
  });

  it("maps a reviewer StepSpec to a reviewer worker (fresh, clean eyes, invoke /code-review)", () => {
    // dispatchWorker.ts stays generic (it serves the family layer's reviewer/cmr
    // kinds too); the role→reviewer mapping is independent of the single-slice
    // StepId set, so any valid id stands in here.
    const reviewerSpec: StepSpec = { ...coderSpec, role: "reviewer" };
    const w = stepSpecToWorkerSpec(reviewerSpec);
    expect(w.kind).toBe("reviewer");
    expect(w.session).toBe("fresh");
    expect(w.contextRetention).toBe("clean");
    expect(w.skill).toBe("/code-review");
  });
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

    override async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
      return {
        ...(await super.fetchIssueSnapshot(issueNumber)),
        body: this.coderRecBody,
      };
    }
  }

  it("dispatches every Coder-Rec token with the host required by its registered provider", async () => {
    // This fixture exercises host dispatch, not pool-separation rejection.
    // Keep Terra out of the CMR gate slots so a one-token Terra Coder-Rec is
    // dispatchable under the fail-closed roster rule.
    vi.stubEnv("ORCHESTRATOR_CMR_COMPLETENESS_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_CMR_CORRECTNESS_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS", "opus,agy");
    for (const entry of CODER_ROSTER) {
      const backend = new CoderRecDispatchBackend(`Coder-Rec: ${entry.id}`);
      const result = await runOrchestrator({ issueNumber: 796, backend });
      const coder = backend.specs.find((spec) => spec.id === "S2");

      expect(result.status).toBe("success");
      expect(coder).toMatchObject({
        model: entry.slug,
        host:
          entry.slug === "grok-4.5"
            ? "cursor"
            : entry.pool === "claude"
              ? "claude"
              : "codex",
      });
    }
  });

  it.each([
    ["gpt-5.6-terra", undefined, "codex"],
    ["sonnet", undefined, "claude"],
    ["grok-4.5", undefined, "cursor"],
    ["opencode-grok", undefined, "opencode"],
    ["grok-4.5", "grok-build", "grok"],
    ["grok-4.5", "codex-5h", "codex"],
  ] as const)(
    "derives host %s/%s from the registered provider",
    (model, billingPool, host) => {
      const worker = stepSpecToWorkerSpec(
        {
          id: "S2",
          role: "coder",
          promptFile: "coder_implement.md",
          model,
          completionSignal: "CODER_STEP_COMPLETE",
          maxIter: 5,
          soul: "coder",
          toolchain: [],
        },
        "fresh",
        billingPool,
      );

      expect(worker.host).toBe(host);
    },
  );

  it("derives every agent-worker factory host from its selected route slot", () => {
    const route = {
      ...SMOKED_ROUTE,
      slots: {
        ...SMOKED_ROUTE.slots,
        ship: "opencode-grok",
        verify: "gpt-5.6-terra",
        fixer: "sonnet",
        cleanup: "grok-4.5",
        docRelease: "opencode-grok",
      },
    };

    expect(familyShipWorkerSpec(route).host).toBe("opencode");
    expect(verifyWorkerSpec(route).host).toBe("codex");
    expect(fixerWorkerSpec(route).host).toBe("claude");
    expect(docReleaseWorkerSpec(route).host).toBe("opencode");
  });

  it("rebuilds the dispatched S2 spec after a real quota relay", async () => {
    const relayWorktree = mkdtempSync(join(tmpdir(), "host-relay-796-"));
    class QuotaRelayBackend extends CoderRecDispatchBackend {
      private quotaThrown = false;

      override async prepareWorktree(): Promise<WorktreeHandle> {
        return { ...this.worktree, path: relayWorktree };
      }

      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.id === "S2" && !this.quotaThrown) {
          this.quotaThrown = true;
          this.dispatched.push(
            `${spec.id}:${spec.kind}:${spec.role}:${spec.session}:${spec.contextRetention}:${spec.skill ?? "—"}`,
          );
          this.specs.push(spec);
          this.ctxs.push(ctx);
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "grok",
              resetAt: new Date("2026-07-10T13:00:00.000Z"),
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              killed: false,
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "grok",
                resetAt: "2026-07-10T13:00:00.000Z",
                reason: "quota limited (429); wait for reset",
                step: "S2",
                workerPid: 1,
                ts: "2026-07-10T12:00:00.000Z",
              },
            },
            pool: "grok",
            probe: { kind: "quota_limited" },
          });
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    try {
      const backend = new QuotaRelayBackend("Coder-Rec: grok-4.5");
      const result = await runOrchestrator({
        issueNumber: 796,
        backend,
        now: () => new Date("2026-07-10T12:00:00.000Z"),
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
            resetAt: new Date("2026-07-10T13:00:00.000Z"),
            parkThresholdMs: 1,
            models: ["grok-4.5"],
          },
          {
            id: "codex-5h",
            status: "live",
            parkThresholdMs: 1,
            models: ["grok-4.5"],
          },
        ],
      });

      const coderDispatches = backend.specs.filter((spec) => spec.id === "S2");
      expect(result.status).toBe("success");
      expect(coderDispatches).toHaveLength(2);
      expect(coderDispatches.map((spec) => spec.host)).toEqual(["cursor", "codex"]);
      expect(backend.ctxs.filter((ctx) => ctx.billingPool !== undefined)[0]?.billingPool).toBe(
        "codex-5h",
      );
    } finally {
      rmSync(relayWorktree, { recursive: true, force: true });
    }
  });
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
        : { kind: "reviewer", findings: [], findingsCount: 0 };
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
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    model: "sonnet",
    soul: "coder",
    toolchain: ["python"],
  };

  it("forwards a coder worker to runStep and wraps the output as completed", async () => {
    const be = new LegacyBackend();
    const res = await legacyDispatchWorker(be as unknown as Backend, coderWorker, {
      worktree: be.worktree,
    });
    expect(be.runStepCalls.length).toBe(1);
    expect(res.kind).toBe("completed");
    if (res.kind === "completed") {
      expect(res.output.kind).toBe("coder");
    }
  });

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
        be as unknown as Backend,
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

  it("does not expose unsupported outcome sidecars to fresh coder/reviewer workers", async () => {
    const worktreePath = mkdtempSync(join(tmpdir(), "dispatch-outcome-worktree-"));
    const stateDir = mkdtempSync(join(tmpdir(), "dispatch-outcome-state-"));
    try {
      execFileSync("git", ["init"], { cwd: worktreePath, stdio: "ignore" });
      const be = new LegacyBackend();
      const worktree = { ...be.worktree, path: worktreePath };

      await legacyDispatchWorker(be as unknown as Backend, { ...coderWorker, session: "fresh" }, {
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

      await legacyDispatchWorker(be as unknown as Backend, { ...coderWorker, id: "S5" }, {
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

  it("forwards a resume worker (resumeSessionId present) to resumeSession with the recorded session id", async () => {
    const be = new LegacyBackend();
    // The resume path is keyed by resumeSessionId. ADR 0030 uses separate
    // runner-visible worker steps for build/review/fix; this assertion only
    // covers forwarding one recorded worker session id through the legacy seam.
    await legacyDispatchWorker(be as unknown as Backend, { ...coderWorker, id: "S2" }, {
      worktree: be.worktree,
      resumeSessionId: "sess-abc",
    });
    expect(be.resumeCalls).toEqual(["sess-abc"]);
    expect(be.runStepCalls).toHaveLength(0);
  });

  it("FAIL-CLOSED: a cmr/merge worker has no legacy path — it throws, never mis-dispatched as coder/reviewer (online review r1)", async () => {
    // cmr/merge are family-only worker kinds with NO legacy backend method. If one
    // reached this public seam, the old fall-through coerced it via
    // workerSpecToStepSpec (dropping kind/skill) and ran it as a plain agent step.
    // The guard must REJECT it (3 bots).
    for (const kind of ["cmr", "merge"] as const) {
      const be = new LegacyBackend();
      // cmr/merge are family-only kinds whose id is not in the single-slice
      // worker-step set (S2/S3/S5/S6/S7) — borrow the build id S2 so the WorkerSpec
      // type-checks; the kind (not the id) is what the fail-closed guard rejects.
      await expect(
        legacyDispatchWorker(
          be as unknown as Backend,
          { ...coderWorker, id: "S2", kind },
          { worktree: be.worktree },
        ),
      ).rejects.toThrow(/no legacy dispatch path/);
      // It must NOT have leaked onto the agent-step seam.
      expect(be.runStepCalls.length).toBe(0);
      expect(be.resumeCalls.length).toBe(0);
    }
  });

  it("dispatchWorker prefers backend.dispatchWorker when present", async () => {
    let used = false;
    const be: Partial<Backend> = {
      async dispatchWorker(): Promise<WorkerResult> {
        used = true;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 0 },
        };
      },
    };
    await dispatchWorker(be as Backend, coderWorker, { modelRoute: SMOKED_ROUTE });
    expect(used).toBe(true);
  });
});
