import { execFileSync } from "node:child_process";

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { runOrchestrator } from "../../src/runner.js";

import * as telemetry from "../../src/telemetry.js";

import type {
  Backend,
  FindingDisposition,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

class HappyPathBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  /** Ordered log of every Backend method invoked (the call timeline). */
  readonly calls: string[] = [];
  /** Ordered log of every agent step actually dispatched to a sandbox. */
  readonly runStepIds: string[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  /** Vitest mock call-order marker for sandbox dispatch. */
  readonly markRunStep = vi.fn();
  /** The single resident worktree handed out (asserts persistence/reuse). */
  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-247",
    base: "main",
    path: "/resident/worktrees/issue-247",
  };

  // #255 / #936: Scene discovery first (fresh-run defaults).
  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
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

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    return this.worktree;
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.markRunStep();
    this.calls.push(`runStep(${spec.id}:${spec.role}:${spec.promptFile})`);
    this.runStepIds.push(spec.id);
    if ((spec.role === "reviewer" || spec.role === "verify")) {
      return { kind: "judge", status: "converged" };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  // #249: writeLedger is part of the Backend seam; the happy-path fake is a
  // no-op stub so existing tests keep passing without asserting ledger details.
  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.ledgerWrites.push(entry);
  }
}

export {
  execFileSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  runOrchestrator,
  telemetry,
  Backend,
  FindingDisposition,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  HappyPathBackend,
};
