/**
 * Family integrated-cmr gate = PURE SCHEDULER (corrected design, ADR 0026
 * 2026-06-24).
 *
 * The runner (`verifyCmr.ts`) is a pure scheduler: it dispatches ONE cmr WORKER,
 * reads its TERMINAL verdict (converged | escalate), and acts:
 *   - converged ⇒ the worker ALREADY fixed every cross-slice finding inside its
 *     own memory-bearing session (it IS the fixer) and the family base now holds
 *     the fixes ⇒ dispatch the ship worker (止于 PR), ok:true.
 *   - escalate ⇒ the worker judged it cannot converge (drift / architectural
 *     rework) ⇒ escalateFamily, ok:false, NO ship.
 *   - a `completed` cmr that is NOT converged (the worker ended its internal loop
 *     without converging AND without escalating — a contract slip) ⇒ fail-safe
 *     escalateFamily with the reason, ok:false, NO ship.
 *   - a malformed / crash result ⇒ recordAborted + INCOMPLETE_GATE.
 *
 * The corrected design (ADR 0026): the cmr worker is a SINGLE memory-bearing
 * `sc.run` session that runs the WHOLE review → grade → fix → re-review loop
 * INTERNALLY (the `ak-cross-m-review` skill drives it; only the 3 review LEGS are
 * fresh each round). So the runner dispatches it ONCE and never loops. There is
 * NO separate coder-fix worker dispatched by the runner, NO runner round-loop, NO
 * priorFindings/cmrReason threaded between fresh workers, ZERO drift/grade/round
 * logic in the runner.
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

/** One recorded worker dispatch (the kind + the session mode). */
interface DispatchRecord {
  readonly kind: WorkerSpec["kind"];
  readonly session: WorkerSpec["session"];
  readonly cmrPass?: DispatchContext["cmrPass"];
}

/**
 * A scriptable family backend exercising the PURE-SCHEDULER dispatch via the
 * unified `dispatchWorker` seam. The cmr worker is dispatched exactly once; every
 * dispatch is recorded so a test can assert the runner scheduled ONE cmr worker,
 * never a coder-fix worker, and only ships on a converged verdict.
 */
class SchedulerFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: DispatchRecord[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  private shipRound = 0;

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: () => WorkerResult;
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
    this.dispatches.push({ kind: spec.kind, session: spec.session, cmrPass: ctx.cmrPass });
    if (spec.kind === "cmr") {
      return (
        this.script.cmr?.() ?? {
          kind: "completed",
          output: { kind: "cmr", converged: true },
        }
      );
    }
    if (spec.kind === "ship") {
      const round = this.shipRound++;
      return (
        this.script.ship?.(round) ?? {
          kind: "completed",
          output: { kind: "ship", branch: ctx.familyBase!, status: "pr_opened", pr: `pr://${ctx.familyBase}` },
        }
      );
    }
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

describe("family integrated-cmr gate = PURE SCHEDULER (runner-dispatched cmr passes, no runner fix loop)", () => {
  it("cmr workers CONVERGED ⇒ ok:true, completeness + correctness dispatches, NO coder-fix, then ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "completed", output: { kind: "cmr", converged: true } }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Exactly two CMR passes, NEVER a coder-fix worker (the pass workers own their
    // convergence; the runner only gates step5 → step6), then ship.
    expect(backend.dispatches.filter((d) => d.kind === "cmr").map((d) => d.cmrPass)).toEqual([
      "completeness",
      "correctness",
    ]);
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toHaveLength(0);
    expect(backend.escalations).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toHaveLength(1);
  });

  it("cmr worker ESCALATE (it judged it cannot converge) ⇒ escalateFamily, ok:false, NO ship, NO fix", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "escalated",
        escalation: {
          reason: "field-name mismatch: region.cannon vs region.cityCannon",
          diagnosis: "the fix loop hit drift across rounds — needs an architectural call",
        },
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
    // The runner escalated WITHOUT ever dispatching a fix or a ship.
    expect(backend.dispatches.filter((d) => d.kind === "coder")).toEqual([]);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("cmr worker COMPLETED but NOT converged (no escalate) ⇒ fail-safe escalateFamily with the reason, ok:false, NO ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({
        kind: "completed",
        output: { kind: "cmr", converged: false, reason: "cross-slice contract drift left unresolved" },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("contract drift");
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("cmr worker MALFORMED / crash ⇒ recordAborted + INCOMPLETE_GATE (ok:false), NO ship", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "malformed", reason: "no parseable CMR-VERDICT" }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    // A malformed cmr persists a DURABLE aborted ledger entry (recordDurableAbort →
    // appendFamilyLedger), so a resume doesn't re-run the same failing gate blind.
    expect(backend.ledger.some((e) => e.status === "aborted")).toBe(true);
    expect(backend.dispatches.filter((d) => d.kind === "ship")).toEqual([]);
  });

  it("the cmr worker dispatch is FRESH (a new memory-bearing session, not a resume) — NO resume plumbing", async () => {
    const backend = new SchedulerFamilyBackend({
      cmr: () => ({ kind: "completed", output: { kind: "cmr", converged: true } }),
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    const cmrDispatch = backend.dispatches.find((d) => d.kind === "cmr");
    expect(cmrDispatch?.session).toBe("fresh");
  });
});

describe("the runner contains NO drift constant / round-counter / grade logic / fix loop", () => {
  it("verifyCmr.ts source has no round-loop, no NO_PROGRESS_LIMIT, no priorFindings/cmrReason threading", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const src = readFileSync(
      fileURLToPath(new URL("../../src/family/verifyCmr.ts", import.meta.url)),
      "utf8",
    );
    // No runner-level round counter / drift constant (the worker judges drift).
    expect(src).not.toMatch(/NO_PROGRESS_LIMIT/);
    expect(src).not.toMatch(/noProgressStreak/);
    expect(src).not.toMatch(/prevReasonKey/);
    // No runner round-loop dispatching reviewer→fix→reviewer.
    expect(src).not.toMatch(/for\s*\(;;\)/);
    // No continuity-as-data threading between fresh workers (the worker has memory
    // within its own session — the runner does not simulate it with data).
    expect(src).not.toMatch(/priorFindings/);
    expect(src).not.toMatch(/cmrReason/);
    // No coder-fix worker dispatched by the runner (the fix is inside the cmr worker).
    expect(src).not.toMatch(/familyCoderFixWorkerSpec/);
    // No resume-session plumbing for the cmr worker.
    expect(src).not.toMatch(/resumeSessionId:/);
  });
});
