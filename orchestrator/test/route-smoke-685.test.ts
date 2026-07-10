import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import {
  resolveRouteModels,
  routeSmokeFailure,
  smokeRouteModels,
} from "../src/modelRoutes.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

class MissingSmokeBackend implements Backend {
  async findResumeState() { return undefined; }
  async cleanResidue() {}
  async resumeSession(_spec: StepSpec): Promise<StepOutput> { return { kind: "coder", committed: true, commitsAdded: 1 }; }
  async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
    return { number: 685, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "", comments: [], agentBrief: "" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/${issueNumber}`, base, path: `/tmp/${issueNumber}` };
  }
  async writeSnapshot() {}
  async runStep(_spec: StepSpec): Promise<StepOutput> { return { kind: "coder", committed: true, commitsAdded: 1 }; }
  async push() {}
  async writeLedger() {}
}

describe("#685 route tool smoke", () => {
  it("rejects a route before its model×pipe entries have been smoked", () => {
    const route = resolveRouteModels("normal", {});

    expect(routeSmokeFailure(route)).toMatch(/route smoke required/i);
  });

  it("records a passed smoke with a timestamp and CLI version and allows dispatch", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async () => ({ cliVersion: "cli-1" }));

    expect(Object.values(smoked.smoke).every((status) => status.state === "passed")).toBe(true);
    expect(routeSmokeFailure(smoked)).toBeUndefined();
    expect(smoked.smoke["coder:sonnet"]).toMatchObject({
      state: "passed",
      cliVersion: "cli-1",
    });
  });

  it("rejects a passed smoke after its configured TTL", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(
      route,
      async () => ({ cliVersion: "cli-1" }),
      new Date("2026-07-01T00:00:00.000Z"),
    );

    expect(routeSmokeFailure(smoked, Date.parse("2026-07-03T00:00:01.000Z"), 48 * 60 * 60 * 1000)).toMatch(
      /route smoke expired/i,
    );
  });

  it("rejects a passed smoke when the selected CLI version changes", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async () => ({ cliVersion: "cli-1" }));

    expect(routeSmokeFailure(smoked, Date.now(), 24 * 60 * 60 * 1000, { sonnet: "cli-2" })).toMatch(
      /CLI version changed/i,
    );
  });

  it("records failures and keeps the route fail-closed", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async ({ slug }) => {
      if (slug === "sonnet") throw new Error("bash tool unavailable");
      return { cliVersion: "cli-1" };
    });

    expect(routeSmokeFailure(smoked)).toMatch(/route smoke failed.*sonnet/i);
  });

  it("refuses through runOrchestrator when the backend has no smoke executor", async () => {
    const result = await runOrchestrator({ issueNumber: 685, backend: new MissingSmokeBackend() });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/smoke/i);
  });
});
