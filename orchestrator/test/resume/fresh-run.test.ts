/** Fresh-run resume contract; moved intact from #255. */

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

describe("fresh run (no residue) is unchanged (#255)", () => {
  it("findResumeState returns undefined → runs the full fixed topology, cuts a fresh worktree", async () => {
    const backend = new ResumeBackend(); // no resumeState

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    // Full happy path executed (ADR 0030: gate + load + implement + review + classify + ship).
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S9", "S9", "S12", "S12", "S11", "S8",
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

    expect(result.status).toBe("escalate");
    expect(result.stopSummary.reason).toBe("infra_failure");
  });
});

// ─── AC1 + AC2: crash-resume — branch/worktree exists, ledger stops at S2 ─────

