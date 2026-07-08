/**
 * Single-slice runner family-mode adaptations (ADR 0022 decision 2 / 6, #293).
 *
 * A child slice in a family run reuses the EXACT single-slice S0–S8 runner, with
 * THREE family-mode differences carried via the optional `family` context on
 * RunInput (the RunnerOptions seam, ADR 0022 decision 2):
 *
 *   1. base = the FAMILY base (not "main") → prepareWorktree gets the family base
 *      (ADR 0022 decision 7: children cut from the local family base).
 *   2. S7 push = a LOCAL NO-OP → backend.push is NOT called (ADR 0022 decision 2:
 *      shared-clone concurrent push would clash on .git/refs/remotes; only the
 *      family base PRs once at the end). The run still reaches S8 success.
 *   3. (dec.6③, ledger口径) — NOT yet wired in #293. ADR 0022 decision 6③ says a
 *      child's OWN single-slice S0 `blocked_by`-closed check SHOULD become the
 *      family ledger-merged predicate in family mode. #293 does NOT replace it:
 *      runOrchestrator's S0 gate still throws on a non-empty `meta.openBlockedBy`
 *      (from GitHub), unchanged. This is sound for #293 ONLY because its thinnest
 *      wave is strictly all-unblocked children (every `blockedBy` is `[]` AND
 *      every fake's `openBlockedBy` is `[]`), so the gate's blocked_by branch is
 *      never reached. The ledger-merged S0 substitution is deferred to #294 (where
 *      a real blocked child appears); here we pin only the base + no-op-push
 *      adaptations. (See spine.test.ts: even the "11 blocked_by 10" commander case
 *      keeps the fake's `openBlockedBy:[]`, so no #293 test trips the real gate.)
 *
 * Regression guard: a run with NO `family` context behaves EXACTLY as before
 * (base=main, push called) — the existing 404 tests must not break.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

/** A fake that records the base passed to prepareWorktree + push invocations. */
class FamilyModeBackend implements Backend {
  readonly calls: string[] = [];
  prepareBase: string | undefined;
  pushCount = 0;

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareBase = base;
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

describe("runner family-mode adaptations (#293)", () => {
  it("cuts the child worktree from the FAMILY base, not main", async () => {
    const backend = new FamilyModeBackend();
    await runOrchestrator({
      issueNumber: 294,
      backend,
      family: { parentIssue: 293, familyBase: "family/293-base", noPush: true },
    });
    expect(backend.prepareBase).toBe("family/293-base");
    expect(backend.calls).toContain("prepareWorktree(294, family/293-base)");
  });

  it("S7 push is a LOCAL NO-OP in family mode (push never called), still reaches success", async () => {
    const backend = new FamilyModeBackend();
    const result = await runOrchestrator({
      issueNumber: 294,
      backend,
      family: { parentIssue: 293, familyBase: "family/293-base", noPush: true },
    });
    expect(result.status).toBe("success");
    expect(result.branch).toBe("feat/child-294");
    // Decision 2: the child does NOT push remotely; push is never called.
    expect(backend.pushCount).toBe(0);
    expect(backend.calls.some((c) => c.startsWith("push("))).toBe(false);
    // It still ran the full S0→S8 sequence (S7 just no-ops). ADR 0030 keeps the
    // reviewer and classification boundaries visible before the local ship step.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  it("REGRESSION: a run with no family context still pushes from base=main", async () => {
    const backend = new FamilyModeBackend();
    const result = await runOrchestrator({ issueNumber: 294, backend });
    expect(result.status).toBe("success");
    expect(backend.prepareBase).toBe("main");
    expect(backend.pushCount).toBe(1);
  });
});
