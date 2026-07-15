/**
 * #686 — relay dispatch: baton handoff across quota walls / hangs / self-report.
 *
 * Seams under test (owner ratification 2026-07-08 + 2026-07-10 deltas):
 *   1. parseRelayTag — shape-validated <relay> terminal (fail-closed)
 *   2. three handoff triggers (429 preserve; hang-with-live-pool kill+relay; blocked)
 *   3. resource failure NEVER calls resetBeforeRetry (#661 boundary)
 *   4. state_summary → ledger + next-baton parameter file; resume from any baton
 *   5. closing baton → normal review gate (no relay exemption)
 *   6. route pool table + three-tier park/relay at #683 disposition point
 *   7. next baton = #767 roster + pool-orthogonal lookup (换马甲 then 顺位)
 *   8. R1: REAL runner park sites (S9/S2) wire the fork — not a parallel dead seam
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CODER_ROSTER,
  lookupCoderRosterEntry,
  poolSeparationViolation,
  resolveCoderRecOrder,
} from "../../src/coderRoster.js";
import { modelIdForSlug } from "../../src/modelRegistry.js";
import { resolveRouteModels } from "../../src/modelRoutes.js";
import {
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  type BillingPoolEntry,
  type BillingPoolId,
  type PoolTable,
} from "../../src/quotaPoolTable.js";
import {
  RELAY_FOCUS_FILENAME,
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayFocusFile,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  CapacityRelayError,
  countRelayHandoffsInLedger,
  decideRelayAfterIdle,
  forkQuotaWallAt683Point,
  HangWithLivePoolError,
  isHangWithLivePoolError,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  parseRelayTag,
  resumeRelayFromLedger,
  stageRelayFocusFile,
  tryBuildRelayFocusFile,
  tryParseActionableRelayTag,
  type RelayHandoffLedgerEvent,
} from "../../src/relayDispatch.js";
import { decideIdleAfterProbe, QuotaWaitForResetError } from "../../src/quotaProbe.js";
import { buildCliMonitorSpawnSpec } from "../../src/cliMonitorHooks.js";
import { dispatchWorkerWithMonitor, legacyDispatchWorker } from "../../src/dispatchWorker.js";
import { relayCandidateConflictSlugs, runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepSpec,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

describe("#686 relay tag contract (fail-closed)", () => {
  it("uses explicit resource and decision-gate signal bits without reading prose", () => {
    expect(
      parseRelayTag(
        `<relay>{"resource":true,"phase":"build","state_summary":"partial","remaining":"continue"}</relay>`,
      ),
    ).toMatchObject({ kind: "phase_complete", phase: "build" });
    expect(
      parseRelayTag(
        `<relay>{"decision_gate":true,"state_summary":"need a ruling"}</relay>`,
      ),
    ).toEqual({
      kind: "decision_gate",
      state_summary: "need a ruling",
    });
  });

  it("accepts phase_complete build|clear with state_summary + remaining", () => {
    const stdout = [
      "建造完成，待清障。",
      `<relay>{"phase_complete":"build","state_summary":"142 tests pending","remaining":"clear mechanical reds"}</relay>`,
    ].join("\n");
    expect(parseRelayTag(stdout)).toEqual({
      kind: "phase_complete",
      phase: "build",
      state_summary: "142 tests pending",
      remaining: "clear mechanical reds",
    });
  });

  it("accepts the blocked variant", () => {
    const stdout = `<relay>{"blocked":{"reason":"design gap on schema","state_summary":"half of apply wired","remaining":"need human on ADR"}}</relay>`;
    expect(parseRelayTag(stdout)).toEqual({
      kind: "blocked",
      reason: "design gap on schema",
      state_summary: "half of apply wired",
      remaining: "need human on ADR",
    });
  });

  it("malformed relay is NOT phase_complete (fail-closed)", () => {
    expect(parseRelayTag("no tag here").kind).toBe("malformed");
    expect(
      parseRelayTag(`<relay>{"phase_complete":"build"}</relay>`).kind,
    ).toBe("malformed");
    expect(
      parseRelayTag(
        `<relay>{"phase_complete":"done","state_summary":"x","remaining":"y"}</relay>`,
      ).kind,
    ).toBe("malformed");
    expect(
      parseRelayTag(`<relay>not-json</relay>`).kind,
    ).toBe("malformed");
    // Mixed / extra keys → malformed (strict)
    expect(
      parseRelayTag(
        `<relay>{"phase_complete":"build","state_summary":"a","remaining":"b","blocked":true}</relay>`,
      ).kind,
    ).toBe("malformed");
  });

  it("reads the LAST <relay> tag when the worker iterates", () => {
    const stdout = [
      `<relay>{"phase_complete":"build","state_summary":"old","remaining":"x"}</relay>`,
      `<relay>{"phase_complete":"clear","state_summary":"new","remaining":"收口"}</relay>`,
    ].join("\n");
    const parsed = parseRelayTag(stdout);
    expect(parsed).toMatchObject({
      kind: "phase_complete",
      phase: "clear",
      state_summary: "new",
    });
  });
});

describe("#686 route pool table + three-tier park/relay (ADR 0124/0125)", () => {
  const now = new Date("2026-07-10T12:00:00.000Z");

  it("defaults T to 30 minutes", () => {
    expect(DEFAULT_PARK_THRESHOLD_MS).toBe(30 * 60 * 1000);
  });

  it("same-pool reset within T → park (wait for original baton)", () => {
    const resetAt = new Date(now.getTime() + 20 * 60 * 1000); // 20 min
    expect(
      decideParkOrRelay({
        now,
        resetAt,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: true,
      }),
    ).toBe("park");
  });

  it("reset beyond T + live baton exists → relay", () => {
    const resetAt = new Date(now.getTime() + 45 * 60 * 1000); // 45 min
    expect(
      decideParkOrRelay({
        now,
        resetAt,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: true,
      }),
    ).toBe("relay");
  });

  it("no live baton → park fallback (even when reset > T)", () => {
    const resetAt = new Date(now.getTime() + 45 * 60 * 1000);
    expect(
      decideParkOrRelay({
        now,
        resetAt,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: false,
      }),
    ).toBe("park_fallback");
  });

  it("missing resetAt is treated as beyond T (cannot wait a known window)", () => {
    expect(
      decideParkOrRelay({
        now,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: true,
      }),
    ).toBe("relay");
    expect(
      decideParkOrRelay({
        now,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: false,
      }),
    ).toBe("park_fallback");
  });

  it("already-elapsed resetAt is beyond T (never clamped into park)", () => {
    const resetAt = new Date(now.getTime() - 60_000); // 1 min ago
    expect(
      decideParkOrRelay({
        now,
        resetAt,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: true,
      }),
    ).toBe("relay");
    expect(
      decideParkOrRelay({
        now,
        resetAt,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        hasLiveBaton: false,
      }),
    ).toBe("park_fallback");
  });

  it("pool table entries carry resetAt and configurable T", () => {
    const table: PoolTable = {
      "grok-build": {
        id: "grok-build",
        status: "limited",
        resetAt: new Date("2026-07-10T13:00:00.000Z"),
        parkThresholdMs: 15 * 60 * 1000,
        models: ["grok-4.5"],
      },
      cursor: {
        id: "cursor",
        status: "live",
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        models: ["grok-4.5"],
      },
    };
    expect(table["grok-build"]!.parkThresholdMs).toBe(15 * 60 * 1000);
    expect(table.cursor!.status).toBe("live");
    expect(table["grok-build"]!.resetAt?.toISOString()).toBe(
      "2026-07-10T13:00:00.000Z",
    );
  });
});

describe("#686 next baton = #767 roster + pool-orthogonal lookup (ADR 0126)", () => {
  function livePool(
    id: BillingPoolId,
    models: ReadonlyArray<string>,
  ): BillingPoolEntry {
    return {
      id,
      status: "live",
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: [...models],
    };
  }

  function deadPool(
    id: BillingPoolId,
    models: ReadonlyArray<string>,
  ): BillingPoolEntry {
    return {
      id,
      status: "dead",
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      models: [...models],
    };
  }

  it("same model on a live alternate pool wins first (换马甲)", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", ["grok-4.5"]),
        livePool("cursor", ["grok-4.5"]),
        livePool("codex-5h", ["terra@med", "luna@med"]),
      ],
    });
    expect(next).toEqual({
      modelId: "grok-4.5",
      slug: "grok-4.5",
      pool: "cursor",
    });
  });

  it("all pools for current model dead → advance to next roster model with a live pool", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", ["grok-4.5"]),
        deadPool("cursor", ["grok-4.5"]),
        livePool("codex-5h", ["terra@med", "luna@med"]),
      ],
    });
    expect(next).toEqual({
      modelId: "terra@med",
      slug: "gpt-5.6-terra",
      pool: "codex-5h",
    });
  });

  it("preserves pool-separation filter (skip reviewer-colliding slug)", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", ["grok-4.5"]),
        livePool("codex-5h", ["terra@med", "luna@med"]),
      ],
      reviewerSlugs: ["gpt-5.6-terra"],
    });
    expect(next?.modelId).toBe("luna@med");
    expect(next?.slug).toBe("gpt-5.6-luna");
  });

  it("returns undefined when no live baton exists anywhere", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med",
    );
    expect(
      selectNextRelayBaton({
        currentModelId: "grok-4.5",
        currentPool: "grok-build",
        rosterOrder: order,
        pools: [
          deadPool("grok-build", ["grok-4.5"]),
          deadPool("codex-5h", ["terra@med"]),
        ],
      }),
    ).toBeUndefined();
  });

  /**
   * #789 / codex bot P2 on PR #792: roster entries alone are not enough —
   * selectNextRelayBaton only picks models served by a live BillingPoolEntry.
   * Default pool table must map sonnet-5 / haiku-4.5 onto the claude pool so a
   * Coder-Rec line `grok-4.5 → haiku-4.5 → sonnet-5` can hand off after grok
   * parks past T (when the claude pool is live / probed).
   */
  it("#789 grok exhaustion relay selects Claude baton via default pool models", () => {
    expect(DEFAULT_POOL_MODELS.claude).toEqual(
      expect.arrayContaining(["haiku-4.5", "sonnet-5", "haiku", "sonnet"]),
    );
    expect(billingPoolFromQuotaPool("claude")).toBe("claude");

    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → haiku-4.5 → sonnet-5",
    );
    expect(order.map((e) => e.id)).toEqual([
      "grok-4.5",
      "haiku-4.5",
      "sonnet-5",
    ]);

    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", DEFAULT_POOL_MODELS["grok-build"]),
        deadPool("cursor", DEFAULT_POOL_MODELS.cursor),
        deadPool("zai", DEFAULT_POOL_MODELS.zai),
        deadPool("codex-5h", DEFAULT_POOL_MODELS["codex-5h"]),
        livePool("claude", DEFAULT_POOL_MODELS.claude),
      ],
      // normal CMR Claude leg is opus — distinct slug from sonnet/haiku.
      reviewerSlugs: ["opus", "gpt-5.6-sol", "agy"],
    });
    expect(next).toEqual({
      modelId: "haiku-4.5",
      slug: "haiku",
      pool: "claude",
    });
  });

  /**
   * #789 / review P2: haiku-first order alone is not enough coverage — the
   * common "full face" Coder-Rec line puts sonnet-5 ahead of haiku-4.5 and must
   * actually select the Sonnet baton after grok parks past T.
   */
  it("#789 grok exhaustion relay selects Sonnet baton when ordered before haiku", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5",
    );
    expect(order.map((e) => e.id)).toEqual([
      "grok-4.5",
      "sonnet-5",
      "haiku-4.5",
    ]);

    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", DEFAULT_POOL_MODELS["grok-build"]),
        deadPool("cursor", DEFAULT_POOL_MODELS.cursor),
        deadPool("zai", DEFAULT_POOL_MODELS.zai),
        deadPool("codex-5h", DEFAULT_POOL_MODELS["codex-5h"]),
        livePool("claude", DEFAULT_POOL_MODELS.claude),
      ],
      // normal CMR Claude leg is opus — distinct slug from sonnet/haiku.
      reviewerSlugs: ["opus", "gpt-5.6-sol", "agy"],
    });
    expect(next).toEqual({
      modelId: "sonnet-5",
      slug: "sonnet",
      pool: "claude",
    });
    // Runtime model id for slug `sonnet` must match roster Sonnet 5 promise.
    expect(modelIdForSlug(next!.slug)).toBe("claude-sonnet-5");
  });

  it("#789 default pool table includes claude row without fabricating live status", () => {
    const pools = buildDefaultBillingPools({
      limitedPool: "grok-build",
      resetAt: new Date("2026-07-10T13:00:00.000Z"),
    });
    const claude = pools.find((p) => p.id === "claude");
    expect(claude).toBeDefined();
    expect(claude!.status).toBe("dead");
    expect(claude!.models).toEqual(
      expect.arrayContaining(["haiku-4.5", "sonnet-5"]),
    );
    // Unprobed default still must not invent a live Claude baton.
    expect(
      hasLiveRelayBaton({
        currentModelId: "grok-4.5",
        currentPool: "grok-build",
        rosterOrder: resolveCoderRecOrder(
          "Coder-Rec: grok-4.5 → haiku-4.5 → sonnet-5",
        ),
        pools,
      }),
    ).toBe(false);
  });

  it("roster table remains the single source (no second relay fallback table)", () => {
    // Sanity: selection only walks CODER_ROSTER / Coder-Rec order.
    expect(CODER_ROSTER.map((e) => e.id)).toEqual(
      expect.arrayContaining(["grok-4.5", "terra@med", "luna@med"]),
    );
    expect(lookupCoderRosterEntry("grok-4.5")?.slug).toBe("grok-4.5");
  });
});

describe("#787 capacity relay", () => {
  const now = new Date("2026-07-11T12:00:00.000Z");

  it("at-capacity relays to the next checkpoint in the same live pool and records capacity", async () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    const pools = [
      {
        id: "codex-5h" as const,
        status: "live" as const,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        models: ["terra@med", "luna@med"],
      },
      {
        id: "grok-build" as const,
        status: "live" as const,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        models: ["grok-4.5"],
      },
    ];

    expect(
      selectCapacityRelayBaton({
        currentModelId: "terra@med",
        currentPool: "codex-5h",
        rosterOrder: order,
        pools,
      }),
    ).toMatchObject({ modelId: "luna@med", pool: "codex-5h" });

    const handoff = await applyResourceFailureHandoff({
      trigger: "capacity",
      state_summary: "worker stopped at model capacity; drift preserved",
      reason: "Selected model is at capacity",
      currentModelId: "terra@med",
      currentPool: "codex-5h",
      rosterOrder: order,
      pools,
      now,
      step: "S2",
    });

    expect(handoff.kind).toBe("relay");
    if (handoff.kind !== "relay") return;
    expect(handoff.nextBaton).toMatchObject({
      modelId: "luna@med",
      pool: "codex-5h",
    });
    expect(handoff.ledgerEntry?.trigger).toBe("capacity");
  });

  it("uses each capacity candidate's landed-route conflict set", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: terra@med → luna@med",
    );
    const pools = [
      {
        id: "codex-5h" as const,
        status: "live" as const,
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        models: ["terra@med", "luna@med"],
      },
    ];

    expect(
      selectCapacityRelayBaton({
        currentModelId: "terra@med",
        currentPool: "codex-5h",
        rosterOrder: order,
        pools,
        reviewerSlugsForCandidate: (candidate) =>
          candidate.id === "luna@med" ? ["gpt-5.6-luna"] : [],
      }),
    ).toBeUndefined();
  });

  it("recognizes only model-capacity fingerprints and leaves quota plus ordinary 5xx to retry", () => {
    const capacity = new CapacityRelayError("Selected model is at capacity");
    expect(isCapacityRelayError(capacity)).toBe(true);
    expect(isCapacityRelayError(new Error("Selected model is at capacity"))).toBe(true);
    expect(isCapacityRelayError(new Error("HTTP 429 rate limit exceeded"))).toBe(false);
    expect(isCapacityRelayError(new Error("HTTP 503 service overloaded"))).toBe(false);
    expect(isCapacityRelayError(new Error("gateway returned 503"))).toBe(false);
    expect(isCapacityRelayError(new Error("worker queue is at capacity"))).toBe(false);
  });

  it("wires a first-leg capacity failure through the production family call shape to the next same-pool checkpoint", async () => {
    async function runCapacityCase(): Promise<{ readonly coderModels: readonly string[]; readonly handoff: unknown }> {
      const worktree: WorktreeHandle = {
        branch: "feat/787-capacity-relay-test",
        base: "main",
        path: mkdtempSync(join(tmpdir(), "relay-787-capacity-")),
      };
      const coderModels: string[] = [];
      class CapacityBackend implements Backend {
        async smokeModelRoute(route: any): Promise<any> {
          const { smokeRouteModels } = await import("../../src/modelRoutes.js");
          return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
        }
        async findResumeState(): Promise<undefined> { return undefined; }
        async resumeSession(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async fetchIssueMeta(n: number): Promise<IssueMeta> {
          return {
            number: n, isReadyForAgent: true, hasSubIssues: false, isClosed: false,
            openBlockedBy: [], body: "Coder-Rec: terra@med → luna@med",
          };
        }
        async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
          return { number: n, body: "Coder-Rec: terra@med → luna@med", comments: [], agentBrief: "" };
        }
        async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
        async writeSnapshot(): Promise<void> {}
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if (spec.kind === "coder" && spec.id === "S2") {
            coderModels.push(spec.model);
            if (spec.model === "gpt-5.6-terra") {
              return { kind: "failed", reason: "Selected model is at capacity" };
            }
            return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
          }
          if (spec.kind === "reviewer") {
            return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
          }
          if (spec.kind === "ship") {
            return { kind: "completed", output: { kind: "ship", branch: worktree.branch, status: "pushed" } };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          if (skeleton !== undefined) return skeleton;
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
      }

      const previous = process.env.ORCHESTRATOR_CODER_MODEL;
      process.env.ORCHESTRATOR_CODER_MODEL = "gpt-5.6-terra";
      try {
        const result = await runOrchestrator({
          issueNumber: 787,
          backend: new CapacityBackend(),
          now: () => now,
          family: {
            parentIssue: 686,
            familyBase: "feat/686-family-base",
            mergedBlockers: [],
          },
        });
        expect(result.status, JSON.stringify(result, null, 2)).not.toBe("error");
        return {
          coderModels,
          handoff: result.stepLedger.find((entry) => entry.event === "relay_baton_handoff"),
        };
      } finally {
        if (previous === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
        else process.env.ORCHESTRATOR_CODER_MODEL = previous;
        rmSync(worktree.path, { recursive: true, force: true });
      }
    }

    const firstLeg = await runCapacityCase();
    expect(firstLeg.coderModels).toEqual(["gpt-5.6-terra", "gpt-5.6-luna"]);
    expect(firstLeg.handoff).toMatchObject({
      trigger: "capacity",
      toModelId: "luna@med",
      toPool: "codex-5h",
    });
  });

  it("keeps an S5 wall relay on the coder-fix slot", async () => {
    const worktree: WorktreeHandle = {
      branch: "fix/873-s5-coder-fix-relay",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "relay-873-s5-coder-fix-")),
    };
    const coderFixModels: string[] = [];
    const blockingFinding = {
      severity: "medium" as const,
      category: "correctness",
      claim_quote: "needs one repair pass",
      location: "runner.ts:1",
      suggested_fix: "repair it",
      action: "fix_now" as const,
    };

    class CoderFixCapacityBackend implements Backend {
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> { return undefined; }
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return {
          number: n,
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
          comments: [],
          agentBrief: "",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "reviewer" && spec.id === "S3") {
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [blockingFinding], findingsCount: 1 },
          };
        }
        if (spec.kind === "coder" && spec.id === "S5") {
          coderFixModels.push(spec.model);
          if (spec.model === "gpt-5.6-terra") {
            return { kind: "failed", reason: "Selected model is at capacity" };
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer" && spec.id === "S6") {
          return {
            kind: "completed",
            output: {
              kind: "reviewer", findings: [], findingsCount: 0,
              priorFindingDispositions: [{
                identityKey: "correctness|runner.ts:1|needs one repair pass",
                status: "verified-closed",
              }],
            },
          };
        }
        if (spec.kind === "reviewer") {
          return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: { kind: "ship", branch: worktree.branch, status: "pushed" },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
    }

    const previousCoder = process.env.ORCHESTRATOR_CODER_MODEL;
    const previousCoderFix = process.env.ORCHESTRATOR_CODER_FIX_MODEL;
    const previousReviewer = process.env.ORCHESTRATOR_REVIEWER_MODEL;
    process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
    process.env.ORCHESTRATOR_CODER_FIX_MODEL = "gpt-5.6-terra";
    process.env.ORCHESTRATOR_REVIEWER_MODEL = "opus";
    try {
      const result = await runOrchestrator({
        issueNumber: 873,
        backend: new CoderFixCapacityBackend(),
        relayPools: [{
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
        }],
        now: () => now,
      });

      expect(result.status, JSON.stringify(result, null, 2)).toBe("success");
      expect(coderFixModels).toEqual(["gpt-5.6-terra", "gpt-5.6-luna"]);
      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        step: "S5",
        fromModelId: "terra@med",
        toModelId: "luna@med",
        toPool: "codex-5h",
      }));
    } finally {
      if (previousCoder === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
      else process.env.ORCHESTRATOR_CODER_MODEL = previousCoder;
      if (previousCoderFix === undefined) delete process.env.ORCHESTRATOR_CODER_FIX_MODEL;
      else process.env.ORCHESTRATOR_CODER_FIX_MODEL = previousCoderFix;
      if (previousReviewer === undefined) delete process.env.ORCHESTRATOR_REVIEWER_MODEL;
      else process.env.ORCHESTRATOR_REVIEWER_MODEL = previousReviewer;
      rmSync(worktree.path, { recursive: true, force: true });
    }
  });

  it.each(["S3", "S6"] as const)(
    "uses the reviewer pool and next reviewer baton for first-leg %s capacity",
    async (capacityStep) => {
      const worktree: WorktreeHandle = {
        branch: `feat/787-${capacityStep.toLowerCase()}-capacity-test`,
        base: "main",
        path: mkdtempSync(join(tmpdir(), "relay-787-reviewer-capacity-")),
      };
      const reviewerModels: string[] = [];
      const blockingFinding = {
        severity: "medium" as const,
        category: "correctness",
        claim_quote: "needs one repair pass",
        location: "runner.ts:1",
        suggested_fix: "repair it",
        action: "fix_now" as const,
      };
      class ReviewerCapacityBackend implements Backend {
        async smokeModelRoute(route: any): Promise<any> {
          const { smokeRouteModels } = await import("../../src/modelRoutes.js");
          return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
        }
        async findResumeState(): Promise<undefined> { return undefined; }
        async resumeSession(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async fetchIssueMeta(n: number): Promise<IssueMeta> {
          return {
            number: n,
            isReadyForAgent: true,
            hasSubIssues: false,
            isClosed: false,
            openBlockedBy: [],
            body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
          };
        }
        async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
          return {
            number: n,
            body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
            comments: [],
            agentBrief: "",
          };
        }
        async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
        async writeSnapshot(): Promise<void> {}
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if (spec.kind === "reviewer") {
            reviewerModels.push(`${spec.id}:${spec.model}`);
            if (spec.id === capacityStep && spec.model === "gpt-5.6-terra") {
              return { kind: "failed", reason: "Selected model is at capacity" };
            }
            if (spec.id === "S3" && capacityStep === "S6") {
              return {
                kind: "completed",
                output: { kind: "reviewer", findings: [blockingFinding], findingsCount: 1 },
              };
            }
            if (spec.id === "S6" && capacityStep === "S6") {
              return {
                kind: "completed",
                output: {
                  kind: "reviewer", findings: [], findingsCount: 0,
                  priorFindingDispositions: [
                    {
                      identityKey: "correctness|runner.ts:1|needs one repair pass",
                      status: "verified-closed",
                    },
                  ],
                },
              };
            }
            return { kind: "completed", output: { kind: "reviewer", findings: [], findingsCount: 0 } };
          }
          if (spec.kind === "coder") {
            return {
              kind: "completed",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            };
          }
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: { kind: "ship", branch: worktree.branch, status: "pushed" },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          if (skeleton !== undefined) return skeleton;
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
      }

      const previousCoder = process.env.ORCHESTRATOR_CODER_MODEL;
      const previousReviewer = process.env.ORCHESTRATOR_REVIEWER_MODEL;
      process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
      process.env.ORCHESTRATOR_REVIEWER_MODEL = "gpt-5.6-terra";
      try {
        const result = await runOrchestrator({
          issueNumber: 787,
          backend: new ReviewerCapacityBackend(),
          now: () => now,
          family: {
            parentIssue: 686,
            familyBase: "feat/686-family-base",
            mergedBlockers: [],
          },
        });

        expect(result.status, JSON.stringify(result, null, 2)).not.toBe("error");
        expect(reviewerModels).toContain(`${capacityStep}:gpt-5.6-luna`);
        expect(
          result.stepLedger.find(
            (entry) =>
              entry.event === "relay_baton_handoff" && entry.step === capacityStep,
          ),
        ).toMatchObject({
          trigger: "capacity",
          fromModelId: "terra@med",
          fromPool: "codex-5h",
          toModelId: "luna@med",
          toPool: "codex-5h",
        });
      } finally {
        if (previousCoder === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
        else process.env.ORCHESTRATOR_CODER_MODEL = previousCoder;
        if (previousReviewer === undefined) delete process.env.ORCHESTRATOR_REVIEWER_MODEL;
        else process.env.ORCHESTRATOR_REVIEWER_MODEL = previousReviewer;
        rmSync(worktree.path, { recursive: true, force: true });
      }
    },
  );

  it("keeps pre-capacity trigger rows readable when resuming a relay", () => {
    const legacyQuotaWall = {
      event: "relay_baton_handoff" as const,
      trigger: "quota_wall" as const,
      state_summary: "legacy baton state",
      fromModelId: "grok-4.5",
      fromPool: "grok-build" as const,
      toModelId: "terra@med",
      toPool: "codex-5h" as const,
      step: "S2" as const,
      ts: now.toISOString(),
    };
    expect(resumeRelayFromLedger([legacyQuotaWall], "S2")).toMatchObject({
      trigger: "quota_wall",
      state_summary: "legacy baton state",
      toModelId: "terra@med",
    });
  });
});

describe("#686 three handoff triggers", () => {
  const now = new Date("2026-07-10T12:00:00.000Z");

  it("probe 429 → preserve worktree, record interrupt (no kill, no reset)", async () => {
    const killPidTree = vi.fn();
    const result = await decideRelayAfterIdle({
      probeKind: "quota_limited",
      resetAt: new Date(now.getTime() + 45 * 60 * 1000),
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med → luna@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt: new Date(now.getTime() + 45 * 60 * 1000),
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "cursor",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      workerPid: 4242,
      killPidTree,
    });
    expect(result.kind).toBe("relay");
    if (result.kind !== "relay") return;
    expect(result.preserveWorktree).toBe(true);
    expect(result.nextBaton).toMatchObject({
      modelId: "grok-4.5",
      pool: "cursor",
    });
    expect(killPidTree).not.toHaveBeenCalled();
  });

  it("hang-with-live-pool → kill pid tree then relay (not same-role retry)", async () => {
    const killPidTree = vi.fn();
    const result = await decideRelayAfterIdle({
      probeKind: "ok",
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med → luna@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
        },
      ],
      workerPid: 99,
      killPidTree,
    });
    expect(result.kind).toBe("relay");
    if (result.kind !== "relay") return;
    expect(result.preserveWorktree).toBe(true);
    expect(result.trigger).toBe("hang_with_live_pool");
    expect(killPidTree).toHaveBeenCalledWith(99);
    expect(result.nextBaton?.modelId).toBe("terra@med");
  });

  it("self-reported blocked relay tag → relay handoff preserving worktree", async () => {
    const resetBeforeRetry = vi.fn();
    const parsed = parseRelayTag(
      `<relay>{"blocked":{"reason":"stuck on design","state_summary":"mid-apply","remaining":"schema decision"}}</relay>`,
    );
    expect(parsed.kind).toBe("blocked");
    const handoff = await applyResourceFailureHandoff({
      trigger: "self_reported_blocked",
      state_summary:
        parsed.kind === "blocked" ? parsed.state_summary : "",
      remaining: parsed.kind === "blocked" ? parsed.remaining : undefined,
      reason: parsed.kind === "blocked" ? parsed.reason : undefined,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med → luna@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med"],
        },
      ],
      resetBeforeRetry,
      now: now,
    });
    expect(handoff.kind).toBe("relay");
    expect(handoff.preserveWorktree).toBe(true);
    expect(resetBeforeRetry).not.toHaveBeenCalled();
  });
});

describe("#686 resource failure NEVER resets worktree (#661 boundary)", () => {
  it("resource failure path never invokes resetBeforeRetry (negative)", async () => {
    const resetBeforeRetry = vi.fn(async () => {
      throw new Error("reset must not run on resource failure");
    });
    const handoff = await applyResourceFailureHandoff({
      trigger: "quota_wall",
      state_summary: "uncommitted drift mid-build",
      remaining: "finish apply + tests",
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med"],
        },
      ],
      resetBeforeRetry,
      now: new Date("2026-07-10T12:00:00.000Z"),
    });
    expect(handoff.kind).toBe("relay");
    expect(handoff.preserveWorktree).toBe(true);
    expect(resetBeforeRetry).not.toHaveBeenCalled();
  });
});

describe("#686 state_summary ledger + next-baton parameter file", () => {
  let tmp: string | undefined;
  afterEach(() => {
    if (tmp !== undefined) {
      rmSync(tmp, { recursive: true, force: true });
      tmp = undefined;
    }
  });

  it("writes state_summary into ledger and forwards as .relay-focus.md", () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-"));
    const now = new Date("2026-07-10T12:00:00.000Z");
    const entry = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary: "142 tests pending, apply half-done",
      remaining: "clear reds then 收口",
      fromModelId: "grok-4.5",
      fromPool: "grok-build",
      toModelId: "luna@med",
      toPool: "codex-5h",
      step: "S2",
      now,
    });
    expect(entry).toMatchObject({
      event: "relay_baton_handoff",
      state_summary: "142 tests pending, apply half-done",
      remaining: "clear reds then 收口",
      fromModelId: "grok-4.5",
      toModelId: "luna@med",
    } satisfies Partial<RelayHandoffLedgerEvent>);

    const focusPath = buildRelayFocusFile(tmp, entry);
    expect(focusPath).toBe(join(tmp, RELAY_FOCUS_FILENAME));
    const body = readFileSync(focusPath, "utf8");
    expect(body).toContain("142 tests pending, apply half-done");
    expect(body).toContain("luna@med");
    expect(body).toContain("clear reds then 收口");
  });

  it("excludes promoted .relay-focus.md from git status", () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-exclude-focus-"));
    execFileSync("git", ["init"], { cwd: tmp, stdio: "ignore" });
    const entry = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary: "relay focus",
      remaining: "continue",
      fromModelId: "grok-4.5",
      fromPool: "grok-build",
      toModelId: "luna@med",
      toPool: "codex-5h",
      step: "S2",
      now: new Date("2026-07-10T12:00:00.000Z"),
    });

    buildRelayFocusFile(tmp, entry);

    expect(
      execFileSync("git", ["status", "--porcelain"], { cwd: tmp, encoding: "utf8" }),
    ).toBe("");
  });

  it("keeps durable baton A's focus consumable when baton B's ledger write fails", () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-atomic-focus-"));
    const batonA = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall", state_summary: "A durable", remaining: "finish A",
      fromModelId: "grok-4.5", fromPool: "grok-build", toModelId: "terra@med",
      toPool: "codex-5h", step: "S2", now: new Date("2026-07-10T12:00:00.000Z"),
    });
    const focusA = stageRelayFocusFile(tmp, batonA);
    focusA.commit(); // ledger A committed before the staged focus is promoted.

    const batonB = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall", state_summary: "B must not replace A", remaining: "finish B",
      fromModelId: "terra@med", fromPool: "codex-5h", toModelId: "luna@med",
      toPool: "codex-5h", step: "S2", now: new Date("2026-07-10T12:30:00.000Z"),
    });
    const focusB = stageRelayFocusFile(tmp, batonB);
    // Simulate the only failed operation: B's durable ledger append. Its staged
    // file must be discarded, never promoted or allowed to erase A's baton.
    focusB.discard();

    const durableFocus = readFileSync(join(tmp, RELAY_FOCUS_FILENAME), "utf8");
    expect(durableFocus).toContain("A durable");
    expect(durableFocus).not.toContain("B must not replace A");
  });

  it("resume can continue from any baton interrupt via ledger", () => {
    const ledger: RelayHandoffLedgerEvent[] = [
      buildRelayHandoffLedgerEntry({
        trigger: "quota_wall",
        state_summary: "baton1 mid-build",
        remaining: "clear",
        fromModelId: "grok-4.5",
        fromPool: "grok-build",
        toModelId: "terra@med",
        toPool: "codex-5h",
        step: "S2",
        now: new Date("2026-07-10T12:00:00.000Z"),
      }),
      buildRelayHandoffLedgerEntry({
        trigger: "hang_with_live_pool",
        state_summary: "baton2 mid-clear",
        remaining: "收口",
        fromModelId: "terra@med",
        fromPool: "codex-5h",
        toModelId: "luna@med",
        toPool: "codex-5h",
        step: "S2",
        now: new Date("2026-07-10T12:30:00.000Z"),
      }),
    ];
    const resume = resumeRelayFromLedger(ledger, "S2");
    expect(resume).toMatchObject({
      state_summary: "baton2 mid-clear",
      toModelId: "luna@med",
      remaining: "收口",
    });
  });

  it("does not replay an S2 baton while resuming a later S9 slot", () => {
    const s2Relay = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall", state_summary: "S2 handoff", fromModelId: "a",
      fromPool: "cursor", toModelId: "b", toPool: "codex-5h", step: "S2", now: new Date("2026-07-10T12:00:00.000Z"),
    });
    expect(resumeRelayFromLedger([s2Relay, { step: "S2" }, { step: "S9" }], "S9")).toBeUndefined();
  });
});

describe("#686 fork at #683 quota disposition point", () => {
  it("composes decideIdleAfterProbe(wait_for_reset) → three-tier park/relay", () => {
    const now = new Date("2026-07-10T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 45 * 60 * 1000);
    const idle = decideIdleAfterProbe("grok", {
      kind: "quota_limited",
      resetAt,
      detail: "402",
    });
    expect(idle.kind).toBe("wait_for_reset");
    if (idle.kind !== "wait_for_reset") return;

    const withinT = forkQuotaWallAt683Point({
      disposition: {
        ...idle,
        resetAt: new Date(now.getTime() + 10 * 60 * 1000),
      },
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med",
      ),
      pools: [
        {
          id: "cursor",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
    });
    expect(withinT.tier).toBe("park");

    const beyondT = forkQuotaWallAt683Point({
      disposition: idle,
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med",
      ),
      pools: [
        {
          id: "cursor",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
    });
    expect(beyondT.tier).toBe("relay");
    expect(beyondT.nextBaton).toMatchObject({
      modelId: "grok-4.5",
      pool: "cursor",
    });
    expect(beyondT.ledgerEntry?.event).toBe("relay_baton_handoff");
  });
});

describe("#686 relay chain ends at normal review gate", () => {
  it("closing baton (no relay tag / normal terminal) → review gate, no exemption", () => {
    // 收口者无 relay tag — normal coder terminal is the exit.
    expect(parseRelayTag("CODER_STEP_COMPLETE\ncommitted ok").kind).toBe(
      "malformed",
    );
    expect(
      isRelayChainReadyForReviewGate({
        closingBatonCompleted: true,
        emittedRelayTag: false,
      }),
    ).toBe(true);
    // A phase_complete clear is NOT the review-gate exemption — it only
    // hands to the closing baton; the gate still requires a normal terminal.
    expect(
      isRelayChainReadyForReviewGate({
        closingBatonCompleted: false,
        emittedRelayTag: true,
        lastRelayPhase: "clear",
      }),
    ).toBe(false);
  });
});

/**
 * #686 R1 — behavior through the REAL runner park sites (not a parallel seam).
 * Seams: parkOrRelayQuotaWall at S9 (and S2/S7 siblings) + mechanical-retry
 * exhaustion → same relay decision.
 */
describe("#686 R1 runner park sites: park vs relay (e2e)", () => {
  const NOW = new Date("2026-07-10T12:00:00.000Z");
  function quotaWaitError(
    step: "S9" | "S3" | "S2",
    resetAt: Date,
    pool = "grok",
  ): QuotaWaitForResetError {
    return new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: pool as "grok" | "zai",
        resetAt,
        reason: "quota limited (429); wait for reset",
      },
      applied: {
        killed: false,
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: pool as "grok" | "zai",
          resetAt: resetAt.toISOString(),
          reason: "quota limited (429); wait for reset",
          step,
          workerPid: 9001,
          ts: NOW.toISOString(),
        },
      },
      pool: pool as "grok" | "zai",
      probe: { kind: "quota_limited", resetAt, detail: "429" },
    });
  }

  let tmp: string | undefined;
  afterEach(() => {
    if (tmp !== undefined) {
      rmSync(tmp, { recursive: true, force: true });
      tmp = undefined;
    }
  });

  it("mechanical-retry exhaustion with live baton → relay (not durable abort)", async () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-exhaust-"));
    const worktree: WorktreeHandle = {
      branch: "feat/686-relay-exhaust",
      base: "main",
      path: tmp,
    };
    let coderFails = 0;
    let coderModels: string[] = [];
    const reviewerDispatches: Array<{ spec: WorkerSpec; ctx: DispatchContext }> = [];
    class ExhaustBackend implements Backend {
      public ledgerWrites: PersistentLedgerEntry[] = [];
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return {
          number: n,
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
          comments: [],
          agentBrief: "",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        this.ledgerWrites.push(entry);
      }
      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          coderModels.push(spec.model);
          coderFails += 1;
          // Wall-hit baton keeps failing; relayed baton succeeds.
          if (spec.model === "grok-4.5") {
            return { kind: "failed", reason: "process crashed mid-build" };
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer") {
          reviewerDispatches.push({ spec, ctx });
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [], findingsCount: 0 },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: worktree.branch,
              status: "pushed",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
    }
    const backend = new ExhaustBackend();
    const result = await runOrchestrator({
      issueNumber: 686,
      backend,
      relayPools: [
        {
          id: "grok-build",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "cursor",
          status: "dead",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
        },
      ],
      now: () => NOW,
    });

    const handoff = result.stepLedger.find(
      (e) => e.event === "relay_baton_handoff",
    );
    expect(handoff).toMatchObject({
      event: "relay_baton_handoff",
      trigger: "mechanical_retry_exhausted",
      toModelId: "terra@med",
    });
    expect(existsSync(join(tmp, RELAY_FOCUS_FILENAME))).toBe(true);
    // #767's final roster advance selects the Terra coding baton.
    expect(coderModels).toContain("gpt-5.6-terra");
    // The S2 relay belongs only to that coder step. The normal S3 reviewer must
    // select its own channel from its reviewer route, not inherit the coder's
    // billing pool or baton brief.
    expect(reviewerDispatches).toHaveLength(1);
    expect(reviewerDispatches[0]?.ctx.billingPool).toBeUndefined();
    expect(reviewerDispatches[0]?.ctx.relayFocusPath).toBeUndefined();
    expect(result.status).not.toBe("error");
  });

  it("S2 quota relay on normal route selects Terra while Sol remains reviewer", async () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-sol-normal-"));
    const worktree: WorktreeHandle = {
      branch: "feat/686-sol-normal",
      base: "main",
      path: tmp,
    };
    const resetAt = new Date(NOW.getTime() + 45 * 60 * 1000);
    const coderModels: string[] = [];
    const reviewerModels: string[] = [];

    class SolRelayBackend implements Backend {
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med",
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return {
          number: n,
          body: "Coder-Rec: grok-4.5 → terra@med",
          comments: [],
          agentBrief: "",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          coderModels.push(spec.model);
          if (spec.model === "grok-4.5") {
            throw quotaWaitError("S2", resetAt);
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer") {
          reviewerModels.push(spec.model);
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [], findingsCount: 0 },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: worktree.branch,
              status: "pushed",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
    }

    const previousRoute = process.env.ORCHESTRATOR_ROUTE;
    const previousCoder = process.env.ORCHESTRATOR_CODER_MODEL;
    const previousCmrReview = process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
    process.env.ORCHESTRATOR_ROUTE = "normal";
    process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
    process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = "opus,agy";
    try {
      const result = await runOrchestrator({
        issueNumber: 686,
        backend: new SolRelayBackend(),
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
            resetAt,
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["grok-4.5"],
          },
          {
            id: "codex-5h",
            status: "live",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["terra@med"],
          },
        ],
        now: () => NOW,
      });

      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        trigger: "quota_wall",
        toModelId: "terra@med",
        toPool: "codex-5h",
        step: "S2",
      }));
      expect(coderModels).toEqual(["grok-4.5", "gpt-5.6-terra"]);
      expect(reviewerModels).toContain("gpt-5.6-sol");
    } finally {
      if (previousRoute === undefined) delete process.env.ORCHESTRATOR_ROUTE;
      else process.env.ORCHESTRATOR_ROUTE = previousRoute;
      if (previousCoder === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
      else process.env.ORCHESTRATOR_CODER_MODEL = previousCoder;
      if (previousCmrReview === undefined) delete process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
      else process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = previousCmrReview;
    }
  });

  it("S3 reviewer quota relay rejects Terra when Terra already owns the coder slot", async () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-sol-reviewer-wall-"));
    const worktree: WorktreeHandle = {
      branch: "feat/686-sol-reviewer-wall",
      base: "main",
      path: tmp,
    };
    const resetAt = new Date(NOW.getTime() + 45 * 60 * 1000);
    const reviewerModels: string[] = [];

    class SolReviewerWallBackend implements Backend {
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med",
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return {
          number: n,
          body: "Coder-Rec: grok-4.5 → terra@med",
          comments: [],
          agentBrief: "",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          if (spec.model === "grok-4.5") {
            throw quotaWaitError("S2", resetAt);
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer" && spec.id === "S3") {
          reviewerModels.push(spec.model);
          throw quotaWaitError("S3", resetAt);
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
    }

    const previousRoute = process.env.ORCHESTRATOR_ROUTE;
    const previousCoder = process.env.ORCHESTRATOR_CODER_MODEL;
    const previousCmrReview = process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
    process.env.ORCHESTRATOR_ROUTE = "normal";
    process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
    process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = "opus,agy";
    try {
      const result = await runOrchestrator({
        issueNumber: 686,
        backend: new SolReviewerWallBackend(),
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
            resetAt,
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["grok-4.5"],
          },
          {
            id: "codex-5h",
            status: "live",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["terra@med"],
          },
        ],
        now: () => NOW,
      });

      expect(result.status).toBe("escalate");
      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "quota_wait_for_reset",
        step: "S3",
      }));
      expect(result.stepLedger).not.toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        step: "S3",
      }));
      expect(reviewerModels).toEqual(["gpt-5.6-sol"]);
    } finally {
      if (previousRoute === undefined) delete process.env.ORCHESTRATOR_ROUTE;
      else process.env.ORCHESTRATOR_ROUTE = previousRoute;
      if (previousCoder === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
      else process.env.ORCHESTRATOR_CODER_MODEL = previousCoder;
      if (previousCmrReview === undefined) delete process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
      else process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = previousCmrReview;
    }
  });

  it("S3 reviewer quota relay admits Terra when the coder slot is not Terra", async () => {
    tmp = mkdtempSync(join(tmpdir(), "relay-686-sol-reviewer-wall-positive-"));
    const worktree: WorktreeHandle = {
      branch: "feat/686-sol-reviewer-wall-positive",
      base: "main",
      path: tmp,
    };
    const resetAt = new Date(NOW.getTime() + 45 * 60 * 1000);
    const reviewerModels: string[] = [];
    const previousReviewer = process.env.ORCHESTRATOR_REVIEWER_MODEL;
    process.env.ORCHESTRATOR_REVIEWER_MODEL = "opus";

    class SolReviewerWallPositiveBackend implements Backend {
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med",
        };
      }
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return {
          number: n,
          body: "Coder-Rec: grok-4.5 → terra@med",
          comments: [],
          agentBrief: "",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer" && spec.id === "S3") {
          reviewerModels.push(spec.model);
          if (spec.model === "opus") throw quotaWaitError("S3", resetAt);
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [], findingsCount: 0 },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: worktree.branch,
              status: "pushed",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
    }

    const previousRoute = process.env.ORCHESTRATOR_ROUTE;
    const previousCoder = process.env.ORCHESTRATOR_CODER_MODEL;
    const previousCmrReview = process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
    process.env.ORCHESTRATOR_ROUTE = "normal";
    process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
    process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = "opus,agy";
    try {
      const result = await runOrchestrator({
        issueNumber: 686,
        backend: new SolReviewerWallPositiveBackend(),
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
            resetAt,
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["grok-4.5"],
          },
          {
            id: "codex-5h",
            status: "live",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["terra@med"],
          },
        ],
        now: () => NOW,
      });

      expect(result.status).toBe("success");
      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        toModelId: "terra@med",
        toPool: "codex-5h",
        step: "S3",
      }));
      expect(reviewerModels).toEqual(["opus", "gpt-5.6-terra"]);
    } finally {
      if (previousRoute === undefined) delete process.env.ORCHESTRATOR_ROUTE;
      else process.env.ORCHESTRATOR_ROUTE = previousRoute;
      if (previousCoder === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
      else process.env.ORCHESTRATOR_CODER_MODEL = previousCoder;
      if (previousCmrReview === undefined) delete process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS;
      else process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS = previousCmrReview;
      if (previousReviewer === undefined) delete process.env.ORCHESTRATOR_REVIEWER_MODEL;
      else process.env.ORCHESTRATOR_REVIEWER_MODEL = previousReviewer;
    }
  });
});

describe("#686 reviewer relay candidate conflict set", () => {
  const sol = lookupCoderRosterEntry("sol@med")!;

  it.each(["S3", "S6"] as const)(
    "%s rejects sol when any complete-route CMR or verify leg shares its checkpoint",
    (wallStep) => {
      const route = resolveRouteModels("normal", {
        cmrCompleteness: sol.slug,
        cmrCorrectness: sol.slug,
        verify: sol.slug,
      }, {
        cmrReview: ["opus", "gpt-5.6-sol", "agy"],
      });

      const conflicts = relayCandidateConflictSlugs(route, sol, wallStep);

      expect(conflicts).toEqual(
        expect.arrayContaining([
          route.slots.coder,
          route.slots.cmrCompleteness,
          route.slots.cmrCorrectness,
          route.slots.verify,
          ...route.legCollections.cmrReview.map((leg) => leg.slug),
        ]),
      );
      expect(poolSeparationViolation(sol, conflicts)).toMatch(
        /must not double as.*reviewer/i,
      );
    },
  );

  it.each([
    "sol@med",
    "grok-4.5",
  ] as const)(
    "allows %s when its only matching slug is the reviewer slot it replaces",
    (candidateId) => {
      const candidate = lookupCoderRosterEntry(candidateId)!;
      const route = resolveRouteModels("normal", {
        reviewer: candidate.slug,
        cmrCompleteness: "opus",
        cmrCorrectness: "opus",
        verify: "opus",
      }, {
        cmrReview: ["opus", "agy"],
      });

      for (const wallStep of ["S3", "S6"] as const) {
        const conflicts = relayCandidateConflictSlugs(route, candidate, wallStep);
        expect(conflicts).not.toContain(candidate.slug);
        expect(poolSeparationViolation(candidate, conflicts)).toBeUndefined();
      }
    },
  );
});

/**
 * #686 R2 — production-seam fixes from fresh reviewer (P0–P3).
 */
describe("#686 R2 production seams", () => {
  const NOW = new Date("2026-07-10T12:00:00.000Z");

  it("P0: resume with pending relay_baton_handoff preserves the scene", async () => {
    const tmp = mkdtempSync(join(tmpdir(), "relay-686-r2-p0-"));
    try {
      const worktree: WorktreeHandle = {
        branch: "feat/686-r2-p0",
        base: "main",
        path: tmp,
      };
      // Seed a focus file that destructive cleanup would destroy.
      writeFileSync(
        join(tmp, RELAY_FOCUS_FILENAME),
        "# Relay baton handoff\n\n## state_summary\n\npreserve me\n",
        "utf8",
      );
      writeFileSync(join(tmp, "uncommitted-baton.txt"), "drift payload\n", "utf8");

      const handoffTs = "2026-07-10T11:00:00.000Z";
      const prior: PersistentLedgerEntry[] = [
        {
          step: "S0",
          sessionId: "s",
          prompt_hash: "h",
          branchHEAD: "deadbeef",
          ts: handoffTs,
        },
        {
          step: "S1",
          sessionId: "s",
          prompt_hash: "h",
          branchHEAD: "deadbeef",
          ts: handoffTs,
        },
        {
          step: "S2",
          sessionId: "s",
          prompt_hash: "h",
          branchHEAD: "deadbeef",
          ts: handoffTs,
          event: "relay_baton_handoff",
          trigger: "quota_wall",
          state_summary: "preserve me",
          fromModelId: "grok-4.5",
          fromPool: "grok-build",
          toModelId: "terra@med",
          toPool: "codex-5h",
        },
      ];

      class ResumeBackend implements Backend {
        async smokeModelRoute(route: any): Promise<any> {
          const { smokeRouteModels } = await import("../../src/modelRoutes.js");
          return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
        }
        async findResumeState(): Promise<ResumeState> {
          return {
            worktree,
            stateDir: join(tmp, "..", ".ledger-r2-p0"),
            ledger: prior,
          };
        }
        async resumeSession(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async fetchIssueMeta(n: number): Promise<IssueMeta> {
          return {
            number: n,
            isReadyForAgent: true,
            hasSubIssues: false,
            isClosed: false,
            openBlockedBy: [],
            body: "Coder-Rec: grok-4.5 → terra@med",
          };
        }
        async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
          return {
            number: n,
            body: "Coder-Rec: grok-4.5 → terra@med",
            comments: [],
            agentBrief: "",
          };
        }
        async prepareWorktree(): Promise<WorktreeHandle> {
          return worktree;
        }
        async writeSnapshot(): Promise<void> {}
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if (spec.kind === "coder") {
            // Prove baton applied (terra slug) and focus survived.
            expect(existsSync(join(tmp, RELAY_FOCUS_FILENAME))).toBe(true);
            expect(existsSync(join(tmp, "uncommitted-baton.txt"))).toBe(true);
            expect(spec.model).toBe("gpt-5.6-terra");
            return {
              kind: "completed",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            };
          }
          if (spec.kind === "reviewer") {
            return {
              kind: "completed",
              output: { kind: "reviewer", findings: [], findingsCount: 0 },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          if (skeleton !== undefined) return skeleton;
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: {
                kind: "ship",
                branch: worktree.branch,
                status: "pr_opened",
                pr: "pr://r2-p0",
                prHead: "deadbeef",
              },
            };
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
      }

      const prev = process.env.ORCHESTRATOR_CODER_MODEL;
      process.env.ORCHESTRATOR_CODER_MODEL = "grok-4.5";
      try {
        await runOrchestrator({
          issueNumber: 686,
          backend: new ResumeBackend(),
          now: () => NOW,
        });
      } finally {
        if (prev === undefined) delete process.env.ORCHESTRATOR_CODER_MODEL;
        else process.env.ORCHESTRATOR_CODER_MODEL = prev;
      }
      expect(existsSync(join(tmp, RELAY_FOCUS_FILENAME))).toBe(true);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  it("P1-3: #905 pins grok-4.5 to SuperGrok CLI regardless of pool 换马甲", async () => {
    const {
      resolveModelSlugForPool,
      POOL_DISPATCH_BINDINGS,
    } = await import("../../src/modelRegistry.js");
    expect(POOL_DISPATCH_BINDINGS["grok-build"]).toBe("grok");
    expect(POOL_DISPATCH_BINDINGS.cursor).toBe("cursor");
    expect(resolveModelSlugForPool("grok-4.5", "grok-build").provider).toBe(
      "grok",
    );
    // cursor pool no longer rewrites grok-4.5 onto the cursor channel.
    expect(resolveModelSlugForPool("grok-4.5", "cursor").provider).toBe(
      "grok",
    );
    expect(resolveModelSlugForPool("grok-4.5").provider).toBe("grok");
  });

  it("P1: monitor attribution follows the active billing pool after a relay", () => {
    const stateDir = mkdtempSync(join(tmpdir(), "relay-686-monitor-pool-"));
    try {
      const spawn = buildCliMonitorSpawnSpec({
        backendKind: "real",
        backendOpts: {},
        spec: {
          id: "S2",
          kind: "coder",
          role: "coder",
          host: "codex",
          session: "fresh",
          contextRetention: "retain",
          promptFile: "coder.md",
          completionSignal: "STEP_COMPLETE",
          maxIter: 1,
          model: "grok-4.5",
          soul: "coder",
          toolchain: [],
        },
        ctx: { stateDir, billingPool: "cursor" },
        runnerPath: "/tmp/runner.js",
      });
      expect(spawn?.poolId).toBe("cursor");
    } finally {
      rmSync(stateDir, { recursive: true, force: true });
    }
  });

  it("P2: legacy dispatch forwards relayFocusPath as a run option", async () => {
    let received: { readonly relayFocusPath?: string } | undefined;
    const worktree: WorktreeHandle = {
      branch: "feat/686-focus-forward",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "relay-686-focus-forward-")),
    };
    try {
      const backend = {
        async runStep(
          _spec: unknown,
          _worktree: unknown,
          options: { readonly relayFocusPath?: string },
        ): Promise<StepOutput> {
          received = options;
          return { kind: "coder", committed: true, commitsAdded: 1 };
        },
      } as unknown as Backend;
      await legacyDispatchWorker(backend, {
        id: "S2",
        kind: "coder",
        role: "coder",
        host: "codex",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder.md",
        completionSignal: "STEP_COMPLETE",
        maxIter: 1,
        model: "grok-4.5",
        soul: "coder",
        toolchain: [],
      }, {
        worktree,
        relayFocusPath: join(worktree.path, RELAY_FOCUS_FILENAME),
      });
      expect(received?.relayFocusPath).toBe(join(worktree.path, RELAY_FOCUS_FILENAME));
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
    }
  });

  it("P2: buildDefaultBillingPools does not fabricate live alternate pools", () => {
    const pools = buildDefaultBillingPools({
      limitedPool: "grok-build",
      resetAt: new Date(NOW.getTime() + 45 * 60 * 1000),
    });
    expect(pools.find((p) => p.id === "grok-build")?.status).toBe("limited");
    expect(pools.filter((p) => p.status === "live")).toEqual([]);
    expect(
      hasLiveRelayBaton({
        currentModelId: "grok-4.5",
        currentPool: "grok-build",
        rosterOrder: resolveCoderRecOrder(
          "Coder-Rec: grok-4.5 → terra@med",
        ),
        pools,
      }),
    ).toBe(false);
  });

  it("B3: after wall on A, A is not re-offered as live baton via knownLive smoke", () => {
    // Smoke still marks grok-build as passed; after it walls, the next wall on
    // codex-5h must not promote grok-build back to live (ping-pong until cap).
    const wallHits = new Set<BillingPoolId>(["grok-build"]);
    const pools = resolveRelayPools(
      "codex-5h",
      new Date(NOW.getTime() + 45 * 60 * 1000),
      undefined,
      ["grok-build", "codex-5h"],
      wallHits,
    );
    expect(pools.find((p) => p.id === "codex-5h")?.status).toBe("limited");
    expect(pools.find((p) => p.id === "grok-build")?.status).not.toBe("live");
    const next = selectNextRelayBaton({
      currentModelId: "terra@med",
      currentPool: "codex-5h",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: terra@med → grok-4.5 → luna@med",
      ),
      pools,
    });
    // grok-4.5 only served by wall-hit grok-build; luna also on limited codex-5h.
    expect(next).toBeUndefined();

    // Positive: first wall on A still promotes other smoke-live pools.
    const afterFirst = resolveRelayPools(
      "grok-build",
      new Date(NOW.getTime() + 45 * 60 * 1000),
      undefined,
      ["grok-build", "codex-5h"],
      new Set<BillingPoolId>(["grok-build"]),
    );
    expect(afterFirst.find((p) => p.id === "grok-build")?.status).toBe("limited");
    expect(afterFirst.find((p) => p.id === "codex-5h")?.status).toBe("live");
  });

  it("P2: MAX_RELAY_HANDOFFS counts chain from ledger history", () => {
    const ledger = Array.from({ length: MAX_RELAY_HANDOFFS }, (_, i) => ({
      event: "relay_baton_handoff" as const,
      ts: `2026-07-10T0${i}:00:00.000Z`,
    }));
    expect(countRelayHandoffsInLedger(ledger)).toBe(MAX_RELAY_HANDOFFS);
    expect(canRelayHandoff(ledger)).toBe(false);
    expect(canRelayHandoff(ledger.slice(0, 3))).toBe(true);
  });

  it("P1-5: tryBuildRelayFocusFile fails closed without worktree", () => {
    const entry = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary: "x",
      fromModelId: "grok-4.5",
      fromPool: "grok-build",
      toModelId: "grok-4.5",
      toPool: "cursor",
      now: NOW,
    });
    expect(tryBuildRelayFocusFile(undefined, entry).ok).toBe(false);
  });

  it("P1-2: HangWithLivePoolError preserves its actionable pool facts", () => {
    const err = new HangWithLivePoolError({
      workerPid: 42,
      poolId: "grok-build",
      step: "S2",
    });
    expect(isHangWithLivePoolError(err)).toBe(true);
  });

  it("P1-2: self-reported blocked tag is actionable for production parse", () => {
    const tag = tryParseActionableRelayTag(
      `<relay>{"blocked":{"reason":"design gap","state_summary":"half wired","remaining":"ADR"}}</relay>`,
    );
    expect(tag).toMatchObject({
      kind: "blocked",
      reason: "design gap",
      state_summary: "half wired",
    });
    expect(tryParseActionableRelayTag("no tag")).toBeUndefined();
  });

  it("P1: a sparse worker-log decision_gate durably parks, then an appended answer re-enters the original step", async () => {
    const tmp = mkdtempSync(join(tmpdir(), "relay-826-decision-gate-"));
    const worktree: WorktreeHandle = {
      branch: "fix/826-decision-gate",
      base: "main",
      path: tmp,
    };
    const rawDecisionGate = '{"decision_gate":{},"unexpected_cargo":[1,2,3]}';
    const workerLog = `<relay>${rawDecisionGate}</relay>`;
    const WORKER_SESSION_ID = "relay-826-worker-session";
    const persisted: PersistentLedgerEntry[] = [];
    const resumed: Array<{ step: string; sessionId: string }> = [];
    let monitorPass = 0;
    const backend = {
      async smokeModelRoute(route: any): Promise<any> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      },
      async findResumeState(): Promise<ResumeState | undefined> {
        if (persisted.length === 0) return undefined;
        return { worktree, stateDir: tmp, ledger: persisted };
      },
      async resumeSession(spec: StepSpec, _worktree: WorktreeHandle, sessionId: string): Promise<StepOutput> {
        resumed.push({ step: spec.id, sessionId });
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5",
        };
      },
      async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
        return { number: n, body: "Coder-Rec: grok-4.5", comments: [], agentBrief: "" };
      },
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      },
      async writeSnapshot(): Promise<void> {},
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "reviewer") return { kind: "reviewer", findings: [], findingsCount: 0 };
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        persisted.push(entry);
      },
      resolveCliMonitorDispatch: () => {
        monitorPass += 1;
        if (monitorPass > 1) return undefined;
        return {
        command: process.execPath,
        args: ["-e", `console.log(${JSON.stringify(workerLog)})`],
        logDir: tmp,
        poolId: "grok-build",
        completionSignal: "STEP_COMPLETE",
        stepId: "S2",
        readInstanceId: () => "relay-826-test",
        };
      },
      async awaitMonitoredCliWorker(): Promise<WorkerResult> {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: WORKER_SESSION_ID,
        };
      },
    } as unknown as Backend;
    const spec: WorkerSpec = {
      id: "S2",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      promptFile: "coder.md",
      completionSignal: "STEP_COMPLETE",
      maxIter: 1,
      model: "grok-4.5",
      soul: "coder",
      toolchain: [],
    };
    try {
      await expect(
        dispatchWorkerWithMonitor(backend, spec, {}, undefined, {
          idleThresholdMs: 60_000,
          pollIntervalMs: 5,
          monitorDeps: { readInstanceId: () => "relay-826-test" },
        }),
      ).rejects.toMatchObject({
        name: "SelfReportedRelayError",
        tag: { kind: "decision_gate", state_summary: rawDecisionGate },
        sessionId: WORKER_SESSION_ID,
      });

      monitorPass = 0;

      const first = await runOrchestrator({
        issueNumber: 826,
        backend,
        now: () => NOW,
      });
      expect(first.status).toBe("escalate");
      expect(first.stopSummary).toMatchObject({
        reason: "decision_gate_park",
        summary: expect.stringContaining(rawDecisionGate),
      });
      expect(
        first.stepLedger.find(
          (entry) => entry.step === "S2" && entry.output?.kind === "coder",
        ),
      ).toMatchObject({ sessionId: WORKER_SESSION_ID });
      expect(persisted.at(-1)).toMatchObject({
        step: "S8",
        handoffStatus: "escalate",
        escalationKind: "decision",
      });
      // The decision park must retain the worker's actual provider session,
      // never this orchestration run's fallback UUID.
      expect(
        persisted.filter((entry) => entry.step === "S2").at(-1)?.sessionId,
      ).toBe(WORKER_SESSION_ID);

      persisted.push({
        step: "S2",
        event: "escalation_answered",
        forStep: "S2",
        answer: "choose policy A",
        source: "human",
        sessionId: "human-answer",
        prompt_hash: "answer",
        branchHEAD: "head",
        ts: NOW.toISOString(),
      });

      const second = await runOrchestrator({
        issueNumber: 826,
        backend,
        now: () => NOW,
      });
      expect(second.status).toBe("success");
      expect(resumed).toContainEqual({ step: "S2", sessionId: WORKER_SESSION_ID });
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  it("P3: no-baton park repairHint is byte-identical to #683", async () => {
    const tmp = mkdtempSync(join(tmpdir(), "relay-686-r2-p3-"));
    try {
      const worktree: WorktreeHandle = {
        branch: "feat/686-r2-p3",
        base: "main",
        path: tmp,
      };
      const resetAt = new Date(NOW.getTime() + 45 * 60 * 1000);
      class ParkBackend implements Backend {
        async smokeModelRoute(route: any): Promise<any> {
          const { smokeRouteModels } = await import("../../src/modelRoutes.js");
          return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
        }
        async findResumeState(): Promise<undefined> {
          return undefined;
        }
        async resumeSession(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async fetchIssueMeta(n: number): Promise<IssueMeta> {
          return {
            number: n,
            isReadyForAgent: true,
            hasSubIssues: false,
            isClosed: false,
            openBlockedBy: [],
            body: "Coder-Rec: grok-4.5",
          };
        }
        async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
          return {
            number: n,
            body: "Coder-Rec: grok-4.5",
            comments: [],
            agentBrief: "",
          };
        }
        async prepareWorktree(): Promise<WorktreeHandle> {
          return worktree;
        }
        async writeSnapshot(): Promise<void> {}
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if (spec.kind === "coder" && spec.id === "S2") {
            throw new QuotaWaitForResetError({
              disposition: {
                kind: "wait_for_reset",
                pool: "grok",
                resetAt,
                reason: "quota limited (429); wait for reset",
              },
              applied: {
                killed: false,
                ledgerEntry: {
                  event: "quota_wait_for_reset",
                  pool: "grok",
                  resetAt: resetAt.toISOString(),
                  reason: "quota limited (429); wait for reset",
                  step: "S2",
                  workerPid: 1,
                  ts: NOW.toISOString(),
                },
              },
              pool: "grok",
              probe: { kind: "quota_limited", resetAt, detail: "429" },
            });
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
      }
      // No relayPools → default table has no live batons → park.
      const result = await runOrchestrator({
        issueNumber: 686,
        backend: new ParkBackend(),
        now: () => NOW,
      });
      expect(result.status).toBe("escalate");
      expect(result.stopSummary?.repairHint).toBe(
        "wait for the provider quota to reset, then re-feed — resume re-enters the parked step (auto re-dispatch is #686)",
      );
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });
});
