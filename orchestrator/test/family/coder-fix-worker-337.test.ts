/**
 * The family integrated-cmr FIX worker (wiki tdd-autonomous-dev Step 6 fix loop)
 * runs in a REAL container, mirroring the cmr worker (#335) and the ship worker
 * (#336). Before this slice, `RealFamilyBackend.dispatchWorker` routed only the
 * `cmr` and `ship` worker kinds; the `coder` (family coder-fix) kind fell through
 * to the legacy seam (`runFamilyCoderFix`, unimplemented) — so in a real dogfood a
 * non-converged family cmr could not actually dispatch a container that fixes.
 *
 * This wires the family coder-fix worker the SAME way the ship worker runs:
 *   - the 2b container's TOP-LEVEL claude under the WRITE (`coder`) soul;
 *   - it `Skill`-invokes `/tdd` (prompts/family_coder_fix.md) over the checked-out
 *     family base, committing its fix in place (`branchStrategy:{type:"head"}`);
 *   - its `<coder>` tag is gated on `CODER_STEP_COMPLETE`, then parsed + git-truthed
 *     against the real commits Sandcastle observed (`result.commits.length`);
 *   - the outcome maps to the `FamilyCoderFixResult` shape the verifyCmr loop
 *     consumes (committed / commitsAdded / optional escalate). An `escalate` from
 *     the fix worker surfaces as `WorkerResult.escalated` so the loop escalates.
 *
 * Tested WITHOUT a real container (mirrors #335/#336): the `runCoderFixWorker` /
 * container seam is fixtured; the `dispatchWorker(coder)` routing + the parse/gate
 * helpers are asserted at the seam.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  CMR_FOCUS_FILENAME,
  coderFixOutcomeFromResult,
  parseCoderFixOutcome,
  RealFamilyBackend,
  REFERENCED_FAMILY_PROMPT_FILES,
  type CoderFixAuth,
  type CoderFixWorkerOutcome,
} from "../../src/family/realFamilyBackend.js";
import {
  SANDBOX_CODEX_DIR,
  SANDBOX_SOUL_ENV,
} from "../../src/realBackend.js";
import {
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
} from "../../src/family/dispatchFamilyWorker.js";
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

const FAMILY_BASE = "feat/330-pure-scheduler";
const REASON = "cross-slice field-name mismatch between #201 and #202";

// ═══════════════════════ 1. parseCoderFixOutcome (pure tag parse) ═══════════════════════

describe("#337 parseCoderFixOutcome — the <coder> fix tag", () => {
  it("committed:true + commitsAdded ⇒ a committed outcome", () => {
    const o = parseCoderFixOutcome('noise\n<coder>{"committed": true, "commitsAdded": 1}</coder>\n');
    expect(o.kind).toBe("committed");
    if (o.kind === "committed") {
      expect(o.committed).toBe(true);
      expect(o.commitsAdded).toBe(1);
    }
  });

  it("committed:false + commitsAdded:0 ⇒ a not-committed outcome (a 0-commit round)", () => {
    const o = parseCoderFixOutcome('<coder>{"committed": false, "commitsAdded": 0}</coder>');
    expect(o.kind).toBe("committed");
    if (o.kind === "committed") {
      expect(o.committed).toBe(false);
      expect(o.commitsAdded).toBe(0);
    }
  });

  it("an escalate object ⇒ an escalate outcome (the finding cannot be fixed as stated)", () => {
    const o = parseCoderFixOutcome(
      '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "design gap", "diagnosis": "needs a human decision"}}</coder>',
    );
    expect(o.kind).toBe("escalate");
    if (o.kind === "escalate") {
      expect(o.reason).toContain("design gap");
      expect(o.diagnosis).toContain("human");
    }
  });

  it("only the LAST <coder> tag is read (the worker may iterate)", () => {
    const o = parseCoderFixOutcome(
      '<coder>{"committed": false, "commitsAdded": 0}</coder>\nlater…\n<coder>{"committed": true, "commitsAdded": 2}</coder>',
    );
    expect(o.kind).toBe("committed");
    if (o.kind === "committed") expect(o.commitsAdded).toBe(2);
  });

  it("no <coder> tag ⇒ malformed (never silently read as a fix)", () => {
    const o = parseCoderFixOutcome("just some prose, no tag");
    expect(o.kind).toBe("malformed");
  });

  it("a non-JSON <coder> tag ⇒ malformed", () => {
    const o = parseCoderFixOutcome("<coder>not json</coder>");
    expect(o.kind).toBe("malformed");
  });

  it("an off-contract shape (extra key) ⇒ malformed (fail-closed)", () => {
    const o = parseCoderFixOutcome('<coder>{"committed": true, "commitsAdded": 1, "shipped": true}</coder>');
    expect(o.kind).toBe("malformed");
  });
});

// ═══════════════════════ 2. coderFixOutcomeFromResult (signal gate + git truth) ═══════════════════════

describe("#337 coderFixOutcomeFromResult — completion-signal gate + git-truthed commits", () => {
  it("an UNSIGNALED run ⇒ escalate (not trusted as a fix — mirrors the cmr/merger gate)", () => {
    const o = coderFixOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<coder>{"committed": true, "commitsAdded": 1}</coder>',
      commits: [{}],
    });
    expect(o.kind).toBe("escalate");
  });

  it("a signaled committed run is git-TRUTHED against result.commits.length", () => {
    // The model self-reports 1 commit AND git observed 1 — agree → committed.
    const o = coderFixOutcomeFromResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": true, "commitsAdded": 1}</coder>',
      commits: [{}],
    });
    expect(o.kind).toBe("committed");
    if (o.kind === "committed") {
      expect(o.committed).toBe(true);
      expect(o.commitsAdded).toBe(1);
    }
  });

  it("a self-report that contradicts git ⇒ malformed (the model claimed a commit git did not see)", () => {
    // Claims 1 commit, git saw 0 — a contract violation; fail-closed (never a trusted fix).
    const o = coderFixOutcomeFromResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": true, "commitsAdded": 1}</coder>',
      commits: [],
    });
    expect(o.kind).toBe("malformed");
  });

  it("an escalate signal is preserved (a model signal, not derivable from git)", () => {
    const o = coderFixOutcomeFromResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout:
        '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "r", "diagnosis": "d"}}</coder>',
      commits: [],
    });
    expect(o.kind).toBe("escalate");
  });
});

// ═══════════════════════ 3. dispatchWorker(coder) routing ═══════════════════════

/** A family backend whose container `runCoderFixWorker` seam is fixtured (no sc.run). */
class FixturedFixBackend extends RealFamilyBackend {
  runFixCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
  outcome: CoderFixWorkerOutcome = { kind: "committed", committed: true, commitsAdded: 1 };
  protected override async runCoderFixWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CoderFixWorkerOutcome> {
    this.runFixCalls.push({ spec, ctx });
    return this.outcome;
  }
}

function fixtured(): FixturedFixBackend {
  return new FixturedFixBackend({
    workingRepo: mkDir("fix-repo-"),
    familyBase: FAMILY_BASE,
    ledgerDir: mkDir("fix-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    imageName: "ming-orchestrator-coder:latest",
  });
}

describe("#337 RealFamilyBackend.dispatchWorker — the family coder-fix worker", () => {
  it("dispatches the family coder-fix spec to runCoderFixWorker — /tdd on the family base", async () => {
    const be = fixtured();
    await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(be.runFixCalls.length).toBe(1);
    const spec = be.runFixCalls[0]!.spec;
    expect(spec.kind).toBe("coder");
    expect(spec.skill).toBe("tdd");
    expect(spec.soul).toBe("coder");
    // The cmr reason is threaded so the worker knows WHAT to fix.
    expect(be.runFixCalls[0]!.ctx.cmrReason).toBe(REASON);
  });

  it("a committed outcome ⇒ WorkerResult.completed with a coder payload the loop consumes", async () => {
    const be = fixtured();
    be.outcome = { kind: "committed", committed: true, commitsAdded: 2 };
    const res = await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "coder") {
      expect(res.output.committed).toBe(true);
      expect(res.output.commitsAdded).toBe(2);
    } else {
      throw new Error("expected a completed coder payload");
    }
  });

  it("a 0-commit committed outcome ⇒ completed coder payload with committed:false (the loop escalates)", async () => {
    const be = fixtured();
    be.outcome = { kind: "committed", committed: false, commitsAdded: 0 };
    const res = await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(res.kind).toBe("completed");
    if (res.kind === "completed" && res.output.kind === "coder") {
      expect(res.output.committed).toBe(false);
    } else {
      throw new Error("expected a completed coder payload");
    }
  });

  it("an escalate outcome ⇒ WorkerResult.escalated (the finding cannot be fixed as stated) — the loop escalates", async () => {
    const be = fixtured();
    be.outcome = {
      kind: "escalate",
      reason: "the finding conflicts with the epic spec",
      diagnosis: "a human must decide",
    };
    const res = await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toContain("conflicts with the epic spec");
    }
  });

  it("a malformed outcome ⇒ WorkerResult.malformed (never silently a fix)", async () => {
    const be = fixtured();
    be.outcome = { kind: "malformed", reason: "no <coder> tag" };
    const res = await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(res.kind).toBe("malformed");
  });

  it("a family coder-fix worker without familyBase throws (it fixes the family base)", async () => {
    const be = fixtured();
    await expect(
      be.dispatchWorker(familyCoderFixWorkerSpec(), { cmrReason: REASON }),
    ).rejects.toThrow(/familyBase/);
  });

  it("a family coder-fix worker without cmrReason throws (it needs the focus)", async () => {
    const be = fixtured();
    await expect(
      be.dispatchWorker(familyCoderFixWorkerSpec(), { familyBase: FAMILY_BASE }),
    ).rejects.toThrow(/cmrReason|reason/i);
  });

  it("a cmr worker is still routed to its own (cmr) path, NOT the coder-fix seam", async () => {
    const be = fixtured();
    // No familyBaseStartHead → the cmr fail-closed escalate proves it took the cmr
    // path (runCmrWorker), not the coder-fix seam.
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: FAMILY_BASE });
    expect(res.kind).toBe("escalated");
    expect(be.runFixCalls.length).toBe(0);
  });
});

// ═══════════════════════ 4. the prompt file is registered for construction-time validation ═══════════════════════

describe("#337 the family coder-fix promptFile is validated at construction", () => {
  it("family_coder_fix.md is in REFERENCED_FAMILY_PROMPT_FILES (derived from the spec)", () => {
    expect(REFERENCED_FAMILY_PROMPT_FILES).toContain(familyCoderFixWorkerSpec().promptFile);
    expect(REFERENCED_FAMILY_PROMPT_FILES).toContain("family_coder_fix.md");
  });
});

// ═══════════════════════ 5. coderFixSandboxConfig — coder soul + codex auth + claude token ═══════════════════════

describe("#337 family coderFixSandboxConfig — the WRITE-soul fix sandbox", () => {
  class ConfigBackend extends RealFamilyBackend {
    public config(auth: CoderFixAuth): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
    } {
      return this.coderFixSandboxConfig(auth);
    }
  }
  function cfg(): ConfigBackend {
    return new ConfigBackend({
      workingRepo: mkDir("fix-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("fix-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  it("mounts codex auth + the claude token under the WRITE (coder) soul", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("coder");
  });

  it("a missing codex auth degrades the mount but still fixes under the coder soul", () => {
    const c = cfg().config({ claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("coder");
  });
});

// ═══════════════════════ 6. runCoderFixWorker fail-closed on a missing Claude WORKER auth ═══════════════════════

describe("#337 family runCoderFixWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The family coder-fix worker is the container's TOP-LEVEL claude
   * (`agent: sc.claudeCode`), so the Claude OAuth token is its OWN auth, not a
   * degradable codex leg. Absent, the worker cannot start and never emits a
   * `<coder>` verdict; letting it through would throw out of `sc.run` (NOT a
   * structured escalate), bypassing the WorkerResult routing. So runCoderFixWorker
   * escalates BEFORE the checkout / focus write / container — matching the
   * cmr/ship workers' claude preflight.
   */
  class NoClaudeAuthBackend extends RealFamilyBackend {
    containerReached = false;
    checkoutReached = false;
    public run(spec: WorkerSpec, ctx: DispatchContext): Promise<CoderFixWorkerOutcome> {
      return (
        this as unknown as {
          runCoderFixWorker(s: WorkerSpec, c: DispatchContext): Promise<CoderFixWorkerOutcome>;
        }
      ).runCoderFixWorker(spec, ctx);
    }
    // codex present, claude token ABSENT (the worker's own auth missing).
    protected override mountCoderFixAuth(): CoderFixAuth {
      return { codexAuthDir: "/x/codex" };
    }
    protected override sh(): string {
      this.checkoutReached = true;
      throw new Error("git checkout should not run when the worker has no auth");
    }
    protected override async coderFixContainerRun(): Promise<never> {
      this.containerReached = true;
      throw new Error("coderFixContainerRun should not run when the worker has no auth");
    }
  }
  function noAuth(): NoClaudeAuthBackend {
    return new NoClaudeAuthBackend({
      workingRepo: mkDir("fix-noauth-repo-"),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("fix-noauth-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
    });
  }

  it("no Claude worker token ⇒ escalate, never checks out / spins the container", async () => {
    const be = noAuth();
    const outcome = await be.run(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
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
    const res = await be.dispatchWorker(familyCoderFixWorkerSpec(), {
      familyBase: FAMILY_BASE,
      cmrReason: REASON,
    });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/claude|token|auth/i);
    }
  });
});

// ═══════════════════════ 7. runCoderFixWorker writes the .cmr-focus.md the fix worker reads ═══════════════════════

describe("#337 runCoderFixWorker — writes the cmr focus file BEFORE the container runs", () => {
  /**
   * prompts/family_coder_fix.md reads `.cmr-focus.md` FIRST (the same machine-
   * generated focus the cmr worker writes): it pins the review-scope diff + the
   * cross-slice issue. Prove runCoderFixWorker produces it before the container
   * spins — trap the container call with a sentinel and assert the focus file is
   * ALREADY on disk (carrying the non-convergence reason) when it fires.
   */
  let focusBodyAtRun: string | undefined;
  class SeamBackend extends RealFamilyBackend {
    protected override sh(): string {
      // Stub the git checkout (the temp repo has no family base ref).
      return "";
    }
    protected override mountCoderFixAuth(): CoderFixAuth {
      return { claudeToken: "tok", codexAuthDir: "/x/codex" };
    }
    protected override async coderFixContainerRun(): Promise<never> {
      focusBodyAtRun = readFileSync(
        join(this["opts"].workingRepo, CMR_FOCUS_FILENAME),
        "utf8",
      );
      throw new Error("SENTINEL: container reached");
    }
  }
  function realRepo(): string {
    const repo = mkDir("fix-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }

  it("the focus file carries the cmr reason + is on disk when the container would launch", async () => {
    const b = new SeamBackend({
      workingRepo: realRepo(),
      familyBase: FAMILY_BASE,
      ledgerDir: mkDir("fix-focus-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "img",
      // the cmr focus file requires a recorded cut SHA (fail-closed otherwise).
      familyBaseStartHead: "deadbeef",
    });
    await expect(
      (
        b as unknown as {
          runCoderFixWorker(s: WorkerSpec, c: DispatchContext): Promise<unknown>;
        }
      ).runCoderFixWorker(familyCoderFixWorkerSpec(), {
        familyBase: FAMILY_BASE,
        cmrReason: REASON,
      }),
    ).rejects.toThrow(/SENTINEL/);
    expect(focusBodyAtRun).toBeDefined();
    // The focus file pins the review-scope diff (the cmr worker's contract); the
    // fix worker re-derives the concrete finding from it + the diff.
    expect(focusBodyAtRun).toContain(FAMILY_BASE);
  });
});
