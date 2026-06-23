/**
 * Family integrated-cmr gate = PURE SCHEDULER (corrected design, 2026-06-23).
 *
 * The runner (`verifyCmr.ts`) is a pure scheduler: it dispatches/resumes the cmr
 * REVIEWER worker, reads its verdict (converged | findings | escalate), and on
 * `findings` dispatches/resumes the coder-FIX worker, then loops back to the
 * reviewer. It contains ZERO drift logic, ZERO round counters, ZERO grade logic —
 * drift/convergence is the WORKER's judgment (the reviewer is RESUMABLE, so across
 * rounds it has continuity and itself emits `escalate` when it cannot converge; the
 * fix worker emits `escalate` when a finding is unfixable as stated).
 *
 *   - reviewer `converged` round 0 ⇒ ok:true, NO fix dispatched (止于 PR).
 *   - reviewer `findings` ⇒ resume coder-fix ⇒ resume reviewer `converged` ⇒ ok:true.
 *   - reviewer `escalate` (the WORKER judged it stuck — NOT a runner round count) ⇒
 *     escalateFamily, ok:false.
 *   - a coder-fix worker that escalates / commits nothing ⇒ escalateFamily, ok:false.
 *
 * The runner threads each worker's `WorkerResult.sessionId` into the SAME worker's
 * next dispatch as a `session:"resume"` + `resumeSessionId` (mirroring the
 * single-slice runner) so both workers resume across rounds.
 *
 * Driven entirely by a zero-container injected-seam fake (no real codex / container).
 */

import { describe, expect, it } from "vitest";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  MergeRequest,
} from "../../src/family/types.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

/** One recorded worker dispatch (the kind + the resume sessionId threaded in, if any). */
interface DispatchRecord {
  readonly kind: WorkerSpec["kind"];
  readonly session: WorkerSpec["session"];
  readonly resumeSessionId?: string;
  readonly cmrReason?: string;
}

/**
 * A scriptable family backend exercising the PURE-SCHEDULER loop via the unified
 * `dispatchWorker` seam. Each scripted function is fed the per-kind call index so a
 * test can return a different verdict per round (round 0 findings → fix → round 1
 * converged, etc.). Every dispatch is recorded (kind + the resume sessionId the
 * runner threaded in) so a test can assert the loop scheduled and resumed correctly.
 */
class SchedulerFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  private cmrRound = 0;
  private fixRound = 0;
  private shipRound = 0;

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (round: number) => WorkerResult;
      fix?: (round: number) => WorkerResult;
      ship?: (round: number) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return this.script.verify?.(req) ?? { ok: true };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }

  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      ...(ctx.resumeSessionId !== undefined ? { resumeSessionId: ctx.resumeSessionId } : {}),
      ...(ctx.cmrReason !== undefined ? { cmrReason: ctx.cmrReason } : {}),
    });
    if (spec.kind === "cmr") {
      const round = this.cmrRound++;
      return (
        this.script.cmr?.(round) ?? {
          kind: "completed",
          output: { kind: "cmr", converged: true },
          sessionId: `cmr-sess-${round}`,
        }
      );
    }
    if (spec.kind === "coder") {
      const round = this.fixRound++;
      return (
        this.script.fix?.(round) ?? {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: `fix-sess-${round}`,
        }
      );
    }
    if (spec.kind === "ship") {
      const round = this.shipRound++;
      return (
        this.script.ship?.(round) ?? {
          kind: "completed",
          output: { kind: "ship", branch: ctx.familyBase!, status: "pr_opened", pr: `pr://${ctx.familyBase}` },
          sessionId: `ship-sess-${round}`,
        }
      );
    }
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

describe("family integrated-cmr gate = PURE SCHEDULER (worker judges drift, runner does not)", () => {
  it("reviewer CONVERGED round 0 ⇒ ok:true, NO fix dispatched (the happy path)", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "completed", output: { kind: "cmr", converged: true }, sessionId: "c0" }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Exactly one cmr dispatch, NO coder-fix, NO escalate; then the ship worker.
    expect(backend.dispatches.filter((d) => d.kind === "cmr")).toHaveLength(1);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(0);
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("reviewer FINDINGS ⇒ resume coder-fix ⇒ resume reviewer CONVERGED ⇒ ok:true (loop ran, fix once)", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: (round) =>
        round === 0
          ? {
              kind: "completed",
              output: { kind: "cmr", converged: false, reason: "field-name mismatch: region.cannon vs region.cityCannon" },
              sessionId: "cmr-A",
            }
          : { kind: "completed", output: { kind: "cmr", converged: true }, sessionId: "cmr-B" },
      fix: () => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "fix-A",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // cmr ran TWICE (round 0 findings, round 1 converged) with a fix BETWEEN them.
    expect(backend.dispatches.filter((d) => d.kind === "cmr")).toHaveLength(2);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(1);
    // The fix worker received the round's non-convergence reason as its focus.
    expect(backend.dispatches.find((d) => d.kind === "coder")?.cmrReason).toContain("region.cannon");
    // NO escalate (it is not escalate-on-first-finding).
    expect(backend.escalations).toEqual([]);
    // RESUME THREADING: the 2nd cmr dispatch resumes the 1st cmr worker's session
    // (continuity → the worker judges drift), not a fresh one.
    const cmrDispatches = backend.dispatches.filter((d) => d.kind === "cmr");
    expect(cmrDispatches[1]?.session).toBe("resume");
    expect(cmrDispatches[1]?.resumeSessionId).toBe("cmr-A");
  });

  it("reviewer ESCALATE (the WORKER judged it cannot converge) ⇒ escalateFamily, ok:false — the runner did NOT count rounds", async () => {
    const backend = new SchedulerFamilyBackend({
      // The reviewer worker — RESUMABLE, judging drift across its own rounds —
      // emits escalate. The runner just relays it; it never counts rounds itself.
      cmr: () => ({
        kind: "escalated",
        escalation: {
          reason: "field-name mismatch: region.cannon vs region.cityCannon",
          diagnosis: "the fix has not changed what the reviewers see across rounds — drift",
        },
        sessionId: "cmr-stuck",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("region.cannon");
    // The runner escalated WITHOUT ever dispatching a fix or a ship (the worker's
    // verdict was escalate on its first return — no runner round counting).
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("a coder-fix worker that itself ESCALATES ⇒ escalateFamily (cannot make progress), ok:false, NO ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: { kind: "cmr", converged: false, reason: "cross-slice contract drift" },
        sessionId: "cmr-x",
      }),
      fix: () => ({
        kind: "escalated",
        escalation: { reason: "finding conflicts with the epic spec", diagnosis: "needs a human design call" },
        sessionId: "fix-x",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toMatch(/conflicts with the epic spec|human design/i);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("a coder-fix worker that commits NOTHING ⇒ escalateFamily (no progress possible), ok:false", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: { kind: "cmr", converged: false, reason: "seam drift" },
        sessionId: "cmr-y",
      }),
      fix: () => ({
        kind: "completed",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
        sessionId: "fix-y",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("seam drift");
  });

  it("multi-round: findings → fix → findings → fix → converged ⇒ ok:true (the worker, resuming, decides when it is done)", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: (round) => {
        if (round === 0)
          return { kind: "completed", output: { kind: "cmr", converged: false, reason: "seam A" }, sessionId: "ca" };
        if (round === 1)
          return { kind: "completed", output: { kind: "cmr", converged: false, reason: "seam B" }, sessionId: "cb" };
        return { kind: "completed", output: { kind: "cmr", converged: true }, sessionId: "cc" };
      },
      fix: (round) => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: `fix-${round}`,
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.filter((d) => d.kind === "cmr")).toHaveLength(3);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(2);
    expect(backend.escalations).toEqual([]);
    // BOTH workers resume their own session across rounds (continuity).
    const fixDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(fixDispatches[1]?.session).toBe("resume");
    expect(fixDispatches[1]?.resumeSessionId).toBe("fix-0");
  });
});

describe("the runner contains NO drift constant / round-counter / grade logic", () => {
  it("verifyCmr.ts source has no NO_PROGRESS_LIMIT / noProgressStreak / prevReasonKey", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const src = readFileSync(
      fileURLToPath(new URL("../../src/family/verifyCmr.ts", import.meta.url)),
      "utf8",
    );
    expect(src).not.toMatch(/NO_PROGRESS_LIMIT/);
    expect(src).not.toMatch(/noProgressStreak/);
    expect(src).not.toMatch(/prevReasonKey/);
  });
});
