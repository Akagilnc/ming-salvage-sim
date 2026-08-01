import {
  describe,
  expect,
  it,
  runVerifyCmr,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
  mkdtempSync,
  rmSync,
  tmpdir,
  join,
  resolveActiveModelRoute,
  smokeRouteModels,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  legacyCmrScriptToWorkerOutput,
  liveCmrJudgeContinue,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  buildExplicitLandingLiveHooks,
  CMR_EVIDENCE,
  completedJudgeGreen,
  CapableFamilyBackend,
} from "./final-gate-dispatch.shared.js";
import { completeReviewPanelLegWorker } from "../../helpers/review-panel-leg-dispatch.js";

describe("#331 family verify-cmr routes cmr + PR through dispatchFamilyWorker", () => {
  it("derives every family worker host from its route-selected model", () => {
    const baseRoute = resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" });
    const route = {
      ...baseRoute,
      slots: {
        ...baseRoute.slots,
        cmrCompleteness: "agy",
        cmrCorrectness: "grok-4.5",
        coderFix: "sonnet",
        ship: "gpt-5.6-terra",
      },
    };

    expect(cmrWorkerSpec("fresh", "completeness", route).host).toBe("agy");
    expect(cmrWorkerSpec("fresh", "correctness", route).host).toBe("grok");
    expect(familyCoderFixWorkerSpec(route).host).toBe("claude");
    expect(familyShipWorkerSpec(route).host).toBe("codex");
  });

  it("routes the family coder-fix worker through the fixer soul", () => {
    expect(familyCoderFixWorkerSpec().soul).toBe("fixer");
  });

  it("legacy monitored dispatch confirms only after the physical launch", async () => {
    const events: string[] = [];
    const backend = {
      dispatchWorker: async (): Promise<WorkerResult> => {
        events.push("launched");
        return {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        };
      },
    } as unknown as FamilyBackend;

    await dispatchFamilyWorkerWithMonitor(
      backend,
      cmrWorkerSpec(),
      {
        familyBase: "family/base",
        modelRoute: await smokeRouteModels(
          resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" }),
          async () => ({ cliVersion: "test" }),
        ),
      },
      undefined,
      { onDispatchConfirmed: () => {
        events.push("confirmed");
      } },
    );

    expect(events).toEqual(["launched", "confirmed"]);
  });

  it("final barrier: green verify → cmr worker (converged) → ship worker (PR), ok", async () => {
    const be = new CapableFamilyBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });

    expect(res).toEqual({ ok: true, ran: true });
    expect(be.cmrCalls).toEqual([
      { familyBase: "feat/330", cmrPass: "completeness" },
      { familyBase: "feat/330", cmrPass: "correctness" },
    ]);
    expect(be.prCalls).toEqual([{ familyBase: "feat/330" }]);
  });

  it("final barrier: a positive reviewer open-count enters coder-fix (no PR), ok:false", async () => {
    const be = new CapableFamilyBackend();
    be.cmrConverged = false;
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });

    expect(res.ok).toBe(false);
    // cmr ran; PR did NOT open while the reviewer-declared count is positive.
    expect(be.cmrCalls.length).toBe(1);
    expect(be.prCalls.length).toBe(0);
  });

  it("forwards llmResolvedChildren through the DispatchContext to the cmr request", async () => {
    const be = new CapableFamilyBackend();
    await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
      llmResolvedChildren: [42, 43],
    });
    expect(be.cmrCalls).toEqual([
      {
        familyBase: "feat/330",
        cmrPass: "completeness",
        llmResolvedChildren: [42, 43],
      },
      {
        familyBase: "feat/330",
        cmrPass: "correctness",
        llmResolvedChildren: [42, 43],
      },
    ]);
  });
});

describe("#331 verify-cmr runs the cmr/PR worker via the NEW seam even without legacy methods", () => {
  /**
   * A backend that implements the UNIFIED `dispatchWorker` seam but NONE of the
   * legacy per-method hooks. The verify-cmr gate must
   * accept it (codex cmr finding: gating on the legacy method alone wrongly
   * fail-safed a new-seam-only backend to a stage fail-safe gate).
   */
  class NewSeamFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    dispatched: Array<{
      kind: WorkerSpec["kind"];
      promptFile: string;
      cmrPass?: DispatchContext["cmrPass"];
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }> = [];
    readonly ledger: FamilyLedgerEntry[] = [];
    completenessConverged = true;
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async readFamilyHead(): Promise<string> {
      return "head-1";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      this.dispatched.push({
        kind: spec.kind,
        promptFile: spec.promptFile,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        ...(ctx.escalationAnswer !== undefined
          ? { escalationAnswer: ctx.escalationAnswer }
          : {}),
      });
      if (spec.kind === "cmr") {
        const passGreen =
          ctx.cmrPass === "completeness" ? this.completenessConverged : true;
        if (passGreen) {
          return completedJudgeGreen();
        }
        // Live judge continue with synthetic open key (coder-fix path).
        return {
          kind: "completed",
          output: liveCmrJudgeContinue([], {
            findingsCount: 1,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            reason: "family base is incomplete",
            ...CMR_EVIDENCE,
          }),
        };
      }
      if (spec.kind === "ship") {
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: "feat/330",
            pr: "https://github.com/test/repo/pull/330",
            prHead: "head-1",
            status: "pr_opened",
          },
        };
      }
      if (
        spec.kind === "collector" ||
        spec.kind === "verify" ||
        spec.kind === "fixer" ||
        spec.kind === "landing"
      ) {
        return {
          kind: "completed",
          output:
            spec.kind === "collector"
              ? {
                  kind: "collector",
                  evidence: {
                    prUrl: "pr://offline",
                    headOid: "offline-head",
                    totalFindingCount: 0,
                    quiescent: true,
                    bots: {},
                    droppedBots: [],
                    threads: [],
                    checkRuns: [],
                    checkRunsEmptyMeans: "converged",
                  },
                }
              : spec.kind === "verify"
              ? { kind: "verify", status: "converged" }
              : spec.kind === "fixer"
                ? {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                }
                : { kind: "landing", released: true },
        };
      }
      return { kind: "failed", reason: `unexpected worker ${spec.kind}` };
    }
  }

  it("final barrier reaches the cmr + ship workers through dispatchWorker (no legacy methods)", async () => {
    const be = new NewSeamFamilyBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    expect(res).toEqual({ ok: true, ran: true });
    expect(be.dispatched).toEqual([
      {
        kind: "cmr",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
      },
      {
        kind: "cmr",
        promptFile: "integrated_cmr_correctness.md",
        cmrPass: "correctness",
      },
      { kind: "ship", promptFile: "family_ship.md" },
      { kind: "collector", promptFile: "collector.md" },
      { kind: "verify", promptFile: "verify.md" },
      { kind: "landing", promptFile: "landing.md" },
    ]);
  });

  it("threads the human escalation answer through both CMR passes and the ship worker", async () => {
    const be = new NewSeamFamilyBackend();
    const escalationAnswer = {
      event: "escalation_answered" as const,
      answer: "continue-same-class",
      note: "Human approved another family gate pass.",
    };

    await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
      escalationAnswer,
    });

    expect(be.dispatched).toEqual([
      {
        kind: "cmr",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
        escalationAnswer,
      },
      {
        kind: "cmr",
        promptFile: "integrated_cmr_correctness.md",
        cmrPass: "correctness",
        escalationAnswer,
      },
      { kind: "ship", promptFile: "family_ship.md", escalationAnswer },
      { kind: "collector", promptFile: "collector.md" },
      { kind: "verify", promptFile: "verify.md" },
      { kind: "landing", promptFile: "landing.md" },
    ]);
  });
});

describe("#331 the family ship worker must return a SHIP payload (codex R2 guard)", () => {
  /** A new-seam backend whose ship worker returns a completed NON-ship payload. */
  class WrongShipFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(): Promise<void> {}
    async readFamilyLedger(): Promise<[]> {
      return [];
    }
    async readFamilyHead(): Promise<string> {
      return "head-1";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      // ship: a mis-wired backend returns a non-ship completed payload.
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }
  }

  it("a completed-but-non-ship family ship result → ship_failed gate (ok:false)", async () => {
    const be = new WrongShipFamilyBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    // #1090: off-contract / missing ship.pr no longer falls back to a branch
    // name — resolveFamilyShipPr yields nothing in unit tests → ship_failed.
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
  });
});

describe("#336 cmr S336 r4 — the terminal family gate re-asserts the ship success contract", () => {
  /**
   * A new-seam-only backend whose ship worker returns a `completed {kind:"ship"}`
   * payload that the consumer would (pre-r4) trust on the discriminant ALONE. The
   * terminal family gate must independently re-assert the family ship contract
   * (branch === familyBase, status === "pr_opened", pr a non-empty string) — a
   * backend that implements the seam but ships an off-contract success is a false
   * family delivery (the PR never opened / opened on the wrong branch).
   */
  class OffContractShipFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    shipOutput: WorkerResult;
    constructor(shipOutput: WorkerResult) {
      this.shipOutput = shipOutput;
    }
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(): Promise<void> {}
    async readFamilyLedger(): Promise<[]> {
      return [];
    }
    async readFamilyHead(): Promise<string> {
      return "head-1";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      if (
        spec.kind === "collector" ||
        spec.kind === "verify" ||
        spec.kind === "fixer" ||
        spec.kind === "cleanup" ||
        spec.kind === "landing"
      ) {
        return {
          kind: "completed",
          output:
            spec.kind === "collector"
              ? {
                  kind: "collector",
                  evidence: {
                    prUrl: "pr://offline",
                    headOid: "offline-head",
                    totalFindingCount: 0,
                    quiescent: true,
                    bots: {},
                    droppedBots: [],
                    threads: [],
                    checkRuns: [],
                    checkRunsEmptyMeans: "converged",
                  },
                }
              : spec.kind === "verify"
              ? { kind: "verify", status: "converged" }
              : spec.kind === "fixer"
                ? {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                }
                : spec.kind === "cleanup"
                  ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                  : { kind: "landing", released: true },
        };
      }
      return this.shipOutput;
    }
  }

  async function gate(shipOutput: WorkerResult): Promise<FamilyVerifyResult> {
    return runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: new OffContractShipFamilyBackend(shipOutput),
    });
  }

  it("a completed ship with status 'pushed' (not pr_opened) ⇒ ship_failed gate (#1090)", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pushed" },
    });
    // #1090: status pushed + no PR URL → no resolvable PR → ship_failed (no
    // branch-name synthesis into the shipped ledger).
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
  });

  it("a completed ship missing its pr URL ⇒ ship_failed gate (#1090)", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened" },
    });
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
  });

  it("a completed ship with a blank pr URL ⇒ ship_failed gate (#1090)", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened", pr: "   " },
    });
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
  });

  it("a completed ship that reports the wrong branch follows host-verified PR truth", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "worker-reported-wrong-branch",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/330",
        prHead: "worker-reported-stale-head",
      },
    });
    expect(res).toEqual({ ok: true, ran: true });
  });

  it("ignores a missing worker-reported PR head", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "feat/330",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/330",
      },
    });
    expect(res).toEqual({ ok: true, ran: true });
  });

  it("ignores a blank worker-reported PR head", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "feat/330",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/330",
        prHead: "   ",
      },
    });
    expect(res).toEqual({ ok: true, ran: true });
  });

  it("a completed pr_opened ship on familyBase with a real pr ⇒ ok (the contract holds)", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "feat/330",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/330",
        prHead: "head-1",
      },
    });
    expect(res).toEqual({ ok: true, ran: true });
  });

  it("ignores a stale worker-reported PR head", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "feat/330",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/330",
        prHead: "stale-head",
      },
    });
    expect(res).toEqual({ ok: true, ran: true });
  });
});

describe("#330 a failed/wrong-kind final cmr/ship worker writes a durable aborted event (online review r3, codex P2)", () => {
  /**
   * A new-seam backend that RECORDS the ledger, with the cmr + ship worker outputs
   * configurable. A `completed` worker whose output kind is WRONG (cmr worker
   * returning a ship-shaped payload, or vice-versa) is the wrong-kind case the
   * verify-cmr hook fail-safes with a stage-named gate — and (r3) must leave a durable
   * `aborted` event so the failed FINAL barrier survives to the ledger for resume.
   */
  class RecordingFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    readonly ledger: FamilyLedgerEntry[] = [];
    constructor(
      private readonly cmrOut: WorkerResult,
      private readonly shipOut: WorkerResult,
    ) {}
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async readFamilyHead(): Promise<string> {
      return "head-1";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      return spec.kind === "cmr" ? this.cmrOut : this.shipOut;
    }
  }

  class NoShipCapabilityAfterCmrBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    readonly ledger: FamilyLedgerEntry[] = [];
    readonly aborted: FamilyLedgerEntry[] = [];
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async readFamilyHead(): Promise<string> {
      return "head-after-cmr";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    // #919: live green needs kind:judge. Ship remains unavailable — dispatchWorker
    // returns failed for non-cmr so the final barrier still dies as ship_failed
    // (the pre-#919 backend had no dispatchWorker at all; residual unusable now
    // fails earlier as cmr_failed, so this keeps the ship-unavailability intent).
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      return {
        kind: "failed",
        reason:
          "family ship worker unavailable after converged CMR: backend has no ship capability",
      };
    }
  }

  class PrHeadMismatchRecordingBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    readonly ledger: FamilyLedgerEntry[] = [];
    private shipDispatched = false;
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async readFamilyHead(): Promise<string> {
      return this.shipDispatched ? "post-ship-head" : "cmr-head";
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      if (spec.kind === "ship") {
        this.shipDispatched = true;
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: "feat/445",
            status: "pr_opened",
            pr: "https://github.com/test/repo/pull/445",
            prHead: "stale-pr-head",
          },
        };
      }
      // #940: host no longer caps online-review rounds. Returning non-verify
      // cargo forever would hang the for(;;) loop — fail closed so the stage
      // still proves ship persisted before online-review failure.
      return {
        kind: "failed",
        reason: `test pin: online-review ${spec.kind} incomplete after ship`,
      };
    }
  }

  it("no ship capability after converged cmr writes durable aborted(final) over stale success", async () => {
    const backend = new NoShipCapabilityAfterCmrBackend();

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/445",
      familyBackend: backend,
    });

    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
    expect(backend.ledger.filter((e) => e.status === "cmr_passed")).toHaveLength(2);
    const latest = backend.ledger.at(-1);
    expect(latest?.status).toBe("aborted");
    expect(latest?.phase).toBe("final");
    // #919: CMR is live judge-green; ship dies via dispatchWorker failed
    // (pre-#919 used dispatchWorker===undefined after residual silent-clean).
    expect(latest?.reason).toMatch(/family ship worker (failed|unavailable)/i);
    expect(latest?.stopSummary?.reason).toBe("ship_failed");
    expect(latest?.stopSummary?.summary).toMatch(
      /family ship worker (failed|unavailable)|PR/i,
    );
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("worker-reported PR-head mismatch cannot block the host family head from being shipped", async () => {
    const backend = new PrHeadMismatchRecordingBackend();

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/445",
      familyBackend: backend,
    });

    // This minimal backend returns a ship payload to the later online-review
    // worker too, so that unrelated stage remains incomplete. The ship gate itself
    // must nevertheless have persisted host HEAD truth before reaching it.
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "online_review_failed",
    });
    const shipped = backend.ledger.find((e) => e.status === "shipped");
    expect(shipped?.familyHeadAfter).toBe("post-ship-head");
    expect(shipped).toMatchObject({ status: "shipped" });
  });
});

describe("#331 an escalated family cmr/ship worker calls escalateFamily (codex R4)", () => {
  class EscalatingFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    escalations: FamilyEscalation[] = [];
    ledger: FamilyLedgerEntry[] = [];
    escalateOn: "cmr" | "ship";
    constructor(escalateOn: "cmr" | "ship") {
      this.escalateOn = escalateOn;
    }
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async escalateFamily(e: FamilyEscalation): Promise<void> {
      this.escalations.push(e);
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === this.escalateOn) {
        return {
          kind: "escalated",
          escalation: { reason: "stuck", diagnosis: "needs human" },
        };
      }
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      return {
        kind: "completed",
        output: { kind: "ship", branch: "fb", pr: "https://github.com/test/repo/pull/1090", status: "pr_opened" },
      };
    }
  }

  class ShipEscalatesWithoutEscalateSeamBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    ledger: FamilyLedgerEntry[] = [];
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      const autoPanelLeg = completeReviewPanelLegWorker(spec);
      if (autoPanelLeg !== undefined) return autoPanelLeg;
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      return {
        kind: "escalated",
        escalation: { reason: "stuck", diagnosis: "needs human" },
      };
    }
  }

  it("an escalated cmr worker → escalateFamily + ok:false (not a bare stage fail-safe)", async () => {
    const be = new EscalatingFamilyBackend("cmr");
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    expect(res.ok).toBe(false);
    expect(be.escalations.length).toBe(1);
    expect(be.escalations[0]?.reason).toContain("stuck");
  });

  it("an escalated family ship worker → escalateFamily + ok:false", async () => {
    const be = new EscalatingFamilyBackend("ship");
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    expect(res.ok).toBe(false);
    expect(be.escalations.length).toBe(1);
    expect(be.escalations[0]).toMatchObject({
      reason: "stuck",
      diagnosis: "needs human",
      escalationKind: "decision",
    });
    expect(be.escalations[0]?.stopSummary).toMatchObject({
      reason: "decision_gate_park",
      summary: "stuck — needs human",
    });
    expect(be.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason: expect.stringContaining("family ship worker escalated"),
      stopSummary: expect.objectContaining({
        reason: "decision_gate_park",
        summary: "stuck — needs human",
      }),
    }));
  });

  it("an escalated family ship worker still writes durable abort when no escalateFamily seam exists", async () => {
    const be = new ShipEscalatesWithoutEscalateSeamBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });

    expect(res.ok).toBe(false);
    expect(be.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason: expect.stringContaining("family ship worker escalated"),
      stopSummary: expect.objectContaining({
        reason: "decision_gate_park",
        summary: "stuck — needs human",
      }),
    }));
  });
});

describe("#331 legacyDispatchFamilyWorker — wraps the legacy CMR return as WorkerResult", () => {
  it("cmr worker: residual red is completed unusableResidualOpenCountPaper (NOT failed / NOT continue) (#919 E / CR N2)", async () => {
    const be = new CapableFamilyBackend();
    be.cmrConverged = false;
    const res = await legacyDispatchFamilyWorker(be, cmrWorkerSpec(), {
      familyBase: "fb",
    });
    // #919 E / CR S1: residual IntegratedCmrResult never mints judge continue.
    // One shared unusable paper (kind:"reviewer"+findingsCount:0) only.
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "reviewer") {
      expect(res.output.findingsCount).toBe(0);
      expect(res.output.findings).toEqual([]);
    } else {
      throw new Error(
        "expected completed unusableResidualOpenCountPaper (kind:reviewer)",
      );
    }
  });

  it("dispatchFamilyWorker prefers familyBackend.dispatchWorker when present", async () => {
    let used = false;
    const be = new CapableFamilyBackend() as FamilyBackend & {
      dispatchWorker?: FamilyBackend["dispatchWorker"];
    };
    be.dispatchWorker = async (): Promise<WorkerResult> => {
      used = true;
      return completedJudgeGreen();
    };
    const route = await smokeRouteModels(
      resolveActiveModelRoute(),
      async () => ({ cliVersion: "test" }),
    );
    await dispatchFamilyWorker(be, cmrWorkerSpec("fresh", "correctness", route), {
      familyBase: "fb",
      modelRoute: route,
    });
    expect(used).toBe(true);
  });
});
