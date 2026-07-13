/**
 * S0 input gate tests (#248; relaxed per the design decision — the Agent Brief is
 * NOT a gate).
 *
 * Verifies the THREE-way reject logic: a non-rfa issue, a parent (has sub-issues),
 * or an open blocked_by each triggers a distinct error and stops at S0 with no
 * downstream Backend calls. A MISSING `## Agent Brief` does NOT gate — the run
 * proceeds to S1 (the coder reads the whole issue). A fully compliant issue
 * (including a leaf with a parent) passes through to S1.
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

// ──────────────────────────────────────────────────────────────────────────────
// Parameterisable fake Backend: caller supplies the IssueMeta to return from
// S0's fetchIssueMeta(); every other method records its call and returns
// a minimal stub. Tests assert on `calls` to prove nothing past S0 ran.
// ──────────────────────────────────────────────────────────────────────────────

class GateTestBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly calls: string[] = [];
  private readonly meta: IssueMeta;

  constructor(meta: IssueMeta) {
    this.meta = meta;
  }

  // #255: fresh-run defaults (no resume residue). Not recorded in `calls` so
  // the exact gate call-sequence assertions in this suite stay intact.
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id})`);
    return { kind: "coder", committed: false, commitsAdded: 0 };
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
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
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
  hasSubIssues: false,
  isClosed: false,
  openBlockedBy: [],
};

async function expectS0GateError(
  meta: IssueMeta,
  messagePattern: RegExp,
  input?: Partial<Parameters<typeof runOrchestrator>[0]>,
): Promise<{ reason: string; backend: GateTestBackend }> {
  const backend = new GateTestBackend(meta);
  const issueNumber = input?.issueNumber ?? 248;
  const result = await runOrchestrator({
    ...input,
    issueNumber,
    backend,
  });

  expect(result.status).toBe("error");
  expect(result.errorPackage?.failedStep).toBe("S0");
  expect(result.errorPackage?.reason).toMatch(messagePattern);
  expect(result.stopSummary.reason).toBe("infra_failure");
  expect(result.stopSummary.summary).toMatch(messagePattern);
  expect(result.stopSummary.repairHint).toMatch(/S0/);
  expect(result.stepLedger.map((entry) => entry.step)).toEqual(["S0", "S8"]);
  expect(result.stepLedger.at(-1)?.stopSummary).toEqual(result.stopSummary);
  expect(backend.calls).toEqual([`fetchIssueMeta(${issueNumber})`]);

  return { reason: result.errorPackage?.reason ?? "", backend };
}

// ──────────────────────────────────────────────────────────────────────────────
// Reject cases — three distinct non-compliant IssueMeta shapes
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 input gate — reject cases (#248)", () => {
  it("(a) non-rfa: returns a structured S0 terminal error", async () => {
    await expectS0GateError(
      { ...COMPLIANT_META, isReadyForAgent: false },
      /ready-for-agent/i,
    );
  });

  it("(b) no Agent Brief: PASSES S0 — a slice need not carry the brief (design: to-issues 切片未必有这段; 工具不能这么死板; coder 读整个 issue)", async () => {
    // DESIGN DECISION (user, 设计 session): the Agent Brief is NOT an S0 gate. A
    // `to-issues` slice may not carry a `## Agent Brief` section, and the gate must
    // not be rigid about it — the coder reads the WHOLE issue (body + comments), not
    // one section. So a missing brief must NOT stop the run at S0; it proceeds to S1.
    // #329 went further: the vestigial `hasAgentBrief` metadata was dropped from
    // IssueMeta entirely (S0 no longer even fetches comments to derive it). A
    // fully-compliant meta therefore inherently lacks any brief signal, which is
    // exactly the "no brief" case — S0 still advances to S1.
    const backend = new GateTestBackend({ ...COMPLIANT_META });

    // S0 does NOT reject on a missing brief — it advances to S1 (fetchIssueSnapshot).
    // It resolves (the stub coder's committed:false routes to an S8 error RESULT,
    // never a throw), so `await` it directly — NO `.catch` (online R1 Gemini): a
    // bare `.catch(()=>{})` would swallow a real reject (e.g. an S0/S1 runtime crash,
    // or a regression that re-adds the brief throw), masking the very failure this
    // test guards against.
    await runOrchestrator({ issueNumber: 248, backend });
    expect(backend.calls).toContain("fetchIssueSnapshot(248)");
    expect(backend.calls.length).toBeGreaterThan(1); // not stopped at the gate
  });

  it("(closed) issue is CLOSED: returns a structured S0 terminal error (#2 — a done slice must not run a coder)", async () => {
    await expectS0GateError({ ...COMPLIANT_META, isClosed: true }, /closed/i);
  });

  it("(c) parent issue (has sub-issues): returns a structured S0 terminal error", async () => {
    await expectS0GateError(
      { ...COMPLIANT_META, hasSubIssues: true },
      /leaf|sub.?issue|child/i,
    );
  });

  it("(d) open blocked_by: returns a structured S0 terminal error naming the blocking issue number AND 'blocked'/'upstream'", async () => {
    await expectS0GateError(
      { ...COMPLIANT_META, openBlockedBy: [247] },
      /(?=.*#?247)(?=.*(?:blocked|upstream))/i,
    );
  });

  it("(d) open blocked_by (multiple): error names all blocking issues AND 'blocked'/'upstream'", async () => {
    await expectS0GateError(
      { ...COMPLIANT_META, openBlockedBy: [100, 200] },
      /(?=.*#?100)(?=.*#?200)(?=.*(?:blocked|upstream))/i,
    );
  });

  it("each reject case produces a DIFFERENT error message (distinguishable)", async () => {
    const cases: [string, IssueMeta][] = [
      ["non-rfa", { ...COMPLIANT_META, isReadyForAgent: false }],
      ["has-sub-issues", { ...COMPLIANT_META, hasSubIssues: true }],
      ["blocked", { ...COMPLIANT_META, openBlockedBy: [99] }],
    ];

    const messages: string[] = [];
    for (const [, meta] of cases) {
      const { reason } = await expectS0GateError(meta, /S0 input gate/i, {
        issueNumber: 1,
      });
      messages.push(reason);
    }

    // All three messages are non-empty and mutually distinct.
    expect(messages.every((m) => m.length > 0)).toBe(true);
    const unique = new Set(messages);
    expect(unique.size).toBe(3);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Pass case — compliant issue proceeds past S0 into S1
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 input gate — pass case (#248)", () => {
  it("compliant leaf (no parent) passes S0 and calls fetchIssueSnapshot in S1", async () => {
    // We only need to see S1 fire; we don't need the full run to succeed.
    // Use a backend whose S1+ methods record calls but runStep returns a stub
    // that lets the ADR 0030 worker sequence proceed.
    class CompliantBackend extends GateTestBackend {
      constructor() {
        super(COMPLIANT_META);
      }

      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if (spec.role === "reviewer") {
          return { kind: "reviewer", findings: [] };
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
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
        if (spec.role === "reviewer") {
          return { kind: "reviewer", findings: [] };
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
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
// #294 / ADR 0022 decision 6③: family-mode blocked_by gate口径.
//
// In a family run the child's single-slice S0 blocked_by gate treats a
// still-open-on-GitHub blocker as SATISFIED iff it is in family.mergedBlockers
// (the commander's ledger-merged set), NOT by GitHub `closed`. The load-bearing
// soundness guarantee (decision 6③, last sentence): a blocker NOT in that set —
// e.g. an EXTERNAL dependency the commander never ledger-merged — is STILL a
// genuine open blocker the gate rejects. These pin S0's consumption contract,
// which the runChild fix (pass ONLY the intra-family subset as mergedBlockers,
// never an external `blocked_by`) relies on to keep external blockers rejected.
// ──────────────────────────────────────────────────────────────────────────────

describe("S0 gate — #294 family-mode ledger-merged blocked_by (decision 6③)", () => {
  const FAMILY = { parentIssue: 291, familyBase: "family/291-base" };

  it("family mode: a still-open-on-GitHub blocker that IS in mergedBlockers is excused (S0 passes)", async () => {
    // The commander released this child because #247 is ledger-merged into the
    // family base, even though GitHub still lists #247 as an open blocked_by.
    class PassBackend extends GateTestBackend {
      constructor() {
        super({ ...COMPLIANT_META, openBlockedBy: [247] });
      }
      override async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if (spec.role === "reviewer") {
          return { kind: "reviewer", findings: [] };
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
    }
    const backend = new PassBackend();
    const result = await runOrchestrator({
      issueNumber: 248,
      backend,
      family: { ...FAMILY, mergedBlockers: [247] },
    });
    // The ledger-merged口径 excused #247, so the gate did NOT throw — S1 ran and
    // the run reached success (no re-rejection of a just-released child).
    expect(backend.calls).toContain("fetchIssueSnapshot(248)");
    expect(result.status).toBe("success");
  });

  it("family mode: an open blocker NOT in mergedBlockers (external dependency) returns a structured S0 terminal error", async () => {
    // Decision 6③ soundness guard: #999 is an EXTERNAL open blocker the commander
    // never ledger-merged, so it is absent from mergedBlockers. The family-mode
    // gate must NOT blanket-skip the blocked_by check — #999 stays a genuine open
    // blocker. (#247 IS ledger-merged and excused; #999 is not and rejects.)
    const { backend } = await expectS0GateError(
      { ...COMPLIANT_META, openBlockedBy: [247, 999] },
      /(?=.*#?999)(?=.*(?:blocked|upstream))/i,
      { family: { ...FAMILY, mergedBlockers: [247] } },
    );
    // Stopped at S0 — nothing downstream ran (the external blocker rejected it).
    expect(backend.calls).toEqual(["fetchIssueMeta(248)"]);
  });

  it("family mode: error excludes the excused ledger-merged blocker, names only the genuine open one", async () => {
    // Sharper guard: when #247 is excused but #999 rejects, the thrown message
    // must name #999 and NOT #247 — the excused blocker is gone from openBlockedBy,
    // not merely outnumbered.
    const { reason: msg } = await expectS0GateError(
      { ...COMPLIANT_META, openBlockedBy: [247, 999] },
      /#?999/,
      { family: { ...FAMILY, mergedBlockers: [247] } },
    );
    expect(msg).toMatch(/#?999/);
    expect(msg).not.toMatch(/#247/);
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
        if (spec.role === "reviewer") {
          return { kind: "reviewer", findings: [] };
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
    }

    const backend = new FullBackend();
    const result = await runOrchestrator({ issueNumber: 248, backend });

    expect(result.status).toBe("success");
    // ADR 0030: the runner-level ledger exposes the fresh reviewer and
    // classification boundary before ship.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0", "S1", "S2", "S3", "S4", "S7", "S8",
    ]);
  });
});
