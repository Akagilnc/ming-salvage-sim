/**
 * #336 — the single-slice ship step (S7) is a CONTAINER ship WORKER that invokes
 * `gstack-ship`, replacing the inline `RealBackend.push` (a bare `git push`).
 *
 * The ship worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `gstack-ship` (base merge / tests / diff review / VERSION / CHANGELOG / commit /
 * push / `gh pr create`). Its `<ship>` tag is gated on the completion signal then
 * classified into a {@link ShipWorkerOutcome}, which `dispatchWorker` maps to the
 * full {@link WorkerResult} union (PRD #330 R2):
 *   shipped → completed ShipResult; escalate → escalated; failed → failed;
 *   malformed → malformed.
 *
 * Tested WITHOUT a real container (mirrors #335's cmr-worker test): the
 * `runShipWorker` seam is fixtured; the `dispatchWorker(ship)` routing + the
 * deleted-inline regression are asserted at the seam.
 */

import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";
import {
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_OPENCODE_AUTH_FILE,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  SHIP_FOCUS_FILENAME,
  soulsMount,
  SPAWNED_WORKER_ENV,
} from "../src/realBackend.js";
import type { ShipAuth } from "../src/realBackend.js";
import { shipWorkerSpec } from "../src/dispatchWorker.js";
import type { ShipWorkerOutcome } from "../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec, WorktreeHandle } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");
const realSoulsDir = join(here, "..", "image", "souls");

const cleanups: string[] = [];
afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});
function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

const worktree: WorktreeHandle = {
  branch: "feat/244-orchestrator-issue-336",
  base: "main",
  path: "/resident/worktrees/issue-336",
};

/**
 * A RealBackend whose container `runShipWorker` seam is fixtured (no real sc.run)
 * AND whose construction-time clone/promptsDir validation is bypassed (we only
 * exercise the pure dispatch routing). The clone is never built — we override the
 * builder to a temp dir.
 */
class FixturedShipBackend extends RealBackend {
  runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
  outcome: ShipWorkerOutcome = {
    kind: "shipped",
    branch: worktree.branch,
    status: "pr_opened",
    pr: "https://gh/pr/1",
  };
  pushCount = 0;

  protected override buildOrReuseClone(): string {
    return mkDir("ship-clone-");
  }
  protected override assertIndependentClone(): void {
    // The fixtured clone is a bare temp dir (no .git) — skip the ADR 0024 guard;
    // this test exercises only the pure dispatch routing, not a real clone.
  }
  protected override async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ShipWorkerOutcome> {
    this.runShipCalls.push({ spec, ctx });
    return this.outcome;
  }
  // The inline push must NEVER be reached by the ship worker path (#336 deletes it).
  override async push(): Promise<void> {
    this.pushCount += 1;
    throw new Error("RealBackend.push must not be reached — S7 ships via gstack-ship (#336)");
  }
}

function fixtured(): FixturedShipBackend {
  return new FixturedShipBackend({
    sourceRepo: mkDir("ship-src-"),
    repo: "Akagilnc/ming-salvage-sim",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "ming-orchestrator-coder:latest",
    runKey: 336,
    // #748: coder dispatch may reach mountAuth; keep it off real ~/.sc-orchestrator.
    home: mkDir("ship-home-"),
  });
}

describe("#336 RealBackend.dispatchWorker — the single-slice ship worker", () => {
  it("dispatches the ship worker spec to runShipWorker — gstack-ship", async () => {
    const be = fixtured();
    await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(be.runShipCalls.length).toBe(1);
    const spec = be.runShipCalls[0]!.spec;
    expect(spec.kind).toBe("ship");
    expect(spec.skill).toBe("gstack-ship");
    expect(be.pushCount).toBe(0); // never the inline push
  });

  it("the ship spec is a WRITE/coder worker with an iterative budget (maxIter>1) — gstack-ship must self-rerun rerun-able failures (ship.md), NOT a single-pass reviewer (#336 cmr r6)", () => {
    const spec = shipWorkerSpec();
    expect(spec.role).toBe("coder");
    expect(spec.maxIter).toBeGreaterThan(1);
  });

  it("a shipped outcome ⇒ WorkerResult.completed with a ShipResult payload", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: worktree.branch, status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "ship") {
      expect(res.output.branch).toBe(worktree.branch);
      expect(res.output.pr).toBe("u");
      expect(res.output.status).toBe("pr_opened");
    } else {
      throw new Error("expected a completed ship payload");
    }
  });

  it("an escalate outcome ⇒ WorkerResult.escalated (a genuine block, not a rerun)", async () => {
    const be = fixtured();
    be.outcome = { kind: "escalate", reason: "merge conflict", diagnosis: "human must resolve", escalationKind: "decision" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") expect(res.escalation.reason).toContain("merge conflict");
  });

  it("a failed outcome ⇒ WorkerResult.failed (a hard ship/test failure)", async () => {
    const be = fixtured();
    be.outcome = { kind: "failed", reason: "tests red", diagnosis: "vitest exited 1" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("failed");
    if (res.kind === "failed") expect(res.reason).toContain("tests red");
  });

  it("a malformed outcome ⇒ WorkerResult.malformed (never silently a success)", async () => {
    const be = fixtured();
    be.outcome = { kind: "malformed", reason: "no <ship> tag" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("malformed");
  });

  it("a ship worker without a worktree throws (the worker ships a branch)", async () => {
    const be = fixtured();
    await expect(be.dispatchWorker!(shipWorkerSpec(), {})).rejects.toThrow(/worktree/);
  });

  it("a shipped outcome whose branch differs from the worktree branch remains a worker outcome", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: "main", status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res).toMatchObject({
      kind: "completed",
      output: { kind: "ship", branch: "main", status: "pr_opened", pr: "u" },
    });
  });

  it("a shipped outcome on the correct worktree branch ⇒ completed (identity holds)", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: worktree.branch, status: "pushed" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("completed");
  });

  it("a NON-ship worker is forwarded to the legacy agent path (not the ship seam)", async () => {
    // dispatchWorker on RealBackend handles ship; other kinds fall back to the
    // existing runStep/resumeSession seam. A coder worker must NOT touch runShipWorker.
    const be = fixtured();
    const coderSpec: WorkerSpec = { ...shipWorkerSpec(), kind: "coder", skill: "/tdd" };
    // It will fail somewhere downstream (no real container), but it must not be
    // routed through the ship seam.
    await be.dispatchWorker!(coderSpec, { worktree }).catch(() => {});
    expect(be.runShipCalls.length).toBe(0);
  });
});

describe("#336 the inline single-slice push is no longer the ship path", () => {
  it("a ship dispatch never calls RealBackend.push (gstack-ship replaces it)", async () => {
    const be = fixtured();
    await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(be.pushCount).toBe(0);
  });
});

// ═══════════════ single-slice shipSandboxConfig — best-effort auth (mirrors family) ═══════════════

describe("#336 single-slice shipSandboxConfig — best-effort ship auth", () => {
  /** A RealBackend exposing the pure config seam, with the clone seams stubbed. */
  class ConfigBackend extends RealBackend {
    protected override buildOrReuseClone(): string {
      return mkDir("ship-clone-");
    }
    protected override assertIndependentClone(): void {
      // pure config seam under test, not a real clone.
    }
    public config(auth: ShipAuth, model = "sonnet", billingPool?: "zai" | "codex-5h"): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.shipSandboxConfig(auth);
    }
  }
  function cfg(): ConfigBackend {
    return new ConfigBackend({
      sourceRepo: mkDir("ship-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-home-cfg-"),
    });
  }

  it("mounts codex auth + the claude token under the dedicated ship soul", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("ship");
    // ORCHESTRATOR_REPO is exported so the ship soul's `gh issue create
    // --repo "$ORCHESTRATOR_REPO"` defer path works (codex #384).
    expect(c.env[SANDBOX_REPO_ENV]).toBe("Akagilnc/ming-salvage-sim");
  });

  it("mounts the isolated grok auth dir when the selected dispatch can use grok", () => {
    const c = cfg().config({
      codexAuthDir: "/tmp/codex",
      grokAuthDir: "/tmp/grok",
      claudeToken: "tok",
    });
    expect(c.mounts).toContainEqual({
      hostPath: "/tmp/grok",
      sandboxPath: SANDBOX_GROK_DIR,
    });
  });

  it("provisions OpenCode auth uniformly regardless of ship model or billing pool", () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const authFile = join(mkDir("ship-opencode-"), "auth.json");
    writeFileSync(authFile, JSON.stringify({ "opencode-go": { type: "api", key: "x" } }));
    const openCode = cfg().config({ opencodeAuthFile: authFile }, "sonnet", "zai");
    expect(openCode.env.GLM_KEY).toBe("glm-secret");
    expect(openCode.mounts).toContainEqual({
      hostPath: authFile,
      sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
      readonly: true,
    });

    const codex = cfg().config({ opencodeAuthFile: authFile }, "gpt-5.6-terra", "codex-5h");
    expect(codex.env.GLM_KEY).toBe("glm-secret");
    expect(codex.mounts).toContainEqual({
      hostPath: authFile,
      sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
      readonly: true,
    });
  });

  it("shipSandboxConfig includes soulsMount() shape (hostPath/sandboxPath/readonly:true) (#372)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    const expected = soulsMount(realSoulsDir);
    expect(c.mounts).toContainEqual(expected);
  });

  it("exports the gh token as GH_TOKEN so the in-container `gh pr create` / push over https is authenticated (cmr S336 r10 P1)", () => {
    // The 2b image BAKES the gh CLI but no gh AUTH (a live OAuth secret). gstack-ship
    // Step 17 `git push` (https → gh credential helper) + Step 19 `gh pr create`
    // both need it. The host token (`gh auth token`) lives in the macOS keyring, NOT
    // in a portable hosts.yml, so we inject it as the GH_TOKEN env var (gh's standard
    // env-token auth) rather than mounting ~/.config/gh (which would be tokenless).
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok", ghToken: "gho_xyz" });
    expect(c.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_xyz");
  });

  it("omits GH_TOKEN when no gh token is present (the pure seam stays tolerant; the REQUIRE-gh preflight lives upstream in runShipWorker)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.env[SANDBOX_GH_TOKEN_ENV]).toBeUndefined();
  });

  it("a missing codex auth degrades the mount but still ships under the ship soul", () => {
    const c = cfg().config({ claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("ship");
  });

  it("the pure config seam tolerates a missing claude token (the preflight that REQUIRES it lives upstream in runShipWorker — cmr S336 r8)", () => {
    // shipSandboxConfig is a PURE auth→env map (mirrors cmrSandboxConfig): it omits
    // the env var when the token is absent rather than throwing. The claude token is
    // NOT optional for the worker, but the gate is the runShipWorker preflight below
    // (it escalates before this seam is ever built when the token is missing) — so
    // this seam stays tolerant, exactly as cmrSandboxConfig does.
    const c = cfg().config({ codexAuthDir: "/tmp/codex" });
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBeUndefined();
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("ship");
  });

  it("marks the ship container as an orchestrator-spawned, non-interactive session (gstack-ship reads OPENCLAW_SESSION → auto-decides its P1 gate)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.env.OPENCLAW_SESSION).toBe("1");
    expect(c.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });
});

// ═══════════════════ runShipWorker fail-closed on a missing Claude WORKER auth (cmr S336 r8) ═══════════════════

describe("#336 single-slice runShipWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The single-slice ship worker is the container's TOP-LEVEL claude
   * (`agent: sc.claudeCode`), so the Claude OAuth token is its OWN auth, not a
   * degradable codex/gh leg. Absent, the worker cannot start and never emits a
   * `<ship>` verdict; letting it through would throw out of `sc.run`. runner S7 DOES
   * wrap the dispatch in try/catch → errorTermination, but a missing token deserves
   * the cleaner escalate续跑 (a human must supply the token) rather than an opaque
   * S8(error). So `runShipWorker` preflights the token and escalates BEFORE the
   * container — symmetric with the family ship + cmr workers. codex/gh stays
   * best-effort.
   */
  class NoClaudeAuthBackend extends RealBackend {
    sandboxReached = false;
    protected override buildOrReuseClone(): string {
      return mkDir("ship-noauth-clone-");
    }
    protected override assertIndependentClone(): void {
      // pure preflight under test, not a real clone.
    }
    public run(spec: WorkerSpec, ctx: DispatchContext): Promise<ShipWorkerOutcome> {
      return (
        this as unknown as {
          runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome>;
        }
      ).runShipWorker(spec, ctx);
    }
    // codex/gh present, claude token ABSENT (the worker's own auth missing).
    protected override mountShipAuth(): ShipAuth {
      return { codexAuthDir: "/x/codex" };
    }
    // If the preflight is honoured this is never built (the sandbox is downstream of
    // the token gate); reaching it means the worker tried to start unauthenticated.
    protected override shipSandbox(): never {
      this.sandboxReached = true;
      throw new Error("shipSandbox should not be built when the worker has no auth");
    }
  }
  function noAuth(): NoClaudeAuthBackend {
    return new NoClaudeAuthBackend({
      sourceRepo: mkDir("ship-noauth-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-home-noauth-"),
    });
  }

  it("no Claude worker token ⇒ escalate, never builds the sandbox / starts the container", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const be = noAuth();
    const outcome = await be.run(shipWorkerSpec(), { worktree });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/claude|token|auth/i);
      expect(outcome.diagnosis).toMatch(/cannot start without CLAUDE_CODE_OAUTH_TOKEN/i);
    }
    expect(be.sandboxReached).toBe(false);
  });

  it("dispatchWorker routes the no-auth escalate to a not-passed (escalated) WorkerResult", async () => {
    const be = noAuth();
    const res = await be.dispatchWorker(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/claude|token|auth/i);
    }
  });

  it("reclaims the isolated grok auth dir on the early no-Claude-auth exit", async () => {
    const codexDir = mkDir("ship-reclaim-codex-");
    const grokDir = mkDir("ship-reclaim-grok-");
    class ReclaimBackend extends NoClaudeAuthBackend {
      protected override mountShipAuth(): ShipAuth {
        return { codexAuthDir: codexDir, grokAuthDir: grokDir };
      }
    }
    const be = new ReclaimBackend({
      sourceRepo: mkDir("ship-reclaim-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-reclaim-home-"),
    });

    const outcome = await be.run(shipWorkerSpec(), { worktree });
    expect(outcome.kind).toBe("escalate");
    expect(existsSync(codexDir)).toBe(false);
    expect(existsSync(grokDir)).toBe(false);
  });
});

// ═══════════════ runShipWorker fail-closed on a missing gh auth (cmr S336 r10 P1) ═══════════════

describe("#336 single-slice runShipWorker — fail-closed when gh auth is missing", () => {
  /**
   * gh auth is a HARD requirement for the ship worker's happy path: gstack-ship
   * Step 17 pushes over https (gh credential helper) and Step 19 runs `gh pr create`.
   * The 2b image bakes the gh CLI but NO gh auth (a live OAuth secret). Without it the
   * worker would run the whole pipeline only to fail at `git push` / `gh pr create` —
   * an opaque late failure, NOT the cleaner escalate续跑 a human can act on. So
   * runShipWorker preflights the gh token (like the claude token, cmr S336 r8) and
   * escalates BEFORE the container. codex auth stays best-effort (it only degrades the
   * in-container diff review, not push/PR).
   */
  class NoGhAuthBackend extends RealBackend {
    sandboxReached = false;
    protected override buildOrReuseClone(): string {
      return mkDir("ship-noghauth-clone-");
    }
    protected override assertIndependentClone(): void {
      // pure preflight under test, not a real clone.
    }
    public run(spec: WorkerSpec, ctx: DispatchContext): Promise<ShipWorkerOutcome> {
      return (
        this as unknown as {
          runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome>;
        }
      ).runShipWorker(spec, ctx);
    }
    // claude + codex present, gh token ABSENT (push/PR cannot authenticate).
    protected override mountShipAuth(): ShipAuth {
      return { codexAuthDir: "/x/codex", claudeToken: "tok" };
    }
    protected override shipSandbox(): never {
      this.sandboxReached = true;
      throw new Error("shipSandbox should not be built when gh auth is missing");
    }
  }
  function noGh(): NoGhAuthBackend {
    return new NoGhAuthBackend({
      sourceRepo: mkDir("ship-noghauth-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-home-nogh-"),
    });
  }

  it("no gh token ⇒ escalate, never builds the sandbox / starts the container", async () => {
    const be = noGh();
    const outcome = await be.run(shipWorkerSpec(), { worktree });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/gh|github/i);
      expect(outcome.diagnosis).toMatch(/gh auth|GH_TOKEN|gh pr create|push/i);
    }
    expect(be.sandboxReached).toBe(false);
  });

  it("dispatchWorker routes the missing-gh escalate to a not-passed (escalated) WorkerResult", async () => {
    const be = noGh();
    const res = await be.dispatchWorker(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/gh|github/i);
    }
  });

  it("a present gh token passes the preflight (the sandbox IS reached — the gh gate does not over-reject a fully-authenticated host)", async () => {
    // gh + claude present ⇒ both preflights pass and the worker proceeds to build the
    // sandbox (here the stub `shipSandbox` throws on reach, which is how we OBSERVE the
    // preflight let it through — the gate did not stop early). Asserts the gh preflight
    // is not over-eager.
    class GhPresentBackend extends NoGhAuthBackend {
      protected override mountShipAuth(): ShipAuth {
        return { codexAuthDir: "/x/codex", claudeToken: "tok", ghToken: "gho_ok" };
      }
    }
    const be = new GhPresentBackend({
      sourceRepo: mkDir("ship-ghok-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-home-ghok-"),
    });
    await expect(be.run(shipWorkerSpec(), { worktree })).rejects.toThrow(
      /shipSandbox should not be built/,
    );
    expect(be.sandboxReached).toBe(true);
  });
});

describe("#336 single-slice runShipWorker — outcome sidecar cleanup", () => {
  it("removes the temporary outcome sidecar directory after parsing the ship result", async () => {
    let outcomePathAtRun: string | undefined;
    const localWorktree: WorktreeHandle = {
      branch: "feat/issue-496",
      base: "main",
      path: mkDir("ship-outcome-worktree-"),
    };
    class OutcomeCleanupBackend extends RealBackend {
      public run(spec: WorkerSpec, ctx: DispatchContext): Promise<ShipWorkerOutcome> {
        return (
          this as unknown as {
            runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome>;
          }
        ).runShipWorker(spec, ctx);
      }
      protected override buildOrReuseClone(): string {
        return mkDir("ship-outcome-clone-");
      }
      protected override assertIndependentClone(): void {}
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      protected override excludeRuntimeFileFromGit(): void {}
      protected override prepareShipOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } | undefined {
        const landing = super.prepareShipOutcomeLanding(ctx);
        outcomePathAtRun = landing?.path;
        return landing;
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(
          outcomePathAtRun,
          JSON.stringify({
            status: "pr_opened",
            branch: "feat/issue-496",
            pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/514",
          }),
          "utf8",
        );
        return {
          completionSignal: "SHIP_STEP_COMPLETE",
          stdout: "<ship>{}</ship>",
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new OutcomeCleanupBackend({
      sourceRepo: mkDir("ship-outcome-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 336,
      home: mkDir("ship-home-outcome-"),
    });

    const outcome = await be.run(shipWorkerSpec(), {
      worktree: localWorktree,
      stateDir: mkDir("ship-outcome-state-"),
    });

    expect(outcome.kind).toBe("shipped");
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });
});

describe("#439 single-slice ship worker resume answer focus", () => {
  it(".ship-focus.md is repo-ignored even if a per-worktree exclude update fails", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const ignore = readFileSync(join(here, "..", "..", ".gitignore"), "utf8");
    expect(ignore.split(/\r?\n/)).toContain(SHIP_FOCUS_FILENAME);
  });

  it("writes the answered S7 decision escalation into .ship-focus.md before sandbox startup", async () => {
    const focusWorktree: WorktreeHandle = {
      branch: "feat/orchestrator/issue-439",
      base: "main",
      path: mkDir("ship-answer-focus-worktree-"),
    };
    let focusBody = "";
    class ShipAnswerFocusBackend extends RealBackend {
      public run(spec: WorkerSpec, ctx: DispatchContext): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override buildOrReuseClone(): string {
        return mkDir("ship-answer-focus-clone-");
      }
      protected override assertIndependentClone(): void {}
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "claude-token", ghToken: "gho_token" };
      }
      protected override shipSandbox(): never {
        focusBody = readFileSync(
          join(focusWorktree.path, SHIP_FOCUS_FILENAME),
          "utf8",
        );
        throw new Error("shipSandbox reached after writing focus");
      }
    }
    const be = new ShipAnswerFocusBackend({
      sourceRepo: mkDir("ship-answer-focus-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 439,
      home: mkDir("ship-home-answer-"),
    });

    await expect(
      be.run(shipWorkerSpec(), {
        worktree: focusWorktree,
        escalationAnswer: {
          event: "escalation_answered",
          forStep: "S7",
          answer: "retry-ship-after-human-fix",
          note: "Human resolved the delivery blocker; retry ship.",
        },
      }),
    ).rejects.toThrow(/shipSandbox reached/);

    expect(focusBody).toContain("retry-ship-after-human-fix");
    expect(focusBody).toContain("Human resolved the delivery blocker");
    expect(focusBody).toContain('"forStep": "S7"');
  });
});

// ═══════════════════ auth mounts — container codex config is minimal, NOT host copy (#378) ═══════════════════

describe("#378 RealBackend auth mounts — write a minimal danger-full-access config, never copy the host config.toml", () => {
  /** A host $HOME with codex creds + a host config.toml with host-only keys, plus the claude token. */
  function hostHome(): string {
    const home = mkDir("rb-host-home-");
    const codexDir = join(home, ".codex");
    mkdirSync(codexDir, { recursive: true });
    writeFileSync(join(codexDir, "auth.json"), '{"OPENAI_API_KEY":"sk-host"}');
    writeFileSync(
      join(codexDir, "config.toml"),
      [
        'model = "gpt-5.6-sol"',
        'sandbox_mode = "workspace-write"',
        'notify = ["/Users/host/notify.app"]',
        '[plugins."github@openai-curated"]',
        "enabled = true",
        "",
      ].join("\n"),
    );
    // mountAuth requires the durable claude token file.
    writeFileSync(join(home, ".sc-claude-token"), "sk-claude-host\n");
    return home;
  }

  class AuthBackend extends RealBackend {
    protected override buildOrReuseClone(): string {
      return mkDir("rb-clone-");
    }
    protected override assertIndependentClone(): void {}
    public agentAuth(issueNumber: number): { authDir: string } {
      return this.mountAuth(issueNumber);
    }
    public shipAuth(issueNumber: number): ShipAuth {
      return this.mountShipAuth(issueNumber);
    }
  }

  function backend(home: string): AuthBackend {
    return new AuthBackend({
      sourceRepo: mkDir("rb-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 378,
      home,
    });
  }

  function assertMinimalConfig(dir: string): void {
    expect(readFileSync(join(dir, "auth.json"), "utf8")).toContain("sk-host");
    const config = readFileSync(join(dir, "config.toml"), "utf8");
    expect(config).toContain('sandbox_mode = "danger-full-access"');
    expect(config).not.toContain("workspace-write");
    expect(config).not.toContain("notify");
    expect(config).not.toContain("plugins");
  }

  it("the agent-step mountAuth copies auth.json + writes the minimal config", () => {
    const be = backend(hostHome());
    const { authDir } = be.agentAuth(378);
    assertMinimalConfig(authDir);
  });

  it("the ship mountShipAuth copies auth.json + writes the minimal config", () => {
    const be = backend(hostHome());
    const auth = be.shipAuth(378);
    expect(auth.codexAuthDir).toBeTruthy();
    assertMinimalConfig(auth.codexAuthDir as string);
  });
});

// ═══════════════════ #807 grok auth mount (agent-step mountAuth only) ═══════════════════

describe("#807 mountAuth grok auth copy (fail-closed skip when host absent)", () => {
  class GrokAuthBackend extends RealBackend {
    protected override buildOrReuseClone(): string {
      return mkdtempSync(join(tmpdir(), "grok-auth-clone-"));
    }
    protected override assertIndependentClone(): void {}
    public agentAuth(issueNumber: number): {
      authDir: string;
      claudeToken?: string;
      grokAuthDir?: string;
    } {
      return this.mountAuth(issueNumber);
    }
    public agentBoxConfig(auth: {
      authDir: string;
      claudeToken?: string;
      grokAuthDir?: string;
    }) {
      return this.boxConfig(auth, { role: "coder", soul: "coder" }, 807);
    }
  }

  function mkHome(withGrok: boolean): string {
    const home = mkdtempSync(join(tmpdir(), "grok-auth-home-"));
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tok":"codex"}\n');
    writeFileSync(join(home, ".sc-claude-token"), "sk-claude\n");
    if (withGrok) {
      mkdirSync(join(home, ".grok"), { recursive: true });
      writeFileSync(join(home, ".grok", "auth.json"), '{"https://auth.x.ai::x":{"key":"g"}}\n');
      chmodSync(join(home, ".grok", "auth.json"), 0o600);
    }
    return home;
  }

  function backend(home: string): GrokAuthBackend {
    return new GrokAuthBackend({
      sourceRepo: mkdtempSync(join(tmpdir(), "grok-auth-src-")),
      repo: "Akagilnc/ming-salvage-sim",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: 807,
      home,
    });
  }

  it("copies host ~/.grok/auth.json into a per-issue dir when present", () => {
    const home = mkHome(true);
    const be = backend(home);
    const auth = be.agentAuth(807);
    expect(auth.grokAuthDir).toMatch(new RegExp(`${join(home, ".sc-orchestrator", "grok-auth-807-")}.+`));
    expect(readFileSync(join(auth.grokAuthDir!, "auth.json"), "utf8")).toContain("auth.x.ai");
  });

  it("allocates isolated Grok auth copies for concurrent same-issue launches", () => {
    const home = mkHome(true);
    const be = backend(home);
    const first = be.agentAuth(807);
    const second = be.agentAuth(807);
    expect(first.grokAuthDir).toBeDefined();
    expect(second.grokAuthDir).toBeDefined();
    expect(first.grokAuthDir).not.toBe(second.grokAuthDir);
    expect(readFileSync(join(first.grokAuthDir!, "auth.json"), "utf8")).toContain("auth.x.ai");
    expect(readFileSync(join(second.grokAuthDir!, "auth.json"), "utf8")).toContain("auth.x.ai");
  });

  it("skips grokAuthDir (and the sandbox mount) when host auth is absent", () => {
    const home = mkHome(false);
    const be = backend(home);
    const auth = be.agentAuth(807);
    expect(auth.grokAuthDir).toBeUndefined();
    expect(existsSync(join(home, ".sc-orchestrator", "grok-auth-807"))).toBe(false);
    const cfg = be.agentBoxConfig({ authDir: auth.authDir });
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_GROK_DIR)).toBe(false);
  });

  it("boxConfig mounts the per-issue grok auth dir at SANDBOX_GROK_DIR when present", () => {
    const home = mkHome(true);
    const be = backend(home);
    const auth = be.agentAuth(807);
    const cfg = be.agentBoxConfig(auth);
    expect(
      cfg.mounts.some(
        (m) => m.hostPath === auth.grokAuthDir && m.sandboxPath === SANDBOX_GROK_DIR,
      ),
    ).toBe(true);
  });
});
