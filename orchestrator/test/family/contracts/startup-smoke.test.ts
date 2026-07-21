import { describe, expect, it, vi } from "vitest";
import { dispatchFamilyWorker, familyShipWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
import { runFamily } from "../../../src/family/runner.js";
import type { Backend, DispatchContext, WorkerResult, WorkerSpec } from "../../../src/types.js";
import type { FamilyBackend } from "../../../src/family/types.js";
import { resolveActiveModelRoute, smokeRouteModels } from "../../../src/modelRoutes.js";

const familyBackend: FamilyBackend = {
  async mergeChildIntoFamilyBase() {
    throw new Error("family backend should not run");
  },
  async resolveMergeConflict() {
    throw new Error("family backend should not run");
  },
  async appendFamilyLedger() {
    throw new Error("family backend should not run");
  },
  async readFamilyLedger() {
    throw new Error("family backend should not run");
  },
  async runFamilyVerify() {
    throw new Error("family backend should not run");
  },
};

function singleSliceBackend(overrides: Partial<Backend> = {}): Backend {
  return {
    smokeModelRoute: async (route) => route,
    ...overrides,
  } as Backend;
}

describe("family startup smoke gate (#685)", () => {
  it("refuses before family work when the backend has no smoke executor", async () => {
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: { issue: 685, children: [{ issue: 686, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: singleSliceBackend({ smokeModelRoute: undefined }),
      familyBase: "family/685-base",
    });

    expect(result.status).toBe("failed");
    expect(result.escalation?.diagnosis).toMatch(/smoke executor/i);
    expect(result.children).toEqual([{ issue: 686, status: "skipped" }]);
  });

  it("refuses before family work when route smoke fails", async () => {
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: { issue: 685, children: [{ issue: 687, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: singleSliceBackend({
        smokeModelRoute: async (route) => ({
          ...route,
          smoke: Object.fromEntries(
            Object.keys(route.smoke).map((key) => [
              key,
              { state: "failed", at: new Date().toISOString(), error: "boom" },
            ]),
          ),
        }),
      }),
      familyBase: "family/685-base",
    });

    expect(result.status).toBe("failed");
    expect(result.escalation?.diagnosis).toMatch(/route smoke failed/i);
    expect(result.children).toEqual([{ issue: 687, status: "skipped" }]);
  });

  it("drops an optional smoke failure, records it durably, and echoes the effective lineup", async () => {
    const entries: import("../../../src/family/types.js").FamilyLedgerEntry[] = [];
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const backend: FamilyBackend = {
      async mergeChildIntoFamilyBase() { throw new Error("must not merge"); },
      async resolveMergeConflict() { throw new Error("must not resolve"); },
      async appendFamilyLedger(entry) { entries.push(entry); },
      async readFamilyLedger() {
        return [
          ...entries,
          { status: "escalated", event: "escalated", escalationKind: "failure", reason: "test stop" },
        ];
      },
      async runFamilyVerify() { throw new Error("must not verify"); },
    };
    try {
      await runFamily({
        verifyCmr: async () => ({ ok: true, ran: true }),
        epic: { issue: 846, children: [{ issue: 847, blockedBy: [] }] },
        familyBackend: backend,
        singleSliceBackend: singleSliceBackend({
          smokeModelRoute: async (route) => smokeRouteModels(route, async ({ slug }) => {
            if (slug === "agy") throw new Error("agy unavailable");
            return { cliVersion: "test" };
          }),
        }),
        familyBase: "family/846-base",
      });

      expect(entries).toContainEqual(expect.objectContaining({
        status: "route_degraded",
        event: "route_degraded",
        droppedLeg: "agy",
        reason: "agy unavailable",
      }));
      expect(error).toHaveBeenCalledWith(expect.stringMatching(/OPTIONAL CMR LEG DROPPED: agy.*agy unavailable/));
      expect(info).toHaveBeenCalledWith(expect.stringContaining("cmrReview=[codex:gpt-5.6-sol,claude:opus]"));
    } finally {
      info.mockRestore();
      error.mockRestore();
    }
  });

  it("does not duplicate a degraded-route ledger row across resumes", async () => {
    const entries: import("../../../src/family/types.js").FamilyLedgerEntry[] = [];
    const backend: FamilyBackend = {
      async mergeChildIntoFamilyBase() { throw new Error("must not merge"); },
      async resolveMergeConflict() { throw new Error("must not resolve"); },
      async appendFamilyLedger(entry) { entries.push(entry); },
      async readFamilyLedger() {
        return [...entries, { status: "escalated", event: "escalated", escalationKind: "failure", reason: "test stop" }];
      },
      async runFamilyVerify() { throw new Error("must not verify"); },
    };
    const input = {
      epic: { issue: 846, children: [{ issue: 847, blockedBy: [] }] },
      familyBackend: backend,
      singleSliceBackend: singleSliceBackend({
        smokeModelRoute: async (route: ReturnType<typeof resolveActiveModelRoute>) => smokeRouteModels(route, async ({ slug }) => {
          if (slug === "agy") throw new Error("agy unavailable");
          return { cliVersion: "test" };
        }),
      }),
      familyBase: "family/846-base",
    };
    await runFamily(input);
    await runFamily(input);
    expect(entries.filter((entry) => entry.event === "route_degraded")).toHaveLength(1);
  });
});

describe("family worker smoke route envelope (#685)", () => {
  it("forwards the smoked route and refuses an absent route", async () => {
    const route = await smokeRouteModels(
      resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" }),
      async () => ({ cliVersion: "test" }),
    );
    let received: DispatchContext | undefined;
    const backend: FamilyBackend = {
      ...familyBackend,
      async dispatchWorker(
        _spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        received = ctx;
        return {
          kind: "completed",
          output: { kind: "ship", pr: "https://github.com/test/repo/pull/685", branch: "family/685", status: "opened" },
        };
      },
    };

    await dispatchFamilyWorker(backend, familyShipWorkerSpec(route), {
      familyBase: "family/685-base",
      modelRoute: route,
    });
    expect(received?.modelRoute).toBe(route);

    await expect(
      dispatchFamilyWorker(backend, familyShipWorkerSpec(route), {
        familyBase: "family/685-base",
      }),
    ).rejects.toThrow(/model route smoke state is missing/i);
    expect(received?.modelRoute).toBe(route);
  });
});
