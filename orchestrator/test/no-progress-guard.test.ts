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
  it("commits each round but findings never change → K no-progress rounds → S8(error), not throw", async () => {
    // The genuine stuck shape under base rule B: the fix step keeps committing a
    // REAL new commit every round (committed:true, commitsAdded:1 — a valid,
    // contract-consistent coder output, so route()'s S5 0-commit error edge does
    // NOT fire), but the reviewer raises the SAME finding forever (no findings
    // change). The fix never moves the review → the loop would spin forever; the
    // guard must bail after K rounds. (Under rule B the old "committed:true,
    // commitsAdded:0" shape is a contract violation; a 0-commit fix is
    // committed:false → caught earlier by the S5 0-commit edge. So the
    // findings-unchanged-despite-commits loop is THE stuck shape this guard
    // catches.)
    const SAME = finding("critical", "fix_now", "src/stuck.ts:1");
    // An effectively infinite supply of the identical review.
    const seq: ReviewerOutput[] = Array.from({ length: 200 }, () =>
      reviewerWith([SAME]),
    );
    // committed:true + commitsAdded:1 (valid, passes route 0-commit gate) → the
    // bail is driven purely by findings-unchanged across rounds.
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
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
      commitsAdded: 1,
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
      // Coder commits a real new commit each round (commitsAdded:1, valid under
      // rule B) — the ONLY progress signal is findings changing. This isolates
      // the findings-change leg of "progress": odd rounds change the finding →
      // streak resets → never reaches K consecutive no-progress rounds.
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it("changed findings every round is progress and converges, even with steady commits", async () => {
    // Integ reconcile (#254 ⋈ base rule B): the original #254 test here asserted
    // "a fresh commit each round = progress even if findings repeat". Under base
    // rule B that premise no longer holds: the commit-leg of the progress signal
    // is degenerate (every committed fix has commitsAdded ≥ 1), so a loop where
    // the reviewer raises the SAME finding round after round is genuinely stuck
    // regardless of commits (US#19: 在打磨次要的 / findings 不动) and MUST bail —
    // the contract-faithful progress signal is findings-change. This test now
    // asserts the corrected semantics: when the findings DO change each round,
    // that is real progress and the loop converges (the same converging path the
    // commit-only version meant to protect, expressed via the real signal).
    const seq: ReviewerOutput[] = [
      reviewerWith([finding("high", "fix_now", "src/c.ts:1")]), // S3
      reviewerWith([finding("high", "fix_now", "src/c.ts:2")]), // S6 r1 — changed
      reviewerWith([finding("high", "fix_now", "src/c.ts:3")]), // S6 r2 — changed
      reviewerWith([finding("high", "fix_now", "src/c.ts:4")]), // S6 r3 — changed
      reviewerWith([]), // converge
    ];
    let commit = 0;
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: ++commit, // a real new commit every round (valid, rule B)
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it("steady real commits but the SAME finding forever still bails (commits are not a free pass)", async () => {
    // The flip side of the above: the coder commits a real new commit every
    // round (valid under rule B) but the reviewer raises the IDENTICAL finding
    // forever. Under the contract-faithful findings-change signal this is NOT
    // progress — the commits never move the review — so the guard MUST bail
    // after K consecutive no-progress rounds (it does not treat "committed
    // something" as progress).
    const SAME = finding("high", "fix_now", "src/c.ts:1");
    const seq: ReviewerOutput[] = Array.from({ length: 200 }, () =>
      reviewerWith([SAME]),
    );
    let commit = 0;
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: ++commit, // genuine commits, yet review never moves
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason.toLowerCase()).toContain("stuck");
    expect(backend.pushCount).toBe(0);
    const s5 = backend.coderRunIds.filter((id) => id === "S5").length;
    expect(s5).toBeLessThanOrEqual(5);
  });
});

// ─── findings-change signal must be normalized (序变 ≠ 进展) ─────────────────

/**
 * Build a Finding whose object keys are inserted in a DIFFERENT order than the
 * canonical `finding()` helper. `JSON.stringify` serialises keys in insertion
 * order, so a naive stringify would treat this as a different string even
 * though the field VALUES are identical. A correct normalised comparison must
 * treat it as the SAME finding.
 */
function findingScrambledKeys(
  severity: Finding["severity"],
  action: Finding["action"],
  location = "src/foo.ts:1",
): Finding {
  // Keys deliberately out of declaration order, with values matching finding().
  return {
    suggested_fix: "fix it",
    location,
    claim_quote: "some quote",
    action,
    category: "test",
    severity,
  } as Finding;
}

describe("no-progress guard — findings-change signal is normalized (序变不算进展)", () => {
  it("same findings every round but key/array order shuffled + 0 commit → still bails (no false progress)", async () => {
    // The reviewer reports the SAME logical findings every round, but each round
    // the object key order AND the array element order are permuted. A raw
    // JSON.stringify would see an ever-changing string → findingsChanged always
    // true → the true-stuck loop would never accumulate to K and the guard is
    // bypassed (exactly the bug it should catch). With normalization, the
    // serialised key must be identical across rounds → the loop bails after K.
    const A = finding("critical", "fix_now", "src/a.ts:1");
    const B = finding("high", "fix_now", "src/b.ts:2");
    const Ascr = findingScrambledKeys("critical", "fix_now", "src/a.ts:1");
    const Bscr = findingScrambledKeys("high", "fix_now", "src/b.ts:2");

    // S3 then S6×N: the SAME two findings, but the order of the pair AND the key
    // order inside each finding flip-flops every round. Logical content is
    // constant; only serialisation order changes.
    const seq: ReviewerOutput[] = [];
    for (let r = 0; r < 200; r++) {
      seq.push(
        r % 2 === 0
          ? reviewerWith([A, B]) // canonical order, canonical keys
          : reviewerWith([Bscr, Ascr]), // reversed array + scrambled keys
      );
    }

    // Real new commit every round (commitsAdded:1, valid under rule B) so the
    // ONLY progress signal is findings-change. With normalization the LOGICAL
    // findings are unchanged → no progress → K consecutive no-progress rounds →
    // clean S8(error). (A raw stringify would see the reorder as a change and
    // never bail — the exact bug normalization fixes.)
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason.toLowerCase()).toContain("stuck");
    expect(backend.pushCount).toBe(0);
    // Stuck loop dies fast — a small constant, NOT spinning indefinitely.
    const s5 = backend.coderRunIds.filter((id) => id === "S5").length;
    expect(s5).toBeLessThanOrEqual(5);
  });

  it("a real findings content change (add/remove/edit a finding) is still progress (not masked by normalization)", async () => {
    // Guard against over-normalization: the normalised key must still DIFFER
    // when the actual finding content changes. Each round changes a real field
    // (location), so every round is genuine progress → never trips K → converge.
    const seq: ReviewerOutput[] = [];
    for (let r = 0; r < 12; r++) {
      // genuinely different finding content each round (different location).
      seq.push(reviewerWith([finding("critical", "fix_now", `src/real.ts:${r}`)]));
    }
    seq.push(reviewerWith([])); // converge

    // Real commit each round (commitsAdded:1, valid under rule B); the progress
    // must be detected purely from the changing findings content.
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });
});

// ─── off-by-one: a true-stuck loop bails at EXACTLY round K, not K+1 ─────────

describe("no-progress guard — bails at exactly K=3 no-progress rounds (off-by-one)", () => {
  it("S3 finding seeds the baseline so the FIRST S6 round counts, bail on the Kth round", async () => {
    // The genuine-stuck shape under rule B: identical finding from S3 onward,
    // with a real new commit each round (commitsAdded:1). The contract is K=3 —
    // the loop must bail after exactly 3 consecutive no-progress fix rounds.
    // Because prevFindingsKey is seeded from the S3 review, the first S6 round
    // (which repeats the S3 finding) ALREADY counts as a no-progress round;
    // without seeding it would be a false "progress" round and the bail would
    // slip to the 4th round (off-by-one).
    //
    // Expected exact S5 count = K = 3:
    //   round 1 (S6 #1): findings == S3 → no-progress, streak 1
    //   round 2 (S6 #2): no-progress, streak 2
    //   round 3 (S6 #3): no-progress, streak 3 == K → bail
    const SAME = finding("critical", "fix_now", "src/stuck.ts:1");
    const seq: ReviewerOutput[] = Array.from({ length: 200 }, () =>
      reviewerWith([SAME]),
    );
    const backend = new ScriptedBackend(seq, () => ({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    }));

    const result = await runOrchestrator({ issueNumber: 254, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason.toLowerCase()).toContain("stuck");
    // EXACTLY K=3 fix rounds before the bail — proves the off-by-one fix:
    // S5 ran once per no-progress round, and there were exactly 3 of them.
    const s5 = backend.coderRunIds.filter((id) => id === "S5").length;
    expect(s5).toBe(3);
  });
});
