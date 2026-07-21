import { describe, expect, it } from "vitest";

import { execFileSync } from "node:child_process";

import { mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { legacyDispatchWorker } from "../../src/dispatchWorker.js";

import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";

import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";

import { findingIdentityKey } from "../../src/findings.js";

import { route } from "../../src/route.js";

import { runOrchestrator } from "../../src/runner.js";

import { openCourtWorkerResultIfMatch } from "../helpers/judge-fixtures.js";

import type {
  Backend,
  DispatchContext,
  Finding,
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

type PersistentLedgerFixture = Omit<
  PersistentLedgerEntry,
  "sessionId" | "prompt_hash" | "branchHEAD" | "ts"
> & Partial<Pick<PersistentLedgerEntry, "sessionId" | "prompt_hash" | "branchHEAD" | "ts">>;

type ResumeStateFixture = Omit<ResumeState, "ledger"> & {
  readonly ledger: ReadonlyArray<PersistentLedgerFixture>;
};

function materializeResumeState(fixture: ResumeStateFixture): ResumeState {
  return {
    ...fixture,
    ledger: fixture.ledger.map((entry) => ({
      ...entry,
      sessionId: entry.sessionId ?? "fixture-session",
      prompt_hash: entry.prompt_hash ?? "fixture-prompt",
      branchHEAD: entry.branchHEAD ?? "fixture-head",
      ts: entry.ts ?? "2026-07-01T00:00:00.000Z",
    })),
  };
}

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-369",
  base: "main",
  path: "/resident/worktrees/issue-369",
};

function makeGitWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "runner-progress-"));
  execFileSync("git", ["init", "-b", "main"], {
    cwd: path,
    stdio: "ignore",
  });
  writeFileSync(join(path, "README.md"), "base\n", "utf8");
  execFileSync("git", ["add", "."], { cwd: path, stdio: "ignore" });
  execFileSync(
    "git",
    [
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.com",
      "commit",
      "-m",
      "base",
    ],
    { cwd: path, stdio: "ignore" },
  );
  execFileSync("git", ["checkout", "-b", WORKTREE.branch], {
    cwd: path,
    stdio: "ignore",
  });
  return { ...WORKTREE, path };
}

class RetryReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;
  coderAttempts = 0;

  constructor(
    private readonly reviewerResults: ReadonlyArray<WorkerResult>,
    private readonly resumeState?: ResumeStateFixture,
    private readonly coderOutputs: ReadonlyArray<StepOutput> = [],
    private readonly worktree: WorktreeHandle = WORKTREE,
    private readonly onCoderDispatch?: (
      attempt: number,
      worktree: WorktreeHandle,
    ) => void,
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.resumeState && materializeResumeState(this.resumeState);
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
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
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if ((spec.role === "reviewer" || spec.role === "verify")) return { kind: "judge", status: "converged" };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);
    // #1081: open-court birth does not consume judge script queue.
    const openCourt = openCourtWorkerResultIfMatch(spec);
    if (openCourt !== undefined) return openCourt;
    if (spec.kind === "coder" && spec.id === "S5") {
      const attempt = this.coderAttempts;
      const scripted = this.coderOutputs[this.coderAttempts];
      this.coderAttempts += 1;
      this.onCoderDispatch?.(attempt, this.worktree);
      if (scripted !== undefined) {
        return { kind: "completed", output: scripted };
      }
    }
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      const result = this.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      // Prefer resume session when provided so ledger proves same judge.
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : undefined;
      if (result !== undefined) {
        return sessionId !== undefined && result.kind === "completed"
          ? { ...result, sessionId: result.sessionId ?? sessionId }
          : result;
      }
      return {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
        ...(sessionId !== undefined ? { sessionId } : {}),
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

export {
  describe,
  expect,
  it,
  execFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  writeFileSync,
  tmpdir,
  join,
  legacyDispatchWorker,
  skeletonReviewLoopWorkerResult,
  MAX_DISPATCH_ATTEMPTS,
  findingIdentityKey,
  route,
  runOrchestrator,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  PersistentLedgerFixture,
  ResumeStateFixture,
  materializeResumeState,
  WORKTREE,
  makeGitWorktree,
  RetryReviewBackend,
};
