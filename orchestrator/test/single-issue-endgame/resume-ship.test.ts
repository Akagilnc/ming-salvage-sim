/** Single-issue S7 ship resume contract; moved intact from #255. */

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
      "S0", "S1", "S2", "S3", "S4", "S7", "S9", "S9", "S12", "S12", "S11", "S8",
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
      "S0", "S1", "S2", "S3", "S4", "S7", "S9", "S9", "S12", "S12", "S11", "S8",
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
            escalate: {
              reason: "r",
              diagnosis: "d",
              escalationKind: "decision",
            },
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

describe("S7 ship failure resume", () => {
  it("re-dispatches the idempotent ship worker without re-observing old delivery", async () => {
    class ShipResumeBackend extends DispatchRecordingResumeBackend {
    }

    const backend = new ShipResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [] }),
        entry("S4"),
        entry("S7", {
          kind: "ship",
          branch: WORKTREE.branch,
          status: "pushed",
        }),
        {
          ...s8("escalate"),
          escalationKind: "failure",
          stopSummary: {
            reason: "infra_failure",
            summary: "S7 worker process failed after retries",
            repairHint: "repair the worker process and rerun",
          },
        },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 891, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatchSpecs.filter((spec) => spec.id === "S7")).toHaveLength(1);
    expect(backend.ledgerWrites).toContainEqual(expect.objectContaining({
      step: "mechanical_redispatch_attempt",
      forStep: "S7",
      mechanicalRedispatchAttempt: 1,
    }));
  });

});

