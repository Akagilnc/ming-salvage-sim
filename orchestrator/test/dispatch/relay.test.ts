import {
  execFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  getCoderRoster,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
  selectCoderRecEntry,
  modelIdForSlug,
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  BillingPoolEntry,
  BillingPoolId,
  PoolTable,
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  CapacityRelayError,
  countRelayHandoffsInLedger,
  forkQuotaWallAt683Point,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  renderEphemeralRelayBrief,
  resumeRelayFromLedger,
  RelayHandoffLedgerEvent,
  QuotaWaitForResetError,
  dispatchWorkerWithMonitor,
  legacyDispatchWorker,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepSpec,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  writeRoutePreset,
} from "./relay.shared.js";
import {
  expectNoRelayFocusFile,
  RELAY_FOCUS_FILENAME,
} from "../helpers/relayFocus.js";

describe("#937 free-log relay parse surface deleted (ID-007/016)", () => {
  it("production module no longer exports parseRelayTag", async () => {
    const relay = await import("../../src/relayDispatch.js");
    expect("parseRelayTag" in relay).toBe(false);
    const src = readFileSync(
      join(import.meta.dirname, "../../src/relayDispatch.ts"),
      "utf8",
    );
    expect(src).not.toMatch(/export function parseRelayTag/);
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
      zai: {
        id: "zai",
        status: "live",
        parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
        models: ["grok-4.5"],
      },
    };
    expect(table["grok-build"]!.parkThresholdMs).toBe(15 * 60 * 1000);
    expect(table.zai!.status).toBe("live");
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

  it("skips non-executable live pools and selects the next executable roster baton", () => {
    const order = resolveCoderRecOrder(
      "Coder-Rec: grok-4.5 → terra@med → luna@med",
    );
    const next = selectNextRelayBaton({
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: order,
      pools: [
        deadPool("grok-build", ["grok-4.5"]),
        livePool("zai", ["grok-4.5", "terra@med"]),
        livePool("codex-5h", ["terra@med", "luna@med"]),
      ],
    });
    expect(next).toEqual({
      modelId: "terra@med",
      slug: "gpt-5.6-terra",
      pool: "codex-5h",
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
        livePool("codex-5h", ["terra@med", "luna@med"]),
      ],
    });
    expect(next).toEqual({
      modelId: "terra@med",
      slug: "gpt-5.6-terra",
      pool: "codex-5h",
    });
  });

  it("#920: roster relay no longer skips a slug that also sits on review seats", () => {
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
    });
    // Pre-#920 reviewerSlugs: ["gpt-5.6-terra"] would skip terra → luna.
    expect(next?.modelId).toBe("terra@med");
    expect(next?.slug).toBe("gpt-5.6-terra");
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
    expect(() => billingPoolFromQuotaPool("retired")).toThrow(/unknown quota pool/);

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
        deadPool("zai", DEFAULT_POOL_MODELS.zai),
        deadPool("codex-5h", DEFAULT_POOL_MODELS["codex-5h"]),
        livePool("claude", DEFAULT_POOL_MODELS.claude),
      ],
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
        deadPool("zai", DEFAULT_POOL_MODELS.zai),
        deadPool("codex-5h", DEFAULT_POOL_MODELS["codex-5h"]),
        livePool("claude", DEFAULT_POOL_MODELS.claude),
      ],
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
    // Sanity: selection only walks live coder roster / Coder-Rec order.
    expect(getCoderRoster().map((e) => e.id)).toEqual(
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

  it("#920: capacity relay picks the next same-pool roster entry without conflict filter", () => {
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

    // Pre-#920 a reviewerSlugsForCandidate collision could veto luna entirely.
    expect(
      selectCapacityRelayBaton({
        currentModelId: "terra@med",
        currentPool: "codex-5h",
        rosterOrder: order,
        pools,
      }),
    ).toMatchObject({ modelId: "luna@med", pool: "codex-5h" });
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
        async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
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
          if ((spec.kind === "reviewer" || spec.kind === "verify")) {
            return { kind: "completed", output: { kind: "judge", status: "converged" } };
          }
          if (spec.kind === "ship") {
            return { kind: "completed", output: { kind: "ship", branch: worktree.branch, status: "pushed" } };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          if (skeleton !== undefined) return skeleton;
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
      }

      try {
        // #936: normal preset already staffs gpt-5.6-terra coder (no env override).
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

  it("NEGATIVE: capacity relay writeLedger failure surfaces record_persist_failed (not capacity class)", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/934-capacity-relay-persist-fail",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "relay-934-capacity-persist-")),
    };

    class CapacityPersistFailBackend implements Backend {
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
          body: "Coder-Rec: terra@med → luna@med",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        if (entry.event === "relay_baton_handoff") {
          throw new Error("disk full on relay handoff");
        }
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          if (spec.model === "gpt-5.6-terra") {
            return { kind: "failed", reason: "Selected model is at capacity" };
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer" || spec.kind === "verify") {
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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

    try {
      const result = await runOrchestrator({
        issueNumber: 934,
        backend: new CapacityPersistFailBackend(),
        now: () => now,
        family: {
          parentIssue: 686,
          familyBase: "feat/686-family-base",
          mergedBlockers: [],
        },
      });
      expect(result.status).toBe("failed");
      expect(result.errorPackage?.reason ?? "").toMatch(
        /record_persist_failed.*capacity relay_baton_handoff/i,
      );
      // Must not mislabel the write failure as the outer capacity fingerprint.
      expect(result.errorPackage?.reason ?? "").not.toMatch(
        /Selected model is at capacity/i,
      );
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
    }
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
      async prepareWorktree(): Promise<WorktreeHandle> { return worktree; }
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if ((spec.kind === "reviewer" || spec.kind === "verify") && spec.id === "S3") {
          return {
            kind: "completed",
            output: { kind: "reviewer", findings: [blockingFinding], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
          };
        }
        if (spec.kind === "coder" && spec.id === "S5") {
          coderFixModels.push(spec.model);
          // #936: Coder-Rec rewrites both coder and coderFix to first seat (grok);
          // no env preserve of a separate coderFix slot. Capacity-wall the seat
          // model and expect relay to the next codex baton.
          if (spec.model === "grok-4.5" || spec.model === "gpt-5.6-terra") {
            return { kind: "failed", reason: "Selected model is at capacity" };
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if ((spec.kind === "reviewer" || spec.kind === "verify") && spec.id === "S6") {
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          };
        }
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          return { kind: "completed", output: { kind: "judge", status: "converged" } };
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

    const presetPath = writeRoutePreset("s5-relay", {
      coder: "grok-4.5",
      coderFix: "grok-4.5",
      verify: "opus",
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "s5-relay");
    try {
      const result = await runOrchestrator({
        issueNumber: 873,
        backend: new CoderFixCapacityBackend(),
        relayPools: [
          {
            id: "grok-build",
            status: "limited",
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
        now: () => now,
      });

      expect(result.status, JSON.stringify(result, null, 2)).toBe("completed");
      // First S5 seat (after Coder-Rec) is grok; capacity relays onto codex.
      expect(coderFixModels).toEqual([
        "grok-4.5",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
      ]);
      expect(result.stepLedger).toContainEqual(
        expect.objectContaining({
          event: "relay_baton_handoff",
          step: "S5",
          trigger: "capacity",
        }),
      );
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
    }
  });

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

describe("#686 three handoff triggers (quota wall fork; #937 idle path deleted)", () => {
  const now = new Date("2026-07-10T12:00:00.000Z");

  it("probe 429 beyond T → relay preserves worktree (no reset)", () => {
    const result = forkQuotaWallAt683Point({
      disposition: {
        kind: "wait_for_reset",
        pool: "unknown",
        resetAt: new Date(now.getTime() + 45 * 60 * 1000),
        reason: "quota limited",
      },
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
          id: "zai",
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
    });
    expect(result.tier).toBe("relay");
    expect(result.nextBaton).toMatchObject({
      modelId: "terra@med",
      pool: "codex-5h",
    });
  });

  it("resource handoff for capacity has no resetBeforeRetry surface (#937)", async () => {
    const handoff = await applyResourceFailureHandoff({
      trigger: "capacity",
      state_summary: "model checkpoint at capacity; drift preserved",
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
      now,
    });
    expect(handoff.kind).toBe("relay");
    // Type-layer: resetBeforeRetry is not on ApplyResourceFailureHandoffInput.
    expect(handoff).not.toHaveProperty("resetBeforeRetry");
  });
});

describe("#686 state_summary ledger + ephemeral relay brief (#937)", () => {
  let tmp: string | undefined;
  afterEach(() => {
    if (tmp !== undefined) {
      rmSync(tmp, { recursive: true, force: true });
      tmp = undefined;
    }
  });

  it("writes state_summary into ledger and renders ephemeral brief (no focus file)", () => {
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

    const body = renderEphemeralRelayBrief(entry);
    expect(body).toContain("142 tests pending, apply half-done");
    expect(body).toContain("luna@med");
    expect(body).toContain("clear reds then 收口");
    // NEGATIVE: no worktree focus file is produced
    expectNoRelayFocusFile(tmp);
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
        trigger: "capacity",
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
      fromPool: "grok-build", toModelId: "b", toPool: "codex-5h", step: "S2", now: new Date("2026-07-10T12:00:00.000Z"),
    });
    expect(resumeRelayFromLedger([s2Relay, { step: "S2" }, { step: "S9" }], "S9")).toBeUndefined();
  });
});

describe("#686 fork at #683 quota disposition point", () => {
  it("composes wait_for_reset disposition → three-tier park/relay", () => {
    const now = new Date("2026-07-10T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 45 * 60 * 1000);
    const idle = {
      kind: "wait_for_reset" as const,
      pool: "grok" as const,
      resetAt,
      reason: "quota limited (402); wait for reset",
    };

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
          id: "zai",
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
          id: "zai",
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
    });
    expect(beyondT.tier).toBe("relay");
    expect(beyondT.nextBaton).toMatchObject({
      modelId: "terra@med",
      pool: "codex-5h",
    });
    expect(beyondT.ledgerEntry?.event).toBe("relay_baton_handoff");
  });
});

describe("#686 relay chain ends at normal review gate", () => {
  it("closing baton (no free-log relay tag / normal terminal) → review gate, no exemption", () => {
    // Free-log <relay> parse deleted (#937); gate uses completion flags only.
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
      pool: pool as "grok" | "zai"
    });
  }

  let tmp: string | undefined;
  afterEach(() => {
    if (tmp !== undefined) {
      rmSync(tmp, { recursive: true, force: true });
      tmp = undefined;
    }
  });

  it("mechanical-retry exhaustion is canonical failed edge (no baton relay) #937", async () => {
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
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
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
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          reviewerDispatches.push({ spec, ctx });
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
        },
      ],
      now: () => NOW,
    });

    // #934 ID-004 / #937: process-root exhaustion is a canonical failed edge —
    // never a mechanical_retry_exhausted baton handoff.
    const handoff = result.stepLedger.find(
      (e) => e.event === "relay_baton_handoff",
    );
    expect(handoff).toBeUndefined();
    expectNoRelayFocusFile(tmp);
    // Only the wall-hit model was dispatched (no relay baton re-entry).
    expect(coderModels.every((m) => m === "grok-4.5")).toBe(true);
    expect(coderFails).toBeGreaterThanOrEqual(1);
    expect(result.status).toBe("failed");
    expect(result.stopSummary?.summary ?? "").toMatch(
      /dispatch attempts|mechanical redispatch|process crashed/i,
    );
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
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
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
        if ((spec.kind === "reviewer" || spec.kind === "verify")) {
          reviewerModels.push(spec.model);
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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

    const presetPath = writeRoutePreset("relay-grok-normal", {
      coder: "grok-4.5",
      // keep normal-like CMR via default writeRoutePreset legs
    });
    // Custom file is sole table — use route name relay-grok-normal
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "relay-grok-normal");
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
      // #936 preset cleaned by afterEach
      // #936 preset cleaned by afterEach
    }
  });

  it("#920: S3 reviewer quota relay admits Terra even when Terra already owns the coder slot", async () => {
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
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
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
        if ((spec.kind === "reviewer" || spec.kind === "verify") && spec.id === "S3") {
          reviewerModels.push(spec.model);
          // First S3 attempt (sol) walls; after baton→terra, terra completes.
          if (spec.model === "gpt-5.6-sol") {
            throw quotaWaitError("S3", resetAt);
          }
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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

    const presetPath = writeRoutePreset("relay-grok-normal", {
      coder: "grok-4.5",
      // keep normal-like CMR via default writeRoutePreset legs
    });
    // Custom file is sole table — use route name relay-grok-normal
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "relay-grok-normal");
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

      // Pre-#920 pool separation vetoed Terra as reviewer while it owned coder;
      // #920 same-model cross-role is legal → S3 baton handoff lands Terra.
      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        step: "S3",
        toModelId: "terra@med",
      }));
      expect(reviewerModels).toEqual(
        expect.arrayContaining(["gpt-5.6-sol", "gpt-5.6-terra"]),
      );
    } finally {
      // #936 preset cleaned by afterEach
      // #936 preset cleaned by afterEach
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
    // #936: coder=grok + verify=opus via single custom preset (no slot env).
    const presetPath = writeRoutePreset("relay-grok-opus", {
      coder: "grok-4.5",
      verify: "opus",
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "relay-grok-opus");

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
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
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
        if ((spec.kind === "reviewer" || spec.kind === "verify") && spec.id === "S3") {
          reviewerModels.push(spec.model);
          if (spec.model === "opus") throw quotaWaitError("S3", resetAt);
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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

      expect(result.status).toBe("completed");
      expect(result.stepLedger).toContainEqual(expect.objectContaining({
        event: "relay_baton_handoff",
        toModelId: "terra@med",
        toPool: "codex-5h",
        step: "S3",
      }));
      expect(reviewerModels).toEqual(["opus", "gpt-5.6-terra"]);
    } finally {
      // #936 preset cleaned by afterEach
      // #936 preset cleaned by afterEach
      // #936 preset cleaned by afterEach
    }
  });
});

describe("#920 same-model cross-role is legal (ex-#686 conflict filter)", () => {
  const sol = lookupCoderRosterEntry("sol@med")!;

  it("admits sol on roster select and relay baton when every judging seat shares its slug", () => {
    // Pre-#920 pool separation vetoed sol whenever review/CMR seats shared its slug.
    expect(selectCoderRecEntry([sol]).id).toBe("sol@med");
    expect(
      selectNextRelayBaton({
        currentModelId: "grok-4.5",
        currentPool: "grok-build",
        rosterOrder: resolveCoderRecOrder("Coder-Rec: grok-4.5 → sol@med"),
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
            models: ["sol@med"],
          },
        ],
      })?.modelId,
    ).toBe("sol@med");
  });
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
        async prepareWorktree(): Promise<WorktreeHandle> {
          return worktree;
        }
        async runStep(): Promise<StepOutput> {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        async writeLedger(): Promise<void> {}
        async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
          if (spec.kind === "coder") {
            // Prove baton applied (terra slug) and uncommitted scene survived
            // (seeded focus file is ordinary drift after #937 — never deleted).
            expect(existsSync(join(tmp, RELAY_FOCUS_FILENAME))).toBe(true);
            expect(existsSync(join(tmp, "uncommitted-baton.txt"))).toBe(true);
            expect(spec.model).toBe("gpt-5.6-terra");
            return {
              kind: "completed",
              output: { kind: "coder", committed: true, commitsAdded: 1 },
            };
          }
          if ((spec.kind === "reviewer" || spec.kind === "verify")) {
            return {
              kind: "completed",
              output: { kind: "judge", status: "converged" },
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
                pr: "https://github.com/test/repo/pull/200",
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

      const presetPath = writeRoutePreset("relay-coder-grok", { coder: "grok-4.5" });
      vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetPath);
      vi.stubEnv("ORCHESTRATOR_ROUTE", "relay-coder-grok");
      try {
        await runOrchestrator({
          issueNumber: 686,
          backend: new ResumeBackend(),
          now: () => NOW,
        });
      } finally {
        // #936 preset cleaned by afterEach
      }
      // Seeded focus file remains as worktree drift (never host-cleaned).
      expect(existsSync(join(tmp, RELAY_FOCUS_FILENAME))).toBe(true);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  it("P1-3: #905 pins grok-4.5 to SuperGrok and rejects unbound pools", async () => {
    const {
      resolveModelSlugForPool,
      POOL_DISPATCH_BINDINGS,
    } = await import("../../src/modelRegistry.js");
    expect(POOL_DISPATCH_BINDINGS["grok-build"]).toBe("grok");
    expect(POOL_DISPATCH_BINDINGS.zai).toBeUndefined();
    expect(resolveModelSlugForPool("grok-4.5", "grok-build").provider).toBe(
      "grok",
    );
    expect(() => resolveModelSlugForPool("grok-4.5", "zai")).toThrow(
      /no executable provider binding/,
    );
    expect(resolveModelSlugForPool("grok-4.5").provider).toBe("grok");
    expect(() => resolveModelSlugForPool("gpt-5.6-sol", "zai")).toThrow(
      /no executable provider binding/,
    );
  });

  it("P2: legacy dispatch forwards relayBrief as a run option", async () => {
    let received: { readonly relayBrief?: string } | undefined;
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
          options: { readonly relayBrief?: string },
        ): Promise<StepOutput> {
          received = options;
          return { kind: "coder", committed: true, commitsAdded: 1 };
        },
      } as unknown as Backend;
      const brief = "state_summary: half-done\nremaining: clear reds";
      await legacyDispatchWorker(backend, {
        id: "S2",
        kind: "coder",
        role: "coder",
        host: "codex",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder.md",
        maxIter: 1,
        model: "grok-4.5",
        soul: "coder",
        toolchain: [],
      }, {
        worktree,
        relayBrief: brief,
      });
      expect(received?.relayBrief).toBe(brief);
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

  it("P1-5: ephemeral brief does not require a worktree (#937)", () => {
    const entry = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary: "x",
      fromModelId: "grok-4.5",
      fromPool: "grok-build",
      toModelId: "terra@med",
      toPool: "codex-5h",
      now: NOW,
    });
    const brief = renderEphemeralRelayBrief(entry);
    expect(brief).toContain("x");
    expect(brief).toContain("codex-5h");
  });

  it("P1-2: free-log hang/self-report constructors deleted (#937)", async () => {
    const relay = await import("../../src/relayDispatch.js");
    expect("HangWithLivePoolError" in relay).toBe(false);
    expect("SelfReportedRelayError" in relay).toBe(false);
    expect("tryParseActionableRelayTag" in relay).toBe(false);
    expect("isHangWithLivePoolError" in relay).toBe(false);
    expect("isSelfReportedRelayError" in relay).toBe(false);
  });

  it("public runOrchestrator: tight-violating relay baton escalates with zero further productive dispatch (ID-002 / R7 F4)", async () => {
    // Public driver seam (not unit-only admitRelayBaton): claude-tight forbids
    // claude family; S2 429 beyond T selects sonnet baton → tight re-admit stop.
    const dir = mkdtempSync(join(tmpdir(), "relay-934-tight-re-admit-"));
    const worktree: WorktreeHandle = {
      branch: "feat/934-tight-re-admit",
      base: "main",
      path: dir,
    };
    const resetAt = new Date(NOW.getTime() + 45 * 60 * 1000);
    const coderModels: string[] = [];
    const productiveKinds: string[] = [];

    class TightRelayBackend implements Backend {
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
          body: "Coder-Rec: grok-4.5 → sonnet-5",
        };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      }
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        productiveKinds.push(spec.kind);
        if (spec.kind === "coder" && spec.id === "S2") {
          coderModels.push(spec.model);
          if (spec.model === "grok-4.5") {
            throw new QuotaWaitForResetError({
              disposition: {
                kind: "wait_for_reset",
                pool: "grok",
                resetAt,
                reason: "quota limited (429); wait for reset",
              },
              applied: {
                ledgerEntry: {
                  event: "quota_wait_for_reset",
                  pool: "grok",
                  resetAt: resetAt.toISOString(),
                  reason: "quota limited (429); wait for reset",
                  step: "S2",
                  workerPid: 9001,
                  ts: NOW.toISOString(),
                },
              },
              pool: "grok",
            });
          }
          // Should never reach a claude-family baton re-dispatch.
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "reviewer" || spec.kind === "verify") {
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
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

    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    try {
      const result = await runOrchestrator({
        issueNumber: 934,
        backend: new TightRelayBackend(),
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
            status: "dead",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["terra@med", "luna@med", "sol@med"],
          },
          {
            id: "claude",
            status: "live",
            parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
            models: ["sonnet-5", "sonnet", "haiku-4.5", "haiku"],
          },
        ],
        now: () => NOW,
      });

      expect(result.status).toBe("failed");
      expect(
        `${result.errorPackage?.reason ?? ""} ${result.stopSummary?.summary ?? ""}`,
      ).toMatch(/tight route violation/i);
      // Wall-hit baton only — no productive re-dispatch after tight refuse.
      expect(coderModels).toEqual(["grok-4.5"]);
      expect(coderModels).not.toContain("sonnet");
      // No reviewer/ship after the refused baton (only the one coder attempt).
      expect(productiveKinds.filter((k) => k !== "coder")).toEqual([]);
      expectNoRelayFocusFile(dir);
    } finally {
      rmSync(dir, { recursive: true, force: true });
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
        async prepareWorktree(): Promise<WorktreeHandle> {
          return worktree;
        }
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
              pool: "grok"
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
      expect(result.status).toBe("parked");
      expect(result.stopSummary?.repairHint).toBe(
        "wait for the provider quota to reset, then re-feed — resume re-enters the parked step (auto re-dispatch is #686)",
      );
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });
});
