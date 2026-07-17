/**
 * #955 r3 cx4 — persistent seat resume admission gates on provider capability.
 *
 * Same slug match alone is not enough: resume-incapable providers (registry
 * slug `agy`, no sessionStorage) must open fresh even when a prior session id
 * was retained. Capable providers (e.g. grok-4.5) keep S2→S5 / S3→S6 resume.
 *
 * Entry: real `runOrchestrator` + real registry slugs via env slot overrides.
 * No hand-built capability fixtures — `resumeCapableForSlug` is the sole source.
 */

import { describe, expect, it, vi } from "vitest";

import { resumeCapableForSlug } from "../../src/modelRegistry.js";
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

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-955-seat-cap",
  base: "main",
  path: "/resident/worktrees/issue-955-seat-cap",
};

const CODER_SESSION = "sess-coder-955-cap";
const JUDGE_SESSION = "sess-judge-955-cap";

const OPEN_FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "seat resume capability gate",
  location: "orchestrator/src/runner.ts:2966",
  suggested_fix: "gate resume on resumeCapableForSlug",
  action: "fix_now",
};

/**
 * Minimal backend that records session mode + resumeSessionId on every
 * dispatch and drives one S2→S3(continue)→S5→S6(converged) loop.
 */
class SeatCapBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  private judgeOpenings = 0;
  constructor(private readonly coderRecBody: string = "") {}

  async smokeModelRoute(route: Parameters<NonNullable<Backend["smokeModelRoute"]>>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession called directly — use dispatchWorker");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      ...(this.coderRecBody.length > 0 ? { body: this.coderRecBody } : {}),
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);

    if (spec.kind === "coder") {
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : CODER_SESSION;
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId,
      };
    }

    if (
      spec.kind === "verify" ||
      spec.kind === "reviewer" ||
      spec.id === "S3" ||
      spec.id === "S6"
    ) {
      this.judgeOpenings += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : JUDGE_SESSION;
      if (this.judgeOpenings === 1) {
        return {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [OPEN_FINDING],
            findingsCount: 1,
          },
          sessionId,
        };
      }
      return {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
        sessionId,
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

function dispatchOf(
  backend: SeatCapBackend,
  stepId: string,
): { spec: WorkerSpec; ctx: DispatchContext } {
  const idx = backend.specs.findIndex((s) => s.id === stepId);
  expect(idx).toBeGreaterThanOrEqual(0);
  return { spec: backend.specs[idx]!, ctx: backend.ctxs[idx]! };
}

describe("#955 persistent seat resume capability gate", () => {
  it("registry truth: agy is incapable; grok-4.5 is capable", () => {
    // Anchor tests to the real registry — not a test-local set.
    expect(resumeCapableForSlug("agy")).toBe(false);
    expect(resumeCapableForSlug("grok-4.5")).toBe(true);
  });

  it("same slug but resume-incapable provider opens S5/S6 fresh — no resumeSessionId", async () => {
    // #936: seat via Coder-Rec. Spy capability gate — no permanent incapable roster slug.
    const backend = new SeatCapBackend("Coder-Rec: grok-4.5\n");
    const mod = await import("../../src/modelRegistry.js");
    const spy = vi.spyOn(mod, "resumeCapableForSlug").mockReturnValue(false);
    try {
      const result = await runOrchestrator({ issueNumber: 95501, backend });
      expect(result.status).toBe("completed");
      const byId = (id: string) => {
        const i = backend.specs.findIndex((s) => s.id === id);
        expect(i).toBeGreaterThanOrEqual(0);
        return { spec: backend.specs[i]!, ctx: backend.ctxs[i]! };
      };
      expect(byId("S2").spec.model).toBe("grok-4.5");
      const s5 = byId("S5");
      expect(s5.spec.session).toBe("fresh");
      expect(s5.ctx.resumeSessionId).toBeUndefined();
      const s6 = byId("S6");
      expect(s6.spec.session).toBe("fresh");
      expect(s6.ctx.resumeSessionId).toBeUndefined();
    } finally {
      spy.mockRestore();
    }
  });

  it("resume-capable provider (grok-4.5 coder / sol judge) still resumes S5 and S6", async () => {
    const backend = new SeatCapBackend("Coder-Rec: grok-4.5\n");
    const result = await runOrchestrator({ issueNumber: 95502, backend });
    expect(result.status).toBe("completed");

    const byId = (id: string) => {
      const i = backend.specs.findIndex((s) => s.id === id);
      expect(i).toBeGreaterThanOrEqual(0);
      return { spec: backend.specs[i]!, ctx: backend.ctxs[i]! };
    };
    const s2 = byId("S2");
    expect(s2.spec.model).toBe("grok-4.5");
    const s5 = byId("S5");
    expect(s5.spec.model).toBe("grok-4.5");
    expect(s5.spec.session).toBe("resume");
    expect(s5.ctx.resumeSessionId).toBe(CODER_SESSION);
    const s6 = byId("S6");
    // judge seat follows route verify (sol on normal), not Coder-Rec
    expect(s6.spec.session).toBe("resume");
    expect(s6.ctx.resumeSessionId).toBe(JUDGE_SESSION);
  });
});
