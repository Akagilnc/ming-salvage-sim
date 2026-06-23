/**
 * Family integrated-cmr gate = PURE SCHEDULER (corrected design, ADR 0026).
 *
 * The runner (`verifyCmr.ts`) is a pure scheduler: it dispatches the cmr REVIEWER
 * worker FRESH each round, reads its verdict (converged | findings | escalate), and
 * on `findings` dispatches the coder-FIX worker FRESH, then loops back to the
 * reviewer. It contains ZERO drift logic, ZERO round counters, ZERO grade logic —
 * drift/convergence is the WORKER's judgment (the reviewer re-reviews the WHOLE diff
 * with fresh eyes each round, informed by the PRIOR round's findings passed as DATA;
 * it itself emits `escalate` when it cannot converge; the fix worker emits
 * `escalate` when a finding is unfixable as stated).
 *
 *   - reviewer `converged` round 0 ⇒ ok:true, NO fix dispatched (止于 PR).
 *   - reviewer `findings` ⇒ fresh coder-fix ⇒ fresh reviewer `converged` ⇒ ok:true.
 *   - reviewer `escalate` (the WORKER judged it stuck — NOT a runner round count) ⇒
 *     escalateFamily, ok:false.
 *   - a coder-fix worker that escalates / commits nothing ⇒ escalateFamily, ok:false.
 *
 * ADR 0026 (line 20): the reviewer (cmr) and the coder-fix worker dispatch FRESH
 * each round — NEVER the `resumeSession` (session:"resume") crash/escalate path,
 * which skips git-truthing. Continuity comes from passing the PRIOR round's cmr
 * findings/verdict into the NEXT reviewer dispatch as DATA (DispatchContext
 * `priorFindings`), and the round's non-convergence reason into the coder-fix
 * dispatch (`cmrReason`). No worker resumes.
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

/** One recorded worker dispatch (the kind + the DATA threaded in, if any). */
interface DispatchRecord {
  readonly kind: WorkerSpec["kind"];
  readonly session: WorkerSpec["session"];
  readonly resumeSessionId?: string;
  readonly cmrReason?: string;
  readonly priorFindings?: string;
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
      ...(ctx.priorFindings !== undefined ? { priorFindings: ctx.priorFindings } : {}),
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

  it("reviewer FINDINGS ⇒ fresh coder-fix ⇒ fresh reviewer CONVERGED ⇒ ok:true (loop ran, fix once)", async () => {
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
    // ADR 0026: BOTH the cmr reviewer and the coder-fix worker dispatch FRESH each
    // round — NEVER the session:"resume" crash/escalate path. NO worker resumes.
    expect(backend.dispatches.every((d) => d.session === "fresh")).toBe(true);
    expect(backend.dispatches.every((d) => d.resumeSessionId === undefined)).toBe(true);
    // CONTINUITY-AS-DATA: the 2nd (round-1) cmr dispatch carries the PRIOR round's
    // findings/verdict as DATA (priorFindings), NOT via a resumed session.
    const cmrDispatches = backend.dispatches.filter((d) => d.kind === "cmr");
    expect(cmrDispatches[1]?.session).toBe("fresh");
    expect(cmrDispatches[1]?.priorFindings).toContain("region.cannon");
    // The round-0 cmr dispatch has NO prior findings (it is the first review).
    expect(cmrDispatches[0]?.priorFindings).toBeUndefined();
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
    // ADR 0026: every dispatch is FRESH — NO worker resumes across rounds.
    expect(backend.dispatches.every((d) => d.session === "fresh")).toBe(true);
    expect(backend.dispatches.every((d) => d.resumeSessionId === undefined)).toBe(true);
    // CONTINUITY-AS-DATA: each later reviewer round carries the prior round's
    // findings (seam A then seam B) as DATA; each fix round carries its reason.
    const cmrDispatches = backend.dispatches.filter((d) => d.kind === "cmr");
    expect(cmrDispatches[1]?.priorFindings).toContain("seam A");
    expect(cmrDispatches[2]?.priorFindings).toContain("seam B");
    const fixDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(fixDispatches[0]?.cmrReason).toContain("seam A");
    expect(fixDispatches[1]?.cmrReason).toContain("seam B");
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

describe("ADR 0026: the cmr/coder-fix loop dispatches FRESH each round (NO resume)", () => {
  it("verifyCmr.ts threads NO resumeSessionId / session:'resume' for these two workers", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const src = readFileSync(
      fileURLToPath(new URL("../../src/family/verifyCmr.ts", import.meta.url)),
      "utf8",
    );
    // The corrected design: NO resume-session plumbing for the cmr reviewer / coder-fix
    // workers. Continuity is DATA (priorFindings / cmrReason), not a resumed session
    // (ADR 0026 line 20: 评审类每轮 fresh; resumeSession is for crash/escalate ONLY).
    expect(src).not.toMatch(/cmrResumeSessionId/);
    expect(src).not.toMatch(/fixResumeSessionId/);
    // No resumeSessionId field threaded onto any dispatch context in this file.
    expect(src).not.toMatch(/resumeSessionId:/);
    // No worker spec dispatched in the "resume" session mode (both are always fresh).
    // The specs are constructed with the literal "fresh"; "resume" appears only in
    // EXPLANATORY comments (describing the path we deliberately do NOT take), never as
    // a `cmrWorkerSpec(...)` / `familyCoderFixWorkerSpec(...)` argument.
    expect(src).not.toMatch(/WorkerSpec\([^)]*"resume"/);
    expect(src).not.toMatch(/\?\s*"resume"\s*:\s*"fresh"/);
    // Continuity-as-data IS present (the prior round's findings threaded forward).
    expect(src).toMatch(/priorFindings/);
  });
});
