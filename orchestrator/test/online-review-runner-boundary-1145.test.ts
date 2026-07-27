/**
 * #1145 tracer bullet — production family shared-tail boundary.
 *
 * From the real shared-tail entry (`runFamilyOnlineReviewLoop`):
 * 1. Runner dispatches Collector before Verify.
 * 2. Collector evidence is transported as-is into the Verify landing.
 * 3. Verify does not start until Collector returns.
 * 4. Runner does not host-call GH poll seams; host dual-owner module is gone.
 * 5. Collector model comes from the independent `collector` route slot.
 * 6. AC3: old-round 5 keys + current-round 6 fix items → fixer gets only this
 *    round's opaque packet, verbatim (including isRecheck:false passthrough).
 * 7. Three shortest repros on the crash/no-op/re-entry seam:
 *    - Collector writes checkpoint → fail before Verify → re-entry
 *    - fixer legal no-op returns to same judge (no new Collector, no round++)
 *    - mergeable re-entry does not re-dispatch Verify (side effects once)
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import * as botPolling from "../src/botPolling.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import {
  skeletonReviewLoopWorkerResult,
  stubCollectorEvidence,
} from "../src/reviewLoopOutcome.js";
import { resolveRouteModels } from "../src/modelRoutes.js";
import { collectorWorkerSpec, verifyWorkerSpec } from "../src/dispatchWorker.js";
import { familyWorkerSlotForDispatch } from "../src/family/familyWorkerSlots.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

const offlineShip = {
  kind: "ship" as const,
  branch: "family/1145",
  pr: "pr://family/1145",
  prHead: "head-1145",
  status: "pr_opened" as const,
};

const PRIOR_ROUND_5_KEYS = [
  "old-key-1",
  "old-key-2",
  "old-key-3",
  "old-key-4",
  "old-key-5",
] as const;

const CURRENT_ROUND_6_KEYS = [
  "cur-key-1",
  "cur-key-2",
  "cur-key-3",
  "cur-key-4",
  "cur-key-5",
  "cur-key-6",
] as const;

const CURRENT_ROUND_6_THREADS = CURRENT_ROUND_6_KEYS.map((identityKey, i) => ({
  identityKey,
  threadId: `thread-cur-${i + 1}`,
}));

class TracerFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly landings: WorkerLandingPayload[] = [];
  readonly kinds: string[] = [];
  readonly models: string[] = [];
  /** Timestamps: collector return before first verify start. */
  collectorReturnedAt: number | undefined;
  verifyStartedAt: number | undefined;
  collectorDispatchCount = 0;
  verifyDispatchCount = 0;
  /**
   * Crash window: Collector may complete + write checkpoint, but every Verify
   * dispatch fails for this run (mechanical retry must not "self-heal" mid-run).
   * Clear between runs to allow re-entry success.
   */
  blockVerify = false;
  collectorEvidence = stubCollectorEvidence({
    prUrl: offlineShip.pr,
    headOid: offlineShip.prHead,
    totalFindingCount: 6,
    // Distinct marker so passthrough asserts the exact blob.
    droppedBots: ["marker-bot-1145"],
  });
  verifyImpl?: (
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ) => Promise<WorkerResult>;
  fixerImpl?: (
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ) => Promise<WorkerResult>;

  constructor(opts?: { readonly seedPriorRound5Keys?: boolean }) {
    if (opts?.seedPriorRound5Keys) {
      this.ledger.push({
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        familyHeadAfter: "prior-fix-sha",
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: [...PRIOR_ROUND_5_KEYS],
        fixMarkedFindingThreads: PRIOR_ROUND_5_KEYS.map((identityKey, i) => ({
          identityKey,
          threadId: `thread-old-${i + 1}`,
        })),
        ts: "2026-01-01T00:00:00.000Z",
      });
    }
  }

  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "fb-head-1145" };
  }
  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in #1145 tracer");
  }
  async runFamilyVerify(): Promise<{ ok: boolean }> {
    return { ok: true };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<FamilyLedgerEntry[]> {
    return [...this.ledger];
  }
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.kinds.push(spec.kind);
    this.models.push(spec.model);
    if (landing !== undefined) this.landings.push(landing);

    if (spec.kind === "collector") {
      this.collectorDispatchCount += 1;
      // Simulate async seat so ordering vs verify is observable.
      await Promise.resolve();
      this.collectorReturnedAt = Date.now();
      return {
        kind: "completed",
        output: { kind: "collector", evidence: this.collectorEvidence },
      };
    }

    if (spec.kind === "verify") {
      this.verifyDispatchCount += 1;
      this.verifyStartedAt = Date.now();
      if (this.blockVerify) {
        // EISDIR-class fails closed without burning the full mechanical-retry
        // budget — models a hard crash after Collector checkpoint, not a
        // six-hit empty spin that would block re-entry Verify.
        return {
          kind: "failed",
          reason:
            "simulated crash after collector checkpoint: EISDIR: illegal operation on a directory",
        };
      }
      if (this.verifyImpl) return this.verifyImpl(spec, ctx, landing);
      return {
        kind: "completed",
        output: {
          kind: "verify",
          converged: true,
          // Residual plan cargo — must NOT trigger host replay (#1145).
          threadReplies: [{ threadId: "discussion_r1", body: "acked" }],
          threadsToResolve: ["discussion_r1"],
        },
      };
    }

    if (spec.kind === "fixer") {
      if (this.fixerImpl) return this.fixerImpl(spec, ctx, landing);
      return {
        kind: "completed",
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fixer-sha-1145",
        },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected ${spec.kind}` };
  }
}

describe("#1145 production shared-tail Online Review boundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("collector route slot is independent of verify", () => {
    const route = resolveRouteModels("normal", {});
    expect(route.slots.collector).toBe("grok-4.5");
    expect(route.slots.verify).toBe("gpt-5.6-sol");
    expect(route.slots.collector).not.toBe(route.slots.verify);

    expect(familyWorkerSlotForDispatch("collector")).toBe("collector");
    expect(familyWorkerSlotForDispatch("verify")).toBe("verify");

    expect(collectorWorkerSpec(route).model).toBe(route.slots.collector);
    expect(verifyWorkerSpec(route).model).toBe(route.slots.verify);
    expect(collectorWorkerSpec(route).model).not.toBe(
      verifyWorkerSpec(route).model,
    );
  });

  it("tracer: collector then verify; evidence passthrough; verify after collector; no host GH", async () => {
    const pollSpy = vi.spyOn(botPolling, "pollPrReviewState");

    const backend = new TracerFamilyBackend();
    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });

    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 1,
    });

    // Collector before Verify; no other GH seats.
    expect(backend.kinds[0]).toBe("collector");
    expect(backend.kinds).toContain("verify");
    const collectorIdx = backend.kinds.indexOf("collector");
    const verifyIdx = backend.kinds.indexOf("verify");
    expect(collectorIdx).toBeGreaterThanOrEqual(0);
    expect(verifyIdx).toBeGreaterThan(collectorIdx);

    // Verify must not start before collector returns.
    expect(backend.collectorReturnedAt).toBeTypeOf("number");
    expect(backend.verifyStartedAt).toBeTypeOf("number");
    expect(backend.verifyStartedAt!).toBeGreaterThanOrEqual(
      backend.collectorReturnedAt!,
    );

    // Collector receipt evidence is transported as-is into Verify landing.
    const pairs = backend.kinds.map((kind, i) => ({
      kind,
      landing: backend.landings[i],
    }));
    const verifyPair = pairs.find((p) => p.kind === "verify");
    expect(verifyPair?.landing?.onlineReviewSnapshot).toEqual(
      backend.collectorEvidence,
    );

    // Host GH poll seams stay dark (deleted dual-owner path).
    expect(pollSpy).not.toHaveBeenCalled();
    // Host retrigger export is gone — not merely uncalled.
    expect(
      Object.prototype.hasOwnProperty.call(botPolling, "postBotRetriggerComment"),
    ).toBe(false);

    // Host dual-owner module is gone — not merely uncalled.
    const { existsSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const sideEffectsPath = fileURLToPath(
      new URL("../src/onlineReviewSideEffects.ts", import.meta.url),
    );
    expect(existsSync(sideEffectsPath)).toBe(false);

    // Action-owned checkpoints are durable after Collector + mergeable.
    expect(
      backend.ledger.some(
        (e) => e.event === "online_review_collector_completed",
      ),
    ).toBe(true);
    expect(
      backend.ledger.some((e) => e.event === "online_review_mergeable"),
    ).toBe(true);
    // No parallel retrigger truth next to collector checkpoint.
    expect(
      backend.ledger.some((e) => e.event === "online_review_round_retrigger"),
    ).toBe(false);
  });

  it("AC3 tracer: old-round 5 keys + current 6-item opaque packet reaches fixer verbatim; isRecheck:false passthrough", async () => {
    const backend = new TracerFamilyBackend({ seedPriorRound5Keys: true });
    let fixerLanding: WorkerLandingPayload | undefined;

    backend.verifyImpl = async (_spec, _ctx, landing) => {
      // Prove prior-round history may be present on landing without becoming
      // the fixer packet source.
      expect(landing?.priorRoundFindings?.some((s) => s.round === 1)).toBe(
        true,
      );
      const priorKeys =
        landing?.priorRoundFindings?.find((s) => s.round === 1)
          ?.fixMarkedFindingIdentityKeys ?? [];
      expect(priorKeys).toEqual([...PRIOR_ROUND_5_KEYS]);

      return {
        kind: "completed",
        output: {
          kind: "verify",
          converged: false,
          isRecheck: false, // Verify-owned; Runner must transport as-is
          // Opaque fixer packet — 6 current items, distinct from prior 5.
          fixMarkedFindingIdentityKeys: [...CURRENT_ROUND_6_KEYS],
          fixMarkedFindingThreads: CURRENT_ROUND_6_THREADS,
          findingDispositions: [
            // Disposition noise that must NOT become the fixer packet.
            ...PRIOR_ROUND_5_KEYS.map((identityKey, i) => ({
              identityKey,
              threadId: `noise-old-${i}`,
              action: "fix" as const,
            })),
            ...CURRENT_ROUND_6_KEYS.map((identityKey, i) => ({
              identityKey,
              threadId: CURRENT_ROUND_6_THREADS[i]!.threadId,
              action: "fix" as const,
            })),
          ],
        },
      };
    };

    backend.fixerImpl = async (_spec, _ctx, landing) => {
      fixerLanding = landing;
      return {
        kind: "completed",
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fix-from-6-packet",
        },
      };
    };

    // After fixer, converge on recheck so the loop ends.
    let verifyCalls = 0;
    const firstVerify = backend.verifyImpl;
    backend.verifyImpl = async (spec, ctx, landing) => {
      verifyCalls += 1;
      if (verifyCalls === 1) return firstVerify!(spec, ctx, landing);
      return {
        kind: "completed",
        output: { kind: "verify", converged: true, isRecheck: false },
      };
    };

    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(result.ok).toBe(true);

    // Fixer received ONLY this-round opaque packet — verbatim, not derived.
    expect(fixerLanding).toBeDefined();
    expect(fixerLanding!.fixMarkedFindingIdentityKeys).toEqual([
      ...CURRENT_ROUND_6_KEYS,
    ]);
    expect(fixerLanding!.fixMarkedFindingThreads).toEqual(
      CURRENT_ROUND_6_THREADS,
    );
    // Must not be the prior-round 5 keys or a disposition-filtered merge.
    expect(fixerLanding!.fixMarkedFindingIdentityKeys).not.toEqual([
      ...PRIOR_ROUND_5_KEYS,
    ]);
    expect(fixerLanding!.fixMarkedFindingIdentityKeys).toHaveLength(6);
  });

  it("sparse Verify cargo must not backfill prior-round recheck keys into Fixer packet", async () => {
    const backend = new TracerFamilyBackend({ seedPriorRound5Keys: true });
    let fixerLanding: WorkerLandingPayload | undefined;
    let verifyCalls = 0;

    backend.verifyImpl = async (_spec, _ctx, landing) => {
      verifyCalls += 1;
      if (verifyCalls === 1) {
        // Round-2 resume seeds prior fix keys onto Verify landing for recheck
        // context — they must NOT leak into Fixer when this-round packet is sparse.
        expect(landing?.fixMarkedFindingIdentityKeys).toEqual([
          ...PRIOR_ROUND_5_KEYS,
        ]);
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: false,
            isRecheck: false,
            // Sparse: no fixMarkedFindingIdentityKeys / threads this round.
          },
        };
      }
      return {
        kind: "completed",
        output: { kind: "verify", converged: true, isRecheck: false },
      };
    };

    backend.fixerImpl = async (_spec, _ctx, landing) => {
      fixerLanding = landing;
      // Legal no-op so we return to same judge without a new commit round.
      return { kind: "completed", output: { kind: "fixer", committed: false } };
    };

    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(result.ok).toBe(true);
    expect(fixerLanding).toBeDefined();
    // Missing this-round packet → empty transport, NOT prior 5 keys.
    expect(fixerLanding!.fixMarkedFindingIdentityKeys).toEqual([]);
    expect(fixerLanding!.fixMarkedFindingThreads ?? []).toEqual([]);
  });

  describe("three shortest repros — crash / no-op / re-entry", () => {
    it("crash: Collector writes checkpoint → Verify fails → re-entry skips Collector", async () => {
      const backend = new TracerFamilyBackend();
      // Real path: Collector runs + checkpoint, Verify process-fails the run.
      backend.blockVerify = true;

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.terminalState).toBe("decision_gate_raised");
      expect(first.stopSummary?.summary).toMatch(
        /simulated crash after collector checkpoint/,
      );

      expect(backend.collectorDispatchCount).toBe(1);
      expect(
        backend.ledger.some(
          (e) => e.event === "online_review_collector_completed",
        ),
      ).toBe(true);
      // Crash before Verify success → no mergeable proof yet.
      expect(
        backend.ledger.some((e) => e.event === "online_review_mergeable"),
      ).toBe(false);
      const evidence = backend.collectorEvidence;
      // Hard-fail path: one Verify attempt, not a six-hit retry spin.
      expect(backend.verifyDispatchCount).toBe(1);

      // Re-entry: clear crash window; must NOT re-dispatch Collector / re-burn wait.
      backend.blockVerify = false;
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(result.ok).toBe(true);
      expect(backend.collectorDispatchCount).toBe(1);
      expect(backend.kinds.filter((k) => k === "collector")).toHaveLength(1);
      // First-run fail + one successful Verify on re-entry.
      expect(backend.verifyDispatchCount).toBe(2);

      const verifyLanding = backend.kinds
        .map((kind, i) => ({ kind, landing: backend.landings[i] }))
        .filter((p) => p.kind === "verify")
        .at(-1)?.landing;
      expect(verifyLanding?.onlineReviewSnapshot).toEqual(evidence);
    });

    it("no-op: legal fixer no-op returns to same judge without new Collector / round++", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;
      const fixerRounds: number[] = [];
      const verifyRounds: number[] = [];

      backend.verifyImpl = async (_spec, _ctx, landing) => {
        verifyCalls += 1;
        verifyRounds.push(landing?.onlineReviewRound ?? -1);
        if (verifyCalls === 1) {
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              isRecheck: false,
              fixMarkedFindingIdentityKeys: ["live:1"],
              fixMarkedFindingThreads: [
                { identityKey: "live:1", threadId: "t1" },
              ],
            },
          };
        }
        return {
          kind: "completed",
          output: { kind: "verify", converged: true, isRecheck: false },
        };
      };

      backend.fixerImpl = async (_spec, _ctx, landing) => {
        fixerCalls += 1;
        fixerRounds.push(landing?.onlineReviewRound ?? -1);
        return {
          kind: "completed",
          output: { kind: "fixer", committed: false },
        };
      };

      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });

      expect(result).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 1,
      });
      expect(verifyCalls).toBe(2);
      expect(fixerCalls).toBe(1);
      // Same round both times — no unconditional round++ after no-op.
      expect(verifyRounds).toEqual([1, 1]);
      expect(fixerRounds).toEqual([1]);
      // Collector only once — no-op does not open a new Collector seat.
      expect(backend.collectorDispatchCount).toBe(1);
      expect(backend.kinds.filter((k) => k === "collector")).toHaveLength(1);
    });

    it("re-entry: mergeable side effects dispatch only once", async () => {
      const backend = new TracerFamilyBackend();

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(true);
      expect(first.terminalState).toBe("mergeable");
      expect(backend.verifyDispatchCount).toBe(1);
      expect(
        backend.ledger.filter((e) => e.event === "online_review_mergeable"),
      ).toHaveLength(1);

      // Second entry after mergeable: Action-owned completion recovery — no
      // re-dispatch of Verify (side effects already proven done).
      const second = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(second).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 1,
      });
      expect(backend.collectorDispatchCount).toBe(1);
      expect(backend.verifyDispatchCount).toBe(1);
      expect(backend.kinds.filter((k) => k === "verify")).toHaveLength(1);
    });
  });
});
