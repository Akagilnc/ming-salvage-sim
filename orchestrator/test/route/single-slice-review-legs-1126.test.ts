/**
 * #1126 — single-slice review legs are Runner-dispatched via the same #1094
 * panel-leg mechanism (scope is a parameter). Judge typed empty-continue is the
 * request; papers land back to the same judge session; judge worker fans out
 * zero nested CLIs.
 *
 * CR R2: Runner owns Standards + Spec as two same-model fresh workers (never one
 * worker that re-runs /code-review). Zero successful transports must park before
 * judge (same class as #1094), never M6 contract_drift.
 *
 * Seam: public runOrchestrator / Backend.dispatchWorker only.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  CODE_REVIEW_SPEC_LEG_PROMPT_FILE,
  CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE,
  isReviewPanelLegPromptFile,
} from "../../src/family/reviewPanelLegs.js";
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
  completeReviewPanelLegWorker,
  isReviewPanelLegWorker,
} from "../helpers/review-panel-leg-dispatch.js";
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
} from "../helpers/judge-fixtures.js";

const SLICE_BASE = "origin/codex/issue-1126-base";

function makeScratchWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "slice-legs-1126-"));
  return {
    branch: "feat/orchestrator/issue-1126",
    base: SLICE_BASE,
    path,
  };
}

type PanelLegMode = "ok" | "fail";

class SliceReviewLegBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  readonly legContexts: DispatchContext[] = [];
  private judgeVisits = 0;

  constructor(
    private readonly worktree: WorktreeHandle,
    private readonly panelLegMode: PanelLegMode = "ok",
  ) {}

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

    if (isReviewPanelLegWorker(spec)) {
      this.legContexts.push(ctx);
      if (this.panelLegMode === "fail") {
        // Completed but empty stdout → ADR 0141 absent paper (not process crash).
        return {
          kind: "completed",
          output: {
            kind: "reviewer",
            findingsCount: 0,
            findings: [],
            rawStdout: "",
          },
        };
      }
      return (
        completeReviewPanelLegWorker(
          spec,
          `SLICE_REVIEW_PAPER_1126:${spec.promptFile}`,
        ) ?? {
          kind: "failed",
          reason: "panel leg fixture missing",
        }
      );
    }

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
        return completedJudge(
          judgeContinue([], {
            fixPacketBody: "request fresh review legs after construction",
          }),
          sessionId,
        );
      }
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

function panelReviewers(specs: ReadonlyArray<WorkerSpec>): WorkerSpec[] {
  return specs.filter(
    (s) => s.kind === "reviewer" && isReviewPanelLegPromptFile(s.promptFile),
  );
}

describe("#1126 single-slice review legs via Runner (#1094 reuse)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_REPO", "test/repo");
  });

  it("Runner dispatches Standards+Spec as two same-model fresh legs; judge resumes with both papers", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const worktree = makeScratchWorktree();
    const backend = new SliceReviewLegBackend(worktree);
    const result = await runOrchestrator({ issueNumber: 1126, backend });

    expect(result.status).toBe("completed");

    const reviewers = panelReviewers(backend.specs);
    expect(reviewers).toHaveLength(2);
    expect(new Set(reviewers.map((r) => r.promptFile))).toEqual(
      new Set([
        CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE,
        CODE_REVIEW_SPEC_LEG_PROMPT_FILE,
      ]),
    );
    expect(reviewers[0]?.model).toBe(reviewers[1]?.model);
    for (const leg of reviewers) {
      expect(leg).toMatchObject({
        role: "reviewer",
        session: "fresh",
        contextRetention: "clean",
        soul: "READ-ONLY",
      });
      expect(leg.promptFile).not.toBe("cmr_panel_leg.md");
    }

    expect(backend.legContexts).toHaveLength(2);
    for (const ctx of backend.legContexts) {
      expect(ctx.worktree?.base).toBe(SLICE_BASE);
    }

    const judgeAfterLegs = backend.landings.find(
      (l) => (l?.panelLegTransports?.length ?? 0) > 0,
    );
    expect(judgeAfterLegs?.panelLegTransports).toHaveLength(2);
    const transportIds = (judgeAfterLegs?.panelLegTransports ?? []).map(
      (t) => t.slug,
    );
    expect(new Set(transportIds).size).toBe(2);

    const sequence = backend.specs.map((s) => `${s.id}:${s.kind}`);
    const s2 = sequence.indexOf("S2:coder");
    expect(s2).toBeGreaterThanOrEqual(0);
    expect(sequence.slice(s2 + 1, s2 + 5)).toEqual([
      "S3:verify",
      "S3:reviewer",
      "S3:reviewer",
      "S3:verify",
    ]);

    expect(
      backend.specs.filter((s) => s.id === "S3" && s.kind === "verify"),
    ).toHaveLength(2);
  });

  it("zero successful panel legs park before judge — never M6 contract_drift", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const backend = new SliceReviewLegBackend(makeScratchWorktree(), "fail");
    const result = await runOrchestrator({ issueNumber: 1126, backend });

    expect(result.status).toBe("parked");
    expect(result.stopSummary?.reason).not.toBe("contract_drift");
    expect(result.stopSummary?.summary ?? "").toMatch(/zero successful|panel leg/i);

    const reviewers = panelReviewers(backend.specs);
    expect(reviewers.length).toBeGreaterThanOrEqual(1);

    expect(
      backend.specs.filter((s) => s.id === "S3" && s.kind === "verify"),
    ).toHaveLength(1);
    expect(
      backend.landings.some((l) => (l?.panelLegTransports?.length ?? 0) > 0),
    ).toBe(false);
  });
});
