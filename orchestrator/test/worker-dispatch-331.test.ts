import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  dispatchWorker,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
} from "../src/dispatchWorker.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

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
    // ship (S7)
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
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

  it("dispatches the worker SEQUENCE S2→S3→S7 with the right kind/role/session/retention/skill", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    // session is `fresh` for the normal S2/S3/S7 path (ADR 0026: a worker is
    // `resume` ONLY on the crash/escalate-resume path); contextRetention is
    // `retain` for the coder, `clean` for review/ship.
    expect(backend.dispatched).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:reviewer:reviewer:fresh:clean:/review",
      "S7:ship:coder:fresh:clean:gstack-ship",
    ]);
  });

  it("each worker spec keeps the versioned promptFile (ADR 0018 #4 — no ad-hoc prompts)", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    const byId = Object.fromEntries(backend.specs.map((s) => [s.id, s]));
    expect(byId.S2.promptFile).toBe("coder_implement.md");
    expect(byId.S3.promptFile).toBe("reviewer_full_review.md");
  });

  it("hands the resident worktree to every single-slice worker via DispatchContext", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    for (const ctx of backend.ctxs) {
      expect(ctx.worktree).toEqual(backend.worktree);
    }
  });
});

describe("#331 fix-loop routes the S5 fix worker (resume) with prev findings", () => {
  /** A reviewer that emits one fix_now finding on S3, then approves on S6. */
  class FixLoopBackend extends DispatchBackend {
    private reviewCount = 0;
    override async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.dispatched.push(
        `${spec.id}:${spec.kind}:${spec.session}:${spec.contextRetention}`,
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
        this.reviewCount += 1;
        const findings: Finding[] =
          this.reviewCount === 1
            ? [
                {
                  severity: "critical",
                  category: "correctness",
                  claim_quote: "x",
                  location: "f.ts:1",
                  suggested_fix: "fix it",
                  action: "fix_now",
                },
              ]
            : [];
        return { kind: "completed", output: { kind: "reviewer", findings } };
      }
      return {
        kind: "completed",
        output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
      };
    }
  }

  it("S3(findings)→S5 fix→S6(approve)→S7, with the fix worker carrying fix_now findings", async () => {
    const backend = new FixLoopBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });

    expect(result.status).toBe("success");
    // A NORMAL S5 fix round is session:"fresh" (NOT the resume path) with
    // contextRetention:"retain" — the ADR 0026 invariant the codex R3 finding
    // caught: a normal fix must not use the crash/escalate resume path.
    expect(backend.dispatched).toEqual([
      "S2:coder:fresh:retain",
      "S3:reviewer:fresh:clean",
      "S5:coder:fresh:retain",
      "S6:reviewer:fresh:clean",
      "S7:ship:fresh:clean",
    ]);

    // The S5 fix worker received the round's fix_now findings (US#13) via ctx —
    // its retention mechanism, NOT a resumeSessionId.
    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s5Idx).toBeGreaterThanOrEqual(0);
    const s5spec = backend.specs[s5Idx];
    expect(s5spec.session).toBe("fresh");
    expect(s5spec.contextRetention).toBe("retain");
    const s5ctx = backend.ctxs[s5Idx];
    expect(s5ctx.resumeSessionId).toBeUndefined();
    expect(s5ctx.prevFindings?.length).toBe(1);
    expect(s5ctx.prevFindings?.[0].action).toBe("fix_now");
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
      return { kind: "completed", output: { kind: "cmr", converged: true } };
    }
  }

  it("a completed-but-non-ship S7 result → S8(error), NOT a false success", async () => {
    const backend = new WrongShipPayloadBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason).toContain("non-ship output kind");
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

  it("maps a reviewer StepSpec to a reviewer worker (fresh, clean eyes, invoke /review)", () => {
    const reviewerSpec: StepSpec = { ...coderSpec, id: "S3", role: "reviewer" };
    const w = stepSpecToWorkerSpec(reviewerSpec);
    expect(w.kind).toBe("reviewer");
    expect(w.session).toBe("fresh");
    expect(w.contextRetention).toBe("clean");
    expect(w.skill).toBe("/review");
  });
});

describe("#331 legacyDispatchWorker — forwards to the existing methods", () => {
  /** A minimal legacy backend exposing only runStep + push (no dispatchWorker). */
  class LegacyBackend {
    runStepCalls: StepSpec[] = [];
    resumeCalls: string[] = [];
    pushCalls = 0;
    lastFixFindings?: ReadonlyArray<Finding>;
    worktree: WorktreeHandle = {
      branch: "b",
      base: "main",
      path: "/wt",
    };
    async runStep(
      spec: StepSpec,
      _wt: WorktreeHandle,
      fixNow?: ReadonlyArray<Finding>,
    ): Promise<StepOutput> {
      this.runStepCalls.push(spec);
      this.lastFixFindings = fixNow;
      return spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 1 }
        : { kind: "reviewer", findings: [] };
    }
    async resumeSession(
      _spec: StepSpec,
      _wt: WorktreeHandle,
      sid: string,
      fixNow?: ReadonlyArray<Finding>,
    ): Promise<StepOutput> {
      this.resumeCalls.push(sid);
      this.lastFixFindings = fixNow;
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

  it("forwards a resume fix worker (resumeSessionId present) to resumeSession with findings", async () => {
    const be = new LegacyBackend();
    const findings: Finding[] = [
      {
        severity: "high",
        category: "c",
        claim_quote: "q",
        location: "l",
        suggested_fix: "s",
        action: "fix_now",
      },
    ];
    await legacyDispatchWorker(be as unknown as Backend, { ...coderWorker, id: "S5" }, {
      worktree: be.worktree,
      resumeSessionId: "sess-abc",
      prevFindings: findings,
    });
    expect(be.resumeCalls).toEqual(["sess-abc"]);
    expect(be.lastFixFindings).toEqual(findings);
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
