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

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { RealBackend, SANDBOX_CODEX_DIR, SANDBOX_SOUL_ENV } from "../src/realBackend.js";
import type { ShipAuth } from "../src/realBackend.js";
import { shipWorkerSpec } from "../src/dispatchWorker.js";
import type { ShipWorkerOutcome } from "../src/shipOutcome.js";
import type { DispatchContext, WorkerSpec, WorktreeHandle } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

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
    base: "main",
    promptsDir: realPromptsDir,
    imageName: "ming-orchestrator-coder:latest",
    runKey: "k336",
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
    be.outcome = { kind: "escalate", reason: "merge conflict", diagnosis: "human must resolve" };
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

  // ── cmr S336 r3 F1 (branch-identity check): the worker self-reports `branch`, and
  // the consumer trusted it. A worker that ships `main` (or any branch ≠ the resident
  // slice worktree branch it was asked to deliver) but reports it as a success was
  // read as a completed delivery. ship.md asks the worker to report THE shipped branch
  // (the slice branch already checked out, branchStrategy:{type:"head"}) — there is no
  // legitimate rename path, so an outcome.branch ≠ ctx.worktree.branch is off-contract.
  it("a shipped outcome whose branch ≠ the worktree branch ⇒ malformed (branch identity)", async () => {
    const be = fixtured();
    be.outcome = { kind: "shipped", branch: "main", status: "pr_opened", pr: "u" };
    const res = await be.dispatchWorker!(shipWorkerSpec(), { worktree });
    expect(res.kind).toBe("malformed");
    if (res.kind === "malformed") expect(res.reason).toMatch(/branch/);
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
    public config(auth: ShipAuth): {
      imageName: string;
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
    } {
      return this.shipSandboxConfig(auth);
    }
  }
  function cfg(): ConfigBackend {
    return new ConfigBackend({
      sourceRepo: mkDir("ship-src-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: "k336cfg",
    });
  }

  it("mounts codex auth + the claude token under the WRITE (coder) soul", () => {
    const c = cfg().config({ codexAuthDir: "/tmp/codex", claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("coder");
  });

  it("a missing codex auth degrades the mount but still ships under the coder soul", () => {
    const c = cfg().config({ claudeToken: "tok" });
    expect(c.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(false);
    expect(c.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("tok");
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("coder");
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
    expect(c.env[SANDBOX_SOUL_ENV]).toBe("coder");
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
      base: "main",
      promptsDir: realPromptsDir,
      imageName: "ming-orchestrator-coder:latest",
      runKey: "k336noauth",
    });
  }

  it("no Claude worker token ⇒ escalate, never builds the sandbox / starts the container", async () => {
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
});
