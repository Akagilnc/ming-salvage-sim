/**
 * #875 [873·S1] — demolish the verifyCmr accounting court.
 *
 * Owner order (#873 / #875): the runner is a traffic cop (exit code / findings
 * count / decision gate). It must NOT kill a live family run because a
 * reviewer's envelope is chatty, sloppy, incomplete on claim/disposition shape,
 * or inaccurate on leg-accounting prose. Old case handoff is the reviewer's
 * contractual duty (ADR 0130); prior findings pass as artifact pointers — the
 * runner does not parse envelope content to branch fate.
 *
 * Flip pattern (#862 / #861): tests that once asserted "kill the run" now
 * assert "run survives / three-channel routing continues".
 *
 * Keep (out of this court's scope): real infra durable abort, CMR leg floor /
 * required-leg provider degradation, decision-gate park.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import { findingIdentityKey } from "../../src/findings.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";
import type {
  CmrResult,
  DispatchContext,
  Finding,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

const PROTECTED_PRIOR_KEY =
  "medium|correctness|prior blocker awaiting closure|scope";

const NEW_BLOCKER: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "a brand-new blocker",
  location: "orchestrator/src/family/verifyCmr.ts:999",
  suggested_fix: "fix the new blocker",
  action: "fix_now",
};

afterEach(() => {
  vi.unstubAllEnvs();
});

/**
 * Scripted backend: fixed CMR worker output(s), records coder dispatches
 * (and fails them) so the test can tell whether the runner reached coder-fix
 * or aborted in the accounting court first. Includes the post-CMR ship
 * verification capability so a surviving court path can complete to ok:true.
 */
class ScriptedCmrBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatchedNonCmrKinds: WorkerSpec["kind"][] = [];
  currentFamilyHead = "head-1";
  private cmrIndex = 0;

  constructor(
    private readonly cmrOutputs: ReadonlyArray<CmrResult> | CmrResult,
  ) {}

  async mergeChildIntoFamilyBase(
    _child: MergeRequest,
  ): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async verifyFamilyShippedPr(): Promise<{ ok: true }> {
    return { ok: true };
  }
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      const outputs = Array.isArray(this.cmrOutputs)
        ? this.cmrOutputs
        : [this.cmrOutputs];
      const output = outputs[Math.min(this.cmrIndex, outputs.length - 1)]!;
      this.cmrIndex += 1;
      return { kind: "completed", output };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/875",
          status: "pr_opened",
          pr: `pr://${ctx.familyBase ?? "family/875"}`,
          prHead: this.currentFamilyHead,
        },
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    this.dispatchedNonCmrKinds.push(spec.kind);
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

function isCourtAbort(ledger: ReadonlyArray<FamilyLedgerEntry>): boolean {
  return ledger.some((entry) => {
    if (entry.status !== "aborted") return false;
    const reason =
      typeof (entry as { reason?: unknown }).reason === "string"
        ? (entry as { reason: string }).reason
        : "";
    return (
      /were not explicitly claimed fixed|not verified closed|closure_context_missing|missing explicit disposition|leg accounting failed|not declared|duplicate prior finding|accepted_suppressed dispositions missing|dispositions without claimed-fixed|outside the runner-supplied/i.test(
        reason,
      ) ||
      (entry.stopSummary?.metadata?.routeAccounting !== undefined &&
        entry.stopSummary.reason === "infra_failure")
    );
  });
}

describe("#875 demolish verifyCmr accounting court — sloppy/chatty envelope survives", () => {
  it("unaccounted protected prior + new blocker routes to coder-fix (not contract_drift court death)", async () => {
    // Pre-#875: early closure coverage audit aborted as contract_drift and
    // starved the fix loop. Post-#875: findings-count channel routes to coder-fix.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "fresh re-review found a new blocker",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [NEW_BLOCKER],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(["coder", "coder", "coder"]);
    expect(isCourtAbort(backend.ledger)).toBe(false);
  });

  it("converged envelope with claimed-fixed keys but no dispositions still ships", async () => {
    // Pre-#875: missing-disposition coverage audit → contract_drift kill.
    // Post-#875: findings=0 + converged + exit ok → three-channel pass → ship.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: true,
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|fake closure"],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: ["correctness|src/x.ts:1|fake closure"],
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(isCourtAbort(backend.ledger)).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_passed"),
    ).toBe(true);
  });

  it("converged envelope with still-active prose disposition still ships when findings=0", async () => {
    // Pre-#875: disposition-enum court (still-active) → contract_drift kill.
    // Post-#875: runner does not read disposition statuses to branch fate.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: true,
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|still open",
          status: "still-active",
        },
      ],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(isCourtAbort(backend.ledger)).toBe(false);
  });

  it("converged envelope with undeclared successful legs still ships (no leg-accounting death)", async () => {
    // Pre-#875: cmrLegAccountingFailure → infra_failure kill with routeAccounting.
    // Post-#875: leg lists are prose; floor/required-leg degradation stays, court dies.
    // claude-tight declares gpt-5.6-sol + agy; listing an EXTRA undeclared "opus"
    // was pure accounting death (not required-leg skip / floor).
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: true,
      successfulLegs: ["gpt-5.6-sol", "agy", "opus"],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(isCourtAbort(backend.ledger)).toBe(false);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          entry.stopSummary?.metadata?.routeAccounting !== undefined,
      ),
    ).toBe(false);
  });

  it("required leg double-reported as successful+skipped still ships (sloppy prose, not unavailable)", async () => {
    // #875: skippedLegs prose must not override a simultaneous successful report
    // for the same required route leg — that was pure accounting death / milder
    // re-court of double-report. claude-tight required = gpt-5.6-sol.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [{ slug: "gpt-5.6-sol", reason: "quota (double-report noise)" }],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /required CMR anchor leg/i.test(
            typeof entry.reason === "string" ? entry.reason : "",
          ),
      ),
    ).toBe(false);
    expect(backend.ledger.some((entry) => entry.status === "cmr_passed")).toBe(
      true,
    );
  });

  it("floor still fails when only an undeclared strong leg is reported (no route-declared strong credit)", async () => {
    // After accounting-court demolition, undeclared legs must not kill via
    // routeAccounting — but they also must not *satisfy* the retained strong-leg
    // floor. claude-tight declares gpt-5.6-sol (+ optional agy); opus alone is
    // strong-but-undeclared and must still trip provider_degraded floor.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: true,
      successfulLegs: ["opus"],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(isCourtAbort(backend.ledger)).toBe(false);
    const abort = backend.ledger.find((entry) => entry.status === "aborted");
    expect(abort?.stopSummary?.reason).toBe("provider_degraded");
    expect(String(abort?.reason ?? "")).toMatch(/floor failed/i);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          entry.stopSummary?.metadata?.routeAccounting !== undefined,
      ),
    ).toBe(false);
  });

  it("#875 Opus: open-count is array-derived — lying findingsCount is ignored at runner", async () => {
    // Downstream never reconciles independent findingsCount vs array (Opus).
    // findings=[one blocker] ⇒ openCount=1 ⇒ coder-fix, even if findingsCount lies.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "array has one blocker",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      findingsCount: 99,
      findings: [NEW_BLOCKER],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(["coder", "coder", "coder"]);
    expect(isCourtAbort(backend.ledger)).toBe(false);
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" && e.stopSummary?.reason === "infra_failure",
      ),
    ).toBe(false);
  });

  });
