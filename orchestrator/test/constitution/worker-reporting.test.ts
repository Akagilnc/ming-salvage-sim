/**
 * #825 — closing regression sweep for ADR 0062 / #820.
 *
 * #928: `*_STEP_COMPLETE` passwords retired — completion is clean exit + legal
 * sidecar / typed envelope. Routing behavior is exercised below through worker
 * results and durable ledgers, not source-text bans.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { runOrchestrator } from "../../src/runner.js";
import { mergeChild } from "../../src/family/merger.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import { runOnlineReviewLoopStage } from "../../src/family/onlineReviewLoop.js";
import { buildRoundTrigger } from "../../src/evidenceAdmissibility.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import { completeReviewPanelLegWorker } from "../helpers/review-panel-leg-dispatch.js";
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {

  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";
import { onlineReviewDispatch } from "../helpers/online-review-dispatch.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/825-behavior",
  base: "main",
  path: "/tmp/825-behavior",
};

class ScriptedRunnerBackend implements Backend {
  readonly ledger: PersistentLedgerEntry[] = [];
  readonly dispatches: string[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  private readonly attempts = new Map<string, number>();

  constructor(
    private readonly script: (
      spec: WorkerSpec,
      attempt: number,
      ctx: DispatchContext,
    ) => WorkerResult | Promise<WorkerResult>,
  ) {}

  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<ResumeState | undefined> { return undefined; }
  async fetchIssueMeta(number: number): Promise<IssueMeta> {
    return { number, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async prepareWorktree() { return WORKTREE; }
  async runStep(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async resumeSession(_spec: StepSpec, _worktree: WorktreeHandle, _sessionId: string): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(entry: PersistentLedgerEntry) { this.ledger.push(entry); }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext, landing?: WorkerLandingPayload) {
    const attempt = (this.attempts.get(spec.id) ?? 0) + 1;
    this.attempts.set(spec.id, attempt);
    this.dispatches.push(`${spec.id}:${spec.kind}:${attempt}`);
    this.landings.push(landing);
    return this.script(spec, attempt, ctx);
  }
}

function validWorkerResult(spec: WorkerSpec): WorkerResult {
  if ((spec.kind === "reviewer" || spec.kind === "verify")) {
    return { kind: "completed", output: { kind: "judge", status: "converged" } };
  }
  const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
  if (skeleton !== undefined) return skeleton;
  return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
}

describe("#825 Group A/B — real runner defective-report and exit retry behavior", () => {
  it("Group A coder completed report advances without git adjudication", async () => {
    const backend = new ScriptedRunnerBackend((spec) => {
      if (spec.id === "S2") {
        return {
          kind: "completed",
          output: {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
          },
        };
      }
      return validWorkerResult(spec);
    });
    const result = await runOrchestrator({ issueNumber: 825, backend });
    expect(result.status).toBe("completed");
    expect(result.stepLedger.find((row) => row.step === "S2")?.output).toMatchObject({
      kind: "coder", committed: false, commitsAdded: 0,
    });
  });

  it("Group B: exit != 0 is a step-level mechanical retry, not false success or run failure", async () => {
    const backend = new ScriptedRunnerBackend((spec, attempt) =>
      spec.id === "S2" && attempt === 1
        ? { kind: "failed", reason: "process exited 17", sessionId: "failed-s2" }
        : validWorkerResult(spec));
    const result = await runOrchestrator({ issueNumber: 825, backend });
    expect(backend.dispatches.filter((row) => row.startsWith("S2:"))).toHaveLength(2);
    expect(result.status).toBe("completed");
    expect(result.stepLedger.find((row) => row.step === "S2")?.output).toMatchObject({ committed: true });
  });

  it("coder StructuredOutputError is mechanical-retried at the same step without decision park", async () => {
    // #899: typed-signal SOE exhaust is process-level #598 redispatch, not
    // silent advance as committed:0 and not a decision-gate park.
    const backend = new ScriptedRunnerBackend((spec, attempt) => {
      if (spec.id === "S2" && attempt === 1) {
        const err = new Error("coder outcome JSON was truncated");
        err.name = "StructuredOutputError";
        throw err;
      }
      return validWorkerResult(spec);
    });

    const result = await runOrchestrator({ issueNumber: 825, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatches.filter((row) => row.startsWith("S2:")).length).toBeGreaterThanOrEqual(2);
    expect(JSON.stringify(result.stepLedger)).not.toContain('"escalationKind":"decision"');
  });

  it("reviewer StructuredOutputError exhaust redispatches S3 only — zero S5 fixer", async () => {
    // #899 / R2 Spec: pure reviewer SOE exhaust is process-level #598 at the
    // same seat. Runner must NOT invent an S5 fixer dispatch from SOE throw.
    const backend = new ScriptedRunnerBackend((spec) => {
      if (spec.id === "S3") {
        const err = new Error("reviewer open-count SO exhausted");
        err.name = "StructuredOutputError";
        throw err;
      }
      return validWorkerResult(spec);
    });

    const result = await runOrchestrator({ issueNumber: 825, backend });

    expect(result.status).toBe("failed");
    expect(backend.dispatches.filter((row) => row.startsWith("S3:"))).toHaveLength(
      MAX_DISPATCH_ATTEMPTS,
    );
    expect(backend.dispatches.filter((row) => row.startsWith("S5:"))).toHaveLength(0);
    expect(backend.dispatches.filter((row) => row.startsWith("S6:"))).toHaveLength(0);
    expect(JSON.stringify(result.stepLedger)).not.toContain('"escalationKind":"decision"');
  });

  it("coder completed no-commit report advances once to S3", async () => {
    const backend = new ScriptedRunnerBackend((spec) =>
      spec.id === "S2"
        ? { kind: "completed", output: { kind: "coder", committed: false, commitsAdded: 0 } }
        : validWorkerResult(spec));

    const result = await runOrchestrator({ issueNumber: 825, backend });

    expect(result.status).toBe("completed");
    expect(backend.dispatches.filter((row) => row.startsWith("S2:"))).toHaveLength(1);
    expect(backend.dispatches.filter((row) => row.startsWith("S3:"))).toHaveLength(1);
    expect(JSON.stringify(result.stepLedger)).not.toContain('"synthesizedFailure"');
    expect(JSON.stringify(backend.ledger)).not.toContain('"escalationKind":"decision"');
  });
});

describe("#825 Group A family roles", () => {
  it("Group A merger still-conflicted: Action trusts one worker outcome and does not host-redispatch (#938)", async () => {
    class MergerBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

      readonly ledger: FamilyLedgerEntry[] = [];
      resolves = 0;
      async mergeChildIntoFamilyBase(_request: MergeRequest) {
        return { conflicted: true, familyHead: "base" };
      }
      async resolveMergeConflict() {
        this.resolves += 1;
        // Still conflicted after the worker returns once — Action converges that
        // outcome (ID-010); process-root retry lives inside the worker leg.
        return { conflicted: true, familyHead: "base" };
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry) { this.ledger.push(entry); }
      async readFamilyLedger() { return this.ledger; }
    }
    const backend = new MergerBackend();
    const result = await mergeChild(backend, { childIssue: 825, childBranch: "feat/child-825" });
    expect(result.conflicted).toBe(true);
    expect(result.familyHead).toBe("base");
    expect(backend.resolves).toBe(1);
    expect(backend.ledger).toEqual([]);
  });

  it("Group A CMR reviewer bad envelope: real family gate retries then continues to ship", async () => {
    class CmrBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      readonly ledger: FamilyLedgerEntry[] = [];
      cmrCalls = 0;
      shipCalls = 0;
      async mergeChildIntoFamilyBase() { return { familyHead: "head" }; }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

      async appendFamilyLedger(entry: FamilyLedgerEntry) { this.ledger.push(entry); }
      async readFamilyLedger() { return this.ledger; }
      async readFamilyHead() { return "head"; }
      async runFamilyVerify() { return { ok: true as const }; }
      async dispatchWorker(spec: WorkerSpec, _ctx: DispatchContext): Promise<WorkerResult> {
        const panelLeg = completeReviewPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          this.cmrCalls += 1;
          if (this.cmrCalls === 1) {
            throw new Error("bad JSON sidecar parser failure");
          }
          return { kind: "completed", output: { kind: "judge", status: "converged", successfulLegs: ["opus", "gpt-5.6-sol", "agy"], skippedLegs: [], evidencePaths: ["cmr/review-summary.json"] } };
        }
        if (spec.kind === "ship") {
          this.shipCalls += 1;
          return { kind: "completed", output: { kind: "ship", branch: "family/825", status: "pr_opened", pr: "https://github.com/test/repo/pull/825", prHead: "head" } };
        }
        // #940: offline skeleton / explicit role cargo — do not return ship
        // envelopes for verify/fixer (would hang the uncapped continue loop).
        if (spec.kind === "verify") {
          return { kind: "completed", output: { kind: "verify", status: "converged" } };
        }
        if (spec.kind === "fixer") {
          return { kind: "completed", output: { kind: "fixer", committed: false } };
        }
        if (spec.kind === "landing") {
          return { kind: "completed", output: { kind: "landing", released: true } };
        }
        return { kind: "failed", reason: `unexpected kind ${spec.kind}` };
      }
    }
    const backend = new CmrBackend();
    const result = await runVerifyCmr({ phase: "final", familyBase: "family/825", familyBackend: backend });
    expect(result.ran).toBe(true);
    expect(backend.cmrCalls).toBeGreaterThanOrEqual(2);
    expect(backend.shipCalls).toBeGreaterThanOrEqual(1);
    expect(backend.ledger.some((row) => row.reason?.includes("bad JSON"))).toBe(true);
  });

  it("Group A fixer wrong/missing report: committed:false continues to a fresh verify baton", async () => {
    let verifyCalls = 0;
    let fixerCalls = 0;
    const snapshot: PrReviewSnapshot = {
      repo: "o/r", prNumber: 825, prUrl: "https://github.com/test/repo/pull/825", headOid: "head", pollCount: 1,
      totalFindingCount: 1, quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 1 }, sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 }, gemini: { state: "complete", findingCount: 0 },
      }, threads: [], checkRuns: [], roundTriggerUsed: buildRoundTrigger("head"),
      checkRunsEmptyMeans: "converged",
    };
    const result = await runOnlineReviewLoopStage(
      { kind: "ship", branch: WORKTREE.branch, status: "pr_opened", pr: "https://github.com/test/repo/pull/825" },
      onlineReviewDispatch({
      snapshot: snapshot,
        dispatchVerify: async () => (++verifyCalls === 1
          ? { kind: "verify", status: "continue", findingDispositions: [{ identityKey: "f:1", threadId: "thread-f1", action: "fix" }] }
          : { kind: "verify", status: "converged", isRecheck: true, fixMarkedFindingIdentityKeys: ["f:1"] }),
        dispatchFixer: async () => { fixerCalls += 1; return { kind: "fixer", committed: false }; },

      }),
    );
    // #1145: legal no-op returns to same judge — no round++ / no new Collector.
    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 1 });
    expect({ verifyCalls, fixerCalls }).toEqual({ verifyCalls: 2, fixerCalls: 1 });
  });
});

describe("#825 Group D — no git output enters findings-driven reviewer/fixer loop", () => {
  it("committed:false never invokes a lie-detector gate; next fresh findings control the loop", async () => {
    // This is the missing assertion angle on the merged e2e in online-review-loop-600.test.ts.
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(
      { kind: "ship", branch: WORKTREE.branch, status: "pr_opened", pr: "https://github.com/test/repo/pull/825" },
      onlineReviewDispatch({
      snapshot: {
          repo: "o/r", prNumber: 825, prUrl: "https://github.com/test/repo/pull/825", headOid: "head", pollCount: 1,
          totalFindingCount: 1, quiescent: true,
          bots: { coderabbit: { state: "complete", findingCount: 1 }, sourcery: { state: "complete", findingCount: 0 }, codex: { state: "complete", findingCount: 0 }, gemini: { state: "complete", findingCount: 0 } },
          threads: [], checkRuns: [], roundTriggerUsed: buildRoundTrigger("head"),
          checkRunsEmptyMeans: "converged" as const,
        },
        dispatchVerify: async () => (++verifyCalls === 1
          ? { kind: "verify", status: "continue", findingDispositions: [{ identityKey: "fresh:1", threadId: "thread-fresh1", action: "fix" }] }
          : { kind: "verify", status: "converged", isRecheck: true, fixMarkedFindingIdentityKeys: ["fresh:1"] }),
        dispatchFixer: async () => ({ kind: "fixer", committed: false }),

      }),
    );
    expect({
      verifyCalls,
      ok: result.ok,
      terminalState: result.terminalState,
      round: result.round,
    }).toEqual({
      verifyCalls: 2,
      ok: true,
      terminalState: "mergeable",
      round: 1,
    });
  });
});

describe("#825 Group C — durable decision park and in-place resume", () => {
  it("decision gate survives re-feed; the answer resumes the persisted sessionId in place", async () => {
    const row = (step: "S0" | "S1" | "S2" | "S8", output?: StepOutput, sessionId = "prior"): PersistentLedgerEntry => ({
      step, sessionId, prompt_hash: `hash-${step}`, branchHEAD: "head", ts: "2026-07-11T00:00:00.000Z",
      ...(output === undefined ? {} : { output }),
    });
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/tmp/.ledger-825",
      ledger: [
        row("S0"), row("S1"),
        row("S2", {
          kind: "coder", committed: false, commitsAdded: 0,
          escalate: {
            reason: "decision needed",
            diagnosis: "choose A or B",
          },
        }, "session-decision-825"),
        { ...row("S8"), handoffStatus: "parked", escalationKind: "decision" },
        {
          ...row("S2"), event: "escalation_answered", forStep: "S2",
          answer: "choose A", source: "human",
        },
      ],
    };
    const resumed: Array<[string, string | undefined]> = [];
    class ResumeDecisionBackend extends ScriptedRunnerBackend {
      constructor() {
        super((spec, _attempt, ctx) => {
          resumed.push([spec.id, ctx.resumeSessionId]);
          return validWorkerResult(spec);
        });
      }
      override async findResumeState() { return resumeState; }
    }
    const backend = new ResumeDecisionBackend();
    const result = await runOrchestrator({ issueNumber: 825, backend });
    expect(resumed[0]).toEqual(["S2", "session-decision-825"]);
    expect(result.status).toBe("completed");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      step: "S2",
      output: expect.objectContaining({ kind: "coder", committed: true, commitsAdded: 1 }),
    }));
    expect(result.stepLedger.filter((entry) => entry.step === "S2").at(-1)).toMatchObject({
      output: { kind: "coder", committed: true, commitsAdded: 1 },
    });
  });
});
