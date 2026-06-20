/**
 * S0 input gate tests (#248).
 *
 * Verifies the four-way reject logic: each non-compliant IssueMeta triggers
 * a distinct error and stops at S0 — no downstream Backend methods are called.
 * A fully compliant issue (including a leaf with a parent) passes through to S1.
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

// ──────────────────────────────────────────────────────────────────────────────
// Parameterisable fake Backend: caller supplies the IssueMeta to return from
// S0's fetchIssueMeta(); every other method records its call and returns
// a minimal stub. Tests assert on `calls` to prove nothing past S0 ran.
// ──────────────────────────────────────────────────────────────────────────────

class GateTestBackend implements Backend {
  readonly calls: string[] = [];
  private readonly meta: IssueMeta;

  constructor(meta: IssueMeta) {
    this.meta = meta;
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return this.meta;
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return { number: issueNumber, body: "", comments: [], agentBrief: "" };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    return {
      branch: `feat/issue-${issueNumber}`,
      base,
      path: `/wt/${issueNumber}`,
    };
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    return { kind: "coder", committed: false, commitsAdded: 0 };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
  }

  // #249 integration: writeLedger is part of the Backend seam. This suite
  // asserts the S0 gate (which stops before any ledger write) and the #247
  // happy-path regression, so the ledger write is a no-op (not recorded in
  // `calls`, to keep the exact gate-rejection call-sequence assertions intact).
  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Shared helpers
// ──────────────────────────────────────────────────────────────────────────────

/** Compliant leaf issue (has a parent in real GH, but v0.1 treats it as a leaf). */
const COMPLIANT_META: IssueMeta = {
  number: 248,
  isReadyForAgent: true,
  hasAgentBrief: true,
  hasSubIssues: false,
  openBlockedBy: [],
};


// ──────────────────────────────────────────────────────────────────────────────
// Reject cases — four distinct non-compliant IssueMeta shapes
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 input gate — reject cases (#248)", () => {
  it("(a) non-rfa: rejects and stops at S0 with a clear error", async () => {
    const backend = new GateTestBackend({
      ...COMPLIANT_META,
      isReadyForAgent: false,
    });

    await expect(
      runOrchestrator({ issueNumber: 248, backend }),
    ).rejects.toThrow(/ready-for-agent/i);

    // Gate must fire exactly once (fetchIssueMeta) with no downstream calls.
    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("(b) no Agent Brief: rejects and stops at S0 with a clear error", async () => {
    const backend = new GateTestBackend({
      ...COMPLIANT_META,
      hasAgentBrief: false,
    });

    await expect(
      runOrchestrator({ issueNumber: 248, backend }),
    ).rejects.toThrow(/agent brief/i);

    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("(c) parent issue (has sub-issues): rejects and stops at S0 with a clear error", async () => {
    const backend = new GateTestBackend({
      ...COMPLIANT_META,
      hasSubIssues: true,
    });

    await expect(
      runOrchestrator({ issueNumber: 248, backend }),
    ).rejects.toThrow(/leaf|sub.?issue|child/i);

    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("(d) open blocked_by: rejects at S0 naming the blocking issue number AND 'blocked'/'upstream'", async () => {
    const backend = new GateTestBackend({
      ...COMPLIANT_META,
      openBlockedBy: [247],
    });

    // Single assertion: error must simultaneously name the blocking issue AND
    // carry 'blocked'/'upstream' semantics — ensures both are present together.
    await expect(
      runOrchestrator({ issueNumber: 248, backend }),
    ).rejects.toThrow(/(?=.*#?247)(?=.*(?:blocked|upstream))/i);

    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("(d) open blocked_by (multiple): error names all blocking issues AND 'blocked'/'upstream'", async () => {
    const backend = new GateTestBackend({
      ...COMPLIANT_META,
      openBlockedBy: [100, 200],
    });

    await expect(
      runOrchestrator({ issueNumber: 248, backend }),
    ).rejects.toThrow(/(?=.*#?100)(?=.*#?200)(?=.*(?:blocked|upstream))/i);

    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("each reject case produces a DIFFERENT error message (distinguishable)", async () => {
    const cases: [string, IssueMeta][] = [
      ["non-rfa", { ...COMPLIANT_META, isReadyForAgent: false }],
      ["no-brief", { ...COMPLIANT_META, hasAgentBrief: false }],
      ["has-sub-issues", { ...COMPLIANT_META, hasSubIssues: true }],
      ["blocked", { ...COMPLIANT_META, openBlockedBy: [99] }],
    ];

    const messages: string[] = [];
    for (const [, meta] of cases) {
      const b = new GateTestBackend(meta);
      let msg = "";
      try {
        await runOrchestrator({ issueNumber: 1, backend: b });
      } catch (e) {
        msg = (e as Error).message;
      }
      messages.push(msg);
    }

    // All four messages are non-empty and mutually distinct.
    expect(messages.every((m) => m.length > 0)).toBe(true);
    const unique = new Set(messages);
    expect(unique.size).toBe(4);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Pass case — compliant issue proceeds past S0 into S1
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 input gate — pass case (#248)", () => {
  it("compliant leaf (no parent) passes S0 and calls fetchIssueSnapshot in S1", async () => {
    // We only need to see S1 fire; we don't need the full run to succeed.
    // Use a backend whose S1+ methods record calls but runStep returns a stub
    // that lets the runner proceed. Wire up a minimal full run by extending
    // GateTestBackend to return a proper coder/reviewer output in runStep.
    class CompliantBackend extends GateTestBackend {
      constructor() {
        super(COMPLIANT_META);
      }

      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "reviewer", findings: [] };
      }
    }

    const backend = new CompliantBackend();
    const result = await runOrchestrator({ issueNumber: 248, backend });

    // Gate let it through → S1 load_context ran.
    expect(backend.calls).toContain("fetchIssueSnapshot(248)");
    // Full run succeeded.
    expect(result.status).toBe("success");
  });

  it("compliant meta passes S0 and calls S0 then S1 in order (gate-to-context sequencing)", async () => {
    // leafWithParentMeta is byte-identical to COMPLIANT_META: IssueMeta has no
    // parent field, so this test cannot verify parent mapping. What it actually
    // pins is that S0 calls fetchIssueMeta first, then S1 calls fetchIssueSnapshot —
    // i.e. the gate-to-context call ordering is correct.
    const leafWithParentMeta: IssueMeta = {
      ...COMPLIANT_META,
      number: 248, // same shape as COMPLIANT_META; parent-in-GitHub is outside IssueMeta
    };

    class LeafBackend extends GateTestBackend {
      constructor() {
        super(leafWithParentMeta);
      }

      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "reviewer", findings: [] };
      }
    }

    const backend = new LeafBackend();
    const result = await runOrchestrator({ issueNumber: 248, backend });

    expect(result.status).toBe("success");
    // S0 only reads lightweight meta — fetchIssueSnapshot is S1, not S0.
    expect(backend.calls[0]).toBe("fetchIssueMeta(248)");
    expect(backend.calls[1]).toBe("fetchIssueSnapshot(248)");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// #247 happy-path regression: compliant run still reaches success
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 gate — #247 happy-path regression", () => {
  it("original happy-path (#247) still reaches S8 success unchanged", async () => {
    class FullBackend extends GateTestBackend {
      constructor() {
        super(COMPLIANT_META);
      }

      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "reviewer", findings: [] };
      }
    }

    const backend = new FullBackend();
    const result = await runOrchestrator({ issueNumber: 248, backend });

    expect(result.status).toBe("success");
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });
});
