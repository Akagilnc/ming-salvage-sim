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
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
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

    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
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
      if (findingsCount === 0) {
        return {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
          sessionId: `sess-review-${this.reviewCount}`,
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings,
          findingsCount,
          fixPacketBody: "fixture residual authored body",
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

// #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
describe("#924 coder station-receipt Output.object (T2 schema)", () => {
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

});
