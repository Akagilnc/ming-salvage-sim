import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  cleanupWorkerSpec,
  dispatchWorker,
  docReleaseWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
  shipWorkerSpec,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
} from "../src/dispatchWorker.js";
import { CODER_ROSTER } from "../src/coderRoster.js";
import { QuotaWaitForResetError } from "../src/quotaProbe.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import { resolveRouteModels, routeSmokeEntries } from "../src/modelRoutes.js";
import {
  readTelemetryRecords,
  type TelemetryCommitRecord,
  type TelemetryEnvironmentRecord,
} from "../src/telemetry.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  OnlineReviewLandingSnapshot,
  StepOutput,
  StepSpec,
  WorkerOutcomeLandingFile,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;
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
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
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
  pushCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-331",
    base: "main",
    path: "/resident/worktrees/issue-331",
  };

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
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
  async push(): Promise<void> {
    this.pushCount += 1;
    throw new Error("push should not be called directly (#331)");
  }
  async pollOnlineReviewState(input: {
    repo: string;
    prUrl: string;
    pollCount: number;
  }): Promise<OnlineReviewLandingSnapshot> {
    void input;
    return {
      prUrl: "pr://slice/offline-331",
      headOid: "deadbeef",
      totalFindingCount: 0,
      quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 0 },
        sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 },
        gemini: { state: "complete", findingCount: 0 },
      },
      droppedBots: [],
      threads: [],
      checkRuns: [],
    };
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
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
    // #596 review-loop skeleton (S9–S12): this spy backend has no real verify/
    // fixer/cleanup/docRelease worker, so delegate to the shared skeleton stubs
    // (same verdicts the legacy dispatcher returns).
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    // ship (S7) — pr_opened engages the online review loop (#600)
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: this.worktree.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-331",
      },
    };
  }
}

describe("#331 unified worker-dispatch seam — happy path", () => {
  it("continues from a coder/git discrepancy through the production dispatch seam to a fresh reviewer", async () => {
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
              selfReportDiscrepancy: {
                code: "coder_self_report_disagrees_with_git_commits",
                selfReportedCommitted: true,
                selfReportedCommitsAdded: 1,
                gitCommitCount: 0,
              },
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

  it("routes S2/S3 (and S7 ship) through dispatchWorker, never the legacy methods", async () => {
    const backend = new DispatchBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });

    expect(result.status).toBe("success");
    expect(result.branch).toBe("feat/orchestrator/issue-331");

    // Every worker step went through the unified seam — not runStep / push.
    expect(backend.legacyRunStepCount).toBe(0);
    expect(backend.pushCount).toBe(0);
  });

  it("dispatches the worker SEQUENCE S2→S3→S4→S7 with the right kind/role/session/retention/skill", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    // ADR 0030: implementation and review are separate runner-visible workers.
    // The reviewer is fresh/clean; a clean review is classified by S4 before S7.
    // #596: S7 ship is now INTERMEDIATE — the runner-visible review-loop skeleton
    // (S9 verify → S10 fixer → S12 docRelease → S11 cleanup) runs before S8.
    expect(backend.dispatched).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:reviewer:reviewer:fresh:clean:/code-review",
      "S7:ship:coder:fresh:clean:gstack-ship",
      "S9:verify:verify:fresh:clean:/verify",
      "S12:docRelease:docRelease:fresh:clean:/gstack-document-release",
      "S11:cleanup:cleanup:fresh:clean:/cleanup",
    ]);
  });

  it("each worker spec keeps the versioned promptFile (ADR 0018 #4 — no ad-hoc prompts)", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    const byId = Object.fromEntries(backend.specs.map((s) => [s.id, s]));
    expect(byId.S2.promptFile).toBe("coder_implement.md");
    expect(byId.S3.promptFile).toBe("reviewer_review.md");
    expect(byId.S7.promptFile).toBe("ship.md");
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

  it("records a committed coder HEAD movement before rejecting its malformed output", async () => {
    const root = mkdtempSync(join(tmpdir(), "orch-786-malformed-coder-"));
    const telemetryDir = join(root, ".ledger-786");
    execFileSync("git", ["init", "--initial-branch=main", root]);
    execFileSync("git", ["-C", root, "config", "user.email", "test@example.com"]);
    execFileSync("git", ["-C", root, "config", "user.name", "Test User"]);
    execFileSync("git", ["-C", root, "commit", "--allow-empty", "-m", "initial"]);

    class MalformedCoderTelemetryBackend extends DispatchBackend {
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
          execFileSync("git", ["-C", root, "commit", "--allow-empty", "-m", "worker commit"]);
          return {
            kind: "completed",
            output: {
              kind: "coder",
              committed: true,
              commitsAdded: "malformed",
            } as unknown as StepOutput,
          };
        }
        throw new Error("malformed coder output must stop before review");
      }
    }

    try {
      const backend = new MalformedCoderTelemetryBackend();
      const result = await runOrchestrator({ issueNumber: 786, backend });

      expect(result.status).toBe("error");
      let commits: TelemetryCommitRecord[] = [];
      await vi.waitFor(() => {
        commits = readTelemetryRecords(telemetryDir).filter(
          (record): record is TelemetryCommitRecord => record.phase === "commit",
        );
        expect(commits).toHaveLength(1);
      });
      expect(commits[0]).toMatchObject({ issue: 786, runId: backend.ctxs[0]?.runId });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("#331 a non-completed WorkerResult routes via workerResultToStep", () => {
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
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
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
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
  }

  it("a failed worker → S8(error) with the reason surfaced", async () => {
    const backend = new FailedBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.reason).toContain("container crashed");
  });
});

describe("#331 the S7 ship worker must return a SHIP payload (codex R2 guard)", () => {
  /** A backend whose S7 ship worker returns a completed NON-ship payload. */
  class WrongShipPayloadBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      if (spec.kind === "coder") {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
      if (spec.kind === "reviewer") {
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      // ship: a mis-wired backend returns a non-ship completed payload.
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol"],
          ...CMR_EVIDENCE,
        },
      };
    }
  }

  it("a persistently completed-but-non-ship S7 result exhausts bounded redispatch, never false-success", async () => {
    const backend = new WrongShipPayloadBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason).toContain("invalid delivery envelope");
    expect(result.errorPackage?.reason).toContain("after 3 dispatch attempts");
  });
});

describe("#596 S9 (verify) worker must return a valid verify payload — finding 6 defensive (runner r7b)", () => {
  /**
   * A backend that returns a *completed* result for S9 but with *undefined* output.
   * This exercises the !outputValid branch in the S9–S12 case (result.output may be
   * nullish even on "completed"). The guard must produce a clean errorTermination
   * (with message) and not throw TypeError on `result.output.kind`.
   */
  class S9UndefinedOutputBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      if (spec.kind === "coder") {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
      if (spec.kind === "reviewer") {
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      if (spec.id === "S9") {
        // Simulate a misbehaving / malformed S9 worker that "completed" but
        // yielded no output (or undefined). The runner's isValidVerifyResult
        // will reject; the error message construction must be null-safe.
        return { kind: "completed", output: undefined as unknown as StepOutput };
      }
      // For S10+ in this test path we can fall to skeleton or minimal; the run
      // will hit the S9 bad case first and terminate.
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      if (skeleton != null) return skeleton;
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: this.worktree.branch,
          status: "pr_opened",
          pr: "pr://slice/offline-331",
        },
      };
    }
  }

  it("S9 worker returning completed-with-undefined-output exhausts bounded redispatch without a TypeError", async () => {
    const backend = new S9UndefinedOutputBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason).toContain("invalid S9 envelope (output kind 'undefined')");
    expect(result.errorPackage?.reason).toContain("after 3 dispatch attempts");
    // Sanity: did not surface a TypeError string.
    expect(result.errorPackage?.reason).not.toMatch(/TypeError/i);
  });
});

describe("#331 an escalated SHIP worker → S8(escalate), not S8(error) (codex R4)", () => {
  class ShipEscalatesBackend extends DispatchBackend {
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.specs.push(spec);
      this.ctxs.push(ctx);
      if (spec.kind === "coder") {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
      if (spec.kind === "reviewer") {
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      // ship escalates (gstack-ship STOP/HITL), surfacing its session id.
      return {
        kind: "escalated",
        escalation: { reason: "needs human approval", diagnosis: "HITL gate" },
        sessionId: "sess-ship-7",
      };
    }
  }

  it("routes a STOP/HITL ship escalate to status=escalate and persists its sessionId", async () => {
    const backend = new ShipEscalatesBackend();
    const persisted: { step: string; sessionId: string }[] = [];
    const spy = backend.writeLedger.bind(backend);
    backend.writeLedger = async (entry, dir): Promise<void> => {
      persisted.push({ step: entry.step, sessionId: entry.sessionId });
      return spy(entry, dir);
    };
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("escalate");
    // The S7 escalate persists the worker session id (resume truth) — NOT lost
    // in the promptFile slot (codex cmr R6 finding).
    const s7 = persisted.find((e) => e.step === "S7");
    expect(s7?.sessionId).toBe("sess-ship-7");
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

  it("derives every route-backed worker factory host from its selected slot", () => {
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

    expect(shipWorkerSpec(route).host).toBe("opencode");
    expect(verifyWorkerSpec(route).host).toBe("codex");
    expect(fixerWorkerSpec(route).host).toBe("claude");
    expect(cleanupWorkerSpec(route).host).toBe("cursor");
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
  /** A minimal legacy backend exposing only runStep + push (no dispatchWorker). */
  class LegacyBackend {
    runStepCalls: StepSpec[] = [];
    resumeCalls: string[] = [];
    runStepOutcomeLandings: Array<WorkerOutcomeLandingFile | undefined> = [];
    resumeOutcomeLandings: Array<WorkerOutcomeLandingFile | undefined> = [];
    pushCalls = 0;
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
        : { kind: "reviewer", findings: [] };
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
    async push(): Promise<void> {
      this.pushCalls += 1;
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

  it("forwards a ship worker to push and wraps as completed ShipResult", async () => {
    const be = new LegacyBackend();
    const res = await legacyDispatchWorker(
      be as unknown as Backend,
      {
        ...coderWorker,
        id: "S7",
        kind: "ship",
        skill: "gstack-ship",
        session: "fresh",
        promptFile: "ship.md",
      },
      { worktree: be.worktree },
    );
    expect(be.pushCalls).toBe(1);
    expect(res.kind).toBe("completed");
    if (res.kind === "completed") {
      expect(res.output.kind).toBe("ship");
    }
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
