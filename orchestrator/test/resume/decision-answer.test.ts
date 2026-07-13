/** Decision-answer resume contract; moved intact from #255/#439. */

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

  it("#877: continue_fixing answer for historical no-progress park needs findings-count keys (disposition prose alone is not enough)", async () => {
    // Pre-#877: still-active disposition prose reopened priors so continue_fixing
    // matched CLAIMED_FIXED_KEY and reopened S5. Post-#877: empty findings[] means
    // replayed S4 has no blocking keys → continue_fixing cannot map → park stays.
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

    expect(result.status).toBe("escalate");
    expect(backend.dispatchSpecs).toEqual([]);
    expect(result.stopSummary?.summary).toMatch(/unanswered escalation/i);
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
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs a human answer",
              escalationKind: "decision",
            },
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
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs a human answer",
              escalationKind: "decision",
            },
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
                escalationKind: "decision",
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
              escalationKind: "decision",
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
                escalationKind: "decision",
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
            escalate: {
              reason: "design ambiguity",
              diagnosis: "needs a human answer",
              escalationKind: "decision",
            },
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

    // #877: still-active disposition prose does not reopen; findings=[] → S7.
    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs[0]?.id).toBe("S7");
  });
});

// ─── AC3 + AC4: escalate-resume — SAME machine, via resumeSession + sessionId ─

