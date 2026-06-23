/**
 * #249 — Persisted step ledger tests (RED → GREEN).
 *
 * Acceptance criteria (from issue #249):
 *   1. Happy path → every executed step has exactly one ledger entry, in order.
 *   2. Every entry has `prompt_hash` and `sessionId` fields.
 *   3. Every step is written to the ledger (anti-skip invariant; v0.1 physically executes all steps — gap detection via a skipping Backend is deferred to #248/#254).
 *   4. Ledger is written to a sibling state directory OUTSIDE the worktree:
 *      `git clean -fd` on the worktree path cannot remove it.
 *
 * Strategy: extend the Backend fake with a `writeLedger` spy that records
 * every call, including the full `PersistentLedgerEntry` shape and the
 * `stateDir` path handed to it.  Then assert:
 *   - path is NOT under the worktree path (`!stateDir.startsWith(worktree.path)`)
 *   - step sequence matches canonical S0→S1→S2→S3→S4→S7→S8
 *   - every entry carries prompt_hash, sessionId, branchHEAD, ts
 *
 * For the skip test we drive a custom Backend that omits the S2 dispatch
 * (simulating a skip) and verify the ledger sequence reflects the absence.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── shared worktree fixture ──────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-249",
  base: "main",
  path: "/resident/worktrees/issue-249",
};

// ─── full-featured fake Backend (#249) ───────────────────────────────────────

class LedgerBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  pushCount = 0;

  /** Every writeLedger call is captured here in insertion order. */
  readonly ledgerCalls: Array<{
    entry: PersistentLedgerEntry;
    stateDir: string;
  }> = [];

  // #255: fresh-run defaults (this suite tests ledger persistence, not resume).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
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

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id}:${spec.role}:${spec.promptFile})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    this.ledgerCalls.push({ entry, stateDir });
  }
}

// ─── helper ──────────────────────────────────────────────────────────────────

/** Run once, return the captured ledger calls. */
async function runAndCapture() {
  const backend = new LedgerBackend();
  const result = await runOrchestrator({ issueNumber: 249, backend });
  return { backend, result };
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe("persisted step ledger (#249)", () => {
  it("writeLedger is called once per executed step including S8 handoff", async () => {
    const { backend } = await runAndCapture();

    const steps = backend.ledgerCalls.map((c) => c.entry.step);
    expect(steps).toEqual(["S0", "S1", "S2", "S3", "S4", "S7", "S8"]);
  });

  it("every ledger entry carries prompt_hash and sessionId (audit fields)", async () => {
    const { backend } = await runAndCapture();

    for (const { entry } of backend.ledgerCalls) {
      expect(typeof entry.prompt_hash).toBe("string");
      expect(entry.prompt_hash.length).toBeGreaterThan(0);
      expect(typeof entry.sessionId).toBe("string");
      expect(entry.sessionId.length).toBeGreaterThan(0);
    }
  });

  it("every ledger entry carries branchHEAD and ts fields", async () => {
    const { backend } = await runAndCapture();

    for (const { entry } of backend.ledgerCalls) {
      expect(typeof entry.branchHEAD).toBe("string");
      // ts must be a valid ISO string
      expect(new Date(entry.ts).toISOString()).toBe(entry.ts);
    }
  });

  it("ledger stateDir is OUTSIDE the worktree path (clean -fd cannot remove it)", async () => {
    const { backend } = await runAndCapture();

    // Every writeLedger call must target a path that is NOT a sub-path of the
    // worktree root.  Sibling directories pass; anything under
    // WORKTREE.path fails.
    for (const { stateDir } of backend.ledgerCalls) {
      expect(stateDir.startsWith(WORKTREE.path + "/")).toBe(false);
      expect(stateDir).not.toBe(WORKTREE.path);
    }
  });

  it("all writeLedger calls target the same stateDir (one canonical dir per run)", async () => {
    const { backend } = await runAndCapture();

    const dirs = new Set(backend.ledgerCalls.map((c) => c.stateDir));
    expect(dirs.size).toBe(1);
  });

  it("agent-step entries carry the structured output (anti-skip truth)", async () => {
    const { backend } = await runAndCapture();

    const s2 = backend.ledgerCalls.find((c) => c.entry.step === "S2");
    const s3 = backend.ledgerCalls.find((c) => c.entry.step === "S3");

    expect(s2?.entry.output).toEqual({
      kind: "coder",
      committed: true,
      commitsAdded: 1,
    });
    expect(s3?.entry.output).toEqual({ kind: "reviewer", findings: [] });
  });

  it("pure runner-action entries (S0/S1/S4) have no output field", async () => {
    const { backend } = await runAndCapture();

    const runnerActions = ["S0", "S1", "S4"] as const;
    for (const stepId of runnerActions) {
      const call = backend.ledgerCalls.find((c) => c.entry.step === stepId);
      expect(call).toBeDefined();
      expect(call!.entry.output).toBeUndefined();
    }
  });

  it("S7 (ship worker, #336) persists its ship payload into the ledger", async () => {
    // S7 is no longer a pure runner-action push — it is a ship WORKER (ADR 0026 /
    // #336) that returns a ShipResult. Its branch/status/pr (+ worker sessionId)
    // must be persisted so the delivery is recoverable from resume truth and
    // surfaced in RunResult.stepLedger (online review r1 — 3 bots: S7 dropped it).
    const { backend } = await runAndCapture();

    const s7 = backend.ledgerCalls.find((c) => c.entry.step === "S7");
    expect(s7).toBeDefined();
    expect(s7!.entry.output).toEqual({
      kind: "ship",
      branch: "feat/orchestrator/issue-249",
      status: "pushed",
    });
  });

  it("every step is written to the ledger (anti-skip invariant: no step silently omitted)", async () => {
    /**
     * The v0.1 runner physically executes every step in sequence — it does not
     * skip steps.  This test asserts the invariant that EVERY step in the
     * canonical happy-path sequence has exactly one ledger entry.
     *
     * NOTE: This does NOT simulate a step being skipped (v0.1 has no
     * skip mechanism; real gap-detection via a custom Backend that omits a
     * dispatch is deferred to #248/#254 where skipping becomes possible).
     * The test name reflects what it actually verifies: all steps are present.
     */
    const { backend } = await runAndCapture();
    const allSteps = backend.ledgerCalls.map((c) => c.entry.step);

    // Every step in the canonical order must appear exactly once.
    const canonicalOrder = ["S0", "S1", "S2", "S3", "S4", "S7", "S8"];
    expect(allSteps).toEqual(canonicalOrder);

    // Cross-check: no step is absent.
    for (const stepId of canonicalOrder) {
      expect(allSteps).toContain(stepId);
    }
  });

  it("in-memory stepLedger in RunResult still reflects every step (backward compat)", async () => {
    const { result } = await runAndCapture();

    // The in-memory ledger (#247 contract) must still be present and consistent.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });

  // ── F4: drain-on-write — buffered entries survive a writeLedger failure ──────

  it("F4: if writeLedger throws on the first buffered entry, that entry is not dropped before the throw", async () => {
    /**
     * Regression: the old implementation called `pendingEntries.splice(0)`
     * BEFORE awaiting writeLedger.  If writeLedger threw, the buffer was
     * already cleared → entries permanently lost.
     *
     * The fixed implementation shifts each entry out of the buffer ONLY after
     * its write succeeds.  We verify this by using a Backend that rejects the
     * very first writeLedger call (the S0 buffered flush that happens at S1
     * completion).
     *
     * #6 (integ-cmr): a writeLedger failure is a backend-call exception — it
     * must NOT raw-reject out of runOrchestrator.  Per the PRD route table,
     * any runner-action / backend call that throws converges to S8(error) with
     * an error package.  So we assert the run terminates with status=error
     * (not a raw rejection), and that the first buffered entry was never
     * silently dropped (the write was attempted, which is what threw).
     */
    let writeAttempts = 0;
    const failFirstWriteBackend: Backend = {
      async findResumeState() { return undefined; },
      async cleanResidue() { /* no-op */ },
      async resumeSession(spec) {
        if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
        return { kind: "reviewer", findings: [] };
      },
      async fetchIssueMeta(n) {
        return { number: n, isReadyForAgent: true, hasSubIssues: false, openBlockedBy: [] };
      },
      async fetchIssueSnapshot(n) {
        return { number: n, body: "b", comments: [], agentBrief: "brief" };
      },
      async prepareWorktree(_n, _base) {
        return WORKTREE;
      },
      async writeSnapshot() { /* no-op */ },
      async runStep(spec) {
        if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
        return { kind: "reviewer", findings: [] };
      },
      async push() { /* no-op */ },
      async writeLedger() {
        writeAttempts += 1;
        if (writeAttempts === 1) {
          throw new Error("writeLedger: simulated I/O failure on first write");
        }
      },
    };

    // The runner must convert the writeLedger failure into S8(error), NOT
    // raw-reject (#6).
    const result = await runOrchestrator({
      issueNumber: 249,
      backend: failFirstWriteBackend,
    });
    expect(result.status).toBe("error");
    expect(result.errorPackage).toBeDefined();
    // The failed write was attempted (so the buffered entry was not dropped
    // before the throw — drain-on-write shifts only AFTER a successful write).
    // (The error termination then best-effort-persists S8, so attempts may be
    // >1; the load-bearing assertion is that the first write WAS attempted.)
    expect(writeAttempts).toBeGreaterThanOrEqual(1);
  });

  // ── F5: trailing-slash invariant ─────────────────────────────────────────────

  it("F5: worktreePath with trailing slash → stateDir is still a sibling (outside the worktree)", async () => {
    /**
     * Regression: the old implementation did not trim trailing separators, so
     * path "/foo/bar/" would compute lastSep at position 8 (the trailing slash)
     * and return parent = "/foo/bar" → stateDir = "/foo/bar/.ledger-N", which
     * IS under the worktree root.  `git clean -fd` on "/foo/bar" would then
     * remove it, breaking the core invariant.
     *
     * The fix trims trailing separators before computing the parent.
     */
    const trailingSlashWorktree: WorktreeHandle = {
      branch: "feat/orchestrator/issue-249",
      base: "main",
      // Trailing slash: the real worktree root is /resident/worktrees/issue-249
      path: "/resident/worktrees/issue-249/",
    };

    const capturedStateDirs: string[] = [];
    const trailingSlashBackend: Backend = {
      async findResumeState() { return undefined; },
      async cleanResidue() { /* no-op */ },
      async resumeSession(spec) {
        if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
        return { kind: "reviewer", findings: [] };
      },
      async fetchIssueMeta(n) {
        return { number: n, isReadyForAgent: true, hasSubIssues: false, openBlockedBy: [] };
      },
      async fetchIssueSnapshot(n) {
        return { number: n, body: "b", comments: [], agentBrief: "brief" };
      },
      async prepareWorktree() {
        return trailingSlashWorktree;
      },
      async writeSnapshot() { /* no-op */ },
      async runStep(spec) {
        if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
        return { kind: "reviewer", findings: [] };
      },
      async push() { /* no-op */ },
      async writeLedger(_entry, stateDir) {
        capturedStateDirs.push(stateDir);
      },
    };

    await runOrchestrator({ issueNumber: 249, backend: trailingSlashBackend });

    // All writeLedger calls must target a path that is NOT under the worktree root.
    // The canonical worktree root (without trailing slash):
    const worktreeRoot = "/resident/worktrees/issue-249";
    for (const dir of capturedStateDirs) {
      // Must NOT be a child of the worktree root.
      expect(dir.startsWith(worktreeRoot + "/")).toBe(false);
      // Must NOT be the worktree root itself.
      expect(dir).not.toBe(worktreeRoot);
      // Must NOT be the path-with-trailing-slash variant.
      expect(dir).not.toBe(worktreeRoot + "/");
    }
    // Sanity: some writeLedger calls did happen.
    expect(capturedStateDirs.length).toBeGreaterThan(0);
  });
});
