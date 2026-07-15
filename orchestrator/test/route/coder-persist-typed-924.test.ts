/**
 * #924 — coder persistent session + single-iter + official typed station receipt.
 *
 * Seams (owner-confirmed via #919 Testing Decisions + AC):
 * 1. runOrchestrator + fake Backend — S2 fresh / S5 resume same session shape
 * 2. Real sc.run + production SO schema — bad envelope shape native re-ask
 * 3. realBackend resume — dead session → fresh run, run does not die
 * 4. coder prompts teach envelope by referencing T2 contracts (no second schema)
 */

import { afterEach, describe, expect, it } from "vitest";
import { readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { RECEIPT_MAX_RETRIES } from "../../src/receiptRecovery.js";
import {
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  decodeCoderEnvelope,
} from "../../src/stationReceiptContracts.js";
import { classifyResumeError } from "../../src/realBackend.js";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  runScriptedStructuredOutput,
  type ScriptedAgent,
} from "../helpers/scripted-sandcastle-run.js";
const PROMPTS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../prompts",
);

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-924",
  base: "main",
  path: "/resident/worktrees/issue-924",
};

const S2_SESSION = "sess-coder-s2-924";

/**
 * Fake backend that surfaces a stable S2 session id and records every
 * dispatch's session mode + resumeSessionId for AC assertions.
 */
class PersistCoderBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  /** Each resumeSession via dispatch: [stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[string, string]> = [];
  private reviewCount = 0;

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    // Only reached if a backend wrapper routes here; dispatchWorker path records
    // resume via ctx. Keep for completeness.
    this.resumeSessionCalls.push([spec.id, sessionId]);
    return { kind: "coder", committed: true, commitsAdded: 1 };
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
    this.dispatched.push(`${spec.id}:${spec.kind}:${spec.session}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);

    if (typeof ctx.resumeSessionId === "string") {
      this.resumeSessionCalls.push([spec.id, ctx.resumeSessionId]);
    }

    if (spec.kind === "coder") {
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : spec.id === "S2"
            ? S2_SESSION
            : `sess-${spec.id}-fresh`;
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId,
      };
    }

    if (spec.kind === "reviewer") {
      this.reviewCount += 1;
      const findingsCount = this.reviewCount === 1 ? 1 : 0;
      const findings: Finding[] =
        findingsCount === 1
          ? [
              {
                severity: "high",
                category: "correctness",
                claim_quote: "x",
                location: "f.ts:1",
                suggested_fix: "fix it",
                action: "fix_now",
              },
            ]
          : [];
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings,
          findingsCount,
          ...(this.reviewCount > 1
            ? {
                priorFindingDispositions: [
                  {
                    identityKey: "correctness|f.ts:1|x",
                    status: "verified-closed",
                  },
                ],
              }
            : {}),
        },
        sessionId: `sess-review-${this.reviewCount}`,
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

describe("#924 S2/S5 single-iter + S5 resumes coder session", () => {
  it("S2 is single-iter fresh; S5 is single-iter resume of the S2 session", async () => {
    const backend = new PersistCoderBackend();
    const result = await runOrchestrator({ issueNumber: 924, backend });
    expect(result.status).toBe("success");

    const s2Idx = backend.specs.findIndex((s) => s.id === "S2");
    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s2Idx).toBeGreaterThanOrEqual(0);
    expect(s5Idx).toBeGreaterThanOrEqual(0);

    const s2 = backend.specs[s2Idx]!;
    const s5 = backend.specs[s5Idx]!;
    const s2Ctx = backend.ctxs[s2Idx]!;
    const s5Ctx = backend.ctxs[s5Idx]!;

    // Single-iteration seats (Ralph outer multi-iter retired).
    expect(s2.maxIter).toBe(1);
    expect(s5.maxIter).toBe(1);

    // S2 establishes the session.
    expect(s2.session).toBe("fresh");
    expect(s2Ctx.resumeSessionId).toBeUndefined();

    // S5 resumes the same session S2 surfaced.
    expect(s5.session).toBe("resume");
    expect(s5Ctx.resumeSessionId).toBe(S2_SESSION);
    expect(backend.resumeSessionCalls).toContainEqual(["S5", S2_SESSION]);
  });

  it("multi-round S5 keeps resuming the same coder session id", async () => {
    /**
     * Force two fix rounds: S3 open-count>0 → S5 → S6 open-count>0 → S5 → S6 clean.
     */
    class TwoFixRoundsBackend extends PersistCoderBackend {
      private reviews = 0;
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "reviewer") {
          this.dispatched.push(`${spec.id}:${spec.kind}:${spec.session}`);
          this.specs.push(spec);
          this.ctxs.push(ctx);
          this.reviews += 1;
          // r1 and r2 still open; r3 clean.
          const findingsCount = this.reviews <= 2 ? 1 : 0;
          const findings: Finding[] =
            findingsCount === 1
              ? [
                  {
                    severity: "high",
                    category: "correctness",
                    claim_quote: `round-${this.reviews}`,
                    location: `f.ts:${this.reviews}`,
                    suggested_fix: "fix",
                    action: "fix_now",
                  },
                ]
              : [];
          return {
            kind: "completed",
            output: { kind: "reviewer", findings, findingsCount },
            sessionId: `sess-review-${this.reviews}`,
          };
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const backend = new TwoFixRoundsBackend();
    const result = await runOrchestrator({ issueNumber: 924, backend });
    expect(result.status).toBe("success");

    const s5Resumes = backend.resumeSessionCalls.filter(([step]) => step === "S5");
    expect(s5Resumes.length).toBeGreaterThanOrEqual(2);
    for (const [, sessionId] of s5Resumes) {
      expect(sessionId).toBe(S2_SESSION);
    }
    const s5Specs = backend.specs.filter((s) => s.id === "S5");
    expect(s5Specs.every((s) => s.maxIter === 1)).toBe(true);
    expect(s5Specs.every((s) => s.session === "resume")).toBe(true);
  });
});

// sequential: nested real sc.run races on ~/.gitconfig locks under file-parallelism.
describe.sequential("#924 coder station-receipt Output.object (T2 schema)", () => {
  const cleanups: string[] = [];
  afterEach(() => {
    while (cleanups.length > 0) {
      const dir = cleanups.pop();
      if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
    }
  });

  const goodCompleted = {
    station: "coder" as const,
    status: "completed" as const,
    committed: true,
    commitsAdded: 1,
  };

  it("accepts a legal completed envelope via real sc.run (positive)", async () => {
    const { agent, result } = await runScriptedStructuredOutput({
      tag: CODER_RECEIPT_TAG,
      schema: coderStationReceiptSchema(),
      emissions: [{ body: JSON.stringify(goodCompleted) }],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-924-coder-good",
      cleanups,
    });
    expect(result.output).toMatchObject({
      station: "coder",
      status: "completed",
    });
    expect(agent.callCount).toBe(1);
    const decoded = decodeCoderEnvelope(result.output);
    expect(decoded.ok).toBe(true);
  });

  it("re-asks in-session when the envelope shape is illegal (negative)", async () => {
    // Bad: missing station/status traffic fields → SO re-ask → good on second try.
    const agentOut: { agent?: ScriptedAgent } = {};
    const { agent, result } = await runScriptedStructuredOutput({
      tag: CODER_RECEIPT_TAG,
      schema: coderStationReceiptSchema(),
      emissions: [
        { body: JSON.stringify({ committed: true, commitsAdded: 1 }) },
        { body: JSON.stringify(goodCompleted) },
      ],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-924-coder-reask",
      cleanups,
      agentOut,
    });
    expect(result.output).toMatchObject({ status: "completed", station: "coder" });
    expect(agent.callCount).toBe(2);
    expect(agent.resumedSessions).toEqual([undefined, "sess-924-coder-reask"]);
    expect(agentOut.agent?.callCount).toBe(2);
  });

  it("rejects illegal traffic shapes at the SO schema boundary (negative)", () => {
    // Pure schema pin — does not race on sc.run / ~/.gitconfig. Bad shapes are
    // what Sandcastle re-asks; the bad→good case above proves native re-ask.
    const schema = coderStationReceiptSchema();
    expect(schema.safeParse({ committed: true, commitsAdded: 1 }).success).toBe(
      false,
    );
    expect(schema.safeParse({ status: "maybe" }).success).toBe(false);
    expect(schema.safeParse({ station: "coder" }).success).toBe(false);
    expect(
      schema.safeParse({ station: "coder", status: "refused" }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        station: "coder",
        status: "completed",
        refusedFindingIdentityKeys: ["x"],
      }).success,
    ).toBe(false);
    expect(schema.safeParse(goodCompleted).success).toBe(true);
    expect(
      schema.safeParse({
        station: "coderFix",
        status: "refused",
        refusedFindingIdentityKeys: ["correctness|a.ts:1|claim"],
        cargoPointer: "artifacts/refuse.json",
      }).success,
    ).toBe(true);
  });
});

describe("#924 session lost degrades to fresh (run survives)", () => {
  it("classifyResumeError maps dead session to fresh-run (negative path stays alive)", () => {
    // Production resumeSession already falls back to runFreshAgentStep on this
    // class — the run does not die. Pin the pure classifier contract here.
    expect(
      classifyResumeError(
        new Error('resumeSession "sess-coder-s2-924" not found under /tmp/sc'),
      ),
    ).toEqual({ kind: "fresh-run" });
    expect(
      classifyResumeError(new Error("session expired while resuming")),
    ).toEqual({ kind: "fresh-run" });
    // Non-dead errors still propagate (must not mask SOE / auth as fresh).
    expect(
      classifyResumeError(new Error("401 unauthorized on resume")),
    ).toEqual({ kind: "propagate" });
  });
});

describe("#924 coder prompts teach legal envelope (T2 reference, no second copy)", () => {
  it("implement + fix prompts name station envelope traffic fields and T2 source", () => {
    const implement = readFileSync(
      join(PROMPTS_DIR, "coder_implement.md"),
      "utf8",
    );
    const fix = readFileSync(join(PROMPTS_DIR, "coder_fix.md"), "utf8");

    for (const text of [implement, fix]) {
      // Envelope traffic vocabulary (T2 / stationReceiptContracts).
      expect(text).toMatch(/station/);
      expect(text).toMatch(/status/);
      expect(text).toMatch(/completed|refused|escalate/);
      expect(text).toMatch(/refusedFindingIdentityKeys/);
      expect(text).toMatch(/cargoPointer/);
      // Point at the contract module — do not hand-copy a second schema.
      expect(text).toMatch(/stationReceiptContracts/);
      // Four reasons live in cargo body for the judge, not envelope schema.
      expect(text).toMatch(/违宪|unconstitutional|四理由/);
    }
  });
});
