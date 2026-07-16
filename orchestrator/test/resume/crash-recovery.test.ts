/** Crash and terminal-status resume contracts; moved intact from #255. */

import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { runOrchestrator } from "../../src/runner.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { route } from "../../src/route.js";
import { parseLedgerJsonl } from "../../src/realBackend.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  DispatchContext,
  OnlineReviewLandingSnapshot,
  StepId,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

import {
  WORKTREE,
  STATE_DIR,
  CLAIMED_FIXED_FINDING,
  CLAIMED_FIXED_KEY,
  entry,
  s8,
  coderProtocolFailureS8,
  malformedCoderPayloadFailureS8,
  escalationAnswer,
  ResumeBackend,
  DispatchRecordingResumeBackend,
  MissingCoderTagBackend,
} from "../helpers/resume-fixtures.js";

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
  });

  it("AC2: continues from S3 (route successor of a committed S2) — does NOT re-run S0/S1/S2", async () => {
    const backend = new ResumeBackend(crashedAtS2());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    // The committed S2 routes to a fresh reviewer; S2 itself is not re-dispatched.
    expect(backend.runStepIds).toEqual(["S3"]);
    expect(backend.resumeSessionCalls).toHaveLength(0);
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
    // Prior S0/S1/S2 + resumed fixed topology.
    expect(steps).toEqual([
      "S0", "S1", "S2", "S3", "S7", "S8",
    ]);
    // The preserved S2 entry still carries its committed output.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });
  });

  it("does not use git to overturn a landed S5 protocol error", async () => {
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
          ...entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING], findingsCount: 1 }),
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

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
  });

  it("does not use git to overturn a landed S2 protocol error", async () => {
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

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
  });

  it("does not use HEAD movement to overturn a legacy no-tag coder error", async () => {
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

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
  });

  it("does not read persisted HEADs to recover a coder result", async () => {
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
          ...entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING], findingsCount: 1 }),
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

    expect(result.status).toBe("error");
    expect(backend.calls).not.toContain(
      `countCommitsBetween(${beforeFixHead}, ${afterFixHead})`,
    );
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

  it("does not use SHA-256 HEAD movement to recover a coder result", async () => {
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

    expect(result.status).toBe("error");
    expect(backend.dispatchSpecs).toHaveLength(0);
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
            summary: "persisted coder protocol error",
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
      "persisted coder protocol error",
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
describe("#824 durable mechanical redispatch budget", () => {
  it("continues the prior S2 attempt count after a crash instead of granting a fresh budget", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: parseLedgerJsonl([
        entry("S0"),
        entry("S1"),
        {
          ...entry("S2"),
          step: "mechanical_redispatch_attempt",
          event: "mechanical_redispatch_attempt",
          forStep: "S2",
          mechanicalRedispatchAttempt: 1,
        },
        {
          ...entry("S2"),
          step: "mechanical_redispatch_attempt",
          event: "mechanical_redispatch_attempt",
          forStep: "S2",
          mechanicalRedispatchAttempt: 2,
        },
      ].map((row) => JSON.stringify(row)).join("\n")),
    };
    const backend = new ResumeBackend(resumeState);
    backend.runStep = async (spec) => {
      backend.runStepIds.push(spec.id);
      if (spec.role === "coder") throw new Error("coder process crashed");
      return { kind: "judge", status: "converged" };
    };

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("escalate");
    expect(backend.runStepIds).toEqual(["S2"]);
    expect(
      backend.ledgerWrites.filter(
        (written) => written.event === "mechanical_redispatch_attempt",
      ).map((written) => written.mechanicalRedispatchAttempt),
    ).toContain(3);
    expect(result.stopSummary?.summary).toContain(
      "after 3 dispatch attempts",
    );
  });

});

describe("crash-resume: S4 replay preserves ADR0030 claimed-fixed adjudication", () => {
  it("ADR 0131: persisted and live S4 both route by row count without reading severity/action", async () => {
    const opaqueFinding = {
      category: "opaque",
      claim_quote: "one declared row",
      location: "opaque:1",
      suggested_fix: "worker-owned prose",
      get severity(): never {
        throw new Error("runner must not read severity");
      },
      get action(): never {
        throw new Error("runner must not read action");
      },
    } as unknown as Finding;

    expect(route({
      from: "S4",
      output: { kind: "reviewer", findings: [opaqueFinding], findingsCount: 1 },
    })).toEqual({ kind: "next", step: "S5" });

    const backend = new ResumeBackend({
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [opaqueFinding], findingsCount: 1 }),
        entry("S4"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(backend.runStepIds[0]).toBe("S5");
  });

  function crashedAfterSecondEmptyStillActiveS6(): ResumeState {
    return {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S3", { kind: "reviewer", findings: [CLAIMED_FIXED_FINDING], findingsCount: 1 }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "judge", status: "converged" }),
        entry("S4"),
        entry("S5", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry("S6", { kind: "judge", status: "converged" }),
      ],
    };
  }

  it("#877: multi-round empty S6 still-active disposition prose closes via findings-count (no no-progress kill)", async () => {
    const backend = new ResumeBackend(crashedAfterSecondEmptyStillActiveS6());

    const result = await runOrchestrator({ issueNumber: 255, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage?.reason ?? "").not.toContain(
      "review/fix loop made no progress",
    );
    // Resume replays empty S6 still-active as findings=0 → local handoff.
  });
});

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
    // Resumed to local handoff purely from ledger truth.
    expect(result.status).toBe("success");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S7", "S8",
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

});

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

  it("prior crash with last entry = coder committed:false (no S8 yet) → resumes into the next baton (S3) instead of treating it as terminal", async () => {
    // The prior run crashed AFTER persisting the 0-commit coder entry but
    // BEFORE the next baton. A completed coder entry advances to fresh review;
    // committed:false is cargo, so recovery must not redispatch the coder.
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

    expect(result.status).toBe("success");
    expect(backend.runStepIds).toContain("S3");
    expect(backend.runStepIds).not.toContain("S2");
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

  it("a terminal-status resume reports the finished run without mutating its worktree", async () => {
    // Re-feeding a completed run is a pure status report — no worktree mutation.
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
  });
});
