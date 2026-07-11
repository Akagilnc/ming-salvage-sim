/**
 * #255 — Idempotent resume tests (RED → GREEN).
 *
 * Crash-resume and escalate-resume share ONE machine: when the same issue is
 * re-fed and a resident slice branch/worktree already exists (crash residue or
 * escalate residue), the runner reuses the existing HEAD and continues from the
 * step recorded in the ledger — it does NOT re-cut from S0, does NOT re-run
 * already-completed steps, and does NOT re-burn the LLM on prior steps.
 *
 * Acceptance criteria (issue #255):
 *   AC1 — fake Backend reports "branch/worktree already exists" → assert reuse
 *         of existing HEAD (no re-cut); before reuse, the residue-clean action
 *         (reset --hard / clean -fd / worktree prune) is invoked while committed
 *         progress is preserved.
 *   AC2 — backend call dies mid-run → "re-feed same issue" → assert crash-resume
 *         path: read ledger, continue from the recorded next step, lose no
 *         committed progress, do not re-burn the LLM from scratch.
 *   AC3 — escalate blocker, human gives an answer, re-feed → assert it goes
 *         through Sandcastle-native `resumeSession` (carrying the ledger's
 *         sessionId) to resume the real agent session — SAME machine as
 *         crash-resume, continuing from the breakpoint, not re-running from S0.
 *   AC4 — assert recovery reads the ledger (incl. sessionId) + branch HEAD to
 *         decide the next step, NOT any in-memory / LLM state.
 *
 * Strategy: extend the Backend fake with
 *   - findResumeState(issueNumber) → ResumeState | undefined  (the host-side
 *     check that detects an existing resident worktree + persisted ledger)
 *   - cleanResidue(worktree)                                  (reset/clean/prune)
 *   - resumeSession(spec, worktree, sessionId)                (Sandcastle-native)
 * A fresh run returns undefined from findResumeState (no residue) → behaves
 * exactly like before. A resume run pre-loads a ResumeState whose ledger stops
 * at step k, then asserts the runner reuses, cleans, and continues from k+1.
 */

import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import { buildRoundTrigger } from "../src/evidenceAdmissibility.js";
import {
  ONLINE_REVIEW_SNAPSHOT_FILE,
  onlineReviewRoundFromLedger,
  lastOnlineReviewFixCommitShaFromLedger,
} from "../src/onlineReviewLoop.js";
import * as onlineReviewLoop from "../src/onlineReviewLoop.js";
import * as autoMerge from "../src/autoMerge.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  DispatchContext,
  OnlineReviewLandingSnapshot,
  PrMergedEvent,
  StepId,
  StepOutput,
  StepSpec,
  VerifyResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

type PrMergedLedgerFixture = PersistentLedgerEntry & PrMergedEvent;

// ─── shared fixtures ──────────────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-255",
  base: "main",
  path: "/resident/worktrees/issue-255",
};

const STATE_DIR = "/resident/worktrees/.ledger-255";

const CLAIMED_FIXED_FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "Do not rely on omitting a finding to mean it is closed.",
  location: "orchestrator/src/runner.ts:1061",
  suggested_fix: "Replay prior S4 adjudication state on resume.",
  action: "fix_now",
};

const CLAIMED_FIXED_KEY =
  "correctness|orchestrator/src/runner.ts:1061|do not rely on omitting a finding to mean it is closed.";

function stubAutoMergeMergedForLiveReviewTests(
  livePr: string,
  mergedHeadOid: string,
): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(autoMerge, "runAutoMergeStage").mockResolvedValue({
    ok: true,
    terminalState: "merged",
    record: {
      prUrl: livePr,
      prNumber: 255,
      remoteBranchName: WORKTREE.branch,
      mergedHeadOid,
      convergedHeadOid: mergedHeadOid,
    },
  });
}

/** Build a persisted ledger entry (the resume truth on disk). */
function entry(
  step: StepId,
  output?: StepOutput,
  sessionId = "session-prior",
  branchHEAD = "deadbeefcommitsha",
): PersistentLedgerEntry {
  return {
    step,
    sessionId,
    prompt_hash: `hash-${step}`,
    branchHEAD,
    ts: "2026-06-21T00:00:00.000Z",
    ...(output !== undefined ? { output } : {}),
  };
}

function writeResumeOnlineReviewSnapshot(stateDir: string): void {
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(
    join(stateDir, ONLINE_REVIEW_SNAPSHOT_FILE),
    `${JSON.stringify(
      {
        repo: "Akagilnc/ming-salvage-sim",
        prNumber: 0,
        prUrl: "pr://slice/offline-255",
        headOid: "deadbeefcommitsha",
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 1 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        threads: [
          {
            id: "100",
            threadNodeId: "PRRT_resumeThread",
            body: "fix this",
            authorLogin: "bot",
            isResolved: false,
          },
        ],
        checkRuns: [],
        totalFindingCount: 1,
        quiescent: true,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
}

/** Build a terminal S8 entry tagged with its handoff status (#255). */
function s8(handoffStatus: "success" | "escalate" | "error"): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    handoffStatus,
  };
}

function coderProtocolFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder step stdout carried no <coder>...</coder> tag - the coder must emit its structured result in a <coder> tag.",
      repairHint:
        "Inspect the landed commit and resume from the next step if HEAD advanced.",
    },
  };
}

function malformedCoderPayloadFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder must emit its structured result in a <coder> tag; the payload was malformed.",
      repairHint: "Fix the malformed coder payload instead of fabricating a landed coder output.",
    },
  };
}

function escalationAnswer(
  forStep: StepId,
  answer: string,
  note?: string,
): PersistentLedgerEntry {
  return {
    ...entry(forStep),
    event: "escalation_answered",
    forStep,
    answer,
    source: "human",
    ...(note !== undefined ? { note } : {}),
  };
}

/**
 * A configurable resume-aware fake Backend.
 *
 * - If `resumeState` is provided, findResumeState returns it (the issue has
 *   residue: existing worktree + persisted ledger). Otherwise it returns
 *   undefined (fresh run).
 * - Records cleanResidue / prepareWorktree / resumeSession / runStep calls so
 *   the tests can assert reuse-vs-recut and resume-vs-fresh-session.
 */
class ResumeBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  readonly commitCountsBetween = new Map<string, number>();
  /** Each resumeSession call: [stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[string, string]> = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return this.resumeState;
  }

  async cleanResidue(_worktree: WorktreeHandle): Promise<void> {
    this.calls.push("cleanResidue");
    this.cleanResidueCount += 1;
  }

  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
    this.resumeSessionCalls.push([spec.id, sessionId]);
    this.runStepIds.push(spec.id);
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareWorktreeCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(
    spec: StepSpec,
    _worktree: WorktreeHandle,
  ): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async countCommitsBetween(
    _worktree: WorktreeHandle,
    fromHead: string,
    toHead: string,
  ): Promise<number> {
    this.calls.push(`countCommitsBetween(${fromHead}, ${toHead})`);
    return this.commitCountsBetween.get(`${fromHead}..${toHead}`) ?? 1;
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async pollOnlineReviewState(input: {
    repo: string;
    prUrl: string;
    pollCount: number;
  }): Promise<OnlineReviewLandingSnapshot> {
    void input;
    return {
      prUrl: "pr://slice/offline-255",
      headOid: "deadbeefcommitsha",
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
}

class DispatchRecordingResumeBackend extends ResumeBackend {
  readonly dispatchSpecs: WorkerSpec[] = [];
  readonly dispatchContexts: DispatchContext[] = [];
  readonly dispatchLandings: Array<WorkerLandingPayload | undefined> = [];

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatchSpecs.push(spec);
    this.dispatchContexts.push(ctx);
    this.dispatchLandings.push(landing);

    if (spec.kind === "ship") {
      if (ctx.worktree === undefined) {
        throw new Error("test backend: ship dispatch requires a worktree");
      }
      await this.push(ctx.worktree);
      return {
        kind: "completed",
        output: { kind: "ship", branch: ctx.worktree.branch, status: "pushed" },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }

    const stepSpec = spec as unknown as StepSpec;
    if (spec.id === "S6") {
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "verified-closed" },
          ],
        },
      };
    }
    const output =
      ctx.resumeSessionId !== undefined
        ? await this.resumeSession(stepSpec, ctx.worktree!, ctx.resumeSessionId)
        : await this.runStep(stepSpec, ctx.worktree!);
    return { kind: "completed", output };
  }
}

/** Records landing + drives verify→fixer→recheck for #600 r7 resume tests. */
class ReviewLoopResumeBackend extends DispatchRecordingResumeBackend {
  verifyDispatchCount = 0;

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (spec.kind === "verify") {
      this.verifyDispatchCount += 1;
      this.dispatchSpecs.push(spec);
      this.dispatchContexts.push(ctx);
      this.dispatchLandings.push(landing);
      if (this.verifyDispatchCount === 1) {
        return {
          kind: "completed",
          output: {
            kind: "verify",
            converged: true,
            ...(landing?.fixMarkedFindingIdentityKeys?.length
              ? { isRecheck: true }
              : {}),
            fixMarkedFindingIdentityKeys:
              landing?.fixMarkedFindingIdentityKeys ?? [],
          } satisfies VerifyResult,
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "verify",
          converged: true,
          isRecheck: true,
          fixMarkedFindingIdentityKeys:
            landing?.fixMarkedFindingIdentityKeys ?? [],
          threadsToResolve: ["100"],
        } satisfies VerifyResult,
      };
    }
    return super.dispatchWorker(spec, ctx, landing);
  }
}

class MissingCoderTagBackend extends ResumeBackend {
  override async runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
  ): Promise<StepOutput> {
    if (spec.id === "S2") {
      throw new Error(
        "realBackend: coder step stdout carried no <coder>…</coder> tag — the coder must emit its structured result in a <coder> tag.",
      );
    }
    return super.runStep(spec, worktree);
  }
}

// ─── AC: fresh run is unaffected (no residue) ────────────────────────────────

describe("fresh run (no residue) is unchanged (#255)", () => {
  it("findResumeState returns undefined → runs full S0→S8, cuts a fresh worktree", async () => {
    const backend = new ResumeBackend(); // no resumeState

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Full happy path executed (ADR 0030: gate + load + implement + review + classify + ship).
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
    // Fresh cut: prepareWorktree called once; cleanResidue never called.
    expect(backend.prepareWorktreeCount).toBe(1);
    expect(backend.cleanResidueCount).toBe(0);
    // No resumeSession on a fresh run.
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("findResumeState is consulted at the very start of the run", async () => {
    const backend = new ResumeBackend();

    await runOrchestrator({ issueNumber: 255, backend });

    // The resume check is the first Backend interaction (before the S0 gate).
    expect(backend.calls[0]).toBe("findResumeState(255)");
  });

  it("classifies missing coder tag errors as contract drift", async () => {
    const backend = new MissingCoderTagBackend();

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(result.stopSummary.reason).toBe("contract_drift");
  });
});

// ─── AC1 + AC2: crash-resume — branch/worktree exists, ledger stops at S2 ─────

describe("crash-resume: residue exists, ledger stops mid-run (#255 AC1/AC2, ADR 0030)", () => {
  /**
   * Crash scenario (ADR 0030): the prior run completed S0, S1, S2 (the build
   * worker committed) and then died before review. The ledger on disk therefore
   * ends at S2 with a committed coder output. Re-feeding the same issue must
   * reuse the worktree, clean the uncommitted residue, and continue from S3, the
   * route() successor of a committed S2.
   */
  function crashedAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
  }

  it("AC1: reuses the existing worktree (no re-cut) and preserves the scene", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // No fresh cut — the resident worktree is reused.
    expect(backend.prepareWorktreeCount).toBe(0);
    // #661 owner ruling: resume continues the worker scene; it never resets
    // or cleans uncommitted/partial worker output before re-entry.
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("AC2: continues from S3 (route successor of a committed S2) — does NOT re-run S0/S1/S2", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The committed S2 routes to a fresh reviewer; S2 itself is not re-dispatched.
    expect(backend.runStepIds).toEqual(["S3"]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.pushCount).toBe(1);
    // S0 gate / S1 load are NOT re-executed (no re-cut, no re-snapshot write).
    // #767 may re-fetch issue meta/body for Coder-Rec on the resume path.
    expect(backend.calls).not.toContain("prepareWorktree(255, main)");
    expect(backend.calls).not.toContain(
      `writeSnapshot(${WORKTREE.branch}, #255)`,
    );

    // The run completes from the resumed point.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("AC2: committed progress (prior ledger) is preserved in the result ledger", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The prior committed steps survive into the final ledger (not lost), and
    // the resumed steps are appended after them.
    const steps = result.stepLedger.map((e) => e.step);
    // Prior S0/S1/S2 + resumed S3/S4/S7/S8.
    expect(steps).toEqual(["S0", "S1", "S2", "S3", "S4", "S7", "S8"]);
    // The preserved S2 entry still carries its committed output.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });
  });

  it("recovers a landed S5 commit when stdout outcome parsing wrote S8(error)", async () => {
    const beforeFixHead = "a".repeat(40);
    const afterFixHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeFixHead },
        { ...entry("S1"), branchHEAD: beforeFixHead },
        {
          ...entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
          branchHEAD: beforeFixHead,
        },
        {
          ...entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
          branchHEAD: beforeFixHead,
        },
        { ...entry("S4"), branchHEAD: beforeFixHead },
        {
          step: "S5",
          sessionId: "session-s5-protocol-failed",
          prompt_hash: "hash-S5",
          branchHEAD: afterFixHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterFixHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S6");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S5",
      "S6",
      "S4",
      "S7",
      "S8",
    ]);
    const s5 = result.stepLedger.find((e) => e.step === "S5");
    expect(s5?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("recovers a landed S2 commit when stdout outcome parsing wrote S8(error)", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S3");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S7",
      "S8",
    ]);
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("recovers a real no-tag coder failure even when legacy stop summary classified it as infra", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-real-notag-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        {
          step: "S8",
          handoffStatus: "error",
          stopSummary: {
            reason: "infra_failure",
            summary:
              "realBackend: coder step stdout carried no <coder>…</coder> tag — the coder must emit its structured result in a <coder> tag.",
            repairHint: "inspect S2 and rerun after repairing the cause",
          },
          branchHEAD: afterBuildHead,
          sessionId: "session-s8",
          prompt_hash: "hash-S8",
          ts: "2026-07-02T00:00:01.000Z",
        },
      ],
    });
    backend.commitCountsBetween.set(`${beforeBuildHead}..${afterBuildHead}`, 2);

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S3");
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 2,
    });
  });

  it("recovers the real landed coder commit count from persisted HEADs", async () => {
    const beforeFixHead = "a".repeat(40);
    const afterFixHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeFixHead },
        { ...entry("S1"), branchHEAD: beforeFixHead },
        {
          ...entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
          branchHEAD: beforeFixHead,
        },
        {
          ...entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
          branchHEAD: beforeFixHead,
        },
        { ...entry("S4"), branchHEAD: beforeFixHead },
        {
          step: "S5",
          sessionId: "session-s5-protocol-failed",
          prompt_hash: "hash-S5",
          branchHEAD: afterFixHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterFixHead },
      ],
    });
    backend.commitCountsBetween.set(`${beforeFixHead}..${afterFixHead}`, 3);

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.calls).toContain(
      `countCommitsBetween(${beforeFixHead}, ${afterFixHead})`,
    );
    const s5 = result.stepLedger.find((e) => e.step === "S5");
    expect(s5?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 3,
    });
  });

  it("does not recover a landed coder protocol failure when the git count is not positive", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterBuildHead },
      ],
    });
    backend.commitCountsBetween.set(`${beforeBuildHead}..${afterBuildHead}`, 0);

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S8",
    ]);
  });

  it("recovers a landed SHA-256 coder commit while skipping intervening S8 heads", async () => {
    const beforeBuildHead = "a".repeat(64);
    const afterBuildHead = "b".repeat(64);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        { ...s8("error"), branchHEAD: afterBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-sha256-protocol-failed",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...coderProtocolFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S3");
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
  });

  it("does not recover unrelated terminal S8 errors even when HEAD advanced", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-unrelated-error",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        {
          ...s8("error"),
          branchHEAD: afterBuildHead,
          stopSummary: {
            reason: "contract_drift",
            summary: "coder output failed commit-truth reconciliation",
            repairHint: "Re-run the coder step or inspect the contract failure.",
          },
        },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S8",
    ]);
    expect(result.stopSummary?.summary).toBe(
      "coder output failed commit-truth reconciliation",
    );
  });

  it("does not recover malformed coder payload failures that merely mention the <coder> tag", async () => {
    const beforeBuildHead = "a".repeat(40);
    const afterBuildHead = "b".repeat(40);
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        { ...entry("S0"), branchHEAD: beforeBuildHead },
        { ...entry("S1"), branchHEAD: beforeBuildHead },
        {
          step: "S2",
          sessionId: "session-s2-malformed-payload",
          prompt_hash: "hash-S2",
          branchHEAD: afterBuildHead,
          ts: "2026-07-02T00:00:00.000Z",
        },
        { ...malformedCoderPayloadFailureS8(), branchHEAD: afterBuildHead },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 496, backend });

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S8",
    ]);
    expect(result.stopSummary?.summary).toContain("payload was malformed");
  });
});

describe("crash-resume: S4 replay preserves ADR0030 claimed-fixed adjudication", () => {
  function crashedAfterSecondEmptyStillActiveS6(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
      ],
    };
  }

  it("multi-round empty S6 still-active dispositions resume as no-progress, not silent closure", async () => {
    const backend = new ResumeBackend(crashedAfterSecondEmptyStillActiveS6());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.reason).toContain("review/fix loop made no progress");
    expect(backend.pushCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(result.stepLedger.map((e) => e.step).slice(-2)).toEqual(["S4", "S8"]);
    expect(backend.ledgerWrites.find((e) => e.step === "S8")).toMatchObject({
      handoffStatus: "escalate",
      escalationKind: "decision",
    });
  });
});

describe("#439 decision-escalate answer channel", () => {
  function decisionEscalatedAtS4(opts?: {
    answer?: PersistentLedgerEntry;
    escalationKind?: "decision" | "failure";
  }): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        entry("S4"),
        {
          ...s8("escalate"),
          escalationKind: opts?.escalationKind ?? "decision",
        },
        ...(opts?.answer !== undefined ? [opts.answer] : []),
      ],
    };
  }

  it("decision-escalate without an appended answer remains paused at escalate", async () => {
    const backend = new DispatchRecordingResumeBackend(decisionEscalatedAtS4());

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("decision-escalate with a malformed blank answer row remains paused", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({ answer: escalationAnswer("S4", "   ") }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("appended answer reopens the S4 decision escalation at S5 and injects the answer", async () => {
    const answer = escalationAnswer(
      "S4",
      "continue-same-class",
      "Human says keep fixing this same no-progress class.",
    );
    const scopedAnswer = {
      ...answer,
      source: "human",
      findingScope: { identityKeys: [CLAIMED_FIXED_KEY] },
    } as const;
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({ answer: scopedAnswer }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S4",
      answer: "continue-same-class",
      note: "Human says keep fixing this same no-progress class.",
      source: "human",
      findingScope: { identityKeys: [CLAIMED_FIXED_KEY] },
    });
    expect(result.stepLedger).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          event: "escalation_answered",
          forStep: "S4",
          answer: "continue-same-class",
        }),
      ]),
    );
  });

  it("turns repair-intent ledger write failures into a structured S8 error handoff", async () => {
    class RepairIntentWriteFailureBackend extends DispatchRecordingResumeBackend {
      async writeLedger(
        ledgerEntry: PersistentLedgerEntry,
        stateDir: string,
      ): Promise<void> {
        if (ledgerEntry.event === "runner_bookkeeping") {
          throw new Error("repair intent ledger write failed");
        }
        await super.writeLedger(ledgerEntry, stateDir);
      }
    }
    const backend = new RepairIntentWriteFailureBackend(decisionEscalatedAtS4());

    const result = await runOrchestrator({
      issueNumber: 439,
      backend,
      repairIntent: {
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        findingIdentityKey: CLAIMED_FIXED_KEY,
        source: "resume_input",
        ts: "2026-07-01T00:00:01.000Z",
      },
    });

    expect(result.status).toBe("error");
    expect(result.errorPackage).toMatchObject({
      failedStep: "S4",
      reason: expect.stringContaining("repair intent ledger write failed"),
    });
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.ledgerWrites.at(-1)).toMatchObject({
      step: "S8",
      handoffStatus: "error",
    });
  });

  it("failure-escalate remains terminal even if an answer row is appended", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({
        escalationKind: "failure",
        answer: escalationAnswer("S4", "try-anyway"),
      }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("unknown tagged escalationKind remains terminal even if an answer row is appended", async () => {
    const backend = new DispatchRecordingResumeBackend(
      decisionEscalatedAtS4({
        escalationKind: "maybe" as unknown as "decision",
        answer: escalationAnswer("S4", "try-anyway"),
      }),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("legacy untagged agent decision escalation without an appended answer remains paused", async () => {
    const backend = new ResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("escalate");
    expect(backend.resumeSessionCalls).toHaveLength(0);
    expect(backend.cleanResidueCount).toBe(0);
  });

  it("legacy untagged agent decision escalation reopens only after an appended answer", async () => {
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        escalationAnswer("S2", "continue-with-x-required"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S2",
      answer: "continue-with-x-required",
      source: "human",
    });
  });

  it.each(["human", "resume_input"] as const)(
    "legacy untagged agent decision escalation accepts %s answer rows",
    async (source) => {
      const backend = new DispatchRecordingResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: [
          entry("S0"),
          entry("S1"),
          entry(
            "S2",
            {
              kind: "coder",
              committed: false,
              commitsAdded: 0,
              escalate: {
                reason: "design ambiguity",
                diagnosis: "needs a human answer",
              },
            },
            "session-escalated-S2",
          ),
          s8("escalate"),
          { ...escalationAnswer("S2", "continue-with-x-required"), source },
        ],
      });

      const result = await runOrchestrator({ issueNumber: 439, backend });

      expect(result.status).toBe("success");
      expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    },
  );

  it("legacy untagged agent decision escalation accepts source-less legacy answer rows as human", async () => {
    const legacyAnswer = escalationAnswer("S2", "continue-with-x-required");
    const { source: _source, ...sourceLessAnswer } = legacyAnswer;
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs a human answer",
            },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        sourceLessAnswer,
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S2",
      answer: "continue-with-x-required",
      source: "human",
    });
  });

  it.each(["coordinator", "peripheral"] as const)(
    "legacy untagged agent decision escalation ignores %s answer rows",
    async (source) => {
      const backend = new DispatchRecordingResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: [
          entry("S0"),
          entry("S1"),
          entry(
            "S2",
            {
              kind: "coder",
              committed: false,
              commitsAdded: 0,
              escalate: {
                reason: "design ambiguity",
                diagnosis: "needs a human answer",
              },
            },
            "session-escalated-S2",
          ),
          s8("escalate"),
          { ...escalationAnswer("S2", "continue-with-x-required"), source },
        ],
      });

      const result = await runOrchestrator({ issueNumber: 439, backend });

      expect(result.status).toBe("escalate");
      expect(backend.resumeSessionCalls).toHaveLength(0);
      expect(backend.dispatchSpecs).toEqual([]);
    },
  );

  it("tagged agent decision escalation reopens without keeping superseded S2/S8 entries", async () => {
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: { reason: "design ambiguity", diagnosis: "needs a human answer" },
          },
          "session-escalated-S2",
        ),
        { ...s8("escalate"), escalationKind: "decision" },
        escalationAnswer("S2", "continue-with-x-required"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.resumeSessionCalls[0]).toEqual(["S2", "session-escalated-S2"]);
    expect(result.stepLedger.filter((e) => e.step === "S2")).toHaveLength(1);
    expect(result.stepLedger).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          step: "S8",
          handoffStatus: "escalate",
          escalationKind: "decision",
        }),
      ]),
    );
  });

  it("malformed answer event rows do not replay as S4 classifications", async () => {
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING] }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "still-active" },
          ],
        }),
        escalationAnswer("S4", "   "),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
  });
});

// ─── AC3 + AC4: escalate-resume — SAME machine, via resumeSession + sessionId ─

describe("escalate-resume: human answered, re-feed → resumeSession (#255 AC3/AC4)", () => {
  /**
   * Escalate scenario: the prior run escalated at S2 (coder hit a design-level
   * blocker). The ledger therefore ends with an S2 escalate entry and an S8
   * handoff(escalate). The human answers the blocker, then re-feeds the issue.
   *
   * The SAME machine resumes: read the ledger, reuse the worktree, and resume
   * the prior agent session via Sandcastle-native resumeSession (carrying the
   * recorded sessionId) — NOT a fresh sandbox.run from S0.
   *
   * After escalate, the resumed step is the escalated step itself (S2): the
   * human's answer lets the coder finish what it was stuck on, in the SAME
   * agent session (resumeSession, not a fresh run).
   */
  function escalatedAtS2(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs product decision on field X",
            },
          },
          "session-escalated-S2",
        ),
        entry("S8"),
        escalationAnswer("S2", "continue-after-human-answer"),
      ],
    };
  }

  it("AC3: resumes the escalated step via resumeSession (Sandcastle-native), not a fresh run", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The escalated step resumes through resumeSession — NOT a fresh runStep.
    expect(backend.resumeSessionCalls.length).toBeGreaterThan(0);
    // The very first dispatched step on resume is the escalated S2.
    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
    // The run continues to completion (human answer unblocked the coder).
    expect(result.status).toBe("success");
  });

  it("AC3: same machine — reuses worktree + preserves scene (no re-cut from S0)", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // Identical reuse/preserve behaviour as the crash-resume path (#661).
    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(0);
    // S0 gate / S1 load are NOT re-run (no re-cut / no snapshot write).
    // #767 may re-fetch issue meta/body for Coder-Rec on the resume path.
    expect(backend.calls).not.toContain("prepareWorktree(255, main)");
    expect(backend.calls).not.toContain(
      `writeSnapshot(${WORKTREE.branch}, #255)`,
    );
  });

  it("AC4: resume carries the ledger's recorded sessionId into resumeSession", async () => {
    const backend = new ResumeBackend(escalatedAtS2());

    await runOrchestrator({ issueNumber: 255, backend });

    // The sessionId handed to resumeSession is the one recorded in the ledger
    // for that step (resume reads disk, not in-memory LLM state).
    const [, sessionId] = backend.resumeSessionCalls[0]!;
    expect(sessionId).toBe("session-escalated-S2");
  });

  it("AC2: crash inside review-loop (ledger truncated at S10) resumes at S9 re-verify — prior S9/S10 skipped, run completes verify→S12→S11→S8 (F3)", async () => {
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      entry("S10", {
        kind: "fixer",
        committed: true,
        fixCommitSha: "fixsha1111111111111111111111111111111111",
      }),
      // truncated before fresh re-verify / S11; no S8 yet — S9 false → S10 is the
      // legal loop-back topology (not converged:true then fixer).
    ];
    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    const steps = result.stepLedger.map((e) => e.step);
    expect(steps).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S7",
      "S9", // fresh re-verify after truncated S9(false)→S10 loop-back
      "S9", // online_review_converged marker
      "S12",
      "S12",
      "S11",
      "S8",
    ]);
    // Prior S9/S10 were skipped on this resume; fresh re-verify at S9 then docRelease/post-merge cleanup
    const reviewLoopDispatched = backend.dispatchSpecs
      .filter((s) => ["S9", "S10", "S11", "S12"].includes(s.id))
      .map((s) => s.id);
    expect(reviewLoopDispatched).toEqual(["S9", "S12", "S11"]);
  });

  it("AC2 r7: crash after S9(converged:false) resumes S10 with reconstructed landing (#600 F1)", async () => {
    const stateDir = mkdtempSync(join(tmpdir(), "resume-snapshot-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
    ];
    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(1);
    const fixerIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S10");
    const fixerLanding = backend.dispatchLandings[fixerIdx];
    expect(fixerLanding?.onlineReviewSnapshot).toBeDefined();
    expect(fixerLanding?.fixMarkedFindingIdentityKeys).toEqual(["f:1"]);
    expect(fixerLanding?.fixMarkedFindingThreads).toEqual([
      { identityKey: "f:1", threadId: "100" },
    ]);
    expect(
      backend.dispatchContexts.find((_, i) => backend.dispatchSpecs[i]?.id === "S10")
        ?.onlineReviewRound,
    ).toBe(1);
  });

  it("pin r29: crash after retrigger-only marker resumes S9 with round (no fix SHA)", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      {
        step: "S10",
        event: "online_review_round_retrigger",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: retriggerTs,
      },
    ];
    expect(onlineReviewRoundFromLedger(prior)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(prior)).toBeUndefined();

    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(0);
    const resumedVerifyIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S9");
    expect(resumedVerifyIdx).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchContexts[resumedVerifyIdx]?.onlineReviewRound).toBe(2);
    expect(backend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
  });

  it("pin r30: crash after fix_committed only (before retrigger) resumes S9 not fixer", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      {
        step: "S10",
        event: "online_review_fix_committed",
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: fixTs,
      },
    ];
    expect(onlineReviewRoundFromLedger(prior)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(prior)).toBe(fixSha);

    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(0);
    const resumedVerifyIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S9");
    expect(resumedVerifyIdx).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchContexts[resumedVerifyIdx]?.onlineReviewRound).toBe(2);
    expect(backend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
  });

  it("#743 R5: single-slice legacy key-only recheck resume fails closed before merge", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-r5-key-only-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        // Old #743 ledger shape carried the authorized key but no pair binding.
        // Resume must fail closed rather than treating this stale row as mergeable.
        isRecheck: true,
        fixMarkedFindingIdentityKeys: ["f:1"],
      }),
      {
        step: "S10" as const,
        event: "online_review_fix_committed" as const,
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: "2026-07-08T12:30:00.000Z",
      },
    ];
    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.stopSummary).toEqual(
      expect.objectContaining({ reason: "contract_drift" }),
    );
    expect(backend.dispatchSpecs.filter((s) => s.id === "S11")).toHaveLength(0);
  });

  it("#743 R6: single-slice resume with empty last-S9 rebuild fails closed on bare converge", async () => {
    const fixSha = "fixsha4444444444444444444444444444444444";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-r6-empty-auth-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
      }),
      {
        step: "S10" as const,
        event: "online_review_fix_committed" as const,
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: "2026-07-08T12:30:00.000Z",
      },
    ];
    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.stopSummary).toEqual(
      expect.objectContaining({ reason: "contract_drift" }),
    );
    expect(backend.dispatchSpecs.filter((s) => s.id === "S11")).toHaveLength(0);
  });

  it("#743 R6: single-slice fix_committed authorization pairs survive key-only last-S9 resume", async () => {
    const fixSha = "fixsha5555555555555555555555555555555555";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-r6-marker-auth-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        // Key-only recheck shape — threads must come from the fix_committed marker.
        isRecheck: true,
        fixMarkedFindingIdentityKeys: ["f:1"],
      }),
      {
        step: "S10" as const,
        event: "online_review_fix_committed" as const,
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: ["f:1"],
        fixMarkedFindingThreads: [{ identityKey: "f:1", threadId: "100" }],
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: "2026-07-08T12:30:00.000Z",
      },
    ];
    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    const verifyIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S9");
    expect(verifyIdx).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchLandings[verifyIdx]?.fixMarkedFindingIdentityKeys).toEqual([
      "f:1",
    ]);
    expect(backend.dispatchLandings[verifyIdx]?.fixMarkedFindingThreads).toEqual([
      { identityKey: "f:1", threadId: "100" },
    ]);
  });

  it("#743 R6: single-slice continuous path persists (key,thread) on fix_committed", async () => {
    const livePr = "https://github.com/o/r/pull/255";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-r6-persist-auth-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: livePr,
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
    ];

    const pollSpy = vi
      .spyOn(onlineReviewLoop, "waitForBotQuiescence")
      .mockImplementation(async (_sh, input) => ({
        repo: "o/r",
        prNumber: 255,
        prUrl: input.prUrl,
        headOid: input.roundTrigger.headOid,
        roundTriggerUsed: input.roundTrigger,
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 0 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        threads: [],
        checkRuns: [],
        checkRunsEmptyMeans: "converged",
        totalFindingCount: 0,
        quiescent: true,
      }));
    const retriggerSpy = vi
      .spyOn(onlineReviewLoop, "retriggerBotsAndPoll")
      .mockImplementation(() => {
        throw new Error("retriggerBotsAndPoll: gh api failed");
      });

    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    vi.stubEnv("ORCHESTRATOR_REPO", "o/r");

    try {
      const backend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir,
        ledger: prior,
      });
      backend.verifyDispatchCount = 0;
      const origDispatch = backend.dispatchWorker.bind(backend);
      backend.dispatchWorker = async (spec, ctx, landing) => {
        if (spec.kind === "fixer") {
          backend.dispatchSpecs.push(spec);
          backend.dispatchContexts.push(ctx);
          backend.dispatchLandings.push(landing);
          return {
            kind: "completed",
            output: {
              kind: "fixer",
              committed: true,
              fixCommitSha: "fixsha1111111111111111111111111111111111",
            },
          };
        }
        return origDispatch(spec, ctx, landing);
      };

      await runOrchestrator({ issueNumber: 255, backend });

      const marker = backend.ledgerWrites.find(
        (e) => e.event === "online_review_fix_committed",
      );
      expect(marker).toMatchObject({
        fixMarkedFindingIdentityKeys: ["f:1"],
        fixMarkedFindingThreads: [{ identityKey: "f:1", threadId: "100" }],
      });
    } finally {
      retriggerSpy.mockRestore();
      pollSpy.mockRestore();
      vi.unstubAllEnvs();
    }
  });

  it("pin online R3 Codex P1: retrigger fail after fix_committed parks escalate (not S8 error)", async () => {
    const livePr = "https://github.com/o/r/pull/255";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-retrigger-fail-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: livePr,
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
    ];

    const pollSpy = vi
      .spyOn(onlineReviewLoop, "waitForBotQuiescence")
      .mockImplementation(async (_sh, input) => ({
        repo: "o/r",
        prNumber: 255,
        prUrl: input.prUrl,
        headOid: input.roundTrigger.headOid,
        roundTriggerUsed: input.roundTrigger,
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 0 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        threads: [],
        checkRuns: [],
        checkRunsEmptyMeans: "converged",
        totalFindingCount: 0,
        quiescent: true,
      }));
    const retriggerSpy = vi
      .spyOn(onlineReviewLoop, "retriggerBotsAndPoll")
      .mockImplementation(() => {
        throw new Error("retriggerBotsAndPoll: gh api failed");
      });

    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    vi.stubEnv("ORCHESTRATOR_REPO", "o/r");

    try {
      const backend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir,
        ledger: prior,
      });
      // First verify stays false so we go to fixer; fixer commits then retrigger throws.
      backend.verifyDispatchCount = 0;
      const origDispatch = backend.dispatchWorker.bind(backend);
      backend.dispatchWorker = async (spec, ctx, landing) => {
        if (spec.kind === "verify") {
          backend.verifyDispatchCount += 1;
          backend.dispatchSpecs.push(spec);
          backend.dispatchContexts.push(ctx);
          backend.dispatchLandings.push(landing);
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              findingDispositions: [
                { identityKey: "f:1", threadId: "100", action: "fix" },
              ],
            },
          };
        }
        if (spec.kind === "fixer") {
          backend.dispatchSpecs.push(spec);
          backend.dispatchContexts.push(ctx);
          backend.dispatchLandings.push(landing);
          return {
            kind: "completed",
            output: {
              kind: "fixer",
              committed: true,
              fixCommitSha: "fixsha1111111111111111111111111111111111",
            },
          };
        }
        return origDispatch(spec, ctx, landing);
      };

      const result = await runOrchestrator({ issueNumber: 255, backend });

      expect(result.status).toBe("escalate");
      expect(result.status).not.toBe("error");
      expect(result.stopSummary.summary).toMatch(
        /re-trigger failed after fix committed/i,
      );
      expect(
        backend.ledgerWrites.some((e) => e.event === "online_review_fix_committed"),
      ).toBe(true);
      // No terminal S8 error tag that would block fix-gap recovery
      expect(
        backend.ledgerWrites.some(
          (e) => e.step === "S8" && e.handoffStatus === "error",
        ),
      ).toBe(false);
      // S10 executable row present so re-feed resumes S10→S9 + gap recovery
      expect(
        result.stepLedger.some(
          (e) =>
            e.step === "S10" &&
            e.event === undefined &&
            e.output?.kind === "fixer",
        ),
      ).toBe(true);
      expect(retriggerSpy).toHaveBeenCalled();
    } finally {
      retriggerSpy.mockRestore();
      pollSpy.mockRestore();
      vi.unstubAllEnvs();
    }
  });

  it("pin r33: fix-gap resume posts retrigger + marker then polls; non-gap unchanged", async () => {
    const livePr = "https://github.com/o/r/pull/255";
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const ensuredRetriggerTs = "2026-07-08T13:30:00.000Z";
    const gapTrigger = buildRoundTrigger(fixSha, fixTs);
    const ensuredTrigger = buildRoundTrigger(fixSha, ensuredRetriggerTs);
    const persistedTrigger = buildRoundTrigger(fixSha, retriggerTs);
    const reviewLoopBase = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: livePr,
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
    ];

    const pollSpy = vi
      .spyOn(onlineReviewLoop, "waitForBotQuiescence")
      .mockImplementation(async (_sh, input) => ({
        repo: "o/r",
        prNumber: 255,
        prUrl: input.prUrl,
        headOid: input.roundTrigger.headOid,
        roundTriggerUsed: input.roundTrigger,
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 0 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        threads: [],
        checkRuns: [],
        checkRunsEmptyMeans: "converged",
        totalFindingCount: 0,
        quiescent: true,
      }));
    const ensureSpy = vi
      .spyOn(onlineReviewLoop, "ensureOnlineReviewRetriggerAfterFixGap")
      .mockImplementation(({ gapTrigger: gap }) => ({
        roundTrigger: buildRoundTrigger(gap.headOid, ensuredRetriggerTs),
        posted: true,
      }));

    const prevOffline = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    const prevRepo = process.env.ORCHESTRATOR_REPO;
    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    vi.stubEnv("ORCHESTRATOR_REPO", "o/r");

    let autoMergeSpy: ReturnType<typeof stubAutoMergeMergedForLiveReviewTests> | undefined;
    try {
      autoMergeSpy = stubAutoMergeMergedForLiveReviewTests(livePr, fixSha);
      const fixGapPrior: PersistentLedgerEntry[] = [
        ...reviewLoopBase,
        {
          step: "S10",
          event: "online_review_fix_committed",
          fixCommitSha: fixSha,
          onlineReviewRound: 1,
          sessionId: "session-prior",
          prompt_hash: "hash-S10",
          branchHEAD: fixSha,
          ts: fixTs,
        },
      ];
      expect(onlineReviewLoop.slicePendingRoundTriggerFromFixGap(fixGapPrior)).toEqual(
        gapTrigger,
      );

      const fixGapBackend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: fixGapPrior,
      });
      pollSpy.mockClear();
      const fixGapResult = await runOrchestrator({
        issueNumber: 255,
        backend: fixGapBackend,
      });

      expect(fixGapResult.status).toBe("success");
      expect(ensureSpy).toHaveBeenCalledTimes(1);
      expect(ensureSpy.mock.calls[0]![0].gapTrigger).toEqual(gapTrigger);
      expect(
        fixGapBackend.ledgerWrites.some(
          (e) => e.event === "online_review_round_retrigger",
        ),
      ).toBe(true);
      expect(pollSpy).toHaveBeenCalledTimes(1);
      expect(pollSpy.mock.calls[0]![1].roundTrigger).toEqual(ensuredTrigger);
      expect(pollSpy.mock.calls[0]![1].roundTrigger.triggeredAt).toBe(
        ensuredRetriggerTs,
      );
      expect(fixGapBackend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(
        0,
      );
      const fixGapVerifyIdx = fixGapBackend.dispatchSpecs.findIndex(
        (s) => s.id === "S9",
      );
      expect(fixGapVerifyIdx).toBeGreaterThanOrEqual(0);
      expect(
        fixGapBackend.dispatchContexts[fixGapVerifyIdx]?.onlineReviewRound,
      ).toBe(2);
      expect(fixGapBackend.verifyDispatchCount).toBeGreaterThanOrEqual(1);

      const retriggerPrior: PersistentLedgerEntry[] = [
        ...reviewLoopBase,
        {
          step: "S10",
          event: "online_review_round_retrigger",
          roundTriggerHeadOid: fixSha,
          roundTriggerAt: retriggerTs,
          onlineReviewRound: 2,
          sessionId: "session-prior",
          prompt_hash: "hash-S10",
          branchHEAD: fixSha,
          ts: retriggerTs,
        },
      ];
      expect(onlineReviewLoop.slicePendingRoundTriggerFromFixGap(retriggerPrior)).toBe(
        undefined,
      );

      const retriggerBackend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: retriggerPrior,
      });
      ensureSpy.mockClear();
      pollSpy.mockClear();
      const retriggerResult = await runOrchestrator({
        issueNumber: 255,
        backend: retriggerBackend,
      });

      expect(retriggerResult.status).toBe("success");
      expect(ensureSpy).not.toHaveBeenCalled();
      expect(pollSpy).toHaveBeenCalledTimes(1);
      expect(pollSpy.mock.calls[0]![1].roundTrigger).toEqual(persistedTrigger);
      expect(pollSpy.mock.calls[0]![1].roundTrigger.triggeredAt).toBe(retriggerTs);
      expect(
        retriggerBackend.dispatchSpecs.filter((s) => s.id === "S10"),
      ).toHaveLength(0);
      expect(retriggerBackend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
    } finally {
      ensureSpy.mockRestore();
      pollSpy.mockRestore();
      autoMergeSpy?.mockRestore();
      if (prevOffline === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prevOffline;
      }
      if (prevRepo === undefined) {
        delete process.env.ORCHESTRATOR_REPO;
      } else {
        process.env.ORCHESTRATOR_REPO = prevRepo;
      }
    }
  });

  it("pin r35: live happy-path ledger does not duplicate retrigger on resume", async () => {
    const livePr = "https://github.com/o/r/pull/255";
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const s10LaterTs = "2026-07-08T13:05:00.000Z";
    const persistedTrigger = buildRoundTrigger(fixSha, retriggerTs);
    const reviewLoopBase = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: livePr,
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
    ];
    const happyPrior: PersistentLedgerEntry[] = [
      ...reviewLoopBase,
      {
        step: "S10",
        event: "online_review_fix_committed",
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: fixTs,
      },
      {
        step: "S10",
        event: "online_review_round_retrigger",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: retriggerTs,
      },
      {
        step: "S10",
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fixsha1111111111111111111111111111111111",
        },
        branchHEAD: fixSha,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        ts: s10LaterTs,
      },
    ];
    expect(onlineReviewLoop.slicePendingRoundTriggerFromFixGap(happyPrior)).toBeUndefined();

    const pollSpy = vi
      .spyOn(onlineReviewLoop, "waitForBotQuiescence")
      .mockImplementation(async (_sh, input) => ({
        repo: "o/r",
        prNumber: 255,
        prUrl: input.prUrl,
        headOid: input.roundTrigger.headOid,
        roundTriggerUsed: input.roundTrigger,
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 0 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        threads: [],
        checkRuns: [],
        checkRunsEmptyMeans: "converged",
        totalFindingCount: 0,
        quiescent: true,
      }));
    const ensureSpy = vi.spyOn(
      onlineReviewLoop,
      "ensureOnlineReviewRetriggerAfterFixGap",
    );

    const prevOffline = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    const prevRepo = process.env.ORCHESTRATOR_REPO;
    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    vi.stubEnv("ORCHESTRATOR_REPO", "o/r");

    let autoMergeSpy: ReturnType<typeof stubAutoMergeMergedForLiveReviewTests> | undefined;
    try {
      autoMergeSpy = stubAutoMergeMergedForLiveReviewTests(livePr, fixSha);
      const backend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: happyPrior,
      });
      const result = await runOrchestrator({
        issueNumber: 255,
        backend,
      });

      expect(result.status).toBe("success");
      expect(ensureSpy).not.toHaveBeenCalled();
      expect(pollSpy).toHaveBeenCalledTimes(1);
      expect(pollSpy.mock.calls[0]![1].roundTrigger).toEqual(persistedTrigger);
      expect(pollSpy.mock.calls[0]![1].roundTrigger.triggeredAt).toBe(retriggerTs);
      expect(backend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(0);
      expect(backend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
    } finally {
      ensureSpy.mockRestore();
      pollSpy.mockRestore();
      autoMergeSpy?.mockRestore();
      if (prevOffline === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prevOffline;
      }
      if (prevRepo === undefined) {
        delete process.env.ORCHESTRATOR_REPO;
      } else {
        process.env.ORCHESTRATOR_REPO = prevRepo;
      }
    }
  });

  it("pin online R1 Codex P2: recheck S9 false after same-SHA markers resumes S10 fixer not S9", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const stateDir = mkdtempSync(join(tmpdir(), "resume-codex-p2-"));
    writeResumeOnlineReviewSnapshot(stateDir);
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      // recovery order: executable S10 then markers for the same fix SHA
      entry(
        "S10",
        {
          kind: "fixer",
          committed: true,
          fixCommitSha: fixSha,
        },
        "session-fix",
        fixSha,
      ),
      {
        step: "S10",
        event: "online_review_fix_committed",
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: fixTs,
      },
      {
        step: "S10",
        event: "online_review_round_retrigger",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: retriggerTs,
      },
      entry("S9", {
        kind: "verify",
        converged: false,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "f:2", threadId: "200", action: "fix" },
        ],
      }),
    ];

    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Must dispatch the pending fixer (S10), not steal back to a duplicate S9 verify
    expect(backend.dispatchSpecs.filter((s) => s.id === "S10").length).toBeGreaterThanOrEqual(1);
    const firstReviewLoop = backend.dispatchSpecs.findIndex(
      (s) => s.id === "S9" || s.id === "S10",
    );
    expect(firstReviewLoop).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchSpecs[firstReviewLoop]?.id).toBe("S10");
  });

  it("pin r28: crash after fix markers but before S10 row resumes S9 not fixer", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      {
        step: "S10",
        event: "online_review_round_retrigger",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: retriggerTs,
      },
      {
        step: "S10",
        event: "online_review_fix_committed",
        fixCommitSha: fixSha,
        onlineReviewRound: 1,
        sessionId: "session-prior",
        prompt_hash: "hash-S10",
        branchHEAD: fixSha,
        ts: fixTs,
      },
    ];
    expect(onlineReviewRoundFromLedger(prior)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(prior)).toBe(fixSha);

    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((s) => s.id === "S10")).toHaveLength(0);
    const resumedVerifyIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S9");
    expect(resumedVerifyIdx).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchContexts[resumedVerifyIdx]?.onlineReviewRound).toBe(2);
    expect(backend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
  });

  it("AC2 r7: crash after S10 resumes S9 with round+fix SHA from full ledger (#600 F1)", async () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      entry("S9", {
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      }),
      entry(
        "S10",
        {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fixsha1111111111111111111111111111111111",
        },
        "session-fix",
        fixSha,
      ),
    ];
    expect(onlineReviewRoundFromLedger(prior)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(prior)).toBe(fixSha);

    const backend = new ReviewLoopResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    const resumedVerifyIdx = backend.dispatchSpecs.findIndex((s) => s.id === "S9");
    expect(resumedVerifyIdx).toBeGreaterThanOrEqual(0);
    expect(backend.dispatchContexts[resumedVerifyIdx]?.onlineReviewRound).toBe(2);
    expect(backend.verifyDispatchCount).toBeGreaterThanOrEqual(1);
  });

  it("pin r26: crash after converged marker resumes into S12 (skips re-verify)", async () => {
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: "deadbeefcommitsha",
        onlineReviewRound: 1,
      },
    ];
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((s) => s.id === "S9")).toHaveLength(0);
    expect(backend.dispatchSpecs.map((s) => s.id)).toEqual(["S12", "S11"]);
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S7",
      "S9",
      "S12",
      "S12",
      "S11",
      "S8",
    ]);
  });

  it("#603 P1: crash after S12+pr_merged resumes S11 with durable marker (not truncated away)", async () => {
    const convergedHead = "deadbeefcommitsha";
    const prior: Array<PersistentLedgerEntry | PrMergedLedgerFixture> = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
        prHead: convergedHead,
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: convergedHead,
        onlineReviewRound: 1,
      },
      entry("S12", { kind: "docRelease", released: true }, "session-prior", convergedHead),
      ({
        step: "S12",
        event: "pr_merged",
        sessionId: "session-prior",
        prompt_hash: "hash-pr-merged",
        branchHEAD: convergedHead,
        ts: "2026-07-09T00:00:00.000Z",
        prUrl: "pr://slice/offline-255",
        prNumber: 255,
        remoteBranchName: "feat/orchestrator/issue-255",
        mergedHeadOid: convergedHead,
        prHead: convergedHead,
      } satisfies PrMergedLedgerFixture),
    ];
    const backend = new DispatchRecordingResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.map((s) => s.id)).toEqual(["S11"]);
    const cleanupLanding = backend.dispatchLandings[0]?.cleanupDispatch;
    expect(cleanupLanding).toMatchObject({
      prUrl: "pr://slice/offline-255",
      prNumber: 255,
      remoteBranchName: "feat/orchestrator/issue-255",
      mergedHeadOid: convergedHead,
      convergedHeadOid: convergedHead,
    });
    expect(result.errorPackage?.reason ?? "").not.toMatch(
      /post-merge cleanup requires a durable pr_merged/,
    );
  });

  it("#603 P2: non-terminal S11 parks resumable (re-feed re-dispatches S11, not S8 error)", async () => {
    const convergedHead = "deadbeefcommitsha";
    const prior: Array<PersistentLedgerEntry | PrMergedLedgerFixture> = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
        prHead: convergedHead,
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: convergedHead,
        onlineReviewRound: 1,
      },
      entry("S12", { kind: "docRelease", released: true }, "session-prior", convergedHead),
      ({
        step: "S12",
        event: "pr_merged",
        sessionId: "session-prior",
        prompt_hash: "hash-pr-merged",
        branchHEAD: convergedHead,
        ts: "2026-07-09T00:00:00.000Z",
        prUrl: "pr://slice/offline-255",
        prNumber: 255,
        remoteBranchName: "feat/orchestrator/issue-255",
        mergedHeadOid: convergedHead,
        prHead: convergedHead,
      } satisfies PrMergedLedgerFixture),
    ];

    class NonTerminalCleanupBackend extends DispatchRecordingResumeBackend {
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (spec.kind === "cleanup") {
          this.dispatchSpecs.push(spec);
          this.dispatchContexts.push(ctx);
          this.dispatchLandings.push(landing);
          return {
            kind: "completed",
            output: {
              kind: "cleanup",
              terminal: false,
              ok: false,
              skippedReasons: ["live_pr_fetch_failed:gh unavailable"],
              branchOutcome: "skipped_precondition",
            },
          };
        }
        return super.dispatchWorker(spec, ctx, landing);
      }
    }

    const backend = new NonTerminalCleanupBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const parked = await runOrchestrator({ issueNumber: 255, backend });
    expect(parked.status).toBe("escalate");
    expect(parked.status).not.toBe("error");
    expect(backend.dispatchSpecs.map((s) => s.id)).toEqual(["S11"]);
    expect(
      parked.stepLedger.some(
        (e) => e.step === "S8" && (e as { handoffStatus?: string }).handoffStatus === "error",
      ),
    ).toBe(false);

    // Re-feed from a parked ledger ending at non-terminal S11 — must re-dispatch
    // cleanup, not report a terminal S8(error) from route(S11, non-terminal).
    const parkedPrior: PersistentLedgerEntry[] = [
      ...prior,
      entry(
        "S11",
        {
          kind: "cleanup",
          terminal: false,
          ok: false,
          skippedReasons: ["live_pr_fetch_failed:gh unavailable"],
          branchOutcome: "skipped_precondition",
        },
        "session-prior",
        convergedHead,
      ),
    ];
    const resumeBackend = new NonTerminalCleanupBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: parkedPrior,
    });
    const refeed = await runOrchestrator({ issueNumber: 255, backend: resumeBackend });
    expect(refeed.status).toBe("escalate");
    expect(resumeBackend.dispatchSpecs.map((s) => s.id)).toEqual(["S11"]);
    expect(refeed.status).not.toBe("error");
  });

  it("#735 US13: S12 released:false parks resumable (re-feed re-dispatches S12, not sticky S8 error)", async () => {
    const convergedHead = "deadbeefcommitsha";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
        prHead: convergedHead,
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: convergedHead,
        onlineReviewRound: 1,
      },
    ];

    class FailedDocReleaseBackend extends DispatchRecordingResumeBackend {
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (spec.kind === "docRelease") {
          this.dispatchSpecs.push(spec);
          this.dispatchContexts.push(ctx);
          this.dispatchLandings.push(landing);
          return {
            kind: "completed",
            output: { kind: "docRelease", released: false },
          };
        }
        return super.dispatchWorker(spec, ctx, landing);
      }
    }

    const backend = new FailedDocReleaseBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });

    const parked = await runOrchestrator({ issueNumber: 255, backend });
    expect(parked.status).toBe("escalate");
    expect(parked.status).not.toBe("error");
    expect(backend.dispatchSpecs.map((s) => s.id)).toEqual(["S12"]);
    // CodeRabbit R3: in-memory S8 rows may omit handoffStatus — assert no S8 at all.
    expect(parked.stepLedger.some((e) => e.step === "S8")).toBe(false);
    expect(
      parked.stepLedger.some(
        (e) =>
          e.step === "S12" &&
          e.output?.kind === "docRelease" &&
          e.output.released === false,
      ),
    ).toBe(true);
    expect(parked.stopSummary?.repairHint ?? "").toMatch(/S12|doc-?release|文档发布/i);

    // Re-feed from a parked ledger ending at S12 released:false — must re-dispatch
    // docRelease, not report a sticky terminal S8(error) from route(S12, !released).
    const parkedPrior: PersistentLedgerEntry[] = [
      ...prior,
      entry(
        "S12",
        { kind: "docRelease", released: false },
        "session-prior",
        convergedHead,
      ),
    ];
    const resumeBackend = new FailedDocReleaseBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: parkedPrior,
    });
    const refeed = await runOrchestrator({ issueNumber: 255, backend: resumeBackend });
    expect(refeed.status).toBe("escalate");
    expect(refeed.status).not.toBe("error");
    expect(resumeBackend.dispatchSpecs.map((s) => s.id)).toEqual(["S12"]);
  });

  it("#740: S12 process-failure retry continues on current worktree (no cleanResidue)", async () => {
    // User override 2026-07-10 (#740, same philosophy as #600 / 21906adf):
    // single-slice S12 crash retry must NOT scoped-reset; continue AS-IS like
    // family docRelease. Resume still cleans once at breakpoint entry.
    const convergedHead = "deadbeefcommitsha";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: "pr://slice/offline-255",
        prHead: convergedHead,
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: convergedHead,
        onlineReviewRound: 1,
      },
    ];

    class FlakyDocReleaseBackend extends DispatchRecordingResumeBackend {
      docReleaseAttempts = 0;
      /** cleanResidue calls observed after the first docRelease dispatch. */
      cleanResidueDuringDocReleaseRetry = 0;
      override async cleanResidue(worktree: WorktreeHandle): Promise<void> {
        if (this.docReleaseAttempts >= 1) {
          this.cleanResidueDuringDocReleaseRetry += 1;
        }
        return super.cleanResidue(worktree);
      }
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (spec.kind === "docRelease") {
          this.dispatchSpecs.push(spec);
          this.dispatchContexts.push(ctx);
          this.dispatchLandings.push(landing);
          this.docReleaseAttempts += 1;
          if (this.docReleaseAttempts === 1) {
            return {
              kind: "failed",
              reason: "docRelease sandbox crash mid skill (no tag yet)",
            };
          }
          return {
            kind: "completed",
            output: { kind: "docRelease", released: true },
          };
        }
        return super.dispatchWorker(spec, ctx, landing);
      }
    }

    const backend = new FlakyDocReleaseBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: prior,
    });
    const result = await runOrchestrator({ issueNumber: 255, backend });
    expect(result.status).toBe("success");
    expect(backend.docReleaseAttempts).toBe(2);
    // #661: neither resume nor S12 mechanical retry may clean the scene.
    expect(backend.cleanResidueCount).toBe(0);
    expect(backend.cleanResidueDuringDocReleaseRetry).toBe(0);
  });

  it("#735 Codex P1: post-doc CI pending parks without sticky S8; re-feed retries auto-merge", async () => {
    const convergedHead = "deadbeefcommitsha";
    const livePr = "https://github.com/Akagilnc/ming-salvage-sim/pull/255";
    const prior: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", { kind: "reviewer", findings: [] }),
      entry("S4"),
      entry("S7", {
        kind: "ship",
        branch: WORKTREE.branch,
        status: "pr_opened",
        pr: livePr,
        prHead: convergedHead,
      }),
      {
        ...entry("S9", { kind: "verify", converged: true }),
        event: "online_review_converged",
        prUrl: livePr,
        prHead: convergedHead,
        onlineReviewRound: 1,
      },
    ];

    let mergeAttempts = 0;
    const mergeSpy = vi.spyOn(autoMerge, "runAutoMergeStage").mockImplementation(async () => {
      mergeAttempts += 1;
      if (mergeAttempts === 1) {
        return {
          ok: false,
          terminalState: "not_ready",
          stopSummary: {
            reason: "decision_gate_park",
            summary: "PR merge readiness blocked: ci_pending",
            repairHint:
              "wait for post-doc-release CI to finish, then re-feed to resume auto-merge",
          },
        };
      }
      return {
        ok: true,
        terminalState: "merged",
        record: {
          prUrl: livePr,
          prNumber: 255,
          remoteBranchName: WORKTREE.branch,
          mergedHeadOid: convergedHead,
          convergedHeadOid: convergedHead,
        },
      };
    });

    try {
      const backend = new DispatchRecordingResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: prior,
      });
      const parked = await runOrchestrator({ issueNumber: 255, backend });
      expect(parked.status).toBe("escalate");
      expect(parked.stopSummary?.summary ?? "").toMatch(/ci_pending/);
      // CodeRabbit R3: park must leave no S8 row (not just no tagged escalate).
      expect(parked.stepLedger.some((e) => e.step === "S8")).toBe(false);
      expect(
        parked.stepLedger.some(
          (e) =>
            e.step === "S12" &&
            e.output?.kind === "docRelease" &&
            e.output.released === true,
        ),
      ).toBe(true);

      // Re-feed from ledger ending at S12 released:true (no sticky S8) → S11 → merge
      const parkedPrior: PersistentLedgerEntry[] = [
        ...prior,
        entry(
          "S12",
          { kind: "docRelease", released: true },
          "session-prior",
          convergedHead,
        ),
      ];
      const resumeBackend = new DispatchRecordingResumeBackend({
        worktree: WORKTREE,
        stateDir: STATE_DIR,
        ledger: parkedPrior,
      });
      const refeed = await runOrchestrator({ issueNumber: 255, backend: resumeBackend });
      expect(refeed.status).toBe("success");
      expect(mergeAttempts).toBeGreaterThanOrEqual(2);
    } finally {
      mergeSpy.mockRestore();
    }
  });
});

// ─── C-1 (integ-cmr int-r1): S7 SHIP escalate-resume re-dispatches the ship worker
//
// ship.md promises ship `escalate` = a real blocker the human answers → the
// runner RE-OPENS S7. S7 is a runner-ACTION step, not an agent step, and ship
// outputs deliberately do NOT carry an `escalate` field (escalateOf returns
// undefined for them) — so the agent escalate-resume path (Case 2) cannot fire.
// Instead, a prior S7 escalate leaves the ledger ending with an UNTAGGED-output
// S7 entry + a trailing tagged S8(escalate). Recovery must recognise this pattern
// and RE-DISPATCH the S7 ship worker (re-run the push/ship), NOT report the prior
// escalate as a terminal status (which would leave the slice permanently stuck).

describe("S7 ship escalate-resume re-dispatches the ship worker (integ-cmr int-r1 C-1)", () => {
  /**
   * Prior run reached S7, the ship worker escalated (gstack-ship STOP/HITL). The
   * ledger ends with an S7 entry (no output — escalateTermination records the
   * failing step without one) and a trailing S8 tagged 'escalate'. The human has
   * answered the blocker and re-feeds the issue.
   */
  function escalatedAtS7(
    answer?: PersistentLedgerEntry,
    escalationKind?: "decision" | "failure",
  ): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7"), // failing step recorded without an output (escalateTermination)
        {
          ...s8("escalate"),
          ...(escalationKind !== undefined ? { escalationKind } : {}),
        },
        ...(answer !== undefined ? [answer] : []),
      ],
    };
  }

  it("S7 decision escalation without an appended answer remains paused", async () => {
    const backend = new ResumeBackend(escalatedAtS7());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("escalate");
    expect(backend.pushCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("answered S7 decision escalation re-opens: re-runs the ship worker instead of reporting the prior escalate", async () => {
    const backend = new ResumeBackend(
      escalatedAtS7(escalationAnswer("S7", "retry-ship-after-human-fix")),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.pushCount).toBe(1);
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.cleanResidueCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it.each(["human", "resume_input"] as const)(
    "S7 decision escalation accepts %s answer rows",
    async (source) => {
      const backend = new ResumeBackend(
        escalatedAtS7(
          { ...escalationAnswer("S7", "retry-ship-after-human-fix"), source },
          "decision",
        ),
      );

      const result = await runOrchestrator({ issueNumber: 255, backend });

      expect(result.status).toBe("success");
      expect(backend.pushCount).toBe(1);
      expect(backend.resumeSessionCalls).toHaveLength(0);
    },
  );

  it("S7 decision escalation accepts source-less legacy answer rows as human", async () => {
    const legacyAnswer = escalationAnswer("S7", "retry-ship-after-human-fix");
    const { source: _source, ...sourceLessAnswer } = legacyAnswer;
    const backend = new ResumeBackend(
      escalatedAtS7(sourceLessAnswer, "decision"),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it.each(["coordinator", "peripheral"] as const)(
    "S7 decision escalation ignores %s answer rows",
    async (source) => {
      const backend = new ResumeBackend(
        escalatedAtS7(
          { ...escalationAnswer("S7", "retry-ship-after-human-fix"), source },
          "decision",
        ),
      );

      const result = await runOrchestrator({ issueNumber: 255, backend });

      expect(result.status).toBe("escalate");
      expect(backend.pushCount).toBe(0);
      expect(backend.cleanResidueCount).toBe(0);
      expect(backend.resumeSessionCalls).toHaveLength(0);
    },
  );

  it("answered S7 re-opening drops the SUPERSEDED S7 entry — no double-S7 in the ledger (online review r1)", async () => {
    // The prior escalate left `[…, S7(failing), S8(escalate)]`. Re-opening S7
    // must truncate BOTH the trailing S8 boundary AND the superseded S7 entry;
    // otherwise the re-dispatch appends a SECOND S7 → two consecutive S7 entries
    // (3 bots). The final stepLedger must hold exactly ONE S7.
    const backend = new ResumeBackend(
      escalatedAtS7(escalationAnswer("S7", "retry-ship-after-human-fix")),
    );

    const result = await runOrchestrator({ issueNumber: 255, backend });

    const s7Entries = result.stepLedger.filter((e) => e.step === "S7");
    expect(s7Entries).toHaveLength(1);
    // The single surviving S7 is the FRESH re-dispatch (it carries the ship
    // payload, #336), not the output-less superseded escalate entry.
    expect(s7Entries[0]!.output).toBeDefined();
    // The full re-opened ledger has the clean happy-path shape (ADR 0030), no S7 twice.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("answered tagged S7 decision escalation drops the stale S7/S8 pause before re-dispatch", async () => {
    const backend = new ResumeBackend(
      escalatedAtS7(
        escalationAnswer("S7", "retry-ship-after-human-fix"),
        "decision",
      ),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    const s7Entries = result.stepLedger.filter((e) => e.step === "S7");
    expect(s7Entries).toHaveLength(1);
    expect(s7Entries[0]!.output).toBeDefined();
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
    expect(result.stepLedger).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          step: "S8",
          handoffStatus: "escalate",
          escalationKind: "decision",
        }),
      ]),
    );
  });

  it("answered S7 decision escalation passes the human answer to the ship worker", async () => {
    const answer = escalationAnswer(
      "S7",
      "retry-ship-after-human-fix",
      "Human resolved the delivery blocker; retry ship.",
    );
    const backend = new DispatchRecordingResumeBackend(
      escalatedAtS7(answer, "decision"),
    );

    const result = await runOrchestrator({ issueNumber: 439, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S7");
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S7",
      answer: "retry-ship-after-human-fix",
      note: "Human resolved the delivery blocker; retry ship.",
      source: "human",
    });
  });

  it("only answered S7-escalate re-opens: a prior answered S2-escalate S8 still resumes the agent step, not S7", async () => {
    // Guard: the new S7-reopen pattern must NOT swallow the existing agent
    // escalate-resume. A prior AGENT escalate (S2) still drives resumeSession on
    // S2 — it is not mistaken for an S7 re-open.
    const backend = new ResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry(
          "S2",
          {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: { reason: "r", diagnosis: "d" },
          },
          "session-escalated-S2",
        ),
        s8("escalate"),
        escalationAnswer("S2", "continue-agent-work"),
      ],
    });

    await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.resumeSessionCalls[0]![0]).toBe("S2");
  });
});

// ─── AC4: recovery decides next step from ledger, not memory ──────────────────

describe("recovery reads the ledger to decide next step (#255 AC4, ADR 0030)", () => {
  it("ledger stopping at a committed S2 resumes at the route successor S3, not S0", async () => {
    // Prior run got through S2 but died before review. Resume must route
    // S2→S3→S4→S7→S8 from the recorded output.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // S2 is not re-dispatched; the next fresh agent step is S3 reviewer.
    expect(backend.runStepIds).toEqual(["S3"]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // Pushed and succeeded — resumed purely from ledger truth.
    expect(backend.pushCount).toBe(1);
    expect(result.status).toBe("success");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("a ledger already ending at S8 (run already complete) does not re-cut or re-run agents", async () => {
    // Defensive: re-feeding a fully-completed issue must be a no-op resume —
    // no fresh worktree, no agent dispatch.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(backend.prepareWorktreeCount).toBe(0);
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
    // The completed run reports success against the resident branch.
    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
  });

  it("a legacy S8 entry without a handoffStatus tag is inferred from the prior step (untagged success → success)", async () => {
    // Older ledgers (written before the handoffStatus tag) end at a bare S8.
    // Recovery must infer the terminal status from the prior step (S7 → success)
    // rather than calling route() out of S8 (which throws).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        entry("S8"), // untagged legacy terminal entry
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(result.branch).toBe(WORKTREE.branch);
    expect(backend.runStepIds).toEqual([]);
  });
});

// ─── #255 review fix: a prior ERROR/ESCALATE must not masquerade as success ───

describe("re-feeding a terminated run reports its TRUE status (#255 review fix)", () => {
  it("prior ERROR handoff (tagged S8) re-fed → status error, NOT success", async () => {
    // A 0-commit coder failure terminated the prior run with an error handoff.
    // The S8 entry carries handoffStatus:'error'. Re-feeding must report error
    // (with an error package), never a hardcoded success.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
        s8("error"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    // No agent steps re-run; this is a pure status report.
    expect(backend.runStepIds).toEqual([]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
  });

  it("prior crash with last entry = coder committed:false (no S8 yet) → status error, NOT success", async () => {
    // The prior run crashed AFTER persisting the 0-commit coder entry but
    // BEFORE writing the S8 handoff. route(S2, committed:false) → error handoff.
    // Recovery must report error, not collapse it into success.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: false, commitsAdded: 0 }),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("error");
    expect(result.branch).toBeUndefined();
    expect(result.errorPackage).toBeDefined();
    expect(backend.runStepIds).toEqual([]);
  });

  it("prior crash with an advisory S2 commit count resumes through review", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", {
          kind: "coder",
          committed: true,
          commitsAdded: 0,
        } as unknown as StepOutput),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
  });

  it("a terminal-status resume does NOT run cleanResidue (a clean failure must not flip a finished run's status)", async () => {
    // Re-feeding a completed run is a pure status report — no worktree mutation.
    // cleanResidue must NOT be invoked, so a transient git failure during clean
    // can never turn an already-finished success into an error.
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S7"),
        s8("success"),
      ],
    };
    const backend = new ResumeBackend(resumeState);

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.cleanResidueCount).toBe(0);
  });
});
