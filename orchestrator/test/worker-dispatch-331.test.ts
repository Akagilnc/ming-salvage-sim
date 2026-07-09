import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  dispatchWorker,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
} from "../src/dispatchWorker.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
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
  WorktreeHandle,
} from "../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

/**
 * #331 — the unified worker-dispatch seam.
 *
 * A fake Backend that implements ONLY the new `dispatchWorker` seam (plus the S0/S1
 * read seams the runner needs to reach the worker steps). It records every
 * dispatched WorkerSpec so we can assert the SEQUENCE + each spec — replacing the
 * old per-method (runStep/push) assertions (PRD #330 Testing Decisions).
 */
class DispatchBackend implements Backend {
  /** Ordered log of every worker dispatched: "id:kind:role:session:skill". */
  readonly dispatched: string[] = [];
  /** The full WorkerSpec of each dispatch, in order. */
  readonly specs: WorkerSpec[] = [];
  /** The DispatchContext of each dispatch, in order. */
  readonly ctxs: DispatchContext[] = [];
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
  }) {
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
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {}

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
      "S12:docRelease:docRelease:fresh:clean:/doc-release",
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
    expect(result.status).toBe("error");
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }
  }

  it("a completed-but-non-ship S7 result → S8(error), NOT a false success", async () => {
    const backend = new WrongShipPayloadBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason).toContain("non-ship output kind");
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

  it("S9 worker returning completed-with-undefined-output → errorTermination with the non-crash message, not a TypeError", async () => {
    const backend = new S9UndefinedOutputBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("error");
    // Must be the clean message from the !outputValid branch (defensive String()).
    expect(result.errorPackage?.reason).toContain("S9 worker returned non-S9 output kind 'undefined'");
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
    await dispatchWorker(be as Backend, coderWorker, {});
    expect(used).toBe(true);
  });
});
