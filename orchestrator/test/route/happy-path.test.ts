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

  it("durably records an optional CMR leg dropped by single-slice route smoke", async () => {
    class DegradedRouteBackend extends HappyPathBackend {
      override async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async ({ slug }) => {
          if (slug === "agy") throw new Error("agy unavailable");
          return { cliVersion: "test" };
        });
      }
    }
    const backend = new DegradedRouteBackend();
    await runOrchestrator({ issueNumber: 247, backend });
    expect(backend.ledgerWrites).toContainEqual(expect.objectContaining({
      step: "S0",
      event: "route_degraded",
      droppedLeg: "agy",
      reason: "agy unavailable",
    }));
  });

  it("prints the resolved model route lineup before the first worker dispatch", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const backend = new HappyPathBackend();
    const info = vi.spyOn(console, "info").mockImplementation(() => {});

    await runOrchestrator({ issueNumber: 247, backend });

    expect(info).toHaveBeenCalledWith(
      [
        "[orchestrator] model route lineup",
        "route=normal",
        "coder=gpt-5.6-terra",
        "coderFix=gpt-5.6-terra",
        "ship=sonnet",
        "merger=sonnet",
        "cmrCompleteness=gpt-5.6-sol",
        "cmrCorrectness=gpt-5.6-sol",
        "verify=gpt-5.6-sol",
        "fixer=sonnet",
        "cleanup=sonnet",
        "landing=sonnet",
        "cmrReview=[codex:gpt-5.6-sol,claude:opus,agy:agy]",
      ].join("\n"),
    );
    expect(info.mock.invocationCallOrder[0]).toBeLessThan(
      backend.markRunStep.mock.invocationCallOrder[0]!,
    );
  });

  it("completed child hands off locally at S8(success)", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // Final state: success handoff pointing at the resident child branch.
    expect(result.status).toBe("completed");
    expect(result.branch).toBe("feat/orchestrator/issue-247");
    expect(result.stopSummary.reason).toBe("success");
    expect(result.stepLedger.at(-1)?.stopSummary?.reason).toBe("success");
    expect(backend.ledgerWrites.at(-1)?.stopSummary?.reason).toBe("success");

    // The child runner never pushes; family merge/ship owns remote delivery.

    // The step ledger records the runner's decisions in canonical order —
    // S3 is the judge establish seat; S4 mechanical classify is dissolved (#925).
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S7",
      "S8",
    ]);
  });

  it("dispatches implementation and review steps to the sandbox", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    // S4/S7/S8 are runner/handoff boundaries; S2 and S3 are agent workers.
    expect(backend.runStepIds).toEqual(["S2", "S3"]);
  });

  it("calls Backend actions in the canonical S0→S8 sequence", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    // #936: Scene discovery first; snapshot dual court deleted.
    expect(backend.calls).toEqual([
      "findResumeState(247)", // Scene Recovery discovery (ID-005)
      "fetchIssueMeta(247)", // S0 input_gate (lightweight metadata)
      "prepareWorktree(247, main)", // S1 resident worktree, base=main
      "runStep(S2:coder:coder_implement.md)", // S2 implementation
      "runStep(S3:verify:judge_station.md)", // S3 fresh full-diff review
      // S4 classify, S7 local handoff, S8 success are pure TS.
    ]);
  });

  it("the build output is {committed,commitsAdded} and a committed build routes to local handoff", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // The ledger captures the structured S2 output route() consumed.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });

    // A committed build plus clean independent review → local handoff succeeds.
    expect(result.status).toBe("completed");
  });

  it("only takes an issue number as input and uses versioned promptFiles (no ad-hoc prompts)", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    // The S2 coder and S3 reviewer steps dispatched fixed, versioned promptFiles
    // (recorded in the call log) — no step assembled an inline prompt string.
    const runCalls = backend.calls.filter((c) => c.startsWith("runStep("));
    expect(runCalls).toEqual([
      "runStep(S2:coder:coder_implement.md)",
      "runStep(S3:verify:judge_station.md)",
    ]);
  });

  it("commits accumulate on a single resident worktree/branch (base=main), not a throwaway sandbox", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // prepareWorktree was called exactly once → one resident worktree reused
    // across the whole run; its base is main; the pushed branch is that same
    // resident branch.
    const prepareCalls = backend.calls.filter((c) =>
      c.startsWith("prepareWorktree("),
    );
    expect(prepareCalls).toEqual(["prepareWorktree(247, main)"]);
    expect(result.branch).toBe(backend.worktree.branch);
  });

  it("does not turn rejected or wont_fix dispositions into accepted suppression metadata", async () => {
    const legacyRejected: FindingDisposition = {
      identityKey: "correctness|src/x.ts:1|old rejected review",
      status: "rejected",
      reason: "reviewer-only rejection without owner authority",
      severity: "medium",
    };
    class ResumeAfterS4Backend extends HappyPathBackend {
      // This fixture deliberately resumes after S4; keep the inherited broad return type.
      async findResumeState(): Promise<ResumeState | undefined> {
        return {
          worktree: this.worktree,
          stateDir: "/resident/worktrees/.ledger-247",
          ledger: [
            {
              step: "S0",
              sessionId: "prior",
              prompt_hash: "hash-S0",
              branchHEAD: "head",
              ts: "2026-07-02T00:00:00.000Z",
            },
            {
              step: "S3",
              sessionId: "prior",
              prompt_hash: "hash-S3",
              branchHEAD: "head",
              ts: "2026-07-02T00:00:01.000Z",
              output: { kind: "judge", status: "converged" },
            },
            {
              step: "S4",
              sessionId: "prior",
              prompt_hash: "hash-S4",
              branchHEAD: "head",
              ts: "2026-07-02T00:00:02.000Z",
              findingDispositions: [legacyRejected],
            },
          ],
        };
      }
    }
    const backend = new ResumeAfterS4Backend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    expect(result.status).toBe("completed");
    expect(result.stopSummary.metadata?.acceptedSuppressions).toBeUndefined();
    expect(backend.ledgerWrites.at(-1)?.stopSummary?.metadata?.acceptedSuppressions)
      .toBeUndefined();
  });
});
