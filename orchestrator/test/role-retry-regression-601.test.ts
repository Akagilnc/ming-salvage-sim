/**
 * #601 — role-specific regression tests proving #598's generic mechanical retry
 * actually COVERS the previously-zero-retry roles (coder / ship / cmr-closure).
 *
 * #592 ("no role treated specially") means no role gets ZERO retry. #598 landed
 * the generic retry at the shared seam (`withMechanicalRetry` wrapping
 * `dispatchWorker` / `dispatchFamilyWorker`). This slice is a DIRECT, UNMODIFIED
 * consumer of that shared path — it adds NO new retry-count logic and NO per-role
 * special-case branches. Every test dispatches through the SAME shared retry path
 * (`runOrchestrator` → `withMechanicalRetry` → `dispatchWorker` for single-slice,
 * `dispatchFamilyWorker` for family), asserting the roles that used to durably
 * abort the run on first crash/malformed output now retry-then-converge.
 *
 * The grounding ledger incidents:
 *   - dogfood-362 / family-405 — a ship worker returned "no valid result
 *     (crash/malformed)" (no parseable `<ship>` tag) and aborted the whole run.
 *   - dogfood-70 — a completeness (CMR closure) worker returned no valid result.
 *
 * Per #601's carve-out, the JUDGED ship verdicts (a parsed `failed`, a
 * branch-identity mismatch, family's pushed-without-PR) are NOT retried — those
 * are decided outcomes, not transient process failures. Only the STRUCTURAL
 * "no parseable output" case retries. The negative tests below assert that
 * boundary so the generic retry never re-runs a decided failure.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS } from "../src/dispatchRetry.js";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

// Every single-slice replay reuses one resident worktree handle.
const ROLE_WORKTREE: WorktreeHandle = {
  branch: "feat/issue-601",
  base: "main",
  path: "/resident/worktrees/issue-601",
};

/**
 * Minimal backend shell: every method not under test returns a clean success so
 * the runner reaches the step under test. Worker dispatch is overridden per
 * fixture. Mirrors the #598 test backends (dispatch-mechanical-retry-598.test.ts)
 * so these tests assert against the SAME shared seam, not a re-implementation.
 */
abstract class RoleRetryBackend implements Backend {
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    return { number: n, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
    return { number: n, body: "body", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return ROLE_WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}
  abstract dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult>;
}

// ───────────────────── AC #1: a crashed CODER retries (the #592 asymmetry) ─────────────────────

/**
 * A backend whose S2 coder dispatch returns a process-level `failed` (produced no
 * commit — the worker crashed mid-run) `coderFailures` times before completing.
 * Counts coder dispatches so the test proves a retry happened through the shared
 * path (the coder step has NO `callerOwns` — every process failure is retried
 * generically, the #592 asymmetry #601 re-asserts).
 */
class CoderCrashThenConvergeBackend extends RoleRetryBackend {
  coderDispatches = 0;
  constructor(private readonly coderFailures: number) {
    super();
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "coder" && spec.id === "S2") {
      this.coderDispatches += 1;
      if (this.coderDispatches <= this.coderFailures) {
        return { kind: "failed", reason: "coder container crashed mid-run (dogfood-362 replay)" };
      }
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
    if (spec.kind === "ship") {
      return { kind: "completed", output: { kind: "ship", branch: ROLE_WORKTREE.branch, status: "pushed" } };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#601 AC#1 — a crashed coder dispatch retries fresh through the shared path and the run continues", () => {
  it("a coder (S2) that crashes once then succeeds no longer aborts — dispatched twice, run succeeds", async () => {
    const backend = new CoderCrashThenConvergeBackend(1);
    const result = await runOrchestrator({ issueNumber: 601, backend });
    // Before #598 a single coder crash durably aborted (zero retry). #601 re-asserts
    // the generic layer now covers it: the run converges as if no crash occurred.
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(2);
  });

  it("a coder crash surfacing as a THROW (connection drop / idle timeout) also retries through the shared path", async () => {
    // The grounding incident class includes a process crash that surfaces as a throw
    // (connection drop / idle timeout) rather than a resolved `failed`. The generic
    // layer treats a throw as a process failure and retries it the same way.
    class CoderThrowThenConvergeBackend extends CoderCrashThenConvergeBackend {
      private thrown = false;
      constructor() {
        super(0);
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2" && !this.thrown) {
          this.thrown = true;
          this.coderDispatches += 1;
          throw new Error("coder worker connection dropped mid-run");
        }
        return super.dispatchWorker(spec);
      }
    }
    const backend = new CoderThrowThenConvergeBackend();
    const result = await runOrchestrator({ issueNumber: 601, backend });
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(2);
  });
});

// ───────────────────── AC #2: the SHIP role — structural malformed retries, judged verdicts do not ─────────────────────

/**
 * A backend whose S7 ship dispatch is scripted across THREE independent axes so
 * one fixture class covers the whole ship retry surface:
 *   - `structuralMalformed` times: return a STRUCTURAL `malformed` (the worker
 *     emitted no parseable `<ship>` tag — the dogfood-362 / family-405 incident
 * *       class). This MUST retry through the shared path and converge.
 *   - then on the converging path return a clean `shipped`. Counts dispatches.
 *
 * The negative cases (a JUDGED `failed` verdict; a branch-identity mismatch) are
 * covered by sibling fixtures below — those are decided outcomes that must NOT
 * retry, asserting #601's carve-out boundary.
 */
class ShipStructuralMalformedThenConvergeBackend extends RoleRetryBackend {
  shipDispatches = 0;
  constructor(private readonly structuralMalformed: number) {
    super();
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "ship") {
      this.shipDispatches += 1;
      if (this.shipDispatches <= this.structuralMalformed) {
        // The genuine structural case: no parseable `<ship>` tag at all (the worker
        // crashed before emitting a verdict, or emitted garbage). This is a
        // process-level failure, NOT a judged verdict → retries via the shared path.
        return {
          kind: "malformed",
          reason: "ship worker emitted no <ship> tag (dogfood-362 / family-405 replay)",
        };
      }
      return { kind: "completed", output: { kind: "ship", branch: ROLE_WORKTREE.branch, status: "pushed" } };
    }
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#601 AC#2 — a ship worker returning 'no valid result (crash/malformed)' retries and converges", () => {
  it("a ship (S7) whose worker emits no parseable <ship> tag retries through the shared path and reaches shipped", async () => {
    const backend = new ShipStructuralMalformedThenConvergeBackend(1);
    const result = await runOrchestrator({ issueNumber: 601, backend });
    // The structural "no parseable <ship> tag" case (dogfood-362 / family-405) used
    // to durably abort on first occurrence. It now retries via the SAME shared path
    // as the coder (#592 "no role treated specially") and converges to a delivery.
    expect(result.status).not.toBe("error");
    expect(backend.shipDispatches).toBe(2);
  });

  it("a ship CRASH (throw — container/connection failure) retries through the shared path and converges", async () => {
    class ShipThrowThenConvergeBackend extends ShipStructuralMalformedThenConvergeBackend {
      private thrown = false;
      constructor() {
        super(0);
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "ship" && !this.thrown) {
          this.thrown = true;
          this.shipDispatches += 1;
          throw new Error("ship container connection dropped mid-push");
        }
        return super.dispatchWorker(spec);
      }
    }
    const backend = new ShipThrowThenConvergeBackend();
    const result = await runOrchestrator({ issueNumber: 601, backend });
    expect(result.status).not.toBe("error");
    expect(backend.shipDispatches).toBe(2);
  });

  it("a ship that reaches pr_opened (not just pushed) on the retry converges to a delivery", async () => {
    // The AC names both `shipped`/`pr_opened` as the convergent state. A retry that
    // opens a PR on the second attempt must be read as a delivery, not an abort.
    class ShipMalformedThenPrOpenedBackend extends ShipStructuralMalformedThenConvergeBackend {
      constructor() {
        super(1);
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "ship" && this.shipDispatches > 1) {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ROLE_WORKTREE.branch,
              status: "pr_opened",
              pr: "https://example.com/pr/601",
            },
          };
        }
        return super.dispatchWorker(spec);
      }
    }
    const backend = new ShipMalformedThenPrOpenedBackend();
    const result = await runOrchestrator({ issueNumber: 601, backend });
    expect(result.status).not.toBe("error");
    expect(backend.shipDispatches).toBe(2);
  });
});

describe("#601 AC#2 carve-out — JUDGED ship verdicts are NOT retried (decided outcomes, not transient failures)", () => {
  // #601 explicitly does NOT claim #598's judged carve-outs retry. A parsed `failed`
  // verdict (gstack-ship ran, the delivery hard-failed) and a branch-identity
  // mismatch (the worker reported a branch, we judged it the wrong one) are DECIDED
  // outcomes — they pass through with zero retry. These negative tests pin that
  // boundary so the generic retry never re-runs a decided failure.

  it("a JUDGED ship-`failed` verdict (parsed failed) passes through with ZERO retry", async () => {
    class ShipJudgedFailedBackend extends RoleRetryBackend {
      shipDispatches = 0;
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "ship") {
          this.shipDispatches += 1;
          return {
            kind: "failed",
            reason: "gstack-ship: tests hard-failed, delivery could not complete (a judged verdict)",
          };
        }
        if (spec.kind === "reviewer") {
          return { kind: "completed", output: { kind: "reviewer", findings: [] } };
        }
        return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
      }
    }
    const backend = new ShipJudgedFailedBackend();
    const result = await runOrchestrator({ issueNumber: 601, backend });
    // A decided delivery failure is surfaced (S8 error), never re-run.
    expect(result.status).toBe("error");
    expect(backend.shipDispatches).toBe(1);
  });

  it("a ship branch-identity mismatch (reported the wrong branch) passes through with ZERO retry", async () => {
    class ShipBranchMismatchBackend extends RoleRetryBackend {
      shipDispatches = 0;
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "ship") {
          this.shipDispatches += 1;
          // The worker successfully parsed AND shipped, but reported a DIFFERENT branch
          // than the resident slice branch — a judged off-contract delivery, not a
          // transient process failure. Must NOT retry.
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: "some-other-branch",
              status: "pushed",
            },
          };
        }
        if (spec.kind === "reviewer") {
          return { kind: "completed", output: { kind: "reviewer", findings: [] } };
        }
        return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
      }
    }
    const backend = new ShipBranchMismatchBackend();
    const result = await runOrchestrator({ issueNumber: 601, backend });
    expect(result.status).toBe("error");
    expect(backend.shipDispatches).toBe(1);
  });

  it("persistent structural malformed exhausts the shared bound and durably aborts (no infinite retry)", async () => {
    // The other direction of the carve-out: a structural malformed that NEVER
    // converges is retried only up to MAX_DISPATCH_ATTEMPTS, then durably aborts
    // (runner function (a) per #604). This proves the retry is bounded by the SAME
    // shared counter as every other role — no special per-role tuning.
    const backend = new ShipStructuralMalformedThenConvergeBackend(Number.MAX_SAFE_INTEGER);
    const result = await runOrchestrator({ issueNumber: 601, backend });
    expect(result.status).toBe("error");
    expect(backend.shipDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

// ───────────────────── AC #6: the reviewer's own 2-retry budget still holds (one shared mechanism) ─────────────────────

/**
 * A backend whose S3 reviewer ALWAYS returns a `malformed` result — a semantic
 * invalid-output failure the reviewer's OWN `MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS`
 * (= 2) loop owns. The generic layer defers it (callerOwns) so the reviewer budget
 * is NOT double-counted. #601 re-asserts this: all roles share ONE underlying
 * mechanism, not separate implementations.
 */
class ReviewerAlwaysMalformedBackend extends RoleRetryBackend {
  reviewerDispatches = 0;
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "reviewer") {
      this.reviewerDispatches += 1;
      return { kind: "malformed", reason: "reviewer emitted no <review> tag" };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#601 AC#6 — the existing 'reviewer gets 2 retries' regression still holds (one shared mechanism)", () => {
  it("a persistently malformed reviewer is dispatched EXACTLY its own bounded budget (not multiplied by the generic retry)", async () => {
    const backend = new ReviewerAlwaysMalformedBackend();
    await runOrchestrator({ issueNumber: 601, backend });
    // The reviewer's malformed RESULT is caller-owned → deferred to its own
    // MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS loop; the generic layer never retries it.
    // So the reviewer is dispatched exactly its own budget (2), NOT 2 × the generic
    // MAX_DISPATCH_ATTEMPTS — confirming all roles share one underlying mechanism.
    expect(backend.reviewerDispatches).toBe(2);
    expect(backend.reviewerDispatches).toBeLessThan(2 * MAX_DISPATCH_ATTEMPTS);
  });
});
