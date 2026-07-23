/**
 * #955 r7 — propagation of r3 (pool-bound capability) + r5 (session identity)
 * into the still-open surfaces:
 *
 * 1. Receipt maxRetries must use dispatch-bound (slug, pool), not slug alone.
 * 2. Session rebuild must ignore bookkeeping/audit ledger rows (event markers).
 * 3. escalateTermination agent rows must carry modelSlug (creator identity).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  Escalation,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
// ── Finding 2: rebuild skips audit event rows ───────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-955-r7-rebuild",
  base: "main",
  path: "/resident/worktrees/issue-955-r7-rebuild",
};
const STATE_DIR = "/resident/worktrees/.ledger-955-r7-rebuild";
const GOOD_CODER_SESSION = "sess-coder-real-dispatch";
const DISCARDED_SESSION = "sess-dropped-by-r5-continuity-lost";

function ledgerEntry(
  step: PersistentLedgerEntry["step"],
  opts?: {
    output?: StepOutput;
    sessionId?: string;
    modelSlug?: string;
    event?: PersistentLedgerEntry["event"];
    reason?: string;
    handoffStatus?: PersistentLedgerEntry["handoffStatus"];
  },
): PersistentLedgerEntry {
  return {
    step,
    sessionId: opts?.sessionId ?? "session-prior",
    prompt_hash: `hash-${step}`,
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-07-16T00:00:00.000Z",
    ...(opts?.output !== undefined ? { output: opts.output } : {}),
    ...(opts?.modelSlug !== undefined ? { modelSlug: opts.modelSlug } : {}),
    ...(opts?.event !== undefined ? { event: opts.event } : {}),
    ...(opts?.reason !== undefined ? { reason: opts.reason } : {}),
    ...(opts?.handoffStatus !== undefined
      ? { handoffStatus: opts.handoffStatus }
      : {}),
  };
}

/**
 * Crash residue: S2 real dispatch completed, S3 continue, then an audit tail
 * `session_continuity_lost` at S5 carrying the discarded session id (no modelSlug).
 * planResume re-enters S5; rebuild must not adopt DISCARDED_SESSION.
 */
function rebuildPoisonLedger(): ResumeState {
  return {
    worktree: WORKTREE,
    stateDir: STATE_DIR,
    ledger: [
      ledgerEntry("S0"),
      ledgerEntry("S1"),
      ledgerEntry("S2", {
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: GOOD_CODER_SESSION,
        modelSlug: "grok-4.5",
      }),
      ledgerEntry("S3", {
        output: {
          kind: "judge",
          status: "continue",
          findings: [
            {
              severity: "high",
              category: "correctness",
              claim_quote: "r7 rebuild filter",
              location: "orchestrator/src/runner.ts",
              suggested_fix: "skip event rows in session rebuild",
              action: "fix_now",
            },
          ],
        },
        sessionId: "sess-judge",
        modelSlug: "gpt-5.6-sol",
      }),
      // Audit tail that r5 writes when dropping a foreign session — must not
      // be treated as a real S5 agent dispatch for coderSessionId rebuild.
      {
        step: "S5",
        event: "session_continuity_lost",
        reason: "model_mismatch (session=other, seat=grok-4.5)",
        fromModelId: "other",
        toModelId: "grok-4.5",
        sessionId: DISCARDED_SESSION,
        runId: "run-r7",
        prompt_hash: "hash-lost",
        branchHEAD: "deadbeefcommitsha",
        ts: "2026-07-16T00:00:03.000Z",
      },
    ],
  };
}

class RebuildBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];

  constructor(
    private readonly resumeState: ResumeState,
    private readonly coderRecBody: string = "Coder-Rec: grok-4.5\n",
  ) {}

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
      body: this.coderRecBody,
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);

    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId:
          typeof ctx.resumeSessionId === "string"
            ? ctx.resumeSessionId
            : "sess-fresh-s5",
      };
    }
    if (spec.kind === "verify" || spec.kind === "reviewer") {
      return {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
        sessionId: "sess-judge-s6",
      };
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

describe("#955 r7 session rebuild ignores event audit rows", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("ledger tail session_continuity_lost must not become coder resumeSessionId", async () => {
    const backend = new RebuildBackend(rebuildPoisonLedger());
    const result = await runOrchestrator({ issueNumber: 95572, backend });
    expect(result.status).toBe("completed");

    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s5Idx).toBeGreaterThanOrEqual(0);
    const s5 = { spec: backend.specs[s5Idx]!, ctx: backend.ctxs[s5Idx]! };

    // Must not resurrect the r5-discarded id from the audit tail.
    expect(s5.ctx.resumeSessionId).not.toBe(DISCARDED_SESSION);
    // May resume the earlier real S2 dispatch (same model + capable) or open
    // fresh if continuity is absent — never the dropped audit id.
    if (s5.ctx.resumeSessionId !== undefined) {
      expect(s5.ctx.resumeSessionId).toBe(GOOD_CODER_SESSION);
      expect(s5.spec.session).toBe("resume");
    }
  });
});

// ── Finding 3: escalateTermination modelSlug ────────────────────────────────

const STUCK = {
  reason: "Design-level ambiguity on field X",
  diagnosis: "Spec says optional in one place and required in another.",
} satisfies Escalation;

class DecisionGateBackend implements Backend {
  constructor(private readonly coderRecBody: string = "Coder-Rec: grok-4.5\n") {}
  readonly ledger: PersistentLedgerEntry[] = [];

  async smokeModelRoute(route: Parameters<NonNullable<Backend["smokeModelRoute"]>>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
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
      body: this.coderRecBody,
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return {
      branch: "feat/orchestrator/issue-955-r7-esc",
      base: "main",
      path: "/resident/worktrees/issue-955-r7-esc",
    };
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.id === "S2") {
      // #937: free-log SelfReportedRelayError deleted. Typed coder escalate
      // still stamps modelSlug + sessionId via escalate handoff path.
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          escalate: STUCK,
        },
        sessionId: "sess-escalated-s2",
      };
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: "x", status: "pushed" },
    };
  }
}

describe("#955 r7 escalateTermination stamps modelSlug", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("decision_gate escalate agent row carries seat modelSlug on stepLedger + disk", async () => {
    const backend = new DecisionGateBackend();
    const result = await runOrchestrator({ issueNumber: 95573, backend });
    expect(result.status).toBe("parked");

    const s2Mem = result.stepLedger.find(
      (e) => e.step === "S2" && e.event === undefined,
    );
    expect(s2Mem).toBeDefined();
    expect(s2Mem?.sessionId).toBe("sess-escalated-s2");
    expect(s2Mem?.modelSlug).toBe("grok-4.5");

    const s2Disk = backend.ledger.find(
      (e) => e.step === "S2" && e.event === undefined && e.output !== undefined,
    );
    expect(s2Disk?.modelSlug).toBe("grok-4.5");
    expect(s2Disk?.sessionId).toBe("sess-escalated-s2");
  });
});
