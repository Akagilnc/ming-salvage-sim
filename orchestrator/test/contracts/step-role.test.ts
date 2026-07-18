/**
 * #253 — StepSpec role contract + soul injection (vertical path assertions).
 *
 * All assertions are on a *running path* (through Backend.runStep), not on a
 * static StepSpec constructor, as the tdd hint in #253 requires:
 *   "穿 dispatch 路径的 vertical 断言"
 *
 * ADR 0030 keeps the single-slice runner as a pure scheduler while making the
 * per-slice review/fix loop runner-visible: S2 implements, S3 reviews, S4
 * classifies, S5 fixes, and S6 re-reviews as needed. This legacy suite still
 * pins the S2 coder contract plus common agent StepSpec shape.
 *
 * Covered acceptance criteria:
 *   AC-1  coder step (S2): role=coder, model=gpt-5.6-terra, soul=coder
 *   AC-3  changing model only changes runtime CLI selection, not StepSpec shape
 *   AC-4  versioned promptFile on the agent step; no ad-hoc inline prompt
 *   AC-6  tool-chain declaration contains Python + frontend stack
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

/** Minimal fake backend that records every StepSpec passed to runStep. */
class RecordingBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
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
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "judge", status: "converged" };
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

  async prepareWorktree(
    issueNumber: number,
    _base: string,
  ): Promise<WorktreeHandle> {
    return { ...this.worktree, branch: `feat/orchestrator/issue-${issueNumber}` };
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.capturedSpecs.push(spec);
    if (spec.role === "coder") {
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "judge", status: "converged" };
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

  it("S2 coder step: role=coder, normal-route model=gpt-5.6-terra, soul=coder", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const specs = await runAndCapture();
    const s2 = specs.find((s) => s.id === "S2");
    expect(s2).toBeDefined();
    expect(s2!.role).toBe("coder");
    // The normal route follows the parent #376 route table; env overrides can still
    // switch this slot without changing StepSpec wiring.
    expect(s2!.model).toBe("gpt-5.6-terra");
    expect(s2!.soul).toBe("coder");
  });

  // ── AC-2 (S3 reviewer step) lives in the ADR 0030 per-slice loop tests. ──

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

  // ── AC-4b: coder maxIter is single-iteration (#899 / ADR 0128) ──
  //   Each selected seat runs one Sandcastle iteration; skill work finishes
  //   inside that invocation (no outer Ralph multi-iter).

  it("coder maxIter is 1 (single-iteration seat)", async () => {
    const specs = await runAndCapture();
    const s2 = specs.find((s) => s.id === "S2")!;
    expect(s2.maxIter).toBeDefined();
    expect(s2.maxIter!).toBe(1);
  });

  // ── AC-4c (#928): completionSignal retired — clean exit + sidecar ──

  it("no agent step carries a completionSignal field", async () => {
    const specs = await runAndCapture();
    for (const spec of specs) {
      expect(Object.prototype.hasOwnProperty.call(spec, "completionSignal")).toBe(
        false,
      );
      expect(spec.maxIter).toBe(1);
    }
  });

  // ── AC-5 (reviewer READ-ONLY soul) is covered by ADR 0030 reviewer-step tests. ──

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
