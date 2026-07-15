/**
 * #926 — judge advance_coder execution + stay-put when advance invalid.
 *
 * Seams:
 * 1. Pure resolveAdvanceCoderSuggestion (roster lookup → advanced | stay_put | noop)
 * 2. runOrchestrator + fake Backend — S5 model/session after continue+advanceCoder;
 *    invalid target never terminals; stay-put ledger audit
 * 3. Negative: without judge order, multi-round path never mechanically rotates
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  lookupCoderRosterEntry,
  resolveAdvanceCoderSuggestion,
} from "../../src/coderRoster.js";
import { findingIdentityKey } from "../../src/findings.js";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  sampleFinding,
} from "../helpers/judge-fixtures.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-926",
  base: "main",
  path: "/resident/worktrees/issue-926",
};

const CODER_REC_BODY =
  "Coder-Rec: grok-4.5 → terra@med → sol@med\n\n## Scope\nadvance-coder tests\n";

const S2_SESSION = "sess-coder-s2-926";
const S3_SESSION = "sess-judge-s3-926";

type JudgeScript =
  | { kind: "converged" }
  | {
      kind: "continue";
      findings?: Finding[];
      advanceCoder?: string;
    };

class AdvanceCoderBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly coderModels: string[] = [];
  readonly coderSessions: Array<"fresh" | "resume"> = [];
  readonly resumeSessionIds: Array<string | undefined> = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private judgeScripts: JudgeScript[];
  private judgeIdx = 0;

  constructor(judgeScripts: JudgeScript[]) {
    this.judgeScripts = judgeScripts;
  }

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async runStep(): Promise<never> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<never> {
    throw new Error("resumeSession called directly — use dispatchWorker");
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: CODER_REC_BODY,
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return {
      number: issueNumber,
      body: CODER_REC_BODY,
      comments: [],
      agentBrief: "",
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);

    if (spec.kind === "coder") {
      this.coderModels.push(spec.model);
      this.coderSessions.push(spec.session);
      this.resumeSessionIds.push(ctx.resumeSessionId);
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : S2_SESSION;
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId,
      };
    }

    if (
      spec.kind === "verify" ||
      spec.kind === "reviewer" ||
      spec.id === "S3" ||
      spec.id === "S6"
    ) {
      const script = this.judgeScripts[this.judgeIdx] ?? { kind: "converged" };
      this.judgeIdx += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : S3_SESSION;
      if (script.kind === "converged") {
        return completedJudge(judgeConverged(), sessionId);
      }
      const findings = script.findings ?? [sampleFinding()];
      return completedJudge(
        judgeContinue(findings, {
          ...(script.advanceCoder !== undefined
            ? { advanceCoder: script.advanceCoder }
            : {}),
        }),
        sessionId,
      );
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("#926 pure: resolveAdvanceCoderSuggestion", () => {
  it("advances to a roster-valid target (positive)", () => {
    const decision = resolveAdvanceCoderSuggestion("sol@med", "grok-4.5");
    expect(decision).toEqual({
      kind: "advanced",
      entry: lookupCoderRosterEntry("sol@med"),
      fromSlug: "grok-4.5",
    });
  });

  it("accepts roster slug aliases as targets", () => {
    const decision = resolveAdvanceCoderSuggestion("gpt-5.6-sol", "grok-4.5");
    expect(decision.kind).toBe("advanced");
    if (decision.kind === "advanced") {
      expect(decision.entry.slug).toBe("gpt-5.6-sol");
    }
  });

  it("stay-put on unknown target (negative — never invents a seat)", () => {
    const decision = resolveAdvanceCoderSuggestion(
      "not-a-real-coder",
      "grok-4.5",
    );
    expect(decision).toEqual({
      kind: "stay_put",
      reason: "unknown_target",
      suggestion: "not-a-real-coder",
      currentSlug: "grok-4.5",
    });
  });

  it("noop when target is already the active coder", () => {
    const decision = resolveAdvanceCoderSuggestion("grok-4.5", "grok-4.5");
    expect(decision).toEqual({
      kind: "noop",
      reason: "already_active",
      currentSlug: "grok-4.5",
    });
  });

  it("noop on empty / whitespace suggestion", () => {
    expect(resolveAdvanceCoderSuggestion("   ", "grok-4.5").kind).toBe("noop");
  });
});

describe("#926 behavior: runner executes advance_coder", () => {
  it("switches S5 to the suggested roster coder with a fresh session", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new AdvanceCoderBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "sol@med",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9261, backend });
    expect(result.status).toBe("success");

    // S2 first seat (Coder-Rec) → S5 advanced seat.
    expect(backend.coderModels[0]).toBe("grok-4.5");
    expect(backend.coderModels[1]).toBe("gpt-5.6-sol");

    // New coder is fresh — prior S2 session is retired.
    expect(backend.coderSessions[0]).toBe("fresh");
    expect(backend.coderSessions[1]).toBe("fresh");
    expect(backend.resumeSessionIds[1]).toBeUndefined();

    const advanceRows = result.stepLedger.filter(
      (e) => e.event === "coder_advance",
    );
    expect(advanceRows.length).toBe(1);
    expect(advanceRows[0]).toMatchObject({
      event: "coder_advance",
      fromModelId: "grok-4.5",
      toModelId: "gpt-5.6-sol",
    });
  });

  it("stay-put on invalid advance: keeps coder, never terminals, audits ledger", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new AdvanceCoderBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "claude-opus-not-on-roster",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9262, backend });

    // Negative: roster failure must not end the run.
    expect(result.status).toBe("success");
    expect(result.status).not.toBe("error");
    expect(result.status).not.toBe("escalate");

    // S2 and S5 stay on first seat.
    expect(backend.coderModels.every((m) => m === "grok-4.5")).toBe(true);
    expect(backend.coderModels.length).toBeGreaterThanOrEqual(2);

    // S5 may resume the original coder session (not retired).
    expect(backend.coderSessions[1]).toBe("resume");
    expect(backend.resumeSessionIds[1]).toBe(S2_SESSION);

    const stayPutRows = result.stepLedger.filter(
      (e) => e.event === "coder_advance_stay_put",
    );
    expect(stayPutRows.length).toBe(1);
    expect(stayPutRows[0]).toMatchObject({
      event: "coder_advance_stay_put",
      reason: "unknown_target",
      fromModelId: "grok-4.5",
      toModelId: "grok-4.5",
    });
    // Suggestion is audit-visible (state_summary carrier).
    expect(stayPutRows[0]!.state_summary).toMatch(/claude-opus-not-on-roster/);
  });

  it("without advanceCoder, multi-round path never mechanically rotates coder", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    // Three continue rounds then converge — pure round count, no judge order.
    const backend = new AdvanceCoderBackend([
      { kind: "continue", findings: [sampleFinding()] },
      { kind: "continue", findings: [sampleFinding()] },
      { kind: "continue", findings: [sampleFinding()] },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9263, backend });
    expect(result.status).toBe("success");

    expect(backend.coderModels.length).toBeGreaterThanOrEqual(4); // S2 + 3×S5
    expect(backend.coderModels.every((m) => m === "grok-4.5")).toBe(true);
    expect(
      result.stepLedger.some(
        (e) =>
          e.event === "coder_advance" || e.event === "coder_advance_stay_put",
      ),
    ).toBe(false);
  });

  it("advance sticky holds across a subsequent S5 after S6 continue without new advance", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const backend = new AdvanceCoderBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "terra@med",
      },
      // S6: still open, no new advance — sticky advanced seat must hold.
      { kind: "continue", findings: [sampleFinding()] },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9264, backend });
    expect(result.status).toBe("success");

    // S2=grok, S5#1=terra (advanced), S5#2=terra (sticky).
    expect(backend.coderModels).toEqual([
      "grok-4.5",
      "gpt-5.6-terra",
      "gpt-5.6-terra",
    ]);
  });
});

describe("#926 ledger carriers are bookkeeping (not step results)", () => {
  it("finding identity on continue is independent of advance event", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    const finding = sampleFinding("advance-claim", "a.ts:1");
    const backend = new AdvanceCoderBackend([
      {
        kind: "continue",
        findings: [finding],
        advanceCoder: "sol@med",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9265, backend });
    expect(result.status).toBe("success");

    const s5 = backend.ctxs.find(
      (c, i) => backend.specs[i]?.id === "S5",
    );
    expect(s5?.blockingFindingIdentityKeys).toEqual([
      findingIdentityKey(finding),
    ]);

    // Advance bookkeeping does not masquerade as a productive step output.
    const advance = result.stepLedger.find(
      (e: LedgerEntry) => e.event === "coder_advance",
    );
    expect(advance?.output).toBeUndefined();
  });
});
