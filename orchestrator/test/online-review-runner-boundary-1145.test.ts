/**
 * #1145 tracer bullet — production family shared-tail boundary.
 *
 * From the real shared-tail entry (`runFamilyOnlineReviewLoop`):
 * 1. Runner dispatches Collector before Verify.
 * 2. Collector evidence is transported as-is into the Verify landing.
 * 3. Verify does not start until Collector returns.
 * 4. Runner does not host-call waitForBotQuiescence / retriggerBotsAndPoll /
 *    applyVerifySideEffects, and does not directly query/interpret GitHub.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as sideEffects from "../src/onlineReviewSideEffects.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import {
  skeletonReviewLoopWorkerResult,
  stubCollectorEvidence,
} from "../src/reviewLoopOutcome.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "../src");

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

  it("static: production path drops host poll/retrigger/applySideEffects seams", () => {
    const loopSrc = readFileSync(
      join(SRC, "family/onlineReviewLoop.ts"),
      "utf8",
    );
    const verifyCmrSrc = readFileSync(join(SRC, "family/verifyCmr.ts"), "utf8");
    const runnerSrc = readFileSync(join(SRC, "family/runner.ts"), "utf8");

    // Stage: independent Collector + Verify; no host retrigger seam.
    expect(loopSrc).toMatch(/readonly dispatchCollector\s*:/);
    expect(loopSrc).toMatch(/readonly dispatchVerify\s*:/);
    expect(loopSrc).not.toMatch(/readonly retriggerAfterFix\s*:/);
    expect(loopSrc).not.toMatch(/readonly poll\s*:/);
    expect(loopSrc).not.toMatch(/readonly applySideEffects\s*:/);
    expect(loopSrc).not.toMatch(/dispatch\.poll\b/);
    expect(loopSrc).not.toMatch(/dispatch\.applySideEffects\b/);
    expect(loopSrc).not.toMatch(/applyVerifySideEffects/);

    // Production shared-tail: no host bot wait / retrigger / side-effect replay.
    expect(verifyCmrSrc).not.toMatch(/waitForBotQuiescence/);
    expect(verifyCmrSrc).not.toMatch(/retriggerBotsAndPoll/);
    expect(verifyCmrSrc).not.toMatch(/applyVerifySideEffects/);
    expect(verifyCmrSrc).not.toMatch(/applySideEffects\s*:/);
    expect(verifyCmrSrc).toMatch(/collectorWorkerSpec/);
    expect(verifyCmrSrc).toMatch(/dispatchCollector/);

    // Family runner only dispatches the Action — no direct botPolling import.
    expect(runnerSrc).not.toMatch(/from ["'].*botPolling/);
    expect(runnerSrc).not.toMatch(/waitForBotQuiescence/);
    expect(runnerSrc).not.toMatch(/applyVerifySideEffects/);
    expect(runnerSrc).toMatch(/runFamilyOnlineReviewLoop/);
  });

  it("tracer: collector then verify; evidence passthrough; verify after collector", async () => {
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const applySpy = vi.spyOn(sideEffects, "applyVerifySideEffects");

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

    // Residual plan cargo must not host-execute.
    expect(applySpy).not.toHaveBeenCalled();
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
