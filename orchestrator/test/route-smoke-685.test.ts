import { mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import type * as sc from "@ai-hero/sandcastle";
import { runOrchestrator } from "../src/runner.js";
import {
  resolveRouteModels,
  routeSmokeFailure,
  routeSmokeEntries,
  smokeRouteModels,
} from "../src/modelRoutes.js";
import {
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
} from "../src/realBackend.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

const { runSpy } = vi.hoisted(() => ({ runSpy: vi.fn() }));

vi.mock("@ai-hero/sandcastle", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ai-hero/sandcastle")>();
  return { ...actual, run: runSpy };
});

class MissingSmokeBackend implements Backend {
  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) { return route; }
  async findResumeState(): Promise<ResumeState | undefined> { return undefined; }
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

class RoutePolicyOrderingBackend extends MissingSmokeBackend {
  readonly calls: string[] = [];

  async currentCliVersions() {
    this.calls.push("currentCliVersions");
    return {};
  }

  override async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    this.calls.push("smokeModelRoute");
    return route;
  }
}

class TerminalResumeSmokeBackend extends MissingSmokeBackend {
  readonly calls: string[] = [];

  override async findResumeState(): Promise<ResumeState> {
    this.calls.push("findResumeState");
    const terminal: PersistentLedgerEntry = {
      step: "S8",
      sessionId: "prior-session",
      prompt_hash: "prior-prompt",
      branchHEAD: "prior-head",
      ts: "2026-07-10T00:00:00.000Z",
      handoffStatus: "success",
    };
    return {
      worktree: { branch: "feat/685", base: "main", path: "/tmp/685" },
      stateDir: "/tmp/.ledger-685",
      ledger: [terminal],
    };
  }

  override async smokeModelRoute(): Promise<never> {
    this.calls.push("smokeModelRoute");
    throw new Error("smoke must not run for a terminal resume");
  }
}

class ProductionSmokeBackend extends RealBackend {
  protected override cloneDirExists(): boolean {
    return true;
  }

  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return ".git";
    }
    return "";
  }
}

const smokeFixtureDir = dirname(fileURLToPath(import.meta.url));
const smokePromptsDir = join(smokeFixtureDir, "..", "prompts");
const smokeSoulsDir = join(smokeFixtureDir, "..", "image", "souls");

function productionSmokeBackend(home: string): ProductionSmokeBackend {
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), "{}\n");
  writeFileSync(join(home, ".sc-claude-token"), "test-token\n");
  return new ProductionSmokeBackend({
    sourceRepo: "/tmp/route-smoke-source",
    remote: "https://github.com/owner/route-smoke.git",
    runKey: 685,
    repo: "owner/route-smoke",
    imageName: "route-smoke-test-image",
    promptsDir: smokePromptsDir,
    soulsDir: smokeSoulsDir,
    home,
  });
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
    expect(smoked.smoke["coder:gpt-5.6-terra"]).toMatchObject({
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

  it("accepts a passed smoke from a clock that is slightly ahead", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(
      route,
      async () => ({ cliVersion: "cli-1" }),
      new Date("2026-07-10T00:00:00.000Z"),
    );

    expect(
      routeSmokeFailure(smoked, Date.parse("2026-07-09T23:59:59.000Z")),
    ).toBeUndefined();
  });

  it("runs each unique model smoke concurrently", async () => {
    const route = resolveRouteModels("normal", {});
    let active = 0;
    let peak = 0;
    await smokeRouteModels(route, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 0));
      active -= 1;
      return { cliVersion: "cli-1" };
    });

    expect(peak).toBeGreaterThan(1);
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

  it("rejects tight-route violations before querying versions or starting smoke", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "codex-tight");
    vi.stubEnv("ORCHESTRATOR_REVIEWER_MODEL", "gpt-5.6-sol");
    const backend = new RoutePolicyOrderingBackend();

    const result = await runOrchestrator({ issueNumber: 685, backend });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.reason).toMatch(/tight route violation/i);
    expect(backend.calls).toEqual([]);
  });

  it("reports a terminal resume before starting route smoke", async () => {
    const backend = new TerminalResumeSmokeBackend();

    const result = await runOrchestrator({ issueNumber: 685, backend });

    expect(result.status).toBe("success");
    expect(result.stopSummary.reason).toBe("already_done");
    expect(backend.calls).toEqual(["findResumeState"]);
  });

  it("resolves the idle budget through resolveRouteSmokeIdleTimeoutSeconds across every input branch", () => {
    // Guard against external env pollution: the default branch is only honest
    // if it holds even when the ambient env happens to carry the var. Save,
    // unset, and restore around the whole matrix.
    const saved = process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    try {
      // undefined / missing → default 60s
      expect(resolveRouteSmokeIdleTimeoutSeconds(undefined)).toBe(60);
      // blank / whitespace-only → default
      expect(resolveRouteSmokeIdleTimeoutSeconds("")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("   ")).toBe(60);
      // legal positive integers honored verbatim
      expect(resolveRouteSmokeIdleTimeoutSeconds("1")).toBe(1);
      expect(resolveRouteSmokeIdleTimeoutSeconds("25")).toBe(25);
      expect(resolveRouteSmokeIdleTimeoutSeconds("120")).toBe(120);
      // zero / negative → default (must be >= 1)
      expect(resolveRouteSmokeIdleTimeoutSeconds("0")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("-5")).toBe(60);
      // non-numeric → default
      expect(resolveRouteSmokeIdleTimeoutSeconds("not-a-number")).toBe(60);
      // decimal / non-integer → default
      expect(resolveRouteSmokeIdleTimeoutSeconds("3.5")).toBe(60);
      // super-large value above the 32-bit-safe bound → default (would overflow
      // Sandcastle's value*1000 signed timer)
      expect(resolveRouteSmokeIdleTimeoutSeconds("3000000")).toBe(60);
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(String(Number.MAX_SAFE_INTEGER)),
      ).toBe(60);
      // the bound itself (2_147_483) is still accepted: the largest whole-second
      // value whose milliseconds remain <= INT32_MAX
      expect(resolveRouteSmokeIdleTimeoutSeconds("2147483")).toBe(2147483);
      // the first integer above the bound is rejected exactly
      expect(resolveRouteSmokeIdleTimeoutSeconds("2147484")).toBe(60);
    } finally {
      if (saved === undefined) {
        delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      } else {
        process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = saved;
      }
    }
  });

  it("resolves ORCHESTRATOR_SMOKE_IDLE_SECONDS per call, not once at module load", () => {
    // Locks the per-call resolution semantic: changing the env WITHIN the
    // process and resolving again must reflect the new value. A module-load
    // constant would freeze the first reading and fail this.
    const saved = process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    try {
      delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS),
      ).toBe(60);

      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "42";
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS),
      ).toBe(42);

      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "7";
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS),
      ).toBe(7);

      delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS),
      ).toBe(60);
    } finally {
      if (saved === undefined) {
        delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      } else {
        process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = saved;
      }
    }
  });

  it("wires ORCHESTRATOR_SMOKE_IDLE_SECONDS into every production smoke run per call", async () => {
    const saved = process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    const home = mkdtempSync(join(tmpdir(), "route-smoke-production-"));
    const route = resolveRouteModels("normal", {});
    const smokeRunCount = new Set(routeSmokeEntries(route).map(({ slug }) => slug)).size;
    let mutateNextSmokeEnvTo: string | undefined = "7";
    runSpy.mockImplementation(async (options: Parameters<typeof sc.run>[0]) => {
      if (options.logging?.type === "file") {
        if (mutateNextSmokeEnvTo !== undefined) {
          process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = mutateNextSmokeEnvTo;
          mutateNextSmokeEnvTo = undefined;
        }
        options.logging.onAgentStreamEvent?.({
          type: "toolCall",
          name: "bash",
          formattedArgs: "echo OK",
          iteration: 1,
          timestamp: new Date(),
        });
      }
      return { completionSignal: "ROUTE_SMOKE_COMPLETE" } as Awaited<ReturnType<typeof sc.run>>;
    });
    try {
      const backend = productionSmokeBackend(home);

      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "42";
      await backend.smokeModelRoute(route);
      expect(runSpy).toHaveBeenCalledTimes(smokeRunCount);
      expect(runSpy.mock.calls.map(([options]) => options.idleTimeoutSeconds)).toEqual(
        Array(smokeRunCount).fill(42),
      );

      runSpy.mockClear();
      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "7";
      mutateNextSmokeEnvTo = "42";
      await backend.smokeModelRoute(
        route,
        Object.fromEntries(routeSmokeEntries(route).map(({ slug }) => [slug, "changed-cli-version"])),
      );
      expect(runSpy).toHaveBeenCalledTimes(smokeRunCount);
      expect(runSpy.mock.calls.map(([options]) => options.idleTimeoutSeconds)).toEqual(
        Array(smokeRunCount).fill(7),
      );
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
      if (saved === undefined) {
        delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      } else {
        process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = saved;
      }
    }
  });

  it("smokes a pooled Grok route through the pool-selected Grok provider", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-pool-"));
    runSpy.mockImplementation(async () => ({ completionSignal: "ROUTE_SMOKE_COMPLETE" }) as Awaited<ReturnType<typeof sc.run>>);
    try {
      const backend = productionSmokeBackend(home);
      const route = resolveRouteModels("normal", { coder: "grok-4.5" });
      await backend.smokeModelRoute(route, {}, "grok-build");
      const grokRun = runSpy.mock.calls.find(([options]) => options.agent.name === "grok");
      expect(grokRun).toBeDefined();
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("does not reuse a default-provider smoke for the grok-build relay pool", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-cache-"));
    runSpy.mockImplementation(async () =>
      ({ completionSignal: "ROUTE_SMOKE_COMPLETE" }) as Awaited<ReturnType<typeof sc.run>>,
    );
    try {
      const backend = productionSmokeBackend(home);
      const route = resolveRouteModels("normal", { coder: "grok-4.5" });

      await backend.smokeModelRoute(route);
      runSpy.mockClear();
      await backend.smokeModelRoute(route, {}, "grok-build");

      expect(runSpy.mock.calls.some(([options]) => options.agent.name === "grok")).toBe(true);
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("reclaims the temporary Grok OAuth directory after each smoke container exits", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-auth-"));
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"token":"test"}\n');
    runSpy.mockImplementation(async () =>
      ({ completionSignal: "ROUTE_SMOKE_COMPLETE" }) as Awaited<ReturnType<typeof sc.run>>,
    );
    try {
      const backend = productionSmokeBackend(home);
      await backend.smokeModelRoute(resolveRouteModels("normal", { coder: "grok-4.5" }));

      expect(
        readdirSync(join(home, ".sc-orchestrator")).filter((name) =>
          name.startsWith("grok-auth-685-"),
        ),
      ).toEqual([]);
    } finally {
      runSpy.mockReset();
      rmSync(home, { recursive: true, force: true });
    }
  });
});
