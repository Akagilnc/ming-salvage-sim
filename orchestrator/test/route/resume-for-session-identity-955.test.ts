/**
 * #955 r5 cx-r5-1 — resumeFor session identity binding.
 *
 * Invariant: a stored session id may only resume into the same model binding
 * that created it. Persistent seats already gate on seatModel === sessionModel;
 * crash/escalate `resumeFor` must do the same (plus the r3 capability gate).
 *
 * Entry: real `runOrchestrator` + real ledger rows (modelSlug on the escalated
 * agent step) + real registry slugs via env. No hand-built capability fixtures.
 */

import { describe, expect, it, vi } from "vitest";

import { resumeCapableForSlug } from "../../src/modelRegistry.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  Escalation,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-955-resume-identity",
  base: "main",
  path: "/resident/worktrees/issue-955-resume-identity",
};

const STATE_DIR = "/resident/worktrees/.ledger-955-resume-identity";
const ESCALATED_SESSION = "sess-escalated-grok-955";

const STUCK = {
  reason: "Design-level ambiguity: field X optional vs required",
  diagnosis:
    "The child issue body says optional in one place but required in another; a product decision is required before implementation can proceed.",
} satisfies Escalation;

function entry(
  step: PersistentLedgerEntry["step"],
  output?: StepOutput,
  opts?: {
    sessionId?: string;
    modelSlug?: string;
  },
): PersistentLedgerEntry {
  return {
    step,
    sessionId: opts?.sessionId ?? "session-prior",
    prompt_hash: `hash-${step}`,
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-07-16T00:00:00.000Z",
    ...(output !== undefined ? { output } : {}),
    ...(opts?.modelSlug !== undefined ? { modelSlug: opts.modelSlug } : {}),
  };
}

function s8Escalate(): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-07-16T00:00:01.000Z",
    handoffStatus: "escalate",
    escalationKind: "decision",
  };
}

function answerRow(): PersistentLedgerEntry {
  return {
    step: "S2",
    event: "escalation_answered",
    forStep: "S2",
    answer: "field X is required; proceed",
    source: "human",
    sessionId: ESCALATED_SESSION,
    prompt_hash: "hash-answer",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-07-16T00:00:02.000Z",
  };
}

/**
 * Parked ledger: S2 escalated under `sessionModel`, human answered.
 * Resume re-enters S2 via planResume → resumeFor.
 */
function parkedEscalationLedger(sessionModel: string): ResumeState {
  return {
    worktree: WORKTREE,
    stateDir: STATE_DIR,
    ledger: [
      entry("S0"),
      entry("S1"),
      entry(
        "S2",
        {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          escalate: STUCK,
        },
        { sessionId: ESCALATED_SESSION, modelSlug: sessionModel },
      ),
      s8Escalate(),
      answerRow(),
    ],
  };
}

/**
 * Resume-aware backend that records dispatch session mode + resumeSessionId
 * and writes ledger rows (so session_continuity_lost is observable).
 */
class ResumeIdentityBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];

  constructor(private readonly resumeState: ResumeState) {}

  async smokeModelRoute(route: Parameters<NonNullable<Backend["smokeModelRoute"]>>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  async findResumeState(): Promise<ResumeState> {
    return this.resumeState;
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession called directly — use dispatchWorker");
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
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
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
      // After escalate answer, coder finishes cleanly (fresh or resume).
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId:
          typeof ctx.resumeSessionId === "string"
            ? ctx.resumeSessionId
            : "sess-fresh-after-answer",
      };
    }

    if (spec.kind === "verify" || spec.kind === "reviewer") {
      return {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
        sessionId: "sess-judge",
      };
    }

    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

function firstCoderDispatch(backend: ResumeIdentityBackend): {
  spec: WorkerSpec;
  ctx: DispatchContext;
} {
  const idx = backend.specs.findIndex((s) => s.id === "S2");
  expect(idx).toBeGreaterThanOrEqual(0);
  return { spec: backend.specs[idx]!, ctx: backend.ctxs[idx]! };
}

describe("#955 resumeFor session identity gate", () => {
  it("registry truth anchors: grok-4.5 capable; gpt-5.6-terra capable; agy incapable", () => {
    expect(resumeCapableForSlug("grok-4.5")).toBe(true);
    expect(resumeCapableForSlug("gpt-5.6-terra")).toBe(true);
    expect(resumeCapableForSlug("agy")).toBe(false);
  });

  it("identity mismatch (grok session → codex seat) → fresh + answer delivered + continuity-lost mark", async () => {
    // Ledger records the session was created on grok; resume seat is codex terra.
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "gpt-5.6-terra");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "gpt-5.6-terra");

    const backend = new ResumeIdentityBackend(parkedEscalationLedger("grok-4.5"));
    const result = await runOrchestrator({ issueNumber: 95510, backend });
    expect(result.status).toBe("success");

    const s2 = firstCoderDispatch(backend);
    expect(s2.spec.model).toBe("gpt-5.6-terra");
    expect(s2.spec.session).toBe("fresh");
    expect(s2.ctx.resumeSessionId).toBeUndefined();
    // Escalation answer still reaches the worker — only session continuity is dropped.
    expect(s2.ctx.escalationAnswer).toMatchObject({
      event: "escalation_answered",
      forStep: "S2",
      answer: "field X is required; proceed",
    });

    const lost = backend.ledgerWrites.filter(
      (e) => e.event === "session_continuity_lost",
    );
    expect(lost).toHaveLength(1);
    expect(lost[0]).toMatchObject({
      event: "session_continuity_lost",
      step: "S2",
      sessionId: ESCALATED_SESSION,
      fromModelId: "grok-4.5",
      toModelId: "gpt-5.6-terra",
    });
    expect(lost[0]!.reason).toMatch(/model_mismatch/);
  });

  it("identity match + resume-capable seat → original session resume (no regression)", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "grok-4.5");

    const backend = new ResumeIdentityBackend(parkedEscalationLedger("grok-4.5"));
    const result = await runOrchestrator({ issueNumber: 95511, backend });
    expect(result.status).toBe("success");

    const s2 = firstCoderDispatch(backend);
    expect(s2.spec.model).toBe("grok-4.5");
    expect(s2.spec.session).toBe("resume");
    expect(s2.ctx.resumeSessionId).toBe(ESCALATED_SESSION);
    expect(s2.ctx.escalationAnswer).toMatchObject({
      event: "escalation_answered",
      forStep: "S2",
      answer: "field X is required; proceed",
    });
    expect(
      backend.ledgerWrites.some((e) => e.event === "session_continuity_lost"),
    ).toBe(false);
  });

  it("identity match but resume-incapable seat (agy) → fresh (r3 capability gate kept)", async () => {
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "agy");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "agy");

    const backend = new ResumeIdentityBackend(parkedEscalationLedger("agy"));
    const result = await runOrchestrator({ issueNumber: 95512, backend });
    expect(result.status).toBe("success");

    const s2 = firstCoderDispatch(backend);
    expect(s2.spec.model).toBe("agy");
    expect(s2.spec.session).toBe("fresh");
    expect(s2.ctx.resumeSessionId).toBeUndefined();
    expect(s2.ctx.escalationAnswer).toMatchObject({
      event: "escalation_answered",
      forStep: "S2",
    });

    const lost = backend.ledgerWrites.filter(
      (e) => e.event === "session_continuity_lost",
    );
    expect(lost).toHaveLength(1);
    expect(lost[0]!.reason).toMatch(/provider_incapable/);
    expect(lost[0]).toMatchObject({
      sessionId: ESCALATED_SESSION,
      fromModelId: "agy",
      toModelId: "agy",
    });
  });
});
