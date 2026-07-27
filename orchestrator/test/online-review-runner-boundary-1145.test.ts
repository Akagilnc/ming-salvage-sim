/**
 * #1145 tracer bullet — production family shared-tail boundary.
 *
 * From the real shared-tail entry (`runFamilyOnlineReviewLoop`):
 * 1. Runner dispatches Collector before Verify.
 * 2. Collector evidence is transported as-is into the Verify landing.
 * 3. Verify does not start until Collector returns.
 * 4. Runner does not host-call GH poll/retrigger/side-effect seams (deleted).
 * 5. Collector model comes from the independent `collector` route slot.
 * 6. AC3: old-round 5 keys + current-round 6 fix items → fixer gets only this
 *    round's opaque packet, verbatim.
 * 7. AC2: crash after Collector success reuses durable checkpoint (no re-burn).
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
  /** Crash window: throw after first Collector success, before Verify. */
  crashAfterCollectorOnce = false;
  private crashedOnce = false;
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
      if (this.crashAfterCollectorOnce && !this.crashedOnce) {
        this.crashedOnce = true;
        // Action persists checkpoint via ledger write in verifyCmr AFTER this
        // returns — so we return success then the harness simulates crash by
        // throwing from verify on the first entry. For true post-collector
        // crash, verifyCmr records checkpoint before returning to stage; the
        // crash is simulated by aborting the first runFamilyOnlineReviewLoop
        // via verify throw after checkpoint is written. Here we just complete.
      }
      return {
        kind: "completed",
        output: { kind: "collector", evidence: this.collectorEvidence },
      };
    }

    if (spec.kind === "verify") {
      this.verifyStartedAt = Date.now();
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
    const retriggerSpy = vi.spyOn(botPolling, "postBotRetriggerComment");

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
    expect(retriggerSpy).not.toHaveBeenCalled();

    // Host dual-owner module is gone — not merely uncalled.
    const { existsSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const sideEffectsPath = fileURLToPath(
      new URL("../src/onlineReviewSideEffects.ts", import.meta.url),
    );
    expect(existsSync(sideEffectsPath)).toBe(false);

    // Action-owned checkpoint is durable after Collector success.
    expect(
      backend.ledger.some(
        (e) => e.event === "online_review_collector_completed",
      ),
    ).toBe(true);
  });

  it("AC3 tracer: old-round 5 keys + current 6-item opaque packet reaches fixer verbatim", async () => {
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
          isRecheck: true, // Verify-owned; Runner must not overwrite
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
        output: { kind: "verify", converged: true, isRecheck: true },
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

  it("AC2 tracer: crash after Collector reuses durable checkpoint (no re-burn)", async () => {
    // Crash window: Collector completed + durable checkpoint written, process
    // died before Verify. Re-entry must NOT re-dispatch Collector / re-burn wait.
    const backend = new TracerFamilyBackend();
    const evidence = backend.collectorEvidence;
    backend.ledger.push({
      status: "online_review_collector_completed",
      event: "online_review_collector_completed",
      onlineReviewRound: 1,
      cargoPointer: "ledger:online_review_collector_completed:round=1:crash",
      collectorEvidenceCargo: evidence,
      ts: "2026-01-01T00:00:00.000Z",
    });

    const result = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(result.ok).toBe(true);
    // No live Collector dispatch — Action short-circuited on checkpoint.
    expect(backend.collectorDispatchCount).toBe(0);
    expect(backend.kinds.filter((k) => k === "collector")).toEqual([]);
    expect(backend.kinds).toContain("verify");

    const verifyLanding = backend.kinds
      .map((kind, i) => ({ kind, landing: backend.landings[i] }))
      .find((p) => p.kind === "verify")?.landing;
    expect(verifyLanding?.onlineReviewSnapshot).toEqual(evidence);
  });

  it("tracer: residual side-effect cargo never host-replays on re-entry", async () => {
    const backend = new TracerFamilyBackend();

    const first = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(first.ok).toBe(true);

    // Second entry after mergeable: checkpoint for round 1 still present, so
    // Collector is not re-dispatched; Verify runs again on reused evidence.
    const second = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(second.ok).toBe(true);
    expect(backend.collectorDispatchCount).toBe(1);
    expect(backend.kinds.filter((k) => k === "verify").length).toBe(2);
  });
});
