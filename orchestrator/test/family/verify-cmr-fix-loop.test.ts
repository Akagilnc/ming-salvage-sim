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

import { describe, expect, it } from "vitest";
import { findingIdentityKey } from "../../src/findings.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  MergeRequest,
} from "../../src/family/types.js";
import type {
  DispatchContext,
  Finding,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

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
            successfulLegs: ["opus", "gpt-5.5", "agy"],
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
    throw new Error(`unexpected worker kind ${spec.kind}`);
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

class ReviewFixRereviewBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly verifyRequests: FamilyVerifyRequest[] = [];
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
            reason: "blocking family CMR finding requires coder-fix",
            successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          repairEvidence: {
            findingScope: {
              identityKeys: [BLOCKING_FAMILY_CMR_KEY],
              locations: [BLOCKING_FAMILY_CMR_FINDING.location],
            },
            changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
            tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
            sameClassBugScan:
              "rg \"runCmrCoderFix|cmr_fix_committed\" orchestrator/src/family orchestrator/test/family",
            introducedRegressionCheck:
              "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
            patchSummary: "routed family CMR findings through coder-fix",
          },
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

    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

class CorrectnessReviewFixRestartsBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly verifyRequests: FamilyVerifyRequest[] = [];
  currentFamilyHead = "head-before-correctness-review";
  private correctnessReviewRound = 0;

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
      if (ctx.cmrPass === "correctness" && this.correctnessReviewRound++ === 0) {
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: false,
            reason: "correctness pass found a fixable family CMR finding",
            successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          repairEvidence: {
            findingScope: {
              identityKeys: [BLOCKING_FAMILY_CMR_KEY],
              locations: [BLOCKING_FAMILY_CMR_FINDING.location],
            },
            changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
            tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
            sameClassBugScan:
              "rg \"restartFinalBarrier|runVerifyCmr\" orchestrator/src/family/verifyCmr.ts",
            introducedRegressionCheck:
              "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
          },
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

    throw new Error(`unexpected worker kind ${spec.kind}`);
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
              reason: "first blocking family CMR finding requires coder-fix",
              successfulLegs: ["opus", "gpt-5.5", "agy"],
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
              reason:
                "fresh full-diff re-review found a new same-module blocker",
              successfulLegs: ["opus", "gpt-5.5", "agy"],
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
            successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          repairEvidence: {
            findingScope: {
              identityKeys: [...(ctx.blockingFindingIdentityKeys ?? [])],
              locations: [
                ...(ctx.blockingFindingIdentityKeys?.includes(
                  BLOCKING_FAMILY_CMR_KEY,
                )
                  ? [BLOCKING_FAMILY_CMR_FINDING.location]
                  : []),
                ...(ctx.blockingFindingIdentityKeys?.includes(
                  SECOND_BLOCKING_FAMILY_CMR_KEY,
                )
                  ? [SECOND_BLOCKING_FAMILY_CMR_FINDING.location]
                  : []),
              ],
            },
            changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
            tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
            sameClassBugScan:
              "rg \"allowCoderFix|runCmrCoderFix\" orchestrator/src/family/verifyCmr.ts",
            introducedRegressionCheck:
              "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
          },
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

    throw new Error(`unexpected worker kind ${spec.kind}`);
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
              reason: `fresh full-diff re-review found blocker ${reviewRound + 1}`,
              successfulLegs: ["opus", "gpt-5.5", "agy"],
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          claimedFixedFindingIdentityKeys: EXCESSIVE_CMR_FIX_KEYS,
          priorFindingDispositions: EXCESSIVE_CMR_FIX_KEYS.map((identityKey) => ({
            identityKey,
            status: "verified-closed",
            reason: "all repeated coder-fixes closed",
          })),
          ...CMR_EVIDENCE,
        },
      };
    }

    if (spec.kind === "coder") {
      const fixedKeys = [...(ctx.blockingFindingIdentityKeys ?? [])];
      this.coderFixRound += 1;
      this.currentFamilyHead = `head-after-excessive-coder-fix-${this.coderFixRound}`;
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          repairEvidence: {
            findingScope: {
              identityKeys: fixedKeys,
              locations: EXCESSIVE_CMR_FIX_FINDINGS.filter((finding) =>
                fixedKeys.includes(findingIdentityKey(finding)),
              ).map((finding) => finding.location),
            },
            changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
            tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
            sameClassBugScan:
              "rg \"remainingCmrCoderFixRounds|MAX_CMR_CODER_FIX_ROUNDS\" orchestrator/src/family/verifyCmr.ts",
            introducedRegressionCheck:
              "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
          },
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

    throw new Error(`unexpected worker kind ${spec.kind}`);
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
        repairEvidence: {
          findingScope: {
            identityKeys: [BLOCKING_FAMILY_CMR_KEY],
            locations: [BLOCKING_FAMILY_CMR_FINDING.location],
          },
          changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
          tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
          sameClassBugScan:
            "rg \"runCmrCoderFix|cmr_fix_committed\" orchestrator/src/family orchestrator/test/family",
          introducedRegressionCheck:
            "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
        },
      },
    };
  }
}

class MultipleEvidenceOnlyFailuresThenGoodBackend extends ReviewFixRereviewBackend {
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

    this.coderFixRound += 1;
    if (this.coderFixRound === 1) {
      this.currentFamilyHead = "head-after-bad-coder-fix";
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    const completeEvidence = this.coderFixRound >= 3;
    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: false,
        commitsAdded: 0,
        repairEvidence: {
          findingScope: {
            identityKeys: [BLOCKING_FAMILY_CMR_KEY],
            locations: [BLOCKING_FAMILY_CMR_FINDING.location],
          },
          changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
          tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
          ...(completeEvidence
            ? {
                sameClassBugScan:
                  "rg \"runCmrCoderFix|cmr_fix_committed\" orchestrator/src/family orchestrator/test/family",
                introducedRegressionCheck:
                  "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
              }
            : {}),
        },
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

    const repairEvidence = {
      findingScope: {
        identityKeys: [BLOCKING_FAMILY_CMR_KEY],
        locations: [BLOCKING_FAMILY_CMR_FINDING.location],
      },
      changedFiles: ["orchestrator/src/family/verifyCmr.ts"],
      tests: ["npm test -- --run test/family/verify-cmr-fix-loop.test.ts"],
      sameClassBugScan:
        "rg \"runCmrCoderFix|cmr_fix_committed\" orchestrator/src/family orchestrator/test/family",
      introducedRegressionCheck:
        "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
    };

    if (this.coderFixRound++ === 0) {
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          repairEvidence,
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
        repairEvidence,
      },
    };
  }
}

class OutcomeProtocolFailureCoderFixBackend extends ReviewFixRereviewBackend {
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
    return {
      kind: "outcome_protocol_failure",
      reason: "coder-fix outcome guard rejected missing repairEvidence",
      attempts: 2,
      sessionId: "coder-fix-session",
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
    throw new Error(`unexpected worker kind ${spec.kind}`);
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
        role: "reviewer",
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
        role: "reviewer",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "integrated_cmr_completeness.md",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({
        kind: "cmr",
        role: "reviewer",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "integrated_cmr_correctness.md",
        cmrPass: "correctness",
      }),
      expect.objectContaining({ kind: "ship", promptFile: "family_ship.md" }),
    ]);
    expect(backend.ledger).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          cmrPass: "completeness",
          familyHeadAfter: "head-before-cmr-review",
          cmrFindingClassification: expect.objectContaining({
            blocking: [BLOCKING_FAMILY_CMR_FINDING],
          }),
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
    ]);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_reviewed"),
    ).toHaveLength(2);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_fix_committed"),
    ).toHaveLength(2);
  });

  it("fails closed instead of restarting coder-fix forever when fresh CMR keeps finding blockers", async () => {
    const backend = new ExcessiveReviewFixRestartsBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(
      backend.dispatches.filter((dispatch) => dispatch.kind === "coder"),
    ).toHaveLength(3);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_fix_committed"),
    ).toHaveLength(3);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      familyHeadAfter: "head-after-excessive-coder-fix-3",
      reason: expect.stringContaining("coder-fix round budget exhausted"),
    }));
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(false);
  });

  it("restarts verify and completeness when a correctness coder-fix commits", async () => {
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
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: undefined,
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "correctness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "ship", promptFile: "family_ship.md" }),
    ]);
  });

  it("bounces family coder-fix back before re-review when repair evidence is missing", async () => {
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
        kind: "coder",
        repairAttemptFailures: [
          expect.objectContaining({
            attempt: 1,
            reason: expect.stringContaining("repairEvidence missing required"),
            familyHeadBefore: "head-before-cmr-review",
            familyHeadAfter: "head-after-bad-coder-fix",
          }),
        ],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
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
    ).toBe(3);
  });

  it("preserves evidence-only repair state across multiple failed evidence retries", async () => {
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
        kind: "coder",
        repairAttemptFailures: [
          expect.objectContaining({
            attempt: 1,
            familyHeadBefore: "head-before-cmr-review",
            familyHeadAfter: "head-after-bad-coder-fix",
          }),
        ],
      }),
      expect.objectContaining({
        kind: "coder",
        repairAttemptFailures: [
          expect.objectContaining({ attempt: 1 }),
          expect.objectContaining({
            attempt: 2,
            familyHeadBefore: "head-before-cmr-review",
            familyHeadAfter: "head-after-bad-coder-fix",
          }),
        ],
      }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      cmrPass: "completeness",
      familyHeadBefore: "head-before-cmr-review",
      familyHeadAfter: "head-after-bad-coder-fix",
      blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
    }));
  });

  it("bounces family coder-fix back before re-review when family HEAD did not move", async () => {
    const backend = new NoHeadMovementThenGoodBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({ kind: "coder" }),
      expect.objectContaining({ kind: "coder" }),
      expect.objectContaining({
        kind: "cmr",
        cmrPass: "completeness",
        priorCmrFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
      expect.objectContaining({ kind: "cmr", cmrPass: "correctness" }),
      expect.objectContaining({ kind: "ship" }),
    ]);
  });

  it("preserves coder-fix outcome protocol failure details in the durable abort", async () => {
    const backend = new OutcomeProtocolFailureCoderFixBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/551-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
      expect.objectContaining({
        kind: "coder",
        blockingFindingIdentityKeys: [BLOCKING_FAMILY_CMR_KEY],
      }),
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      reason: expect.stringContaining("outcome protocol failure"),
      stopSummary: expect.objectContaining({
        summary: expect.stringContaining(
          "coder-fix outcome guard rejected missing repairEvidence",
        ),
      }),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
  });

  it("fails closed when the CMR reviewer moves family HEAD before returning blocking findings", async () => {
    const backend = new ReviewerMutatesHeadBeforeFindingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(["cmr"]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      reason: expect.stringMatching(/CMR .*reviewer moved family HEAD/i),
      familyHeadAfter: "head-mutated-by-cmr-reviewer",
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        metadata: expect.objectContaining({
          heads: expect.objectContaining({
            reportedFamilyHead: "head-before-cmr-review",
            actualFamilyHead: "head-mutated-by-cmr-reviewer",
          }),
        }),
      }),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_passed"),
    ).toBe(false);
  });

  it("fails closed when the CMR reviewer leaves tracked changes without moving HEAD", async () => {
    const backend = new ReviewerLeavesTrackedDirtyBeforeFindingBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(["cmr"]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      reason: expect.stringMatching(/reviewer left tracked changes/i),
      familyHeadAfter: "head-before-cmr-review",
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        metadata: expect.objectContaining({
          trackedStatus: ["M tracked.txt"],
        }),
      }),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_passed"),
    ).toBe(false);
  });

  it("fails closed when the CMR reviewer checks out a different clean HEAD", async () => {
    const backend = new ReviewerChecksOutOtherHeadBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatches).toEqual([
      expect.objectContaining({ kind: "cmr", cmrPass: "completeness" }),
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      reason: expect.stringMatching(/checked out.*different HEAD/i),
      familyHeadAfter: "detached-review-head",
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        metadata: expect.objectContaining({
          heads: expect.objectContaining({
            reportedFamilyHead: "family-head",
            actualFamilyHead: "detached-review-head",
          }),
        }),
      }),
    }));
    expect(
      backend.dispatches.some((dispatch) => dispatch.kind === "ship"),
    ).toBe(false);
  });

  it("fails closed when the runner cannot read tracked status after CMR review", async () => {
    const backend = new ReviewerTrackedStatusReadFailsBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/550-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(["cmr"]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrPass: "completeness",
      reason: expect.stringContaining("tracked status read failed"),
      familyHeadAfter: "head-before-cmr-review",
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
      }),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
  });

  it("cmr workers CONVERGED ⇒ ok:true, completeness + correctness dispatches, NO coder-fix, then ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("region.cannon");
    // The runner escalated WITHOUT ever dispatching a fix or a ship.
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("cmr worker COMPLETED but NOT converged (no escalate) ⇒ machine abort with the reason, ok:false, NO ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          reason: "cross-slice contract drift left unresolved",
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          ...CMR_EVIDENCE,
        },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringContaining("contract drift"),
      stopSummary: expect.objectContaining({ reason: "contract_drift" }),
    }));
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("converged cmr with prior claimed-fixed keys but no dispositions fails closed", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringMatching(/missing explicit disposition/i),
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        repairHint: expect.stringContaining("claimed-fixed closure payload"),
      }),
    }));
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("converged cmr cannot self-claim stale prior keys without runner closure context", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringMatching(/closure_context_missing/i),
    }));
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("converged cmr rejects claimed-fixed keys outside the runner closure context", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
      priorCmrFindingIdentityKeys: ["correctness|src/x.ts:1|real closure"],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringMatching(/outside the runner-supplied/i),
    }));
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("converged cmr with a still-active prior disposition fails even when the claimed key list is empty", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringMatching(/were not explicitly claimed fixed|not verified closed/i),
    }));
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("converged cmr with verified-closed dispositions may pass to ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

  it("blocking family CMR stop summary selects a blocking result, not an earlier suppression", async () => {
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
    const blocker: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "ADR conflicts with implementation",
      location: "orchestrator/src/family/verifyCmr.ts:2",
      suggested_fix: "resolve the accepted contract conflict",
      action: "defer",
      disposition: {
        kind: "spec_conflict",
        source: "ADR 0030",
        reason: "ADR and implementation require different CMR outcomes.",
      },
    };
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          reason: "has blocking findings",
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      cmrFindingClassification: expect.objectContaining({
        results: expect.arrayContaining([
          expect.objectContaining({
            identityKey:
              "correctness|orchestrator/src/family/verifycmr.ts:1|accepted hub-loss gap",
            classification: "accepted_suppressed",
          }),
        ]),
      }),
      stopSummary: expect.objectContaining({
        reason: "spec_conflict",
        finding: blocker,
      }),
    }));
    const aborted = backend.ledger.find((entry) => entry.status === "aborted");
    expect(aborted?.reason).toContain("spec_conflict");
    expect(aborted?.reason).not.toContain("accepted_suppressed");
  });

  it("fails closed when prior accepted_suppressed closure lacks a trusted suppression source", async () => {
    const priorKey = "correctness|src/x.ts:1|accepted without trusted source";
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        summary: expect.stringContaining("accepted_suppressed"),
      }),
    }));
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(["cmr"]);
  });

  it("fails closed when a runner-protected prior blocker is closed by accepted_suppressed", async () => {
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      reason: expect.stringContaining("cannot be closed by accepted_suppressed"),
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
      }),
    }));
    expect(backend.dispatches.map((dispatch) => dispatch.kind)).toEqual(["cmr"]);
  });

  it("threads prior family CMR dispositions from the ledger into finding classification", async () => {
    const finding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "stateful suppression should not reopen forever",
      location: "orchestrator/src/family/verifyCmr.ts:77",
      suggested_fix: "honor prior family CMR dispositions",
      action: "fix_now",
    };
    const identityKey = findingIdentityKey(finding);
    const trustedSuppression = {
      source: "issue #445 acceptance criteria",
      scope: "#445 family integrated CMR",
      reason: "accepted by parent issue",
      findingIdentity: identityKey,
      boundedReopen: "reopen on higher severity",
    };
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: {
          kind: "cmr",
          converged: false,
          reason: "same finding reappeared",
          successfulLegs: ["opus", "gpt-5.5", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
          findings: [finding],
        },
      }),
    });
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      cmrFindingClassification: {
        blocking: [],
        deferred: [],
        results: [],
        dispositions: [
          {
            identityKey,
            status: "accepted_suppressed",
            reason: trustedSuppression.reason,
            severity: "medium",
            reopenAttempts: 0,
            disputeAttempts: 1,
            source: trustedSuppression.source,
            scope: trustedSuppression.scope,
            boundedReopen: trustedSuppression.boundedReopen,
          },
        ],
        moduleContext: {
          currentModules: [],
          childModules: [],
          undevelopedModules: [],
        },
      },
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
    ]);
  });

  it("cmr worker MALFORMED / crash ⇒ recordAborted + INCOMPLETE_GATE (ok:false), NO ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "malformed", reason: "no parseable CMR-VERDICT" }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    // A malformed cmr persists a DURABLE aborted ledger entry (recordDurableAbort →
    // appendFamilyLedger), so a resume doesn't re-run the same failing gate blind.
    expect(backend.ledger.some((e) => e.status === "aborted")).toBe(true);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("cmr worker returned failed ⇒ records the failure before INCOMPLETE_GATE", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "failed", reason: "sandbox exited 1" }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
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
          successfulLegs: ["opus", "gpt-5.5", "agy"],
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
});

describe("the verifyCmr seam keeps cmr pass outcomes at the WorkerResult boundary", () => {
  it("verifyCmr.ts source has no local drift constants or legacy priorFindings/cmrReason threading", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const src = readFileSync(
      fileURLToPath(new URL("../../src/family/verifyCmr.ts", import.meta.url)),
      "utf8",
    );
    // No local round counter / drift constant in this hook.
    expect(src).not.toMatch(/NO_PROGRESS_LIMIT/);
    expect(src).not.toMatch(/noProgressStreak/);
    expect(src).not.toMatch(/prevReasonKey/);
    // No ad-hoc unbounded iteration in this hook.
    expect(src).not.toMatch(/for\s*\(;;\)/);
    // No legacy priorFindings/cmrReason threading through the family hook.
    expect(src).not.toMatch(/priorFindings/);
    expect(src).not.toMatch(/cmrReason/);
    // Family coder-fix is an explicit runner boundary, not hidden in the CMR worker.
    expect(src).toMatch(/familyCoderFixWorkerSpec/);
    // No resume-session plumbing for the cmr worker.
    expect(src).not.toMatch(/resumeSessionId:/);
    // Provider-degradation matching must tolerate dirty route legs without family.
    expect(src).not.toMatch(/leg\.family\.toLowerCase\(\)/);
  });
});
