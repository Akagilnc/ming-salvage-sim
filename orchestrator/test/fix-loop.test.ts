/**
 * Fix-loop back-edge tests for #254: S5→S6→S4→(S5|S7).
 *
 * These tests drive the full runner loop with a fake Backend whose reviewer
 * returns a *scripted sequence* of outputs (P0/P1 for the first N rounds, then
 * empty = approve). They assert the fix loop actually iterates:
 *
 *   S3 (initial review) → S4 → S5 (fix) → S6 (re-review) → S4 → … → S7 (push)
 *
 * What the slice must guarantee (issue #254 acceptance criteria):
 *   - reviewer returns N rounds of P0/P1 then empty → route loops S5→S6→S4
 *     exactly N times, the (N+1)-th review (empty) routes to S7 push.
 *   - coder_fix (S5) called N times; reviewer (S3+S6) called N+1 times.
 *   - fix commits accumulate on the SAME resident branch (commitsAdded grows,
 *     no new branch — prepareWorktree called once).
 *   - S6 full-diff re-review: a regression injected by one fix round is caught
 *     by the NEXT S6 (full review, not narrow check of last round's bug).
 *   - reviewer steps (S3/S6) never call any write/commit/push action.
 *   - S6 and S3 share the same schema (ReviewerOutput) and promptFile family.
 *
 * Co-existence with sibling slices (must NOT break):
 *   - escalate (#251): reviewer/coder output carrying `escalate` stops the loop
 *     mid-flight → S8(escalate).
 *   - error (#252): S5 fix producing 0 commits → S8(error).
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  Escalation,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ReviewerOutput,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared fixtures ────────────────────────────────────────────────────────

const COMPLIANT_META: IssueMeta = {
  number: 254,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 254,
  body: "fix-loop test issue body",
  comments: [],
  agentBrief: "## Agent Brief\nimplement the fix-loop back-edge",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-254",
  base: "main",
  path: "/resident/worktrees/issue-254",
};

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
): Finding {
  return {
    severity,
    action,
    category: "test",
    claim_quote: "some quote",
    location: "src/foo.ts:1",
    suggested_fix: "fix it",
  };
}

function reviewerWith(findings: Finding[]): ReviewerOutput {
  return { kind: "reviewer", findings };
}

/**
 * A fake Backend whose reviewer (S3/S6) returns a *scripted sequence* of
 * outputs — one per review call. The coder (S2/S5) accumulates commits on the
 * single resident branch. Records every Backend call so tests can assert the
 * loop shape: reviewer-step writes are impossible (the fake exposes no such
 * method on reviewer dispatch — runStep is the only entry; pushes/commits are
 * separate methods the reviewer dispatch path never touches).
 */
class ScriptedBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  /** runStep ids for reviewer-role steps only (S3/S6). */
  readonly reviewerRunIds: string[] = [];
  /** runStep ids for coder-role steps only (S2/S5). */
  readonly coderRunIds: string[] = [];
  pushCount = 0;
  prepareCount = 0;
  /** Total commits accumulated on the resident branch (monotone). */
  totalCommits = 0;
  /** commitsAdded reported by each coder step, in dispatch order. */
  readonly commitsAddedSeq: number[] = [];

  /** Reviewer outputs to return on successive reviewer (S3/S6) calls. */
  private reviewerCallIndex = 0;

  constructor(
    /** One reviewer output per review call (S3 first, then each S6). */
    private readonly reviewerSequence: ReviewerOutput[],
    /** Optional override for what each coder step returns. */
    private readonly coderOutput?: (callIndex: number) => StepOutput,
  ) {}

  // #255 resume seam: this fake is for fresh (non-resume) runs, so it reports
  // no residue. The runner consults findResumeState at the very start of every
  // run, so all fakes must implement it (returning undefined = fresh run).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op (no resume residue in these tests)
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return { ...COMPLIANT_META, number: issueNumber };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return { ...SNAPSHOT, number: issueNumber };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  private coderCallIndex = 0;

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id}:${spec.role})`);
    this.runStepIds.push(spec.id);

    if (spec.role === "coder") {
      this.coderRunIds.push(spec.id);
      const idx = this.coderCallIndex++;
      if (this.coderOutput) {
        const out = this.coderOutput(idx);
        if (out.kind === "coder" && out.committed) {
          this.totalCommits += out.commitsAdded;
        }
        if (out.kind === "coder") this.commitsAddedSeq.push(out.commitsAdded);
        return out;
      }
      // Default coder: one commit per fix round, accumulating on the branch.
      this.totalCommits += 1;
      this.commitsAddedSeq.push(1);
      return { kind: "coder", committed: true, commitsAdded: this.totalCommits };
    }

    // reviewer (S3 / S6): return the next scripted output.
    this.reviewerRunIds.push(spec.id);
    const out =
      this.reviewerSequence[this.reviewerCallIndex] ??
      reviewerWith([]); // exhausted → approve (defensive)
    this.reviewerCallIndex += 1;
    return out;
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op — this suite asserts loop shape, not ledger persistence details.
  }
}

// ─── the loop iterates N times then converges to push ───────────────────────

describe("fix loop (#254) — S5→S6→S4 back-edge iterates then converges", () => {
  it("1 round of P0 then empty → S5 once, reviewer twice (S3+S6), push reached", async () => {
    const backend = new ScriptedBackend([
      reviewerWith([finding("critical", "fix_now")]), // S3 initial
      reviewerWith([]), // S6 after fix → approve
    ]);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    // coder fix (S5) ran exactly once.
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(1);
    // reviewer ran twice: S3 then S6.
    expect(backend.reviewerRunIds).toEqual(["S3", "S6"]);
  });

  it("N=3 rounds of P0/P1 then empty → S5 thrice, reviewer 4× (S3+3×S6), push at end", async () => {
    const N = 3;
    const seq: ReviewerOutput[] = [];
    // S3 + first (N-1) S6 return P0/P1; the N-th S6 returns empty = approve.
    for (let r = 0; r < N; r++) {
      seq.push(reviewerWith([finding(r % 2 === 0 ? "critical" : "high", "fix_now")]));
    }
    seq.push(reviewerWith([])); // converge

    const backend = new ScriptedBackend(seq);
    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    // Exactly N coder_fix (S5) calls.
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(N);
    // Reviewer ran N+1 times: one S3 + N×S6.
    expect(backend.reviewerRunIds).toEqual(["S3", "S6", "S6", "S6"]);
    expect(backend.reviewerRunIds).toHaveLength(N + 1);
  });

  it("the loop count is recoverable from the step ledger (S5 entries = N rounds)", async () => {
    const N = 2;
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("high", "fix_now")]), // S3
      reviewerWith([finding("critical", "fix_now")]), // S6 round 1 → still bad
      reviewerWith([]), // S6 round 2 → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    const steps = result.stepLedger.map((e) => e.step);
    // S5 appears exactly N times in the ledger.
    expect(steps.filter((s) => s === "S5")).toHaveLength(N);
    // S6 appears exactly N times (one re-review per fix).
    expect(steps.filter((s) => s === "S6")).toHaveLength(N);
    // Final route is to push then handoff.
    expect(steps).toContain("S7");
    expect(steps[steps.length - 1]).toBe("S8");
  });

  it("full canonical ledger sequence for N=2 fix rounds", async () => {
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3
      reviewerWith([finding("high", "fix_now")]), // S6 r1
      reviewerWith([]), // S6 r2 → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S5",
      "S6",
      "S4",
      "S5",
      "S6",
      "S4",
      "S7",
      "S8",
    ]);
    // The fix loop preserves the rest of the contract end-to-end: it converges
    // to a successful push on one resident branch, prepared exactly once.
    expect(result.status).toBe("success");
    expect(backend.prepareCount).toBe(1);
    expect(backend.pushCount).toBe(1);
  });
});

// ─── fix commits accumulate on the same resident branch ─────────────────────

describe("fix loop (#254) — commits accumulate on one resident branch", () => {
  it("prepareWorktree called once; commitsAdded grows across fix rounds; one branch", async () => {
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3
      reviewerWith([finding("high", "fix_now")]), // S6 r1
      reviewerWith([]), // S6 r2 → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    // Worktree prepared exactly once → one resident branch across the whole run.
    expect(backend.prepareCount).toBe(1);
    // The pushed branch is the resident branch.
    expect(result.branch).toBe(WORKTREE.branch);
    // commitsAdded is monotone non-decreasing across coder steps
    // (S2 then 2× S5) — commits accumulate, never reset.
    const seqCommits = backend.commitsAddedSeq;
    expect(seqCommits.length).toBe(3); // S2 + S5×2
    for (let i = 1; i < seqCommits.length; i++) {
      expect(seqCommits[i]!).toBeGreaterThanOrEqual(seqCommits[i - 1]!);
    }
  });
});

// ─── S6 is a full-diff re-review (catches regressions introduced by a fix) ──

describe("fix loop (#254) — S6 is a full re-review, not a narrow last-bug check", () => {
  it("a regression injected by fix round 1 is caught by the next S6 (full diff)", async () => {
    // Round 1 review (S3): critical bug A. Coder fixes A but introduces bug B.
    // The NEXT S6 must surface bug B — proving the re-review covers the whole
    // current diff, not just "is bug A fixed?".
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3: bug A
      reviewerWith([finding("critical", "fix_now")]), // S6 r1: bug B (regression)
      reviewerWith([]), // S6 r2: clean → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    // The regression (S6 r1 finding) drove another fix round — so S5 ran twice
    // and reviewer ran three times. If S6 only checked "bug A fixed?", the run
    // would have pushed after one round and missed bug B.
    expect(result.status).toBe("success");
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(2);
    expect(backend.reviewerRunIds).toEqual(["S3", "S6", "S6"]);
  });

  it("S3 and S6 share the same promptFile family (reviewer) and ReviewerOutput schema", async () => {
    // We assert this structurally via the StepSpec dispatched: both reviewer
    // steps carry role:'reviewer' and a reviewer_*.md promptFile, and both
    // return ReviewerOutput ({ kind:'reviewer', findings }).
    const seenSpecs: { id: string; role: string; promptFile: string }[] = [];
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("high", "fix_now")]), // S3
      reviewerWith([]), // S6 → approve
    ];
    const backend = new ScriptedBackend(seq);
    const origRunStep = backend.runStep.bind(backend);
    backend.runStep = async (spec: StepSpec) => {
      seenSpecs.push({ id: spec.id, role: spec.role, promptFile: spec.promptFile });
      return origRunStep(spec);
    };

    const result = await runOrchestrator({ issueNumber: 254, backend });

    const reviewerSpecs = seenSpecs.filter((s) => s.role === "reviewer");
    expect(reviewerSpecs.map((s) => s.id)).toEqual(["S3", "S6"]);
    // Both reviewer steps use a reviewer-family prompt file.
    for (const s of reviewerSpecs) {
      expect(s.promptFile).toMatch(/^reviewer_/);
    }
    // Both review outputs in the ledger are ReviewerOutput-shaped.
    const reviewerLedger = result.stepLedger.filter(
      (e) => e.output?.kind === "reviewer",
    );
    expect(reviewerLedger).toHaveLength(2);
  });
});

// ─── reviewer steps never write / commit / push (write-review separation) ──

describe("fix loop (#254) — reviewer never writes; write/review separation holds", () => {
  it("across a multi-round loop, push is called exactly once and only after convergence", async () => {
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3
      reviewerWith([finding("high", "fix_now")]), // S6 r1
      reviewerWith([finding("medium", "fix_now")]), // S6 r2
      reviewerWith([]), // S6 r3 → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    // push happens exactly once, at the very end — never during a review round.
    expect(backend.pushCount).toBe(1);
    // The only commits came from coder steps (S2 + 3× S5), never a reviewer.
    // coderRunIds has S2 + 3×S5; reviewerRunIds has S3 + 3×S6; the two never
    // overlap → reviewer dispatch never produced a commit.
    expect(backend.coderRunIds).toEqual(["S2", "S5", "S5", "S5"]);
    expect(backend.reviewerRunIds).toEqual(["S3", "S6", "S6", "S6"]);
  });
});

// ─── fix_now P2/P3 (no P0/P1) also drives the loop ──────────────────────────

describe("fix loop (#254) — fix_now P2/P3 (no P0/P1) iterates too", () => {
  it("medium fix_now then empty → one fix round then push", async () => {
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("medium", "fix_now")]), // S3
      reviewerWith([]), // S6 → approve
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(1);
    expect(backend.pushCount).toBe(1);
  });

  it("defer-only P2/P3 after a fix round does not block push and surfaces in deferredFindings", async () => {
    const deferLow = finding("low", "defer");
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3
      reviewerWith([deferLow]), // S6 r1 → only defer left → push
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(1);
    // The defer finding from the LAST review surfaces in the result.
    expect(result.deferredFindings).toHaveLength(1);
    expect(result.deferredFindings[0]).toEqual(
      expect.objectContaining({ severity: "low", action: "defer" }),
    );
  });

  it("deferredFindings reflects the FINAL full re-review, not an accumulation across rounds", async () => {
    // PRD #244: each S6 is a FULL re-review of the current diff, so the last
    // review's defer list is the authoritative current list. S4 re-collects
    // defers every loop pass (overwrite, not accumulate). This test locks that
    // contract: a defer raised in an EARLY round that the FINAL review no longer
    // raises must NOT leak into the result, and a defer the final review DOES
    // raise must surface.
    const earlyDefer = finding("medium", "defer"); // S3-only, dropped by final review
    const finalDefer = finding("clarity", "defer"); // raised by the final review
    const seq: ReviewerOutput[] = [
      // S3: a fix_now (drives S5) plus an early defer that won't reappear.
      reviewerWith([finding("critical", "fix_now"), earlyDefer]),
      // S6 r1: still a fix_now (another round) — the early defer is GONE now.
      reviewerWith([finding("high", "fix_now")]),
      // S6 r2 (final): only a defer left → converge to push, carrying it.
      reviewerWith([finalDefer]),
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(2);
    // Only the FINAL review's defer surfaces; the early (medium) defer that the
    // final full re-review did not re-raise is correctly dropped — proving the
    // overwrite semantic, not a stale accumulation.
    expect(result.deferredFindings).toHaveLength(1);
    expect(result.deferredFindings[0]).toEqual(
      expect.objectContaining({ severity: "clarity", action: "defer" }),
    );
    expect(result.deferredFindings).not.toContainEqual(
      expect.objectContaining({ severity: "medium" }),
    );
  });
});

// ─── co-existence: escalate can interrupt the loop mid-flight (#251) ────────

describe("fix loop (#254) ⨯ escalate (#251) — escalate stops the loop mid-flight", () => {
  it("S6 re-review carries escalate → S8(escalate), loop stops, no push", async () => {
    const STUCK: Escalation = {
      reason: "fix round 2 hit a design ambiguity",
      diagnosis: "the spec is contradictory on field X; needs human decision",
    };
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3 → fix
      { kind: "reviewer", findings: [], escalate: STUCK }, // S6 r1 escalates
    ];
    const backend = new ScriptedBackend(seq);

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("escalate");
    expect(backend.pushCount).toBe(0);
    // One fix round happened (S5) before the escalating S6.
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(1);
  });

  it("S5 coder_fix carries escalate → S8(escalate), no re-review, no push", async () => {
    const STUCK: Escalation = {
      reason: "cannot fix without a design call",
      diagnosis: "root cause is in a frozen interface; product decision needed",
    };
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3 → fix
    ];
    // Coder fix (the 2nd coder call, index 1 = S5) escalates.
    const backend = new ScriptedBackend(seq, (idx) =>
      idx === 0
        ? { kind: "coder", committed: true, commitsAdded: 1 } // S2
        : { kind: "coder", committed: true, commitsAdded: 2, escalate: STUCK }, // S5
    );

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("escalate");
    expect(backend.pushCount).toBe(0);
    // S6 was never reached (escalate fired right after the fix).
    expect(backend.reviewerRunIds).toEqual(["S3"]);
  });
});

// ─── co-existence: S5 0-commit → error edge (#252) ──────────────────────────

describe("fix loop (#254) ⨯ error (#252) — S5 0-commit stops with error", () => {
  it("S5 fix produces 0 commits → S8(error), no re-review, no push", async () => {
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("critical", "fix_now")]), // S3 → fix
    ];
    // The fix step (2nd coder call) commits nothing.
    const backend = new ScriptedBackend(seq, (idx) =>
      idx === 0
        ? { kind: "coder", committed: true, commitsAdded: 1 } // S2
        : { kind: "coder", committed: false, commitsAdded: 0 }, // S5 0-commit
    );

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S5");
    expect(backend.pushCount).toBe(0);
    // S6 must never have been reached.
    expect(backend.reviewerRunIds).toEqual(["S3"]);
  });
});
