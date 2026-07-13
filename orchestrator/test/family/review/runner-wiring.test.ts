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
import {
  pendingPriorCmrFindingIdentityKeysByPass,
  runFamily,
} from "../../../src/family/runner.js";
import { findingIdentityKey } from "../../../src/findings.js";
import type { Finding } from "../../../src/types.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../../src/dispatchRetry.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import type { VerifyCmrInput, VerifyCmrResult } from "../../../src/family/verifyCmr.js";
import type { FindingDisposition } from "../../../src/types.js";

/** A single-slice Backend that drives every child to S8(success). */
class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
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
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/** Models an old persisted CMR-abort row using the current durable shape. */
function readLegacyPersistedCmrAbort(): FamilyLedgerEntry {
  const persistedLegacyRow = {
    status: "aborted" as const,
    event: "aborted" as const,
    phase: "final" as const,
    cmrPass: "correctness" as const,
    familyHeadAfter: "head-after-coder-fix",
    blockingFindingIdentityKeys: [],
    reason: "integrated cmr correctness did not converge",
  };
  return persistedLegacyRow;
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

const COMPLETE_CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;

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

  it("passes run-option accepted suppression sources into the final CMR module context", async () => {
    const calls: VerifyCmrInput[] = [];
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: false };
    };
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Owner accepted this exact finding for the family CMR scope",
      findingIdentity:
        "correctness|orchestrator/src/family/verifyCmr.ts:42|accepted source",
      boundedReopen: "reopen on different scope, higher severity, or new evidence",
    };

    await runFamily({
      epic: {
        issue: 445,
        moduleDeclaration: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        children: [{ issue: 10, blockedBy: [] }],
      },
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/445-base",
      acceptedSuppressionSources: [acceptedSource],
      verifyCmr,
    });

    expect(calls.at(-1)?.moduleContext?.acceptedSuppressionSources).toEqual([
      acceptedSource,
    ]);
  });

  it("passes suppression-only module context into the final CMR hook", async () => {
    const calls: VerifyCmrInput[] = [];
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: false };
    };
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Owner accepted this exact finding for the family CMR scope",
      findingIdentity:
        "correctness|orchestrator/src/family/verifyCmr.ts:42|accepted source",
      boundedReopen: "reopen on different scope, higher severity, or new evidence",
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/445-base",
      acceptedSuppressionSources: [acceptedSource],
      verifyCmr,
    });

    expect(calls.at(-1)?.moduleContext).toMatchObject({
      currentModules: [],
      childModules: [],
      acceptedSuppressionSources: [acceptedSource],
    });
  });

  it("passes undeveloped-module-only context into the final CMR hook", async () => {
    const calls: VerifyCmrInput[] = [];
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: false };
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/445-base",
      undevelopedModules: [
        {
          module: "route-accounting",
          moduleScope: ["orchestrator/src/modelRoutes.ts"],
          source: "run_option",
        },
      ],
      verifyCmr,
    });

    expect(calls.at(-1)?.moduleContext).toMatchObject({
      currentModules: [],
      childModules: [],
      undevelopedModules: [
        {
          module: "route-accounting",
          moduleScope: ["orchestrator/src/modelRoutes.ts"],
          source: "run_option",
        },
      ],
    });
  });

  it("keeps pending correctness CMR finding keys across a newer unrelated completeness pass", async () => {
    // #604 slice 2 / ADR 0062: the runner derives pending keys from the classification's
    // `blocking` findings (counted, not content-classified), so the seeded aborted row
    // carries the blocker as a real Finding whose identity key drives recovery.
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "correctness blocker",
      location: "orchestrator/src/family/verifyCmr.ts:42",
      suggested_fix: "close the correctness blocker",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);
    const calls: VerifyCmrInput[] = [];
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push(
          { childIssue: 10, status: "merged" },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
            blockingFindingIdentityKeys: [priorKey],
            cmrDispositions: [],
          },
          {
            status: "cmr_passed",
            event: "cmr_passed",
            phase: "final",
            cmrPass: "completeness",
            familyHeadAfter: "family-head",
          },
        );
      }
    }
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: true };
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });

    expect((calls.at(-1) as VerifyCmrInput & {
      priorCmrFindingIdentityKeysByPass?: { correctness?: readonly string[] };
    })?.priorCmrFindingIdentityKeysByPass?.correctness).toEqual([priorKey]);
    expect(calls.at(-1)?.priorCmrFindingIdentityKeys).toBeUndefined();
  });

  it("keeps only the newest aborted finding set for a CMR pass", async () => {
    // #604 slice 2 / ADR 0062: pending keys are derived from the classification's
    // `blocking` findings, so each seeded aborted row carries its blockers as real
    // Findings whose identity keys the runner recovers.
    const oldFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "old blocker",
      location: "orchestrator/src/family/verifyCmr.ts:41",
      suggested_fix: "close the old blocker",
      action: "fix_now",
    };
    const newFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "new blocker",
      location: "orchestrator/src/family/verifyCmr.ts:42",
      suggested_fix: "close the new blocker",
      action: "fix_now",
    };
    const newerFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "newer blocker",
      location: "orchestrator/src/family/verifyCmr.ts:43",
      suggested_fix: "close the newer blocker",
      action: "fix_now",
    };
    const oldKey = findingIdentityKey(oldFinding);
    const newKey = findingIdentityKey(newFinding);
    const newerKey = findingIdentityKey(newerFinding);
    const calls: VerifyCmrInput[] = [];
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push(
          { childIssue: 10, status: "merged" },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
            blockingFindingIdentityKeys: [oldKey],
            cmrDispositions: [],
          },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
            blockingFindingIdentityKeys: [newKey, newerKey],
            cmrDispositions: [],
          },
        );
      }
    }
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: true };
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });

    expect((calls.at(-1) as VerifyCmrInput & {
      priorCmrFindingIdentityKeysByPass?: { correctness?: readonly string[] };
    })?.priorCmrFindingIdentityKeysByPass?.correctness).toEqual([newKey, newerKey]);
  });

  it("does not use an older CMR review as crash-window evidence after a no-head-movement coder-fix abort", async () => {
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "coder-fix must prove repair evidence before closure",
      location: "orchestrator/src/family/verifyCmr.ts:runCmrCoderFix",
      suggested_fix: "do not treat aborted evidence failure as crash-window repair",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);
    const calls: VerifyCmrInput[] = [];
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push(
          { childIssue: 10, status: "merged" },
          {
            status: "cmr_reviewed",
            event: "cmr_reviewed",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-before-coder-fix",
            // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
            blockingFindingIdentityKeys: [priorKey],
            cmrDispositions: [],
          },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-before-coder-fix",
            reason:
              "integrated cmr correctness coder-fix repair evidence gate failed after 3 attempts",
            stopSummary: {
              reason: "contract_drift",
              summary:
                "integrated CMR correctness coder-fix failed: repair evidence gate failed",
              repairHint:
                "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
            },
          },
        );
      }
      async readFamilyHead(): Promise<string> {
        return "head-before-coder-fix";
      }
    }
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: true };
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });

    expect((calls.at(-1) as VerifyCmrInput & {
      priorCmrFindingIdentityKeysByPass?: { correctness?: readonly string[] };
    })?.priorCmrFindingIdentityKeysByPass?.correctness).toBeUndefined();
  });

  it("preserves older CMR review keys after a head-moving coder-fix evidence-gate abort", async () => {
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "coder-fix must prove repair evidence before closure",
      location: "orchestrator/src/family/verifyCmr.ts:runCmrCoderFix",
      suggested_fix: "do not bypass missing repair evidence after a committed repair",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);
    const calls: VerifyCmrInput[] = [];
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push(
          { childIssue: 10, status: "merged" },
          {
            status: "cmr_reviewed",
            event: "cmr_reviewed",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-before-coder-fix",
            // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
            blockingFindingIdentityKeys: [priorKey],
            cmrDispositions: [],
          },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-after-bad-coder-fix",
            reason:
              "integrated cmr correctness coder-fix repair evidence gate failed after 3 attempts",
            stopSummary: {
              reason: "contract_drift",
              summary:
                "integrated CMR correctness coder-fix failed: repair evidence gate failed",
              repairHint:
                "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
            },
          },
        );
      }
      async readFamilyHead(): Promise<string> {
        return "head-after-bad-coder-fix";
      }
    }
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      calls.push(input);
      return { ok: true, ran: true };
    };

    await runFamily({
      epic: epicWith(10),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr,
    });

    expect((calls.at(-1) as VerifyCmrInput & {
      priorCmrFindingIdentityKeysByPass?: { correctness?: readonly string[] };
    })?.priorCmrFindingIdentityKeysByPass?.correctness).toEqual([priorKey]);
  });

  it("does not derive pending keys from cmr_reviewed after a newer no-head-movement coder-fix abort row", () => {
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "coder-fix must prove repair evidence before closure",
      location: "orchestrator/src/family/verifyCmr.ts:runCmrCoderFix",
      suggested_fix: "do not treat aborted evidence failure as crash-window repair",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);

    const pending = pendingPriorCmrFindingIdentityKeysByPass(
      [
        { childIssue: 10, status: "merged" },
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-before-coder-fix",
          // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
          blockingFindingIdentityKeys: [priorKey],
          cmrDispositions: [],
        } as FamilyLedgerEntry,
        {
          status: "aborted",
          event: "aborted",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-before-coder-fix",
          reason:
            "integrated cmr correctness coder-fix repair evidence gate failed after 3 attempts",
          stopSummary: {
            reason: "contract_drift",
            summary:
              "integrated CMR correctness coder-fix failed: repair evidence gate failed",
            repairHint:
              "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
          },
        } as FamilyLedgerEntry,
      ],
      "head-before-coder-fix",
    );

    expect(pending.correctness).toBeUndefined();
  });

  it("derives pending keys from cmr_reviewed after a newer head-moving coder-fix abort row", () => {
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "coder-fix must prove repair evidence before closure",
      location: "orchestrator/src/family/verifyCmr.ts:runCmrCoderFix",
      suggested_fix: "do not bypass missing repair evidence after a committed repair",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);

    const pending = pendingPriorCmrFindingIdentityKeysByPass(
      [
        { childIssue: 10, status: "merged" },
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-before-coder-fix",
          // #604 slice 3 / ADR 0062: the runner reads only the thin envelope now.
          blockingFindingIdentityKeys: [priorKey],
          cmrDispositions: [],
        } as FamilyLedgerEntry,
        {
          status: "aborted",
          event: "aborted",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-after-bad-coder-fix",
          reason:
            "integrated cmr correctness coder-fix repair evidence gate failed after 3 attempts",
          stopSummary: {
            reason: "contract_drift",
            summary:
              "integrated CMR correctness coder-fix failed: repair evidence gate failed",
            repairHint:
              "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
          },
        } as FamilyLedgerEntry,
      ],
      "head-after-bad-coder-fix",
    );

    expect(pending.correctness).toEqual([priorKey]);
  });

  it("keeps committed CMR fix keys when a later re-review abort has no classification", () => {
    const priorKey =
      "correctness|orchestrator/src/family/verifycmr.ts:45|post fix re-review aborted";

    const pending = pendingPriorCmrFindingIdentityKeysByPass(
      [
        { childIssue: 10, status: "merged" },
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-before-coder-fix",
        } as FamilyLedgerEntry,
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadBefore: "head-before-coder-fix",
          familyHeadAfter: "head-after-coder-fix",
          blockingFindingIdentityKeys: [priorKey],
        } as FamilyLedgerEntry,
        {
          status: "aborted",
          event: "aborted",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: "head-after-coder-fix",
          reason: "integrated cmr correctness provider floor failed after coder-fix",
          stopSummary: {
            reason: "provider_degraded",
            summary: "post-fix CMR re-review did not have a strong leg",
          },
        } as FamilyLedgerEntry,
      ],
      "head-after-coder-fix",
    );

    expect(pending.correctness).toEqual([priorKey]);
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

  it("verify_failed ignores earlier success summaries when no aborted barrier row exists", async () => {
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
      verifyCmr: async (input) =>
        input.phase === "final" ? { ok: false, ran: true } : { ok: true, ran: true },
    });

    expect(result.status).toBe("verify_failed");
    expect(result.stopSummary.reason).toBe("infra_failure");
    expect(result.stopSummary.summary).toMatch(/final verify\/cmr barrier failed/);
  });

  it("verify_failed does not reuse stale aborted rows from before the current final barrier", async () => {
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push(
          { childIssue: 10, status: "merged" },
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            stopSummary: {
              reason: "same_module_still_red",
              summary: "old CMR blocker",
              repairHint: "old repair hint",
            },
          },
        );
      }
    }

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
      verifyCmr: async (input) =>
        input.phase === "final" ? { ok: false, ran: true } : { ok: true, ran: true },
    });

    expect(result.status).toBe("verify_failed");
    expect(result.stopSummary.reason).toBe("infra_failure");
    expect(result.stopSummary.summary).toMatch(/final verify\/cmr barrier failed/);
    expect(result.stopSummary.summary).not.toContain("old CMR blocker");
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

  it("success stop summary ignores null ledger head metadata instead of crashing", async () => {
    const familyBackend = new FakeFamilyBackend();
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "final") {
        await input.familyBackend.appendFamilyLedger({
          status: "cmr_passed",
          event: "cmr_passed",
          phase: "final",
          cmrPass: "correctness",
          familyHeadAfter: null as never,
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

    expect(result.status).toBe("success");
    expect(result.stopSummary.metadata?.heads).toEqual({
      reportedFamilyHead: "+10",
      actualFamilyHead: "+10",
      sources: {
        reportedFamilyHead: "FamilyRunResult.familyHead",
        actualFamilyHead: "family runner current head",
      },
    });
  });

  it("success stop summary preserves material final CMR metadata from the ledger", async () => {
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
          stopSummary: {
            reason: "success",
            summary: "run completed successfully",
            metadata: {
              acceptedSuppressions: [
                {
                  source: "issue #448 acceptance criteria",
                  scope: "same claimed-fixed finding",
                  reason: "owner accepted this bounded nonblocking case",
                  findingIdentity: "correctness|src/family.ts:1|bounded case",
                  boundedReopen: "reopen if severity increases or scope changes",
                },
              ],
            },
          },
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

    expect(result.status).toBe("success");
    expect(result.stopSummary.metadata?.acceptedSuppressions).toEqual([
      {
        source: "issue #448 acceptance criteria",
        scope: "same claimed-fixed finding",
        reason: "owner accepted this bounded nonblocking case",
        findingIdentity: "correctness|src/family.ts:1|bounded case",
        boundedReopen: "reopen if severity increases or scope changes",
      },
    ]);
    expect(result.stopSummary.metadata?.heads?.verifiedCmrHead).toBe("current-head");
  });

  it("success stop summary preserves material shipped metadata from the ledger", async () => {
    class FreshHeadFamilyBackend extends FakeFamilyBackend {
      async readFamilyHead(): Promise<string> {
        return "current-head";
      }
    }
    const familyBackend = new FreshHeadFamilyBackend();
    const verifyCmr = async (input: VerifyCmrInput): Promise<VerifyCmrResult> => {
      if (input.phase === "final") {
        await input.familyBackend.appendFamilyLedger({
          status: "shipped",
          event: "shipped",
          phase: "final",
          pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/999",
          familyHeadAfter: "current-head",
          stopSummary: {
            reason: "success",
            summary: "run completed successfully",
            metadata: {
              providerDegraded: [
                {
                  provider: "sourcery",
                  leg: "sourcery",
                  reason: "diff larger than review limit",
                  blocking: false,
                },
              ],
            },
          },
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

    expect(result.status).toBe("success");
    expect(result.stopSummary.metadata?.providerDegraded).toEqual([
      {
        provider: "sourcery",
        leg: "sourcery",
        reason: "diff larger than review limit",
        blocking: false,
      },
    ]);
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
          throw new Error("coder process crashed");
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

  it("INCOMPLETE summary excludes children already merged in the family ledger", async () => {
    class OneChildFailsBackend extends ChildBackend {
      override async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          throw new Error("coder process crashed");
        }
        return { kind: "reviewer", findings: [] };
      }
    }
    class PreSeededFamilyBackend extends FakeFamilyBackend {
      constructor() {
        super();
        this.ledger.push({ childIssue: 10, status: "merged" });
      }
    }

    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend: new PreSeededFamilyBackend(),
      singleSliceBackend: new OneChildFailsBackend(),
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("incomplete");
    expect(result.children).toEqual([
      { issue: 11, status: "failed" },
      { issue: 10, status: "already_done" },
    ]);
    expect(result.stopSummary.summary).toContain("#11:failed");
    expect(result.stopSummary.summary).not.toContain("#10:already_done");
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

  // #604 slice 3 / ADR 0062: the runner reads only the THIN control envelope. A
  // red integrated CMR review must persist `blockingFindingIdentityKeys` (the
  // runner's only pending-key source) + `cmrDispositions` (the gate's cross-round
  // prior-disposition source) — NOT the fat `cmrFindingClassification` structure
  // (Finding full text / results[] audit / dispositions[] merged into one blob).
  describe("thin CMR envelope on the ledger (#604 slice 3 / ADR 0062)", () => {
    const CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;

    /** Drive the real final CMR gate; no coder-fix worker so a blocker aborts. */
    class ScriptedCmrBackend extends FakeFamilyBackend {
      constructor(private readonly cmrOutput: WorkerResult) {
        super();
      }
      async runFamilyVerify(): Promise<{ ok: true }> {
        return { ok: true };
      }
      async readFamilyHead(): Promise<string> {
        return "head-after-cmr";
      }
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") return this.cmrOutput;
        // No coder-fix worker: the coder-fix dispatch fails → the family aborts,
        // but the pre-fix `cmr_reviewed` row is the row under test.
        throw new Error(`unexpected worker kind ${spec.kind}`);
      }
    }

    const blocker: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "family CMR blocker still red",
      location: "orchestrator/src/family/verifyCmr.ts:7",
      suggested_fix: "close the family CMR blocker",
      action: "fix_now",
    };
    const blockerKey = findingIdentityKey(blocker);

    const blockingCmrOutput: WorkerResult = {
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        findingsCount: 1,
        reason: "family CMR found a blocking finding",
        successfulLegs: [...CMR_LEGS],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review-summary.json"],
        findings: [blocker],
      },
    };

    it("persists only finding identity keys, never content-derived dispositions or the fat classification", async () => {
      const backend = new ScriptedCmrBackend(blockingCmrOutput);
      const result = await runVerifyCmr({
        phase: "final",
        familyBase: "family/604-base",
        familyBackend: backend,
        familyIssue: 604,
      });

      expect(result).toEqual({ ok: false, ran: true });
      const reviewed = backend.ledger.find(
        (entry) => entry.status === "cmr_reviewed",
      );
      expect(reviewed).toBeDefined();
      // The runner's only pending-key source is present…
      expect(reviewed!.blockingFindingIdentityKeys).toEqual([blockerKey]);
      // Content-derived disposition judgment belongs to the worker, not the runner.
      expect(reviewed).not.toHaveProperty("cmrDispositions");
      // The fat structure the runner used to read from is GONE.
      expect(reviewed).not.toHaveProperty("cmrFindingClassification");
    });

    it("lets the runner rebuild pending keys from the thin envelope alone", () => {
      // Read-path proof: a `cmr_reviewed` row carrying ONLY the thin
      // `blockingFindingIdentityKeys` envelope, followed by a head-moving coder-fix
      // abort, must let the runner recover the pending keys. Before slice 3 the
      // runner read `cmrFindingClassification` — a thin-field-only row yielded
      // nothing (RED); now it reads `blockingFindingIdentityKeys` directly (GREEN).
      const pending = pendingPriorCmrFindingIdentityKeysByPass(
        [
          { childIssue: 10, status: "merged" },
          {
            status: "cmr_reviewed",
            event: "cmr_reviewed",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-before-coder-fix",
            blockingFindingIdentityKeys: [blockerKey],
            cmrDispositions: [],
          } satisfies FamilyLedgerEntry,
          {
            status: "aborted",
            event: "aborted",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-after-bad-coder-fix",
            reason:
              "integrated cmr correctness coder-fix repair evidence gate failed after 3 attempts",
            stopSummary: {
              reason: "contract_drift",
              summary: "integrated CMR correctness coder-fix failed",
              repairHint: "repair the family CMR coder-fix worker contract",
            },
          } satisfies FamilyLedgerEntry,
        ],
        "head-after-bad-coder-fix",
      );
      expect(pending.correctness).toEqual([blockerKey]);
    });

    // #604 correctness r1 (P1-e): a coder-fix committed its claimed-fixed keys,
    // then the re-review NOT_CONVERGED with an EMPTY classified envelope
    // (`blockingFindingIdentityKeys: []`). The empty abort must NOT MASK the older
    // fix-commit's pending keys — they are still awaiting ADR 0030 closure and the
    // next fresh reviewer must be told to cover them.
    it("keeps committed CMR fix keys after a later not_converged EMPTY classified abort", () => {
      const pending = pendingPriorCmrFindingIdentityKeysByPass(
        [
          { childIssue: 10, status: "merged" },
          {
            status: "cmr_reviewed",
            event: "cmr_reviewed",
            phase: "final",
            cmrPass: "correctness",
            familyHeadAfter: "head-before-coder-fix",
            blockingFindingIdentityKeys: [blockerKey],
            cmrDispositions: [],
          } satisfies FamilyLedgerEntry,
          {
            status: "cmr_fix_committed",
            event: "cmr_fix_committed",
            phase: "final",
            cmrPass: "correctness",
            familyHeadBefore: "head-before-coder-fix",
            familyHeadAfter: "head-after-coder-fix",
            blockingFindingIdentityKeys: [blockerKey],
          } satisfies FamilyLedgerEntry,
          // not_converged sentinel: a CLASSIFIED abort carrying an EMPTY envelope.
          readLegacyPersistedCmrAbort(),
        ],
        "head-after-coder-fix",
      );

      // The pending keys survive the empty not_converged abort.
      expect(pending.correctness).toEqual([blockerKey]);
    });

    it("reads cross-round prior dispositions from cmrDispositions, not the fat blob", () => {
      const prior: FindingDisposition = {
        identityKey: blockerKey,
        status: "accepted_suppressed",
        reason: "accepted by family issue scope",
        severity: "medium",
        reopenAttempts: 0,
        disputeAttempts: 1,
        source: "issue #604 acceptance criteria",
        scope: "#604 family integrated CMR",
        boundedReopen: "reopen on higher severity or different scope",
      };
      class PriorDispositionBackend extends FakeFamilyBackend {
        constructor() {
          super();
          this.ledger.push(
            { childIssue: 10, status: "merged" },
            {
              status: "cmr_reviewed",
              event: "cmr_reviewed",
              phase: "final",
              cmrPass: "correctness",
              familyHeadAfter: "head-prior",
              blockingFindingIdentityKeys: [blockerKey],
              cmrDispositions: [prior],
            } as FamilyLedgerEntry,
          );
        }
      }
      const backend = new PriorDispositionBackend();
      // The gate reads the latest cmrDispositions off the ledger for its next pass.
      // With the fat blob removed, the read must come from `cmrDispositions`.
      const seen = backend.ledger
        .slice()
        .reverse()
        .find((entry) => entry.cmrDispositions !== undefined);
      expect(seen?.cmrDispositions).toEqual([prior]);
    });
  });
});
