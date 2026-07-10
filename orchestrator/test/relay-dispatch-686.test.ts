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
 */
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CODER_ROSTER,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
} from "../src/coderRoster.js";
import {
  DEFAULT_PARK_THRESHOLD_MS,
  decideParkOrRelay,
  selectNextRelayBaton,
  type BillingPoolEntry,
  type BillingPoolId,
  type PoolTable,
} from "../src/quotaPoolTable.js";
import {
  RELAY_FOCUS_FILENAME,
  applyResourceFailureHandoff,
  buildRelayFocusFile,
  buildRelayHandoffLedgerEntry,
  classifyFailureForRetryOrRelay,
  decideRelayAfterIdle,
  forkQuotaWallAt683Point,
  isRelayChainReadyForReviewGate,
  parseRelayTag,
  resumeRelayFromLedger,
  type RelayHandoffLedgerEvent,
} from "../src/relayDispatch.js";
import { decideIdleAfterProbe } from "../src/quotaProbe.js";

describe("#686 relay tag contract (fail-closed)", () => {
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

  it("roster table remains the single source (no second relay fallback table)", () => {
    // Sanity: selection only walks CODER_ROSTER / Coder-Rec order.
    expect(CODER_ROSTER.map((e) => e.id)).toEqual(
      expect.arrayContaining(["grok-4.5", "terra@med", "luna@med"]),
    );
    expect(lookupCoderRosterEntry("grok-4.5")?.slug).toBe("grok-4.5");
  });
});

describe("#686 three handoff triggers", () => {
  const now = new Date("2026-07-10T12:00:00.000Z");

  it("probe 429 → preserve worktree, record interrupt (no kill, no reset)", async () => {
    const killPidTree = vi.fn();
    const resetBeforeRetry = vi.fn();
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
      resetBeforeRetry,
    });
    expect(result.kind).toBe("relay");
    if (result.kind !== "relay") return;
    expect(result.preserveWorktree).toBe(true);
    expect(result.nextBaton).toMatchObject({
      modelId: "grok-4.5",
      pool: "cursor",
    });
    expect(killPidTree).not.toHaveBeenCalled();
    expect(resetBeforeRetry).not.toHaveBeenCalled();
  });

  it("hang-with-live-pool → kill pid tree then relay (not same-role retry)", async () => {
    const killPidTree = vi.fn();
    const resetBeforeRetry = vi.fn();
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
      resetBeforeRetry,
    });
    expect(result.kind).toBe("relay");
    if (result.kind !== "relay") return;
    expect(result.preserveWorktree).toBe(true);
    expect(result.trigger).toBe("hang_with_live_pool");
    expect(killPidTree).toHaveBeenCalledWith(99);
    expect(resetBeforeRetry).not.toHaveBeenCalled();
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
  it("classifies quota/pool-dead/hang-with-live-pool as resource failure", () => {
    expect(classifyFailureForRetryOrRelay({ kind: "quota_wall" })).toBe(
      "resource",
    );
    expect(classifyFailureForRetryOrRelay({ kind: "pool_dead" })).toBe(
      "resource",
    );
    expect(
      classifyFailureForRetryOrRelay({ kind: "hang_with_live_pool" }),
    ).toBe("resource");
    expect(
      classifyFailureForRetryOrRelay({ kind: "self_reported_blocked" }),
    ).toBe("resource");
  });

  it("classifies process-level failed/malformed as mechanical retry", () => {
    expect(classifyFailureForRetryOrRelay({ kind: "process_failed" })).toBe(
      "mechanical_retry",
    );
    expect(classifyFailureForRetryOrRelay({ kind: "malformed" })).toBe(
      "mechanical_retry",
    );
    expect(
      classifyFailureForRetryOrRelay({ kind: "outcome_protocol_failure" }),
    ).toBe("mechanical_retry");
  });

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
      toModelId: "terra@med",
      toPool: "codex-5h",
      step: "S2",
      now,
    });
    expect(entry).toMatchObject({
      event: "relay_baton_handoff",
      state_summary: "142 tests pending, apply half-done",
      remaining: "clear reds then 收口",
      fromModelId: "grok-4.5",
      toModelId: "terra@med",
    } satisfies Partial<RelayHandoffLedgerEvent>);

    const focusPath = buildRelayFocusFile(tmp, entry);
    expect(focusPath).toBe(join(tmp, RELAY_FOCUS_FILENAME));
    const body = readFileSync(focusPath, "utf8");
    expect(body).toContain("142 tests pending, apply half-done");
    expect(body).toContain("terra@med");
    expect(body).toContain("clear reds then 收口");
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
    const resume = resumeRelayFromLedger(ledger);
    expect(resume).toMatchObject({
      state_summary: "baton2 mid-clear",
      toModelId: "luna@med",
      remaining: "收口",
    });
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
