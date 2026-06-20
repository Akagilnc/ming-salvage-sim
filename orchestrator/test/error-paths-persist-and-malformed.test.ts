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
 *       success and bypass the P0/P1 fix gate.  A coder step that returns a
 *       reviewer/undefined/garbage output, or a reviewer step that returns a
 *       coder/undefined/garbage output, is a contract violation → S8(error).
 *       In particular S4 must NOT coerce a non-reviewer output into empty
 *       findings and push (that would ship unreviewed code).
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

// ─── shared fixtures ───────────────────────────────────────────────────────

const COMPLIANT_META: IssueMeta = {
  number: 244,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
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
  readonly ledgerCalls: Array<{
    entry: PersistentLedgerEntry;
    stateDir: string;
  }> = [];
  readonly runStepIds: string[] = [];

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
    return { kind: "reviewer", findings: [] };
  }
  async push(_w: WorktreeHandle): Promise<void> {}
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
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    // The failing step AND the terminal S8 must be in the PERSISTED ledger,
    // so a resume reading the persisted ledger sees the error termination.
    expect(persistedSteps).toContain("S2");
    expect(persistedSteps).toContain("S8");
  });

  it("S2 0-commit error → persisted ledger contains S2 and S8", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persistedSteps).toContain("S2");
    expect(persistedSteps).toContain("S8");
    // S3 was never reached → must not be in the persisted ledger.
    expect(persistedSteps).not.toContain("S3");
  });

  it("S7 push throw → persisted ledger contains S7 and S8", async () => {
    const backend = new SpyBackend();
    backend.push = async () => {
      throw new Error("remote rejected: non-fast-forward");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const persistedSteps = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persistedSteps).toContain("S7");
    expect(persistedSteps).toContain("S8");
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
    backend.push = async () => {
      throw new Error("push failed");
    };

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

describe("#5 malformed step output → S8(error), never silent bypass", () => {
  it("S2 returns a reviewer output (wrong kind) → S8(error), S3 NOT reached", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        // Contract violation: coder step must return a coder output.
        return { kind: "reviewer", findings: [] };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    // Must not have advanced to the reviewer on a malformed coder output.
    expect(backend.runStepIds).not.toContain("S3");
  });

  it("S2 returns undefined → S8(error), not treated as committed", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return undefined as unknown as StepOutput;
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(backend.runStepIds).not.toContain("S3");
  });

  it("S2 returns garbage object (no kind) → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { foo: "bar" } as unknown as StepOutput;
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(backend.runStepIds).not.toContain("S3");
  });

  it("S3 returns a coder output (wrong kind) → S8(error), NEVER coerced to empty findings + push", async () => {
    // This is the dangerous one: if S4 coerced a non-reviewer output into [],
    // it would route to push and SHIP UNREVIEWED CODE.  Must be S8(error).
    const backend = new SpyBackend();
    let pushed = false;
    backend.push = async () => {
      pushed = true;
    };
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      // Contract violation: reviewer step returns a coder output.
      return { kind: "coder", committed: true, commitsAdded: 1 };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The failing step is the reviewer step (S3), not push.
    expect(result.errorPackage?.failedStep).toBe("S3");
    // CRUCIAL: push must NEVER happen on a malformed reviewer output.
    expect(pushed).toBe(false);
  });

  it("S3 returns undefined → S8(error), push NOT reached", async () => {
    const backend = new SpyBackend();
    let pushed = false;
    backend.push = async () => {
      pushed = true;
    };
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return undefined as unknown as StepOutput;
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S3");
    expect(pushed).toBe(false);
  });

  it("S3 returns garbage object (no kind) → S8(error), push NOT reached", async () => {
    const backend = new SpyBackend();
    let pushed = false;
    backend.push = async () => {
      pushed = true;
    };
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return { findings: "not an array" } as unknown as StepOutput;
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S3");
    expect(pushed).toBe(false);
  });

  it("well-formed reviewer with a P0 still routes to fix (gate not bypassed) — regression", async () => {
    // Sanity: the malformed-output guard must not break the real P0 gate.
    const backend = new SpyBackend();
    let pushed = false;
    backend.push = async () => {
      pushed = true;
    };
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      return {
        kind: "reviewer",
        findings: [
          {
            severity: "critical",
            category: "correctness",
            claim_quote: "null deref",
            location: "src/foo.ts:1",
            suggested_fix: "guard",
            action: "fix_now",
          },
        ],
      };
    };

    // A P0 routes to S5 (fix). Post-#254 the fix loop is wired (S5→S6→S4), so
    // S5 no longer throws — instead this backend re-raises the SAME P0 every
    // re-review while the coder commits, so the loop never converges and the
    // no-progress guard bails cleanly to S8(error) after K rounds. The point of
    // this regression remains: the P0 gate sent us to S5 (fix), NOT to push.
    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason.toLowerCase()).toContain("stuck");
    // The P0 gate sent us to S5 (fix), NOT to push.
    expect(backend.runStepIds).toContain("S5");
    expect(pushed).toBe(false);
  });
});
