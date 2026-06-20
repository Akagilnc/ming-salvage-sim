/**
 * integ-cmr (base) round 2 — five cross-slice seam gaps the integrated review
 * found that per-slice cmr missed (all behavioural, test-first):
 *
 *   A [Crit] finding ELEMENTS were not validated → a malformed finding
 *     (severity with trailing space / uppercase action / missing field) slipped
 *     past the kind+Array.isArray guard.  route()'s S4 compares severity/action
 *     by string, so a malformed element → needsFix=false → push → a real P0 is
 *     SILENTLY SHIPPED past the mandatory fix gate.  Fix: validate each finding
 *     element (exact severity/action enums, required string fields).  Any
 *     malformed element → S8(error); never routed as legitimate findings.
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
import { runOrchestrator } from "../src/runner.js";
import { route } from "../src/route.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ReviewerOutput,
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

/** A well-formed finding the fan-out helper can mutate per case. */
function goodFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    severity: "critical",
    category: "correctness",
    claim_quote: "null deref at line 1",
    location: "src/foo.ts:1",
    suggested_fix: "guard the deref",
    action: "fix_now",
    ...overrides,
  };
}

/**
 * Base fake Backend. Override runStep / push / writeLedger per test.
 * writeLedger is a spy so persisted entries can be asserted independently of
 * the in-memory ledger.
 */
class SpyBackend implements Backend {
  readonly ledgerCalls: Array<{
    entry: PersistentLedgerEntry;
    stateDir: string;
  }> = [];
  readonly runStepIds: string[] = [];
  pushed = false;

  // #255 resume seam: fresh-run fake → no residue (runner consults this first).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
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
    return { kind: "reviewer", findings: [] };
  }
  async push(_w: WorktreeHandle): Promise<void> {
    this.pushed = true;
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    this.ledgerCalls.push({ entry, stateDir });
  }
}

/** A reviewer step backend that returns a chosen ReviewerOutput. */
function reviewerReturning(
  reviewerOut: StepOutput,
): SpyBackend {
  const backend = new SpyBackend();
  backend.runStep = async (spec: StepSpec) => {
    backend.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return reviewerOut;
  };
  return backend;
}

// ═══════════════════════════════════════════════════════════════════════════
// A [Crit] — finding ELEMENT validation: malformed finding → S8(error), the
// P0/P1 fix gate is NEVER silently bypassed.
// ═══════════════════════════════════════════════════════════════════════════

describe("A: finding element validation (runner end-to-end)", () => {
  // The dangerous core case: a REAL P0 with a malformed severity (trailing
  // space). route()'s S4 compares severity by exact string, so "critical " !==
  // "critical" → needsFix=false → push → the P0 is SHIPPED. Must be S8(error).
  it("severity 'critical ' (trailing space) on a P0 → S8(error), NOT pushed", async () => {
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [goodFinding({ severity: "critical " as unknown as Finding["severity"] })],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S3");
    expect(backend.pushed).toBe(false);
  });

  it("severity 'CRITICAL' (uppercase) → S8(error), NOT pushed", async () => {
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [goodFinding({ severity: "CRITICAL" as unknown as Finding["severity"] })],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("action 'FIX_NOW' (uppercase) on a P2 → S8(error), NOT pushed", async () => {
    // A medium with action 'FIX_NOW' would (under the bug) miss both the
    // severity branch AND the action==='fix_now' branch → push, shipping a
    // finding the reviewer wanted fixed.
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [
        goodFinding({
          severity: "medium",
          action: "FIX_NOW" as unknown as Finding["action"],
        }),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("finding missing claim_quote → S8(error)", async () => {
    const bad = { ...goodFinding() } as Record<string, unknown>;
    delete bad.claim_quote;
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [bad as unknown as Finding],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("finding with non-string location (number) → S8(error)", async () => {
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [
        goodFinding({ location: 123 as unknown as string }),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("finding missing action field → S8(error)", async () => {
    const bad = { ...goodFinding() } as Record<string, unknown>;
    delete bad.action;
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [bad as unknown as Finding],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("a single malformed element among well-formed ones → S8(error) (whole step)", async () => {
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [
        goodFinding({ severity: "low", action: "defer" }),
        goodFinding({ severity: "garbage" as unknown as Finding["severity"], action: "defer" }),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(backend.pushed).toBe(false);
  });

  it("regression: all-well-formed defer findings still push (approve) and surface defers", async () => {
    const backend = reviewerReturning({
      kind: "reviewer",
      findings: [
        goodFinding({ severity: "low", action: "defer" }),
        goodFinding({ severity: "clarity", action: "defer" }),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
    expect(backend.pushed).toBe(true);
    expect(result.deferredFindings).toHaveLength(2);
  });

  it("regression: empty findings still push (approve)", async () => {
    const backend = reviewerReturning({ kind: "reviewer", findings: [] });
    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
    expect(backend.pushed).toBe(true);
  });
});

describe("A: finding element validation at the route() seam (defense in depth)", () => {
  // route() is the agent↔runner seam: even though the runner guards first,
  // route()'s S4 must NEVER coerce a malformed finding into a push edge.
  function rOut(findings: Finding[]): ReviewerOutput {
    return { kind: "reviewer", findings };
  }

  it("S4 with a trailing-space critical → handoff(error), not push", () => {
    const decision = route({
      from: "S4",
      output: rOut([goodFinding({ severity: "critical " as unknown as Finding["severity"] })]),
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S4 with an uppercase action → handoff(error), not push", () => {
    const decision = route({
      from: "S4",
      output: rOut([
        goodFinding({ severity: "medium", action: "FIX_NOW" as unknown as Finding["action"] }),
      ]),
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S4 with a finding missing a required field → handoff(error)", () => {
    const bad = { ...goodFinding() } as Record<string, unknown>;
    delete bad.suggested_fix;
    const decision = route({
      from: "S4",
      output: rOut([bad as unknown as Finding]),
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S4 with all well-formed defer findings → push (regression)", () => {
    const decision = route({
      from: "S4",
      output: rOut([goodFinding({ severity: "low", action: "defer" })]),
    });
    expect(decision).toEqual({ kind: "next", step: "S7" });
  });
});

describe("integ-cmr m2 r4: S3/S6 reviewer-output validation at the route() seam (defense in depth, symmetric with S2/S5)", () => {
  // The reviewer-output edges (S3→S4, S6→S4) must reject a malformed reviewer
  // output at the producing seam — symmetric with the S2/S5 isValidCoderOutput
  // edges. The resume path drives route({from:'S3'|'S6', output: ledgerEntry})
  // off a recorded ledger output with NO runner pre-route re-check, so route()
  // must be self-defending. Without this, a malformed S6 routed blindly to S4
  // and the violation was only re-discovered a step later (after the resume
  // defer-rebuild had already crashed on the same garbage).

  it("S3 with {kind:'reviewer'} (no findings array) → handoff(error), not S4", () => {
    const decision = route({
      from: "S3",
      output: { kind: "reviewer" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S3 with findings NON-array → handoff(error), not S4", () => {
    const decision = route({
      from: "S3",
      output: { kind: "reviewer", findings: "nope" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S3 with a malformed finding element → handoff(error), not S4", () => {
    const bad = { ...goodFinding() } as Record<string, unknown>;
    delete bad.action;
    const decision = route({
      from: "S3",
      output: { kind: "reviewer", findings: [bad] } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S3 with well-formed (empty) findings → next S4 (regression)", () => {
    const decision = route({
      from: "S3",
      output: { kind: "reviewer", findings: [] },
    });
    expect(decision).toEqual({ kind: "next", step: "S4" });
  });

  it("S6 with {kind:'reviewer'} (no findings array) → handoff(error), not S4", () => {
    const decision = route({
      from: "S6",
      output: { kind: "reviewer" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S6 with findings NON-array → handoff(error), not S4", () => {
    const decision = route({
      from: "S6",
      output: { kind: "reviewer", findings: 7 } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S6 with well-formed findings → next S4 (regression, loop closure intact)", () => {
    const decision = route({
      from: "S6",
      output: { kind: "reviewer", findings: [goodFinding({ action: "defer" })] },
    });
    expect(decision).toEqual({ kind: "next", step: "S4" });
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// B [High] — coder commitsAdded validation.
// ═══════════════════════════════════════════════════════════════════════════

describe("B: coder commitsAdded validation", () => {
  it("committed:true with commitsAdded:0 (inconsistent) → S8(error), S3 NOT reached", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(backend.runStepIds).not.toContain("S3");
  });

  it("committed:false with commitsAdded:2 (inconsistent) → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 2 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("missing commitsAdded → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true } as unknown as StepOutput;
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("non-integer commitsAdded (1.5) → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: 1.5 };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("negative commitsAdded (-1) → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: -1 } as unknown as StepOutput;
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("non-number commitsAdded ('1') → S8(error)", async () => {
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: true, commitsAdded: "1" } as unknown as StepOutput;
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S2");
  });

  it("regression: committed:true with commitsAdded:1 (consistent) proceeds to S3", async () => {
    const backend = new SpyBackend(); // default: true/1
    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("success");
    expect(backend.runStepIds).toContain("S3");
  });

  it("regression: committed:false with commitsAdded:0 (consistent) → S8(error) for 0-commit (not for shape)", async () => {
    // Consistent 0-commit is still an error (coder produced nothing) but via the
    // 0-commit route, with failedStep S2 — same surface, different cause. This
    // pins that the B guard does NOT reject the legitimate consistent shape.
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
    expect(result.errorPackage?.failedStep).toBe("S2");
    expect(backend.runStepIds).not.toContain("S3");
  });

  it("the S5 fix step also validates commitsAdded (inconsistent → S8(error))", async () => {
    // Drive into the fix loop: reviewer returns a P0 on S3 → S5 coder_fix.
    // The S5 fix step returns an inconsistent coder output → S8(error) at S5.
    let reviewCount = 0;
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.id === "S2") {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      if (spec.id === "S5") {
        // inconsistent fix output
        return { kind: "coder", committed: true, commitsAdded: 0 };
      }
      // reviewer S3 → one P0 to force the fix loop
      reviewCount += 1;
      if (spec.id === "S3" && reviewCount === 1) {
        return {
          kind: "reviewer",
          findings: [goodFinding()],
        };
      }
      return { kind: "reviewer", findings: [] };
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });
    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S5");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// C [High] — S1 pre-worktree failures are an unpersistable special case (like
// S0); only post-worktree S1 (writeSnapshot) persists.
// ═══════════════════════════════════════════════════════════════════════════

describe("C: S1 pre-worktree failures are an unpersistable special case", () => {
  it("fetchIssueSnapshot throw (pre-worktree) → S8(error), nothing persisted", async () => {
    const backend = new SpyBackend();
    backend.fetchIssueSnapshot = async () => {
      throw new Error("gh: rate limit exceeded");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S1");
    // No worktree yet → no sibling stateDir → nothing can be persisted.
    expect(backend.ledgerCalls).toHaveLength(0);
    // In-memory ledger still records the S8 termination.
    expect(result.stepLedger.map((e) => e.step)).toContain("S8");
  });

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

  it("writeSnapshot throw (POST-worktree S1) DOES persist S1 and S8 (contrast)", async () => {
    // This is the persistable S1 case: the worktree exists, so the sibling
    // stateDir is resolved and the error termination persists.
    const backend = new SpyBackend();
    backend.writeSnapshot = async () => {
      throw new Error("ENOSPC");
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    const persisted = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persisted).toContain("S1");
    expect(persisted).toContain("S8");
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// D [High] — writeLedger failure on a normal step still best-effort re-persists
// the failing step (persisted and in-memory ledgers agree on the error path).
// ═══════════════════════════════════════════════════════════════════════════

describe("D: writeLedger failure re-persists the failing step (best-effort)", () => {
  it("S3 emitLedger throws → S8(error), and the failing step S3 is re-attempted on disk", async () => {
    // Make the writeLedger for the S3 entry throw the FIRST time it is hit, then
    // succeed afterwards so the best-effort re-persist of S3 + S8 can land.
    const backend = new SpyBackend();
    let s3WriteThrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S3" && !s3WriteThrown) {
        s3WriteThrown = true;
        throw new Error("writeLedger: transient I/O fault on S3");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // The persisted ledger must still record the failing step S3 (best-effort
    // re-persist) — not vanish because recordFailingStep:false skipped it.
    const persisted = backend.ledgerCalls.map((c) => c.entry.step);
    expect(persisted).toContain("S3");
    expect(persisted).toContain("S8");
  });

  it("in-memory ledger is not double-recorded for the failing step", async () => {
    // The failing step must appear exactly once in the in-memory ledger (the
    // normal push happened before emitLedger; the error path must not push it
    // again).
    const backend = new SpyBackend();
    let s3WriteThrown = false;
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S3" && !s3WriteThrown) {
        s3WriteThrown = true;
        throw new Error("transient");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    const s3Count = result.stepLedger.filter((e) => e.step === "S3").length;
    expect(s3Count).toBe(1);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// E [Med] — S8 ledger-write failure attributes to the REAL failing step, not a
// hard-coded "S7".
// ═══════════════════════════════════════════════════════════════════════════

describe("E: S8 ledger-write failure attributes the real failing step", () => {
  it("S2 no-commit handoff whose S8 write throws → failedStep is NOT hard-coded S7", async () => {
    // Route into an S8 error handoff from S2 (0-commit). Then make the S8 ledger
    // write throw. The old code hard-coded failedStep:'S7' here, even though
    // push never ran. It must attribute to the step that actually failed.
    const backend = new SpyBackend();
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      return { kind: "reviewer", findings: [] };
    };
    backend.writeLedger = async (entry, stateDir) => {
      if (entry.step === "S8") {
        throw new Error("writeLedger: S8 fault");
      }
      backend.ledgerCalls.push({ entry, stateDir });
    };

    const result = await runOrchestrator({ issueNumber: 244, backend });

    expect(result.status).toBe("error");
    // push never ran on a 0-commit error path → must not be attributed to S7.
    expect(result.errorPackage?.failedStep).not.toBe("S7");
    expect(backend.pushed).toBe(false);
  });

  it("approve handoff (S7 push success) whose S8 write throws → failedStep attributes to the S8 write step", async () => {
    // Happy path reaches S7 push (success), then the S8 handoff ledger write
    // throws. Here push DID run; the failing operation is the S8 write. The
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
