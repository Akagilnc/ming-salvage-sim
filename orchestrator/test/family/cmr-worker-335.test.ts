/**
 * #335 — the family integrated cmr step is a CONTAINER cmr WORKER that invokes
 * the real `ak-cross-m-review`, replacing the runner-internal 3-CLI 手搓
 * (`DriverFamilyBackend.runCmr`'s direct codex/claude/agy fan-out).
 *
 * The cmr worker = the 2b container's TOP-LEVEL claude; it `Skill`-invokes
 * `ak-cross-m-review` (which itself fans out 1 Agent + 2 CLI legs inside the
 * container — proven in #333), FRESH each round (cross-model independence). The
 * worker returns a BARE `{converged, reason?}` verdict (PRD #330 R2: the family
 * cmr consumer `verifyCmr.ts` is escalate-on-red, NO fix-loop, so no findings
 * array is required). A `red` verdict is `WorkerResult.completed` (a CmrResult
 * payload), NOT `failed`.
 *
 * Tested WITHOUT a real container:
 *   - parseCmrOutcome: the `<cmr>` tag → converged / red / escalate / malformed;
 *   - cmrOutcomeFromResult: the completion-signal gate (an unsignaled run is NOT a
 *     pass — mirrors the merger gate);
 *   - RealFamilyBackend.dispatchWorker(cmr): routes ak-cross-m-review + FRESH +
 *     READ-ONLY soul through the injected `runCmrWorker` seam and wraps the verdict
 *     into a WorkerResult (converged → completed; red → completed; escalate →
 *     escalated; malformed → malformed);
 *   - cmrSandboxConfig: wires the agy auth runtime-mount (writable dir) + codex
 *     auth + the claude token (the #333 gotcha: agy needs its file token mounted,
 *     else the cmr leg degrades to codex-only);
 *   - the deleted-fanout regression: the 手搓 symbols no longer exist on the
 *     familyDriver module.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  type CmrAuth,
  type CmrWorkerOutcome,
} from "../../src/family/realFamilyBackend.js";
import {
  SANDBOX_CODEX_DIR,
  SANDBOX_SOUL_ENV,
} from "../../src/realBackend.js";
import { cmrWorkerSpec, familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";
import type { ShipWorkerOutcome } from "../../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec } from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");

const cleanups: string[] = [];
afterEach(() => {
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

function makeBackend(over?: {
  home?: string;
  ledgerDir?: string;
}): RealFamilyBackend {
  return new RealFamilyBackend({
    workingRepo: mkDir("cmr-repo-"),
    familyBase: "feat/330-pure-scheduler",
    ledgerDir: over?.ledgerDir ?? mkDir("cmr-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    imageName: "ming-orchestrator-coder:latest",
    home: over?.home,
  });
}

// ═══════════════════════ 1. parseCmrOutcome (pure tag parse) ═══════════════════════

describe("#335 parseCmrOutcome — the <cmr> verdict tag", () => {
  it("converged:true ⇒ a converged outcome", () => {
    const o = parseCmrOutcome('noise\n<cmr>{"converged": true}</cmr>\n');
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("converged:false + reason ⇒ a red outcome carrying the reason", () => {
    const o = parseCmrOutcome(
      '<cmr>{"converged": false, "reason": "cross-slice field-name mismatch"}</cmr>',
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") {
      expect(o.converged).toBe(false);
      expect(o.reason).toBe("cross-slice field-name mismatch");
    }
  });

  it("an escalate object ⇒ an escalate outcome (the worker is model-stuck)", () => {
    const o = parseCmrOutcome(
      '<cmr>{"escalate": {"reason": "skill missing", "diagnosis": "ak-cross-m-review not on PATH"}}</cmr>',
    );
    expect(o.kind).toBe("escalate");
    if (o.kind === "escalate") {
      expect(o.reason).toContain("skill missing");
      expect(o.diagnosis).toContain("not on PATH");
    }
  });

  it("only the LAST <cmr> tag is read (the worker may iterate)", () => {
    const o = parseCmrOutcome(
      '<cmr>{"converged": false}</cmr>\nlater…\n<cmr>{"converged": true}</cmr>',
    );
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("no <cmr> tag ⇒ malformed (never silently a pass)", () => {
    const o = parseCmrOutcome("I reviewed everything, looks fine.");
    expect(o.kind).toBe("malformed");
  });

  it("a non-JSON / non-object <cmr> body ⇒ malformed (never a pass)", () => {
    expect(parseCmrOutcome("<cmr>not json</cmr>").kind).toBe("malformed");
    expect(parseCmrOutcome("<cmr>null</cmr>").kind).toBe("malformed");
    expect(parseCmrOutcome("<cmr>true</cmr>").kind).toBe("malformed");
  });

  it("a <cmr> object with no boolean converged and no escalate ⇒ malformed", () => {
    expect(parseCmrOutcome('<cmr>{"foo": 1}</cmr>').kind).toBe("malformed");
  });
});

// ═══════════════════════ 2. cmrOutcomeFromResult (signal gate) ═══════════════════════

describe("#335 cmrOutcomeFromResult — completion-signal gate (mirrors the merger gate)", () => {
  const SIGNAL = cmrWorkerSpec().completionSignal;

  it("a signaled converged run ⇒ a verdict outcome", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: SIGNAL,
      stdout: '<cmr>{"converged": true}</cmr>',
    });
    expect(o.kind).toBe("verdict");
    if (o.kind === "verdict") expect(o.converged).toBe(true);
  });

  it("an UNSIGNALED run ⇒ escalate (a complete-but-unsignaled run is NOT a pass)", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<cmr>{"converged": true}</cmr>',
    });
    expect(o.kind).toBe("escalate");
  });

  it("a wrong-signal run ⇒ escalate", () => {
    const o = cmrOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: '<cmr>{"converged": true}</cmr>',
    });
    expect(o.kind).toBe("escalate");
  });
});

// ═══════════════════ 3. dispatchWorker(cmr) — routes the skill + wraps verdict ═══════════════════

describe("#335 RealFamilyBackend.dispatchWorker — the cmr worker", () => {
  /** A backend whose container `runCmrWorker` seam is fixtured (no real sc.run). */
  class FixturedCmrBackend extends RealFamilyBackend {
    runCmrCalls: { spec: ReturnType<typeof cmrWorkerSpec>; ctx: DispatchContext }[] = [];
    runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    outcome: CmrWorkerOutcome = { kind: "verdict", converged: true };
    protected override async runCmrWorker(
      spec: ReturnType<typeof cmrWorkerSpec>,
      ctx: DispatchContext,
    ): Promise<CmrWorkerOutcome> {
      this.runCmrCalls.push({ spec, ctx });
      return this.outcome;
    }
    // #336: a ship spec routes to the ship worker seam (NOT the cmr seam). Fixture it
    // so this test asserts the routing without a real container / host claude token
    // (the pre-#336 version relied on the legacy openFamilyPr `git push` throwing,
    // which is now both stale and host-fragile — cmr S336 r9).
    protected override async runShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ShipWorkerOutcome> {
      this.runShipCalls.push({ spec, ctx });
      return { kind: "shipped", branch: ctx.familyBase!, status: "pr_opened", pr: "https://gh/pr/9" };
    }
  }

  function fixtured(): FixturedCmrBackend {
    return new FixturedCmrBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  it("dispatches the cmr worker spec to runCmrWorker — ak-cross-m-review + FRESH + READ-ONLY", async () => {
    const be = fixtured();
    await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "feat/330-pure-scheduler" });
    expect(be.runCmrCalls.length).toBe(1);
    const spec = be.runCmrCalls[0]!.spec;
    expect(spec.kind).toBe("cmr");
    expect(spec.skill).toBe("ak-cross-m-review");
    expect(spec.session).toBe("fresh");
    expect(spec.contextRetention).toBe("clean");
    expect(spec.soul).toBe("READ-ONLY");
  });

  it("a converged verdict ⇒ WorkerResult.completed with a bare cmr payload", async () => {
    const be = fixtured();
    be.outcome = { kind: "verdict", converged: true };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "cmr") {
      expect(res.output.converged).toBe(true);
    } else {
      throw new Error("expected completed cmr payload");
    }
  });

  it("a red verdict ⇒ WorkerResult.completed (NOT failed), carrying the reason", async () => {
    const be = fixtured();
    be.outcome = { kind: "verdict", converged: false, reason: "seam mismatch" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "cmr") {
      expect(res.output.converged).toBe(false);
      expect(res.output.reason).toBe("seam mismatch");
    } else {
      throw new Error("expected completed cmr payload");
    }
  });

  it("an escalate outcome ⇒ WorkerResult.escalated (model-stuck, not a verdict)", async () => {
    const be = fixtured();
    be.outcome = { kind: "escalate", reason: "skill missing", diagnosis: "not on PATH" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toContain("skill missing");
    }
  });

  it("a malformed outcome ⇒ WorkerResult.malformed (never silently a pass)", async () => {
    const be = fixtured();
    be.outcome = { kind: "malformed", reason: "no <cmr> tag" };
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("malformed");
  });

  it("forwards llmResolvedChildren on the DispatchContext to the cmr worker", async () => {
    const be = fixtured();
    await be.dispatchWorker(cmrWorkerSpec(), {
      familyBase: "fb",
      llmResolvedChildren: [42, 43],
    });
    expect(be.runCmrCalls[0]!.ctx.llmResolvedChildren).toEqual([42, 43]);
  });

  it("a family worker without familyBase throws (the worker reviews the base diff)", async () => {
    const be = fixtured();
    await expect(be.dispatchWorker(cmrWorkerSpec(), {})).rejects.toThrow(/familyBase/);
  });

  it("the ship worker is NOT handled by the cmr path — routed to the ship worker seam (#336)", async () => {
    // This slice (#335) owns cmr only. A ship spec routes to the ship worker seam
    // (dispatchShipWorker → runShipWorker, #336), NOT through runCmrWorker. (The full
    // ship contract — gstack-ship routing, pr_opened narrowing, branch identity — is
    // covered by ship-worker-336.test.ts; here we only assert the cmr seam is untouched.)
    const be = fixtured();
    be.outcome = { kind: "verdict", converged: true };
    const res = await be.dispatchWorker(familyShipWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("completed"); // the fixtured ship outcome, not the cmr path
    expect(be.runShipCalls.length).toBe(1); // reached the ship worker seam
    expect(be.runCmrCalls.length).toBe(0); // the cmr worker seam was NOT touched
  });
});

// ═══════════════════ 4. cmrSandboxConfig — agy auth runtime-mount + codex + claude ═══════════════════

describe("#335 cmrSandboxConfig — wires the agy auth runtime-mount (writable dir)", () => {
  /** Expose the protected pure config seam + a canned-auth path. */
  class ConfigBackend extends RealFamilyBackend {
    public config(auth: CmrAuth): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.cmrSandboxConfig(auth);
    }
  }

  function cfgBackend(): ConfigBackend {
    return new ConfigBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  const auth = {
    codexAuthDir: "/tmp/cmr-codex-auth",
    agyDir: "/tmp/cmr-agy",
    claudeToken: "tok-xyz",
  };

  it("mounts the agy writable dir onto the antigravity token path (the #333 gotcha)", () => {
    const cfg = cfgBackend().config(auth);
    const agyMount = cfg.mounts.find((m) => m.sandboxPath === SANDBOX_AGY_DIR);
    expect(agyMount).toBeDefined();
    expect(agyMount!.hostPath).toBe("/tmp/cmr-agy");
    // The agy leg WRITES into its config dir → it must NOT be read-only.
    expect(agyMount!.readonly).not.toBe(true);
  });

  it("still mounts codex auth + injects the claude token + READ-ONLY soul (all three legs)", () => {
    const cfg = cfgBackend().config(auth);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok-xyz");
    expect(cfg.env[SANDBOX_SOUL_ENV]).toBe("READ-ONLY");
  });

  it("the antigravity token path is the host-mirrored gemini path (#333 contract)", () => {
    expect(SANDBOX_AGY_DIR).toBe("/home/agent/.gemini/antigravity-cli");
  });

  it("a leg whose auth is ABSENT degrades — no mount/env, never a crash (codex cmr R1)", () => {
    // agy token absent ⇒ no agy mount, but the rest still mount (the 降级链).
    const noAgy = cfgBackend().config({
      codexAuthDir: "/tmp/cmr-codex-auth",
      claudeToken: "tok",
    });
    expect(noAgy.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(false);
    expect(noAgy.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(noAgy.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");

    // claude token absent ⇒ no env var (the Claude Agent leg degrades).
    const noClaude = cfgBackend().config({ codexAuthDir: "/tmp/c", agyDir: "/tmp/a" });
    expect(noClaude.env.CLAUDE_CODE_OAUTH_TOKEN).toBeUndefined();
    expect(noClaude.env[SANDBOX_SOUL_ENV]).toBe("READ-ONLY");

    // ALL auth absent ⇒ zero mounts, only the soul env — still no throw (the skill
    // runs and will degrade/escalate in-container, never a host crash).
    const none = cfgBackend().config({});
    expect(none.mounts.length).toBe(0);
    expect(none.env[SANDBOX_SOUL_ENV]).toBe("READ-ONLY");
  });
});

// ═══════════════════ 4b. mountCmrAuth — best-effort per leg (codex cmr R1) ═══════════════════

describe("#335 mountCmrAuth — a missing host credential degrades, never throws", () => {
  /** Expose the protected auth-mount seam, with $HOME pointed at an EMPTY dir. */
  class AuthBackend extends RealFamilyBackend {
    public auth(): CmrAuth {
      return this.mountCmrAuth();
    }
  }

  it("an empty $HOME (no codex/agy/claude creds) ⇒ all-undefined auth, no throw", () => {
    const emptyHome = mkDir("cmr-empty-home-");
    const be = new AuthBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
      home: emptyHome,
    });
    let auth: CmrAuth | undefined;
    expect(() => {
      auth = be.auth();
    }).not.toThrow();
    expect(auth).toEqual({
      codexAuthDir: undefined,
      agyDir: undefined,
      claudeToken: undefined,
    });
  });
});

// ═══════════════════ 4c. writeCmrFocusFile — exact scope + focus (codex cmr R1 F2/F3) ═══════════════════

describe("#335 writeCmrFocusFile — threads the exact diff scope + machine-resolved focus", () => {
  /** Expose the focus-file seam over a REAL temp git repo (so the exclude path resolves). */
  class FocusBackend extends RealFamilyBackend {
    public focus(ctx: { familyBase: string; llmResolvedChildren?: readonly number[] }): void {
      this.writeCmrFocusFile(ctx as never);
    }
  }

  function realRepo(): string {
    const repo = mkDir("cmr-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }

  it("pins the cut-SHA scope command + names the machine-resolved children", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.focus({ familyBase: "feat/330-pure-scheduler", llmResolvedChildren: [42, 43] });
    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    // F3: the exact scope diff is on the recorded cut SHA, NOT main...HEAD.
    expect(body).toContain("git diff abc123...feat/330-pure-scheduler");
    // F2: the machine-resolved children are named.
    expect(body).toContain("#42");
    expect(body).toContain("#43");
    // It is git-ignored (info/exclude), so the review never accidentally commits it.
    const exclude = readFileSync(join(repo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(CMR_FOCUS_FILENAME);
  });

  it("no recorded cut SHA ⇒ FAIL-CLOSED throw, never a stale-base fallback scope (codex R3)", () => {
    // The focus file pins the EXACT cut-SHA review-scope diff (prompt contract
    // integrated_cmr.md:19-24: do NOT guess main...HEAD). Emitting a
    // `main...familyBase` fallback when no cut SHA was recorded would silently
    // disable that load-bearing scope — the same fail-open the reconcile
    // `familyBaseStartHead()` predicate refuses (realFamilyBackend.ts:887-895). So
    // a missing cut SHA must THROW (the gate converts it to not-passed / escalate),
    // never write a stale-base diff command.
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    expect(() => be.focus({ familyBase: "fb" })).toThrow(/familyBaseStartHead|cut SHA/i);
    // And it did NOT write a stale-base fallback file.
    expect(() => readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8")).toThrow();
  });
});

// ═══════════════════ 4d. runCmrWorker fail-closed on a missing cut SHA (codex R3) ═══════════════════

describe("#335 runCmrWorker — fail-closed when no cut SHA was recorded", () => {
  /** Exposes runCmrWorker and traps sc.run so we can prove it is NEVER reached. */
  class GuardBackend extends RealFamilyBackend {
    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    protected override writeCmrFocusFile(): void {
      // If the guard is correct this is never reached; flag it if it is.
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when fail-closed");
    }
  }

  it("a cmr worker with NO familyBaseStartHead ⇒ escalate, never spins the container", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/familyBaseStartHead|cut SHA/i);
    }
    // The fail-closed guard returns BEFORE any container / focus-file work.
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes that fail-closed escalate to a not-passed WorkerResult", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/familyBaseStartHead|cut SHA/i);
    }
  });
});

// ═══════ 4e. runCmrWorker fail-closed on a missing Claude WORKER auth (codex R4) ═══════

describe("#335 runCmrWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The CMR worker is the container's TOP-LEVEL claude (`agent: sc.claudeCode`), so
   * the Claude OAuth token is not a mere reviewer leg — it is the worker's OWN auth.
   * A missing token means the worker cannot start and never emits a `<cmr>` verdict;
   * letting it through would crash out of `sc.run` (NOT a structured escalate),
   * bypassing verifyCmr's escalate routing. So `runCmrWorker` must escalate BEFORE
   * spinning the container when `mountCmrAuth().claudeToken` is absent.
   */
  class NoClaudeAuthBackend extends RealFamilyBackend {
    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    // The cut SHA IS recorded (we isolate the Claude-auth guard from the R3 guard).
    protected override mountCmrAuth(): CmrAuth {
      // codex/agy present, claude token ABSENT (the worker's own auth missing).
      return { codexAuthDir: "/x/codex", agyDir: "/x/agy" };
    }
    protected override writeCmrFocusFile(): void {
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when the worker has no auth");
    }
  }

  it("no Claude worker token ⇒ escalate, never spins the container", async () => {
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/claude|token|auth/i);
    }
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes the no-auth escalate to a not-passed WorkerResult", async () => {
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
  });
});

function realRepo335(): string {
  const repo = mkDir("cmr-guard-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  return repo;
}

// ═══════════════════ 5. deleted-fanout regression ═══════════════════

describe("#335 the runner-internal 3-CLI 手搓 is DELETED", () => {
  it("familyDriver no longer exports the 3-leg reviewer fan-out symbols", async () => {
    const mod = await import("../../src/familyDriver.js");
    const m = mod as Record<string, unknown>;
    expect(m.DriverFamilyBackend).toBeUndefined();
    expect(m.reviewerPrompt).toBeUndefined();
    expect(m.parseReviewerVerdict).toBeUndefined();
    expect(m.aggregateCmr).toBeUndefined();
    expect(m.reviewerLegFromOutput).toBeUndefined();
  });
});
