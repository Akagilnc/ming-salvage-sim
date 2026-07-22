/**
 * #604 correctness r2 (C2) — superseded in part by #875.
 *
 * Pre-#875: on a restart pass the runner carried `priorCmrFindingIdentityKeys`
 * and a fresh reviewer that left a protected prior unaccounted while raising a
 * NEW blocker was aborted as contract_drift (coverage court before coder-fix).
 *
 * #875 demolishes that court. Findings-count routing continues: a new blocker
 * goes to coder-fix regardless of claim/disposition prose. ADR 0130 moves old
 * case handoff to the reviewer's contractual duty.
 *
 * Driven entirely by a zero-container injected-seam fake.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";
import type {
  DispatchContext,
  Finding,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";
import { liveCmrJudgeContinue } from "../helpers/judge-fixtures.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";
import { completeCmrPanelLegWorker } from "../helpers/cmr-panel-leg-dispatch.js";


const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

const PROTECTED_PRIOR_KEY = "medium|correctness|prior blocker awaiting closure|scope";

const NEW_BLOCKER: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "a brand-new blocker unrelated to the protected prior key",
  location: "orchestrator/src/family/verifyCmr.ts:999",
  suggested_fix: "fix the new blocker",
  action: "fix_now",
};

class ClosureOrderingBackend implements FamilyBackend {
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
  readonly dispatchedNonCmrKinds: WorkerSpec["kind"][] = [];
  currentFamilyHead = "head-1";

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
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
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
  ): Promise<WorkerResult> {
    const panelLeg = completeCmrPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (spec.kind === "cmr") {
      // #919 CR N3: live kind:judge continue (not residual kind:cmr).
      return {
        kind: "completed",
        sessionId: "fixture-cmr-604-ordering",
        output: liveCmrJudgeContinue([NEW_BLOCKER], {
          reason: "fresh re-review found a new blocker",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
        }),
      };
    }
    this.dispatchedNonCmrKinds.push(spec.kind);
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

describe("#604 r2 C2 / #875 — unaccounted prior no longer blocks coder-fix", () => {
  it("#875: a new blocker that leaves a protected prior key unaccounted routes to coder-fix", async () => {
    const backend = new ClosureOrderingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toMatchObject({ ok: false, ran: true });
    // Findings-count channel → coder-fix; no coverage-court abort.
    expect(backend.dispatchedNonCmrKinds).toEqual(
      Array.from({ length: MAX_DISPATCH_ATTEMPTS }, () => "coder"),
    );
    expect(
      backend.ledger.some(
        (entry) =>
          typeof (entry as { reason?: unknown }).reason === "string" &&
          ((entry as { reason: string }).reason).includes(
            "were not explicitly claimed fixed",
          ),
      ),
    ).toBe(false);
  });

  it("a new blocker on a FIRST pass (no protected prior keys) still routes to coder-fix", async () => {
    const backend = new ClosureOrderingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toMatchObject({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(
      Array.from({ length: MAX_DISPATCH_ATTEMPTS }, () => "coder"),
    );
    expect(
      backend.ledger.some(
        (entry) =>
          typeof (entry as { reason?: unknown }).reason === "string" &&
          ((entry as { reason: string }).reason).includes(
            "were not explicitly claimed fixed",
          ),
      ),
    ).toBe(false);
  });
});
