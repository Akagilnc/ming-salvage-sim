/**
 * #255 — Idempotent resume tests (RED → GREEN).
 *
 * Crash-resume and escalate-resume share ONE machine: when the same issue is
 * re-fed and a resident slice branch/worktree already exists (crash residue or
 * escalate residue), the runner reuses the existing HEAD and continues from the
 * step recorded in the ledger — it does NOT re-cut from S0, does NOT re-run
 * already-completed steps, and does NOT re-burn the LLM on prior steps.
 *
 * Acceptance criteria (issue #255):
 *   AC1 — fake Backend reports "branch/worktree already exists" → assert reuse
 *         of existing HEAD (no re-cut); before reuse, the residue-clean action
 *         (reset --hard / clean -fd / worktree prune) is invoked while committed
 *         progress is preserved.
 *   AC2 — backend call dies mid-run → "re-feed same issue" → assert crash-resume
 *         path: read ledger, continue from the recorded next step, lose no
 *         committed progress, do not re-burn the LLM from scratch.
 *   AC3 — escalate blocker, human gives an answer, re-feed → assert it goes
 *         through Sandcastle-native `resumeSession` (carrying the ledger's
 *         sessionId) to resume the real agent session — SAME machine as
 *         crash-resume, continuing from the breakpoint, not re-running from S0.
 *   AC4 — assert recovery reads the ledger (incl. sessionId) + branch HEAD to
 *         decide the next step, NOT any in-memory / LLM state.
 *
 * Strategy: extend the Backend fake with
 *   - findResumeState(issueNumber) → ResumeState | undefined  (the host-side
 *     check that detects an existing resident worktree + persisted ledger)
 *   - cleanResidue(worktree)                                  (reset/clean/prune)
 *   - resumeSession(spec, worktree, sessionId)                (Sandcastle-native)
 * A fresh run returns undefined from findResumeState (no residue) → behaves
 * exactly like before. A resume run pre-loads a ResumeState whose ledger stops
 * at step k, then asserts the runner reuses, cleans, and continues from k+1.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";

import { runOrchestrator } from "../../src/runner.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { route } from "../../src/route.js";
import { parseLedgerJsonl } from "../../src/realBackend.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  DispatchContext,
  StepId,
  StepOutput,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

// ─── shared fixtures ──────────────────────────────────────────────────────────

export const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-255",
  base: "main",
  path: "/resident/worktrees/issue-255",
};

export const STATE_DIR = "/resident/worktrees/.ledger-255";

export const CLAIMED_FIXED_FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "Do not rely on omitting a finding to mean it is closed.",
  location: "orchestrator/src/runner.ts:1061",
  suggested_fix: "Replay prior S4 adjudication state on resume.",
  action: "fix_now",
};

export const CLAIMED_FIXED_KEY =
  "correctness|orchestrator/src/runner.ts:1061|do not rely on omitting a finding to mean it is closed.";

/** Build a persisted ledger entry (the resume truth on disk). */
export function entry(
  step: StepId,
  output?: StepOutput,
  sessionId = "session-prior",
  branchHEAD = "deadbeefcommitsha",
): PersistentLedgerEntry {
  return {
    step,
    sessionId,
    prompt_hash: `hash-${step}`,
    branchHEAD,
    ts: "2026-06-21T00:00:00.000Z",
    ...(output !== undefined ? { output } : {}),
  };
}

/** Build a terminal S8 entry tagged with its handoff status (#255). */
export function s8(handoffStatus: "success" | "escalate" | "error"): PersistentLedgerEntry {
  return {
    step: "S8",
    sessionId: "session-prior",
    prompt_hash: "hash-S8",
    branchHEAD: "deadbeefcommitsha",
    ts: "2026-06-21T00:00:00.000Z",
    handoffStatus,
  };
}

export function coderProtocolFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder step stdout carried no <coder>...</coder> tag - the coder must emit its structured result in a <coder> tag.",
      repairHint:
        "Inspect the landed commit and resume from the next step if HEAD advanced.",
    },
  };
}

export function malformedCoderPayloadFailureS8(): PersistentLedgerEntry {
  return {
    ...s8("error"),
    stopSummary: {
      reason: "contract_drift",
      summary:
        "realBackend: coder must emit its structured result in a <coder> tag; the payload was malformed.",
      repairHint: "Fix the malformed coder payload instead of fabricating a landed coder output.",
    },
  };
}

export function escalationAnswer(
  forStep: StepId,
  answer: string,
  note?: string,
): PersistentLedgerEntry {
  return {
    ...entry(forStep),
    event: "escalation_answered",
    forStep,
    answer,
    source: "human",
    ...(note !== undefined ? { note } : {}),
  };
}

/**
 * A configurable resume-aware fake Backend.
 *
 * - If `resumeState` is provided, findResumeState returns it (the issue has
 *   residue: existing worktree + persisted ledger). Otherwise it returns
 *   undefined (fresh run).
 * - Records cleanResidue / prepareWorktree / resumeSession / runStep calls so
 *   the tests can assert reuse-vs-recut and resume-vs-fresh-session.
 */
export class ResumeBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  readonly commitCountsBetween = new Map<string, number>();
  /** Each resumeSession call: [stepId, sessionId]. */
  readonly resumeSessionCalls: Array<[string, string]> = [];
  prepareWorktreeCount = 0;
  cleanResidueCount = 0;
  pushCount = 0;

  constructor(private readonly resumeState?: ResumeState) {}

  async findResumeState(
    issueNumber: number,
  ): Promise<ResumeState | undefined> {
    this.calls.push(`findResumeState(${issueNumber})`);
    return this.resumeState;
  }

  async cleanResidue(_worktree: WorktreeHandle): Promise<void> {
    this.calls.push("cleanResidue");
    this.cleanResidueCount += 1;
  }

  async resumeSession(
    spec: StepSpec,
    _worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput> {
    this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
    this.resumeSessionCalls.push([spec.id, sessionId]);
    this.runStepIds.push(spec.id);
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    this.prepareWorktreeCount += 1;
    return WORKTREE;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(
    spec: StepSpec,
    _worktree: WorktreeHandle,
  ): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async countCommitsBetween(
    _worktree: WorktreeHandle,
    fromHead: string,
    toHead: string,
  ): Promise<number> {
    this.calls.push(`countCommitsBetween(${fromHead}, ${toHead})`);
    return this.commitCountsBetween.get(`${fromHead}..${toHead}`) ?? 1;
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.ledgerWrites.push(entry);
  }

}

export class DispatchRecordingResumeBackend extends ResumeBackend {
  readonly dispatchSpecs: WorkerSpec[] = [];
  readonly dispatchContexts: DispatchContext[] = [];

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.dispatchSpecs.push(spec);
    this.dispatchContexts.push(ctx);

    const stepSpec = spec as unknown as StepSpec;
    if (spec.id === "S6") {
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: CLAIMED_FIXED_KEY, status: "verified-closed" },
          ],
        },
      };
    }
    const output =
      ctx.resumeSessionId !== undefined
        ? await this.resumeSession(stepSpec, ctx.worktree!, ctx.resumeSessionId)
        : await this.runStep(stepSpec, ctx.worktree!);
    return { kind: "completed", output };
  }
}

export class MissingCoderTagBackend extends ResumeBackend {
  override async runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
  ): Promise<StepOutput> {
    if (spec.id === "S2") {
      throw new Error(
        "realBackend: coder step stdout carried no <coder>…</coder> tag — the coder must emit its structured result in a <coder> tag.",
      );
    }
    return super.runStep(spec, worktree);
  }
}
