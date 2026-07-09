import { describe, expect, it } from "vitest";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import {
  cmrWorkerSpec,
  dispatchFamilyWorker,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
} from "../../src/family/dispatchFamilyWorker.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
} from "../../src/family/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

/**
 * #331 — the FAMILY worker-dispatch seam. The verify-cmr hook dispatches the
 * integrated cmr + 止于 PR through `dispatchFamilyWorker` instead of the per-method
 * `runIntegratedCmr` / `openFamilyPr`. Behaviour is unchanged (the legacy methods
 * are still consulted as the capability gate; the wrapper forwards to them).
 */

/** A capable FamilyBackend that records the legacy method calls. */
class CapableFamilyBackend implements FamilyBackend {
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrCalls: IntegratedCmrRequest[] = [];
  prCalls: OpenFamilyPrRequest[] = [];
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
    return this.cmrConverged
      ? { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }
      : { converged: false, reason: "cross-slice seam mismatch" };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return { url: `pr://${req.familyBase}`, prHead: "head-1" };
  }
}

describe("#331 family verify-cmr routes cmr + PR through dispatchFamilyWorker", () => {
  it("final barrier: green verify → cmr worker (converged) → ship worker (PR), ok", async () => {
    const be = new CapableFamilyBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });

    expect(res).toEqual({ ok: true, ran: true });
    // The legacy methods were still reached (the wrapper forwards to them).
    expect(be.cmrCalls).toEqual([
      { familyBase: "feat/330", cmrPass: "completeness" },
      { familyBase: "feat/330", cmrPass: "correctness" },
    ]);
    expect(be.prCalls).toEqual([{ familyBase: "feat/330" }]);
  });

  it("final barrier: a red cmr verdict is routed as escalate (no PR), ok:false", async () => {
    const be = new CapableFamilyBackend();
    be.cmrConverged = false;
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });

    expect(res.ok).toBe(false);
    // cmr ran; PR did NOT open on a red verdict.
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
   * legacy `runIntegratedCmr` / `openFamilyPr` methods. The verify-cmr gate must
   * accept it (codex cmr finding: gating on the legacy method alone wrongly
   * fail-safed a new-seam-only backend to INCOMPLETE_GATE).
   */
  class NewSeamFamilyBackend implements FamilyBackend {
    dispatched: Array<{
      kind: WorkerSpec["kind"];
      promptFile: string;
      cmrPass?: DispatchContext["cmrPass"];
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }> = [];
    completenessConverged = true;
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
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged:
              ctx.cmrPass === "completeness" ? this.completenessConverged : true,
            successfulLegs: ["opus", "gpt-5.5", "agy"],
            ...CMR_EVIDENCE,
            ...(ctx.cmrPass === "completeness" && !this.completenessConverged
              ? { reason: "family base is incomplete" }
              : {}),
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
                  ? { kind: "cleanup", ok: true }
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
      { kind: "cleanup", promptFile: "cleanup.md" },
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
      { kind: "cleanup", promptFile: "cleanup.md" },
      { kind: "docRelease", promptFile: "docRelease.md" },
    ]);
  });

  it("a red completeness pass gates correctness and ship (step6 cannot run before step5 passes)", async () => {
    const be = new NewSeamFamilyBackend();
    be.completenessConverged = false;
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    expect(res).toEqual({ ok: false, ran: true });
    expect(be.dispatched).toEqual([
      {
        kind: "cmr",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
      },
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

  it("a completed-but-non-ship family ship result → INCOMPLETE_GATE (ok:false)", async () => {
    const be = new WrongShipFamilyBackend();
    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: be,
    });
    expect(res).toEqual({ ok: false, ran: true });
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
                  ? { kind: "cleanup", ok: true }
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

  it("a completed ship with status 'pushed' (not pr_opened) ⇒ INCOMPLETE_GATE", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pushed" },
    });
    expect(res).toEqual({ ok: false, ran: true });
  });

  it("a completed ship missing its pr URL ⇒ INCOMPLETE_GATE", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened" },
    });
    expect(res).toEqual({ ok: false, ran: true });
  });

  it("a completed ship with a blank pr URL ⇒ INCOMPLETE_GATE", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "feat/330", status: "pr_opened", pr: "   " },
    });
    expect(res).toEqual({ ok: false, ran: true });
  });

  it("a completed ship on the WRONG branch (≠ familyBase) ⇒ INCOMPLETE_GATE", async () => {
    const res = await gate({
      kind: "completed",
      output: { kind: "ship", branch: "main", status: "pr_opened", pr: "u" },
    });
    expect(res).toEqual({ ok: false, ran: true });
  });

  it("a completed pr_opened ship missing its verified PR head ⇒ INCOMPLETE_GATE", async () => {
    const res = await gate({
      kind: "completed",
      output: {
        kind: "ship",
        branch: "feat/330",
        status: "pr_opened",
        pr: "pr://feat/330",
      },
    });
    expect(res).toEqual({ ok: false, ran: true });
  });

  it("a completed pr_opened ship with a blank verified PR head ⇒ INCOMPLETE_GATE", async () => {
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
    expect(res).toEqual({ ok: false, ran: true });
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

  it("a completed pr_opened ship whose PR head does not match the current family HEAD ⇒ INCOMPLETE_GATE", async () => {
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
    expect(res).toEqual({ ok: false, ran: true });
  });
});

describe("#330 a crash/malformed final cmr/ship worker writes a durable aborted event (online review r3, codex P2)", () => {
  /**
   * A new-seam backend that RECORDS the ledger, with the cmr + ship worker outputs
   * configurable. A `completed` worker whose output kind is WRONG (cmr worker
   * returning a ship-shaped payload, or vice-versa) is the crash/malformed case the
   * verify-cmr hook fail-safes to INCOMPLETE_GATE — and (r3) must leave a durable
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
    async runIntegratedCmr(): Promise<IntegratedCmrResult> {
      return { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
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

  it("a malformed cmr worker (completed but NOT a cmr payload) ⇒ INCOMPLETE_GATE + durable aborted(final)", async () => {
    const backend = new RecordingFamilyBackend(
      { kind: "completed", output: { kind: "ship", branch: "feat/330", status: "pushed" } },
      { kind: "completed", output: { kind: "ship", branch: "feat/330", status: "pr_opened", pr: "u" } },
    );
    const res = await runVerifyCmr({ phase: "final", familyBase: "feat/330", familyBackend: backend });
    expect(res).toEqual({ ok: false, ran: true });
    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    expect(aborts[0]?.phase).toBe("final");
    // NO ship marker — the barrier failed, so a resume re-runs it (does not skip).
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("a malformed ship worker (completed but NOT a ship payload) ⇒ INCOMPLETE_GATE + durable aborted(final)", async () => {
    const backend = new RecordingFamilyBackend(
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      },
    );
    const res = await runVerifyCmr({ phase: "final", familyBase: "feat/330", familyBackend: backend });
    expect(res).toEqual({ ok: false, ran: true });
    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    expect(aborts[0]?.phase).toBe("final");
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("a null ship worker payload ⇒ INCOMPLETE_GATE + durable aborted(final), not a TypeError", async () => {
    const backend = new RecordingFamilyBackend(
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      },
      { kind: "completed", output: null as never },
    );

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: backend,
    });

    expect(res).toEqual({ ok: false, ran: true });
    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    expect(aborts[0]?.reason).toMatch(/returned no valid result/i);
    expect(aborts[0]?.stopSummary?.reason).toBe("contract_drift");
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("an off-contract ship success writes durable aborted(final) with ship/head summary", async () => {
    const backend = new RecordingFamilyBackend(
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      },
      {
        kind: "completed",
        output: { kind: "ship", branch: "feat/330", status: "pushed" },
      },
    );

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/330",
      familyBackend: backend,
    });

    expect(res).toEqual({ ok: false, ran: true });
    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    expect(aborts[0]?.phase).toBe("final");
    expect(aborts[0]?.reason).toMatch(/did not open a valid family PR/i);
    expect(aborts[0]?.familyHeadAfter).toBe("head-1");
    expect(aborts[0]?.stopSummary?.reason).toBe("infra_failure");
    expect(aborts[0]?.stopSummary?.repairHint).toMatch(/rerun/i);
    expect(aborts[0]?.stopSummary?.metadata?.ship).toEqual({
      latestVerifiedCmrHead: "head-1",
      currentFamilyHead: "head-1",
      shipPrState: "branch=feat/330 status=pushed pr=missing",
    });
    expect(aborts[0]?.stopSummary?.metadata?.heads).toEqual({
      actualFamilyHead: "head-1",
      verifiedCmrHead: "head-1",
      sources: {
        actualFamilyHead: "family head after ship contract failure",
        verifiedCmrHead: "latest cmr_passed ledger row",
      },
    });
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("no ship capability after converged cmr writes durable aborted(final) over stale success", async () => {
    const backend = new NoShipCapabilityAfterCmrBackend();

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/445",
      familyBackend: backend,
    });

    expect(res).toEqual({ ok: false, ran: true });
    expect(backend.ledger.filter((e) => e.status === "cmr_passed")).toHaveLength(2);
    const latest = backend.ledger.at(-1);
    expect(latest?.status).toBe("aborted");
    expect(latest?.phase).toBe("final");
    expect(latest?.reason).toMatch(/family ship worker unavailable/i);
    expect(latest?.stopSummary?.reason).toBe("infra_failure");
    expect(latest?.stopSummary?.summary).toMatch(/PR/i);
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("PR-head mismatch records latest verified CMR head separately from post-ship head", async () => {
    const backend = new PrHeadMismatchRecordingBackend();

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "feat/445",
      familyBackend: backend,
    });

    expect(res).toEqual({ ok: false, ran: true });
    const abort = backend.ledger.find((e) => e.status === "aborted");
    expect(abort?.stopSummary?.metadata?.ship).toEqual({
      latestVerifiedCmrHead: "cmr-head",
      currentFamilyHead: "post-ship-head",
      reportedFamilyHead: "stale-pr-head",
      shipPrState: "pr-head-mismatch",
    });
    expect(abort?.stopSummary?.metadata?.heads).toEqual({
      actualFamilyHead: "post-ship-head",
      verifiedCmrHead: "cmr-head",
      sources: {
        actualFamilyHead: "family head after ship worker",
        verifiedCmrHead: "latest cmr_passed ledger row",
      },
    });
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
      return {
        kind: "escalated",
        escalation: { reason: "stuck", diagnosis: "needs human" },
      };
    }
  }

  it("an escalated cmr worker → escalateFamily + ok:false (not a bare INCOMPLETE_GATE)", async () => {
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
    expect(be.escalations[0]?.stopSummary).toMatchObject({
      reason: "infra_failure",
      metadata: {
        ship: { shipPrState: "ship-worker-escalated" },
      },
    });
    expect(be.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason: expect.stringContaining("family ship worker escalated"),
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        summary: expect.stringContaining("family ship worker escalated"),
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
        reason: "infra_failure",
        metadata: expect.objectContaining({
          ship: { shipPrState: "ship-worker-escalated" },
        }),
      }),
    }));
  });
});

describe("#331 legacyDispatchFamilyWorker — wraps legacy returns as WorkerResult", () => {
  it("cmr worker: a red verdict is `completed` (with payload), NOT `failed`", async () => {
    const be = new CapableFamilyBackend();
    be.cmrConverged = false;
    const res = await legacyDispatchFamilyWorker(be, cmrWorkerSpec(), {
      familyBase: "fb",
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "cmr") {
      expect(res.output.converged).toBe(false);
      expect(res.output.reason).toBe("cross-slice seam mismatch");
    } else {
      throw new Error("expected completed cmr payload");
    }
  });

  it("ship worker: forwards to openFamilyPr and wraps as completed ShipResult", async () => {
    const be = new CapableFamilyBackend();
    const res = await legacyDispatchFamilyWorker(be, familyShipWorkerSpec(), {
      familyBase: "fb",
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "ship") {
      expect(res.output.pr).toBe("pr://fb");
      expect(res.output.prHead).toBe("head-1");
      expect(res.output.status).toBe("pr_opened");
    } else {
      throw new Error("expected completed ship payload");
    }
  });

  it("ship worker: does not synthesize prHead from the local family ref when openFamilyPr did not verify it", async () => {
    class UnverifiedPrBackend extends CapableFamilyBackend {
      override async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
        this.prCalls.push(req);
        return { url: `pr://${req.familyBase}` };
      }
    }
    const be = new UnverifiedPrBackend();
    const res = await legacyDispatchFamilyWorker(be, familyShipWorkerSpec(), {
      familyBase: "fb",
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "ship") {
      expect(res.output.pr).toBe("pr://fb");
      expect(res.output.prHead).toBeUndefined();
    } else {
      throw new Error("expected completed ship payload");
    }
  });

  it("dispatchFamilyWorker prefers familyBackend.dispatchWorker when present", async () => {
    let used = false;
    const be = new CapableFamilyBackend() as FamilyBackend & {
      dispatchWorker: (s: WorkerSpec, c: DispatchContext) => Promise<WorkerResult>;
    };
    be.dispatchWorker = async (): Promise<WorkerResult> => {
      used = true;
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    };
    await dispatchFamilyWorker(be, cmrWorkerSpec(), { familyBase: "fb" });
    expect(used).toBe(true);
  });
});
