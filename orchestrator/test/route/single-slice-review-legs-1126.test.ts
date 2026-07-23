/**
 * #1126 — single-slice review legs are Runner-dispatched via the same #1094
 * panel-leg mechanism (scope is a parameter). Judge typed empty-continue is the
 * request; papers land back to the same judge session; judge worker fans out
 * zero nested CLIs.
 *
 * Seam: public runOrchestrator / Backend.dispatchWorker only.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  CODE_REVIEW_LEG_PROMPT_FILE,
  isReviewPanelLegPromptFile,
} from "../../src/family/cmrPanelLegs.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completeCmrPanelLegWorker,
} from "../helpers/cmr-panel-leg-dispatch.js";
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
} from "../helpers/judge-fixtures.js";

function makeScratchWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "slice-legs-1126-"));
  return {
    branch: "feat/orchestrator/issue-1126",
    base: "main",
    path,
  };
}

class SliceReviewLegBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  private judgeVisits = 0;

  constructor(private readonly worktree: WorktreeHandle) {}

  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState() {
    return undefined;
  }
  async runStep(): Promise<never> {
    throw new Error("runStep called directly");
  }
  async resumeSession(): Promise<never> {
    throw new Error("resumeSession called directly");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeLedger(_entry: PersistentLedgerEntry): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.landings.push(landing);

    const openCourt = openCourtWorkerResultIfMatch(spec, OPEN_COURT_SESSION);
    if (openCourt !== undefined) return openCourt;

    const panelLeg = completeCmrPanelLegWorker(spec, "SLICE_REVIEW_PAPER_1126");
    if (panelLeg !== undefined) return panelLeg;

    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: {
          kind: "coder",
          beat: "construct",
          committed: true,
          commitsAdded: 1,
        },
        sessionId: "sess-coder-1126",
      };
    }

    if (spec.kind === "verify" || isJudgeSeatKind(spec)) {
      this.judgeVisits += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : OPEN_COURT_SESSION;
      if (this.judgeVisits === 1) {
        // Typed continue request: empty dispositions → Runner must fan out legs.
        return completedJudge(
          judgeContinue([], {
            fixPacketBody: "request fresh review legs after construction",
          }),
          sessionId,
        );
      }
      // Second visit must carry landed paper and resume the same session.
      expect(landing?.panelLegTransports?.length ?? 0).toBeGreaterThan(0);
      expect(ctx.resumeSessionId).toBe(OPEN_COURT_SESSION);
      return completedJudge(judgeConverged(), sessionId);
    }

    throw new Error(`unexpected worker ${spec.id}:${spec.kind}`);
  }
}

function isJudgeSeatKind(spec: WorkerSpec): boolean {
  return spec.id === "S3" || spec.id === "S6";
}

describe("#1126 single-slice review legs via Runner (#1094 reuse)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_REPO", "test/repo");
  });

  it("construct continue requests fresh legs; Runner dispatches; same judge resumes with paper", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const backend = new SliceReviewLegBackend(makeScratchWorktree());
    const result = await runOrchestrator({ issueNumber: 1126, backend });

    expect(result.status).toBe("completed");

    const sequence = backend.specs.map((s) => `${s.id}:${s.kind}`);
    const s2 = sequence.indexOf("S2:coder");
    expect(s2).toBeGreaterThanOrEqual(0);
    expect(sequence.slice(s2 + 1, s2 + 4)).toEqual([
      "S3:verify",
      "S3:reviewer",
      "S3:verify",
    ]);

    const leg = backend.specs.find(
      (s) => s.kind === "reviewer" && isReviewPanelLegPromptFile(s.promptFile),
    );
    expect(leg).toMatchObject({
      role: "reviewer",
      session: "fresh",
      contextRetention: "clean",
      // #1126 CR R1: single-slice must get per-slice /code-review task, not Family CMR.
      promptFile: CODE_REVIEW_LEG_PROMPT_FILE,
      soul: "READ-ONLY",
    });
    expect(leg?.promptFile).not.toBe("cmr_panel_leg.md");

    const judgeSpecs = backend.specs.filter(
      (s) => s.id === "S3" && s.kind === "verify",
    );
    expect(judgeSpecs).toHaveLength(2);
    // Judge worker itself never appears as a nested CLI fan-out owner —
    // only Runner-dispatched first-class workers show up on this seam.
    expect(
      backend.specs.filter((s) => s.kind === "reviewer"),
    ).toHaveLength(1);
  });
});
