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
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixture helpers ────────────────────────────────────────────────

/** A compliant IssueMeta that passes S0 gate. */
const COMPLIANT_META: IssueMeta = {
  number: 252,
  isReadyForAgent: true,
  hasSubIssues: false,
  isClosed: false,
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
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  // #255: fresh-run defaults (this suite tests error edges, not resume).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
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
  // #249 integration: writeLedger is part of the Backend seam; this suite
  // asserts error edges, not ledger persistence, so it is a no-op.
  async writeLedger(
    _e: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {}
}

// ─── 0-commit (S2 coder_implement returns committed:false) ─────────────────

describe("S2 coder completed 0-commit report", () => {
  it("advances once to S3 without entering process retry", async () => {
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

    expect(result.status).toBe("success");
    expect(runStepIds).toContain("S3");
    expect(runStepIds.filter((id) => id === "S2")).toHaveLength(1);
    expect(JSON.stringify(result.stepLedger)).not.toContain("synthesizedFailure");
  });

  it("leaves the empty-diff judgment to the reviewer", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("success");
    expect(result.stepLedger.some((entry) => entry.step === "S3")).toBe(true);
  });

  it("records S2 and S3 before the ordinary success handoff", async () => {
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
    expect(steps).toContain("S3");
    expect(result.stepLedger.find((entry) => entry.step === "S8")?.stopSummary?.reason).toBe("success");
  });
});

// ─── push failure (S7 push throws) ─────────────────────────────────────────

describe("infra edge: persistent S7 process failure → S8 infra park", () => {
  it("parks after the bounded process retry when push throws", async () => {
    const backend = new BaseBackend();
    backend.push = async () => {
      throw new Error("remote rejected: non-fast-forward");
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("escalate");
    expect(result.stopSummary.reason).toBe("infra_failure");
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
  it("sandbox.run (S2 runStep) permanently throws → bounded failure escalation", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        throw new Error("sandbox.run crashed: OOM");
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 252, backend });

    expect(result.status).toBe("escalate");
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

  it("0-commit exhaustion proceeds to reviewer judgment", async () => {
    const backend = new BaseBackend();
    backend.runStep = async (spec) => {
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };
    const result = await runOrchestrator({ issueNumber: 252, backend });
    expect(result.status).toBe("success");
    expect(result.stepLedger.some((entry) => entry.step === "S3")).toBe(true);
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
          escalate: {
            reason: "stuck on design",
            diagnosis: "needs human input",
            escalationKind: "decision",
          },
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

    // error (process crash)
    const errorBackend = new BaseBackend();
    errorBackend.runStep = async (spec) => {
      if (spec.role === "coder") {
        throw new Error("coder process crashed");
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
          escalate: {
            reason: "stuck",
            diagnosis: "needs human",
            escalationKind: "decision",
          },
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
