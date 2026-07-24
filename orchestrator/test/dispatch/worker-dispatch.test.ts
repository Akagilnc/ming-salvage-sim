import {
  execFileSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  runOrchestrator,
  decodeReviewerOpenCountReceipt,
  dispatchWorker,
  landingWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
  workerResultToStep,
  familyShipWorkerSpec,
  getCoderRoster,
  QuotaWaitForResetError,
  resolveRouteModels,
  routeSmokeEntries,
  readTelemetryRecords,
  TelemetryCommitRecord,
  TelemetryEnvironmentRecord,
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
  SMOKED_ROUTE,
  DispatchBackend,
} from "./worker-dispatch.shared.js";

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

    expect(result.status).toBe("completed");
    expect(backend.dispatched.slice(0, 2)).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:verify:verify:fresh:clean:/verify",
    ]);
  });

  it("dispatches S2→S3 before the local S7 handoff", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    // ADR 0030: implementation and review are separate runner-visible workers.
    // S7 is not a worker: the family merger consumes the local child commit.
    expect(backend.dispatched).toEqual([
      "S2:coder:coder:fresh:retain:/tdd",
      "S3:verify:verify:fresh:clean:/verify",
    ]);
  });

  it("each worker spec keeps the versioned promptFile (ADR 0018 #4 — no ad-hoc prompts)", async () => {
    const backend = new DispatchBackend();
    await runOrchestrator({ issueNumber: 331, backend });

    const byId = Object.fromEntries(backend.specs.map((s) => [s.id, s]));
    expect(byId.S2.promptFile).toBe("coder_implement.md");
    expect(byId.S3.promptFile).toBe("judge_station.md");
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
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
  }

  it("an escalated worker → S8(escalate), NOT S8(error) (high cmr finding)", async () => {
    const backend = new EscalateBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    // The escalate edge is preserved through the unified seam.
    expect(result.status).toBe("parked");
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
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
  }

  it("a failed worker → S8(error) with the reason surfaced", async () => {
    const backend = new FailedBackend();
    const result = await runOrchestrator({ issueNumber: 331, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage?.reason).toContain("container crashed");
  });
});

describe("ADR 0131 reviewer count envelope", () => {
  it("residual open-count without authored body fails loud at coder-fix edge (ADR 0138 R4-C1)", async () => {
    class ResidualNoBodyBackend extends DispatchBackend {
      reviewerCalls = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          this.reviewerCalls += 1;
          if (this.reviewerCalls > 1) return super.dispatchWorker(spec, ctx);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          return {
            kind: "completed",
            // Positive residual open-count with no authored body — runner must
            // not invent "[residual] open-count continue …"; fail loud instead.
            output: {
              kind: "reviewer",
              findingsCount: 1,
              findings: [],
            },
            sessionId: "reviewer-session-residual-no-body",
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

    const backend = new ResidualNoBodyBackend();
    const result = await runOrchestrator({ issueNumber: 978, backend });

    expect(result.status).toBe("completed");
    expect(backend.specs.some((spec) => spec.id === "S5")).toBe(true);
    expect(JSON.stringify(result)).not.toContain("[residual] open-count continue");
  });

  it("dispatches S5 when the reviewer returns the wrong role kind", async () => {
    class WrongReviewerKindBackend extends DispatchBackend {
      reviewerCalls = 0;
      override async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
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

    expect(result.status).toBe("completed");
    expect(backend.specs.some((spec) => spec.id === "S5")).toBe(true);
    expect(JSON.stringify(backend.persistedLedger)).not.toContain('"escalationKind":"decision"');
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
    expect(result.status).toBe("parked");
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
    // #928: production seats are single-iter; fixture matches that contract.
    maxIter: 1,
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
    expect(Object.prototype.hasOwnProperty.call(w, "completionSignal")).toBe(false);
    expect(w.maxIter).toBe(1);
  });

  it("marks session:'resume' ONLY when the runner threads a resume (crash/escalate path)", () => {
    const w = stepSpecToWorkerSpec(coderSpec, "resume");
    expect(w.session).toBe("resume");
    // Even on the resume path, retention stays a separate by-kind concern.
    expect(w.contextRetention).toBe("retain");
  });

  it("maps a residual reviewer StepSpec to reviewer kind (fresh, clean; skill undefined)", () => {
    // Live reviewer workers are review-panel legs (#1094/#1126) with skill
    // undefined on the declarative WorkerSpec. Residual role→kind mapping here
    // must not reintroduce `/code-review` as a second dispatch truth.
    const reviewerSpec: StepSpec = { ...coderSpec, role: "reviewer" };
    const w = stepSpecToWorkerSpec(reviewerSpec);
    expect(w.kind).toBe("reviewer");
    expect(w.session).toBe("fresh");
    expect(w.contextRetention).toBe("clean");
    expect(w.skill).toBeUndefined();
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
  }

  it("dispatches every Coder-Rec token with the host required by its registered provider", async () => {
    // This fixture exercises host dispatch, not pool-separation rejection.
    // Keep Terra out of the CMR gate slots so a one-token Terra Coder-Rec is
    // dispatchable under the fail-closed roster rule.
    vi.stubEnv("ORCHESTRATOR_CMR_COMPLETENESS_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_CMR_CORRECTNESS_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "opus");
    vi.stubEnv("ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS", "opus,agy");
    for (const entry of getCoderRoster()) {
      const backend = new CoderRecDispatchBackend(`Coder-Rec: ${entry.id}`);
      const result = await runOrchestrator({ issueNumber: 796, backend });
      const coder = backend.specs.find((spec) => spec.id === "S2");

      expect(result.status).toBe("completed");
      expect(coder).toMatchObject({
        model: entry.slug,
        host:
          entry.slug === "grok-4.5"
            ? "grok"
            : entry.pool === "claude"
              ? "claude"
              : "codex",
      });
    }
  });

  it("derives every agent-worker factory host from its selected route slot", () => {
    const route = {
      ...SMOKED_ROUTE,
      slots: {
        ...SMOKED_ROUTE.slots,
        ship: "agy",
        verify: "gpt-5.6-terra",
        fixer: "sonnet",
        cleanup: "grok-4.5",
        landing: "agy",
      },
    };

    expect(familyShipWorkerSpec(route).host).toBe("agy");
    expect(verifyWorkerSpec(route).host).toBe("codex");
    expect(fixerWorkerSpec(route).host).toBe("claude");
    expect(landingWorkerSpec(route).host).toBe("agy");
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
            pool: "grok"
          });
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    try {
      const backend = new QuotaRelayBackend("Coder-Rec: grok-4.5 → terra@med");
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
            // #905: next roster model (terra), not a grok-4.5 换马甲 — SuperGrok
            // is the only executable channel for that slug.
            models: ["terra@med", "gpt-5.6-terra"],
          },
        ],
      });

      const coderDispatches = backend.specs.filter((spec) => spec.id === "S2");
      expect(result.status).toBe("completed");
      expect(coderDispatches).toHaveLength(2);
      // #905: first baton grok-4.5 → SuperGrok; relay advances roster to terra@med.
      expect(coderDispatches.map((spec) => spec.host)).toEqual(["grok", "codex"]);
      expect(coderDispatches.map((spec) => spec.model)).toEqual([
        "grok-4.5",
        "gpt-5.6-terra",
      ]);
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

  it("forwards a coder worker to runStep and wraps the output as completed", async () => {
    const be = new LegacyBackend();
    const res = await legacyDispatchWorker(be, coderWorker, {
      worktree: be.worktree,
    });
    expect(be.runStepCalls.length).toBe(1);
    expect(res.kind).toBe("completed");
    if (res.kind === "completed") {
      expect(res.output.kind).toBe("coder");
    }
  });

  it("forwards a resume worker (resumeSessionId present) to resumeSession with the recorded session id", async () => {
    const be = new LegacyBackend();
    // The resume path is keyed by resumeSessionId. ADR 0030 uses separate
    // runner-visible worker steps for build/review/fix; this assertion only
    // covers forwarding one recorded worker session id through the legacy seam.
    await legacyDispatchWorker(be, { ...coderWorker, id: "S2" }, {
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
          be,
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
