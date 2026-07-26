/**
 * #1145 tracer bullet — production family shared-tail boundary.
 *
 * From the real shared-tail entry (`runFamilyOnlineReviewLoop`):
 * 1. Runner stage has no poll / applySideEffects second-owner seams.
 * 2. Production wiring never calls applyVerifySideEffects after the Action returns.
 * 3. Online Review seat owns evidence assembly; residual plan cargo is not
 *    host-replayed on re-entry after a completed seat.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as sideEffects from "../src/onlineReviewSideEffects.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
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
    if (spec.kind === "verify") {
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

  it("static: stage + production entry drop Runner poll/applySideEffects seams", () => {
    const loopSrc = readFileSync(
      join(SRC, "family/onlineReviewLoop.ts"),
      "utf8",
    );
    const verifyCmrSrc = readFileSync(join(SRC, "family/verifyCmr.ts"), "utf8");
    const runnerSrc = readFileSync(join(SRC, "family/runner.ts"), "utf8");

    // Stage interface: no second-owner seams.
    expect(loopSrc).not.toMatch(/readonly poll\s*:/);
    expect(loopSrc).not.toMatch(/readonly applySideEffects\s*:/);
    expect(loopSrc).not.toMatch(/dispatch\.poll\b/);
    expect(loopSrc).not.toMatch(/dispatch\.applySideEffects\b/);
    expect(loopSrc).not.toMatch(/applyVerifySideEffects/);

    // Production Online Review Action entry: never host-replays side effects.
    expect(verifyCmrSrc).not.toMatch(/applyVerifySideEffects/);
    expect(verifyCmrSrc).not.toMatch(/applySideEffects\s*:/);

    // Family runner only dispatches the Action — no direct botPolling import.
    expect(runnerSrc).not.toMatch(/from ["'].*botPolling/);
    expect(runnerSrc).not.toMatch(/waitForBotQuiescence/);
    expect(runnerSrc).not.toMatch(/applyVerifySideEffects/);
    // Shared-tail entry is the Action, not inline GH work.
    expect(runnerSrc).toMatch(/runFamilyOnlineReviewLoop/);
  });

  it("tracer: runFamilyOnlineReviewLoop never host-replays side effects after seat cargo", async () => {
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
    expect(backend.kinds).toContain("verify");
    // Worker returned residual plan cargo; Runner must not execute it.
    expect(applySpy).not.toHaveBeenCalled();
    // Seat received evidence landing (Action-assembled), not an empty pre-poll.
    const verifyLanding = backend.landings.find(
      (l) => l.onlineReviewSnapshot !== undefined,
    );
    expect(verifyLanding?.onlineReviewSnapshot).toEqual(
      expect.objectContaining({
        quiescent: true,
        prUrl: offlineShip.pr,
      }),
    );
  });

  it("tracer: completed seat with side-effect cargo stays mergeable on re-entry (no replay)", async () => {
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const applySpy = vi.spyOn(sideEffects, "applyVerifySideEffects");
    const backend = new TracerFamilyBackend();

    // First pass — worker completes with residual plan (already "done" in prod).
    const first = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(first.ok).toBe(true);
    expect(applySpy).not.toHaveBeenCalled();

    // Re-entry (process resume) — still must not host-apply residual plans.
    const second = await runFamilyOnlineReviewLoop({
      familyBackend: backend,
      familyBase: "family/1145",
      ship: offlineShip,
    });
    expect(second.ok).toBe(true);
    expect(applySpy).not.toHaveBeenCalled();
  });
});
