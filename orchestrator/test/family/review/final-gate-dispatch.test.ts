import { describe, expect, it } from "vitest";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import {
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
} from "../../../src/family/dispatchFamilyWorker.js";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveActiveModelRoute, smokeRouteModels } from "../../../src/modelRoutes.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import { legacyCmrScriptToWorkerOutput } from "../../helpers/judge-fixtures.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
} from "../../../src/family/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

/** #919 live green fixture — residual findingsCount:0 is unusable, never ship. */
function completedJudgeGreen(
  cargo: Record<string, unknown> = {},
): WorkerResult {
  return {
    kind: "completed",
    output: {
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      ...CMR_EVIDENCE,
      ...cargo,
    },
  } as WorkerResult;
}

/**
 * #331 — the FAMILY worker-dispatch seam. The verify-cmr hook dispatches the
 * integrated cmr + 止于 PR through `dispatchFamilyWorker`.
 */

/** A capable FamilyBackend that records the unified worker calls. */
class CapableFamilyBackend implements FamilyBackend {
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrCalls: IntegratedCmrRequest[] = [];
  prCalls: Array<{ readonly familyBase: string }> = [];
  cmrConverged = true;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(): Promise<void> {}
  async readFamilyLedger(): Promise<[]> {
    return [];
  }
  async readFamilyHead(): Promise<string> {
    return "head-1";
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return { ok: true };
  }
  async runIntegratedCmr(
    req: IntegratedCmrRequest,
  ): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    // #919 M2: residual findingsCount:0 is unusable. Boolean green without
    // open-count is promoted by legacyCmrScriptToWorkerOutput (test-fake only).
    return this.cmrConverged
      ? {
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [],
        }
      : {
          converged: false,
          findingsCount: 1,
          reason: "cross-slice seam mismatch",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [
            {
              severity: "high",
              category: "correctness",
              claim_quote: "cross-slice seam mismatch",
              location: "family integration seam",
              suggested_fix: "repair the cross-slice seam",
              action: "fix_now",
            },
          ],
        };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      // Test-fake: promote boolean green → kind:judge; residual positive → continue.
      const res = await legacyDispatchFamilyWorker(this, spec, ctx);
      if (res.kind !== "completed") return res;
      // Re-map residual kind:cmr paper through the shared test helper so green
      // boolean scripts become live judge traffic (production never does this).
      if (res.output.kind === "cmr") {
        const { kind: _k, ...rest } = res.output as {
          kind: "cmr";
          converged?: boolean;
          findingsCount?: number;
          reason?: string;
          findings?: IntegratedCmrResult["findings"];
          successfulLegs?: readonly string[];
          skippedLegs?: IntegratedCmrResult["skippedLegs"];
          claimedFixedFindingIdentityKeys?: readonly string[];
          priorFindingDispositions?: IntegratedCmrResult["priorFindingDispositions"];
          evidencePaths?: readonly string[];
        };
        return {
          kind: "completed",
          output: legacyCmrScriptToWorkerOutput({
            converged: rest.converged ?? false,
            ...rest,
          }),
        };
      }
      return res;
    }
    if (spec.kind === "ship") {
      const familyBase = ctx.familyBase!;
      this.prCalls.push({ familyBase });
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: familyBase,
          pr: `pr://${familyBase}`,
          prHead: "head-1",
          status: "pr_opened",
        },
      };
    }
    return legacyDispatchFamilyWorker(this, spec, ctx);
  }
}

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

  it("family monitored dispatch produces and persists its handle before awaiting the child", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-family-monitor-"));
    try {
      const events: string[] = [];
      const backend = {
        resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
          command: process.platform === "win32" ? "cmd" : "true",
          args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
          logDir: dir,
          poolId: `claude/${spec.model}`,
          stepId: spec.id,
        }),
        awaitMonitoredCliWorker: async () => {
          events.push("awaited");
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          } as WorkerResult;
        },
      } as unknown as FamilyBackend;

      const outcome = await dispatchFamilyWorkerWithMonitor(
        backend,
        cmrWorkerSpec(),
        { familyBase: "family/base" },
        undefined,
        {
          onMonitorHandleSpawned: async (handle) => {
            events.push(`persisted:${handle.stepId}`);
          },
        },
      );

      expect(outcome.monitorHandle).toBeDefined();
      expect(events).toEqual(["persisted:S3", "awaited"]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
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
        // Residual positive open-count → judge continue (coder-fix path).
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: false,
            findingsCount: 1,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            reason: "family base is incomplete",
            ...CMR_EVIDENCE,
          },
        };
      }
      if (spec.kind === "ship") {
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: "feat/330",
            pr: "pr://feat/330",
            prHead: "head-1",
            status: "pr_opened",
          },
        };
      }
      if (
        spec.kind === "verify" ||
        spec.kind === "fixer" ||
        spec.kind === "docRelease"
      ) {
        return {
          kind: "completed",
          output:
            spec.kind === "verify"
              ? { kind: "verify", converged: true }
              : spec.kind === "fixer"
                ? {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                }
                : { kind: "docRelease", released: true },
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
      { kind: "verify", promptFile: "verify.md" },
      { kind: "docRelease", promptFile: "docRelease.md" },
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
      { kind: "verify", promptFile: "verify.md" },
      { kind: "docRelease", promptFile: "docRelease.md" },
    ]);
  });
});

describe("#331 the family ship worker must return a SHIP payload (codex R2 guard)", () => {
  /** A new-seam backend whose ship worker returns a completed NON-ship payload. */
  class WrongShipFamilyBackend implements FamilyBackend {
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
    // Off-contract ship payload still synthesizes a PR handle and continues into
    // online review, which then dies as online_review_failed (#922 stage token).
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "online_review_failed",
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
    shipOutput: WorkerResult;
    constructor(shipOutput: WorkerResult) {
      this.shipOutput = shipOutput;
    }
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      if (
        spec.kind === "verify" ||
        spec.kind === "fixer" ||
        spec.kind === "cleanup" ||
        spec.kind === "docRelease"
      ) {
        return {
          kind: "completed",
          output:
            spec.kind === "verify"
              ? { kind: "verify", converged: true }
              : spec.kind === "fixer"
                ? {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                }
                : spec.kind === "cleanup"
                  ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                  : { kind: "docRelease", released: true },
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

  it("a completed ship with status 'pushed' (not pr_opened) ⇒ online_review_failed gate", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pushed" },
    });
    // Host still synthesizes a PR handle from branch; death is later online-review.
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "online_review_failed",
    });
  });

  it("a completed ship missing its pr URL ⇒ online_review_failed gate", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened" },
    });
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "online_review_failed",
    });
  });

  it("a completed ship with a blank pr URL ⇒ online_review_failed gate", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened", pr: "   " },
    });
    expect(res).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "online_review_failed",
    });
  });

  it("a completed ship that reports the wrong branch follows host-verified PR truth", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "worker-reported-wrong-branch",
        status: "pr_opened",
        pr: "pr://feat/330",
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
        pr: "pr://feat/330",
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
        pr: "pr://feat/330",
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
        pr: "pr://feat/330",
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
        pr: "pr://feat/330",
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
    readonly ledger: FamilyLedgerEntry[] = [];
    constructor(
      private readonly cmrOut: WorkerResult,
      private readonly shipOut: WorkerResult,
    ) {}
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
      return spec.kind === "cmr" ? this.cmrOut : this.shipOut;
    }
  }

  class NoShipCapabilityAfterCmrBackend implements FamilyBackend {
    readonly ledger: FamilyLedgerEntry[] = [];
    readonly aborted: FamilyLedgerEntry[] = [];
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
    readonly ledger: FamilyLedgerEntry[] = [];
    private shipDispatched = false;
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
      if (spec.kind === "cmr") {
        return completedJudgeGreen();
      }
      this.shipDispatched = true;
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: "feat/445",
          status: "pr_opened",
          pr: "pr://feat/445",
          prHead: "stale-pr-head",
        },
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
    escalations: FamilyEscalation[] = [];
    ledger: FamilyLedgerEntry[] = [];
    escalateOn: "cmr" | "ship";
    constructor(escalateOn: "cmr" | "ship") {
      this.escalateOn = escalateOn;
    }
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
        output: { kind: "ship", branch: "fb", pr: "u", status: "pr_opened" },
      };
    }
  }

  class ShipEscalatesWithoutEscalateSeamBackend implements FamilyBackend {
    ledger: FamilyLedgerEntry[] = [];
    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
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
  it("cmr worker: a red verdict is `completed` judge continue (NOT `failed`) (#930)", async () => {
    const be = new CapableFamilyBackend();
    be.cmrConverged = false;
    const res = await legacyDispatchFamilyWorker(be, cmrWorkerSpec(), {
      familyBase: "fb",
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "judge") {
      // Residual red IntegratedCmrResult projects to judge continue at boundary.
      expect(res.output.status).toBe("continue");
    } else {
      throw new Error("expected completed judge payload");
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
