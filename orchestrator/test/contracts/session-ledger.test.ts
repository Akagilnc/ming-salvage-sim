/**
 * Seam-extension unit test (#256): the runner records the REAL per-step sandbox
 * session id surfaced by the widened seam (runStep/resumeSession may return a
 * StepResult), and falls back to the run-level UUID when a Backend returns a bare
 * StepOutput. Also asserts true-value prompt_hash (content) + branchHEAD (SHA)
 * when the optional Backend helpers are present.
 *
 * Zero-container: a hand-rolled fake exercises ONLY the runner's normalisation +
 * ledger threading — no Sandcastle, no Docker, no LLM.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepResult,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

const WT: WorktreeHandle = {
  branch: "feat/244-orchestrator-issue-256",
  base: "main",
  path: "/resident/worktrees/issue-256",
};

/**
 * A fake that returns the #256 StepResult shape (real per-step sessionId), plus
 * the optional true-value helpers. Records every persisted ledger entry.
 */
class SeamExtensionBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly persisted: PersistentLedgerEntry[] = [];
  /** When false, runStep returns a BARE StepOutput (no per-step sessionId). */
  constructor(
    private readonly returnStepResult = true,
    private readonly withTrueValueHelpers = true,
  ) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput | StepResult> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    return {
      number: n,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
    return { number: n, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WT;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput | StepResult> {
    const output: StepOutput =
      spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 1 }
        : { kind: "reviewer", findings: [] };
    if (!this.returnStepResult) return output; // bare StepOutput path
    // Real per-step session id keyed on the step id so each step is distinct.
    return { output, sessionId: `sess-${spec.id}` };
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.persisted.push(entry);
  }

  // Optional #256 true-value helpers (present only when withTrueValueHelpers).
  readPromptContent?(promptFile: string): Promise<string | undefined>;
  worktreeHead?(_w: WorktreeHandle): Promise<string | undefined>;

  enableTrueValue(): void {
    if (!this.withTrueValueHelpers) return;
    this.readPromptContent = async (pf: string) =>
      `RESOLVED CONTENT OF ${pf}`;
    this.worktreeHead = async () => "f".repeat(40);
  }
}

describe("#256 seam extension — real per-step sessionId in the ledger", () => {
  it("records the real per-step sessionId for the agent step (S2)", async () => {
    // ADR 0030 dispatches per-slice build/review/fix as separate worker steps.
    // This assertion covers the S2 build worker's REAL per-step id surfaced by
    // the seam, not the run-level UUID shared by runner-action steps.
    const backend = new SeamExtensionBackend(/*returnStepResult*/ true);
    const result = await runOrchestrator({ issueNumber: 256, backend });
    expect(result.status).toBe("success");

    const byStep = (s: string) =>
      backend.persisted.find((e) => e.step === s);
    // The agent step carries its REAL per-step session id (not a shared UUID).
    expect(byStep("S2")?.sessionId).toBe("sess-S2");
    // It differs from the run-level UUID the runner-action steps share — proving
    // it is the per-step seam id, not the fallback.
    expect(byStep("S2")?.sessionId).not.toBe(byStep("S0")?.sessionId);
  });

  it("runner-action steps share the run-level UUID fallback (no per-step session)", async () => {
    const backend = new SeamExtensionBackend(true);
    await runOrchestrator({ issueNumber: 256, backend });
    const s0 = backend.persisted.find((e) => e.step === "S0")!;
    const s1 = backend.persisted.find((e) => e.step === "S1")!;
    const s7 = backend.persisted.find((e) => e.step === "S7")!;
    // All runner-action steps share ONE id (the run-level UUID), and it differs
    // from the per-step agent ids.
    expect(s0.sessionId).toBe(s1.sessionId);
    expect(s1.sessionId).toBe(s7.sessionId);
    expect(s0.sessionId).not.toBe("sess-S2");
    expect(s0.sessionId.length).toBeGreaterThan(0);
  });

  it("falls back to the run-level UUID when the Backend returns a bare StepOutput", async () => {
    // A fake returning a bare StepOutput (the v0.1 / control-flow-test shape) —
    // the runner must still work and record the run-level UUID for agent steps.
    const backend = new SeamExtensionBackend(/*returnStepResult*/ false);
    const result = await runOrchestrator({ issueNumber: 256, backend });
    expect(result.status).toBe("success");
    const s0 = backend.persisted.find((e) => e.step === "S0")!;
    const s2 = backend.persisted.find((e) => e.step === "S2")!;
    // No per-step id → agent step shares the run-level UUID with runner actions.
    expect(s2.sessionId).toBe(s0.sessionId);
  });
});

describe("#256 true-value ledger — content prompt_hash + SHA branchHEAD", () => {
  it("hashes promptFile CONTENT (content:) and records the real HEAD SHA", async () => {
    const backend = new SeamExtensionBackend(true, true);
    backend.enableTrueValue();
    await runOrchestrator({ issueNumber: 256, backend });

    const s2 = backend.persisted.find((e) => e.step === "S2")!;
    // prompt_hash is the CONTENT hash (prefixed content:), not the name hash.
    expect(s2.prompt_hash.startsWith("content:")).toBe(true);
    // branchHEAD is the real 40-hex SHA from worktreeHead(), not the branch name.
    expect(s2.branchHEAD).toBe("f".repeat(40));
  });

  it("falls back to name: hash + branch name when no true-value helpers exist", async () => {
    const backend = new SeamExtensionBackend(true, false);
    // do NOT enable true-value helpers
    await runOrchestrator({ issueNumber: 256, backend });
    const s2 = backend.persisted.find((e) => e.step === "S2")!;
    expect(s2.prompt_hash.startsWith("name:")).toBe(true);
    // branchHEAD falls back to the branch name (v0.1 behaviour preserved).
    expect(s2.branchHEAD).toBe(WT.branch);
  });

  it("runner-action steps hash the step id (name:) — they have no promptFile", async () => {
    const backend = new SeamExtensionBackend(true, true);
    backend.enableTrueValue();
    await runOrchestrator({ issueNumber: 256, backend });
    const s0 = backend.persisted.find((e) => e.step === "S0")!;
    // S0 has no promptFile → name hash even with readPromptContent present.
    expect(s0.prompt_hash.startsWith("name:")).toBe(true);
  });
});
