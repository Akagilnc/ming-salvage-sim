/**
 * #604 correctness r4 — superseded in part by #875.
 *
 * Pre-#875 D1/D2/D3 asserted an early well-formedness court on claimed-fixed /
 * disposition coverage (abort as contract_drift when protected priors were
 * unaccounted; still-active dispositions on the early path routed to coder-fix).
 *
 * #875 demolishes the coverage/disposition court entirely. Still-active prior
 * + active findings → coder-fix (findings-count). Unaccounted priors are
 * prose. Thin not_converged is ordinary three-channel not_converged, not court
 * death. First-pass self-report already survived under #861.
 *
 * #919 CR N3: fixtures emit live kind:judge continue (not residual kind:cmr).
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
  JudgeResult,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";
import { liveCmrJudgeContinue } from "../helpers/judge-fixtures.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

const PROTECTED_PRIOR_KEY =
  "medium|correctness|prior blocker awaiting closure|scope";

const STILL_ACTIVE_PRIOR: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "prior blocker awaiting closure",
  location: "scope",
  suggested_fix: "actually fix it this time",
  action: "fix_now",
};

const NEW_BLOCKER: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "a brand-new blocker",
  location: "orchestrator/src/family/verifyCmr.ts:999",
  suggested_fix: "fix the new blocker",
  action: "fix_now",
};

class ScriptedCmrBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatchedNonCmrKinds: WorkerSpec["kind"][] = [];
  currentFamilyHead = "head-1";

  constructor(private readonly cmrOutput: JudgeResult) {}

  async mergeChildIntoFamilyBase(
    _child: MergeRequest,
  ): Promise<{ familyHead: string }> {
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
    if (spec.kind === "cmr") {
      return { kind: "completed", output: this.cmrOutput };
    }
    this.dispatchedNonCmrKinds.push(spec.kind);
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

describe("#604 r4 D1 / #875 — still-active prior routes to coder-fix", () => {
  it("a well-formed still-active prior key (claimed + disposed still-active) routes to coder-fix, NOT contract_drift", async () => {
    const backend = new ScriptedCmrBackend(
      liveCmrJudgeContinue([STILL_ACTIVE_PRIOR], {
        reason: "prior fix did not hold",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
        priorFindingDispositions: [
          { identityKey: PROTECTED_PRIOR_KEY, status: "still-active" },
        ],
        ...CMR_EVIDENCE,
      }),
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toMatchObject({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(
      Array.from({ length: MAX_DISPATCH_ATTEMPTS }, () => "coder"),
    );
    expect(
      backend.ledger.some(
        (e) =>
          typeof (e as { reason?: unknown }).reason === "string" &&
          /were not explicitly claimed fixed|are not verified closed|closure_context_missing/.test(
            (e as { reason: string }).reason,
          ),
      ),
    ).toBe(false);
  });

  it("#875: a prior key left completely unaccounted still routes new blocker to coder-fix", async () => {
    const backend = new ScriptedCmrBackend(
      liveCmrJudgeContinue([NEW_BLOCKER], {
        reason: "fresh re-review found a new blocker",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
      }),
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toMatchObject({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(
      Array.from({ length: MAX_DISPATCH_ATTEMPTS }, () => "coder"),
    );
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" &&
          typeof (e as { reason?: unknown }).reason === "string" &&
          /were not explicitly claimed fixed/.test((e as { reason: string }).reason),
      ),
    ).toBe(false);
  });
});


describe("#604 r4 D3 / #861/#875 — first-pass self-report is not court death", () => {
  it("#861: first pass (no protected keys) + new blocker + self-reported claimedFixed routes to coder-fix like any blocking round", async () => {
    const backend = new ScriptedCmrBackend(
      liveCmrJudgeContinue([NEW_BLOCKER], {
        reason: "fresh review",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: ["some|self|reported|key"],
        priorFindingDispositions: [
          { identityKey: "some|self|reported|key", status: "verified-closed" },
        ],
        ...CMR_EVIDENCE,
      }),
    );

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
    expect(backend.ledger).not.toContainEqual(
      expect.objectContaining({
        status: "aborted",
        reason: expect.stringContaining("closure_context_missing"),
      }),
    );
  });

  it("first pass (no protected keys) + new blocker + NO closure payload still routes to coder-fix", async () => {
    const backend = new ScriptedCmrBackend(
      liveCmrJudgeContinue([NEW_BLOCKER], {
        reason: "fresh review",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
      }),
    );

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
  });
});
