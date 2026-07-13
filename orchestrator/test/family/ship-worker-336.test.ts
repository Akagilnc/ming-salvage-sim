/**
 * #336 — the FAMILY ship step (止于 PR) is a CONTAINER ship WORKER that invokes
 * `gstack-ship`, replacing the inline `RealFamilyBackend.openFamilyPr` (a bare
 * `git push` + `gh pr create`).
 *
 * The family ship worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `gstack-ship` over the family base and STOPS at the PR (止于 PR — the online bot
 * cmr + merge are the separate pr-review-loop stage). Its `<ship>` tag is gated on
 * the completion signal then classified into a {@link ShipWorkerOutcome}, which
 * `dispatchWorker` maps to the full {@link WorkerResult} union (PRD #330 R2):
 *   shipped → completed ShipResult; escalate → escalated; failed → failed;
 *   malformed → malformed.
 *
 * Tested WITHOUT a real container (mirrors #335's cmr-worker test): the
 * `runShipWorker` seam is fixtured; the `dispatchWorker(ship)` routing is asserted
 * at the seam.
 */

import { execFileSync } from "node:child_process";
import {
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
import { RealFamilyBackend, SHIP_FOCUS_FILENAME } from "../../src/family/realFamilyBackend.js";
import {
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  soulsMount,
  SPAWNED_WORKER_ENV,
} from "../../src/realBackend.js";
import { cmrWorkerSpec, familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";
import type { ShipAuth } from "../../src/realBackend.js";
import type { ShipWorkerOutcome } from "../../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec } from "../../src/types.js";

/**
 * Read the model id an agent was built with off an agent — its CLI model flag is
 * the only externally-observable proof of the model
 * (the agent object exposes no scalar model field).
 */
function modelOfAgent(agent: unknown): string {
  const build = (agent as { buildPrintCommand?: (p: string) => { command: string } })
    .buildPrintCommand;
  if (typeof build !== "function") throw new Error("agent has no buildPrintCommand");
  const m = /(?:--model|-m) '([^']+)'/.exec(build("x").command);
  if (m === null) throw new Error(`no model flag in: ${build("x").command}`);
  return m[1]!;
}

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

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

const FAMILY_BASE = "feat/330-pure-scheduler";

/** A family backend whose container `runShipWorker` seam is fixtured (no sc.run). */
class FixturedShipBackend extends RealFamilyBackend {
  runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
  outcome: ShipWorkerOutcome = {
    kind: "shipped",
    branch: FAMILY_BASE,
    status: "pr_opened",
    pr: "https://gh/pr/9",
  };
  openFamilyPrCount = 0;
  protected override async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ShipWorkerOutcome> {
    this.runShipCalls.push({ spec, ctx });
    return this.outcome;
  }
  // The inline openFamilyPr must NEVER back the ship worker path (#336 replaces it).
  override async openFamilyPr(): Promise<{ url: string }> {
    this.openFamilyPrCount += 1;
    throw new Error("openFamilyPr must not be reached — family ship via gstack-ship (#336)");
  }
}

function fixtured(): FixturedShipBackend {
  return new FixturedShipBackend({
    workingRepo: mkDir("ship-repo-"),
    familyBase: FAMILY_BASE,
    ledgerDir: mkDir("ship-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "ming-orchestrator-coder:latest",
  });
}

describe("#336 RealFamilyBackend.dispatchWorker — the family ship worker", () => {
  it("dispatches the family ship spec to runShipWorker — gstack-ship, 止于 PR", async () => {
    const be = fixtured();
    await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(be.runShipCalls.length).toBe(1);
    const spec = be.runShipCalls[0]!.spec;
    expect(spec.kind).toBe("ship");
    expect(spec.skill).toBe("gstack-ship");
    expect(be.openFamilyPrCount).toBe(0); // never the inline openFamilyPr
  });

  it("the family ship spec is a WRITE/coder worker with an iterative budget, while cmr is a single clean review pass", () => {
    const spec = familyShipWorkerSpec();
    expect(spec.role).toBe("coder");
    expect(spec.maxIter).toBeGreaterThan(1);
    // The cmr pass worker is a clean reviewer boundary. A red outcome returns to
    // the runner, which dispatches coder-fix separately.
    expect(cmrWorkerSpec().role).toBe("reviewer");
    expect(cmrWorkerSpec().contextRetention).toBe("clean");
    expect(cmrWorkerSpec().maxIter).toBe(1);
  });

  it("a shipped outcome ⇒ WorkerResult.completed with a ShipResult payload", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: FAMILY_BASE, status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "ship") {
      expect(res.output.branch).toBe(FAMILY_BASE);
      expect(res.output.pr).toBe("u");
      expect(res.output.prHead).toBeUndefined();
      expect(res.output.status).toBe("pr_opened");
    } else {
      throw new Error("expected a completed ship payload");
    }
  });

  it("an escalate outcome ⇒ WorkerResult.escalated (a genuine block)", async () => {
    const be = fixtured();
    be.outcome = { kind: "escalate", reason: "review ASK", diagnosis: "human must decide scope", escalationKind: "decision" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") expect(res.escalation.reason).toContain("review ASK");
  });

  it("a failed outcome ⇒ WorkerResult.failed (a hard ship/test failure)", async () => {
    const be = fixtured();
    be.outcome = { kind: "failed", reason: "tests red", diagnosis: "vitest exited 1" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("failed");
  });

  it("a malformed outcome ⇒ WorkerResult.malformed (never silently a success)", async () => {
    const be = fixtured();
    be.outcome = { kind: "malformed", reason: "no <ship> tag" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("malformed");
  });

  it('a shipped outcome with status "pushed" is completed worker truth', async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: FAMILY_BASE, status: "pushed" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("completed");
  });

  it('a shipped "pr_opened" with no cargo URL remains completed', async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: FAMILY_BASE, status: "pr_opened" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("completed");
  });

  it("a family ship worker without familyBase throws (the worker ships the base)", async () => {
    const be = fixtured();
    await expect(be.dispatchWorker(familyShipWorkerSpec(), {})).rejects.toThrow(/familyBase/);
  });

  it("a shipped outcome whose branch differs from familyBase remains a worker outcome", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: "main", status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res).toMatchObject({
      kind: "completed",
      output: { kind: "ship", branch: "main", status: "pr_opened", pr: "u" },
    });
  });

  it("a shipped pr_opened on the correct family base ⇒ completed (identity holds)", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: FAMILY_BASE, status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("completed");
  });


  it("the cmr worker is still routed to its own (cmr) path, NOT the ship seam", async () => {
    // #336 owns ship; a cmr worker must still go through runCmrWorker, not runShipWorker.
    const be = fixtured();
    // No familyBaseStartHead → the cmr fail-closed escalate proves it took the cmr
    // path (runCmrWorker), not the ship seam.
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    expect(be.runShipCalls.length).toBe(0);
  });
});

describe("#336 the inline family openFamilyPr is no longer the ship path", () => {
  it("a family ship dispatch never calls openFamilyPr (gstack-ship replaces it)", async () => {
    const be = fixtured();
    await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(be.openFamilyPrCount).toBe(0);
  });
});

// ═══════════════════ shipSandboxConfig — ship soul + codex auth + claude token ═══════════════════

describe("#336 family shipSandboxConfig — the WRITE-soul ship sandbox", () => {
  class ConfigBackend extends RealFamilyBackend {
    public config(auth: ShipAuth): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.shipSandboxConfig(auth);
    }
  }
  function cfg(): ConfigBackend {
    return new ConfigBackend({
      workingRepo: mkDir("ship-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
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

  it("mounts isolated grok auth when the family ship route selects grok", () => {
    const c = cfg().config({
      codexAuthDir: "/tmp/codex",
      grokAuthDir: "/tmp/family-grok-auth",
      claudeToken: "tok",
    });
    expect(c.mounts).toContainEqual({
      hostPath: "/tmp/family-grok-auth",
      sandboxPath: SANDBOX_GROK_DIR,
    });
  });

  it("family shipSandboxConfig includes soulsMount() shape (hostPath/sandboxPath/readonly:true) (#372)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    const expected = soulsMount(realSoulsDir);
    expect(c.mounts).toContainEqual(expected);
  });

  it("a missing codex auth degrades the mount but still ships under the ship soul", () => {
    const c = cfg().config({ claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("ship");
  });

  it("exports the gh token as GH_TOKEN so the in-container family `gh pr create` is authenticated (cmr S336 r10 P1)", () => {
    // The family ship worker's happy path is a family PR (`gh pr create --base`). The
    // 2b image bakes gh but no gh AUTH; the host token (keyring, not portable
    // hosts.yml) is injected as the standard GH_TOKEN env var.
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok", ghToken: "gho_fam" });
    expect(c.env[SANDBOX_GH_TOKEN_ENV]).toBe("gho_fam");
  });

  it("omits GH_TOKEN when no gh token is present (the pure seam stays tolerant; the REQUIRE-gh preflight lives upstream in runShipWorker)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.env[SANDBOX_GH_TOKEN_ENV]).toBeUndefined();
  });

  it("marks the family ship container as an orchestrator-spawned, non-interactive session (gstack-ship auto-decides its P1 gate)", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.env.OPENCLAW_SESSION).toBe("1");
    expect(c.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });
});

// ═══════════════════ runShipWorker fail-closed on a missing Claude WORKER auth (cmr S336 r8) ═══════════════════

describe("#336 family runShipWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The family ship worker is the container's TOP-LEVEL claude (`agent: sc.claudeCode`),
   * so the Claude OAuth token is its OWN auth, not a degradable codex/gh leg. Absent,
   * the worker cannot start and never emits a `<ship>` verdict; letting it through
   * would throw out of `sc.run` (NOT a structured escalate), bypassing the
   * dispatchShipWorker → verifyCmr WorkerResult routing. So `runShipWorker` must
   * escalate BEFORE spinning the container (and before the checkout / focus write)
   * when `mountShipAuth().claudeToken` is absent — matching the cmr worker's claude
   * preflight (cmr-worker-335.test.ts:512-557). codex/gh auth stays best-effort.
   */
  class NoClaudeAuthBackend extends RealFamilyBackend {
    containerReached = false;
    checkoutReached = false;
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
    protected override sh(): string {
      this.checkoutReached = true;
      throw new Error("git checkout should not run when the worker has no auth");
    }
    protected override async shipContainerRun(): Promise<never> {
      this.containerReached = true;
      throw new Error("shipContainerRun should not run when the worker has no auth");
    }
  }
  function noAuth(): NoClaudeAuthBackend {
    return new NoClaudeAuthBackend({
      workingRepo: mkDir("ship-noauth-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-noauth-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("no Claude worker token ⇒ escalate, never checks out / spins the container", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const be = noAuth();
    const outcome = await be.run(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/claude|token|auth/i);
      expect(outcome.diagnosis).toMatch(/cannot start without CLAUDE_CODE_OAUTH_TOKEN/i);
    }
    expect(be.checkoutReached).toBe(false);
    expect(be.containerReached).toBe(false);
  });

  it("dispatchWorker routes the no-auth escalate to a not-passed (escalated) WorkerResult", async () => {
    const be = noAuth();
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/claude|token|auth/i);
    }
  });
});

// ═══════════════════ runShipWorker fail-closed on a missing gh auth (cmr S336 r10 P1) ═══════════════════

describe("#336 family runShipWorker — fail-closed when gh auth is missing", () => {
  /**
   * gh auth is a HARD requirement for the family delivery: the family ship's ONLY
   * accepted outcome is "pr_opened" (family_ship.md), which gstack-ship reaches via
   * `gh pr create --base`. The 2b image bakes the gh CLI but NO gh auth. Without it the
   * worker would run the whole pipeline only to fail at `gh pr create` — an opaque late
   * failure, not the cleaner escalate续跑. So runShipWorker preflights the gh token
   * (like the claude token, cmr S336 r8) BEFORE the checkout / focus write / container.
   * codex auth stays best-effort (in-container diff review only).
   */
  class NoGhAuthBackend extends RealFamilyBackend {
    containerReached = false;
    checkoutReached = false;
    public run(spec: WorkerSpec, ctx: DispatchContext): Promise<ShipWorkerOutcome> {
      return (
        this as unknown as {
          runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome>;
        }
      ).runShipWorker(spec, ctx);
    }
    // claude + codex present, gh token ABSENT (the family PR cannot be opened).
    protected override mountShipAuth(): ShipAuth {
      return { codexAuthDir: "/x/codex", claudeToken: "tok" };
    }
    protected override sh(): string {
      this.checkoutReached = true;
      throw new Error("git checkout should not run when gh auth is missing");
    }
    protected override async shipContainerRun(): Promise<never> {
      this.containerReached = true;
      throw new Error("shipContainerRun should not run when gh auth is missing");
    }
  }
  function noGh(): NoGhAuthBackend {
    return new NoGhAuthBackend({
      workingRepo: mkDir("ship-nogh-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-nogh-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("no gh token ⇒ escalate, never checks out / spins the container", async () => {
    const be = noGh();
    const outcome = await be.run(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/gh|github/i);
      expect(outcome.diagnosis).toMatch(/gh auth|GH_TOKEN|gh pr create/i);
    }
    expect(be.checkoutReached).toBe(false);
    expect(be.containerReached).toBe(false);
  });

  it("dispatchWorker routes the missing-gh escalate to a not-passed (escalated) WorkerResult", async () => {
    const be = noGh();
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/gh|github/i);
    }
  });
});

// ═══════════════════ writeShipFocusFile — pins the CONFIGURED PR target base (cmr S336 r5) ═══════════════════

describe("#336 writeShipFocusFile — threads the configured PR target base into the ship worker", () => {
  /** Expose the focus-file seam over a REAL temp git repo (so the exclude path resolves). */
  class FocusShipBackend extends RealFamilyBackend {
    public focus(ctx: {
      familyBase: string;
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }): void {
      this.writeShipFocusFile(ctx as never);
    }
  }
  function realRepo(): string {
    const repo = mkDir("ship-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }
  function be(over: Partial<{ base: string; repo: string }> = {}): FocusShipBackend {
    return new FocusShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-focus-ledger-"),
      repo: over.repo ?? "Akagilnc/ming-salvage-sim",
      base: over.base ?? "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("pins the configured non-main PR target base (the openFamilyPr --base contract)", () => {
    // The legacy openFamilyPr opened the PR with `gh pr create --base this.opts.base`.
    // gstack-ship instead INFERS the base from the repo default branch (main), so a
    // configured non-main target (an integration branch) would silently regress to a
    // main-targeted PR. The focus file MUST pin the configured base so the worker
    // overrides gstack-ship's inference.
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({ familyBase: FAMILY_BASE });
    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("integ/291-wave3");
    expect(body).toContain(FAMILY_BASE);
  });

  it("pins a 'develop' configured base + the family base branch + the repo slug", () => {
    const backend = be({ base: "develop", repo: "Akagilnc/ming-salvage-sim" });
    backend.focus({ familyBase: FAMILY_BASE });
    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("develop");
    expect(body).toContain(FAMILY_BASE);
    expect(body).toContain("Akagilnc/ming-salvage-sim");
  });

  it("git-ignores the focus file (info/exclude) so the ship never commits it", () => {
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({ familyBase: FAMILY_BASE });
    const exclude = readFileSync(join(backend["opts"].workingRepo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(SHIP_FOCUS_FILENAME);
  });

  it("threads a human escalation answer into the ship focus file", () => {
    const backend = be({ base: "integ/291-wave3" });
    backend.focus({
      familyBase: FAMILY_BASE,
      escalationAnswer: {
        event: "escalation_answered",
        answer: "continue-same-class",
        note: "Human approved retrying the family ship gate.",
      },
    });

    const body = readFileSync(join(backend["opts"].workingRepo, SHIP_FOCUS_FILENAME), "utf8");
    expect(body).toContain("Human escalation answer (#439, data-only)");
    expect(body).toContain("continue-same-class");
    expect(body).toContain("Human approved retrying the family ship gate.");
    expect(body).toMatch(/must not override.*GitHub repo.*PR target base.*PR head branch/is);
  });

  it("runShipWorker writes the focus file BEFORE the container runs (so the worker can read it)", async () => {
    // The worker reads .ship-focus.md FIRST (family_ship.md). Prove runShipWorker
    // produces it before the container spins — trap the container call with a
    // sentinel and assert the focus file is ALREADY on disk when it fires (and that
    // the family base was checked out, i.e. the focus write did not displace the
    // existing checkout contract).
    let focusBodyAtRun: string | undefined;
    class SeamBackend extends RealFamilyBackend {
      // Stub the only real-I/O dependency runShipWorker has besides the focus write:
      // the git checkout (the temp repo has no `integ/291-wave3` ref) and sc.run.
      protected override sh(): string {
        return "";
      }
      // The worker's OWN claude token + gh auth ARE present (cmr S336 r8 + r10) — this
      // test isolates the focus-write ordering from the auth preflights, so provide
      // BOTH so runShipWorker proceeds past the preflights to the focus write + container.
      protected override mountShipAuth(): ShipAuth {
        return {
          claudeToken: "tok",
          codexAuthDir: "/x/codex",
          grokAuthDir: "/x/grok",
          ghToken: "gho_ok",
          providerAuth: { claude: true, grok: true },
        };
      }
      protected override async shipContainerRun(): Promise<never> {
        // Capture the focus-file state at the moment the container would launch.
        focusBodyAtRun = readFileSync(
          join(this["opts"].workingRepo, SHIP_FOCUS_FILENAME),
          "utf8",
        );
        throw new Error("SENTINEL: container reached");
      }
    }
    const b = new SeamBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-focus-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "integ/291-wave3",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
    await expect(
      (b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<unknown> }).runShipWorker(
        familyShipWorkerSpec(),
        { familyBase: FAMILY_BASE },
      ),
    ).rejects.toThrow(/SENTINEL/);
    expect(focusBodyAtRun).toBeDefined();
    expect(focusBodyAtRun).toContain("integ/291-wave3");
  });

  it("family ship with billingPool=grok-build launches the grok provider", async () => {
    let providerAtLaunch: string | undefined;
    class ProviderBackend extends RealFamilyBackend {
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return {
          claudeToken: "tok",
          codexAuthDir: "/x/codex",
          grokAuthDir: "/x/grok",
          ghToken: "gho_ok",
          providerAuth: { claude: true, grok: true },
        };
      }
      protected override async shipContainerRun(
        spec: WorkerSpec,
        _auth: ShipAuth,
        _outcomeLanding?: { path: string; sandboxPath: string },
        ctx?: Pick<DispatchContext, "billingPool">,
      ): Promise<never> {
        providerAtLaunch = this.agentForSpec(spec, ctx).name;
        throw new Error("SENTINEL: provider captured");
      }
    }
    const b = new ProviderBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-provider-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      (b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<unknown> }).runShipWorker(
        { ...familyShipWorkerSpec(), model: "grok-4.5" },
        { familyBase: FAMILY_BASE, billingPool: "grok-build" },
      ),
    ).rejects.toThrow(/SENTINEL/);
    expect(providerAtLaunch).toBe("grok");
  });

  it("runShipWorker removes the temporary outcome sidecar directory after parsing it", async () => {
    let outcomePathAtRun: string | undefined;
    class SeamBackend extends RealFamilyBackend {
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      protected override async shipContainerRun(
        _spec: WorkerSpec,
        _auth: ShipAuth,
        outcomeLanding?: { path: string; sandboxPath: string },
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomeLanding === undefined) {
          throw new Error("expected an outcome sidecar landing");
        }
        outcomePathAtRun = outcomeLanding.path;
        writeFileSync(
          outcomeLanding.path,
          JSON.stringify({
            status: "pr_opened",
            branch: FAMILY_BASE,
            pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/999",
          }),
          "utf8",
        );
        return {
          stdout: "<ship>{}</ship>",
          completionSignal: "SHIP_STEP_COMPLETE",
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new SeamBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-outcome-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    const out = await (
      b as unknown as { runShipWorker(s: WorkerSpec, c: DispatchContext): Promise<ShipWorkerOutcome> }
    ).runShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });

    expect(out.kind).toBe("shipped");
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });
});

// ═══════════════════ model-id contract (cmr S336 r7 P1) — family ship + cmr workers
// derive the model from the spec via the SAME validated `modelIdForSlug` mapping the
// single-slice ship path uses, NOT a hardcoded id. The pre-fix family ship path pinned
// `claude-sonnet-4-5` (a hardcoded constant), bypassing modelIdForSlug AND diverging
// from the verified `sonnet → claude-sonnet-5` mapping `familyShipWorkerSpec().model`
// resolves to. The pure `agentForSpec` seam is the load-bearing point both runs build
// their agent through — assert it directly (mirrors how modelIdForSlug/soulForStep are
// the testable seams on the single-slice path).
describe("#336 family workers — model id is spec-derived via modelIdForSlug (cmr S336 r7 P1)", () => {
  class SeamBackend extends RealFamilyBackend {
    public agent(spec: WorkerSpec): unknown {
      return (this as unknown as { agentForSpec(s: WorkerSpec): unknown }).agentForSpec(spec);
    }
  }
  function seam(): SeamBackend {
    return new SeamBackend({
      workingRepo: mkDir("model-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("model-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("the family SHIP worker resolves to claude-sonnet-5 (the 'sonnet' slug), NOT a hardcoded claude-sonnet-4-5", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = familyShipWorkerSpec();
    expect(spec.model).toBe("sonnet");
    const model = modelOfAgent(seam().agent(spec));
    expect(model).toBe(modelIdForSlug("sonnet"));
    expect(model).toBe("claude-sonnet-5");
    // Regression guard for the r7 bug: never the old hardcoded id.
    expect(model).not.toBe("claude-sonnet-4-5");
  });

  // Symmetry: the family CMR worker (the OTHER family WorkerSpec-driven sc.run in this
  // class) must likewise derive its model from the spec via the same seam — not a
  // standalone constant that could drift from `cmrWorkerSpec().model`.
  it("the family CMR worker resolves to gpt-5.6-sol via the same seam", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = cmrWorkerSpec();
    expect(spec.model).toBe("gpt-5.6-sol");
    const model = modelOfAgent(seam().agent(spec));
    expect(model).toBe(modelIdForSlug("gpt-5.6-sol"));
    expect(model).toBe("gpt-5.6-sol");
  });
});

// ═══════════════════ mountShipAuth — container codex config is minimal, NOT host copy (#378) ═══════════════════

describe("#378 family mountShipAuth — writes a minimal danger-full-access config, never copies the host config.toml", () => {
  class AuthBackend extends RealFamilyBackend {
    public auth(): ShipAuth {
      return this.mountShipAuth();
    }
  }

  function hostHomeWithCodexConfig(): string {
    const home = mkDir("ship-host-home-");
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
    return home;
  }

  it("copies auth.json but WRITES a minimal config.toml (danger-full-access, never the host copy)", () => {
    const be = new AuthBackend({
      workingRepo: mkDir("ship-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: hostHomeWithCodexConfig(),
    });
    const auth = be.auth();
    expect(auth.codexAuthDir).toBeTruthy();
    const dir = auth.codexAuthDir as string;

    expect(readFileSync(join(dir, "auth.json"), "utf8")).toContain("sk-host");

    const config = readFileSync(join(dir, "config.toml"), "utf8");
    expect(config).toContain('sandbox_mode = "danger-full-access"');
    expect(config).not.toContain("workspace-write");
    expect(config).not.toContain("notify");
    expect(config).not.toContain("plugins");
  });
});
