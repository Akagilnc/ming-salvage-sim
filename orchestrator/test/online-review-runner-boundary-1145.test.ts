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
 *    - fixer result returns as opaque cargo to same judge (no new Collector)
 *    - mergeable re-entry does not re-dispatch Verify (side effects once)
 * 8. Sparse collector cargo → Verify receives it and typed-escalates (no infra throw)
 * 9. post-fix retrigger plan is a real Collector capability export
 * 10. Post-fixer crash seam (durable phase, not round arithmetic):
 *    - Fixer no-op completed → crash before same-round Verify → re-entry
 *    - Fixer commit completed → crash before same-round Verify → re-entry
 *    - Post-fixer Verify continue → crash before next Collector → no replay
 * 11. Handle-only cargoPointer (evidence-put style) survives shared-tail →
 *     Verify landing / collector_completed / re-entry without body or re-wait.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import * as botPolling from "../src/botPolling.js";
import {
  BOT_OVERDUE_MIN_WALL_MS,
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  collectorPostFixRetriggerPlan,
  ONLINE_REVIEW_BOT_RETRIGGER_COMMENT,
} from "../src/botPolling.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import {
  runOnlineReviewLoopStage,
} from "../src/family/onlineReviewLoop.js";
import {
  skeletonReviewLoopWorkerResult,
  stubCollectorEvidence,
} from "../src/reviewLoopOutcome.js";
import { resolveRouteModels } from "../src/modelRoutes.js";
import { collectorWorkerSpec, verifyWorkerSpec } from "../src/dispatchWorker.js";
import { familyWorkerSlotForDispatch } from "../src/family/familyWorkerSlots.js";
import { onlineReviewDispatch } from "./helpers/online-review-dispatch.js";
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
  ledger: FamilyLedgerEntry[] = [];
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
    // Distinct marker so passthrough asserts the exact blob.
    marker: "marker-bot-1145",
  });
  /** When set, Collector returns handle-only (no evidence body). */
  collectorCargoPointer: string | undefined;
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
  collectorImpl?: (
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ) => Promise<WorkerResult>;

  constructor(opts?: { readonly seedPriorRound5Keys?: boolean }) {
    if (opts?.seedPriorRound5Keys) {
      // Prior fix at round 1 = history for priorRoundFindings / recheck keys.
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
      // Live high-water is round 2 (max onlineReviewRound on Collector/fix/
      // mergeable markers — not fix-commit count). Without this marker, resume
      // would stay at 1 and prior keys would not be "prior".
      this.ledger.push({
        status: "online_review_collector_completed",
        event: "online_review_collector_completed",
        onlineReviewRound: 2,
        collectorEvidenceCargo: stubCollectorEvidence({
          prUrl: offlineShip.pr,
          headOid: offlineShip.prHead,
          marker: "marker-bot-1145",
        }),
        ts: "2026-01-01T00:01:00.000Z",
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
      if (this.collectorImpl !== undefined) {
        return this.collectorImpl(spec, ctx, landing);
      }
      if (
        this.collectorCargoPointer !== undefined &&
        this.collectorCargoPointer.length > 0
      ) {
        // Handle-only completion — no evidence body (#1145 DecisionGate A).
        return {
          kind: "completed",
          output: {
            kind: "collector",
            cargoPointer: this.collectorCargoPointer,
          },
        };
      }
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
    // T2: stage must NOT elevate evidence.headOid into shipDelivery.prHead —
    // bookkeeping head stays ship/fix SHA only (ADR 0131 zero-read cargo).
    expect(verifyPair?.landing?.shipDelivery?.prHead).toBe(offlineShip.prHead);
    expect(verifyPair?.landing?.shipDelivery?.prHead).not.toBe(
      "elevated-from-evidence-head",
    );
    // DecisionGate A: host must NOT write collection_progress to family ledger.
    expect(
      backend.ledger.some(
        (e) =>
          (e.event as string | undefined) ===
          "online_review_collection_progress",
      ),
    ).toBe(false);

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

    it("no-op: fixer result returns as opaque cargo to same judge (no new Collector / round++)", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;
      const fixerRounds: number[] = [];
      const verifyRounds: number[] = [];
      const verifyFixerCargo: Array<WorkerLandingPayload["fixerResult"]> = [];

      backend.verifyImpl = async (_spec, _ctx, landing) => {
        verifyCalls += 1;
        verifyRounds.push(landing?.onlineReviewRound ?? -1);
        verifyFixerCargo.push(landing?.fixerResult);
        if (verifyCalls === 1) {
          // First seat: no fixer cargo yet.
          expect(landing?.fixerResult).toBeUndefined();
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
        // Same-round re-entry MUST carry the fixer envelope as opaque cargo.
        expect(landing?.fixerResult).toEqual({
          kind: "fixer",
          committed: false,
        });
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
      expect(verifyFixerCargo).toEqual([
        undefined,
        { kind: "fixer", committed: false },
      ]);
      // Collector only once — return-to-judge skips Collector.
      expect(backend.collectorDispatchCount).toBe(1);
      expect(backend.kinds.filter((k) => k === "collector")).toHaveLength(1);
    });

    it("sparse collector cargo: Verify receives missing snapshot and typed-escalates (no infra throw)", async () => {
      const verifyLandings: Array<WorkerLandingPayload | undefined> = [];
      const result = await runOnlineReviewLoopStage(
        offlineShip,
        onlineReviewDispatch({
          dispatchCollector: async () => ({}),
          dispatchVerify: async (landing) => {
            verifyLandings.push(landing);
            // Professional seat owns inability-to-continue — typed escalate.
            return {
              verify: {
                kind: "verify",
                converged: false,
                terminalState: "decision_gate_raised",
              },
            };
          },
          dispatchFixer: async () => {
            throw new Error("fixer must not run after verify escalate");
          },
        }),
      );

      expect(result.ok).toBe(false);
      expect(result.terminalState).toBe("decision_gate_raised");
      expect(verifyLandings).toHaveLength(1);
      expect(verifyLandings[0]?.onlineReviewSnapshot).toBeUndefined();
      // Not an infra collector/verify dispatch failure summary.
      expect(result.stopSummary?.summary).not.toMatch(/dispatch failed/i);
    });

    it("envelope SHA updates lastFixCommitSha without resolveFixCommitSha callback", async () => {
      const collectorHeads: Array<string | undefined> = [];
      let verifyCalls = 0;

      const result = await runOnlineReviewLoopStage(
        offlineShip,
        onlineReviewDispatch({
          // Intentionally NO resolveFixCommitSha — envelope SHA must still land.
          dispatchCollector: async (landing) => {
            collectorHeads.push(landing.shipDelivery?.prHead);
            return {
              evidence: stubCollectorEvidence({
                prUrl: offlineShip.pr,
                headOid: landing.shipDelivery?.prHead ?? offlineShip.prHead!,
              }),
            };
          },
          dispatchVerify: async (landing) => {
            verifyCalls += 1;
            if (verifyCalls === 1) {
              return {
                verify: {
                  kind: "verify",
                  converged: false,
                  fixMarkedFindingIdentityKeys: ["k-env"],
                  fixMarkedFindingThreads: [
                    { identityKey: "k-env", threadId: "t-env" },
                  ],
                },
              };
            }
            if (verifyCalls === 2) {
              expect(landing.fixerResult?.fixCommitSha).toBe("envelope-only-sha");
              return {
                verify: {
                  kind: "verify",
                  converged: false,
                  isRecheck: true,
                },
              };
            }
            return { verify: { kind: "verify", converged: true, isRecheck: true } };
          },
          dispatchFixer: async () => ({
            kind: "fixer",
            committed: true,
            fixCommitSha: "envelope-only-sha",
          }),
        }),
      );

      expect(result.ok).toBe(true);
      expect(collectorHeads).toEqual([
        offlineShip.prHead,
        "envelope-only-sha",
      ]);
    });

    it("post-fix continue: next Collector sees fix head; prior Verify saw fixer cargo", async () => {
      const collectorHeads: Array<string | undefined> = [];
      const verifyFixerShas: Array<string | undefined> = [];
      let verifyCalls = 0;
      let fixerCalls = 0;

      const result = await runOnlineReviewLoopStage(
        offlineShip,
        onlineReviewDispatch({
          dispatchCollector: async (landing, round) => {
            collectorHeads.push(landing.shipDelivery?.prHead);
            return {
              evidence: stubCollectorEvidence({
                prUrl: offlineShip.pr,
                headOid: landing.shipDelivery?.prHead ?? offlineShip.prHead!,
                marker: round === 1 ? "r1" : "r2",
              }),
            };
          },
          dispatchVerify: async (landing) => {
            verifyCalls += 1;
            verifyFixerShas.push(landing.fixerResult?.fixCommitSha);
            if (verifyCalls === 1) {
              return {
                verify: {
                  kind: "verify",
                  converged: false,
                  fixMarkedFindingIdentityKeys: ["k1"],
                  fixMarkedFindingThreads: [
                    { identityKey: "k1", threadId: "t1" },
                  ],
                },
              };
            }
            if (verifyCalls === 2) {
              // Same-round return-to-judge with fixer opaque cargo.
              expect(landing.fixerResult).toEqual({
                kind: "fixer",
                committed: true,
                fixCommitSha: "post-fix-sha-1145",
              });
              // Judge continues → next Collector owns post-fix evidence.
              return {
                verify: {
                  kind: "verify",
                  converged: false,
                  isRecheck: true,
                  fixMarkedFindingIdentityKeys: ["k1"],
                  fixMarkedFindingThreads: [
                    { identityKey: "k1", threadId: "t1" },
                  ],
                },
              };
            }
            return { verify: { kind: "verify", converged: true, isRecheck: true } };
          },
          dispatchFixer: async () => {
            fixerCalls += 1;
            if (fixerCalls === 1) {
              return {
                kind: "fixer",
                committed: true,
                fixCommitSha: "post-fix-sha-1145",
              };
            }
            return { kind: "fixer", committed: false };
          },
          resolveFixCommitSha: async (sha) => sha,
        }),
      );

      expect(result.ok).toBe(true);
      expect(result.terminalState).toBe("mergeable");
      // Collector round1 at ship head; round2 at post-fix head (real retrigger seat).
      expect(collectorHeads).toEqual([offlineShip.prHead, "post-fix-sha-1145"]);
      expect(verifyFixerShas[1]).toBe("post-fix-sha-1145");
      expect(fixerCalls).toBeGreaterThanOrEqual(1);
    });

    it("post-fix: Collector capability plan is real (not host dual-owner)", () => {
      expect(ONLINE_REVIEW_BOT_RETRIGGER_COMMENT).toContain("@sourcery-ai review");
      expect(ONLINE_REVIEW_BOT_RETRIGGER_COMMENT).toContain("@codex review");
      expect(ONLINE_REVIEW_BOT_RETRIGGER_COMMENT).toContain("/gemini review");

      const idle = collectorPostFixRetriggerPlan({
        onlineReviewRound: 1,
        headOid: "head-1",
      });
      expect(idle.shouldRetrigger).toBe(false);

      const postFix = collectorPostFixRetriggerPlan({
        onlineReviewRound: 2,
        headOid: "fix-sha",
      });
      expect(postFix.shouldRetrigger).toBe(true);
      expect(postFix.commentBody).toBe(ONLINE_REVIEW_BOT_RETRIGGER_COMMENT);
      expect(postFix.intervalMs).toBe(BOT_POLL_INTERVAL_MS);
      expect(postFix.maxPolls).toBe(BOT_OVERDUE_POLL_COUNT);
      expect(postFix.overdueWallMs).toBe(BOT_OVERDUE_MIN_WALL_MS);

      // Host dual-owner post path stays deleted.
      expect(
        Object.prototype.hasOwnProperty.call(
          botPolling,
          "postBotRetriggerComment",
        ),
      ).toBe(false);
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

    it("contradictory cargo: converged+decision_gate never writes mergeable; re-entry keeps the gate", async () => {
      const backend = new TracerFamilyBackend();
      backend.verifyImpl = async () => ({
        kind: "completed",
        output: {
          kind: "verify",
          // Contradictory: green flag + escalate terminal. Disposition machine
          // is escalate-first; mergeable checkpoint must NOT swallow the gate.
          converged: true,
          terminalState: "decision_gate_raised",
        },
      });

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.terminalState).toBe("decision_gate_raised");
      expect(
        backend.ledger.some((e) => e.event === "online_review_mergeable"),
      ).toBe(false);

      // Re-entry must not short-circuit to mergeable — gate still stands.
      const second = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(second.ok).toBe(false);
      expect(second.terminalState).toBe("decision_gate_raised");
      expect(
        backend.ledger.some((e) => e.event === "online_review_mergeable"),
      ).toBe(false);
      // Collector checkpoint reused; Verify re-dispatched (no mergeable skip).
      expect(backend.collectorDispatchCount).toBe(1);
      expect(backend.verifyDispatchCount).toBe(2);
    });

    it("contradictory cargo: !converged+terminalState mergeable does not write mergeable; continues to fixer", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;

      backend.verifyImpl = async (_spec, _ctx, landing) => {
        verifyCalls += 1;
        if (verifyCalls === 1) {
          return {
            kind: "completed",
            output: {
              kind: "verify",
              // Contradictory: not green, but terminalState says mergeable.
              // Disposition = continue (only converged===true converges).
              converged: false,
              terminalState: "mergeable",
              fixMarkedFindingIdentityKeys: ["live:contradict"],
              fixMarkedFindingThreads: [
                { identityKey: "live:contradict", threadId: "t-c" },
              ],
            },
          };
        }
        // Same-round return-to-judge after fixer.
        expect(landing?.fixerResult).toEqual({
          kind: "fixer",
          committed: false,
        });
        return {
          kind: "completed",
          output: { kind: "verify", converged: true, isRecheck: false },
        };
      };

      backend.fixerImpl = async () => {
        fixerCalls += 1;
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
      expect(fixerCalls).toBe(1);
      expect(verifyCalls).toBe(2);
      // First contradictory cargo must NOT have written mergeable; only the
      // later real converge writes one.
      expect(
        backend.ledger.filter((e) => e.event === "online_review_mergeable"),
      ).toHaveLength(1);
    });

    it("post-fixer crash: no-op fixerResult survives; re-entry skips Fixer and feeds same Verify", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;
      let crashPostFixerVerify = true;
      const verifyFixerCargo: Array<WorkerLandingPayload["fixerResult"]> = [];

      // Crash at same-round Verify entry AFTER fixer_completed is durable.
      const origDispatch = backend.dispatchWorker.bind(backend);
      backend.dispatchWorker = async (spec, ctx, landing) => {
        if (
          crashPostFixerVerify &&
          spec.kind === "verify" &&
          landing?.fixerResult !== undefined
        ) {
          backend.kinds.push(spec.kind);
          backend.models.push(spec.model);
          backend.landings.push(landing);
          backend.verifyDispatchCount += 1;
          return {
            kind: "failed",
            reason:
              "simulated crash after fixer no-op before same-round verify: EISDIR: illegal operation on a directory",
          };
        }
        return origDispatch(spec, ctx, landing);
      };

      backend.verifyImpl = async (_spec, _ctx, landing) => {
        verifyCalls += 1;
        verifyFixerCargo.push(landing?.fixerResult);
        if (landing?.fixerResult !== undefined) {
          // Same-round Verify after durable fixer cargo.
          expect(landing.fixerResult).toEqual({
            kind: "fixer",
            committed: false,
            alreadySatisfied: true,
          });
          return {
            kind: "completed",
            output: { kind: "verify", converged: true, isRecheck: true },
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: false,
            fixMarkedFindingIdentityKeys: ["noop:1"],
            fixMarkedFindingThreads: [
              { identityKey: "noop:1", threadId: "t-noop" },
            ],
          },
        };
      };

      backend.fixerImpl = async () => {
        fixerCalls += 1;
        return {
          kind: "completed",
          output: {
            kind: "fixer",
            committed: false,
            alreadySatisfied: true,
          },
        };
      };

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.stopSummary?.summary).toMatch(
        /simulated crash after fixer no-op/,
      );
      expect(fixerCalls).toBe(1);
      expect(verifyCalls).toBe(1); // first seat only (post-fixer crashed)
      expect(
        backend.ledger.some((e) => e.event === "online_review_fixer_completed"),
      ).toBe(true);
      const fixerMarker = backend.ledger.find(
        (e) => e.event === "online_review_fixer_completed",
      );
      expect(fixerMarker?.fixerResultCargo).toEqual({
        kind: "fixer",
        committed: false,
        alreadySatisfied: true,
      });

      // Re-entry: no second Fixer; same-round Verify gets opaque cargo.
      crashPostFixerVerify = false;
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
      expect(fixerCalls).toBe(1);
      expect(verifyCalls).toBe(2);
      expect(verifyFixerCargo).toEqual([
        undefined,
        { kind: "fixer", committed: false, alreadySatisfied: true },
      ]);
      // Collector checkpoint reused — not re-burned.
      expect(backend.collectorDispatchCount).toBe(1);
    });

    it("post-fixer crash: commit fixerResult survives; re-entry skips Fixer and feeds same Verify", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;
      let crashPostFixerVerify = true;
      const verifyFixerCargo: Array<WorkerLandingPayload["fixerResult"]> = [];

      const origDispatch = backend.dispatchWorker.bind(backend);
      backend.dispatchWorker = async (spec, ctx, landing) => {
        if (
          crashPostFixerVerify &&
          spec.kind === "verify" &&
          landing?.fixerResult !== undefined
        ) {
          backend.kinds.push(spec.kind);
          backend.models.push(spec.model);
          backend.landings.push(landing);
          backend.verifyDispatchCount += 1;
          return {
            kind: "failed",
            reason:
              "simulated crash after fixer commit before same-round verify: EISDIR: illegal operation on a directory",
          };
        }
        return origDispatch(spec, ctx, landing);
      };

      backend.verifyImpl = async (_spec, _ctx, landing) => {
        verifyCalls += 1;
        verifyFixerCargo.push(landing?.fixerResult);
        if (landing?.fixerResult !== undefined) {
          expect(landing.fixerResult).toEqual({
            kind: "fixer",
            committed: true,
            fixCommitSha: "fix-sha-post-crash-1145",
          });
          return {
            kind: "completed",
            output: { kind: "verify", converged: true, isRecheck: true },
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: false,
            fixMarkedFindingIdentityKeys: ["commit:1"],
            fixMarkedFindingThreads: [
              { identityKey: "commit:1", threadId: "t-commit" },
            ],
          },
        };
      };

      backend.fixerImpl = async () => {
        fixerCalls += 1;
        return {
          kind: "completed",
          output: {
            kind: "fixer",
            committed: true,
            fixCommitSha: "fix-sha-post-crash-1145",
          },
        };
      };

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.stopSummary?.summary).toMatch(
        /simulated crash after fixer commit/,
      );
      expect(fixerCalls).toBe(1);
      expect(
        backend.ledger.some((e) => e.event === "online_review_fixer_completed"),
      ).toBe(true);

      crashPostFixerVerify = false;
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
      expect(fixerCalls).toBe(1);
      expect(verifyCalls).toBe(2);
      expect(verifyFixerCargo[1]).toEqual({
        kind: "fixer",
        committed: true,
        fixCommitSha: "fix-sha-post-crash-1145",
      });
      // Commit bookkeeping lands via resolveFixCommitSha (before V2 crash).
      expect(
        backend.ledger.some(
          (e) =>
            e.event === "online_review_fix_committed" &&
            e.familyHeadAfter === "fix-sha-post-crash-1145",
        ),
      ).toBe(true);
    });

    it("post-fixer continue crash: re-entry starts next Collector; Verify side effects not replayed", async () => {
      const backend = new TracerFamilyBackend();
      let verifyCalls = 0;
      let fixerCalls = 0;
      const collectorRounds: number[] = [];
      let crashAfterContinue = true;

      backend.dispatchWorker = async (spec, ctx, landing) => {
        backend.kinds.push(spec.kind);
        backend.models.push(spec.model);
        if (landing !== undefined) backend.landings.push(landing);

        if (spec.kind === "collector") {
          const round =
            landing?.onlineReviewRound ?? ctx.onlineReviewRound ?? 1;
          collectorRounds.push(round);
          // After post-fixer continue is durable, crash before next Collector burns.
          if (
            crashAfterContinue &&
            round === 2 &&
            backend.ledger.some(
              (e) =>
                e.event === "online_review_verify_continued" &&
                e.onlineReviewRound === 1,
            )
          ) {
            backend.collectorDispatchCount += 1;
            return {
              kind: "failed",
              reason:
                "simulated crash after post-fixer verify continue before next collector: EISDIR: illegal operation on a directory",
            };
          }
          backend.collectorDispatchCount += 1;
          return {
            kind: "completed",
            output: {
              kind: "collector",
              evidence: stubCollectorEvidence({
                prUrl: offlineShip.pr,
                headOid: `head-r${round}`,
                marker: `marker-r${round}`,
              }),
            },
          };
        }

        if (spec.kind === "verify") {
          verifyCalls += 1;
          backend.verifyDispatchCount += 1;
          const hadFixer = landing?.fixerResult !== undefined;
          const round = landing?.onlineReviewRound ?? 1;

          if (round >= 2) {
            // Next-round seat after durable continue — converge, no new Fixer.
            return {
              kind: "completed",
              output: { kind: "verify", converged: true, isRecheck: false },
            };
          }

          if (!hadFixer) {
            return {
              kind: "completed",
              output: {
                kind: "verify",
                converged: false,
                fixMarkedFindingIdentityKeys: [`r${round}:k`],
                fixMarkedFindingThreads: [
                  { identityKey: `r${round}:k`, threadId: `t-r${round}` },
                ],
              },
            };
          }

          // Round-1 post-fixer continue — durable verify_continued then next Collector crashes.
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              isRecheck: true,
              fixMarkedFindingIdentityKeys: ["r1:next"],
              fixMarkedFindingThreads: [
                { identityKey: "r1:next", threadId: "t-next" },
              ],
            },
          };
        }

        if (spec.kind === "fixer") {
          fixerCalls += 1;
          return {
            kind: "completed",
            output: { kind: "fixer", committed: false },
          };
        }

        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      };

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.stopSummary?.summary).toMatch(
        /simulated crash after post-fixer verify continue/,
      );
      expect(fixerCalls).toBe(1);
      expect(verifyCalls).toBe(2); // V1 + V2
      expect(
        backend.ledger.some(
          (e) =>
            e.event === "online_review_verify_continued" &&
            e.onlineReviewRound === 1,
        ),
      ).toBe(true);
      expect(
        backend.ledger.some((e) => e.event === "online_review_mergeable"),
      ).toBe(false);

      const verifyBefore = verifyCalls;
      const fixerBefore = fixerCalls;
      // Round-2 collector was attempted (and failed) — not short-circuited.
      expect(collectorRounds.filter((r) => r === 2).length).toBeGreaterThanOrEqual(
        1,
      );

      // Re-entry: must NOT re-run round-1 Verify (side effects once).
      crashAfterContinue = false;
      const second = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(second.ok).toBe(true);
      expect(second.terminalState).toBe("mergeable");
      expect(second.round).toBe(2);
      expect(fixerCalls).toBe(fixerBefore); // no re-Fixer
      // Only new Verify seats for round 2 — no replay of round-1 V1/V2.
      expect(verifyCalls).toBe(verifyBefore + 1);
      expect(collectorRounds.filter((r) => r === 1)).toHaveLength(1);
      // Successful round-2 collector on re-entry (plus the crashed attempt).
      expect(collectorRounds.filter((r) => r === 2).length).toBeGreaterThanOrEqual(
        2,
      );
    });

    it("durable round: multi no-op continue → round-3 checkpoint → crash/re-entry uses latest evidence", async () => {
      const backend = new TracerFamilyBackend();
      const r3Evidence = stubCollectorEvidence({
        prUrl: offlineShip.pr,
        headOid: "head-round-3-latest",
        marker: "marker-r3-latest",
      });
      let verifyByRound = new Map<number, number>();

      backend.dispatchWorker = async function (
        this: TracerFamilyBackend,
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        this.kinds.push(spec.kind);
        this.models.push(spec.model);
        if (landing !== undefined) this.landings.push(landing);

        if (spec.kind === "collector") {
          this.collectorDispatchCount += 1;
          const round = landing?.onlineReviewRound ?? ctx.onlineReviewRound ?? 1;
          // Distinct evidence per round so resume can prove latest-wins.
          const evidence =
            round >= 3
              ? r3Evidence
              : stubCollectorEvidence({
                  prUrl: offlineShip.pr,
                  headOid: `head-round-${round}`,
                  marker: `marker-r${round}`,
                });
          this.collectorEvidence = evidence;
          return {
            kind: "completed",
            output: { kind: "collector", evidence },
          };
        }

        if (spec.kind === "verify") {
          this.verifyDispatchCount += 1;
          const round = landing?.onlineReviewRound ?? 1;
          verifyByRound.set(round, (verifyByRound.get(round) ?? 0) + 1);
          const callsThisRound = verifyByRound.get(round)!;

          if (this.blockVerify) {
            return {
              kind: "failed",
              reason:
                "simulated crash after round-3 collector checkpoint: EISDIR",
            };
          }

          // Rounds 1–2: first seat continues → fixer no-op → same-round
          // re-entry continues → advance to next Collector cycle.
          // Round 3: first seat crashes (blockVerify) or converges on re-entry.
          if (round < 3) {
            if (callsThisRound === 1) {
              return {
                kind: "completed",
                output: {
                  kind: "verify",
                  converged: false,
                  fixMarkedFindingIdentityKeys: [`r${round}:k`],
                  fixMarkedFindingThreads: [
                    { identityKey: `r${round}:k`, threadId: `t-r${round}` },
                  ],
                },
              };
            }
            // After no-op fixer cargo: continue to next round (no new commit).
            return {
              kind: "completed",
              output: {
                kind: "verify",
                converged: false,
                isRecheck: true,
                fixMarkedFindingIdentityKeys: [`r${round}:k`],
                fixMarkedFindingThreads: [
                  { identityKey: `r${round}:k`, threadId: `t-r${round}` },
                ],
              },
            };
          }

          // Round 3: converge (re-entry after crash).
          return {
            kind: "completed",
            output: { kind: "verify", converged: true, isRecheck: false },
          };
        }

        if (spec.kind === "fixer") {
          // Legal no-op — no fix_committed marker, round still advances.
          return {
            kind: "completed",
            output: { kind: "fixer", committed: false },
          };
        }

        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      };

      // First run: drive to round-3 Collector checkpoint, then crash Verify.
      backend.blockVerify = true;
      // Unblock only after round-3 collector has written; crash the first
      // Verify of round 3. blockVerify is checked inside dispatch above.
      // We need blockVerify true only once round 3 collector is done.
      // Simpler: let rounds 1–2 run with blockVerify false, flip before r3 verify.
      backend.blockVerify = false;
      const origDispatch = backend.dispatchWorker.bind(backend);
      let r3CollectorDone = false;
      backend.dispatchWorker = async (spec, ctx, landing) => {
        const result = await origDispatch(spec, ctx, landing);
        if (
          spec.kind === "collector" &&
          (landing?.onlineReviewRound ?? ctx.onlineReviewRound) === 3 &&
          result.kind === "completed"
        ) {
          r3CollectorDone = true;
          backend.blockVerify = true;
        }
        return result;
      };

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first.ok).toBe(false);
      expect(first.terminalState).toBe("decision_gate_raised");
      expect(r3CollectorDone).toBe(true);

      const r3Checkpoints = backend.ledger.filter(
        (e) =>
          e.event === "online_review_collector_completed" &&
          e.onlineReviewRound === 3,
      );
      expect(r3Checkpoints).toHaveLength(1);
      expect(r3Checkpoints[0]?.collectorEvidenceCargo).toEqual(r3Evidence);
      // No fix commits across no-op continues — old count-based resume would
      // under-count and orphan round-3 evidence.
      expect(
        backend.ledger.filter((e) => e.event === "online_review_fix_committed"),
      ).toHaveLength(0);
      expect(
        backend.ledger.some((e) => e.event === "online_review_mergeable"),
      ).toBe(false);

      const collectorsBefore = backend.collectorDispatchCount;
      const verifyBefore = backend.verifyDispatchCount;

      // Re-entry: durable round must be 3 (max live marker), not 1 (zero fixes).
      backend.blockVerify = false;
      // Keep the wrapped dispatch so collector still serves r3 evidence when
      // asked, but checkpoint should short-circuit Collector entirely.
      const second = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });

      expect(second).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 3,
      });
      // Collector not re-burned — checkpoint for round 3 reused.
      expect(backend.collectorDispatchCount).toBe(collectorsBefore);
      expect(backend.verifyDispatchCount).toBe(verifyBefore + 1);

      const reentryVerify = backend.kinds
        .map((kind, i) => ({ kind, landing: backend.landings[i] }))
        .filter((p) => p.kind === "verify")
        .at(-1);
      expect(reentryVerify?.landing?.onlineReviewRound).toBe(3);
      expect(reentryVerify?.landing?.onlineReviewSnapshot).toEqual(r3Evidence);
    });
  });

  describe("#1145 DecisionGate A — worker durable store / opaque / no host classify",
    () => {
    it("T2: stage does not lift evidence headOid; Verify unpacks body; no host-mint pointer",
      async () => {
      const backend = new TracerFamilyBackend();
      backend.collectorEvidence = stubCollectorEvidence({
        prUrl: offlineShip.pr,
        headOid: "evidence-head-MUST-NOT-ELEVATE",
        marker: "t2-marker",
      });
      let verifySawBody: unknown;
      backend.verifyImpl = async (_s, _c, landing) => {
        verifySawBody = landing?.onlineReviewSnapshot;
        expect(landing?.shipDelivery?.prHead).toBe(offlineShip.prHead);
        expect(landing?.onlineReviewSnapshot?.headOid).toBe(
          "evidence-head-MUST-NOT-ELEVATE",
        );
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      };

      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(result.ok).toBe(true);
      expect(verifySawBody).toEqual(backend.collectorEvidence);
      const completed = backend.ledger.find(
        (e) => e.event === "online_review_collector_completed",
      );
      expect(completed?.familyHeadAfter).toBe(offlineShip.prHead);
      // Worker did not supply cargoPointer — host must not mint one.
      expect(completed?.cargoPointer).toBeUndefined();
      // Dead host progress status must not reappear on the ledger.
      expect(
        backend.ledger.some(
          (e) =>
            (e.event as string | undefined) ===
            "online_review_collection_progress",
        ),
      ).toBe(false);
    });

    it("handle-only cargoPointer survives shared-tail → Verify / re-entry (no body, no re-wait)",
      async () => {
      const HANDLE = "blobs/r1-evidence-put-handle-only-1145";
      const backend = new TracerFamilyBackend();
      backend.collectorCargoPointer = HANDLE;

      let firstVerifyLanding: WorkerLandingPayload | undefined;
      backend.verifyImpl = async (_s, _c, landing) => {
        firstVerifyLanding = landing;
        // Simulate Verify calling evidence-get on the durable handle without
        // re-waiting — host only transported the pointer.
        expect(landing?.cargoPointer).toBe(HANDLE);
        expect(landing?.onlineReviewSnapshot).toBeUndefined();
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      };

      const first = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(first).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 1,
      });
      expect(backend.collectorDispatchCount).toBe(1);
      expect(firstVerifyLanding?.cargoPointer).toBe(HANDLE);
      expect(firstVerifyLanding?.onlineReviewSnapshot).toBeUndefined();

      const completed = backend.ledger.find(
        (e) => e.event === "online_review_collector_completed",
      );
      expect(completed?.cargoPointer).toBe(HANDLE);
      expect(completed?.collectorEvidenceCargo).toBeUndefined();

      // Re-entry: checkpoint short-circuits Collector (no re-wait); same handle
      // reaches Verify again. Strip mergeable so the loop runs; keep checkpoint.
      backend.ledger = backend.ledger.filter(
        (e) => e.event !== "online_review_mergeable",
      );
      let reentryLanding: WorkerLandingPayload | undefined;
      const priorCollectorDispatches = backend.collectorDispatchCount;
      backend.verifyImpl = async (_s, _c, landing) => {
        reentryLanding = landing;
        expect(landing?.cargoPointer).toBe(HANDLE);
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      };
      const second = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(second.ok).toBe(true);
      // Checkpoint short-circuit — no second live Collector dispatch.
      expect(backend.collectorDispatchCount).toBe(priorCollectorDispatches);
      expect(reentryLanding?.cargoPointer).toBe(HANDLE);
      expect(reentryLanding?.onlineReviewSnapshot).toBeUndefined();
    });

    it("T4: missing durable progress does not gate — host still dispatches Collector",
      async () => {
      const backend = new TracerFamilyBackend();
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(result).toMatchObject({
        ok: true,
        terminalState: "mergeable",
      });
      expect(result.terminalState).not.toBe("decision_gate_raised");
      expect(backend.collectorDispatchCount).toBe(1);

      // round+1 after continue: second Collector dispatch (pristine for worker).
      const backend2 = new TracerFamilyBackend();
      backend2.verifyImpl = async (_s, _c, landing) => {
        const r = landing?.onlineReviewRound ?? 1;
        if (r === 1 && landing?.fixerResult === undefined) {
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              fixMarkedFindingIdentityKeys: ["k1"],
              fixMarkedFindingThreads: [
                { identityKey: "k1", threadId: "t1" },
              ],
            },
          };
        }
        if (r === 1 && landing?.fixerResult !== undefined) {
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              fixMarkedFindingIdentityKeys: ["k2"],
              fixMarkedFindingThreads: [
                { identityKey: "k2", threadId: "t2" },
              ],
            },
          };
        }
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      };
      backend2.fixerImpl = async () => ({
        kind: "completed",
        output: { kind: "fixer", committed: false },
      });
      const multi = await runFamilyOnlineReviewLoop({
        familyBackend: backend2,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(multi.ok).toBe(true);
      expect(multi.terminalState).toBe("mergeable");
      expect(backend2.collectorDispatchCount).toBeGreaterThanOrEqual(2);
      expect(
        backend2.ledger.some(
          (e) =>
            (e.event as string | undefined) ===
            "online_review_collection_progress",
        ),
      ).toBe(false);
    });

    it("T5 sparse opaque blob: Collector completes; Verify receives body; no fate rewrite",
      async () => {
      const backend = new TracerFamilyBackend();
      backend.collectorEvidence = stubCollectorEvidence({
        prUrl: offlineShip.pr,
        headOid: offlineShip.prHead,
      });
      let verifyLanding: WorkerLandingPayload | undefined;
      backend.verifyImpl = async (_s, _c, landing) => {
        verifyLanding = landing;
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/1145",
        ship: offlineShip,
      });
      expect(result.ok).toBe(true);
      expect(result.terminalState).toBe("mergeable");
      expect(verifyLanding?.onlineReviewSnapshot).toEqual(
        backend.collectorEvidence,
      );
      expect(
        backend.ledger.some(
          (e) => e.event === "online_review_collector_completed",
        ),
      ).toBe(true);
    });

    it("durable host ships bin.mjs only — no TS store twin; no host classify",
      async () => {
      const { mkdtempSync, rmSync, readFileSync, existsSync } =
        await import("node:fs");
      const { join } = await import("node:path");
      const { tmpdir } = await import("node:os");
      const {
        ensureOnlineReviewDurableDir,
        ONLINE_REVIEW_DURABLE_DIR,
      } = await import("../src/family/onlineReviewActionDurable.js");

      const workingRepo = mkdtempSync(join(tmpdir(), "or-durable-1145-"));
      try {
        const { hostPath } = ensureOnlineReviewDurableDir(workingRepo);
        expect(hostPath).toBe(join(workingRepo, ONLINE_REVIEW_DURABLE_DIR));
        const binPath = join(hostPath, "bin.mjs");
        expect(existsSync(binPath)).toBe(true);
        // Worker-callable CLI is the sole durable capability (no host twin).
        const binSrc = readFileSync(binPath, "utf8");
        expect(binSrc).toMatch(/progress-classify/);
        expect(binSrc).toMatch(/receipt-decide/);
        expect(binSrc).toMatch(/evidence-put/);
        expect(binSrc).toMatch(/evidence-get/);

        // Host module is mount/copy only — no store twin exports.
        const durableMod = await import(
          "../src/family/onlineReviewActionDurable.js"
        );
        expect(durableMod).not.toHaveProperty("openOnlineReviewDurableStore");
        expect(durableMod).not.toHaveProperty("classifyCollectionProgress");
        expect(durableMod).not.toHaveProperty("decideSideEffectRecovery");
        expect(durableMod).not.toHaveProperty("executeIdempotentSideEffect");

        // Host production path must not import-call classify (static pin).
        const verifyCmrSrc = readFileSync(
          new URL("../src/family/verifyCmr.ts", import.meta.url),
          "utf8",
        );
        expect(verifyCmrSrc).not.toMatch(/classifyCollectionProgress/);
        expect(verifyCmrSrc).not.toMatch(/recordOnlineReviewCollectionProgress/);
        expect(verifyCmrSrc).not.toMatch(/ledger:online-review-evidence/);
      } finally {
        rmSync(workingRepo, { recursive: true, force: true });
      }
    });

    it("sandbox-config mounts durable RW + env on collector/verify seats",
      async () => {
      const { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync } =
        await import("node:fs");
      const { join } = await import("node:path");
      const { tmpdir } = await import("node:os");
      const { RealFamilyBackend } = await import(
        "../src/family/realFamilyBackend.js"
      );
      const {
        ONLINE_REVIEW_DURABLE_DIR,
        ONLINE_REVIEW_DURABLE_PATH_ENV,
        ONLINE_REVIEW_DURABLE_SANDBOX_PATH,
      } = await import("../src/family/onlineReviewActionDurable.js");

      const workingRepo = mkdtempSync(join(tmpdir(), "or-sandbox-1145-"));
      try {
        mkdirSync(join(workingRepo, ".git", "info"), { recursive: true });
        writeFileSync(join(workingRepo, ".git", "config"), "");
        const { fileURLToPath } = await import("node:url");
        const packageRoot = fileURLToPath(new URL("..", import.meta.url));
        const promptsDir = join(packageRoot, "prompts");
        const soulsDir = join(packageRoot, "image", "souls");
        class Harness extends RealFamilyBackend {
          exposeConfig(spec: WorkerSpec, ctx: DispatchContext) {
            return this.familyReviewLoopSandboxConfig(
              {},
              spec,
              ctx,
              undefined,
              undefined,
            );
          }
        }
        const backend = new Harness({
          workingRepo,
          familyBase: "family/1145",
          ledgerDir: join(workingRepo, "ledger"),
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir,
          soulsDir,
          imageName: "test-image",
        });

        const ctx: DispatchContext = { familyBase: "family/1145" };
        for (const spec of [collectorWorkerSpec(), verifyWorkerSpec()]) {
          const cfg = backend.exposeConfig(spec, ctx);
          expect(cfg.env[ONLINE_REVIEW_DURABLE_PATH_ENV]).toBe(
            ONLINE_REVIEW_DURABLE_SANDBOX_PATH,
          );
          const durableMount = cfg.mounts.find(
            (m) => m.sandboxPath === ONLINE_REVIEW_DURABLE_SANDBOX_PATH,
          );
          expect(durableMount).toBeDefined();
          expect(durableMount?.hostPath).toBe(
            join(workingRepo, ONLINE_REVIEW_DURABLE_DIR),
          );
          expect(durableMount?.readonly).not.toBe(true);
        }

        // Source pin: production config wires durable mount (not host classify).
        const src = readFileSync(
          new URL("../src/family/realFamilyBackend.ts", import.meta.url),
          "utf8",
        );
        expect(src).toMatch(/onlineReviewDurableMount/);
        expect(src).toMatch(/ONLINE_REVIEW_DURABLE_PATH_ENV/);
      } finally {
        rmSync(workingRepo, { recursive: true, force: true });
      }
    });

    it("souls own side-effect/durable methods; promptFile is not second truth",
      async () => {
      const { readFileSync } = await import("node:fs");
      const collectorSoul = readFileSync(
        new URL("../image/souls/collector.md", import.meta.url),
        "utf8",
      );
      const verifySoul = readFileSync(
        new URL("../image/souls/verify.md", import.meta.url),
        "utf8",
      );
      const verifyPrompt = readFileSync(
        new URL("../prompts/verify.md", import.meta.url),
        "utf8",
      );
      expect(collectorSoul).toMatch(/bin\.mjs/);
      expect(collectorSoul).toMatch(/progress-classify/);
      expect(collectorSoul).toMatch(/evidence-put/);
      expect(verifySoul).toMatch(/副作用方法/);
      expect(verifySoul).toMatch(/receipt-attempted/);
      expect(verifySoul).toMatch(/receipt-decide/);
      expect(verifyPrompt).toMatch(/Side-effect method truth lives in the Verify soul/);
      expect(verifyPrompt).not.toMatch(/gh api` comment on the review thread/);
    });
  });
});
