/**
 * #1002 — online review loop: judge continue + advanceCoder rewrites fixer seat.
 *
 * Seams:
 * 1. runFamilyOnlineReviewLoop + fake FamilyBackend (real entry, no SUT mocks)
 * 2. verify cargo advanceCoder=sol@med → next fixer WorkerSpec.model = gpt-5.6-sol
 * 3. unknown token → stay_put ledger, original fixer slug, never terminal
 * 4. sticky: later continue without advance still dispatches advanced fixer
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import { buildExplicitLandingLiveHooks } from "../src/family/landing.js";
import { resolveActiveModelRoute } from "../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import type {
  DispatchContext,
  ShipResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";

const OFFLINE_SHIP: ShipResult = {
  kind: "ship",
  branch: "family/1002",
  pr: "https://github.com/test/repo/pull/1002",
  prHead: "head-1002",
  status: "pr_opened",
};

class OnlineReviewAdvanceBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly fixerModels: string[] = [];
  readonly specs: WorkerSpec[] = [];
  private verifyRound = 0;
  private readonly scripts: ReadonlyArray<{
    readonly converged: boolean;
    readonly advanceCoder?: string;
  }>;

  constructor(
    scripts: ReadonlyArray<{
      readonly converged: boolean;
      readonly advanceCoder?: string;
    }>,
  ) {
    this.scripts = scripts;
  }

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

  async runFamilyVerify(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "fb-head-1002" };
  }

  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in #1002 tests");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }

  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }

  async dispatchWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    if (spec.kind === "verify") {
      const script = this.scripts[this.verifyRound] ?? { converged: true };
      this.verifyRound += 1;
      if (script.converged) {
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
          sessionId: `verify-1002-${this.verifyRound}`,
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "verify",
          converged: false,
          findingDispositions: [
            {
              identityKey: "correctness|src/a.ts:1|needs-fix",
              threadId: "thread-1002",
              action: "fix",
            },
          ],
          ...(script.advanceCoder !== undefined
            ? { advanceCoder: script.advanceCoder }
            : {}),
        },
        sessionId: `verify-1002-${this.verifyRound}`,
      };
    }
    if (spec.kind === "fixer") {
      this.fixerModels.push(spec.model);
      return {
        kind: "completed",
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fixsha1002000000000000000000000000001",
        },
        sessionId: `fixer-1002-${this.fixerModels.length}`,
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected ${spec.kind}` };
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("#1002 online review advanceCoder → fixer seat", () => {
  it("continue + advanceCoder=sol@med dispatches fixer as gpt-5.6-sol and audits ledger", async () => {
    const defaultFixer = resolveActiveModelRoute({}).slots.fixer;
    expect(defaultFixer).not.toBe("gpt-5.6-sol");

    const backend = new OnlineReviewAdvanceBackend([
      { converged: false, advanceCoder: "sol@med" },
      { converged: true },
    ]);
    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1002",
      ship: OFFLINE_SHIP,
    });

    // #1145: fixer cargo returns to same-round Verify — converge without round++.
    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 1, binding: "bound" });
    expect(backend.fixerModels[0]).toBe("gpt-5.6-sol");
    expect(
      backend.ledger.some(
        (e) => e.status === "coder_advance" || e.event === "coder_advance",
      ),
    ).toBe(true);
    const advance = backend.ledger.find(
      (e) => e.status === "coder_advance" || e.event === "coder_advance",
    );
    expect(advance).toMatchObject({
      fromModelId: defaultFixer,
      toModelId: "gpt-5.6-sol",
      advanceSeat: "fixer",
    });
  });

  it("unknown advanceCoder stay_put keeps original fixer and never terminals", async () => {
    const defaultFixer = resolveActiveModelRoute({}).slots.fixer;

    const backend = new OnlineReviewAdvanceBackend([
      {
        converged: false,
        advanceCoder: "claude-opus-not-on-roster",
      },
      { converged: true },
    ]);
    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1002",
      ship: OFFLINE_SHIP,
    });

    // Negative: roster failure must not end the online-review loop.
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("mergeable");
    expect(result.ok).not.toBe(false);
    expect(backend.fixerModels[0]).toBe(defaultFixer);

    const stayPut = backend.ledger.filter(
      (e) =>
        e.status === "coder_advance_stay_put" ||
        e.event === "coder_advance_stay_put",
    );
    expect(stayPut.length).toBe(1);
    expect(stayPut[0]).toMatchObject({
      reason: "unknown_target",
    });
    expect(
      stayPut[0]!.message ?? stayPut[0]!.advanceCoder ?? "",
    ).toMatch(/claude-opus-not-on-roster/);
  });

  it("advanced fixer seat is sticky across a later continue without advanceCoder", async () => {
    const backend = new OnlineReviewAdvanceBackend([
      { converged: false, advanceCoder: "sol@med" },
      { converged: false },
      { converged: true },
    ]);
    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1002",
      ship: OFFLINE_SHIP,
    });

    // V1 continue+advance → F → V1b continue → round2 V converge.
    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 2, binding: "bound" });
    expect(backend.fixerModels.length).toBeGreaterThanOrEqual(1);
    expect(backend.fixerModels.every((m) => m === "gpt-5.6-sol")).toBe(true);
  });

  it("re-enter online-review rebuilds sticky fixer from latest ledger coder_advance", async () => {
    // Mirror single-slice sticky re-hold: process restart / re-entry must not
    // drop an already-audited advance (in-memory modelRoute alone is not enough).
    const defaultFixer = resolveActiveModelRoute({}).slots.fixer;
    expect(defaultFixer).not.toBe("gpt-5.6-sol");

    const backend = new OnlineReviewAdvanceBackend([
      // No advanceCoder in this invocation — stickiness must come from ledger.
      { converged: false },
      { converged: true },
    ]);
    await backend.appendFamilyLedger({
      status: "coder_advance",
      event: "coder_advance",
      reason: "coder_advance",
      fromModelId: defaultFixer,
      toModelId: "gpt-5.6-sol",
      advanceCoder: "sol@med",
      advanceSeat: "fixer",
      ts: "2026-07-18T00:00:00.000Z",
    });
    // stay_put after advance must not cancel re-hold (same as single-slice scan).
    await backend.appendFamilyLedger({
      status: "coder_advance_stay_put",
      event: "coder_advance_stay_put",
      reason: "unknown_target",
      fromModelId: "gpt-5.6-sol",
      toModelId: "gpt-5.6-sol",
      advanceCoder: "not-a-real-coder",
      advanceSeat: "fixer",
      ts: "2026-07-18T00:00:01.000Z",
    });

    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1002",
      ship: OFFLINE_SHIP,
    });

    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 1, binding: "bound" });
    expect(backend.fixerModels[0]).toBe("gpt-5.6-sol");
    expect(backend.fixerModels.every((m) => m === "gpt-5.6-sol")).toBe(true);
  });

  it("#1017 CMR coderFix advance does not sticky online-review fixer", async () => {
    // Shared family ledger: a CMR-scoped coder_advance must not re-hold the
    // online-review fixer seat (court/seat discriminator).
    const defaultFixer = resolveActiveModelRoute({}).slots.fixer;
    expect(defaultFixer).not.toBe("gpt-5.6-sol");

    const backend = new OnlineReviewAdvanceBackend([
      { converged: false },
      { converged: true },
    ]);
    // Latest advance is CMR coderFix — must be ignored by fixer re-hold.
    await backend.appendFamilyLedger({
      status: "coder_advance",
      event: "coder_advance",
      reason: "coder_advance",
      fromModelId: "gpt-5.4",
      toModelId: "gpt-5.6-sol",
      advanceCoder: "sol@med",
      advanceSeat: "coderFix",
      phase: "final",
      cmrPass: "correctness",
      ts: "2026-07-18T00:00:00.000Z",
    });
    // Legacy unscoped row (no advanceSeat) also must not sticky fixer.
    await backend.appendFamilyLedger({
      status: "coder_advance",
      event: "coder_advance",
      reason: "coder_advance",
      fromModelId: "gpt-5.4",
      toModelId: "gpt-5.6-sol",
      advanceCoder: "sol@med",
      ts: "2026-07-18T00:00:02.000Z",
    });

    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1002",
      ship: OFFLINE_SHIP,
    });

    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 1, binding: "bound" });
    expect(backend.fixerModels[0]).toBe(defaultFixer);
    expect(backend.fixerModels.every((m) => m === defaultFixer)).toBe(true);
  });
});
