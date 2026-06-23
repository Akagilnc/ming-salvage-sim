/**
 * #337 — the收口 slice: prove the runner is a PURE SCHEDULER (ADR 0026).
 *
 * After #331–#336 every productive wiki step (coder/reviewer/fix/ship) is a
 * WORKER dispatched through the single `dispatchWorker` seam, and the runner
 * only does gate / route / 排序 / ledger / 续跑. This slice LOCKS THAT IN with
 * three assertions the dependent slices left implicit:
 *
 *   (A) runner 零具体活 — the runner never reaches for a legacy backend method
 *       (`runStep` / `resumeSession` / `push`) directly: every productive step
 *       goes through `dispatchWorker`. Proven two ways: a STATIC guard over the
 *       runner source (no `backend.runStep(` / `backend.resumeSession(` /
 *       `backend.push(` call sites), AND a BEHAVIOURAL guard — a backend whose
 *       legacy methods all THROW still runs end-to-end (so the only path that
 *       produced work was `dispatchWorker`).
 *
 *   (B) fix worker — the S5 fix step is a WORKER the runner dispatches (it does
 *       NOT inline the fix). Its spec invokes `/tdd` (which routes through
 *       `/diagnosing-bugs` for a hard bug — the prompt + CLAUDE.md routing), and
 *       a NORMAL fix round is `session:"fresh"` (keeps git-truthing + maxIter),
 *       NOT the crash/escalate `resumeSession` path (ADR 0026 invariant).
 *
 *   (C) review-decomposition (#334 deferred P2) — the per-slice reviewer worker
 *       runs ONLY `/review`; the cross-family integrated cmr is the SEPARATE
 *       `ak-cross-m-review` worker. The baked reviewer soul + the repo-root
 *       CLAUDE.md `## Skill routing` must NOT say the per-slice reviewer runs
 *       "two passes, both" (the stale human two-pass-per-slice wording).
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
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
} from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = join(here, "..", "src");
const promptsDir = join(here, "..", "prompts");
const soulsDir = join(here, "..", "image", "souls");
const repoRoot = join(here, "..", "..");

// ─── (A) runner 零具体活 — no inline productive work ─────────────────────────

describe("#337 runner is a pure scheduler — no inline productive work (STATIC)", () => {
  const runnerSrc = readFileSync(join(srcDir, "runner.ts"), "utf8");
  // Strip line comments + block comments so a `// backend.push()` mention in
  // prose (e.g. the family no-op comment) is NOT counted as a call site. Only
  // real call expressions remain.
  const code = runnerSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");

  it("never calls backend.runStep directly (it dispatches a worker)", () => {
    expect(code).not.toMatch(/backend\.runStep\s*\(/);
  });

  it("never calls backend.resumeSession directly (the seam owns resume)", () => {
    expect(code).not.toMatch(/backend\.resumeSession\s*\(/);
  });

  it("never calls backend.push directly (ship is a worker)", () => {
    expect(code).not.toMatch(/backend\.push\s*\(/);
  });

  it("dispatches every productive step through dispatchWorker (the single seam)", () => {
    // The seam is imported and called; the only productive-work path the runner
    // has is dispatchWorker (the static no-legacy-call guards above prove there
    // is no other).
    expect(code).toMatch(/dispatchWorker\s*\(/);
  });
});

/**
 * A backend whose every LEGACY productive method THROWS — only `dispatchWorker`
 * produces work. If the runner ran end-to-end on this backend, every productive
 * step necessarily went through the seam (a single direct legacy call would
 * throw and abort to S8(error)).
 */
class SeamOnlyBackend implements Backend {
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  private reviewCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-337",
    base: "main",
    path: "/resident/worktrees/issue-337",
  };

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  // The three legacy productive methods: any DIRECT runner call is a bug.
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — runner is not a pure scheduler");
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession called directly — runner is not a pure scheduler");
  }
  async push(): Promise<void> {
    throw new Error("push called directly — runner is not a pure scheduler");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return { number: issueNumber, isReadyForAgent: true, hasSubIssues: false, openBlockedBy: [] };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}:${spec.skill ?? "—"}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    if (spec.kind === "coder") {
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if (spec.kind === "reviewer") {
      this.reviewCount += 1;
      const findings: Finding[] =
        this.reviewCount === 1
          ? [
              {
                severity: "high",
                category: "correctness",
                claim_quote: "x",
                location: "f.ts:1",
                suggested_fix: "fix it",
                action: "fix_now",
              },
            ]
          : [];
      return { kind: "completed", output: { kind: "reviewer", findings } };
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

describe("#337 runner is a pure scheduler — no inline productive work (BEHAVIOURAL)", () => {
  it("a backend whose legacy methods all throw still runs end-to-end via the seam", async () => {
    const backend = new SeamOnlyBackend();
    const result = await runOrchestrator({ issueNumber: 337, backend });
    // Reached S8(success) without ever touching a throwing legacy method.
    expect(result.status).toBe("success");
    // Every productive step was a worker dispatch — including the fix loop.
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/review",
      "S5:coder:/tdd",
      "S6:reviewer:/review",
      "S7:ship:gstack-ship",
    ]);
  });
});

// ─── (B) the fix step is a WORKER (dispatched, not inlined) ──────────────────

describe("#337 the S5 fix step is a worker the runner dispatches", () => {
  it("the S5 fix worker invokes /tdd (which routes through /diagnosing-bugs for a hard bug)", async () => {
    const backend = new SeamOnlyBackend();
    await runOrchestrator({ issueNumber: 337, backend });
    const s5 = backend.specs.find((s) => s.id === "S5");
    expect(s5?.kind).toBe("coder");
    expect(s5?.skill).toBe("/tdd");
    // The fix worker carries the round's fix_now findings (it does not re-derive
    // them — the runner schedules + delivers them; US#13).
    const s5Ctx = backend.ctxs[backend.specs.findIndex((s) => s.id === "S5")];
    expect(s5Ctx.prevFindings?.[0].action).toBe("fix_now");
  });

  it("a NORMAL fix round is session:'fresh' — NOT the crash/escalate resume path (ADR 0026 invariant)", async () => {
    const backend = new SeamOnlyBackend();
    await runOrchestrator({ issueNumber: 337, backend });
    const s5 = backend.specs.find((s) => s.id === "S5");
    // Normal fix keeps git-truthing + maxIter (session:"fresh"); resumeSession is
    // reserved for crash/escalate (resumeSessionId present), never set here.
    expect(s5?.session).toBe("fresh");
    const s5Ctx = backend.ctxs[backend.specs.findIndex((s) => s.id === "S5")];
    expect(s5Ctx.resumeSessionId).toBeUndefined();
  });

  it("the fix worker spec carries the iterative maxIter (>1), not a reviewer's single pass", async () => {
    // Assert on the spec the RUNNER ACTUALLY DISPATCHES (STEP_SPECS.S5 → the fix
    // worker), not a hand-built local spec — so a regression of the real S5 maxIter
    // to a reviewer's 1 is caught (cmr S337 r2). The fix worker keeps the within-step
    // iterative budget — the ADR 0026 invariant 'normal fix keeps … maxIter'.
    const backend = new SeamOnlyBackend();
    await runOrchestrator({ issueNumber: 337, backend });
    const s5 = backend.specs.find((s) => s.id === "S5");
    expect(s5).toBeDefined();
    expect(s5!.maxIter).toBeGreaterThan(1);
    expect(s5!.session).toBe("fresh");
    expect(s5!.contextRetention).toBe("retain"); // production worker retains context
    expect(s5!.skill).toBe("/tdd");
  });
});

describe("#337 the fix-loop fork lives in the runner, not inside a worker", () => {
  it("the runner re-dispatches S5(fix)→S6(re-review) and routes on the S6 verdict", async () => {
    // A backend that needs TWO fix rounds before the reviewer approves. If the
    // fork (fix-or-proceed) were inside a worker, the runner would see one
    // worker; instead it dispatches each S5/S6 itself and routes each verdict.
    class TwoRoundBackend extends SeamOnlyBackend {
      private rc = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        this.dispatched.push(`${spec.id}:${spec.kind}:${spec.skill ?? "—"}`);
        this.specs.push(spec);
        this.ctxs.push(ctx);
        if (spec.kind === "coder") {
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
        if (spec.kind === "reviewer") {
          this.rc += 1;
          // Round 1 (S3) + round 2 (first S6) raise a changing fix_now finding;
          // the 3rd reviewer pass (second S6) approves. Distinct findings each
          // round so the no-progress guard sees real progress.
          const findings: Finding[] =
            this.rc <= 2
              ? [
                  {
                    severity: "high",
                    category: "correctness",
                    claim_quote: `round-${this.rc}`,
                    location: `f.ts:${this.rc}`,
                    suggested_fix: "fix it",
                    action: "fix_now",
                  },
                ]
              : [];
          return { kind: "completed", output: { kind: "reviewer", findings } };
        }
        return {
          kind: "completed",
          output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
        };
      }
    }
    const backend = new TwoRoundBackend();
    const result = await runOrchestrator({ issueNumber: 337, backend });
    expect(result.status).toBe("success");
    // Two fix rounds, each an independent runner-dispatched S5→S6, then ship.
    expect(backend.dispatched).toEqual([
      "S2:coder:/tdd",
      "S3:reviewer:/review",
      "S5:coder:/tdd",
      "S6:reviewer:/review",
      "S5:coder:/tdd",
      "S6:reviewer:/review",
      "S7:ship:gstack-ship",
    ]);
  });
});

// ─── (C) review-decomposition wording aligned (#334 deferred P2) ─────────────

describe("#337 review-decomposition wording: per-slice /review, integrated = ak-cross-m-review", () => {
  const reviewerSoul = readFileSync(join(soulsDir, "reviewer.md"), "utf8");
  const claudeMd = readFileSync(join(repoRoot, "CLAUDE.md"), "utf8");
  // The reviewer-bullet of the repo-root CLAUDE.md ## Skill routing — the line
  // that previously said the per-slice reviewer runs "two passes, both".
  const skillRouting = claudeMd.slice(claudeMd.indexOf("## Skill routing"));

  it("the reviewer soul does NOT say the per-slice reviewer runs two passes both", () => {
    // The stale human two-pass-per-slice wording: per-slice runs ONLY /review;
    // ak-cross-m-review is the SEPARATE integrated (cross-family) worker.
    expect(reviewerSoul).not.toMatch(/two review passes, both run/i);
    expect(reviewerSoul).not.toMatch(/two passes, both/i);
  });

  it("the reviewer soul routes the per-slice reviewer to /review", () => {
    expect(reviewerSoul).toMatch(/\/review/);
  });

  it("the reviewer soul names ak-cross-m-review as the INTEGRATED / cross-family review, not a per-slice second pass", () => {
    // It may still mention ak-cross-m-review, but as the integrated/cross-family
    // gate (a separate worker) — NOT as a second per-slice pass run by this
    // reviewer worker.
    expect(reviewerSoul).toMatch(/integrated|cross-family|跨片|family/i);
  });

  it("the repo-root CLAUDE.md ## Skill routing does NOT tell the per-slice reviewer to run two passes both", () => {
    expect(skillRouting).not.toMatch(/two passes, both/i);
  });

  it("the CLAUDE.md ## Skill routing per-slice reviewer routes to /review (integrated cmr is separate)", () => {
    expect(skillRouting).toMatch(/\/review/);
    // The integrated cmr is named as the separate cross-family gate.
    expect(skillRouting).toMatch(/ak-cross-m-review/);
  });
});
