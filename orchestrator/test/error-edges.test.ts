/**
 * Error-edge tests for #252: 0-commit and backend-throw both converge to
 * S8(status=error) with an error package. S8 tri-state (success/escalate/error)
 * fully enumerated.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixture helpers ────────────────────────────────────────────────

/** A compliant IssueMeta that passes S0 gate. */
const COMPLIANT_META: IssueMeta = {
  number: 252,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 252,
  body: "issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the thing",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-252",
  base: "main",
  path: "/resident/worktrees/issue-252",
};

/** Base Backend that satisfies all methods with happy defaults (override per test). */
class BaseBackend implements Backend {
  async fetchIssueMeta(_n: number): Promise<IssueMeta> {
    return COMPLIANT_META;
  }
  async fetchIssueSnapshot(_n: number): Promise<IssueSnapshot> {
    return SNAPSHOT;
  }
  async prepareWorktree(_n: number, _b: string): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(_w: WorktreeHandle, _s: IssueSnapshot): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }
  async push(_w: WorktreeHandle): Promise<void> {}
}

// ─── 0-commit (S2 coder_implement returns committed:false) ─────────────────

describe("error edge: S2 coder 0-commit → S8(error)", () => {
  it("does NOT proceed to reviewer (S3 never called) when coder committed:false", async () => {
    const runStepIds: string[] = [];
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    // S3 must never be reached — coder produced nothing so we stop immediately.
    expect(runStepIds).not.toContain("S3");
    expect(runStepIds).toContain("S2");
  });

  it("converges to S8 handoff(status=error) with an error package identifying S2", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    // Error package must identify the failing step.
    expect(result.errorPackage).toBeDefined();
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(typeof result.errorPackage?.reason).toBe("string");
    expect(result.errorPackage?.reason.length).toBeGreaterThan(0);
  });

  it("records S8 in the ledger on 0-commit error path", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    const steps = result.stepLedger.map((e) => e.step);
    expect(steps).toContain("S8");
    // Must include S2 entry.
    expect(steps).toContain("S2");
    // Must NOT include S3 (reviewer skipped).
    expect(steps).not.toContain("S3");
  });
});

// ─── push failure (S7 push throws) ─────────────────────────────────────────

describe("error edge: S7 push failure → S8(error)", () => {
  it("routes to S8(status=error) when push throws", async () => {
    const backend = new BaseBackend();
    backend.push = async () => {
      throw new Error("remote rejected: non-fast-forward");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
  });

  it("error package includes failedStep=S7 and the original error reason", async () => {
    const backend = new BaseBackend();
    backend.push = async () => {
      throw new Error("push failed: authentication required");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.errorPackage).toBeDefined();
    expect(result.errorPackage?.failedStep).toBe("S7");
    expect(result.errorPackage?.reason).toContain("push failed");
  });

  it("error package includes the branch HEAD so the dev can diagnose without re-running", async () => {
    const backend = new BaseBackend();
    backend.push = async () => {
      throw new Error("remote rejected");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    // branchHead must be set to the resident branch name so the dev knows
    // where the commits landed even though push failed.
    expect(result.errorPackage?.branchHead).toBe(WORKTREE.branch);
  });

  it("records S8 in the ledger on push-failure path", async () => {
    const backend = new BaseBackend();
    backend.push = async () => {
      throw new Error("push failed");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    const steps = result.stepLedger.map((e) => e.step);
    expect(steps).toContain("S7");
    expect(steps).toContain("S8");
  });
});

// ─── backend throws mid-pipeline (sandbox.run / gh / git) ──────────────────

describe("error edge: any backend call throws → S8(error), not silently swallowed", () => {
  it("sandbox.run (S2 runStep) throws → S8(status=error)", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        throw new Error("sandbox.run crashed: OOM");
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(result.errorPackage?.reason).toContain("sandbox.run crashed");
  });

  it("fetchIssueSnapshot (S1) throws → S8(status=error)", async () => {
    const backend = new BaseBackend();
    backend.fetchIssueSnapshot = async () => {
      throw new Error("gh: rate limit exceeded");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S1");
    expect(result.errorPackage?.reason).toContain("gh: rate limit exceeded");
  });

  it("prepareWorktree (S1) throws → S8(status=error)", async () => {
    const backend = new BaseBackend();
    backend.prepareWorktree = async () => {
      throw new Error("git worktree add failed: already exists");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S1");
  });

  it("fetchIssueMeta (S0) throws → S8(status=error)", async () => {
    const backend = new BaseBackend();
    backend.fetchIssueMeta = async () => {
      throw new Error("gh: not found");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.errorPackage?.reason).toContain("gh: not found");
  });
});

// ─── S8 tri-state: success / escalate / error all reachable ────────────────

describe("S8 tri-state: success / escalate / error are all distinct and caller-distinguishable", () => {
  it("happy path still yields S8(status=success) — regression check", async () => {
    const backend = new BaseBackend();
    const result = await runOrchestrator({ issueNumber: 252, backend });
    expect(result.status).toBe("success");
    expect(result.errorPackage).toBeUndefined();
  });

  it("0-commit yields S8(status=error) — distinct from success", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };
    const result = await runOrchestrator({ issueNumber: 252, backend });
    expect(result.status).toBe("error");
    expect(result.status).not.toBe("success");
    expect(result.status).not.toBe("escalate");
  });

  it("escalate signal yields S8(status=escalate) — distinct from error", async () => {
    // escalate is triggered by a coder/reviewer step that carries `escalate` in
    // its output. The route() escalate edge is owned by #251 but the type seam
    // is already wired; this test exercises it through the runner to prove the
    // three statuses are caller-distinguishable.
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          escalate: { reason: "stuck on design", diagnosis: "needs human input" },
        };
      }
      return { kind: "reviewer", findings: [] };
    };
    const result = await runOrchestrator({ issueNumber: 252, backend });
    expect(result.status).toBe("escalate");
    expect(result.status).not.toBe("error");
    expect(result.status).not.toBe("success");
  });

  it("success has branch set; error has errorPackage set; escalate has neither branch nor errorPackage", async () => {
    // success
    const successBackend = new BaseBackend();
    const successResult = await runOrchestrator({
      issueNumber: 252,
      backend: successBackend,
    });
    expect(successResult.branch).toBe(WORKTREE.branch);
    expect(successResult.errorPackage).toBeUndefined();

    // error (0-commit)
    const errorBackend = new BaseBackend();
    errorBackend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };
    const errorResult = await runOrchestrator({
      issueNumber: 252,
      backend: errorBackend,
    });
    expect(errorResult.branch).toBeUndefined();
    expect(errorResult.errorPackage).toBeDefined();

    // escalate
    const escalateBackend = new BaseBackend();
    escalateBackend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          escalate: { reason: "stuck", diagnosis: "needs human" },
        };
      }
      return { kind: "reviewer", findings: [] };
    };
    const escalateResult = await runOrchestrator({
      issueNumber: 252,
      backend: escalateBackend,
    });
    expect(escalateResult.status).toBe("escalate");
    expect(escalateResult.branch).toBeUndefined();
    expect(escalateResult.errorPackage).toBeUndefined();
  });
});
