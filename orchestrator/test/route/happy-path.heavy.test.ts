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

/**
 * Happy-path fake Backend: records every call in order, returns canned
 * outputs that drive the runner straight down
 * S0→S1→S2→S3→S4→S7→S8 (ADR 0030: per-slice review is a runner-visible
 * reviewer worker, and S4 is the visible classification boundary).
 *
 *   - S0/S1 read a compliant issue (rfa ∧ no sub-issues ∧ no open blocked_by)
 *     → gate passes.
 *   - S2 build worker → { committed: true, commitsAdded: 1 }.
 *   - S3 reviewer returns no blocking findings; S4 classifies the clean review
 *     and routes to S7. Blocking findings would instead enter S5/S6.
 *   - S7 locally hands the reviewed child branch off → S8(success)
 */
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

describe("runOrchestrator — happy path skeleton (ADR 0030)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("freezes the real runner telemetry range with held SHAs before deferred collection", async () => {
    const repo = mkdtempSync(join(tmpdir(), "runner-786-telemetry-"));
    try {
      execFileSync("git", ["init", "-q"], { cwd: repo });
      execFileSync("git", ["config", "user.email", "runner@example.test"], { cwd: repo });
      execFileSync("git", ["config", "user.name", "Runner Test"], { cwd: repo });
      writeFileSync(join(repo, "fixture.txt"), "before\n");
      execFileSync("git", ["add", "fixture.txt"], { cwd: repo });
      execFileSync("git", ["commit", "-qm", "base"], { cwd: repo });

      class TelemetryRoutingBackend extends HappyPathBackend {
        override readonly worktree: WorktreeHandle = {
          branch: "feat/orchestrator/issue-786",
          base: "main",
          path: repo,
        };

        override async runStep(spec: StepSpec): Promise<StepOutput> {
          if (spec.role === "coder") {
            writeFileSync(join(repo, "fixture.txt"), "after\n");
            execFileSync("git", ["commit", "-am", "coder commit", "-q"], { cwd: repo });
          }
          return await super.runStep(spec);
        }

        resolveTelemetryDir(): string {
          return join(repo, ".ledger-786");
        }
      }

      let releaseCollection!: () => void;
      const collectionGate = new Promise<void>((resolve) => { releaseCollection = resolve; });
      const schedule = vi.spyOn(telemetry, "scheduleCommitTelemetry")
        .mockImplementation(() => collectionGate);
      const backend = new TelemetryRoutingBackend();

      const result = await runOrchestrator({ issueNumber: 786, backend });

      expect(result.status).toBe("completed");
      expect(backend.runStepIds).toContain("S3");
      expect(schedule).toHaveBeenCalledOnce();
      expect(schedule.mock.calls[0]?.[0]).toMatchObject({
        repoPath: repo,
        worker: { stepId: "S2", modelSlug: "gpt-5.6-terra" },
        before: { kind: "held", oid: expect.stringMatching(/^[0-9a-f]{40}$/) },
        after: { kind: "held", oid: expect.stringMatching(/^[0-9a-f]{40}$/) },
      });
      expect(schedule.mock.calls[0]?.[0].before).not.toEqual(
        schedule.mock.calls[0]?.[0].after,
      );
      releaseCollection();
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });

});
