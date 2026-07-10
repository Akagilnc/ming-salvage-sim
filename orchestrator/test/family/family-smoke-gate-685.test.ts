import { describe, expect, it } from "vitest";
import { dispatchFamilyWorker, familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";
import { runFamily } from "../../src/family/runner.js";
import type { Backend, DispatchContext, WorkerResult, WorkerSpec } from "../../src/types.js";
import type { FamilyBackend } from "../../src/family/types.js";
import { resolveActiveModelRoute, smokeRouteModels } from "../../src/modelRoutes.js";

const familyBackend: FamilyBackend = {
  async mergeChildIntoFamilyBase() {
    throw new Error("family backend should not run");
  },
  async appendFamilyLedger() {
    throw new Error("family backend should not run");
  },
  async readFamilyLedger() {
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
      epic: { issue: 685, children: [{ issue: 686, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: singleSliceBackend({ smokeModelRoute: undefined }),
      familyBase: "family/685-base",
    });

    expect(result.status).toBe("escalated");
    expect(result.escalation?.diagnosis).toMatch(/smoke executor/i);
    expect(result.children).toEqual([{ issue: 686, status: "skipped" }]);
  });

  it("refuses before family work when route smoke fails", async () => {
    const result = await runFamily({
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

    expect(result.status).toBe("escalated");
    expect(result.escalation?.diagnosis).toMatch(/route smoke failed/i);
    expect(result.children).toEqual([{ issue: 687, status: "skipped" }]);
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
        return { kind: "completed", output: { kind: "ship", pr: "pr://family" } };
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
