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
  IssueSnapshot,
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
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
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

  it("same slug but resume-incapable provider (agy) opens S5/S6 fresh — no resumeSessionId", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "agy");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "agy");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "agy");

    const backend = new SeatCapBackend();
    const result = await runOrchestrator({ issueNumber: 95501, backend });
    expect(result.status).toBe("success");

    const s2 = dispatchOf(backend, "S2");
    const s5 = dispatchOf(backend, "S5");
    const s3 = dispatchOf(backend, "S3");
    const s6 = dispatchOf(backend, "S6");

    // Seats actually ran on the registry-incapable slug.
    expect(s2.spec.model).toBe("agy");
    expect(s5.spec.model).toBe("agy");
    expect(s3.spec.model).toBe("agy");
    expect(s6.spec.model).toBe("agy");

    // S2/S3 establish sessions; S5/S6 must NOT thread them.
    expect(s2.spec.session).toBe("fresh");
    expect(s2.ctx.resumeSessionId).toBeUndefined();
    expect(s5.spec.session).toBe("fresh");
    expect(s5.ctx.resumeSessionId).toBeUndefined();

    expect(s3.spec.session).toBe("fresh");
    expect(s3.ctx.resumeSessionId).toBeUndefined();
    expect(s6.spec.session).toBe("fresh");
    expect(s6.ctx.resumeSessionId).toBeUndefined();
  });

  it("resume-capable provider (grok-4.5 coder / sol judge) still resumes S5 and S6", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "gpt-5.6-sol");

    const backend = new SeatCapBackend();
    const result = await runOrchestrator({ issueNumber: 95502, backend });
    expect(result.status).toBe("success");

    const s2 = dispatchOf(backend, "S2");
    const s5 = dispatchOf(backend, "S5");
    const s3 = dispatchOf(backend, "S3");
    const s6 = dispatchOf(backend, "S6");

    expect(s2.spec.model).toBe("grok-4.5");
    expect(s5.spec.model).toBe("grok-4.5");
    expect(s3.spec.model).toBe("gpt-5.6-sol");
    expect(s6.spec.model).toBe("gpt-5.6-sol");

    expect(s2.spec.session).toBe("fresh");
    expect(s2.ctx.resumeSessionId).toBeUndefined();
    expect(s5.spec.session).toBe("resume");
    expect(s5.ctx.resumeSessionId).toBe(CODER_SESSION);

    expect(s3.spec.session).toBe("fresh");
    expect(s3.ctx.resumeSessionId).toBeUndefined();
    expect(s6.spec.session).toBe("resume");
    expect(s6.ctx.resumeSessionId).toBe(JUDGE_SESSION);
  });
});
