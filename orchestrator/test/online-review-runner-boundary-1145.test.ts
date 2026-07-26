/**
 * #1145 tracer bullet — production family shared-tail boundary.
 *
 * From the real shared-tail entry (`runFamilyOnlineReviewLoop`):
 * 1. Runner dispatches Collector before Verify.
 * 2. Collector evidence is transported as-is into the Verify landing.
 * 3. Verify does not start until Collector returns.
 * 4. Runner does not host-call waitForBotQuiescence / retriggerBotsAndPoll /
 *    applyVerifySideEffects, and does not directly query/interpret GitHub.
 * 5. Collector model comes from the independent `collector` route slot.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import * as botPolling from "../src/botPolling.js";
import * as onlineReviewLoop from "../src/family/onlineReviewLoop.js";
import * as sideEffects from "../src/onlineReviewSideEffects.js";
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

class TracerFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly landings: WorkerLandingPayload[] = [];
  readonly kinds: string[] = [];
  readonly models: string[] = [];
  /** Timestamps: collector return before first verify start. */
  collectorReturnedAt: number | undefined;
  verifyStartedAt: number | undefined;
  collectorEvidence = stubCollectorEvidence({
    prUrl: offlineShip.pr,
    headOid: offlineShip.prHead,
  });
  verifyImpl?: (
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ) => Promise<WorkerResult>;

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
      // Simulate async seat so ordering vs verify is observable.
      await Promise.resolve();
      this.collectorReturnedAt = Date.now();
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

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected ${spec.kind}` };
  }
}

describe("#1145 production shared-tail Online Review boundary", () => {
  const prevOffline = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;

  afterEach(() => {
    vi.restoreAllMocks();
    if (prevOffline === undefined) {
      delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    } else {
      process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prevOffline;
    }
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
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const applySpy = vi.spyOn(sideEffects, "applyVerifySideEffects");
    const waitSpy = vi.spyOn(onlineReviewLoop, "waitForBotQuiescence");
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

    // Residual plan cargo must not host-execute; host GH poll seams stay dark.
    expect(applySpy).not.toHaveBeenCalled();
    expect(waitSpy).not.toHaveBeenCalled();
    expect(pollSpy).not.toHaveBeenCalled();
    expect(retriggerSpy).not.toHaveBeenCalled();
  });

  it("tracer: completed seat with side-effect cargo stays mergeable on re-entry (no replay)", async () => {
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const applySpy = vi.spyOn(sideEffects, "applyVerifySideEffects");
    const backend = new TracerFamilyBackend();

    const first = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(first.ok).toBe(true);
    expect(applySpy).not.toHaveBeenCalled();

    const second = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(second.ok).toBe(true);
    expect(applySpy).not.toHaveBeenCalled();
    // Each entry still goes Collector → Verify.
    expect(backend.kinds.filter((k) => k === "collector").length).toBeGreaterThanOrEqual(2);
    expect(backend.kinds.filter((k) => k === "verify").length).toBeGreaterThanOrEqual(2);
  });
});
