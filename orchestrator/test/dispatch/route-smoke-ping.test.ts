/**
 * #884 — bare-ping route smoke redesign + driver stage lines.
 *
 * Smoke = one-shot host CLI, empty cwd, no docker/repo/tool loop; nonce echo
 * in the prompt is the oracle. Six unique legs run in parallel. Driver emits
 * one stage line per phase (smoke-k / reconcile / admission / dispatch).
 */
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  barePingArgv,
  barePingNonceSatisfied,
  buildBarePingPrompt,
  loadBarePingPromptTemplate,
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
} from "../../src/realBackend.js";
import {
  resolveRouteModels,
  routeSmokeEntries,
  routeSmokeFailure,
  smokeRouteModels,
} from "../../src/modelRoutes.js";
import { logDriverStage, DRIVER_STAGES } from "../../src/stageLog.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

const fixtureDir = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(fixtureDir, "..", "..", "prompts");
const soulsDir = join(fixtureDir, "..", "..", "image", "souls");

const tempHomes: string[] = [];
afterEach(() => {
  while (tempHomes.length > 0) {
    const h = tempHomes.pop();
    if (h !== undefined) rmSync(h, { recursive: true, force: true });
  }
  vi.restoreAllMocks();
});

function tempHome(prefix = "bare-ping-884-"): string {
  const home = mkdtempSync(join(tmpdir(), prefix));
  tempHomes.push(home);
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), "{}\n");
  writeFileSync(join(home, ".sc-claude-token"), "test-token\n");
  // #905: agy OAuth for real agy bare-ping / workers (fail-closed without it).
  writeFileSync(join(home, ".sc-agy-oauth-token"), "agy-test-token\n");
  // #807/#905: grok auth for SuperGrok bare-ping / workers.
  mkdirSync(join(home, ".grok"), { recursive: true });
  writeFileSync(join(home, ".grok", "auth.json"), "{}\n");
  return home;
}

/** Production-shaped backend with injectable bare-ping seam (no real CLI). */
class BarePingBackend extends RealBackend {
  readonly pingCalls: Array<{
    slug: string;
    cwd: string;
    prompt: string;
    nonce: string;
  }> = [];
  private readonly pingImpl: (
    input: BarePingBackend["pingCalls"][number],
  ) => Promise<string>;

  constructor(
    home: string,
    pingImpl: (input: BarePingBackend["pingCalls"][number]) => Promise<string>,
  ) {
    super({
      sourceRepo: "/tmp/route-smoke-source",
      remote: "https://github.com/owner/route-smoke.git",
      runKey: 884,
      repo: "owner/route-smoke",
      imageName: "route-smoke-test-image",
      promptsDir,
      soulsDir,
      home,
    });
    this.pingImpl = pingImpl;
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
    const call = {
      slug: input.slug,
      cwd: input.cwd,
      prompt: input.prompt,
      nonce: input.nonce,
    };
    this.pingCalls.push(call);
    return this.pingImpl(call);
  }

  public async readProductionBarePingEnvironment(): Promise<{
    home: string | undefined;
    claudeToken: string | undefined;
  }> {
    const stdout = await super.execBarePing({
      slug: "sonnet",
      cwd: tmpdir(),
      prompt: "unused",
      nonce: "unused",
      file: process.execPath,
      args: [
        "-e",
        "process.stdout.write(JSON.stringify({home:process.env.HOME,claudeToken:process.env.CLAUDE_CODE_OAUTH_TOKEN}))",
      ],
      timeoutMs: 2_000,
    });
    return JSON.parse(stdout) as {
      home: string | undefined;
      claudeToken: string | undefined;
    };
  }
}

describe("#884 bare-ping pure helpers", () => {
  it("builds a nonce-echo prompt from the versioned route-smoke template", () => {
    const template = loadBarePingPromptTemplate(promptsDir);
    expect(template).toContain("{{NONCE}}");
    const prompt = buildBarePingPrompt("abc-nonce-1", template);
    expect(prompt).toContain("abc-nonce-1");
    expect(prompt).not.toContain("{{NONCE}}");
    expect(prompt.toLowerCase()).toMatch(/reply|exactly/);
  });

  it("accepts exact reply or a full line equal to the nonce (not substring embed)", () => {
    expect(barePingNonceSatisfied("abc-nonce-1", "abc-nonce-1")).toBe(true);
    expect(barePingNonceSatisfied("thought...\nabc-nonce-1\n", "abc-nonce-1")).toBe(
      true,
    );
    expect(barePingNonceSatisfied("nope", "abc-nonce-1")).toBe(false);
    // Embedded mid-token must not certify the credential.
    expect(barePingNonceSatisfied("prefix-abc-nonce-1-suffix", "abc-nonce-1")).toBe(
      false,
    );
  });

  it("builds one-shot CLI argv per provider (no docker, no repo, no tools)", () => {
    const prompt = buildBarePingPrompt("n1");
    expect(barePingArgv("codex", "gpt-5.6-terra", prompt)).toMatchObject({
      file: "codex",
      args: expect.arrayContaining(["exec", "--skip-git-repo-check"]),
    });
    expect(barePingArgv("claudeCode", "claude-opus-4-8", prompt)).toMatchObject({
      file: "claude",
    });
    expect(barePingArgv("agy", "", prompt)).toMatchObject({
      file: "agy",
    });
    expect(barePingArgv("grok", "grok-4.5", prompt)).toMatchObject({
      file: "grok",
    });
    // Sandcastle uses standalone `agent` binary for the cursor provider.
    expect(barePingArgv("cursor", "composer", prompt)).toMatchObject({
      file: "agent",
      args: expect.arrayContaining(["-p", prompt]),
    });
    // Never references docker / sandcastle / worktree plumbing.
    // (agy bare-ping intentionally uses --sandbox — that is the CLI flag, not docker.)
    for (const p of ["codex", "claudeCode", "grok", "cursor"] as const) {
      const built = barePingArgv(p, "m", prompt);
      expect(JSON.stringify(built)).not.toMatch(/docker|worktree/i);
    }
  });
});

describe("#884 bare-ping production smoke", () => {
  it("launches host bare ping with the same injected home and Claude token source as workers", async () => {
    const home = tempHome();
    const backend = new BarePingBackend(home, async (call) => call.nonce);

    await expect(backend.readProductionBarePingEnvironment()).resolves.toEqual({
      home,
      claudeToken: "test-token",
    });
  });

  it("runs unique legs in parallel via bare ping (empty cwd, nonce oracle)", async () => {
    const home = tempHome();
    let active = 0;
    let peak = 0;
    const backend = new BarePingBackend(home, async (call) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 30));
      active -= 1;
      // Full-line nonce (oracle accepts exact line; not mid-token embed).
      return `thought\n${call.nonce}\n`;
    });
    const route = resolveRouteModels("normal", {});
    // Owner "六路": unique by model slug (shared roles fan out one status).
    const unique = new Set(routeSmokeEntries(route).map((e) => e.slug)).size;

    const smoked = await backend.smokeModelRoute(route);

    expect(peak).toBeGreaterThan(1);
    expect(backend.pingCalls.length).toBe(unique);
    expect(Object.values(smoked.smoke).every((s) => s.state === "passed")).toBe(
      true,
    );
    expect(routeSmokeFailure(smoked)).toBeUndefined();
    // Empty-dir smoke: cwd is under tmp, not the working repo clone path.
    for (const call of backend.pingCalls) {
      expect(call.cwd).toMatch(/route-smoke-ping/);
      expect(call.prompt).toContain(call.nonce);
    }
  });

  it("fails a leg when the nonce is not echoed (oracle)", async () => {
    const home = tempHome();
    const backend = new BarePingBackend(home, async () => "I refuse to echo");
    const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
    expect(routeSmokeFailure(smoked)).toMatch(/route smoke failed/i);
  });

  it("uses bare-ping exec only (no docker/sandbox argv; tool capability out of ignition)", async () => {
    const home = tempHome();
    const backend = new BarePingBackend(home, async (c) => c.nonce);
    const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
    expect(Object.values(smoked.smoke).every((s) => s.state === "passed")).toBe(
      true,
    );
    // Bare ping builds host CLI argv — never docker/sandcastle/sc.run plumbing.
    for (const call of backend.pingCalls) {
      expect(call.cwd).toMatch(/route-smoke-ping/);
      expect(call.prompt).toMatch(/Reply with exactly:/i);
    }
  });

  it("provider hang on one leg → timeout/retry exhaust → failed smoke with stage name", async () => {
    const home = tempHome();
    const { ExternalCallTimeoutError } = await import("../../src/externalCall.js");
    const backend = new BarePingBackend(home, async (call) => {
      if (call.slug === "opus") {
        throw new ExternalCallTimeoutError({
          stage: `smoke-k:${call.slug}`,
          timeoutMs: 10,
          seam: "provider",
        });
      }
      return call.nonce;
    });
    const smoked = await backend.smokeModelRoute(resolveRouteModels("normal", {}));
    const opusKeys = routeSmokeEntries(smoked).filter((e) => e.slug === "opus");
    for (const entry of opusKeys) {
      expect(smoked.smoke[entry.key]).toMatchObject({
        state: "failed",
        error: expect.stringMatching(/smoke-k:opus|timeout|exhaust/i),
      });
    }
  });

  it("maps ORCHESTRATOR_SMOKE_IDLE_SECONDS into bare-ping wall budget", () => {
    expect(resolveRouteSmokeIdleTimeoutSeconds("15")).toBe(15);
  });

  it("pool-rewritten relay ping overlaps unique legs and does not alias default pipe", async () => {
    // #884 P5 + cmr r8: dedicated pool ping for relaySmokeEntryKey shares the
    // same wave as unique-slug default-pipe legs; unique wave never uses the
    // dispatch pool (would fan out pool-passed as default-passed).
    const home = tempHome();
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"token":"test"}\n');
    let active = 0;
    let peak = 0;
    const starts: number[] = [];
    const pools: Array<string | undefined> = [];
    class RelayAwareBackend extends BarePingBackend {
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
        // file === "grok" ⇒ pool-selected grok CLI; otherwise default pipe.
        pools.push(input.file === "grok" ? "grok-build" : undefined);
        return super.execBarePing(input);
      }
    }
    const backend = new RelayAwareBackend(home, async (call) => {
      starts.push(Date.now());
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 80));
      active -= 1;
      return call.nonce;
    });
    const route = resolveRouteModels("normal", { coder: "grok-4.5" });
    const unique = new Set(routeSmokeEntries(route).map((e) => e.slug)).size;

    await backend.smokeModelRoute(route, {}, "grok-build", "coder:grok-4.5");

    // Unique default-pipe legs + exactly one dedicated pool relay ping.
    // #905: grok-4.5's default pipe IS already the SuperGrok CLI, so the
    // unique-slug ping and the dedicated pool ping both use file=grok.
    expect(backend.pingCalls.length).toBe(unique + 1);
    expect(pools.filter((p) => p === "grok-build")).toHaveLength(2);
    expect(pools.filter((p) => p === undefined).length).toBe(unique - 1);
    expect(peak).toBeGreaterThan(1);
    const skew = Math.max(...starts) - Math.min(...starts);
    expect(skew).toBeLessThan(60);
  });
});

describe("#884 ignition→first-dispatch timing (scripted backend)", () => {
  it("parallel bare-ping smoke keeps ignition tax well under serial multi-minute tax", async () => {
    const t0 = Date.now();
    let peak = 0;
    let active = 0;
    const route = resolveRouteModels("normal", {});
    await smokeRouteModels(route, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 40));
      active -= 1;
      return { cliVersion: "scripted-1" };
    });
    // Simulated "first dispatch" immediately after smoke.
    logDriverStage("dispatch", "step=S2");
    const wall = Date.now() - t0;
    expect(peak).toBeGreaterThan(1);
    // Six legs @ 40ms parallel → ~40–80ms, never multi-minute serial tax.
    expect(wall).toBeLessThan(2_000);
  });
});

describe("#884 driver stage line logs", () => {
  it("exposes the four owner-named stages", () => {
    expect([...DRIVER_STAGES].sort()).toEqual(
      ["admission", "dispatch", "reconcile", "smoke-k"].sort(),
    );
  });

  it("prints one attributable line per stage entry", () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    try {
      logDriverStage("admission", "epic #884");
      logDriverStage("smoke-k");
      logDriverStage("reconcile", "ledger empty");
      logDriverStage("dispatch", "child #885");
      expect(log.mock.calls.map((c) => String(c[0]))).toEqual([
        expect.stringMatching(/\[orchestrator:stage\] admission epic #884/),
        expect.stringMatching(/\[orchestrator:stage\] smoke-k/),
        expect.stringMatching(/\[orchestrator:stage\] reconcile ledger empty/),
        expect.stringMatching(/\[orchestrator:stage\] dispatch child #885/),
      ]);
    } finally {
      log.mockRestore();
    }
  });

  it("runOrchestrator emits smoke-k stage before first worker dispatch", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    class StageBackend implements Backend {
      private reviewerCalls = 0;
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        return smokeRouteModels(route, async () => ({ cliVersion: "t" }));
      }
      async findResumeState(): Promise<ResumeState | undefined> {
        return undefined;
      }
      async resumeSession(_spec: StepSpec): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async fetchIssueMeta(_issueNumber: number): Promise<IssueMeta> {
        return {
          number: 884,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
      async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
        return {
          number: issueNumber,
          body: "",
          comments: [],
          agentBrief: "implement #884",
        };
      }
      async prepareWorktree(
        issueNumber: number,
        base: string,
      ): Promise<WorktreeHandle> {
        return { branch: `feat/${issueNumber}`, base, path: `/tmp/${issueNumber}` };
      }
      async writeSnapshot() {}
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        if ((spec.role === "reviewer" || spec.role === "verify")) {
          // #877: no-progress court demolished — only S3 emits a blocker; later
          // re-reviews return empty so the run ships (findings-count channel).
          this.reviewerCalls += 1;
          if (this.reviewerCalls === 1) {
            return {
              kind: "reviewer", findings: [
                {
                  severity: "critical",
                  category: "bug",
                  claim_quote: "stop",
                  location: "x.ts:1",
                  suggested_fix: "stop",
                  action: "fix_now",
                },
              ], findingsCount: 1,
            };
          }
          return { kind: "judge", status: "converged" };
        }
        // Any remaining role (verify/fixer/cleanup/docRelease): keep the loop moving.
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger() {}
    }
    try {
      await runOrchestrator({ issueNumber: 884, backend: new StageBackend() });
      const lines = log.mock.calls.map((c) => String(c[0]));
      const reconcileIdx = lines.findIndex((l) =>
        /\[orchestrator:stage\] reconcile/.test(l),
      );
      const admissionIdx = lines.findIndex((l) =>
        /\[orchestrator:stage\] admission/.test(l),
      );
      const smokeIdx = lines.findIndex((l) =>
        /\[orchestrator:stage\] smoke-k/.test(l),
      );
      const dispatchIdx = lines.findIndex((l) =>
        /\[orchestrator:stage\] dispatch/.test(l),
      );
      // Owner-named four stages must all appear on the single-slice path so a
      // silent hang is attributable to the last entered phase.
      expect(reconcileIdx).toBeGreaterThanOrEqual(0);
      expect(admissionIdx).toBeGreaterThanOrEqual(0);
      expect(smokeIdx).toBeGreaterThanOrEqual(0);
      expect(dispatchIdx).toBeGreaterThan(smokeIdx);
      expect(admissionIdx).toBeLessThan(dispatchIdx);
    } finally {
      log.mockRestore();
    }
  });
});
