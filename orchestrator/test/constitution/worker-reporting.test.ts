/**
 * #825 — closing regression sweep for ADR 0062 / #820.
 *
 * Completion sentinels are optional telemetry. Routing behavior is exercised
 * below through worker results and durable ledgers, not source-text bans.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import { mergeChild } from "../../src/family/merger.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import { runOnlineReviewLoopStage } from "../../src/family/onlineReviewLoop.js";
import { buildRoundTrigger } from "../../src/evidenceAdmissibility.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
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

describe("#825 ADR 0062 worker reporting", () => {
  it.each([
    "image/souls/fixer.md",
    "prompts/fixer.md",
  ])("routes fixer self-audit evidence outside the strict outcome envelope in %s", (file) => {
    const body = readFileSync(resolve(process.cwd(), file), "utf8");
    expect(body).toContain("Record the self-audit checklist in the fixing commit message body");
  });
});

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
  async fetchIssueSnapshot(number: number): Promise<IssueSnapshot> {
    return { number, body: "behavioral regression", comments: [], agentBrief: "" };
  }
  async prepareWorktree() { return WORKTREE; }
  async writeSnapshot() {}
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
  if (spec.kind === "reviewer") {
    return { kind: "completed", output: { kind: "reviewer", findings: [] } };
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
    expect(result.status).toBe("success");
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
    expect(result.status).toBe("success");
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

    expect(result.status).toBe("success");
    expect(backend.dispatches.filter((row) => row.startsWith("S2:")).length).toBeGreaterThanOrEqual(2);
    expect(JSON.stringify(result.stepLedger)).not.toContain('"escalationKind":"decision"');
  });

  it("coder completed no-commit report advances once to S3", async () => {
    const backend = new ScriptedRunnerBackend((spec) =>
      spec.id === "S2"
        ? { kind: "completed", output: { kind: "coder", committed: false, commitsAdded: 0 } }
        : validWorkerResult(spec));

    const result = await runOrchestrator({ issueNumber: 825, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatches.filter((row) => row.startsWith("S2:"))).toHaveLength(1);
    expect(backend.dispatches.filter((row) => row.startsWith("S3:"))).toHaveLength(1);
    expect(JSON.stringify(result.stepLedger)).not.toContain('"synthesizedFailure"');
    expect(JSON.stringify(backend.ledger)).not.toContain('"escalationKind":"decision"');
  });
});

describe("#825 Group A family roles", () => {
  it("Group A merger missing sidecar: unresolved report redispatches mechanically and records the landed merge", async () => {
    class MergerBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      resolves = 0;
      async mergeChildIntoFamilyBase(_request: MergeRequest) {
        return { conflicted: true, familyHead: "base" };
      }
      async resolveMergeConflict() {
        this.resolves += 1;
        return this.resolves === 1
          ? { conflicted: true, familyHead: "base" }
          : { conflicted: false, familyHead: "merged", familyHeadBefore: "base", childHead: "child" };
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry) { this.ledger.push(entry); }
      async readFamilyLedger() { return this.ledger; }
    }
    const backend = new MergerBackend();
    const result = await mergeChild(backend, { childIssue: 825, childBranch: "feat/child-825" });
    expect(result.familyHead).toBe("merged");
    expect(backend.resolves).toBe(2);
    expect(backend.ledger).toContainEqual(expect.objectContaining({ status: "merged", familyHeadAfter: "merged" }));
  });

  it("Group A CMR reviewer bad envelope: real family gate retries then continues to ship", async () => {
    class CmrBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      cmrCalls = 0;
      shipCalls = 0;
      async mergeChildIntoFamilyBase() { return { familyHead: "head" }; }
      async appendFamilyLedger(entry: FamilyLedgerEntry) { this.ledger.push(entry); }
      async readFamilyLedger() { return this.ledger; }
      async readFamilyHead() { return "head"; }
      async runFamilyVerify() { return { ok: true as const }; }
      async dispatchWorker(spec: WorkerSpec, _ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.cmrCalls += 1;
          if (this.cmrCalls === 1) {
            throw new Error("bad JSON sidecar parser failure");
          }
          return { kind: "completed", output: { kind: "cmr", findingsCount: 0, converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"], skippedLegs: [], evidencePaths: ["cmr/review-summary.json"] } };
        }
        this.shipCalls += 1;
        return { kind: "completed", output: { kind: "ship", branch: "family/825", status: "pr_opened", pr: "pr://825", prHead: "head" } };
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
      repo: "o/r", prNumber: 825, prUrl: "pr://825", headOid: "head", pollCount: 1,
      totalFindingCount: 1, quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 1 }, sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 }, gemini: { state: "complete", findingCount: 0 },
      }, threads: [], checkRuns: [], roundTriggerUsed: buildRoundTrigger("head"),
      checkRunsEmptyMeans: "converged",
    };
    const result = await runOnlineReviewLoopStage(
      { kind: "ship", branch: WORKTREE.branch, status: "pr_opened", pr: "pr://825" },
      {
        poll: async () => snapshot,
        dispatchVerify: async () => (++verifyCalls === 1
          ? { kind: "verify", converged: false, findingDispositions: [{ identityKey: "f:1", threadId: "thread-f1", action: "fix" }] }
          : { kind: "verify", converged: true, isRecheck: true, fixMarkedFindingIdentityKeys: ["f:1"] }),
        dispatchFixer: async () => { fixerCalls += 1; return { kind: "fixer", committed: false }; },
        dispatchDocRelease: async () => true,
        applySideEffects: (_landing, verify) => verify,
        retriggerAfterFix: () => {},
      },
    );
    expect(result).toMatchObject({ ok: true, terminalState: "mergeable", round: 2 });
    expect({ verifyCalls, fixerCalls }).toEqual({ verifyCalls: 2, fixerCalls: 1 });
  });
});

describe("#825 Group D — no git output enters findings-driven reviewer/fixer loop", () => {
  it("committed:false never invokes a lie-detector gate; next fresh findings control the loop", async () => {
    // This is the missing assertion angle on the merged e2e in online-review-loop-600.test.ts.
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(
      { kind: "ship", branch: WORKTREE.branch, status: "pr_opened", pr: "pr://825" },
      {
        poll: async () => ({
          repo: "o/r", prNumber: 825, prUrl: "pr://825", headOid: "head", pollCount: 1,
          totalFindingCount: 1, quiescent: true,
          bots: { coderabbit: { state: "complete", findingCount: 1 }, sourcery: { state: "complete", findingCount: 0 }, codex: { state: "complete", findingCount: 0 }, gemini: { state: "complete", findingCount: 0 } },
          threads: [], checkRuns: [], roundTriggerUsed: buildRoundTrigger("head"),
          checkRunsEmptyMeans: "converged" as const,
        }),
        dispatchVerify: async () => (++verifyCalls === 1
          ? { kind: "verify", converged: false, findingDispositions: [{ identityKey: "fresh:1", threadId: "thread-fresh1", action: "fix" }] }
          : { kind: "verify", converged: true, isRecheck: true, fixMarkedFindingIdentityKeys: ["fresh:1"] }),
        dispatchFixer: async () => ({ kind: "fixer", committed: false }),
        dispatchDocRelease: async () => true,
        applySideEffects: (_landing, verify) => verify,
        retriggerAfterFix: () => {},
      },
    );
    expect({ verifyCalls, ok: result.ok, terminalState: result.terminalState }).toEqual({
      verifyCalls: 2,
      ok: true,
      terminalState: "mergeable",
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
        { ...row("S8"), handoffStatus: "escalate", escalationKind: "decision" },
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
    expect(result.status).toBe("success");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      step: "S2",
      output: expect.objectContaining({ kind: "coder", committed: true, commitsAdded: 1 }),
    }));
    expect(result.stepLedger.filter((entry) => entry.step === "S2").at(-1)).toMatchObject({
      output: { kind: "coder", committed: true, commitsAdded: 1 },
    });
  });
});
