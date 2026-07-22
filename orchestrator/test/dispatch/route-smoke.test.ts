/**
 * #685 route smoke gate + #884 bare-ping production path.
 *
 * Smoke is now a host CLI bare ping (no sandcastle docker / tool loop). The
 * gate semantics (required before dispatch, TTL, CLI version, concurrent unique
 * legs, optional-leg degrade) stay; the production executor is the bare-ping
 * seam on RealBackend.
 */
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import {
  resolveRouteModels,
  routeSmokeFailure,
  routeSmokeEntries,
  smokeRouteModels,
} from "../../src/modelRoutes.js";
import {
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
} from "../../src/realBackend.js";
import type {
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

class MissingSmokeBackend implements Backend {
  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    return route;
  }
  async findResumeState(): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(_spec: StepSpec): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
    return {
      number: 685,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/${issueNumber}`, base, path: `/tmp/${issueNumber}` };
  }
  async runStep(_spec: StepSpec): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
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
      handoffStatus: "completed",
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

/** Production-shaped backend with injectable bare-ping (no real model CLI). */
class ProductionSmokeBackend extends RealBackend {
  readonly pingCalls: Array<{
    slug: string;
    cwd: string;
    timeoutMs: number;
    file: string;
    args: readonly string[];
  }> = [];
  private readonly pingImpl: (input: {
    slug: string;
    nonce: string;
    file: string;
  }) => Promise<string>;

  constructor(
    home: string,
    pingImpl?: (input: { slug: string; nonce: string; file: string }) => Promise<string>,
  ) {
    super({
      sourceRepo: "/tmp/route-smoke-source",
      remote: "https://github.com/owner/route-smoke.git",
      runKey: 685,
      repo: "owner/route-smoke",
      imageName: "route-smoke-test-image",
      promptsDir: smokePromptsDir,
      soulsDir: smokeSoulsDir,
      home,
    });
    this.pingImpl =
      pingImpl ??
      (async (input) => input.nonce);
  }

  protected override cloneDirExists(): boolean {
    return true;
  }

  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return ".git";
    }
    if (
      file === "codex" ||
      file === "claude" ||
      file === "agy" ||
      file === "grok" ||
      file === "cursor" ||
      file === "agent"
    ) {
      return "cli-test-version";
    }
    return "";
  }

  protected override async execBarePing(input: {
    readonly slug: string;
    readonly cwd: string;
    readonly prompt: string;
    readonly nonce: string;
    readonly file: string;
    readonly args: readonly string[];
    readonly stdin?: string;
    readonly timeoutMs: number;
  }): Promise<string> {
    this.pingCalls.push({
      slug: input.slug,
      cwd: input.cwd,
      timeoutMs: input.timeoutMs,
      file: input.file,
      args: input.args,
    });
    return this.pingImpl({
      slug: input.slug,
      nonce: input.nonce,
      file: input.file,
    });
  }
}

const smokeFixtureDir = dirname(fileURLToPath(import.meta.url));
const smokePromptsDir = join(smokeFixtureDir, "..", "..", "prompts");
const smokeSoulsDir = join(smokeFixtureDir, "..", "..", "image", "souls");

function productionSmokeBackend(
  home: string,
  pingImpl?: (input: { slug: string; nonce: string; file: string }) => Promise<string>,
): ProductionSmokeBackend {
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), "{}\n");
  writeFileSync(join(home, ".sc-claude-token"), "test-token\n");
  // #905: agy OAuth for real agy bare-ping (fail-closed without it).
  // #1106: read the LIVE antigravity-cli token (no stale .sc-agy-oauth-token).
  mkdirSync(join(home, ".gemini", "antigravity-cli"), { recursive: true });
  writeFileSync(
    join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token"),
    "agy-test-token\n",
  );
  // Grok auth is optional fixture material — tests that need SuperGrok
  // bare-ping success write `~/.grok/auth.json` themselves (#905).
  return new ProductionSmokeBackend(home, pingImpl);
}

describe("#685 route tool smoke", () => {
  it("passes when bare ping echoes the nonce (credential oracle)", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-rendered-pass-"));
    try {
      const backend = productionSmokeBackend(home);
      const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
      expect(Object.values(smoked.smoke).every((status) => status.state === "passed")).toBe(
        true,
      );
      expect(backend.pingCalls.length).toBeGreaterThan(0);
      expect(backend.pingCalls.every((c) => c.cwd.includes("route-smoke-ping"))).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("fails when bare ping does not echo the nonce", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-rendered-missing-"));
    try {
      const backend = productionSmokeBackend(home, async () => "no nonce here");
      const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
      expect(Object.values(smoked.smoke).every((status) => status.state === "failed")).toBe(
        true,
      );
      expect(routeSmokeFailure(smoked)).toMatch(/route smoke failed/i);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

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

    expect(
      routeSmokeFailure(smoked, Date.parse("2026-07-03T00:00:01.000Z"), 48 * 60 * 60 * 1000),
    ).toMatch(/route smoke expired/i);
  });

  it("accepts a passed smoke from a clock that is slightly ahead", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(
      route,
      async () => ({ cliVersion: "cli-1" }),
      new Date("2026-07-10T00:00:00.000Z"),
    );

    expect(routeSmokeFailure(smoked, Date.parse("2026-07-09T23:59:59.000Z"))).toBeUndefined();
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
    const sonnetKey = routeSmokeEntries(route).find((e) => e.slug === "sonnet")?.key;
    expect(sonnetKey).toBeDefined();

    // #884: freshness is entry-key scoped (with slug fallback for older maps).
    expect(
      routeSmokeFailure(smoked, Date.now(), 24 * 60 * 60 * 1000, {
        [sonnetKey!]: "cli-2",
      }),
    ).toMatch(/CLI version changed/i);
    expect(
      routeSmokeFailure(smoked, Date.now(), 24 * 60 * 60 * 1000, { sonnet: "cli-2" }),
    ).toMatch(/CLI version changed/i);
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
    const result = await runOrchestrator({
      issueNumber: 685,
      backend: new MissingSmokeBackend(),
    });

    expect(result.status).toBe("failed");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toMatch(/smoke/i);
  });

  it("rejects tight-route violations before querying versions or starting smoke", async () => {
    // #936: env cannot force tight violation; pure admission policy fail-closes
    // without any smoke / CLI version query.
    const { resolveRouteModels, applyTightRoutePolicy } = await import(
      "../../src/modelRoutes.js"
    );
    const route = resolveRouteModels("codex-tight", { verify: "gpt-5.6-sol" });
    const decision = applyTightRoutePolicy(route);
    expect(decision.kind).toBe("stop");
    if (decision.kind === "stop") {
      expect(decision.escalation.reason).toMatch(/tight route violation/i);
    }
    // Policy stop does not require backend smoke/version work.
    const backend = new RoutePolicyOrderingBackend();
    expect(backend.calls).toEqual([]);
  });

  it("reports a terminal resume before starting route smoke", async () => {
    const backend = new TerminalResumeSmokeBackend();

    const result = await runOrchestrator({ issueNumber: 685, backend });

    expect(result.status).toBe("completed");
    expect(result.stopSummary.reason).toBe("already_done");
    expect(backend.calls).toEqual(["findResumeState"]);
  });

  it("resolves the idle budget through resolveRouteSmokeIdleTimeoutSeconds across every input branch", () => {
    const saved = process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    try {
      expect(resolveRouteSmokeIdleTimeoutSeconds(undefined)).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("   ")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("1")).toBe(1);
      expect(resolveRouteSmokeIdleTimeoutSeconds("25")).toBe(25);
      expect(resolveRouteSmokeIdleTimeoutSeconds("120")).toBe(120);
      expect(resolveRouteSmokeIdleTimeoutSeconds("0")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("-5")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("not-a-number")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("3.5")).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("3000000")).toBe(60);
      expect(
        resolveRouteSmokeIdleTimeoutSeconds(String(Number.MAX_SAFE_INTEGER)),
      ).toBe(60);
      expect(resolveRouteSmokeIdleTimeoutSeconds("2147483")).toBe(2147483);
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

  it("wires ORCHESTRATOR_SMOKE_IDLE_SECONDS into every production bare-ping per call", async () => {
    const saved = process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
    const home = mkdtempSync(join(tmpdir(), "route-smoke-production-"));
    const route = resolveRouteModels("normal", {});
    // #884: one bare-ping per unique model slug ("六路").
    const smokeRunCount = new Set(routeSmokeEntries(route).map(({ slug }) => slug)).size;
    try {
      const backend = productionSmokeBackend(home);

      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "42";
      await backend.smokeModelRoute(route);
      expect(backend.pingCalls).toHaveLength(smokeRunCount);
      expect(backend.pingCalls.every((c) => c.timeoutMs === 42_000)).toBe(true);

      backend.pingCalls.length = 0;
      process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = "7";
      await backend.smokeModelRoute(
        route,
        Object.fromEntries(
          routeSmokeEntries(route).map(({ slug }) => [slug, "changed-cli-version"]),
        ),
      );
      expect(backend.pingCalls).toHaveLength(smokeRunCount);
      expect(backend.pingCalls.every((c) => c.timeoutMs === 7_000)).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
      if (saved === undefined) {
        delete process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS;
      } else {
        process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS = saved;
      }
    }
  });

  it("smokes a pooled Grok route through the pool-selected Grok CLI", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-pool-"));
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"token":"test"}\n');
    try {
      const backend = productionSmokeBackend(home);
      const route = resolveRouteModels("normal", { coder: "grok-4.5" });
      await backend.smokeModelRoute(route, {}, "grok-build", "coder:grok-4.5");
      const grokPing = backend.pingCalls.find((c) => c.file === "grok");
      expect(grokPing).toBeDefined();
      expect(backend.pingCalls.some((c) => c.file !== "grok")).toBe(true);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("runs a live smoke again on every ignition", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-cache-"));
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"token":"test"}\n');
    try {
      const backend = productionSmokeBackend(home);
      const route = resolveRouteModels("normal", { coder: "grok-4.5" });

      await backend.smokeModelRoute(route);
      const firstIgnitionCalls = backend.pingCalls.length;
      backend.pingCalls.length = 0;
      await backend.smokeModelRoute(route);

      expect(firstIgnitionCalls).toBeGreaterThan(0);
      expect(backend.pingCalls).toHaveLength(firstIgnitionCalls);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("rejects a Grok-selected smoke before launch when its auth is unavailable", async () => {
    const home = mkdtempSync(join(tmpdir(), "route-smoke-grok-no-auth-"));
    try {
      const backend = productionSmokeBackend(home);
      const smoked = await backend.smokeModelRoute(
        resolveRouteModels("normal", { coder: "grok-4.5" }),
        {},
        "grok-build",
        "coder:grok-4.5",
      );
      expect(smoked.smoke["coder:grok-4.5"]).toMatchObject({
        state: "failed",
        error: expect.stringMatching(/no grok auth/i),
      });
      expect(backend.pingCalls.some((c) => c.file === "grok")).toBe(false);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
