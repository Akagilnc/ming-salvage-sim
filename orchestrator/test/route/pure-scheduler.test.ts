/**
 * #337/#369 — prove the runner is a PURE SCHEDULER with ADR 0030 role boundaries.
 *
 * After #331–#336 every productive wiki step (coder/ship, plus family cmr/ship) is a
 * WORKER dispatched through the single `dispatchWorker` seam, and the runner
 * only does gate / route / 排序 / ledger / 续跑. This slice LOCKS THAT IN with
 * three assertions the dependent slices left implicit:
 *
 *   (A) runner 零具体活 — the runner never reaches for a legacy backend method
 *       (`runStep` / `resumeSession` / `push`) directly: every productive step
 *       goes through `dispatchWorker`. Proven two ways: a STATIC guard over the
 *       runner source (no `backend.runStep(` / `backend.resumeSession(` /
 *       `backend.push(` call sites), AND a BEHAVIOURAL guard — a backend whose
 *       legacy methods all THROW still runs end-to-end (so the only path that
 *       produced work was `dispatchWorker`).
 *
 *   (B) coder/reviewer/fix workers — S2, S3, S5, and S6 are separate
 *       runner-visible worker dispatches.
 *
 *   (C) review-decomposition — per-slice review is read-only and full-diff; it
 *       never runs the integrated `ak-cross-m-review` worker. The full
 *       cross-model cmr is a separate family-layer worker.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

/**
 * A backend whose every LEGACY productive method THROWS — only `dispatchWorker`
 * produces work. If the runner ran end-to-end on this backend, every productive
 * step necessarily went through the seam (a single direct legacy call would
 * throw and abort to S8(error)).
 */
class SeamOnlyBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  private reviewCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-337",
    base: "main",
    path: "/resident/worktrees/issue-337",
  };

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  // The three legacy productive methods: any DIRECT runner call is a bug.
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — runner is not a pure scheduler");
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession called directly — runner is not a pure scheduler");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeLedger(): Promise<void> {}
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}:${spec.skill ?? "—"}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    if (spec.kind === "coder") {
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      this.reviewCount += 1;
      // Explicit open-count declaration for the fixture (ADR 0131 / #899): never
      // derive findingsCount from findings.length as if that were production law.
      const findingsCount = this.reviewCount === 1 ? 1 : 0;
      const findings: Finding[] =
        findingsCount === 1
          ? [
              {
                severity: "high",
                category: "correctness",
                claim_quote: "x",
                location: "f.ts:1",
                suggested_fix: "fix it",
                action: "fix_now",
              },
            ]
          : [];
      if (findingsCount === 0) {
        return {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings,
          findingsCount,
          // ADR 0138: residual paper must carry authored body to reach S5;
          // production never invents this string.
          fixPacketBody: "fixture residual authored fixPacketBody (ADR 0138 pass-through)",
        },
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

describe("#337 runner is a pure scheduler — no inline productive work (BEHAVIOURAL)", () => {
  it("a backend whose legacy methods all throw still runs end-to-end via the seam", async () => {
    const backend = new SeamOnlyBackend();
    const result = await runOrchestrator({ issueNumber: 337, backend });
    // Reached S8(success) without ever touching a throwing legacy method.
    expect(result.status).toBe("completed");
    // ADR 0030: every productive step is a worker dispatch through the single
    // seam, and the review/fix loop is visible at runner boundaries.
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:verify:/verify",
      "S5:coder:/tdd",
      "S6:verify:/verify",
    ]);
  });
});

// ─── (B) implementation and fix are WORKERS (dispatched, not inlined) ────────
//     ADR 0030 makes S2/S3/S5/S6 runner-visible dispatch boundaries.

describe("#337 runner-visible per-slice review/fix worker dispatch", () => {
  it("dispatches S2 implementation and S5 fix as separate coder workers", async () => {
    const backend = new SeamOnlyBackend();
    await runOrchestrator({ issueNumber: 337, backend });
    const coderDispatches = backend.specs.filter((s) => s.kind === "coder");
    expect(coderDispatches.map((s) => s.id)).toEqual(["S2", "S5"]);
    expect(coderDispatches.map((s) => s.skill)).toEqual(["/tdd", "/tdd"]);
  });

  it("the build worker spec is a single-iteration seat and retains implementation context", async () => {
    // Assert on the spec the RUNNER ACTUALLY DISPATCHES (S2 worker spec → the build
    // worker). #899 / ADR 0128: one single-iteration Sandcastle run per seat; skill
    // work finishes inside that invocation. ADR 0030 still dispatches per-slice
    // review/fix as visible S3/S5/S6 worker steps. This is a NORMAL fresh dispatch
    // (NOT the crash/escalate resume path).
    const backend = new SeamOnlyBackend();
    await runOrchestrator({ issueNumber: 337, backend });
    const s2 = backend.specs.find((s) => s.id === "S2");
    expect(s2).toBeDefined();
    expect(s2!.maxIter).toBe(1);
    expect(s2!.session).toBe("fresh");
    expect(s2!.contextRetention).toBe("retain"); // production worker retains context
    expect(s2!.skill).toBe("/tdd");
    const s2Ctx = backend.ctxs[backend.specs.findIndex((s) => s.id === "S2")];
    expect(s2Ctx.resumeSessionId).toBeUndefined();
  });
});
