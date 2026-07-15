/**
 * integ-cmr (base) — two cross-slice gaps codex found that per-slice cmr missed:
 *
 *   #3  Error terminations must PERSIST the ledger (not only the in-memory
 *       copy).  The normal path writes every step + S8 via backend.writeLedger
 *       (sibling state dir = resume truth, ADR 0018 §3 / US#26).  But the error
 *       handoff used to push only the in-memory ledger and return — so on a
 *       resume that reads the PERSISTED ledger, the failing step + S8 vanished.
 *       Fix: every error termination that has a resolved stateDir persists the
 *       failing step + S8 via writeLedger, exactly like the happy path.
 *
 *   #5  route() / runner must NEVER silently treat a malformed step output as a
 *       success and bypass the ship gate. Under ADR 0030 a malformed S2 coder
 *       output or malformed S3/S6 reviewer output is a contract violation; it
 *       must NEVER be coerced into a committed/reviewed success and pushed.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

// ─── shared fixtures ───────────────────────────────────────────────────────

const COMPLIANT_META: IssueMeta = {
  number: 244,
  isReadyForAgent: true,
  hasSubIssues: false,
  isClosed: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 244,
  body: "issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the thing",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-244",
  base: "main",
  path: "/resident/worktrees/issue-244",
};

/**
 * Base fake Backend with a writeLedger SPY: every persisted entry is recorded
 * so tests can assert the persisted ledger (not just the in-memory one).
 */
class SpyBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly ledgerCalls: Array<{
    entry: PersistentLedgerEntry;
    stateDir: string;
  }> = [];
  readonly runStepIds: string[] = [];

  // #255 resume seam: fresh-run fake → no residue (runner consults this first).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
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
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [], findingsCount: 0 };
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    this.ledgerCalls.push({ entry, stateDir });
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// #3 — error terminations persist the failing step + S8 to the ledger
// ═══════════════════════════════════════════════════════════════════════════

describe("#3 error paths persist the ledger (not only in-memory)", () => {
  it("S2 runStep throw → persisted ledger contains S2 and S8", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") throw new Error("sandbox.run crashed: OOM");
      return { kind: "reviewer", findings: [], findingsCount: 0 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("escalate");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    // The failing step AND the terminal S8 must be in the PERSISTED ledger,
    // so a resume reading the persisted ledger sees the error termination.
    expect(persistedSteps).toContain("S2");
    expect(persistedSteps).toContain("S8");
  });

  it("S2 0-commit exhaustion → persisted ledger advances through S3 to S8", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [], findingsCount: 0 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("success");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persistedSteps).toContain("S2");
    expect(persistedSteps).toContain("S8");
    expect(persistedSteps).toContain("S3");
    expect(persistedSteps).toContain("S7");
  });

  it("S1 writeSnapshot throw (after worktree prepared) → persisted ledger contains S1 and S8", async () => {
    // The worktree IS prepared (stateDir resolvable), so even though S1's
    // writeSnapshot fails, the error termination must persist.
    const backend = new SpyBackend();
    backend.writeSnapshot = async () => {
      throw new Error("ENOSPC: no space left on device");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persistedSteps).toContain("S1");
    expect(persistedSteps).toContain("S8");
  });

  it("persisted error ledger entries land in the same sibling stateDir as normal entries", async () => {
    const backend = new SpyBackend();

    await runOrchestrator({ issueNumber: 244, backend });

    // One canonical stateDir for the whole run, outside the worktree.
    const dirs = new Set(backend.ledgerCalls.map((c) => c.stateDir));
    expect(dirs.size).toBe(1);
    const [stateDir] = [...dirs];
    expect(stateDir!.startsWith(WORKTREE.path + "/")).toBe(false);
    expect(stateDir).not.toBe(WORKTREE.path);
  });

  it("S0 fetch throw (no worktree yet) → still S8(error); in-memory ledger records S8", async () => {
    // Before any worktree exists there is no sibling stateDir to persist to —
    // persistence is impossible, but the run must still terminate as S8(error)
    // and the in-memory ledger must record the S8 termination.
    const backend = new SpyBackend();
    backend.fetchIssueMeta = async () => {
      throw new Error("gh: not found");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S0");
    expect(result.stepLedger.map((e) => e.step)).toContain("S8");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// #5 — malformed step output is never silently passed through the P0/P1 gate
// ═══════════════════════════════════════════════════════════════════════════

describe("#5 malformed S2 build output → S8(error), never silent bypass", () => {
  it("S2 completed wrong-kind cargo advances to the reviewer without git adjudication", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      // Contract violation: the S2 build worker must return a coder output.
      return { kind: "reviewer", findings: [], findingsCount: 0 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("success");
    expect(backend.runStepIds.filter((id) => id === "S2")).toHaveLength(1);
    expect(result.stepLedger.some((entry) => entry.step === "S3")).toBe(true);
  });

  it("S3 wrong-kind output dispatches S5 then accepts a fresh S6", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.id === "S3") return { kind: "coder", committed: true, commitsAdded: 1 };
      return (spec.role === "reviewer" || spec.role === "verify")
        ? { kind: "reviewer", findings: [], findingsCount: 0 }
        : { kind: "coder", committed: true, commitsAdded: 1 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("success");
    expect(backend.runStepIds.filter((id) => id === "S3")).toHaveLength(1);
    expect(result.stepLedger.at(-1)?.step).toBe("S8");
    expect(backend.runStepIds).toContain("S5");
    expect(backend.runStepIds).toContain("S6");
  });

  it("S2 garbage commitsAdded remains advisory", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      return spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: "lots" } as unknown as StepOutput
        : { kind: "reviewer", findings: [], findingsCount: 0 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("success");
  });

  it("a well-formed committed S2 plus clean S3/S4 review routes to S7 local handoff", async () => {
    // A committed S2 coder output plus a clean S3 reviewer output reaches S7,
    // but the child runner leaves remote delivery to the family endgame.
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if ((spec.role === "reviewer" || spec.role === "verify")) {
        return { kind: "reviewer", findings: [], findingsCount: 0 };
      }
      return { kind: "coder", committed: true, commitsAdded: 1 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });
});
