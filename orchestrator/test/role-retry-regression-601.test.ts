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
import { runOrchestrator } from "../src/runner.js";
import { dispatchFamilyWorker } from "../src/family/dispatchFamilyWorker.js";
import type {
  Backend,
  CmrResult,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import type { FamilyBackend } from "../src/family/types.js";

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

// ───────────────────── AC #3: a CMR closure whose downstream required-field re-validation fails retries via the shared path ─────────────────────
//
// #598 AC#5: "A dispatch that resolved into a shape which then fails the runner's
// own downstream required-field re-validation (e.g. source/scope/boundedReopen on
// a CMR closure) is treated as a process-level malformed outcome and retried."
//
// The CMR closure worker is a FAMILY worker (no single-slice CMR step), so this
// asserts at the shared family seam: `withMechanicalRetry` wrapping
// `dispatchFamilyWorker`. The fixture grounds the failure as a guard/runner
// VERSION-SKEW (the issue's framing): the worker's own guard validated a looser
// field-set than the runner's current schema expects, so the worker signalled
// completion but the downstream re-validation of `source`/`scope`/`boundedReopen`
// failed — surfacing as a process-level `malformed` outcome that the SAME shared
// `withMechanicalRetry` path retries. Matched guard/runner versions cannot
// disagree on an identical field set; the version-skew is what makes the
// first-occurrence abort wrong (a re-dispatch with a matched schema converges).
//
// CMR is family-only, and the family gate composes the generic layer with the
// CMR's own rewrite loop (`OUTCOME_REWRITE_RETRY_CAP`) via `callerOwns` — the
// generic layer fires for a process-level failure nobody else owns. This test
// asserts the shared MECHANISM covers the CMR closure role at its seam (the same
// `withMechanicalRetry` every other role uses), not the gate's composition.

/**
 * Minimal FamilyBackend whose `dispatchWorker` (the unified family seam) scripts a
 * CMR closure worker: returns a process-level `malformed` `malformed` times (the
 * downstream re-validation failure from a guard/runner version-skew), then a
 * `completed` CMR closure with VALID accepted-suppression dispositions (the
 * re-dispatch with a matched schema converges). Counts dispatches.
 */
class CmrClosureVersionSkewFamilyBackend implements FamilyBackend {
  cmrDispatches = 0;
  constructor(private readonly malformed: number) {}
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      this.cmrDispatches += 1;
      if (this.cmrDispatches <= this.malformed) {
        // The worker signalled completion but the runner's downstream re-validation
        // of source/scope/boundedReopen failed (guard/runner version-skew): the
        // shape resolved but a required field was missing → a process-level
        // malformed outcome the shared retry path re-dispatches.
        return {
          kind: "malformed",
          reason:
            "cmr closure downstream re-validation failed: accepted_suppressed " +
            "disposition missing required field source/scope/boundedReopen " +
            "(guard/runner version-skew — dogfood-70 replay)",
        };
      }
      // The re-dispatch (fresh session) converges with a matched schema: the
      // closure carries valid accepted-suppression dispositions.
      const cmrOutput: CmrResult = {
        kind: "cmr",
        converged: true,
        successfulLegs: ["claude", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
      };
      return { kind: "completed", output: cmrOutput };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#601 AC#3 — a CMR closure whose downstream required-field re-validation fails retries via the shared path", () => {
  it("a completeness (CMR closure) worker whose downstream re-validation fails retries through withMechanicalRetry and records the closure on success", async () => {
    // The shared `withMechanicalRetry` is the SAME path #598 wraps around
    // `dispatchWorker` (coder/ship) and `dispatchFamilyWorker` (family cmr). This
    // test wraps it around `dispatchFamilyWorker` directly — asserting the CMR
    // closure role is covered by the ONE shared mechanism, not a separate impl.
    const backend = new CmrClosureVersionSkewFamilyBackend(1);
    const cmrSpec: WorkerSpec = {
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
    const ctx: DispatchContext = { familyBase: "family/601-closure" };
    const result = await withMechanicalRetry(
      cmrSpec,
      ctx,
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    // The first-occurrence downstream re-validation failure no longer durably
    // aborts — the shared path re-dispatches and the closure records normally.
    expect(result.kind).toBe("completed");
    expect(backend.cmrDispatches).toBe(2);
  });

  it("a PERSISTENT downstream re-validation failure exhausts the shared bound and durably aborts (no infinite retry)", async () => {
    // The other direction: a version-skew that NEVER converges is retried only up
    // to MAX_DISPATCH_ATTEMPTS, then durably aborts — the SAME shared bound as
    // coder/ship, no per-role tuning.
    const backend = new CmrClosureVersionSkewFamilyBackend(Number.MAX_SAFE_INTEGER);
    const cmrSpec: WorkerSpec = {
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
    const ctx: DispatchContext = { familyBase: "family/601-closure" };
    const result = await withMechanicalRetry(
      cmrSpec,
      ctx,
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("malformed");
    expect(backend.cmrDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

// ───────────────────── AC #4: dogfoodReplay-pattern regression tests (retry-then-converge, not first-occurrence abort) ─────────────────────
//
// #601: "Replay tests reproduce the real ledger incidents this issue is grounded
// in: dogfood-362 and family-405 (ship worker returned no valid result) and
// dogfood-70 (completeness worker returned no valid result)." Each replay proves
// the incident class now retry-then-converges through the shared path instead of
// durably aborting on first occurrence.
//
// The grounding incidents:
//   - dogfood-362 — a single-slice ship worker emitted no valid `<ship>` verdict
//     (a structural process-level failure). Replay: the runner re-dispatches S7
//     via `withMechanicalRetry` and converges to `shipped` (AC#2 end-to-end).
//   - family-405 — a FAMILY ship worker emitted no valid `<ship>` verdict after a
//     converged CMR. The family gate currently classifies this as `contract_drift`
//     (first-occurrence abort). The shared MECHANISM (`withMechanicalRetry` around
//     `dispatchFamilyWorker`) covers the family ship role at its seam — this replay
//     asserts that coverage (the family gate's write-worker reset idempotency,
//     which would let the production path retry safely, is deferred to #661).
//   - dogfood-70 — a completeness (CMR closure) worker returned no valid result.
//     Replay: the shared `withMechanicalRetry` path re-dispatches and the closure
//     records normally (AC#3 end-to-end at the seam).

/**
 * A family backend whose ship dispatch returns a structural `malformed` (no
 * parseable `<ship>` verdict) `malformed` times, then `completed` shipped. Used
 * for the family-405 replay at the shared-seam level.
 */
class FamilyShipMalformedThenConvergeBackend implements FamilyBackend {
  shipDispatches = 0;
  constructor(private readonly malformed: number) {}
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

describe("#601 AC#4 — dogfoodReplay-pattern regression: dogfood-362, family-405, dogfood-70 retry-then-converge", () => {
  it("dogfood-362: a single-slice ship worker emitting no valid <ship> verdict retries through the shared path and reaches shipped (not first-occurrence abort)", async () => {
    // The real dogfood-362 incident: a ship worker returned no valid result
    // (crash/malformed) and durably aborted the whole run. #601 proves the shared
    // retry path now covers it: S7 re-dispatches via `withMechanicalRetry` and the
    // run converges to a delivery as if no malformed output occurred.
    const backend = new ShipStructuralMalformedThenConvergeBackend(1);
    const result = await runOrchestrator({ issueNumber: 362, backend });
    expect(result.status).not.toBe("error");
    expect(backend.shipDispatches).toBe(2);
  });

  it("family-405: a family ship worker emitting no valid <ship> verdict is covered by the shared withMechanicalRetry path at the family seam (converges to pr_opened)", async () => {
    // The real family-405 incident: a family ship worker returned no valid result
    // after a converged CMR and the gate classified it as `contract_drift`
    // (first-occurrence abort). #601 proves the shared MECHANISM covers the family
    // ship role: `withMechanicalRetry` around `dispatchFamilyWorker` re-dispatches
    // and converges to `pr_opened`. (The production gate's write-worker reset
    // idempotency — which would let `dispatchOrAbort` retry safely — is deferred to
    // #661; this replay asserts the seam-level coverage #601 owns.)
    const backend = new FamilyShipMalformedThenConvergeBackend(1);
    const shipSpec: WorkerSpec = {
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
    const ctx: DispatchContext = { familyBase: "family/405-replay" };
    const result = await withMechanicalRetry(
      shipSpec,
      ctx,
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("completed");
    expect(backend.shipDispatches).toBe(2);
  });

  it("dogfood-70: a completeness (CMR closure) worker returning no valid result retries through the shared path and records the closure (not first-occurrence abort)", async () => {
    // The real dogfood-70 incident: a completeness worker returned no valid result
    // and durably aborted. #601 proves the shared retry path now covers the CMR
    // closure role: `withMechanicalRetry` around `dispatchFamilyWorker` re-dispatches
    // and the closure records normally on the second attempt.
    const backend = new CmrClosureVersionSkewFamilyBackend(1);
    const cmrSpec: WorkerSpec = {
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
    const ctx: DispatchContext = { familyBase: "family/70-replay" };
    const result = await withMechanicalRetry(
      cmrSpec,
      ctx,
      (s, c) => dispatchFamilyWorker(backend, s, c),
    );
    expect(result.kind).toBe("completed");
    expect(backend.cmrDispatches).toBe(2);
  });
});
