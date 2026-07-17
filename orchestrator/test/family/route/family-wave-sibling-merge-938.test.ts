/**
 * #938 — family wave keeps sibling results and trusts the merger worker.
 *
 * Production seams only (#934 Testing Decisions / ID-016):
 *   - public family spine: runFamily (ignition/driver path's Family Integration
 *     Merge Action / wave owner)
 *   - Family Integration Merge Action entry: mergeChild
 *   - unified worker dispatch: resolveMergeConflict is the merger worker leg;
 *     process-root retry lives inside that leg (ID-004), never as a host
 *     still-conflicted re-dispatch court
 *
 * Contracts: #934 ID-009, ID-010, ID-015, ID-016.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { mergeChild } from "../../../src/family/merger.js";
import { runFamily } from "../../../src/family/runner.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import type {
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  ConflictResolveRequest,
  FamilyBackend,
  FamilyEscalation,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
  MergeResult,
} from "../../../src/family/types.js";

// ─── fakes ────────────────────────────────────────────────────────────────────

class OkChildBackend implements Backend {
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
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/** One sibling returns structured non-success (failed single-slice). */
class SiblingFailBackend extends OkChildBackend {
  constructor(private readonly failIssues: ReadonlySet<number>) {
    super();
  }
  override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    const meta = await super.fetchIssueMeta(issueNumber);
    if (this.failIssues.has(issueNumber)) {
      return { ...meta, openBlockedBy: [999] };
    }
    return meta;
  }
}

class RecordingFamilyBackend implements FamilyBackend {
  readonly mergeOrder: number[] = [];
  readonly resolverCalls: ConflictResolveRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly escalationCalls: FamilyEscalation[] = [];

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    this.mergeOrder.push(child.childIssue);
    return { familyHead: `h${child.childIssue}` };
  }
  async resolveMergeConflict(req: ConflictResolveRequest): Promise<MergeResult> {
    this.resolverCalls.push(req);
    return { familyHead: `resolved-${req.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async escalateFamily(escalation: FamilyEscalation): Promise<void> {
    this.escalationCalls.push(escalation);
  }
}

class ConflictOnceFamilyBackend extends RecordingFamilyBackend {
  constructor(
    private readonly conflictIssues: ReadonlySet<number>,
    private readonly stillConflicted: boolean = false,
    private readonly decisionOnResolve: FamilyEscalation | undefined = undefined,
  ) {
    super();
  }
  override async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    this.mergeOrder.push(child.childIssue);
    if (this.conflictIssues.has(child.childIssue)) {
      return { familyHead: `conflicted-${child.childIssue}`, conflicted: true };
    }
    return { familyHead: `h${child.childIssue}` };
  }
  override async resolveMergeConflict(req: ConflictResolveRequest): Promise<MergeResult> {
    this.resolverCalls.push(req);
    if (this.decisionOnResolve !== undefined) {
      return {
        familyHead: `conflicted-${req.childIssue}`,
        conflicted: true,
        escalation: this.decisionOnResolve,
      };
    }
    if (this.stillConflicted) {
      return { familyHead: `conflicted-${req.childIssue}`, conflicted: true };
    }
    return { familyHead: `resolved-${req.childIssue}` };
  }
}

// ─── ID-009: wave aggregation keeps siblings ─────────────────────────────────

describe("#938 public runFamily — ID-009 wave keeps siblings", () => {
  it("POSITIVE: successful sibling still merges when another child returns failed", async () => {
    const familyBackend = new RecordingFamilyBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new SiblingFailBackend(new Set([11])),
      familyBase: "family/938-base",
    });

    expect(familyBackend.mergeOrder).toEqual([10]);
    expect(result.children).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ issue: 10, status: "merged" }),
        expect.objectContaining({ issue: 11, status: "failed" }),
      ]),
    );
    expect(result.status).toBe("incomplete");
    // Per-sibling root causes ride diagnostics — not a blank incomplete.
    expect(result.diagnostics ?? []).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          issue: 11,
          kind: "child_execution",
        }),
      ]),
    );
    expect(JSON.stringify(result.diagnostics)).toMatch(/11/);
    // Public children[] must keep the settled failureCause (not drop on push).
    const failed = result.children.find((c) => c.issue === 11);
    expect(failed?.status).toBe("failed");
    expect(failed?.failureCause).toEqual(expect.stringMatching(/11/));
  });

  it("POSITIVE: hard-fail sibling keeps failureCause on final children[]", async () => {
    class PrepareThrowBackend extends OkChildBackend {
      override async prepareWorktree(
        issueNumber: number,
        base: string,
      ): Promise<WorktreeHandle> {
        if (issueNumber === 11) {
          throw new Error("child #11 process crashed before worktree cut");
        }
        return super.prepareWorktree(issueNumber, base);
      }
    }
    const familyBackend = new RecordingFamilyBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new PrepareThrowBackend(),
      familyBase: "family/938-base",
    });

    expect(result.status).toBe("incomplete");
    const failed = result.children.find((c) => c.issue === 11);
    expect(failed?.status).toBe("failed");
    // Settled wave cause must survive the childResults push (must-1).
    expect(typeof failed?.failureCause).toBe("string");
    expect(failed?.failureCause).toEqual(expect.stringMatching(/11/));
  });

  it("POSITIVE: successful sibling still merges when another child hard-fails (no rethrow-first wipe)", async () => {
    // A hard worktree cut failure used to risk wiping the whole wave via
    // rethrow-first. #938 must keep #10's merge and still record #11.
    class PrepareThrowBackend extends OkChildBackend {
      override async prepareWorktree(
        issueNumber: number,
        base: string,
      ): Promise<WorktreeHandle> {
        if (issueNumber === 11) {
          throw new Error("child #11 process crashed before worktree cut");
        }
        return super.prepareWorktree(issueNumber, base);
      }
    }
    const familyBackend = new RecordingFamilyBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new PrepareThrowBackend(),
      familyBase: "family/938-base",
    });

    // ID-009: wave aggregation keeps every sibling — no whole-wave wipe.
    expect(familyBackend.mergeOrder).toEqual([10]);
    expect(result.status).toBe("incomplete");
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("merged");
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("failed");
    expect(result.diagnostics ?? []).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          issue: 11,
          cause: expect.stringMatching(/11/),
        }),
      ]),
    );
    // Source guard: rethrow-first court is gone.
    const runnerSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/runner.ts"),
      "utf8",
    );
    expect(runnerSrc).not.toMatch(/firstRejected/);
  });

  it("POSITIVE: residual dependency_cycle only after empty wave — independent sibling still merges", async () => {
    const familyBackend = new RecordingFamilyBackend();
    const epic: FamilyEpic = {
      issue: 938,
      children: [
        { issue: 99, blockedBy: [] },
        { issue: 10, blockedBy: [11] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    // ID-009: cycle does NOT block the already-runnable component.
    expect(familyBackend.mergeOrder).toEqual([99]);
    expect(result.children.find((c) => c.issue === 99)?.status).toBe("merged");
    // Residual cycle is the typed outer boundary (not silent empty-wave success).
    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toMatch(/dependency_cycle/i);
    expect(result.stopSummary.summary).toMatch(/dependency_cycle/i);
    // Cycle members never merged.
    expect(result.children.find((c) => c.issue === 10)?.status).not.toBe("merged");
    expect(result.children.find((c) => c.issue === 11)?.status).not.toBe("merged");
  });

  it("POSITIVE: pure residual cycle (no runnable) surfaces dependency_cycle without startup whole-family guard throw", async () => {
    const familyBackend = new RecordingFamilyBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [11] },
          { issue: 11, blockedBy: [10] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    expect(familyBackend.mergeOrder).toEqual([]);
    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toMatch(/dependency_cycle/i);
    // Not an uncaught throw from startup assertAcyclic.
    expect(result.children).toHaveLength(2);
  });
});

// ─── ID-010: trust merger worker; no host still-conflicted court / cap ───────

describe("#938 mergeChild + runFamily — ID-010 trust merger worker", () => {
  it("POSITIVE: clean merge never calls the merger worker (deterministic queue only)", async () => {
    const backend = new ConflictOnceFamilyBackend(/* no conflicts */ new Set());
    const result = await mergeChild(backend, {
      childIssue: 10,
      childBranch: "feat/child-10",
    });
    expect(backend.mergeOrder).toEqual([10]);
    expect(backend.resolverCalls).toEqual([]);
    expect(result.conflictResolvedByLlm ?? false).toBe(false);
    expect(backend.ledger).toEqual([
      expect.objectContaining({ childIssue: 10, status: "merged" }),
    ]);
  });

  it("POSITIVE: real conflict dispatches merger worker exactly once (no still-conflicted host re-dispatch cap)", async () => {
    const backend = new ConflictOnceFamilyBackend(new Set([11]), /* stillConflicted */ true);
    const result = await mergeChild(backend, {
      childIssue: 11,
      childBranch: "feat/child-11",
    });
    // ID-010: no mechanical still-conflicted re-dispatch loop.
    expect(backend.resolverCalls).toHaveLength(1);
    expect(result.conflicted).toBe(true);
    expect(backend.ledger).toEqual([]);
  });

  it("POSITIVE: merger worker that lands after one resolve records merged (Action converges completed)", async () => {
    const backend = new ConflictOnceFamilyBackend(new Set([12]), /* stillConflicted */ false);
    const result = await mergeChild(backend, {
      childIssue: 12,
      childBranch: "feat/child-12",
    });
    expect(backend.resolverCalls).toHaveLength(1);
    expect(result).toMatchObject({
      familyHead: "resolved-12",
      conflictResolvedByLlm: true,
    });
    expect(backend.ledger).toEqual([
      expect.objectContaining({
        childIssue: 12,
        status: "merged",
        conflictResolvedByLlm: true,
      }),
    ]);
  });

  it("POSITIVE: structured merger raise is converged once — no host retry court", async () => {
    const familyBackend = new ConflictOnceFamilyBackend(
      new Set([10]),
      false,
      {
        reason: "choose the canonical migration",
        diagnosis: "both branches deliberately changed the same public contract",
        escalationKind: "decision",
        phase: "wave",
      },
    );
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    expect(familyBackend.resolverCalls).toHaveLength(1);
    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toBe("choose the canonical migration");
    // No host "still-conflicted retries" court language.
    expect(JSON.stringify(result)).not.toMatch(/still-conflicted retries/i);
  });

  it("POSITIVE: merger decision escalate attaches wave diagnostics for failed siblings", async () => {
    // #10 decision-escalates on merge; #11 fails single-slice. Wave diagnostics
    // for #11 are settled before the merge early-return and must ride the
    // public escalated result (attachDiagnostics on that terminal).
    const familyBackend = new ConflictOnceFamilyBackend(
      new Set([10]),
      false,
      {
        reason: "choose the canonical migration",
        diagnosis: "both branches deliberately changed the same public contract",
        escalationKind: "decision",
        phase: "wave",
      },
    );
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new SiblingFailBackend(new Set([11])),
      familyBase: "family/938-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toBe("choose the canonical migration");
    expect(result.diagnostics ?? []).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          issue: 11,
          kind: "child_execution",
        }),
      ]),
    );
  });

  it("POSITIVE: still-conflicted merger result fails the child without host mechanical-cap escalation", async () => {
    const familyBackend = new ConflictOnceFamilyBackend(new Set([10]), true);
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    // One resolve only — Action trusts the worker outcome.
    expect(familyBackend.resolverCalls).toHaveLength(1);
    // Not the deleted host "exhausted bounded still-conflicted retries" court.
    expect(familyBackend.escalationCalls).toEqual([]);
    expect(JSON.stringify(result)).not.toMatch(/still-conflicted retries/i);
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("failed");
    // Sibling that never reached merge (serial stop on conflicted base) is honest.
    expect(result.status).toBe("incomplete");
    expect(result.diagnostics ?? []).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          issue: 10,
          kind: "merger_worker",
        }),
      ]),
    );
  });

  it("POSITIVE: still-conflicted mid-wave exit keeps successful wave peer as ran (not skipped)", async () => {
    // Both siblings allSettled; serial merge stops on #10 conflicted base.
    // #11 already ran single-slice — must remain honest `ran`, not finalize-mapped
    // `skipped` (never-schedulable only).
    const familyBackend = new ConflictOnceFamilyBackend(new Set([10]), true);
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    expect(result.status).toBe("incomplete");
    expect(result.children.find((c) => c.issue === 10)).toEqual(
      expect.objectContaining({
        issue: 10,
        status: "failed",
        failureCause: expect.stringMatching(/merger_worker|conflict/i),
      }),
    );
    const peer = result.children.find((c) => c.issue === 11);
    expect(peer?.status).toBe("ran");
    expect(peer?.status).not.toBe("skipped");
    expect(peer?.branch).toEqual(expect.stringMatching(/11/));
  });

  it("POSITIVE: merger decision-escalate mid-wave exit keeps successful wave peer as ran (not skipped)", async () => {
    // #10 decision-escalates during merge; #11 already allSettled as ran in the
    // same wave. Early exit must drain #11 before mapping residual children.
    const familyBackend = new ConflictOnceFamilyBackend(
      new Set([10]),
      false,
      {
        reason: "choose the canonical migration",
        diagnosis: "both branches deliberately changed the same public contract",
        escalationKind: "decision",
        phase: "wave",
      },
    );
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.escalation?.reason).toBe("choose the canonical migration");
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("failed");
    const peer = result.children.find((c) => c.issue === 11);
    expect(peer?.status).toBe("ran");
    expect(peer?.status).not.toBe("skipped");
    expect(peer?.branch).toEqual(expect.stringMatching(/11/));
  });

  it("POSITIVE: merge-phase quota park mid-wave keeps successful wave peer as ran (not skipped)", async () => {
    // Both siblings allSettled; serial merge of #10 hits QuotaWait → park.
    // Park residual-maps children — must drain #11 (and #10) first so peers
    // stay honest `ran`, not fake finalize/park-mapped `skipped`.
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    class QuotaParkOnMergeBackend extends RecordingFamilyBackend {
      override async mergeChildIntoFamilyBase(
        child: MergeRequest,
      ): Promise<MergeResult> {
        this.mergeOrder.push(child.childIssue);
        if (child.childIssue === 10) {
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "zai",
              resetAt,
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "zai",
                resetAt: resetAt.toISOString(),
                reason: "quota limited (429); wait for reset",
                step: "S1",
                workerPid: 0,
                ts: "2026-07-14T12:00:00.000Z",
              },
            },
            pool: "zai",
          });
        }
        return { familyHead: `h${child.childIssue}` };
      }
    }
    const familyBackend = new QuotaParkOnMergeBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new OkChildBackend(),
      familyBase: "family/938-base",
      now: () => now,
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    // The merge-target child and the same-wave peer both already ran single-slice.
    for (const issue of [10, 11] as const) {
      const child = result.children.find((c) => c.issue === issue);
      expect(child?.status).toBe("ran");
      expect(child?.status).not.toBe("skipped");
      expect(child?.branch).toEqual(expect.stringMatching(new RegExp(String(issue))));
    }
  });

  it("POSITIVE: merge-phase quota park attaches wave diagnostics for failed siblings", async () => {
    // #11 fails single-slice (wave diagnostic); #10 hits QuotaWait on merge.
    // Park path must attachDiagnostics so failed-sibling causes are not dropped.
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    class QuotaParkOnMergeBackend extends RecordingFamilyBackend {
      override async mergeChildIntoFamilyBase(
        child: MergeRequest,
      ): Promise<MergeResult> {
        this.mergeOrder.push(child.childIssue);
        if (child.childIssue === 10) {
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "zai",
              resetAt,
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "zai",
                resetAt: resetAt.toISOString(),
                reason: "quota limited (429); wait for reset",
                step: "S1",
                workerPid: 0,
                ts: "2026-07-14T12:00:00.000Z",
              },
            },
            pool: "zai",
          });
        }
        return { familyHead: `h${child.childIssue}` };
      }
    }
    const familyBackend = new QuotaParkOnMergeBackend();
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 938,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new SiblingFailBackend(new Set([11])),
      familyBase: "family/938-base",
      now: () => now,
    });

    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.children.find((c) => c.issue === 10)?.status).toBe("ran");
    expect(result.children.find((c) => c.issue === 11)?.status).toBe("failed");
    expect(result.diagnostics ?? []).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          issue: 11,
          kind: "child_execution",
        }),
      ]),
    );
  });

  it("NEGATIVE: production merger has no host still-conflicted re-dispatch loop (ID-016 delete)", () => {
    const mergerSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/merger.ts"),
      "utf8",
    );
    const runnerSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/runner.ts"),
      "utf8",
    );
    // Deleted: mechanical still-conflicted cap loop in the Action.
    expect(mergerSrc).not.toMatch(/MAX_DISPATCH_ATTEMPTS/);
    expect(mergerSrc).not.toMatch(/for\s*\(\s*let\s+attempt/);
    // Deleted: missing-resolver fake business exit.
    expect(mergerSrc).not.toMatch(/no resolveMergeConflict resolver/);
    // #934 ID-010 / #938: required seam — no optional `?` + non-null `!` call.
    expect(mergerSrc).toMatch(/backend\.resolveMergeConflict\s*\(/);
    expect(mergerSrc).not.toMatch(/backend\.resolveMergeConflict!\s*\(/);
    const typesSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/types.ts"),
      "utf8",
    );
    expect(typesSrc).toMatch(
      /resolveMergeConflict\s*\(\s*req:\s*ConflictResolveRequest\s*\)\s*:\s*Promise\s*<\s*MergeResult\s*>/,
    );
    expect(typesSrc).not.toMatch(/resolveMergeConflict\?\s*\(/);
    // Deleted: startup whole-family cycle guard + rethrow-first + still-conflicted host court.
    expect(runnerSrc).not.toMatch(/assertAcyclic\(epic\.children\)/);
    expect(runnerSrc).not.toMatch(/firstRejected/);
    expect(runnerSrc).not.toMatch(/still-conflicted retries/);
  });
});
