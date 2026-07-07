/**
 * #604 correctness r4 — early closure guard is a WELL-FORMEDNESS gate, not a
 * "verified-closed" gate; not_converged/empty and first-pass self-report paths
 * also route malformed closure payloads to contract_drift.
 *
 * D1 (regression, most important): the r2 C2 early closure guard ran the FULL
 * `cmrClosureFailureReason` — which fails if any prior disposition is
 * `still-active`/`unable-to-assess`. That over-fired: a prior blocker the
 * coder-fix loop is meant to repair (claimed-fixed but disposed still-active)
 * got aborted as contract_drift instead of routed to coder-fix. The early guard
 * must assert only that the payload is WELL-FORMED (every protected prior key is
 * claimed or disposed; no stale/duplicate/malformed dispositions) — NOT that
 * every prior finding is verified-closed. The LATE converged-path guard keeps
 * the full assertion.
 *
 * D2: a `converged:false, findings:[]` payload on a RESTART barrier must still
 * run the well-formedness closure guard BEFORE the thin not_converged abort — a
 * reviewer that drops the protected prior keys (no claimedFixed / disposition)
 * must fail closed as contract_drift, not slip past as an ordinary not_converged
 * envelope.
 *
 * D3: on a FIRST pass (no protected prior keys) a reviewer that SELF-REPORTS a
 * closure payload (non-empty claimedFixed with no runner-supplied prior set) is
 * malformed (`closure_context_missing`). The early guard must run whenever any
 * closure payload is present, so this malformed self-report fails closed instead
 * of routing its NEW blocker to coder-fix.
 *
 * Driven entirely by a zero-container injected-seam fake.
 */

import { describe, expect, it } from "vitest";
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
  CmrWorkerOutput,
} from "../../src/types.js";

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

/**
 * A scriptable backend that returns a single scripted cmr WORKER output, then
 * records + throws on any coder dispatch so the test can tell whether the runner
 * reached coder-fix or failed closed first.
 */
class ScriptedCmrBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatchedNonCmrKinds: WorkerSpec["kind"][] = [];
  currentFamilyHead = "head-1";

  constructor(private readonly cmrOutput: CmrWorkerOutput) {}

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
  async dispatchWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      return { kind: "completed", output: this.cmrOutput };
    }
    // #598: a coder-fix that cannot fix returns a `failed` RESULT (a judged
    // not-ok, not a process crash); the generic mechanical retry defers judged
    // results to the gate — one dispatch, no retry — and reaching this path still
    // proves the runner routed to coder-fix.
    this.dispatchedNonCmrKinds.push(spec.kind);
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

describe("#604 r4 D1 — early closure guard is well-formed-only, not verified-closed", () => {
  it("a well-formed still-active prior key (claimed + disposed still-active) routes to coder-fix, NOT contract_drift", async () => {
    // The fresh reviewer claims the protected prior key fixed AND discloses its
    // disposition as still-active (the fix did not hold), re-raising it as an
    // active finding. This is a WELL-FORMED closure payload — every protected
    // prior key is accounted for. The early guard must let it through so the
    // still-active finding drives coder-fix; it must NOT abort as contract_drift.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "prior fix did not hold",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
      priorFindingDispositions: [
        { identityKey: PROTECTED_PRIOR_KEY, status: "still-active" },
      ],
      findings: [STILL_ACTIVE_PRIOR],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toEqual({ ok: false, ran: true });
    // Reached coder-fix (still-active finding routed) — the positive signal. The
    // early closure guard did NOT abort as a closure-payload contract drift.
    expect(backend.dispatchedNonCmrKinds).toEqual(["coder"]);
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

  it("a prior key left completely unaccounted still fails closed as contract_drift", async () => {
    // Well-formedness violated: the protected prior key is neither claimed nor
    // disposed. This must still abort as contract_drift — the well-formed guard
    // is NOT weakened for coverage.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "fresh re-review found a new blocker",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [NEW_BLOCKER],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual([]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        reason: expect.stringContaining("were not explicitly claimed fixed"),
        stopSummary: expect.objectContaining({ reason: "contract_drift" }),
      }),
    );
  });
});

describe("#604 r4 D2 — not_converged/empty must run the well-formed closure guard", () => {
  it("converged:false + findings:[] that drops a protected prior key fails closed as contract_drift", async () => {
    // A thin not_converged envelope must not be a bypass: with protected prior
    // keys present, a `converged:false, findings:[]` payload that neither claims
    // nor disposes the prior key is malformed and must fail closed BEFORE the
    // ordinary not_converged abort.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "did not converge",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual([]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        reason: expect.stringContaining("were not explicitly claimed fixed"),
        stopSummary: expect.objectContaining({ reason: "contract_drift" }),
      }),
    );
  });

  it("converged:false + findings:[] that WELL-FORMEDLY closes the prior key aborts as ordinary not_converged", async () => {
    // Coverage guard: a not_converged envelope that DOES account for the prior
    // key (claimed + verified-closed) is well-formed → the D2 guard does not
    // fire; it falls through to the ordinary not_converged abort (not
    // contract_drift).
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "did not converge on unrelated grounds",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
      priorFindingDispositions: [
        { identityKey: PROTECTED_PRIOR_KEY, status: "verified-closed" },
      ],
      findings: [],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual([]);
    // Ordinary not_converged abort (its stopSummary shares the contract_drift
    // reason code) — but NOT the closure-guard failure: the ledger reason is the
    // not_converged reason, not a closure-payload violation.
    expect(
      backend.ledger.some(
        (e) =>
          typeof (e as { reason?: unknown }).reason === "string" &&
          /were not explicitly claimed fixed|are not verified closed|closure_context_missing/.test(
            (e as { reason: string }).reason,
          ),
      ),
    ).toBe(false);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        reason: "did not converge on unrelated grounds",
      }),
    );
  });
});

describe("#604 r4 D3 — first-pass self-reported closure payload is guarded", () => {
  it("first pass (no protected keys) + new blocker + self-reported claimedFixed fails closed, NOT coder-fix", async () => {
    // No runner-supplied prior set, yet the reviewer claims to have fixed a prior
    // finding: `closure_context_missing`. Pre-r4 the guard was skipped on a first
    // pass, so the NEW blocker slipped into coder-fix. The guard must now run
    // because a closure payload is present.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "fresh review",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: ["some|self|reported|key"],
      priorFindingDispositions: [],
      findings: [NEW_BLOCKER],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      // No priorCmrFindingIdentityKeys — a first pass, nothing protected.
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual([]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        reason: expect.stringContaining("closure_context_missing"),
        stopSummary: expect.objectContaining({ reason: "contract_drift" }),
      }),
    );
  });

  it("first pass (no protected keys) + new blocker + NO closure payload still routes to coder-fix", async () => {
    // Regression guard: a genuinely payload-free first pass (no claimed, no
    // dispositions) must preserve the normal blocking→coder-fix path.
    const backend = new ScriptedCmrBackend({
      kind: "cmr",
      converged: false,
      reason: "fresh review",
      successfulLegs: ["opus", "gpt-5.5", "agy"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [NEW_BLOCKER],
      ...CMR_EVIDENCE,
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual(["coder"]);
  });
});
