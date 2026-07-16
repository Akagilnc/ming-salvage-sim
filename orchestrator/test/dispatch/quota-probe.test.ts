/**
 * #683 / #937 — explicit quota wait-for-reset + silence-not-fate (ID-007).
 *
 * Seams under test:
 *   1. bridge serialize/parse of QuotaWaitForResetError
 *   2. buildQuotaWaitForResetLedgerEntry
 *   3. poolForModelRef
 *   4. RealBackend Sandcastle idle rethrows without quota probe
 *   5. runner park on explicit 429 (not abort)
 */


import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  buildQuotaWaitForResetLedgerEntry,
  isAgentIdleTimeoutError,
  poolForModelRef,
  QuotaWaitForResetError,
  serializeQuotaWaitForResetBridge,
  tryParseQuotaWaitForResetBridge,
  type QuotaPoolId,
} from "../../src/quotaProbe.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

describe("#683 bridge-child quota wall serialization", () => {
  it("round-trips QuotaWaitForResetError through failed.reason for parent rethrow", () => {
    const resetAt = new Date("2026-07-10T16:10:00.000Z");
    const err = new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: "zai",
        resetAt,
        reason: "quota limited (429); wait for reset",
      },
      applied: {
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: "zai",
          resetAt: resetAt.toISOString(),
          reason: "quota limited (429); wait for reset",
          step: "S2",
          workerPid: 4242,
          ts: "2026-07-10T12:00:00.000Z",
        },
      },
      pool: "zai"
    });
    const reason = serializeQuotaWaitForResetBridge(err);
    const restored = tryParseQuotaWaitForResetBridge(reason);
    expect(restored).toBeInstanceOf(QuotaWaitForResetError);
    expect(restored?.pool).toBe("zai");
    expect(restored?.disposition.resetAt?.toISOString()).toBe(
      resetAt.toISOString(),
    );
    expect(restored?.applied.ledgerEntry).toMatchObject({
      event: "quota_wait_for_reset",
      step: "S2",
      workerPid: 4242,
    });
    expect(tryParseQuotaWaitForResetBridge("hostCliWorkerRunner: worker threw")).toBeUndefined();
  });

  it("rejects bridge payload whose pool is not a QuotaPoolId", () => {
    const reason =
      "QUOTA_WAIT_FOR_RESET_V1:" +
      JSON.stringify({
        pool: "not-a-real-pool",
        reason: "quota limited (429); wait for reset",
      });
    expect(tryParseQuotaWaitForResetBridge(reason)).toBeUndefined();
  });

  it("drops malformed optional step/workerPid/ts rather than propagating them", () => {
    const reason =
      "QUOTA_WAIT_FOR_RESET_V1:" +
      JSON.stringify({
        pool: "zai",
        reason: "quota limited (429); wait for reset",
        step: 99,
        workerPid: "not-a-pid",
        ts: { when: "now" },
        probeDetail: 42,
      });
    const restored = tryParseQuotaWaitForResetBridge(reason);
    expect(restored).toBeInstanceOf(QuotaWaitForResetError);
    expect(restored?.pool).toBe("zai");
    expect(restored?.applied.ledgerEntry?.step).toBeUndefined();
    expect(restored?.applied.ledgerEntry?.workerPid).toBeUndefined();
    // Malformed ts → wall-clock now (valid ISO), not Invalid Date / object bleed.
    expect(restored?.applied.ledgerEntry?.ts).toEqual(
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
    );
    expect(
      Number.isNaN(new Date(restored!.applied.ledgerEntry!.ts).getTime()),
    ).toBe(false);
  });
});



describe("#683 buildQuotaWaitForResetLedgerEntry (ledger 外显)", () => {
  it("serializes resetAt as ISO and surfaces pool/reason/step/pid", () => {
    const entry = buildQuotaWaitForResetLedgerEntry({
      pool: "zai",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
      reason: "429 wall",
      step: "S2",
      workerPid: 111,
      now: new Date("2026-07-08T12:00:00.000Z"),
    });
    expect(entry).toEqual({
      event: "quota_wait_for_reset",
      pool: "zai",
      resetAt: "2026-07-08T16:10:00.000Z",
      reason: "429 wall",
      step: "S2",
      workerPid: 111,
      ts: "2026-07-08T12:00:00.000Z",
    });
  });
});

describe("#905 opencode-go probe retired", () => {
  it("has no runOpencodePongProbe / opencode spawn path in source", () => {
    const src = readFileSync(
      new URL("../../src/quotaProbe.ts", import.meta.url),
      "utf8",
    );
    expect(src).not.toMatch(/runOpencodePongProbe/);
    expect(src).not.toMatch(/\bopencode\s+run\b/);
    expect(src).not.toMatch(/--dangerously-skip-permissions/);
  });
});

describe("#683 isAgentIdleTimeoutError", () => {
  it("matches Sandcastle idle tag/name/message shapes", () => {
    expect(
      isAgentIdleTimeoutError(
        Object.assign(new Error("Agent idle for 600 seconds — no output received."), {
          name: "AgentIdleTimeoutError",
          _tag: "AgentIdleTimeoutError",
        }),
      ),
    ).toBe(true);
    expect(isAgentIdleTimeoutError(new Error("ECONNREFUSED"))).toBe(false);
  });
});


describe("#683/#937 RealBackend Sandcastle idle — no quota probe fate (ID-007)", () => {
  it("source no longer exports idle→quota composition helpers", () => {
    const src = readFileSync(
      new URL("../../src/quotaProbe.ts", import.meta.url),
      "utf8",
    );
    const realSrc = readFileSync(
      new URL("../../src/realBackend.ts", import.meta.url),
      "utf8",
    );
    expect(src).not.toMatch(/function handleIdleThreshold/);
    expect(src).not.toMatch(/function withIdleQuotaProbeDisposition/);
    expect(src).not.toMatch(/function resolveSandboxIdleAfterQuotaProbe/);
    expect(src).not.toMatch(/function decideIdleAfterProbe/);
    expect(src).not.toMatch(/function applyIdleDisposition/);
    expect(realSrc).not.toMatch(/resolveIdleAfterQuotaProbe/);
    expect(realSrc).not.toMatch(/withIdleQuotaProbeDisposition\s*\(/);
    // Production entry still exists and only invokes Sandcastle.
    expect(realSrc).toMatch(/protected async runAgentSandbox/);
    expect(realSrc).toMatch(/invokeSandcastleRun/);
  });

  it("poolForModelRef still maps model refs for explicit quota park", () => {
    expect(poolForModelRef("zai/glm-5.2")).toBe("zai");
    expect(poolForModelRef("grok-4.5")).toBe("grok");
    expect(poolForModelRef("opencode-go/glm-5.2")).toBe("unknown");
    expect(poolForModelRef("")).toBe("unknown");
  });
});


describe("#683 runner park: 429 parks step via existing park machinery (not abort)", () => {
  /**
   * QuotaWaitForResetError must NOT fall into errorTermination.
   * Mirror CI-pending park: status escalate + ledger marker, re-feed re-enters step.
   */
  const WORKTREE: WorktreeHandle = {
    branch: "feat/orchestrator/issue-683",
    base: "main",
    path: "/tmp/worktree/issue-683-runner",
  };

  class QuotaParkBackend implements Backend {
    public ledgerWrites: PersistentLedgerEntry[] = [];
    public coderDispatches = 0;
    public sandboxHandlePid = 7777;

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
      };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return WORKTREE;
    }
    async runStep(): Promise<StepOutput> {
      // Prefer dispatchWorker path below.
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
      this.ledgerWrites.push(entry);
    }

    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      if (spec.kind === "coder" && spec.id === "S2") {
        this.coderDispatches += 1;
        const resetAt = new Date("2026-07-08T16:10:00.000Z");
        // Explicit typed 429 wall (not host silence → probe).
        const ledgerEntry = buildQuotaWaitForResetLedgerEntry({
          pool: "zai",
          resetAt,
          reason: "quota limited (429); wait for reset",
          step: "S2",
          workerPid: this.sandboxHandlePid,
          now: new Date("2026-07-08T12:00:00.000Z"),
        });
        throw new QuotaWaitForResetError({
          disposition: {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt,
            reason: "quota limited (429); wait for reset",
          },
          applied: { ledgerEntry },
          pool: "zai",
        });
      }
      if (spec.kind === "reviewer" || spec.id === "S3" || spec.id === "S6") {
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
            branch: WORKTREE.branch,
            status: "pushed",
          },
        };
      }
      // Review-loop skeletons so a non-parked run could finish.
      if (spec.kind === "verify") {
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: true,
            findings: [],
            isRecheck: false,
          } as StepOutput,
        };
      }
      if (spec.kind === "docRelease") {
        return {
          kind: "completed",
          output: {
            kind: "docRelease",
            released: true,
            commitOid: "a".repeat(40),
          } as StepOutput,
        };
      }
      if (spec.kind === "cleanup") {
        return {
          kind: "completed",
          output: { kind: "cleanup", terminal: true } as StepOutput,
        };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
  }

  it("429 → run status escalate (parked), NOT error abort; ledger has quota_wait_for_reset", async () => {
    const backend = new QuotaParkBackend();
    // #686: pin no-live-baton pools so this #683 park regression stays park-only
    // (default pool table would otherwise relay beyond T).
    const result = await runOrchestrator({
      issueNumber: 683,
      backend,
      relayPools: [
        {
          id: "zai",
          status: "limited",
          resetAt: new Date("2026-07-08T16:10:00.000Z"),
          parkThresholdMs: 30 * 60 * 1000,
          models: ["grok-4.5"],
        },
      ],
    });

    expect(result.status).toBe("escalate");
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(1);
    // Marker present on in-memory step ledger and durable writes.
    const memMarker = result.stepLedger.find(
      (e) => e.event === "quota_wait_for_reset",
    );
    expect(memMarker).toMatchObject({
      event: "quota_wait_for_reset",
      pool: "zai",
      step: "S2",
      workerPid: 7777,
    });
    expect(result.stopSummary?.reason).toMatch(/provider_degraded|infra_failure/);
    expect(result.stopSummary?.summary).toMatch(/quota|429|reset/i);
    const diskMarker = backend.ledgerWrites.find(
      (e) => e.event === "quota_wait_for_reset",
    );
    expect(diskMarker).toBeDefined();
    // Step was parked — must not have advanced to S3.
    expect(result.stepLedger.some((e) => e.step === "S3" && e.event === undefined)).toBe(
      false,
    );
  });
});

describe("#883 codex capture ritual deleted", () => {
  it("every codex-provider agent has session capture disabled (ephemeral legs never write session files)", async () => {
    const { agentForSlug } = await import("../../src/modelRegistry.js");
    for (const slug of ["gpt-5.6-sol", "gpt-5.6-sol-high", "gpt-5.6-luna"]) {
      expect(agentForSlug(slug).captureSessions).toBe(false);
    }
  });
  it("claude legs keep capture (working path: resume + usage parsing)", async () => {
    const { agentForSlug } = await import("../../src/modelRegistry.js");
    expect(agentForSlug("opus").captureSessions).toBe(true);
  });
});
