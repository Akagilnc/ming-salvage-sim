/**
 * #955 r7 — propagation of r3 (pool-bound capability) + r5 (session identity)
 * into the still-open surfaces:
 *
 * 1. Receipt maxRetries must use dispatch-bound (slug, pool), not slug alone.
 * 2. Session rebuild must ignore bookkeeping/audit ledger rows (event markers).
 * 3. escalateTermination agent rows must carry modelSlug (creator identity).
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RealBackend } from "../../src/realBackend.js";
import {
  resumeCapableForSlug,
  resolveModelSlugForPool,
} from "../../src/modelRegistry.js";
import { SelfReportedRelayError } from "../../src/relayDispatch.js";
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
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type * as sc from "@ai-hero/sandcastle";
import {
  CODER_RECEIPT_TAG,
} from "../../src/stationReceiptContracts.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

// ── Finding 1: receipt pool binding ─────────────────────────────────────────

describe("#955 r7 receipt maxRetries binds (slug, pool)", () => {
  const RESUME_CAPABLE_SLUG = "gpt-5.6-sol";
  /** Registry pool that rewrites codex → cursor (not resume-capable). */
  const NON_RESUME_POOL = "cursor" as const;

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("registry truth: resume-capable slug + cursor pool → incapable provider", () => {
    expect(resumeCapableForSlug(RESUME_CAPABLE_SLUG)).toBe(true);
    expect(resolveModelSlugForPool(RESUME_CAPABLE_SLUG, NON_RESUME_POOL).provider).toBe(
      "cursor",
    );
    expect(resumeCapableForSlug(RESUME_CAPABLE_SLUG, NON_RESUME_POOL)).toBe(false);
  });

  it("runStep entry: resume-capable slug + cursor billingPool → maxRetries=0", async () => {
    class CaptureBackend extends RealBackend {
      public agentOptions: Array<Parameters<typeof sc.run>[0]> = [];

      protected override cloneDirExists(): boolean {
        return true;
      }

      protected override sh(file: string, args: string[]): string {
        if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
          return ".git";
        }
        if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
          return "a".repeat(40);
        }
        if (file === "git" && args[0] === "rev-list" && args[1] === "--count") {
          return "0";
        }
        return "";
      }

      protected override async preflightToolchainTool(): Promise<void> {}

      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.agentOptions.push(options);
        return {
          branch: "feat/r7",
          stdout: "ok",
          commits: [],
          iterations: [{}],
          output: {
            station: "coder",
            status: "completed",
            committed: true,
            commitsAdded: 1,
          },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const home = mkdtempSync(join(tmpdir(), "r7-955-home-"));
    const backend = new CaptureBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 95571,
      repo: "owner/name",
      imageName: "ming-worker:test",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home,
    });

    const coderSpec: StepSpec = {
      id: "S2",
      role: "coder",
      promptFile: "coder_implement.md",
      model: RESUME_CAPABLE_SLUG,
      maxIter: 1,
      soul: "coder",
      toolchain: ["python", "node", "npm", "typescript"],
    };

    // Control: no pool → resume-capable provider keeps maxRetries budget.
    try {
      await backend.runStep(coderSpec, {
        branch: "feat/r7",
        base: "main",
        path: "/tmp/worktree/r7-no-pool",
      });
      expect(backend.agentOptions[0]!.output).toMatchObject({
        tag: CODER_RECEIPT_TAG,
        maxRetries: 2,
      });

      // Under test: same slug, pool rewrites provider to non-resume-capable.
      await backend.runStep(
        coderSpec,
        {
          branch: "feat/r7",
          base: "main",
          path: "/tmp/worktree/r7-cursor-pool",
        },
        { billingPool: NON_RESUME_POOL },
      );
      expect(backend.agentOptions[1]!.output).toMatchObject({
        tag: CODER_RECEIPT_TAG,
        maxRetries: 0,
      });
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

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
          findingsCount: 1,
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
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_VERIFY_MODEL", "gpt-5.6-sol");

    const backend = new RebuildBackend(rebuildPoisonLedger());
    const result = await runOrchestrator({ issueNumber: 95572, backend });
    expect(result.status).toBe("success");

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
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
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
      // Hits escalateTermination (not the main-path route→handoff escalate).
      throw new SelfReportedRelayError(
        { kind: "decision_gate", state_summary: STUCK.diagnosis },
        "S2",
        "sess-escalated-s2",
      );
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
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "grok-4.5");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "grok-4.5");

    const backend = new DecisionGateBackend();
    const result = await runOrchestrator({ issueNumber: 95573, backend });
    expect(result.status).toBe("escalate");

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
