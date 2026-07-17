/**
 * #336 — the FAMILY ship step (止于 PR) is a CONTAINER ship WORKER that invokes
 * `gstack-ship` through the unified worker seam.
 *
 * The family ship worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `gstack-ship` over the family base and STOPS at the PR (止于 PR — the online bot
 * cmr + merge are the separate pr-review-loop stage). Completion is clean exit +
 * legal sidecar / typed envelope; the outcome is classified into a
 * {@link ShipWorkerOutcome}, which `dispatchWorker` maps to the full
 * {@link WorkerResult} union (PRD #330 R2):
 *   shipped → completed ShipResult; escalate → escalated.
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
import {
  RealFamilyBackend,
  SHIP_FOCUS_FILENAME,
  type ShipAuth,
} from "../../../src/family/realFamilyBackend.js";
import {
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SANDBOX_SOUL_ENV,
  soulsMount,
  SPAWNED_WORKER_ENV,
} from "../../../src/realBackend.js";
import { cmrWorkerSpec, familyShipWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
import {
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  shipReceiptOutput,
} from "../../../src/receiptRecovery.js";
import {
  SHIP_RECEIPT_TAG,
  shipStationReceiptSchema,
} from "../../../src/stationReceiptContracts.js";
import {
  shipOutcomeFromResult,
  type ShipWorkerOutcome,
} from "../../../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec } from "../../../src/types.js";
import { isRunnerSynthesizedFailureEscalation } from "../../../src/runnerEscalation.js";
import {
  runScriptedStructuredOutput,
  type ScriptedAgent,
} from "../../helpers/scripted-sandcastle-run.js";

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
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

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
  outcome: ReturnType<typeof shipOutcomeFromResult> = {
    kind: "shipped",
    branch: FAMILY_BASE,
    status: "pr_opened",
    pr: "https://gh/pr/9",
  };
  protected override async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
    this.runShipCalls.push({ spec, ctx });
    return this.outcome;
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
  });

  it("the family ship spec is a WRITE/coder single-iteration seat, while cmr is a single clean review pass", () => {
    const spec = familyShipWorkerSpec();
    expect(spec.role).toBe("coder");
    // #899 / ADR 0128: every selected seat is single-iteration.
    expect(spec.maxIter).toBe(1);
    // The cmr pass worker is a clean reviewer boundary. A red outcome returns to
    // the runner, which dispatches coder-fix separately.
    expect(cmrWorkerSpec().role).toBe("verify");
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
    be.outcome = { kind: "escalate", reason: "review ASK", diagnosis: "human must decide scope" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") expect(res.escalation.reason).toContain("review ASK");
  });

  it('a shipped outcome with status "pushed" is completed worker truth', async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: FAMILY_BASE, status: "pushed" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("completed");
  });

  it("completed cargo (no delivery fields) is still a clean ship success, not coder no-commit", async () => {
    // #899 / ADR 0131: exit 0 + no decision gate = success. Missing status/pr
    // cargo must not rewrite the worker into a coder committed:false report,
    // and must not invent a status token.
    const be = fixtured();
    be.outcome = { kind: "completed" };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res).toEqual({
      kind: "completed",
      output: { kind: "ship", branch: FAMILY_BASE },
    });
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
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
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
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
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

  it("pins the configured non-main PR target base in the ship focus", () => {
    // gstack-ship infers the base from the repo default branch (main), so a
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
          providerAuth: { claude: true, grok: true, agy: true },
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
          providerAuth: { claude: true, grok: true, agy: true },
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
          branch: FAMILY_BASE,
          stdout: "<ship>{}</ship>",
          commits: [],
          iterations: [],
          // Typed T2 ship completed (SO was attached on this seat).
          output: { station: "ship", status: "completed" },
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

  it("fails family ship when typed decision Output.object is absent", async () => {
    // #899: SO seat without result.output must not fall through to cargo success.
    class MissingTypedShipBackend extends RealFamilyBackend {
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override async shipContainerRun(
        _spec: WorkerSpec,
        _auth: ShipAuth,
        outcomeLanding?: { path: string; sandboxPath: string },
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomeLanding !== undefined) {
          writeFileSync(
            outcomeLanding.path,
            JSON.stringify({
              status: "pr_opened",
              branch: FAMILY_BASE,
              pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/999",
            }),
            "utf8",
          );
        }
        return {
          branch: FAMILY_BASE,
          stdout: "<ship>{}</ship>",
          commits: [],
          iterations: [],
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new MissingTypedShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-missing-typed-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      b.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toThrow(/typed traffic signal missing/);
  });

  it("attaches T2 ship envelope Output.object for family ship without cargo-shape re-ask", async () => {
    // #919 D: ship seat uses T2 ship envelope on SHIP_RECEIPT_TAG;
    // PR/URL cargo stays on the opaque sidecar channel (never SO).
    class CaptureShipBackend extends RealFamilyBackend {
      public calls: Parameters<typeof sc.run>[0][] = [];
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      /** Typed public probe — no `as unknown as` cast. */
      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls.push(options);
        // Typed T2 ship completed traffic. Delivery cargo is sidecar-only.
        return {
          branch: FAMILY_BASE,
          stdout: '<ship>{"station":"ship","status":"completed"}</ship>',
          commits: [],
          iterations: [],
          output: { station: "ship", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new CaptureShipBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-signal-so-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    const out = await b.probeRunShipWorker(familyShipWorkerSpec(), {
      familyBase: FAMILY_BASE,
    });

    // T2 completed + empty sidecar cargo → completed (exit is success channel).
    expect(out.kind).toBe("completed");
    expect(b.calls).toHaveLength(1);
    expect(b.calls[0]!.output).toMatchObject({
      tag: SHIP_RECEIPT_TAG,
      maxRetries: RECEIPT_MAX_RETRIES,
    });
    // Not decision-gate dual — ship seat owns the T2 ship tag.
    expect(b.calls[0]!.output).not.toMatchObject({ tag: "decision" });
  });
});

// ─── #919 D: ship production T2 envelope SO four-case matrix ────────────────
// Ship attaches shipStationReceiptSchema on SHIP_RECEIPT_TAG; cargo (status/pr)
// stays opaque sidecar. Four-case crosses production runShipWorker + real sc.run.
// #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
describe("#919 ship production T2 envelope SO four-case", () => {
  function shipFourCaseBackend(opts: {
    emissions: ReadonlyArray<{ body: string }>;
    sessionId: string;
    resumable?: boolean;
    name?: string;
    agentOut?: { agent?: ScriptedAgent };
    sandcastleCalls: { n: number };
  }): RealFamilyBackend & {
    probeRunShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ShipWorkerOutcome>;
  } {
    class Backend extends RealFamilyBackend {
      public probeRunShipWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<ShipWorkerOutcome> {
        return this.runShipWorker(spec, ctx);
      }
      protected override sh(): string {
        return "";
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok", ghToken: "gho_ok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        opts.sandcastleCalls.n += 1;
        // Production ship seat must bind T2 ship SO + maxRetries.
        expect(options.output).toEqual(
          expect.objectContaining({
            tag: SHIP_RECEIPT_TAG,
            maxRetries: RECEIPT_MAX_RETRIES,
          }),
        );
        const run = await runScriptedStructuredOutput({
          tag: SHIP_RECEIPT_TAG,
          schema: shipStationReceiptSchema(),
          emissions: opts.emissions,
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: opts.sessionId,
          resumable: opts.resumable,
          name: opts.name,
          cleanups,
          agentOut: opts.agentOut,
        });
        return run.result;
      }
    }
    return new Backend({
      workingRepo: (() => {
        const repo = mkDir("ship-so-four-case-repo-");
        execFileSync("git", ["init", "-q"], { cwd: repo });
        return repo;
      })(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("ship-so-four-case-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });
  }

  it("accepts initial-good T2 ship completed via production ship + real sc.run", async () => {
    // first-good: station:ship status:completed → completed (cargo miss is fine).
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "completed" }),
        },
      ],
      sessionId: "prod-ship-t2-initial-good",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toEqual({ kind: "completed" });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
    expect(agentOut.agent?.resumedSessions).toEqual([undefined]);
  });

  it("accepts T2 ship shipped envelope via production ship + real sc.run", async () => {
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "shipped" }),
        },
      ],
      sessionId: "prod-ship-t2-shipped",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toEqual({ kind: "shipped" });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
  });

  it("recovers T2 ship escalate bad→good via production ship + real sc.run", async () => {
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      station: "ship",
      status: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    };
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "x",
          }),
        },
        { body: JSON.stringify(good) },
      ],
      sessionId: "prod-ship-t2-recover",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).resolves.toMatchObject({
      kind: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    });
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(2);
    expect(agentOut.agent?.resumedSessions).toEqual([
      undefined,
      "prod-ship-t2-recover",
    ]);
  });

  it("propagates StructuredOutputError when ship T2 envelope maxRetries exhaust", async () => {
    // exhaust SOE → Action non-zero for #598; never invent cargo success.
    const sandcastleCalls = { n: 0 };
    const agentOut: { agent?: ScriptedAgent } = {};
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "",
          }),
        },
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "",
            diagnosis: "x",
          }),
        },
        {
          body: JSON.stringify({
            station: "ship",
            status: "escalate",
            reason: "x",
            diagnosis: "",
          }),
        },
      ],
      sessionId: "prod-ship-t2-exhausted",
      agentOut,
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toSatisfy((err: unknown) => {
      // FiberFailure/ExecError wrap is load-dependent; recovery class is the contract.
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    // One production sc.run; native same-session resumes are inside it.
    expect(sandcastleCalls.n).toBe(1);
    expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
  });

  it("classifies non-resumable ship T2 envelope maxRetries as recovery failure", async () => {
    const sandcastleCalls = { n: 0 };
    const be = shipFourCaseBackend({
      emissions: [
        {
          body: JSON.stringify({ station: "ship", status: "completed" }),
        },
      ],
      sessionId: "prod-ship-t2-nonresumable",
      resumable: false,
      name: "grok",
      sandcastleCalls,
    });
    await expect(
      be.probeRunShipWorker(familyShipWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls.n).toBe(1);
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
