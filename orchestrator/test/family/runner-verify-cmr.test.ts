/**
 * Family spine ↔ verify-cmr seam wiring (ADR 0022 decision 3④/⑤/⑥, #293 seam 4).
 *
 * #293 keeps the verify-cmr body a no-op, but the SPINE WIRING must already be
 * complete so #296 fills only the hook body:
 *   - the hook is called at BOTH points decision 3 names — the per-wave barrier
 *     ("wave") AND after all waves merge ("final");
 *   - each call carries the phase + the context (#296 needs familyBase +
 *     familyBackend);
 *   - the spine acts on `ok`: a `false` at the wave barrier fails-fast (does NOT
 *     排下一波, decision 3④); a `false` at the end-of-run barrier returns without
 *     pretending success.
 *
 * The hook is injectable via `FamilyRunInput.verifyCmr` (defaulting to the #293
 * no-op module export), so these spine behaviours are testable now via the repo's
 * injected-seam idiom — no module mocking.
 */

import { describe, expect, it } from "vitest";
import { classifyFamilyCmrFindings } from "../../src/family/cmrClassification.js";
import { runFamily } from "../../src/family/runner.js";
import type { Finding } from "../../src/types.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";
import type { VerifyCmrInput, VerifyCmrResult } from "../../src/family/verifyCmr.js";

/** A single-slice Backend that drives every child to S8(success). */
class ChildBackend implements Backend {
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {}
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    return { familyHead: `+${child.childIssue}` };
  }
  // #295 conflict-fallback seam `resolveMergeConflict` is OPTIONAL — this
  // verify-cmr test uses the deterministic (no-conflict) merge path and never
  // reaches it, so the fake omits it.
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 293, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

describe("family spine verify-cmr wiring (#293 seam 4)", () => {
  it("calls the verify hook at the wave barrier AND end-of-run, each with phase + context", async () => {
    const calls: VerifyCmrInput[] = [];
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: false };
    };
    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });
    // One wave (all independent) → one "wave" barrier call + one "final" call.
    expect(calls.map((c) => c.phase)).toEqual(["wave", "final"]);
    // Each carries the family base + the family backend (the #296 context).
    expect(calls.every((c) => c.familyBase === "family/293-base")).toBe(true);
    expect(calls.every((c) => typeof c.familyBackend.appendFamilyLedger === "function")).toBe(
      true,
    );
    // A clean run is observably "success", with no failedPhase.
    expect(result.status).toBe("success");
    expect(result.failedPhase).toBeUndefined();
  });

  it("passes run-option undeveloped modules into the final CMR module context", async () => {
    const calls: VerifyCmrInput[] = [];
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: false };
    };

    await runFamily({
      epic: {
        issue: 293,
        moduleDeclaration: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 293,
        },
        children: [{ issue: 10, blockedBy: [] }],
      },
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      undevelopedModules: [
        {
          module: "military-state-machine",
          moduleScope: ["docs/military-state-machine.md"],
          source: "run_option",
        },
      ],
      verifyCmr,
    });

    expect(calls.at(-1)?.moduleContext).toMatchObject({
      undevelopedModules: [
        {
          module: "military-state-machine",
          moduleScope: ["docs/military-state-machine.md"],
          source: "run_option",
        },
      ],
    });
  });

  it("passes the known #287 hub-loss accepted suppression through production CMR context", async () => {
    const classified: ReturnType<typeof classifyFamilyCmrFindings>[] = [];
    const hubLossFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote:
        "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
      location: "docs/adr/0023.md:D9",
      suggested_fix: "do not block #287 on the accepted #261/ADR0021 hub implementation",
      action: "defer",
      disposition: {
        kind: "cross_module",
        targetModule: "hub",
        reason: "the hub implementation is outside #287",
      },
    };
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "final") {
        classified.push(
          classifyFamilyCmrFindings({
            familyIssue: 287,
            findings: [hubLossFinding],
            moduleContext: input.moduleContext,
          }),
        );
      }
      return { ok: true, ran: false };
    };

    await runFamily({
      epic: {
        issue: 287,
        moduleDeclaration: {
          module: "fiscal",
          moduleScope: ["docs/adr/0023.md"],
          source: "family_issue",
          issue: 287,
        },
        children: [{ issue: 10, blockedBy: [] }],
      },
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/287-base",
      verifyCmr,
    });

    expect(classified).toHaveLength(1);
    expect(classified[0]?.blocking).toEqual([]);
    expect(classified[0]?.results[0]).toMatchObject({
      classification: "accepted_suppressed",
      source: "#303",
      targetModule: "#261/ADR0021 hub implementation",
    });
  });

  it("keeps production admission skips visible in the success stop summary", async () => {
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: {
        ...epicWith(10),
        admissionSkipped: [
          {
            issue: 12,
            reason: "not_ready_for_agent",
            message: "family admission skipped child #12: missing ready-for-agent label",
          },
        ],
      },
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr: async () => ({ ok: true, ran: false }),
    });

    expect(result.status).toBe("success");
    expect(result.admissionSkipped).toEqual([
      {
        issue: 12,
        reason: "not_ready_for_agent",
        message: "family admission skipped child #12: missing ready-for-agent label",
      },
    ]);
    expect(result.stopSummary.metadata?.admissionSkipped).toEqual(result.admissionSkipped);
    expect(familyBackend.ledger).toContainEqual(
      expect.objectContaining({
        childIssue: 12,
        status: "admission_skipped",
        event: "admission_skipped",
        reason: "not_ready_for_agent",
      }),
    );
  });

  it("FAIL-FAST: a red wave verify aborts the loop (no end-of-run call, no further waves)", async () => {
    const phases: string[] = [];
    // Two waves (11 blocked_by 10). The wave verify returns ok:false on the FIRST
    // wave → the loop must abort before selecting wave 2; "final" never runs.
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      phases.push(input.phase);
      return input.phase === "wave" ? { ok: false, ran: true } : { ok: true, ran: true };
    };
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 293,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });
    // Only the first wave's barrier ran; no second wave, no "final".
    expect(phases).toEqual(["wave"]);
    // The red wave is OBSERVABLE in the result — NOT indistinguishable from a
    // clean run (the core of the round-2 finding): status + the failing phase.
    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("wave");
    // Wave 1 merged 10; 11 was never scheduled → recorded "skipped", not dropped.
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([10]);
    const byIssue = new Map(result.children.map((c) => [c.issue, c.status]));
    expect(byIssue.get(10)).toBe("merged");
    expect(byIssue.get(11)).toBe("skipped");
  });

  it("a red end-of-run verify is OBSERVABLY verify_failed (NOT indistinguishable from success), keeping the merged children", async () => {
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> =>
      input.phase === "final" ? { ok: false, ran: true } : { ok: true, ran: true };
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });
    // The red FINAL verify must be observable — a clean run and this run both have
    // all children "merged", so the per-child statuses alone CANNOT distinguish
    // them; the family-level status is what makes the failure visible (round-2
    // finding: a red final verify cannot look like success).
    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("final");
    // The merged children are still returned honestly (decision 3⑤ "不静默吞").
    expect(result.children.map((c) => c.status)).toEqual(["merged", "merged"]);
  });

  it("final stop summary keeps reported, current, and latest verified CMR heads distinct", async () => {
    class FreshHeadFamilyBackend extends FakeFamilyBackend {
      async readFamilyHead(): Promise<string> {
        return "current-head";
      }
    }
    const familyBackend = new FreshHeadFamilyBackend();
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "final") {
        await input.familyBackend.appendFamilyLedger({
          status: "cmr_passed",
          event: "cmr_passed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "current-head",
        });
      }
      return { ok: true, ran: true };
    };

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });

    expect(result.familyHead).toBe("+10");
    expect(result.stopSummary.metadata?.heads).toEqual({
      reportedFamilyHead: "+10",
      actualFamilyHead: "current-head",
      verifiedCmrHead: "current-head",
      sources: {
        reportedFamilyHead: "FamilyRunResult.familyHead",
        actualFamilyHead: "familyBackend.readFamilyHead",
        verifiedCmrHead: "latest cmr_passed ledger row",
      },
    });
  });

  it("defaults to the #293 no-op hook when none is injected (ok, ran:false)", async () => {
    // No verifyCmr in the input → the spine uses the module no-op, which is ok, so
    // the run completes normally (covered by spine.test.ts; here we assert the
    // default path does not abort).
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
    });
    expect(result.children.map((c) => c.status)).toEqual(["merged"]);
    // The no-op default passes → the run is observably "success".
    expect(result.status).toBe("success");
  });

  it("INCOMPLETE: a child whose single-slice run does not succeed makes the family status 'incomplete' (NOT a false 'success')", async () => {
    // Child 11's coder never commits → its single-slice run ends S8(error), so
    // runChild records it "failed". Verify passes (no-op), but the run did NOT
    // fully close: status must be "incomplete", never "success".
    class OneChildFailsBackend extends ChildBackend {
      override async runStep(spec: StepSpec): Promise<StepOutput> {
        // The failing child is dispatched on its own runner; we fail the coder for
        // EVERY run here and pair it with a single-failing-child epic below.
        if (spec.role === "coder") {
          return { kind: "coder", committed: false, commitsAdded: 0 };
        }
        return { kind: "reviewer", findings: [] };
      }
    }
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: epicWith(11),
      familyBackend,
      singleSliceBackend: new OneChildFailsBackend(),
      familyBase: "family/293-base",
    });
    // The child failed → it never merged → the family run is "incomplete".
    expect(result.status).toBe("incomplete");
    expect(result.failedPhase).toBeUndefined();
    expect(result.children).toEqual([{ issue: 11, status: "failed" }]);
    // No merge / ledger write for a failed child.
    expect(familyBackend.merges).toEqual([]);
    expect(familyBackend.ledger).toEqual([]);
  });

  it("LEDGER-AWARE finalize: a child already merged in the ledger is reported already_done, not skipped", async () => {
    // Pre-seed the family ledger with child 10 already merged (e.g. a prior
    // invocation — #298's resume truth). The commander excludes 10 (already
    // merged), so it is never run THIS invocation; finalize must report it as
    // already_done, NOT "skipped".
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push({ childIssue: 10, status: "merged" });
      }
    }
    const familyBackend = new PreSeededFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
    });
    // Only 11 actually runs + merges this invocation; 10 is already-merged truth.
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([11]);
    const byIssue = new Map(result.children.map((c) => [c.issue, c.status]));
    expect(byIssue.get(10)).toBe("already_done"); // from the ledger, not "skipped"
    expect(byIssue.get(11)).toBe("merged");
    // Every child merged (one via ledger, one this run) → "success".
    expect(result.status).toBe("success");
  });
});
