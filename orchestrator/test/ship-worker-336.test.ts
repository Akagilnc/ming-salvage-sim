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

import { RealBackend } from "../src/realBackend.js";
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
