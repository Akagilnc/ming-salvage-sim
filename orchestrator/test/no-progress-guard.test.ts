/**
 * No-progress guard tests (cmr S254, US#18 compliance).
 *
 * The runner must NEVER stop because a round counter hit a number. US#18:
 * "我不想它因为数到某个轮数就停，这样它不会还在进展时就放弃。" The PRD
 * defers any round-cap (轮数上限策略 deferred). The ONLY bail condition is a
 * stuck route/loop with NO progress — measured by a no-progress guard, not by
 * counting rounds:
 *
 *   progress  = this fix round produced a new commit (commitsAdded > 0)
 *               OR the reviewer findings changed since the previous round.
 *   no-progress = neither.
 *
 * Contract:
 *   - As long as there is progress every round, the loop runs unbounded —
 *     20, 50, 100 rounds all reach S7. (A real converging review may take many
 *     rounds; the runner must not截 it.)
 *   - Only after K consecutive no-progress rounds does the runner bail with a
 *     clean S8(status=error) + errorPackage (reason names the stuck guard).
 *     Never an uncaught throw / promise reject.
 *
 * All paths use fake Backend injection — zero real Sandcastle / LLM calls.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
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

const COMPLIANT_META: IssueMeta = {
  number: 254,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
  openBlockedBy: [],
};

const SNAPSHOT: IssueSnapshot = {
  number: 254,
  body: "no-progress guard test body",
  comments: [],
  agentBrief: "## Agent Brief\nno-progress guard",
};

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-254",
  base: "main",
  path: "/resident/worktrees/issue-254",
};

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
  location = "src/foo.ts:1",
): Finding {
  return {
    severity,
    action,
    category: "test",
    claim_quote: "some quote",
    location,
    suggested_fix: "fix it",
  };
}

function reviewerWith(findings: Finding[]): ReviewerOutput {
  return { kind: "reviewer", findings };
}

/**
 * A scripted backend (same shape as fix-loop.test.ts's ScriptedBackend) whose
 * reviewer returns a sequence of outputs and whose coder behaviour is
 * overridable. Tracks how many coder/reviewer steps ran.
 */
class ScriptedBackend implements Backend {
  readonly coderRunIds: string[] = [];
  readonly reviewerRunIds: string[] = [];
  pushCount = 0;
  prepareCount = 0;
  private reviewerCallIndex = 0;
  private coderCallIndex = 0;

  constructor(
    private readonly reviewerSequence: ReviewerOutput[],
    private readonly coderOutput?: (callIndex: number) => StepOutput,
  ) {}

  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    return { ...COMPLIANT_META, number: n };
  }
  async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
    return { ...SNAPSHOT, number: n };
  }
  async prepareWorktree(_n: number, _b: string): Promise<WorktreeHandle> {
    this.prepareCount += 1;
    return WORKTREE;
  }
  async writeSnapshot(_w: WorktreeHandle, _s: IssueSnapshot): Promise<void> {}

  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") {
      this.coderRunIds.push(spec.id);
      const idx = this.coderCallIndex++;
      if (this.coderOutput) return this.coderOutput(idx);
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    this.reviewerRunIds.push(spec.id);
    const out =
      this.reviewerSequence[this.reviewerCallIndex] ?? reviewerWith([]);
    this.reviewerCallIndex += 1;
    return out;
  }

  async push(_w: WorktreeHandle): Promise<void> {
    this.pushCount += 1;
  }
  async writeLedger(
    _e: PersistentLedgerEntry,
    _s: string,
  ): Promise<void> {}
}

// ─── a long-but-converging review (20+ rounds) is NEVER truncated ───────────

describe("no-progress guard — a converging review of 20+ rounds is not截", () => {
  it("reviewer returns P0/P1 for 20 rounds (each fix commits) then empty → reaches S7", async () => {
    const ROUNDS = 20;
    const seq: ReviewerOutput[] = [];
    // S3 + (ROUNDS-1) S6 each raise a DISTINCT P0/P1 (findings change every
    // round → progress even ignoring commits); coder commits every round too.
    for (let r = 0; r < ROUNDS; r++) {
      seq.push(
        reviewerWith([
          finding(r % 2 === 0 ? "critical" : "high", "fix_now", `src/f.ts:${r}`),
        ]),
      );
    }
    seq.push(reviewerWith([])); // converge

    const backend = new ScriptedBackend(seq);
    const result = await runOrchestrator({ issueNumber: 254, backend });

    // Must reach push/success — NOT bail on a round count.
    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    // The fix loop ran the full 20 rounds (S5 once per round).
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(ROUNDS);
    // Reviewer ran ROUNDS+1 times (S3 + ROUNDS×S6).
    expect(backend.reviewerRunIds).toHaveLength(ROUNDS + 1);
  });

  it("50 rounds with progress (commits each round) still reaches S7 — no hidden cap", async () => {
    const ROUNDS = 50;
    const seq: ReviewerOutput[] = [];
    for (let r = 0; r < ROUNDS; r++) {
      seq.push(reviewerWith([finding("high", "fix_now", `src/x.ts:${r}`)]));
    }
    seq.push(reviewerWith([]));

    const backend = new ScriptedBackend(seq);
    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.coderRunIds.filter((id) => id === "S5")).toHaveLength(ROUNDS);
  });
});

// ─── true stuck (永远 0-commit + findings unchanged) → clean S8(error) ──────

describe("no-progress guard — a genuinely stuck loop bails cleanly to S8(error)", () => {
  it("no new commit AND findings never change → K no-progress rounds → S8(error), not throw", async () => {
    // The genuine stuck shape: the fix step keeps "committing" (committed:true,
    // so route()'s 0-commit error edge does NOT fire) but adds NO new commit
    // (commitsAdded:0 → no commit progress), and the reviewer raises the SAME
    // finding forever (no findings change). Neither progress signal moves →
    // the loop would spin forever; the guard must bail after K rounds.
    const SAME = finding("critical", "fix_now", "src/stuck.ts:1");
    // An effectively infinite supply of the identical review.
    const seq: ReviewerOutput[] = Array.from({ length: 200 }, () =>
      reviewerWith([SAME]),
    );
    // committed:true (passes route 0-commit gate) but commitsAdded:0 (no real
    // progress) → the bail is driven purely by no-commit + findings-unchanged.
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 0,
    }));

    // Must RESOLVE (not throw / reject) with a clean error handoff.
    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    expect(result.errorPackage?.reason.toLowerCase()).toContain("stuck");
    expect(backend.pushCount).toBe(0);
    // The ledger ends at S8 (clean handoff, not an exception bubbling out).
    const steps = result.stepLedger.map((e) => e.step);
    expect(steps[steps.length - 1]).toBe("S8");
  });

  it("does NOT bail before K no-progress rounds (small constant, bounded ledger)", async () => {
    // Confirm the guard bails reasonably quickly — far below the old MAX_STEPS
    // cap of 32 — proving it's a small-K no-progress detector, not a high count.
    const SAME = finding("critical", "fix_now", "src/stuck.ts:1");
    const seq: ReviewerOutput[] = Array.from({ length: 200 }, () =>
      reviewerWith([SAME]),
    );
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 0,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    // S5 fix rounds before the bail should be a small constant (no-progress K),
    // not anywhere near a large count — the loop must die quickly when stuck.
    const s5 = backend.coderRunIds.filter((id) => id === "S5").length;
    expect(s5).toBeGreaterThan(0);
    expect(s5).toBeLessThanOrEqual(5);
  });
});

// ─── progress resets the guard: a stuck patch then progress keeps going ─────

describe("no-progress guard — progress in any round resets the no-progress streak", () => {
  it("a no-progress round followed by a findings-changing round does NOT trip the guard", async () => {
    // Interleave: same finding (no-progress) then a DIFFERENT finding
    // (progress) repeatedly, then converge. Because progress resets the streak,
    // it must never reach K consecutive no-progress rounds → reaches push.
    const STUCK = finding("critical", "fix_now", "src/a.ts:1");
    const seq: ReviewerOutput[] = [];
    for (let r = 0; r < 12; r++) {
      // even rounds: repeat STUCK (no findings change); odd rounds: new finding.
      seq.push(
        r % 2 === 0
          ? reviewerWith([STUCK])
          : reviewerWith([finding("high", "fix_now", `src/b.ts:${r}`)]),
      );
    }
    seq.push(reviewerWith([])); // converge

    const backend = new ScriptedBackend(seq, () => ({
      // Coder NEVER commits (commitsAdded 0) — so the ONLY progress signal is
      // findings changing. This isolates the findings-change leg of "progress".
      kind: "coder",
      committed: true,
      commitsAdded: 0,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it("a fresh commit each round counts as progress even if findings repeat", async () => {
    // Reviewer raises the SAME finding for several rounds (findings unchanged),
    // but the coder commits a NEW commit each round (commitsAdded>0). Because a
    // new commit is progress, the streak resets every round → never trips K,
    // then converges. Proves "progress" includes new commits, not only findings.
    const SAME = finding("high", "fix_now", "src/c.ts:1");
    const seq: ReviewerOutput[] = [
      reviewerWith([SAME]), // S3
      reviewerWith([SAME]), // S6 r1 — same finding
      reviewerWith([SAME]), // S6 r2 — same finding
      reviewerWith([SAME]), // S6 r3 — same finding
      reviewerWith([]), // converge
    ];
    let commit = 0;
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: ++commit, // a real new commit every round → progress
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });
});
