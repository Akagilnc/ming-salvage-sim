/**
 * #604 correctness r2 (C2): closure-guard ordering on a RESTART barrier.
 *
 * On a restart pass the runner carries `priorCmrFindingIdentityKeys` (the prior
 * blockers the fresh reviewer MUST account for). If that reviewer returns a NEW
 * blocker AND fails to report where the protected prior key went (no
 * claimedFixed / disposition for it), that is a MALFORMED closure payload — it
 * must fail closed (contract_drift) and NOT dispatch coder-fix on the strength
 * of the unrelated new blocker.
 *
 * Pre-r2 the `blocking.length > 0` branch ran BEFORE `cmrClosureFailureReason`,
 * so this malformed outcome slipped straight into coder-fix, bypassing the
 * closure guard. This test pins the corrected ordering: closure is checked
 * first when protected prior keys are present.
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
} from "../../src/types.js";

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

/**
 * A scriptable backend. The cmr WORKER dispatch returns the scripted malformed
 * outcome (new blocker, protected prior key left unaccounted). A coder dispatch
 * is RECORDED (and throws) so the test can assert whether the runner reached
 * coder-fix or failed closed on the closure guard first.
 */
class ClosureOrderingBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatchedNonCmrKinds: WorkerSpec["kind"][] = [];
  currentFamilyHead = "head-1";

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
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
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          reason: "fresh re-review found a new blocker",
          successfulLegs: ["opus", "gpt-5.6-sol"],
          // Protected prior key NEITHER claimed fixed NOR disposed — malformed.
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          findings: [NEW_BLOCKER],
          ...CMR_EVIDENCE,
        },
      };
    }
    // Any coder-fix (or other) dispatch means the closure guard did NOT fire.
    // #598: a coder-fix that cannot fix returns a `failed` RESULT (a judged
    // not-ok, not a process crash) — the generic mechanical retry defers judged
    // results to the gate, so this is one dispatch, no retry; reaching this path
    // still proves the runner routed to coder-fix.
    this.dispatchedNonCmrKinds.push(spec.kind);
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

describe("#604 r2 C2 — closure guard runs before blocking→coder-fix on restart", () => {
  it("a new blocker that leaves a protected prior key unaccounted fails closed, not coder-fix", async () => {
    const backend = new ClosureOrderingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: [PROTECTED_PRIOR_KEY],
    });

    // Fail closed — the family run stops; no coder-fix dispatched.
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatchedNonCmrKinds).toEqual([]);
    // The abort must be the closure/contract-drift failure, naming the
    // unaccounted protected prior key — NOT a coder-fix routing of the new blocker.
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: expect.stringContaining("were not explicitly claimed fixed"),
        stopSummary: expect.objectContaining({
          reason: "contract_drift",
        }),
      }),
    );
  });

  it("a new blocker on a FIRST pass (no protected prior keys) still routes to coder-fix", async () => {
    // Regression guard: with NO protected prior keys the closure guard is a
    // no-op and the normal blocking→coder-fix path must be preserved. The
    // backend records + throws on the coder dispatch (runCmrCoderFix catches the
    // throw and returns a not-ok result), so observing the "coder" dispatch
    // proves the runner reached coder-fix instead of failing closed first.
    const backend = new ClosureOrderingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      // No priorCmrFindingIdentityKeys — a first pass, nothing protected.
    });

    expect(result).toEqual({ ok: false, ran: true });
    // The runner reached the coder-fix dispatch (normal blocking path), NOT a
    // closure fail-closed. The ledger records the coder-fix routing, and there
    // is NO "were not explicitly claimed fixed" closure abort.
    expect(backend.dispatchedNonCmrKinds).toEqual(["coder"]);
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
