/**
 * Wiring 2 (#291 整合缺口 2) — a red verify's `aborted` event reaches the DURABLE
 * family ledger that reconcile reads, in a PHASE-LEVEL shape (ADR 0022 decision
 * 3④/5).
 *
 * #296 surfaced a red verify only through the in-memory seam
 * `backend.recordAborted?(event)` (a fake's array). But the crash-window reconcile
 * (decision 5) reads the DURABLE ledger末条 `familyHeadAfter` — and an abort that
 * lived ONLY in the seam never reached it, so a resume after a red wave could not
 * see the family base was aborted. This wiring closes the gap:
 *
 *   - the durable `aborted` entry is PHASE-LEVEL — `{event:"aborted",
 *     phase:"wave"|"final", familyHeadAfter:<abort-time head>, reason, status:
 *     "aborted"}` — NOT child-level (an abort is a phase verify/cmr failure, not a
 *     single child's). It REUSES `familyHeadAfter` so reconcile's existing "read末条
 *     familyHeadAfter" baseline logic covers merged AND aborted uniformly;
 *   - the red verify path STILL fires the in-memory seam (back-compat) AND ALSO
 *     appends the durable entry through the same `appendFamilyLedger` JSONL the
 *     reconcile baseline is read from;
 *   - `mergedSet` still filters `status==="merged"` only, so an aborted entry never
 *     counts as a merged child (the unblock truth is untouched).
 *
 * Zero container: child on a fake Backend; family verify/cmr/abort on a scriptable
 * fake FamilyBackend — no real git / codex.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../src/family/runner.js";
import { mergedSet } from "../../src/family/ledger.js";
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
  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  MergeResult,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
} from "../../src/family/types.js";

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
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

/** A capable family backend that records both the seam aborts AND the ledger. */
class AbortingFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  currentFamilyHead = "head-1";
  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
    } = {},
  ) {}
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    this.currentFamilyHead = `+${child.childIssue}`;
    return { familyHead: this.currentFamilyHead, childHead: `c${child.childIssue}` };
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
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    const result =
      this.script.cmr?.(req) ?? {
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    return { url: `pr://${req.familyBase}`, prHead: this.currentFamilyHead };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
}

const TWO_WAVES: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 294, blockedBy: [] },
    { issue: 296, blockedBy: [294] },
  ],
};

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 291, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

describe("Wiring 2 — a red wave verify writes a PHASE-LEVEL durable aborted entry (#291 缺口 2)", () => {
  it("appends {status:'aborted', phase:'wave', familyHeadAfter} to the durable ledger (not just the seam array)", async () => {
    // Wave 1 = {294} merges (familyHead "+294"); the wave verify is RED → abort
    // BEFORE wave 2. The durable ledger must record the abort phase-level.
    const backend = new AbortingFamilyBackend({
      verify: (req) =>
        req.phase === "wave"
          ? { ok: false, errorPackage: { reason: "tsc: TS2345 cross-slice type" } }
          : { ok: true },
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("wave");

    // The seam still fired (back-compat).
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("wave");

    // The DURABLE ledger now ALSO has a phase-level aborted entry — this is the
    // reconcile-readable truth the seam alone never reached.
    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    const abort = aborts[0]!;
    expect(abort.event).toBe("aborted");
    expect(abort.phase).toBe("wave");
    // PHASE-LEVEL: no childIssue (an abort is not a single child's failure).
    expect("childIssue" in abort).toBe(false);
    // Carries the abort-time family head in `familyHeadAfter` (reconcile reads末条).
    expect(abort.familyHeadAfter).toBe("+294");
    expect(abort.reason).toContain("TS2345");

    // mergedSet is untouched: 294 merged counts; the aborted entry does NOT.
    const merged = mergedSet(backend.ledger);
    expect(merged.has(294)).toBe(true);
    expect([...merged]).toEqual([294]); // only the real merge, no aborted child
  });

  it("a red FINAL verify writes a phase-level {status:'aborted', phase:'final'} durable entry too", async () => {
    // The final-phase FULL verify is red (it gates the cmr 承重闸, which never runs).
    // The durable aborted entry must record phase:"final" + the abort-time head.
    const backend = new AbortingFamilyBackend({
      verify: (req) =>
        req.phase === "final"
          ? { ok: false, errorPackage: { reason: "vitest: 3 failed cross-slice e2e" } }
          : { ok: true },
    });
    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("final");

    const aborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(aborts).toHaveLength(1);
    expect(aborts[0]?.phase).toBe("final");
    expect(aborts[0]?.event).toBe("aborted");
    expect("childIssue" in aborts[0]!).toBe(false);
    // Both children merged before the final verify → abort-time head is the last merge.
    expect(aborts[0]?.familyHeadAfter).toBe("+295");
    expect(aborts[0]?.reason).toContain("vitest");
  });

  it("a clean all-green run writes NO aborted entry", async () => {
    const backend = new AbortingFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });
    expect(backend.ledger.filter((e) => e.status === "aborted")).toEqual([]);
  });
});
