/** Single-issue S9-S12 online-review resume contract; moved intact from #255/#600. */

import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { runOrchestrator } from "../../src/runner.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { route } from "../../src/route.js";
import { parseLedgerJsonl } from "../../src/realBackend.js";
import { buildRoundTrigger } from "../../src/evidenceAdmissibility.js";
import {
  ONLINE_REVIEW_SNAPSHOT_FILE,
  onlineReviewRoundFromLedger,
  lastOnlineReviewFixCommitShaFromLedger,
} from "../../src/onlineReviewLoop.js";
import * as onlineReviewLoop from "../../src/onlineReviewLoop.js";
import * as autoMerge from "../../src/autoMerge.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
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
} from "../../src/types.js";

import {
  PrMergedLedgerFixture,
  WORKTREE,
  STATE_DIR,
  CLAIMED_FIXED_FINDING,
  CLAIMED_FIXED_KEY,
  stubAutoMergeMergedForLiveReviewTests,
  entry,
  writeResumeOnlineReviewSnapshot,
  s8,
  coderProtocolFailureS8,
  malformedCoderPayloadFailureS8,
  escalationAnswer,
  ResumeBackend,
  DispatchRecordingResumeBackend,
  ReviewLoopResumeBackend,
  MissingCoderTagBackend,
} from "../helpers/resume-fixtures.js";

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
              escalationKind: "decision",
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

  it.each(["S9", "S10", "S12"] as const)(
    "answered %s decision park resumes its persisted worker session",
    async (decisionStep) => {
      const stateDir =
        decisionStep === "S10"
          ? mkdtempSync(join(tmpdir(), "resume-decision-park-"))
          : STATE_DIR;
      if (decisionStep === "S10") {
        writeResumeOnlineReviewSnapshot(stateDir);
      }
      const backend = new ReviewLoopResumeBackend({
        worktree: WORKTREE,
        stateDir,
        ledger: [
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
          entry(decisionStep, undefined, `session-parked-${decisionStep}`),
          { ...s8("escalate"), escalationKind: "decision" },
          escalationAnswer(decisionStep, "continue-after-human-answer"),
        ],
      });

      await runOrchestrator({ issueNumber: 255, backend });

      const resumed = backend.dispatchContexts.find(
        (ctx) => ctx.resumeSessionId === `session-parked-${decisionStep}`,
      );
      expect(resumed?.resumeSessionId).toBe(`session-parked-${decisionStep}`);
    },
  );

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

    // #877: fix-marked echo court demolished — bare converge on legacy key-only
    // recheck no longer contract_drift.
    expect(result.status).toBe("success");
    expect(result.stopSummary?.reason).not.toBe("contract_drift");
  });

  it("#877: single-slice resume with empty last-S9 rebuild admits bare converge", async () => {
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

    expect(result.status).toBe("success");
    expect(result.stopSummary?.reason).not.toBe("contract_drift");
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
