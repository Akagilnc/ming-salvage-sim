import { execFileSync } from "node:child_process";

import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  cmrBlockingFindingsForRatifiedAssertionFlips,
  preexistingAssertionTouched,
  reviewFixAssertionSignal,
  reviewFixDecisionGate,
} from "../../src/reviewFixAssertionGate.js";

import { route } from "../../src/route.js";

import { runOrchestrator } from "../../src/runner.js";

import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";

import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  ReviewFixRefuseRecord,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-677",
  base: "main",
  path: "/resident/worktrees/issue-677",
};

function makeGitWorktreeWithPreexistingPin(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "runner-677-"));
  execFileSync("git", ["init", "-b", "main"], { cwd: path, stdio: "ignore" });
  mkdirSync(join(path, "test"), { recursive: true });
  mkdirSync(join(path, "src"), { recursive: true });
  writeFileSync(join(path, "README.md"), "base\n", "utf8");
  writeFileSync(
    join(path, "test", "gate.test.ts"),
    [
      "import { describe, expect, it } from 'vitest';",
      "describe('gate', () => {",
      "  it('malformed ship stays blocked', () => {",
      "    expect(result).toBe('blocked');",
      "  });",
      "});",
      "",
    ].join("\n"),
    "utf8",
  );
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
      "base with pin",
    ],
    { cwd: path, stdio: "ignore" },
  );
  execFileSync("git", ["checkout", "-b", WORKTREE.branch], {
    cwd: path,
    stdio: "ignore",
  });
  return { ...WORKTREE, path };
}

class FixLoopBackend implements Backend {
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
    private readonly opts: {
      readonly reviewerResults: ReadonlyArray<WorkerResult>;
      readonly coderOutputs?: ReadonlyArray<StepOutput>;
      readonly worktree?: WorktreeHandle;
      readonly resumeState?: ResumeState;
      readonly onCoderDispatch?: (
        attempt: number,
        worktree: WorktreeHandle,
      ) => void;
    },
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.opts.resumeState;
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
    return this.opts.worktree ?? WORKTREE;
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if ((spec.role === "reviewer" || spec.role === "verify")) return { kind: "judge", status: "converged" };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
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
    if (spec.kind === "coder") {
      const attempt = this.coderAttempts;
      this.opts.onCoderDispatch?.(attempt, ctx.worktree ?? WORKTREE);
      const scripted = this.opts.coderOutputs?.[this.coderAttempts];
      this.coderAttempts += 1;
      if (scripted !== undefined) {
        return { kind: "completed", output: scripted };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      const result = this.opts.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      return (
        result ?? { kind: "completed", output: { kind: "judge", status: "converged" } }
      );
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: (ctx.worktree ?? WORKTREE).branch,
        status: "pushed",
      },
    };
  }
}

export {
  execFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  tmpdir,
  join,
  describe,
  expect,
  it,
  cmrBlockingFindingsForRatifiedAssertionFlips,
  preexistingAssertionTouched,
  reviewFixAssertionSignal,
  reviewFixDecisionGate,
  route,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  ReviewFixRefuseRecord,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  WORKTREE,
  makeGitWorktreeWithPreexistingPin,
  FixLoopBackend,
};
