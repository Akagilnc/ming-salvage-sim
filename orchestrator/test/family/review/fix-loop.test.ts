/**
 * Family integrated-cmr pass dispatch (ADR 0030).
 *
 * `verifyCmr.ts` dispatches ordered cmr pass workers (completeness before
 * correctness), reads each worker's TERMINAL pass verdict, records abort/escalate
 * outcomes, and ships only after both passes converge and satisfy leg/floor/closure
 * accounting. The tests here pin that seam without starting real containers.
 *
 * Driven entirely by a zero-container injected-seam fake (no real codex / container).
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findingIdentityKey } from "../../../src/findings.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import { readTelemetryRecords } from "../../../src/telemetry.js";
import {
  runVerifyCmr,
} from "../../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  Finding,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

describe("review-round persistence immunity", () => {
  class ReviewRoundStampBackend implements FamilyBackend {
    readonly telemetryDir = mkdtempSync(join(tmpdir(), "verify-cmr-review-round-"));
    readonly ledger: FamilyLedgerEntry[] = [];
    currentFamilyHead = "review-head";

    constructor(
      private readonly failure: "helper-record" | "terminal-record" | "none",
    ) {}

    async mergeChildIntoFamilyBase(): Promise<never> {
      throw new Error("not used");
    }

    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }

    async readFamilyHead(): Promise<string> {
      return this.currentFamilyHead;
    }

    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }

    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
      if (spec.kind !== "cmr") throw new Error(`unexpected worker kind ${spec.kind}`);
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: this.failure === "terminal-record",
          findingsCount: 0,
          reason: "stop after one review round",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
        },
      };
    }

    resolveTelemetryDir(): string {
      return this.telemetryDir;
    }

    async readFamilyCurrentHead(): Promise<string> {
      if (this.failure === "helper-record") {
        throw new Error("injected current HEAD read failure");
      }
      return this.currentFamilyHead;
    }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      if (
        this.failure === "helper-record" ||
        (this.failure === "terminal-record" && entry.status === "cmr_passed")
      ) {
        throw new Error("injected durable record failure");
      }
      this.ledger.push(entry);
    }
  }

  const reviewRoundRows = (backend: ReviewRoundStampBackend) =>
    readTelemetryRecords(backend.telemetryDir).filter(
      (record) => record.phase === "review_round",
    );

  it("stamps unknown when an intermediate git-state helper rejects while recording its abort", async () => {
    const backend = new ReviewRoundStampBackend("helper-record");

    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/review-round-helper-reject",
        familyBackend: backend,
      }),
    ).rejects.toThrow("injected durable record failure");

    expect(reviewRoundRows(backend)).toEqual([
      expect.objectContaining({ cmrPass: "completeness", finalDisposition: "unknown" }),
    ]);
  });

  it("stamps unknown when the terminal durable record rejects", async () => {
    const backend = new ReviewRoundStampBackend("terminal-record");

    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/review-round-record-reject",
        familyBackend: backend,
      }),
    ).rejects.toThrow("injected durable record failure");

    expect(reviewRoundRows(backend)).toEqual([
      expect.objectContaining({ cmrPass: "completeness", finalDisposition: "unknown" }),
    ]);
  });
});

/** #600/#603: successful pr_opened ship → verify → docRelease → post-merge cleanup. */
const ONLINE_REVIEW_DISPATCH_TAIL = [
  expect.objectContaining({ kind: "verify", promptFile: "verify.md" }),
  expect.objectContaining({ kind: "docRelease", promptFile: "docRelease.md" }),
] as const;

/** Deterministic skeleton for verify/fixer/cleanup/docRelease after ship (#600). */
function onlineReviewLoopWorkerOrThrow(spec: WorkerSpec): WorkerResult {
  const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
  if (skeleton !== undefined) {
    return skeleton;
  }
  throw new Error(`unexpected worker kind ${spec.kind}`);
}

/** One recorded worker dispatch (the kind + the session mode). */
interface DispatchRecord {
  readonly kind: WorkerSpec["kind"];
  readonly session: WorkerSpec["session"];
  readonly cmrPass?: DispatchContext["cmrPass"];
  readonly priorCmrFindingIdentityKeys?: readonly string[];
  readonly role?: WorkerSpec["role"];
  readonly promptFile?: string;
  readonly contextRetention?: WorkerSpec["contextRetention"];
  readonly blockingFindingIdentityKeys?: readonly string[];
  readonly repairAttemptFailures?: DispatchContext["repairAttemptFailures"];
}

/**
 * A scriptable family backend exercising pass-worker dispatch via the unified
 * `dispatchWorker` seam. Every dispatch is recorded so tests can assert the runner
 * schedules cmr pass workers, never a family coder-fix worker, and only ships on
 * converged/accounted pass verdicts.
 */
class SchedulerFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  private shipRound = 0;
  currentFamilyHead = "head-1";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: () => WorkerResult;
      ship?: (round: number) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return this.script.verify?.(req) ?? { ok: true };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }

  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
    });
    if (spec.kind === "cmr") {
      return (
        this.script.cmr?.() ?? {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: true,
            findingsCount: 0,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            ...CMR_EVIDENCE,
          },
        }
      );
    }
    if (spec.kind === "ship") {
      const round = this.shipRound++;
      return (
        this.script.ship?.(round) ?? {
          kind: "completed",
          output: {
            kind: "ship",
            branch: ctx.familyBase!,
            status: "pr_opened",
            pr: `pr://${ctx.familyBase}`,
            prHead: this.currentFamilyHead,
          },
        }
      );
    }
    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

const BLOCKING_FAMILY_CMR_FINDING: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "family CMR review/fix loop is hidden inside the reviewer worker",
  location: "orchestrator/src/family/verifyCmr.ts:cmr-review-fix-loop",
  suggested_fix:
    "return the finding to the runner, dispatch coder-fix, then re-review the full family diff",
  action: "fix_now",
};
const BLOCKING_FAMILY_CMR_KEY = findingIdentityKey(BLOCKING_FAMILY_CMR_FINDING);

const SECOND_BLOCKING_FAMILY_CMR_FINDING: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote:
    "fresh family CMR re-review found another same-module runner-owned blocker",
  location: "orchestrator/src/family/verifyCmr.ts:cmr-repeat-fix-loop",
  suggested_fix:
    "route the new blocker through a new runner-visible coder-fix round",
  action: "fix_now",
};
const SECOND_BLOCKING_FAMILY_CMR_KEY = findingIdentityKey(
  SECOND_BLOCKING_FAMILY_CMR_FINDING,
);

/**
 * #604 correctness r4 (D5): the "runner counts, does not read the reviewer's
 * self-judgment" invariant, expressed with a normal blocking finding
 * (`action:"fix_now"`, medium) whose CONTENT self-labels the blocker as
 * owning-issue-still-red (in claim_quote/suggested_fix) must STILL route through
 * coder-fix — the runner never reads that content to spare it.
 */
const OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote:
    "reviewer believes this blocker's owning issue #498 is still red, but says so in content only",
  location: "orchestrator/src/family/verifyCmr.ts:owning-issue-still-red-valid",
  suggested_fix:
    "the runner must route this through coder-fix regardless of the owning-issue claim",
  action: "fix_now",
};
const OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY = findingIdentityKey(
  OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER,
);

const EXCESSIVE_CMR_FIX_FINDINGS: readonly Finding[] = Array.from(
  { length: 4 },
  (_, index) => ({
    severity: "medium",
    category: "correctness",
    claim_quote: `family CMR fix loop still has blocker ${index + 1}`,
    location: `orchestrator/src/family/verifyCmr.ts:cmr-fix-budget-${index + 1}`,
    suggested_fix: "bound repeated family CMR coder-fix restarts",
    action: "fix_now",
  }),
);
const EXCESSIVE_CMR_FIX_KEYS = EXCESSIVE_CMR_FIX_FINDINGS.map((finding) =>
  findingIdentityKey(finding),
);

// #597 drift guard: the removed round cap wrote a "coder-fix round budget
// exhausted" abort. After the cap is gone, no ledger entry may carry that
// wording — the loop's only steady-state exits are convergence or a
// worker-raised human-decision-gate signal, never a runner-side budget. Both
// no-cap convergence tests assert this, so the wording lives in one place.
const BUDGET_EXHAUSTED_ABORT_REASON = "coder-fix round budget exhausted";
function expectNoBudgetExhaustedAbort(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): void {
  expect(
    ledger.some(
      (entry) =>
        entry.status === "aborted" &&
        typeof entry.reason === "string" &&
        entry.reason.includes(BUDGET_EXHAUSTED_ABORT_REASON),
    ),
  ).toBe(false);
}

class ReviewFixRereviewBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly verifyRequests: FamilyVerifyRequest[] = [];
  readonly escalations: FamilyEscalation[] = [];
  currentFamilyHead = "head-before-cmr-review";
  private completenessReviewRound = 0;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyRequests.push(req);
    return { ok: true };
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness" && this.completenessReviewRound++ === 0) {
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: false,
            findingsCount: 1,
            reason: "blocking family CMR finding requires coder-fix",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            claimedFixedFindingIdentityKeys: [],
            priorFindingDispositions: [],
            ...CMR_EVIDENCE,
            findings: [BLOCKING_FAMILY_CMR_FINDING],
          },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys:
            ctx.cmrPass === "completeness" ? [BLOCKING_FAMILY_CMR_KEY] : [],
          priorFindingDispositions:
            ctx.cmrPass === "completeness"
              ? [
                  {
                    identityKey: BLOCKING_FAMILY_CMR_KEY,
                    status: "verified-closed",
                    reason: "fresh full-diff CMR re-review verified the coder-fix",
                  },
                ]
              : [],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.currentFamilyHead = "head-after-coder-fix";
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

class CountChannelFixBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  readonly escalations: FamilyEscalation[] = [];
  currentFamilyHead = "head-before-count-channel-fix";
  private completenessRound = 0;

  constructor(
    private readonly firstCmrResult: WorkerResult,
    private readonly coderResult?: WorkerResult,
  ) {}

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async escalateFamily(escalation: FamilyEscalation): Promise<void> {
    this.escalations.push(escalation);
  }
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      cmrPass: ctx.cmrPass,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });
    this.landings.push(landing);
    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness" && this.completenessRound++ === 0) {
        return this.firstCmrResult;
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }
    if (spec.kind === "coder") {
      this.currentFamilyHead = "head-after-count-channel-fix";
      return this.coderResult ?? {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }
    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

/**
 * First completeness review returns ONE blocking finding the reviewer
 * content-labels as owning-issue-still-red; the coder-fix closes it and the
 * re-review converges. Exercises the #604 slice 2 rule that a reviewer's
 * self-judgment must NOT terminate the family — the finding still flows through
 * coder-fix by identity key.
 */
class OwningIssueStillRedThenGoodBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly verifyRequests: FamilyVerifyRequest[] = [];
  currentFamilyHead = "head-before-owning-issue-review";
  private completenessReviewRound = 0;
  // #604 r4 (D5): parameterize the blocking finding so the review/fix flow can
  // be driven with the validator-passing blocker.
  constructor(
    private readonly blockingFinding: Finding = OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER,
    private readonly blockingKey: string = OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY,
  ) {}

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyRequests.push(req);
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness" && this.completenessReviewRound++ === 0) {
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: false,
            findingsCount: 1,
            reason:
              "reviewer content-labels the blocker as owning-issue-still-red",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            claimedFixedFindingIdentityKeys: [],
            priorFindingDispositions: [],
            ...CMR_EVIDENCE,
            findings: [this.blockingFinding],
          },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys:
            ctx.cmrPass === "completeness" ? [this.blockingKey] : [],
          priorFindingDispositions:
            ctx.cmrPass === "completeness"
              ? [
                  {
                    identityKey: this.blockingKey,
                    status: "verified-closed",
                    reason: "coder-fix closed the self-deferred blocker",
                  },
                ]
              : [],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.currentFamilyHead = "head-after-owning-issue-coder-fix";
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

class CorrectnessReviewFixRestartsBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly verifyRequests: FamilyVerifyRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  currentFamilyHead = "head-before-correctness-review";
  private correctnessReviewRound = 0;
  private verifyRound = 0;

  constructor(
    private readonly verifyResults: readonly FamilyVerifyResult[] = [],
  ) {}

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyRequests.push(req);
    return this.verifyResults[this.verifyRound++] ?? { ok: true };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "correctness" && this.correctnessReviewRound++ === 0) {
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: false,
            findingsCount: 1,
            reason: "correctness pass found a fixable family CMR finding",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            claimedFixedFindingIdentityKeys: [],
            priorFindingDispositions: [],
            ...CMR_EVIDENCE,
            findings: [BLOCKING_FAMILY_CMR_FINDING],
          },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys:
            ctx.cmrPass === "correctness" ? [BLOCKING_FAMILY_CMR_KEY] : [],
          priorFindingDispositions:
            ctx.cmrPass === "correctness"
              ? [
                  {
                    identityKey: BLOCKING_FAMILY_CMR_KEY,
                    status: "verified-closed",
                    reason:
                      "fresh full-barrier CMR correctness re-review verified the coder-fix",
                  },
                ]
              : [],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.currentFamilyHead = "head-after-correctness-coder-fix";
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

class RepeatedReviewFixRereviewBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  currentFamilyHead = "head-before-repeat-cmr-review";
  private completenessReviewRound = 0;
  private coderFixRound = 0;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const reviewRound = this.completenessReviewRound++;
        if (reviewRound === 0) {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              findingsCount: 1,
              reason: "first blocking family CMR finding requires coder-fix",
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: [],
              priorFindingDispositions: [],
              ...CMR_EVIDENCE,
              findings: [BLOCKING_FAMILY_CMR_FINDING],
            },
          };
        }
        if (reviewRound === 1) {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              findingsCount: 1,
              reason:
                "fresh full-diff re-review found a new same-module blocker",
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
              priorFindingDispositions: [
                {
                  identityKey: BLOCKING_FAMILY_CMR_KEY,
                  status: "verified-closed",
                  reason: "first coder-fix closed the first blocker",
                },
              ],
              ...CMR_EVIDENCE,
              findings: [SECOND_BLOCKING_FAMILY_CMR_FINDING],
            },
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: true,
            findingsCount: 0,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            claimedFixedFindingIdentityKeys: [
              BLOCKING_FAMILY_CMR_KEY,
              SECOND_BLOCKING_FAMILY_CMR_KEY,
            ],
            priorFindingDispositions: [
              {
                identityKey: BLOCKING_FAMILY_CMR_KEY,
                status: "verified-closed",
                reason: "first blocker stayed closed",
              },
              {
                identityKey: SECOND_BLOCKING_FAMILY_CMR_KEY,
                status: "verified-closed",
                reason: "second coder-fix closed the second blocker",
              },
            ],
            ...CMR_EVIDENCE,
          },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.coderFixRound += 1;
      this.currentFamilyHead = `head-after-coder-fix-${this.coderFixRound}`;
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

class ExcessiveReviewFixRestartsBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  currentFamilyHead = "head-before-excessive-cmr-review";
  private completenessReviewRound = 0;
  private coderFixRound = 0;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const reviewRound = this.completenessReviewRound++;
        if (reviewRound < EXCESSIVE_CMR_FIX_FINDINGS.length) {
          const closedPriorKeys = EXCESSIVE_CMR_FIX_KEYS.slice(0, reviewRound);
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              findingsCount: 1,
              reason: `fresh full-diff re-review found blocker ${reviewRound + 1}`,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: closedPriorKeys,
              priorFindingDispositions: closedPriorKeys.map((identityKey) => ({
                identityKey,
                status: "verified-closed",
                reason: "prior coder-fix stayed closed",
              })),
              ...CMR_EVIDENCE,
              findings: [EXCESSIVE_CMR_FIX_FINDINGS[reviewRound]!],
            },
          };
        }
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          // #597: the converged response is pass-aware — completeness closes its
          // OWN accumulated keys; correctness starts with an empty protected prior
          // set and must claim NO keys fixed (a correctness reviewer that claimed
          // completeness's keys would trip the closure_context_missing guard, which
          // is a contract guard, not a round cap — and previously unreachable
          // because MAX_CMR_CODER_FIX_ROUNDS aborted before correctness ran).
          claimedFixedFindingIdentityKeys:
            ctx.cmrPass === "completeness" ? EXCESSIVE_CMR_FIX_KEYS : [],
          priorFindingDispositions:
            ctx.cmrPass === "completeness"
              ? EXCESSIVE_CMR_FIX_KEYS.map((identityKey) => ({
                  identityKey,
                  status: "verified-closed",
                  reason: "all repeated coder-fixes closed",
                }))
              : [],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.coderFixRound += 1;
      this.currentFamilyHead = `head-after-excessive-coder-fix-${this.coderFixRound}`;
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

/**
 * #597 dogfood #272 replay: ~9 consecutive blocking coder-fix rounds before the
 * fresh reviewer finally converges. Proves the family integrated-CMR loop has no
 * fixed round cap — it keeps dispatching coder-fix + fresh re-review while a
 * blocking finding remains, and converges inside a SINGLE `runVerifyCmr` call
 * (no manual relaunch). The previous `MAX_CMR_CODER_FIX_ROUNDS=3` cap would have
 * aborted this run after round 3.
 */
const DOGFOOD_272_BLOCKING_ROUNDS = 9;
const DOGFOOD_272_FINDINGS: readonly Finding[] = Array.from(
  { length: DOGFOOD_272_BLOCKING_ROUNDS },
  (_, index) => ({
    severity: "medium",
    category: "correctness",
    claim_quote: `dogfood #272 round ${index + 1} still reports a blocker`,
    location: `orchestrator/src/family/verifyCmr.ts:dogfood-272-round-${index + 1}`,
    suggested_fix: "keep dispatching coder-fix until the fresh reviewer converges",
    action: "fix_now",
  }),
);
const DOGFOOD_272_KEYS = DOGFOOD_272_FINDINGS.map((finding) =>
  findingIdentityKey(finding),
);

class Dogfood272ReviewFixRereviewBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  currentFamilyHead = "head-before-dogfood-272";
  private completenessReviewRound = 0;
  private coderFixRound = 0;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const reviewRound = this.completenessReviewRound++;
        if (reviewRound < DOGFOOD_272_BLOCKING_ROUNDS) {
          const closedPriorKeys = DOGFOOD_272_KEYS.slice(0, reviewRound);
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              findingsCount: 1,
              reason: `dogfood #272 fresh re-review still has blocker round ${reviewRound + 1}`,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: closedPriorKeys,
              priorFindingDispositions: closedPriorKeys.map((identityKey) => ({
                identityKey,
                status: "verified-closed",
                reason: "prior coder-fix stayed closed",
              })),
              ...CMR_EVIDENCE,
              findings: [DOGFOOD_272_FINDINGS[reviewRound]!],
            },
          };
        }
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys:
            ctx.cmrPass === "completeness" ? DOGFOOD_272_KEYS : [],
          priorFindingDispositions:
            ctx.cmrPass === "completeness"
              ? DOGFOOD_272_KEYS.map((identityKey) => ({
                  identityKey,
                  status: "verified-closed",
                  reason: "dogfood #272 all prior coder-fixes closed",
                }))
              : [],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.coderFixRound += 1;
      this.currentFamilyHead = `head-after-dogfood-272-fix-${this.coderFixRound}`;
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

// #597 R2 (Codex P1): worker-raised non-convergence escalate is the bounded stop
// once the runner-side round cap is gone. This backend drives 2 blocking
// coder-fix rounds, then — instead of a 3rd fix_now — the fresh reviewer
// ESCALATES (it judged the loop will not converge, per the cmr soul's
// non-convergence escalation rule). The run must stop bounded: escalateFamily,
// ok:false, exactly 2 coder-fix dispatches (NOT unbounded), no ship.
const ESCALATE_NONCONV_FINDINGS: readonly Finding[] = Array.from(
  { length: 2 },
  (_, index) => ({
    severity: "medium",
    category: "correctness",
    claim_quote: `non-converging family CMR blocker round ${index + 1}`,
    location: `orchestrator/src/family/verifyCmr.ts:cmr-nonconv-${index + 1}`,
    suggested_fix: "coder-fix keeps committing but the blocker will not converge",
    action: "fix_now",
  }),
);
const ESCALATE_NONCONV_KEYS = ESCALATE_NONCONV_FINDINGS.map((finding) =>
  findingIdentityKey(finding),
);

class EscalateOnNonConvergenceBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly escalations: FamilyEscalation[] = [];
  currentFamilyHead = "head-before-nonconv-escalate";
  private completenessReviewRound = 0;
  private coderFixRound = 0;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const reviewRound = this.completenessReviewRound++;
        if (reviewRound < ESCALATE_NONCONV_FINDINGS.length) {
          const closedPriorKeys = ESCALATE_NONCONV_KEYS.slice(0, reviewRound);
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: false,
              findingsCount: 1,
              reason: `non-converging blocker round ${reviewRound + 1}`,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: closedPriorKeys,
              priorFindingDispositions: closedPriorKeys.map((identityKey) => ({
                identityKey,
                status: "verified-closed",
                reason: "prior coder-fix committed",
              })),
              ...CMR_EVIDENCE,
              findings: [ESCALATE_NONCONV_FINDINGS[reviewRound]!],
            },
          };
        }
        // The fresh reviewer has now seen the loop fail to converge across the
        // prior fix rounds and raises the escalation verdict instead of a 3rd
        // fix_now (cmr soul non-convergence rule). No runner-side round cap did
        // this — the worker's own judgment is the stop.
        return {
          kind: "escalated",
          escalation: {
            reason: "family CMR fix loop is not converging on the same blocker",
            diagnosis:
              "two committed coder-fix rounds and the blocker still recurs; further rounds will not converge — needs a human decision",
          },
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      this.coderFixRound += 1;
      this.currentFamilyHead = `head-after-nonconv-fix-${this.coderFixRound}`;
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    if (spec.kind === "ship") {
      throw new Error("ship must never be dispatched on a non-converging escalate");
    }

    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

class ReviewerMutatesHeadBeforeFindingBackend extends ReviewFixRereviewBackend {
  protected readonly mutatedHead = "head-mutated-by-cmr-reviewer";

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    const result = await super.dispatchWorker(spec, ctx);
    if (spec.kind === "cmr" && ctx.cmrPass === "completeness") {
      this.currentFamilyHead = this.mutatedHead;
    }
    return result;
  }
}

class ReviewerLeavesTrackedDirtyBeforeFindingBackend extends ReviewFixRereviewBackend {
  private reviewerLeftTrackedChanges = false;

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    const result = await super.dispatchWorker(spec, ctx);
    if (spec.kind === "cmr" && ctx.cmrPass === "completeness") {
      this.reviewerLeftTrackedChanges = true;
    }
    return result;
  }

  async readFamilyTrackedStatus(): Promise<readonly string[]> {
    return this.reviewerLeftTrackedChanges ? ["M tracked.txt"] : [];
  }
}

class ReviewerTrackedStatusReadFailsBackend extends ReviewFixRereviewBackend {
  async readFamilyTrackedStatus(): Promise<readonly string[]> {
    throw new Error("git status failed");
  }
}

class MissingRepairEvidenceThenGoodBackend extends ReviewFixRereviewBackend {
  private coderFixRound = 0;

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind !== "coder") return super.dispatchWorker(spec, ctx);
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
      repairAttemptFailures: ctx.repairAttemptFailures,
    });

    if (this.coderFixRound++ === 0) {
      this.currentFamilyHead = "head-after-bad-coder-fix";
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
      },
    };
  }
}

class UnknownFamilyBaselineThenGoodBackend extends ReviewFixRereviewBackend {
  override async readFamilyHead(): Promise<string> {
    throw new Error("git rev-parse HEAD unavailable");
  }
}

class KnownCoderGitMismatchThenGoodBackend extends ReviewFixRereviewBackend {
  private coderFixRound = 0;

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind !== "coder") return super.dispatchWorker(spec, ctx);
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });
    // The first completed fix is handed directly to fresh re-review even when
    // the worker reports no commit.
    if (this.coderFixRound++ === 0) {
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
        },
      };
    }
    this.currentFamilyHead = "head-after-coder-fix";
    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
      },
    };
  }
}

class MultipleEvidenceOnlyFailuresThenGoodBackend extends ReviewFixRereviewBackend {
  private coderFixRound = 0;
  telemetryRepoResolutions = 0;

  resolveFamilyWorkingRepo(): string {
    this.telemetryRepoResolutions += 1;
    return process.cwd();
  }

  resolveTelemetryDir(): string {
    return mkdtempSync(join(tmpdir(), "verify-cmr-telemetry-range-"));
  }

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind !== "coder") return super.dispatchWorker(spec, ctx);
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
      repairAttemptFailures: ctx.repairAttemptFailures,
    });

    this.coderFixRound += 1;
    if (this.coderFixRound === 1) {
      this.currentFamilyHead = "head-after-bad-coder-fix";
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
      },
    };
  }
}

class NoHeadMovementThenGoodBackend extends ReviewFixRereviewBackend {
  private coderFixRound = 0;

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind !== "coder") return super.dispatchWorker(spec, ctx);
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });

    if (this.coderFixRound++ === 0) {
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      };
    }

    this.currentFamilyHead = "head-after-coder-fix";
    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
      },
    };
  }
}

/** Coder always "succeeds" without moving family head — budget must stop thrash. */
class AlwaysHeadStuckCoderBackend extends ReviewFixRereviewBackend {
  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind !== "coder") return super.dispatchWorker(spec, ctx);
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });
    // Head stays at baseline; never advance.
    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
      },
    };
  }
}

class ReviewerChecksOutOtherHeadBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
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
  async readFamilyCurrentHead(): Promise<string> {
    return "detached-review-head";
  }
  async readFamilyTrackedStatus(): Promise<readonly string[]> {
    return [];
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      role: spec.role,
      promptFile: spec.promptFile,
      contextRetention: spec.contextRetention,
      cmrPass: ctx.cmrPass,
      priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
    });
    if (spec.kind === "cmr") {
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: "family-head",
        },
      };
    }
    return onlineReviewLoopWorkerOrThrow(spec);
  }
}

describe("family integrated-cmr gate = PURE SCHEDULER (runner-visible review/fix/re-review)", () => {
  it("blocking family CMR findings return to runner, dispatch coder-fix, then trigger a fresh full-diff re-review", async () => {
    const backend = new ReviewFixRereviewBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({
        kind: "cmr",
        role: "verify",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
      }),
      expect.objectContaining({
        kind: "coder",
        role: "coder",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder_fix.md",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        role: "verify",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        role: "verify",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "integrated_cmr_correctness.md",
        cmrPass: "correctness",
      }),
      expect.objectContaining({ kind: "ship", promptFile: "family_ship.md" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(backend.ledger).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          cmrPass: "completeness",
          familyHeadAfter: "head-before-cmr-review",
          // #604 slice 3 / ADR 0062: the review row carries the thin key envelope,
          // not the fat Finding blob.
          blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
        }),
        expect.objectContaining({
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          familyHeadBefore: "head-before-cmr-review",
          familyHeadAfter: "head-after-coder-fix",
          reason: expect.stringContaining(BLOCKING_FAMILY_CMR_KEY),
        }),
        expect.objectContaining({
          status: "cmr_passed",
          event: "cmr_passed",
          cmrPass: "completeness",
          familyHeadAfter: "head-after-coder-fix",
        }),
      ]),
    );
    expect(
      backend.ledger.find(
        (entry) =>
          entry.status === "aborted" &&
          entry.cmrPass === "completeness" &&
          entry.reason?.includes(BLOCKING_FAMILY_CMR_KEY),
      ),
    ).toBeUndefined();
    expect(backend.verifyRequests).toEqual([
      { phase: "final", familyBase: "family/550-base" },
      { phase: "final", familyBase: "family/550-base" },
    ]);
  });

  it("routes new fixable findings from fresh re-review back through another coder-fix round", async () => {
    const backend = new RepeatedReviewFixRereviewBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({
        kind: "coder",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "coder",
        blockingFindingIdentityKeys: [SECOND_BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [
          BLOCKING_FAMILY_CMR_KEY,
          SECOND_BLOCKING_FAMILY_CMR_KEY,
        ],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship", promptFile: "family_ship.md" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_reviewed"),
    ).toHaveLength(2);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_fix_committed"),
    ).toHaveLength(2);
  });

  it("keeps dispatching coder-fix + re-review across 4+ consecutive blocking rounds and eventually converges (#597: no round cap)", async () => {
    const backend = new ExcessiveReviewFixRestartsBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    // #597: the fixed `MAX_CMR_CODER_FIX_ROUNDS=3` cap is gone. While the fresh
    // reviewer keeps reporting a blocking finding, the runner keeps dispatching
    // coder-fix + fresh re-review. This script produces 4 consecutive blocking
    // rounds before converging — strictly more than the removed cap of 3, so a
    // leftover budget abort would have terminated at exactly 3 coder-fixes.
    expect(result).toEqual({ ok: true, ran: true });
    const coderDispatches = backend.dispatches.filter(
      (dispatch) => dispatch.kind === "coder",
    );
    expect(coderDispatches.length).toBeGreaterThan(3);
    expect(coderDispatches).toHaveLength(
      EXCESSIVE_CMR_FIX_FINDINGS.length,
    );
    // Each blocking round landed exactly one coder-fix commit ledger record.
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_fix_committed"),
    ).toHaveLength(EXCESSIVE_CMR_FIX_FINDINGS.length);
    // The removed cap wrote a budget-exhausted abort — that wording MUST be gone.
    expectNoBudgetExhaustedAbort(backend.ledger);
    // Convergence forwarded the run to the terminal ship worker.
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(true);
  });

  it("dogfood #272: ~9 blocking coder-fix rounds converge inside a single runVerifyCmr call (#597)", async () => {
    const backend = new Dogfood272ReviewFixRereviewBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/272-dogfood",
      familyBackend: backend,
    });

    // The run converges WITHOUT a manual relaunch — the removed cap would have
    // aborted after round 3 of 9. Single call, eventual convergence.
    expect(result).toEqual({ ok: true, ran: true });
    const coderDispatches = backend.dispatches.filter(
      (dispatch) => dispatch.kind === "coder",
    );
    expect(coderDispatches).toHaveLength(DOGFOOD_272_BLOCKING_ROUNDS);
    // Each blocking round landed one coder-fix commit ledger record (no round
    // was silently skipped or coalesced).
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_fix_committed"),
    ).toHaveLength(DOGFOOD_272_BLOCKING_ROUNDS);
    // The removed-budget abort wording MUST be gone.
    expectNoBudgetExhaustedAbort(backend.ledger);
    // Convergence forwarded the run to the terminal ship worker.
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(true);
  });

  it("mid-loop worker escalate on non-convergence stops the run BOUNDED — not an endless coder-fix loop (#597 R2 / Codex P1)", async () => {
    const backend = new EscalateOnNonConvergenceBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/nonconv-base",
      familyBackend: backend,
    });

    // Removing the round cap did NOT make a non-converging loop unbounded: the
    // fresh reviewer's own escalate is the stop. The run halts as escalated.
    // Decision park: omit failedStatus (spine → escalated, not stage death).
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("not converging");
    // Exactly the two committed fix rounds ran before the escalate — bounded,
    // not endless. (Pre-#597 the cap would have aborted at 3; here the WORKER
    // stops the loop on its own non-convergence judgment, no runner counter.)
    expect(
      backend.dispatches.filter((dispatch) => dispatch.kind === "coder"),
    ).toHaveLength(ESCALATE_NONCONV_FINDINGS.length);
    // Three completeness reviews: two blocking rounds + the escalate round.
    expect(
      backend.dispatches.filter(
        (dispatch) => dispatch.kind === "cmr" && dispatch.cmrPass === "completeness",
      ),
    ).toHaveLength(ESCALATE_NONCONV_FINDINGS.length + 1);
    // A non-converging escalate never reaches ship, and never falls back to a
    // budget-exhausted abort.
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(false);
    expectNoBudgetExhaustedAbort(backend.ledger);
  });

  it("continues at correctness when a correctness coder-fix commits", async () => {
    const backend = new CorrectnessReviewFixRestartsBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.verifyRequests).toEqual([
      { phase: "final", familyBase: "family/550-base" },
      { phase: "final", familyBase: "family/550-base" },
    ]);
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({
        kind: "coder",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "correctness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "ship", promptFile: "family_ship.md" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
  });

  it("aborts before correctness re-review when the post-fix full verify is red", async () => {
    const backend = new CorrectnessReviewFixRestartsBackend([
      { ok: true },
      { ok: false, errorPackage: { reason: "vitest red after correctness fix" } },
    ]);

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    expect(backend.verifyRequests).toEqual([
      { phase: "final", familyBase: "family/550-base" },
      { phase: "final", familyBase: "family/550-base" },
    ]);
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({
        kind: "coder",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
    ]);
    expect(backend.aborted).toEqual([
      expect.objectContaining({
        phase: "final",
        familyBase: "family/550-base",
        familyHeadAfter: "head-after-correctness-coder-fix",
        errorPackage: { reason: "vitest red after correctness fix" },
      }),
    ]);
  });

  it("lets fresh re-review judge a coder-fix when repair evidence is missing", async () => {
    const backend = new MissingRepairEvidenceThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({ kind: "coder" }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      cmrPass: "completeness",
      familyHeadBefore: "head-before-cmr-review",
      familyHeadAfter: "head-after-bad-coder-fix",
      blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
    }));
    expect(
      backend.dispatches.findIndex((dispatch, index) => {
        return (
          dispatch.kind === "cmr" &&
          dispatch.cmrPass === "completeness" &&
          index > 0
        );
      }),
    ).toBe(2);
  });

  it("lets fresh CMR judge the attempted fix when family HEAD is unavailable", async () => {
    const backend = new UnknownFamilyBaselineThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result.ran).toBe(true);
    expect(backend.dispatches.filter((dispatch) => dispatch.kind === "cmr").length).toBeGreaterThan(1);
    expect(backend.ledger.some(
      (entry) => entry.status === "aborted" && /repair evidence gate failed/.test(entry.reason ?? ""),
    )).toBe(false);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      reason: expect.stringMatching(/coder-fix completed; fresh reviewer will judge findings/),
    }));
  });

  it("sends a completed no-commit coder report to fresh re-review", async () => {
    const backend = new KnownCoderGitMismatchThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result.ran).toBe(true);
    expect(backend.dispatches.filter((dispatch) => dispatch.kind === "coder")).toHaveLength(1);
    expect(backend.dispatches.filter((dispatch) => dispatch.kind === "cmr").length).toBeGreaterThan(1);
    expect(backend.ledger.some(
      (entry) => entry.status === "aborted" && /repair evidence gate failed/.test(entry.reason ?? ""),
    )).toBe(false);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      reason: expect.stringMatching(/coder-fix completed; fresh reviewer will judge findings/),
    }));
  });

  it("does not retry coder-fix in the observation layer when repair evidence is incomplete", async () => {
    const backend = new MultipleEvidenceOnlyFailuresThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({ kind: "coder" }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      cmrPass: "completeness",
      familyHeadBefore: "head-before-cmr-review",
      familyHeadAfter: "head-after-bad-coder-fix",
      blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
    }));
    // One resolution schedules the coder-fix commit range and one belongs to
    // the independent terminal family auto-merge observation. Evidence-only
    // retries must not add further resolutions for the same coder-fix range.
    expect(backend.telemetryRepoResolutions).toBe(2);
  });

  it("head not moved → fixed topology still alternates to fresh re-review", async () => {
    const backend = new NoHeadMovementThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/878-head-not-moved",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    // HEAD does not authorize an extra fixer dispatch or a runner-authored park.
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({
        kind: "coder",
        promptFile: "coder_fix.md",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(1);
  });

  /**
   * #878 head-not-moved short-circuit (negative):
   * fix leg advanced family head → normal path: one coder-fix then re-review,
   * no second coder-fix redispatch from the head-stuck short-circuit.
   */
  it("#878 head moved → re-review after single coder-fix, no fix redispatch (negative)", async () => {
    const backend = new ReviewFixRereviewBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/878-head-moved",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({
        kind: "coder",
        promptFile: "coder_fix.md",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
      ...ONLINE_REVIEW_DISPATCH_TAIL,
    ]);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(1);
  });

  it("head-stuck coder does not let the runner author a decision gate", async () => {
    const backend = new AlwaysHeadStuckCoderBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/878-head-stuck-budget",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const coders = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coders).toHaveLength(1);
    const cmrAfterFirstCoder = backend.dispatches
      .slice(backend.dispatches.findIndex((d) => d.kind === "coder") + 1)
      .filter((d) => d.kind === "cmr");
    expect(cmrAfterFirstCoder.length).toBeGreaterThan(0);
    expect(backend.escalations).toEqual([]);
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" &&
          typeof e.reason === "string" &&
          /head-stuck/i.test(e.reason),
      ),
    ).toBe(false);
  });
it("#876 keeps the CMR loop alive when the reviewer moves family HEAD before findings", async () => {
    const backend = new ReviewerMutatesHeadBeforeFindingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    // Head movement is routing plumbing, not a capital crime: findings channel
    // still dispatches coder-fix and the barrier can converge.
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(
      expect.arrayContaining(["cmr", "coder", "cmr", "ship"]),
    );
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: "cmr:completeness",
      reason: expect.stringMatching(/reviewer moved family HEAD/i),
    }));
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /reviewer moved family HEAD/i.test(entry.reason ?? ""),
      ),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(true);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_passed"),
    ).toBe(true);
  });

  it("#853 keeps reviewer tracked changes in the normal diff/review flow", async () => {
    const backend = new ReviewerLeavesTrackedDirtyBeforeFindingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((dispatch) => dispatch.kind === "cmr").length)
      .toBeGreaterThan(1);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: "cmr:completeness",
      reason: expect.stringMatching(/reviewer left tracked changes/i),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "aborted" && /tracked changes/i.test(entry.reason ?? "")),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_passed"),
    ).toBe(true);
  });

  it("#876 keeps the CMR loop alive when the reviewer checks out a different clean HEAD", async () => {
    const backend = new ReviewerChecksOutOtherHeadBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: "cmr:completeness",
      reason: expect.stringMatching(/checked out.*different HEAD/i),
    }));
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /checked out.*different HEAD/i.test(entry.reason ?? ""),
      ),
    ).toBe(false);
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(true);
  });

  it("keeps tracked-status read failures out of reviewer fate", async () => {
    const backend = new ReviewerTrackedStatusReadFailsBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(
      expect.arrayContaining(["cmr", "coder", "ship"]),
    );
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /tracked status read failed/i.test(entry.reason ?? ""),
      ),
    ).toBe(false);
  });

  it("cmr workers CONVERGED ⇒ ok:true, completeness + correctness dispatches, NO coder-fix, then ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Exactly two CMR passes, no coder-fix on an already-green review, then ship.
    expect(backend.dispatches.filter((d) => d.kind === "cmr").map((d) => d.cmrPass)).toEqual([
      "completeness",
      "correctness",
    ]);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(0);
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("cmr worker ESCALATE (it judged it cannot converge) ⇒ escalateFamily, ok:false, NO ship, NO fix", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "escalated",
        escalation: {
          reason: "field-name mismatch: region.cannon vs region.cityCannon",
          diagnosis: "the fix loop hit drift across rounds — needs an architectural call",
        },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Decision park: omit failedStatus (spine → escalated, not stage death).
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("region.cannon");
    // The runner escalated WITHOUT ever dispatching a fix or a ship.
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });
it("#875: converged cmr with claimed-fixed keys but no dispositions still ships (coverage court demolished)", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|fake closure"],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      priorCmrFindingIdentityKeys: ["correctness|src/x.ts:1|fake closure"],
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("#861: converged cmr tolerates self-claimed keys when the runner supplied no closure context", async () => {
    // A fresh reviewer that honestly reports pre-resume findings as fixed (it can
    // see older review artifacts in the tree) must not kill the family: with no
    // runner-supplied prior set there is nothing to audit coverage against.
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: ["correctness|stale.ts:1|not supplied by runner"],
          priorFindingDispositions: [
            {
              identityKey: "correctness|stale.ts:1|not supplied by runner",
              status: "verified-closed",
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("#861: converged cmr ignores claimed-fixed keys outside the runner-supplied set when every supplied key is covered", async () => {
    // The 485 night-run abort: reviewer claimed the runner-supplied key AND a
    // genuinely-fixed pre-resume key. Extra honest claims are worker prose, not a
    // closure failure — the runner audits only the keys it supplied.
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [
            "correctness|src/x.ts:1|real closure",
            "correctness|stale.ts:1|not supplied by runner",
          ],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/x.ts:1|real closure",
              status: "verified-closed",
            },
            {
              identityKey: "correctness|stale.ts:1|not supplied by runner",
              status: "verified-closed",
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      priorCmrFindingIdentityKeys: ["correctness|src/x.ts:1|real closure"],
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("#875: converged cmr with still-active prose disposition still ships when findings=0 (disposition court demolished)", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/x.ts:1|still open",
              status: "still-active",
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("converged cmr with verified-closed dispositions may pass to ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|real closure"],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/x.ts:1|real closure",
              status: "verified-closed",
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      priorCmrFindingIdentityKeys: ["correctness|src/x.ts:1|real closure"],
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("positive reviewer count routes every structured finding without reading suppression content", async () => {
    const suppressed: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "accepted hub-loss gap",
      location: "orchestrator/src/family/verifyCmr.ts:1",
      suggested_fix: "accepted by issue scope",
      action: "wont_fix",
      disposition_reason: "accepted by issue scope",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #448 acceptance criteria",
        scope: "#448 family integrated CMR",
        reason: "accepted by issue scope",
        findingIdentity:
          "correctness|orchestrator/src/family/verifycmr.ts:1|accepted hub-loss gap",
        boundedReopen: "reopen on higher severity or different scope",
      },
    };
    // #604 slice 4 (ADR 0062): route kinds are gone; a blocking finding carries no
    // routing disposition. (Was `disposition:{kind:"spec_conflict",...}`.) The
    // blocking-vs-suppression selection invariant is unchanged — this plain
    // blocking finding is still selected over the earlier accepted suppression.
    const blocker: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "ADR conflicts with implementation",
      location: "orchestrator/src/family/verifyCmr.ts:2",
      suggested_fix: "resolve the accepted contract conflict",
      action: "fix_now",
    };
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          findingsCount: 2,
          reason: "has blocking findings",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
          findings: [suppressed, blocker],
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyIssue: 448,
      moduleContext: {
        currentModules: [
          {
            module: "family-cmr",
            moduleScope: ["orchestrator/src/family/verifyCmr.ts"],
            source: "family_issue",
            issue: 448,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [
          {
            source: "issue #448 acceptance criteria",
            scope: "#448 family integrated CMR",
            reason: "accepted by issue scope",
            findingIdentity:
              "correctness|orchestrator/src/family/verifycmr.ts:1|accepted hub-loss gap",
            boundedReopen: "reopen on higher severity or different scope",
          },
        ],
      },
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_reviewed",
      event: "cmr_reviewed",
      blockingFindingIdentityKeys: [
        findingIdentityKey(suppressed),
        findingIdentityKey(blocker),
      ],
      stopSummary: expect.objectContaining({
        reason: "cmr_failed",
      }),
    }));
    const reviewedRow = backend.ledger.find(
      (entry) => entry.status === "cmr_reviewed",
    );
    expect(reviewedRow?.stopSummary).not.toHaveProperty("finding");
    expect(reviewedRow?.stopSummary).not.toHaveProperty("findingDescriptor");
    const reviewed = backend.ledger.find((entry) => entry.status === "cmr_reviewed");
    expect(reviewed).not.toHaveProperty("cmrFindingClassification");
    expect(reviewed?.reason).toBe(
      "integrated cmr completeness judge continue with 2 live finding(s)",
    );
  });

  it("#875: untrusted accepted_suppressed disposition prose does not kill a converged pass", async () => {
    const priorKey = "correctness|src/x.ts:1|accepted without trusted source";
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [priorKey],
          priorFindingDispositions: [
            {
              identityKey: priorKey,
              status: "accepted_suppressed",
              source: "#999",
              scope: "untrusted reviewer-created suppression",
              reason: "reviewer says accepted",
              boundedReopen: "reopen on higher severity",
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      priorCmrFindingIdentityKeys: [priorKey],
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("#875: protected prior closed by accepted_suppressed prose does not kill a converged pass", async () => {
    const priorKey = "correctness|src/x.ts:1|protected blocker";
    const trustedSuppression = {
      source: "issue #445 acceptance criteria",
      scope: "#445 family integrated CMR",
      reason: "accepted by parent issue",
      findingIdentity: priorKey,
      boundedReopen: "reopen on higher severity",
    };
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [priorKey],
          priorFindingDispositions: [
            {
              identityKey: priorKey,
              status: "accepted_suppressed",
              source: trustedSuppression.source,
              scope: trustedSuppression.scope,
              reason: trustedSuppression.reason,
              boundedReopen: trustedSuppression.boundedReopen,
            },
          ],
          ...CMR_EVIDENCE,
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      priorCmrFindingIdentityKeys: [priorKey],
      moduleContext: {
        currentModules: [],
        childModules: [],
        acceptedSuppressionSources: [trustedSuppression],
      },
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("threads prior family CMR dispositions from the ledger into finding classification", async () => {
    // #875 Opus: pass requires converged:true. Prior ledger dispositions still
    // thread into classification; envelope is a clear suppressions-only pass.
    const finding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "stateful suppression should not reopen forever",
      location: "orchestrator/src/family/verifyCmr.ts:77",
      suggested_fix: "honor prior family CMR dispositions",
      action: "wont_fix",
      disposition_reason: "accepted by parent issue",
    };
    const identityKey = findingIdentityKey(finding);
    const trustedSuppression = {
      source: "issue #445 acceptance criteria",
      scope: "#445 family integrated CMR",
      reason: "accepted by parent issue",
      findingIdentity: identityKey,
      boundedReopen: "reopen on higher severity",
    };
    const findingWithDisposition: Finding = {
      ...finding,
      disposition: {
        kind: "accepted_suppressed",
        source: trustedSuppression.source,
        scope: trustedSuppression.scope,
        reason: trustedSuppression.reason,
        findingIdentity: identityKey,
        boundedReopen: trustedSuppression.boundedReopen,
      },
    };
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
          findingsCount: 0,
          findings: [findingWithDisposition],
        },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      moduleContext: {
        currentModules: [
          {
            module: "family-cmr",
            moduleScope: ["orchestrator/src/family/verifyCmr.ts"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [trustedSuppression],
      },
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual([
      "cmr",
      "cmr",
      "ship",
      "verify",
      "docRelease",
    ]);
  });
it("cmr worker returned failed ⇒ records the failure before cmr_failed gate", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "failed", reason: "sandbox exited 1" }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/sandbox exited 1/);
    expect(backend.ledger.some((e) => e.status === "aborted")).toBe(true);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("the cmr pass worker dispatch is FRESH (not a crash/escalate resume) — NO resume plumbing", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          findingsCount: 0,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      }),
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    const cmrDispatch = backend.dispatches.find((d) => d.kind === "cmr");
    expect(cmrDispatch?.session).toBe("fresh");
  });

  it("routes a VALIDATOR-PASSING content-self-labeled blocker through coder-fix (D5: runner counts, does not read reviewer self-judgment)", async () => {
    // #604 correctness r4 (D5): the same "runner counts, does not read the
    // reviewer's self-judgment" invariant, driven by a medium + fix_now finding
    // with the self-label in content only. It must ROUTE THROUGH coder-fix, never terminate the
    // family on the owning-issue claim.
    const backend = new OwningIssueStillRedThenGoodBackend(
      OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER,
      OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY,
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/604-base",
      familyBackend: backend,
    });

    const coderDispatch = backend.dispatches.find((d) => d.kind === "coder");
    expect(coderDispatch?.blockingFindingIdentityKeys).toEqual([
      OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY,
    ]);
    expect(
      backend.ledger.find(
        (entry) =>
          entry.status === "aborted" &&
          entry.reason?.includes(
            OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY,
          ),
      ),
    ).toBeUndefined();
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        cmrPass: "completeness",
        blockingFindingIdentityKeys: [
          OWNING_ISSUE_STILL_RED_THROUGH_REAL_PARSER_KEY,
        ],
      }),
    );
  });

  it.each([
    ["missing findings", undefined],
    ["empty findings", [] as const],
  ])("routes reviewer-declared count 3 with %s through coder-fix with raw artifacts", async (_label, findings) => {
    const backend = new CountChannelFixBackend({
      kind: "completed",
      sessionId: "cmr-reviewer-count-3-sparse-cargo",
      output: {
        kind: "cmr",
        converged: false,
        reason: "reviewer declared three open findings",
        findingsCount: 3,
        ...(findings !== undefined ? { findings } : {}),
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...CMR_EVIDENCE,
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/count-channel",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches[0]?.kind).toBe("cmr");
    expect(backend.dispatches[1]?.kind).toBe("coder");
    const coderIndex = backend.dispatches.findIndex((dispatch) => dispatch.kind === "coder");
    expect(backend.landings[coderIndex]).toMatchObject({
      blockingFindings: [],
      rawReviewerArtifacts: {
        reviewerSessionId: "cmr-reviewer-count-3-sparse-cargo",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
    expect(backend.ledger.some((entry) => entry.status === "cmr_passed")).toBe(true);
  });

  // Channel two says "0 converges"; owner ruling 2026-07-13 confirms the
  // reviewer-declared count is the sole routing signal, regardless of `converged`.
  it("routes converged:false with zero declared findings to cmr_passed", async () => {
    const backend = new CountChannelFixBackend({
      kind: "completed",
      sessionId: "cmr-reviewer-red-zero",
      output: {
        kind: "cmr",
        converged: false,
        reason: "reviewer explicitly reports that the pass has not converged",
        findingsCount: 0,
        findings: [],
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...CMR_EVIDENCE,
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/red-zero-count",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.some((dispatch) => dispatch.kind === "coder")).toBe(false);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({ status: "cmr_passed", cmrPass: "completeness" }),
    );
  });

  it("routes two declared findings through coder-fix despite converged:false", async () => {
    const secondFinding: Finding = {
      ...BLOCKING_FAMILY_CMR_FINDING,
      claim_quote: "a second blocking defect remains",
      location: "orchestrator/src/family/ledger.ts:1122",
    };
    const backend = new CountChannelFixBackend({
      kind: "completed",
      sessionId: "cmr-partial-cargo-session",
      output: {
        kind: "cmr",
        converged: false,
        reason: "reviewer reports two structured findings",
        findingsCount: 2,
        findings: [BLOCKING_FAMILY_CMR_FINDING, secondFinding],
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...CMR_EVIDENCE,
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/red-two-findings",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    const coderIndex = backend.dispatches.findIndex((dispatch) => dispatch.kind === "coder");
    expect(backend.landings[coderIndex]).toEqual({
      blockingFindings: [BLOCKING_FAMILY_CMR_FINDING, secondFinding],
      rawReviewerArtifacts: {
        reviewerSessionId: "cmr-partial-cargo-session",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
  });

  it("keeps converged:true with zero findings on the pass path", async () => {
    const backend = new CountChannelFixBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: true,
        findingsCount: 0,
        findings: [],
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...CMR_EVIDENCE,
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/green-zero-count",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.some((dispatch) => dispatch.kind === "coder")).toBe(false);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({ status: "cmr_passed", cmrPass: "completeness" }),
    );
  });

  it("routes a completed reviewer carrying a non-cmr shape to coder-fix as raw artifacts", async () => {
    const backend = new CountChannelFixBackend({
      kind: "completed",
      sessionId: "cmr-reviewer-wrong-shape",
      output: { kind: "ship", branch: "family/wrong-shape", status: "pushed" },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/wrong-reviewer-shape",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    const coderIndex = backend.dispatches.findIndex((dispatch) => dispatch.kind === "coder");
    expect(backend.landings[coderIndex]).toMatchObject({
      blockingFindings: [],
      rawReviewerArtifacts: {
        reviewerSessionId: "cmr-reviewer-wrong-shape",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
    expect(backend.ledger.some((entry) => entry.status === "aborted")).toBe(false);
  });

  it("sends a completed coder carrying a non-coder shape to a fresh reviewer", async () => {
    const backend = new CountChannelFixBackend(
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          findingsCount: 1,
          findings: [BLOCKING_FAMILY_CMR_FINDING],
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      },
      {
        kind: "completed",
        output: { kind: "ship", branch: "family/wrong-coder-shape", status: "pushed" },
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/wrong-coder-shape",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((dispatch) => dispatch.kind === "cmr")).toHaveLength(3);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({ status: "cmr_fix_committed", cmrPass: "completeness" }),
    );
    expect(backend.ledger.some((entry) => entry.status === "aborted")).toBe(false);
  });

  it("residual cmr missing findingsCount with finding cargo projects to judge continue (live findings to fix)", async () => {
    // #930: residual kind:cmr without findingsCount is projected once into
    // judge form. Findings cargo becomes live dispositions — not a second
    // open-count closer, and not silent empty re-furnace.
    const backend = new CountChannelFixBackend({
      kind: "completed",
      sessionId: "cmr-reviewer-missing-count",
      output: {
        kind: "cmr",
        converged: false,
        reason: "reviewer omitted its declared count",
        findings: [BLOCKING_FAMILY_CMR_FINDING],
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...CMR_EVIDENCE,
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/missing-count",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    const coderIndex = backend.dispatches.findIndex((dispatch) => dispatch.kind === "coder");
    expect(coderIndex).toBeGreaterThan(0);
    expect(backend.landings[coderIndex]).toMatchObject({
      blockingFindings: [BLOCKING_FAMILY_CMR_FINDING],
      rawReviewerArtifacts: {
        reviewerSessionId: "cmr-reviewer-missing-count",
        statement: "the previous reviewer raw artifacts are here",
      },
    });
    expect(backend.escalations).toEqual([]);
  });
});
