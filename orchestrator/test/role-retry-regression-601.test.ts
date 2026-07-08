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
import { MAX_DISPATCH_ATTEMPTS, withMechanicalRetry } from "../src/dispatchRetry.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import { runOrchestrator } from "../src/runner.js";
import { dispatchFamilyWorker } from "../src/family/dispatchFamilyWorker.js";
import { runVerifyCmr } from "../src/family/verifyCmr.js";
import type {
  Backend,
  CmrResult,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  OnlineReviewLandingSnapshot,
  StepOutput,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../src/family/types.js";

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
  async pollOnlineReviewState(input: {
    repo: string;
    prUrl: string;
    pollCount: number;
  }): Promise<OnlineReviewLandingSnapshot> {
    void input;
    return {
      prUrl: "pr://slice/offline-601",
      headOid: "deadbeef",
      totalFindingCount: 0,
      quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 0 },
        sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 },
        gemini: { state: "complete", findingCount: 0 },
      },
      droppedBots: [],
      threads: [],
      checkRuns: [],
    };
  }
  abstract dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult>;
}

/**
 * Shared success tail for a single-slice backend: every role not under test
 * returns a clean `completed` so the runner reaches the step under test. Extracted
 * so the structural-malformed / judged-failed / branch-mismatch / reviewer
 * fixtures share one tail, not a copy each.
 */
function cleanSuccessTail(spec: WorkerSpec): WorkerResult {
  const reviewLoop = skeletonReviewLoopWorkerResult(spec.kind);
  if (reviewLoop !== undefined) {
    return reviewLoop;
  }
  if (spec.kind === "reviewer") {
    return { kind: "completed", output: { kind: "reviewer", findings: [] } };
  }
  return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
}

/**
 * A family CMR closure worker spec (the completeness pass). Extracted so the
 * AC#3 seam-level tests and the dogfood-70 replay share one literal, not 3-4
 * copies of the same 13-field object.
 */
function cmrClosureSpec(): WorkerSpec {
  return {
    id: "cmr-completeness",
    kind: "cmr",
    role: "cmr",
    host: "claude",
    session: "fresh",
    contextRetention: "retain",
    skill: "ak-cross-m-review",
    promptFile: "prompts/cmr_completeness.md",
    completionSignal: "<cmr>",
    maxIter: 1,
    model: "opus",
    soul: "cmr",
    toolchain: [],
  };
}

/**
 * A family ship worker spec (the post-converged-cmr family PR step). Extracted
 * so the family-405 seam-level replay shares one literal.
 */
function familyShipSpec(): WorkerSpec {
  return {
    id: "family-ship",
    kind: "ship",
    role: "ship",
    host: "claude",
    session: "fresh",
    contextRetention: "retain",
    skill: "gstack-ship",
    promptFile: "prompts/family_ship.md",
    completionSignal: "SHIP_STEP_COMPLETE",
    maxIter: 5,
    model: "opus",
    soul: "coder",
    toolchain: [],
  };
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
 * A backend whose S7 ship dispatch returns a STRUCTURAL `malformed` (the worker
 * emitted no parseable `<ship>` tag — the dogfood-362 / family-405 incident
 * class) `structuralMalformed` times, then a clean `shipped`. Counts dispatches
 * so the test proves a retry happened through the shared path.
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
    return cleanSuccessTail(spec);
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
      // Guard is `>= 1` (not `> 1`): super increments the counter on the 1st
      // (malformed) dispatch, so on the 2nd dispatch the count is already 1.
      // The counter is incremented INSIDE this branch too — an early return
      // without incrementing would leave the count at 1 and flip the
      // `dispatches === 2` assertion (cmr R2 finding 1 CAUTION).
      prOpenedReturned = false;
      constructor() {
        super(1);
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "ship" && this.shipDispatches >= 1) {
          this.shipDispatches += 1;
          this.prOpenedReturned = true;
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ROLE_WORKTREE.branch,
              status: "pr_opened",
              pr: "pr://slice/offline-601",
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
    // The pr_opened branch must actually fire — the prior `> 1` guard was dead
    // code (super increments the counter), so the run converged via super's
    // `pushed` return, silently re-testing the sibling fixture's case.
    expect(backend.prOpenedReturned).toBe(true);
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
        return cleanSuccessTail(spec);
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
        return cleanSuccessTail(spec);
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
    return cleanSuccessTail(spec);
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

// ───────────────────── AC #3: a CMR closure whose downstream required-field re-validation fails ─────────────────────

/**
 * Minimal FamilyBackend whose `dispatchWorker` scripts a CMR closure worker:
 * returns a process-level `malformed` outcome for the first `malformed` dispatches
 * (the downstream re-validation failure from a guard/runner version-skew), then a
 * `completed` CMR closure with VALID accepted-suppression dispositions. Used ONLY
 * for seam-level coverage tests — the production family gate owns resolved
 * `malformed` via `callerOwns` and first-occurrence-aborts (deferred to #661).
 */
class CmrClosureVersionSkewFamilyBackend implements FamilyBackend {
  cmrDispatches = 0;
  constructor(private readonly malformed: number) {}
  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async appendFamilyLedger(): Promise<void> {}
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return [];
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      this.cmrDispatches += 1;
      if (this.cmrDispatches <= this.malformed) {
        return {
          kind: "malformed",
          reason:
            "cmr closure downstream re-validation failed: accepted_suppressed " +
            "disposition missing required field source/scope/boundedReopen " +
            "(guard/runner version-skew — dogfood-70 replay)",
        };
      }
      const cmrOutput: CmrResult = {
        kind: "cmr",
        converged: true,
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review-summary.json"],
      };
      return { kind: "completed", output: cmrOutput };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

/**
 * Minimal FamilyBackend whose ship dispatch returns a structural `malformed` (no
 * parseable `<ship>` verdict) `malformed` times, then `completed` shipped. Used
 * ONLY for the family-405 seam-level coverage test.
 */
class FamilyShipMalformedThenConvergeBackend implements FamilyBackend {
  shipDispatches = 0;
  constructor(private readonly malformed: number) {}
  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async appendFamilyLedger(): Promise<void> {}
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return [];
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "ship") {
      this.shipDispatches += 1;
      if (this.shipDispatches <= this.malformed) {
        return {
          kind: "malformed",
          reason: "family ship worker emitted no <ship> tag (family-405 replay)",
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: "family/405-replay",
          status: "pr_opened",
          pr: "https://example.com/pr/405",
        },
      };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

/**
 * FamilyBackend for the family-405 CURRENT-PRODUCTION pin: dispatches scripted
 * outputs sequentially (completeness CMR, correctness CMR, then the ship
 * malformed), runs the REAL family gate (runVerifyCmr), and records the abort.
 * Mirrors DogfoodCmrFamilyBackend from dogfoodReplay.ts (not exported).
 */
class FamilyShipMalformedAfterCmrBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: string[] = [];
  private attempt = 0;
  private familyHeadCursor: string;

  constructor(
    currentHead: string,
    private readonly outputs: ReadonlyArray<WorkerResult>,
  ) {
    this.familyHeadCursor = currentHead;
  }

  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.familyHeadCursor;
  }
  async runFamilyVerify(): Promise<{ ok: true }> {
    return { ok: true };
  }
  async escalateFamily(): Promise<void> {}
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push(`${spec.kind}:${ctx.cmrPass ?? ctx.familyBase ?? "unknown"}`);
    const scripted = this.outputs[this.attempt];
    this.attempt += 1;
    if (scripted !== undefined) {
      if (
        spec.kind === "coder" &&
        scripted.kind === "completed" &&
        scripted.output.kind === "coder"
      ) {
        this.familyHeadCursor = `${this.familyHeadCursor}+fix${this.attempt}`;
      }
      return scripted;
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

//
//
// #598 AC#5: "A dispatch that resolved into a shape which then fails the runner's
// own downstream required-field re-validation (e.g. source/scope/boundedReopen on
// a CMR closure) is treated as a process-level malformed outcome and retried."
//
// The CMR closure worker is a FAMILY worker (no single-slice CMR step). The
// grounding fixture is a guard/runner VERSION-SKEW (the issue's framing): the
// worker's own guard validated a looser field-set than the runner's current
// schema expects, so the worker signalled completion but the downstream
// re-validation of `source`/`scope`/`boundedReopen` failed. Matched guard/runner
// versions cannot disagree on an identical field set; the version-skew is what
// makes the first-occurrence abort wrong (a re-dispatch with a matched schema
// converges).
//
// HONESTY NOTE (review R1 finding 1): the production family seam
// (`dispatchOrAbort` in verifyCmr.ts) owns ALL resolved results via
// `callerOwns: (o) => "result" in o || (writeCapable && o.kind === "thrown")` —
// so a resolved `malformed` is DEFERRED to the gate, NOT retried by the generic
// layer. The gate's write-worker reset idempotency (which would let it retry
// safely) is deferred to #661. This section is therefore split into TWO tests:
//   1. REAL-VALIDATION PIN — exercises the runner's ACTUAL downstream
//      source/scope/boundedReopen re-validation (cmrClosureFailureReason →
//      trustedAcceptedSuppressionDisposition → hasAcceptedSuppressionAuthority)
//      through runVerifyCmr, and asserts the CURRENT production behavior: the
//      closure failure DURABLE-ABORTS as contract_drift (NOT retried), pointing
//      to #661 as the deferred retry-wiring. This keeps the gap visible.
//   2. SEAM-LEVEL COVERAGE — proves the shared withMechanicalRetry MECHANISM
//      covers the CMR closure role at the family seam (the same path every other
//      role uses). This is labeled as seam-level, NOT a claim that production
//      retries today.

/**
 * Minimal FamilyBackend for the REAL-VALIDATION pin: dispatches a `completed` CMR
 * closure whose `priorFindingDispositions` carries an `accepted_suppressed`
 * disposition MISSING `source`/`scope`/`boundedReopen` (the guard/runner
 * version-skew — the worker's guard passed a looser field-set than the runner's
 * schema expects). The runner's downstream `cmrClosureFailureReason` validation
 * catches it. Mirrors ScriptedCmrBackend in verify-cmr-closure-wellformed-604-r4.
 */
class CmrClosureMissingFieldsFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  cmrDispatches = 0;
  constructor(private readonly cmrOutput: CmrResult) {}

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return "family-head";
  }
  async runFamilyVerify(): Promise<{ ok: true }> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      this.cmrDispatches += 1;
      return { kind: "completed", output: this.cmrOutput };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

/** A converged CMR closure carrying an accepted_suppressed disposition with NO source/scope/boundedReopen. */
function cmrClosureWithMissingSuppressionFields(): CmrResult {
  return {
    kind: "cmr",
    converged: true,
    successfulLegs: ["opus", "gpt-5.5", "agy"],
    claimedFixedFindingIdentityKeys: [],
    priorFindingDispositions: [
      {
        identityKey: "correctness|src/closure.ts:1|accepted-suppressed-missing-fields",
        status: "accepted_suppressed",
        reason: "suppressed (guard/runner version-skew: fields missing)",
        // source / scope / boundedReopen deliberately ABSENT — the version-skew the
        // runner's downstream re-validation (hasAcceptedSuppressionAuthority) catches.
      },
    ],
    evidencePaths: ["cmr/review-summary.json"],
  };
}

describe("#601 AC#3 — a CMR closure whose downstream required-field re-validation fails", () => {
  it("REAL-VALIDATION PIN: a converged CMR closure missing source/scope/boundedReopen fails the runner's ACTUAL downstream re-validation and currently DURABLE-ABORTS as contract_drift (#661 wires the retry)", async () => {
    // Exercises the REAL downstream re-validation path: cmrClosureFailureReason →
    // trustedAcceptedSuppressionDisposition → hasAcceptedSuppressionAuthority. The
    // worker signalled completion (converged:true) and the <cmr> tag parsed fine
    // (the guard passed a looser field-set), but the runner's re-validation of the
    // accepted_suppressed disposition catches the missing source/scope/boundedReopen
    // → closure failure → contract_drift durable abort. This is the CURRENT
    // production behavior; the retry that #601 AC#3 mandates is deferred to #661
    // (the family gate's write-worker reset idempotency). This test pins the gap so
    // it stays visible until #661 lands.
    const backend = new CmrClosureMissingFieldsFamilyBackend(
      cmrClosureWithMissingSuppressionFields(),
    );
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/601-closure",
      familyBackend: backend,
    });
    // CURRENT behavior: the closure re-validation failure DURABLE-ABORTS (not
    // retried) — the gate owns the resolved `completed` via callerOwns and surfaces
    // the closure failure as contract_drift.
    expect(result.ok).toBe(false);
    expect(backend.cmrDispatches).toBe(1);
    const abort = backend.ledger.find((e) => e.status === "aborted");
    expect(abort?.stopSummary?.reason).toBe("contract_drift");
    expect(abort?.reason).toMatch(/source\/scope\/boundedReopen/);
  });

  it("SEAM-LEVEL COVERAGE: the shared withMechanicalRetry MECHANISM covers the CMR closure role at the family seam (the retry #661 will wire into the production gate)", async () => {
    // SEAM-LEVEL (not a production claim): this wraps `withMechanicalRetry` around
    // `dispatchFamilyWorker` directly, with the DEFAULT callerOwns (no ownership),
    // proving the shared MECHANISM retries a process-level `malformed` CMR dispatch
    // and converges. The production gate does NOT wire it this way yet — it owns
    // resolved `malformed` via callerOwns (deferred to #661). This test asserts the
    // mechanism coverage #601 owns; #661 owns wiring it into the gate.
    const backend = new CmrClosureVersionSkewFamilyBackend(1);
    const result = await withMechanicalRetry(
      cmrClosureSpec(),
      { familyBase: "family/601-closure" },
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("completed");
    expect(backend.cmrDispatches).toBe(2);
  });

  it("SEAM-LEVEL: a PERSISTENT downstream re-validation failure exhausts the shared bound and durably aborts (no infinite retry)", async () => {
    // The other direction: a version-skew that NEVER converges is retried only up
    // to MAX_DISPATCH_ATTEMPTS, then durably aborts — the SAME shared bound as
    // coder/ship, no per-role tuning. (Seam-level: the production gate would
    // first-occurrence-abort today; #661 wires the retry.)
    const backend = new CmrClosureVersionSkewFamilyBackend(Number.MAX_SAFE_INTEGER);
    const result = await withMechanicalRetry(
      cmrClosureSpec(),
      { familyBase: "family/601-closure" },
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("malformed");
    expect(backend.cmrDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

// ───────────────────── AC #4: dogfoodReplay-pattern regression tests ─────────────────────
//
// #601: "Replay tests reproduce the real ledger incidents this issue is grounded
// in: dogfood-362 and family-405 (ship worker returned no valid result) and
// dogfood-70 (completeness worker returned no valid result)."
//
// HONESTY SPLIT (review R1 finding 1): the three incidents cross the
// production/seam boundary differently, so each replay is labeled honestly:
//   - dogfood-362 — SINGLE-SLICE ship. The production runner DOES retry a
//     structural `malformed` via `withMechanicalRetry` (AC#2 wired it). This
//     replay is a real end-to-end production assertion (retry-then-converge).
//   - family-405 — FAMILY ship. The production family gate currently
//     first-occurrence-aborts a ship `malformed` as `contract_drift` (the gate
//     owns resolved results via callerOwns; write-worker reset idempotency is
//     deferred to #661). This replay PINS that current behavior + asserts the
//     seam-level mechanism coverage #601 owns.
//   - dogfood-70 — FAMILY CMR closure. Same as family-405: the production gate
//     first-occurrence-aborts a closure re-validation failure as `contract_drift`
//     (AC#3 real-validation pin above). This replay cross-references that pin +
//     asserts seam-level mechanism coverage.

describe("#601 AC#4 — dogfoodReplay-pattern regression: dogfood-362, family-405, dogfood-70", () => {
  it("dogfood-362 (PRODUCTION): a single-slice ship worker emitting no valid <ship> verdict retries through the shared path and reaches shipped (not first-occurrence abort)", async () => {
    // The real dogfood-362 incident: a ship worker returned no valid result
    // (crash/malformed) and durably aborted the whole run. #601 proves the shared
    // retry path now covers it in PRODUCTION: S7 re-dispatches via
    // `withMechanicalRetry` (AC#2 wired the narrowed callerOwns) and the run
    // converges to a delivery as if no malformed output occurred.
    const backend = new ShipStructuralMalformedThenConvergeBackend(1);
    const result = await runOrchestrator({ issueNumber: 362, backend });
    expect(result.status).not.toBe("error");
    expect(backend.shipDispatches).toBe(2);
  });

  it("family-405 (CURRENT PRODUCTION PIN): a family ship worker emitting no valid <ship> verdict DURABLE-ABORTS as contract_drift today (#661 wires the retry)", async () => {
    // The real family-405 incident: a family ship worker returned no valid result
    // after a converged CMR and the gate classified it as `contract_drift`
    // (first-occurrence abort). This replay PINS the current production behavior
    // through the REAL family gate (runVerifyCmr): a ship `malformed` is owned by
    // `callerOwns` and first-occurrence-aborts, NOT retried. The retry that #601
    // AC#4 mandates is deferred to #661 (write-worker reset idempotency). This
    // keeps the gap visible.
    const convergedCmr: WorkerResult = {
      kind: "completed",
      output: {
        kind: "cmr",
        converged: true,
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review-summary.json"],
      },
    };
    const backend = new FamilyShipMalformedAfterCmrBackend("family-head", [
      convergedCmr,
      convergedCmr,
      { kind: "malformed", reason: "ship worker emitted no valid result (family-405 replay)" },
    ]);
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/405-replay",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    // PIN the dispatch count: without this the test can't detect what it
    // claims to pin — a future retrying family gate would still pass because
    // exhausted scripted outputs fall back to a completed-coder result that
    // verifyCmr.ts still classifies as no-valid-result (→ contract_drift, see
    // verifyCmr.ts:2351). Symmetric with the dogfood-70 pin's
    // `cmrDispatches === 1`.
    expect(backend.dispatches.filter((d) => d.startsWith("ship:"))).toHaveLength(1);
    const abort = backend.ledger.find((e) => e.status === "aborted");
    expect(abort?.stopSummary?.reason).toBe("contract_drift");
  });

  it("family-405 (SEAM-LEVEL COVERAGE): the shared withMechanicalRetry MECHANISM covers the family ship role at the family seam (#661 wires it into the gate)", async () => {
    // SEAM-LEVEL (not a production claim): the shared MECHANISM retries a family
    // ship `malformed` and converges to `pr_opened`. The production gate does NOT
    // wire it this way yet (see the CURRENT PRODUCTION PIN above). This asserts
    // the mechanism coverage #601 owns; #661 owns wiring it into the gate.
    const backend = new FamilyShipMalformedThenConvergeBackend(1);
    const result = await withMechanicalRetry(
      familyShipSpec(),
      { familyBase: "family/405-replay" },
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("completed");
    expect(backend.shipDispatches).toBe(2);
  });

  it("dogfood-70 (CURRENT PRODUCTION PIN): a completeness worker whose closure is missing source/scope/boundedReopen DURABLE-ABORTS as contract_drift today (#661 wires the retry)", async () => {
    // The real dogfood-70 incident: a completeness (CMR closure) worker returned
    // no valid result and durably aborted. This replay PINS the current production
    // behavior through the REAL family gate: the closure's downstream
    // re-validation of source/scope/boundedReopen fails → contract_drift abort
    // (NOT retried). The retry that #601 AC#4 mandates is deferred to #661. This
    // is the same real-validation path as the AC#3 pin (cross-referenced here as
    // the dogfood-70 incident grounding).
    const backend = new CmrClosureMissingFieldsFamilyBackend(
      cmrClosureWithMissingSuppressionFields(),
    );
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/70-replay",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(backend.cmrDispatches).toBe(1);
    const abort = backend.ledger.find((e) => e.status === "aborted");
    expect(abort?.stopSummary?.reason).toBe("contract_drift");
    expect(abort?.reason).toMatch(/source\/scope\/boundedReopen/);
  });

  it("dogfood-70 (SEAM-LEVEL COVERAGE): the shared withMechanicalRetry MECHANISM covers the CMR closure role at the family seam (#661 wires it into the gate)", async () => {
    // SEAM-LEVEL (not a production claim): the shared MECHANISM retries a CMR
    // closure `malformed` and converges. The production gate does NOT wire it this
    // way yet (see the CURRENT PRODUCTION PIN above). Same coverage as the AC#3
    // seam-level test, cross-referenced here as the dogfood-70 incident grounding.
    const backend = new CmrClosureVersionSkewFamilyBackend(1);
    const result = await withMechanicalRetry(
      cmrClosureSpec(),
      { familyBase: "family/70-replay" },
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("completed");
    expect(backend.cmrDispatches).toBe(2);
  });
});
