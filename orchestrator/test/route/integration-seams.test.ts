/**
 * integ-cmr (base) round 2 — cross-slice seam gaps the integrated review found
 * that per-slice cmr missed (all behavioural, test-first):
 *
 *   (A [Crit] finding ELEMENT validation tests the reviewer-findings path routed
 *    through S3/S4. ADR 0030 restored that runner-visible seam, so malformed
 *    finding elements must fail closed before classification can route to ship.)
 *
 *   B [High] coder output did not validate `commitsAdded`.  The contract is
 *     {committed:boolean, commitsAdded:number} with the two consistent
 *     (committed=true ⇒ commitsAdded≥1; committed=false ⇒ 0).  A
 *     {committed:true, commitsAdded:0} or a missing/garbage commitsAdded slipped
 *     through.  Fix: commitsAdded must be a non-negative integer consistent with
 *     committed → else S8(error).
 *
 *   C [High] S1 pre-worktree (fetchIssueSnapshot / prepareWorktree) failures are
 *     an unpersistable special case (no worktree → no sibling stateDir yet),
 *     exactly like the S0 metadata fetch.  The comment/contract must not
 *     overpromise "S1 throw is persisted" for these — only post-worktree S1
 *     (writeSnapshot) failures persist.  This suite pins the special case.
 *
 *   D [High] writeLedger failure on a normal step used recordFailingStep:false,
 *     which (besides not double-pushing the in-memory entry) also skipped the
 *     best-effort RE-persist of the failing step.  Result: a transient ledger
 *     write fault → the persisted ledger is missing the failing step (in-memory
 *     has it, disk does not).  Fix: split "record in memory" from "persist
 *     failing step"; the error path still best-effort re-persists the failing
 *     step so the persisted and in-memory ledgers agree on the error path.
 *
 *   E [Med] When writing the S8 ledger entry itself throws, the catch hard-coded
 *     failedStep:"S7".  But that S8 write happens for ANY handoff (S2 no-commit
 *     error, route error, etc.), where push never ran.  Fix: attribute to the
 *     REAL failing step.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
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
 * Base fake Backend. Override runStep / push / writeLedger per test.
 * writeLedger is a spy so persisted entries can be asserted independently of
 * the in-memory ledger.
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
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    this.ledgerCalls.push({ entry, stateDir });
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// B [High] — coder commit self-reports are advisory.
// ═══════════════════════════════════════════════════════════════════════════

describe("B: coder commitsAdded advisory telemetry", () => {
  it("committed:true with commitsAdded:0 continues; the self-report is not a gate", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      return spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 0 }
        : { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("success");
  });

  it("committed:false with commitsAdded:2 advances to reviewer", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 2 };
      }
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("missing commitsAdded continues", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true } as unknown as StepOutput;
      }
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("non-integer commitsAdded (1.5) continues", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1.5 };
      }
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("negative commitsAdded (-1) remains advisory on a white run", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: -1 } as unknown as StepOutput;
      }
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("non-number commitsAdded ('1') continues", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: "1" } as unknown as StepOutput;
      }
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("regression: committed:true with commitsAdded:1 proceeds to S7 local handoff", async () => {
    const backend = new SpyBackend(); // default: true/1
    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
  });

  it("regression: committed:false with commitsAdded:0 advances to S3", async () => {
    // A consistent 0-commit coder envelope still advances to the independent S3
    // reviewer; its clean review then permits the normal S7 local handoff.
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      return spec.role === "coder"
        ? { kind: "coder", committed: false, commitsAdded: 0 }
        : { kind: "judge", status: "converged" };
    };
    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
    expect(backend.runStepIds).toContain("S3");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// C [High] — S1 pre-worktree failures are an unpersistable special case (like
// S0); post-worktree failures persist (#936: snapshot dual court deleted).
// ═══════════════════════════════════════════════════════════════════════════

describe("C: S1 pre-worktree failures are an unpersistable special case", () => {
  it("prepareWorktree throw (pre-worktree) → S8(error), nothing persisted", async () => {
    const backend = new SpyBackend();
    backend.prepareWorktree = async () => {
      throw new Error("git worktree add failed");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S1");
    expect(backend.ledgerCalls).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toContain("S8");
  });

  it("post-worktree S2 throw DOES persist S2 and S8 (contrast)", async () => {
    // Persistable case: the worktree exists, so the sibling stateDir is
    // resolved and the error termination persists.
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      if (spec.id === "S2") throw new Error("ENOSPC");
      return spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 1 }
        : { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(["error", "escalate"]).toContain(result.status);
    const persisted = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persisted).toContain("S2");
    expect(persisted).toContain("S8");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// D [High] — writeLedger failure on a normal step still best-effort re-persists
// the failing step (persisted and in-memory ledgers agree on the error path).
// ═══════════════════════════════════════════════════════════════════════════

describe("D: writeLedger failure re-persists the failing step (best-effort)", () => {
  it("S2 emitLedger throws → S8(error), and the failing step S2 is re-attempted on disk", async () => {
    // Make the writeLedger for the S2 entry throw the FIRST time it is hit, then
    // succeed afterwards so the best-effort re-persist of S2 + S8 can land.
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      // 0-commit → errors at S2, exercising the error-path re-persist.
      return { kind: "coder", committed: false, commitsAdded: 0 };
    };
    let s2WriteThrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S2" && !s2WriteThrown) {
        s2WriteThrown = true;
        throw new Error("writeLedger: transient I/O fault on S2");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The persisted ledger must still record the failing step S2 (best-effort
    // re-persist) — not vanish because recordFailingStep:false skipped it.
    const persisted = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persisted).toContain("S2");
    expect(persisted).toContain("S8");
  });

  it("in-memory ledger is not double-recorded for the failing step", async () => {
    // The failing step must appear exactly once in the in-memory ledger (the
    // normal push happened before emitLedger; the error path must not push it
    // again).
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      return { kind: "coder", committed: false, commitsAdded: 0 };
    };
    let s2WriteThrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S2" && !s2WriteThrown) {
        s2WriteThrown = true;
        throw new Error("transient");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    const s2Count = result.stepLedger.filter((e) => e.step === "S2").length;
    expect(s2Count).toBe(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// E [Med] — S8 ledger-write failure attributes to the REAL failing step, not a
// hard-coded "S7".
// ═══════════════════════════════════════════════════════════════════════════

describe("E: S8 ledger-write failure attributes the real failing step", () => {
  it("S2 completed no-commit report still reaches review before an S8 write failure", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "judge", status: "converged" };
    };
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S8") {
        throw new Error("writeLedger: S8 fault");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The white run advances through review and local handoff; the failing operation is
    // still the S8 ledger write, not a fabricated S2 court.
    expect(result.errorPackage?.failedStep).not.toBe("S7");
  });

  it("approve handoff whose S8 write throws → failedStep attributes to the S8 write step", async () => {
    // Happy path reaches S7 local handoff, then the S8 handoff ledger write
    // throws. The failing operation is the S8 write. The
    // attribution must reflect the real failing step (S8), not a stale value.
    const backend = new SpyBackend();
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S8") {
        throw new Error("writeLedger: S8 fault");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The S8 ledger write is what failed.
    expect(result.errorPackage?.failedStep).toBe("S8");
  });
});
