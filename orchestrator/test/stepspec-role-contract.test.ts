/**
 * #253 — StepSpec role contract + soul injection (vertical path assertions).
 *
 * All assertions are on a *running path* (through Backend.runStep), not on a
 * static StepSpec constructor, as the tdd hint in #253 requires:
 *   "穿 dispatch 路径的 vertical 断言"
 *
 * ADR 0026 (2026-06-24, wiki line 42): the single-slice runner collapsed to a
 * pure scheduler — STEP_SPECS now holds ONLY S2 (the whole-slice build worker).
 * There is no runner-level reviewer step (S3) anymore: the per-slice review runs
 * INSIDE the S2 worker's session. The S3-reviewer AC tests are therefore dropped;
 * the surviving ACs all pin the single S2 coder spec.
 *
 * Covered acceptance criteria (S2-only after ADR 0026):
 *   AC-1  coder step (S2): role=coder, model=gpt-5.5, soul=coder
 *   AC-3  changing model only changes runtime CLI selection, not StepSpec shape
 *   AC-4  versioned promptFile on the agent step; no ad-hoc inline prompt
 *   AC-6  tool-chain declaration contains Python + frontend stack
 */

import { afterEach, describe, expect, it, vi } from "vitest";
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

/** Minimal fake backend that records every StepSpec passed to runStep. */
class RecordingBackend implements Backend {
  readonly capturedSpecs: StepSpec[] = [];

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-253",
    base: "main",
    path: "/resident/worktrees/issue-253",
  };

  // #255: fresh-run defaults (this suite asserts StepSpec shape, not resume).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
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
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    _base: string,
  ): Promise<WorktreeHandle> {
    return { ...this.worktree, branch: `feat/orchestrator/issue-${issueNumber}` };
  }

  async writeSnapshot(_worktree: WorktreeHandle, _snapshot: IssueSnapshot): Promise<void> {
    // no-op
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.capturedSpecs.push(spec);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "reviewer", findings: [] };
  }

  async push(_worktree: WorktreeHandle): Promise<void> {
    // no-op
  }

  // #249 integration: writeLedger is part of the Backend seam; this fake only
  // asserts StepSpec shape, so the ledger write is a no-op.
  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op
  }
}

describe("StepSpec role contract + soul injection (#253)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  async function runAndCapture() {
    const backend = new RecordingBackend();
    await runOrchestrator({ issueNumber: 253, backend });
    return backend.capturedSpecs;
  }

  // ── AC-1: coder step (S2) carries role=coder + route-selected model + soul=coder ──

  it("S2 coder step: role=coder, normal-route model=sonnet, soul=coder", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const specs = await runAndCapture();
    const s2 = specs.find((s) => s.id === "S2");
    expect(s2).toBeDefined();
    expect(s2!.role).toBe("coder");
    // The normal route follows the parent #376 route table; env overrides can still
    // switch this slot without changing StepSpec wiring.
    expect(s2!.model).toBe("sonnet");
    expect(s2!.soul).toBe("coder");
  });

  // ── AC-2 (S3 reviewer step) DELETED per ADR 0026: there is no runner-level
  //    reviewer step. STEP_SPECS holds only S2; the per-slice review runs INSIDE
  //    the S2 build worker's session, not as a separate dispatched step. ──

  // ── AC-4: every agent step carries a versioned promptFile (non-empty, file extension, no inline content) ──

  it("every agent step carries a versioned promptFile (filename, not inline content)", async () => {
    const specs = await runAndCapture();
    expect(specs.length).toBeGreaterThan(0);
    for (const spec of specs) {
      // promptFile must be a filename (contains a dot for extension) and not
      // a long inline prompt (inline prompts are detected by newlines or
      // lengths > 120 chars).
      expect(spec.promptFile).toMatch(/\.\w+$/); // has file extension
      expect(spec.promptFile).not.toContain("\n"); // no inline multiline prompt
      expect(spec.promptFile.length).toBeLessThan(120); // not an assembled blob
    }
  });

  // ── AC-3: changing model only changes what the runtime selects; StepSpec shape is stable ──
  //
  //   We verify this by confirming StepSpec.model is a short identifier that a
  //   runtime can map to a CLI — not a CLI path, not a full model string. The
  //   shape itself (which fields exist and how they're typed) never changes when
  //   the model selection changes.

  it("StepSpec.model is a short identifier (runtime selects CLI); StepSpec shape is stable across model choices", async () => {
    const specs = await runAndCapture();
    for (const spec of specs) {
      // model is a short slug, not a CLI path or full model id with hyphens/versions
      expect(typeof spec.model).toBe("string");
      expect((spec.model as string).length).toBeLessThan(40);
      // shape: all required fields always present regardless of model value
      expect(spec.id).toBeDefined();
      expect(spec.role).toBeDefined();
      expect(spec.promptFile).toBeDefined();
      expect(spec.soul).toBeDefined();
    }
  });

  // ── AC-4b: coder maxIter present and > 1 (iterative within-step Ralph budget) ──
  //   ADR 0026: the reviewer half is gone (no S3 step). The within-step retry
  //   budget for the S2 build worker is > 1 (it iterates within its one run).

  it("coder maxIter > 1 (iterative within-step budget)", async () => {
    const specs = await runAndCapture();
    const s2 = specs.find((s) => s.id === "S2")!;
    expect(s2.maxIter).toBeDefined();
    expect(s2.maxIter!).toBeGreaterThan(1);
  });

  // ── AC-4c: completionSignal present on every agent step ──

  it("every agent step carries a completionSignal", async () => {
    const specs = await runAndCapture();
    for (const spec of specs) {
      expect(spec.completionSignal).toBeDefined();
      expect(typeof spec.completionSignal).toBe("string");
      expect((spec.completionSignal as string).length).toBeGreaterThan(0);
    }
  });

  // ── AC-5 (reviewer READ-ONLY soul) DELETED per ADR 0026: there is no
  //    dispatched reviewer step. The soul-vs-OS-mount distinction for the
  //    READ-ONLY reviewer soul is now exercised only by the in-S2-worker review
  //    and the family cmr worker, not by the single-slice runner's STEP_SPECS.
  //    The coder soul is still asserted by AC-1 above. ──

  // ── AC-6: tool-chain declaration carried in StepSpec ──
  //   The spec includes a toolchain field listing Python + frontend stack.

  it("StepSpec carries toolchain declaration with Python and frontend entries", async () => {
    const specs = await runAndCapture();
    for (const spec of specs) {
      expect(spec.toolchain).toBeDefined();
      const tc = spec.toolchain as string[];
      expect(Array.isArray(tc)).toBe(true);
      // Must include Python
      expect(tc.some((t) => t.toLowerCase().includes("python"))).toBe(true);
      // Must include a frontend entry (node, npm, typescript, or frontend)
      expect(
        tc.some((t) =>
          ["node", "npm", "typescript", "frontend"].some((kw) =>
            t.toLowerCase().includes(kw),
          ),
        ),
      ).toBe(true);
    }
  });
});
