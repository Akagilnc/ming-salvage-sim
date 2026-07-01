/**
 * #296 — the verify-cmr HOOK BODY (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * #293 立 the seam (a no-op called at the wave barrier + end-of-run, with phase +
 * context, the spine acting on `ok`). #296 fills the BODY behind that same
 * `runVerifyCmr(input)` signature — it never touches the spine call sites:
 *
 *   - "wave" phase  → family verify (typecheck + unit tests), FAIL-FAST: red ⇒
 *                     `{ok:false}` (spine aborts before the next wave) + an
 *                     `aborted` ledger event (decision 3④/5).
 *   - "final" phase → full verify, then the integrated cross-model cmr 承重闸;
 *                     cmr not-converged ⇒ escalate续跑 (#298) + `{ok:false}`;
 *                     all green ⇒ open the family PR (止于 PR, decision 4) +
 *                     `{ok:true}`.
 *
 * The verify / cmr / PR / abort / escalate capabilities are reached through the
 * `FamilyBackend` seam (the input the frozen spine passes is `{phase, familyBase,
 * familyBackend}`), as OPTIONAL methods — a backend that does not implement them
 * (the #293 no-op default) yields the no-op `{ok:true, ran:false}`, so the spine's
 * existing default path is untouched. Everything is driven by a zero-container
 * fake — no real codex / container / push.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { meetsCmrFloor, runVerifyCmr } from "../../src/family/verifyCmr.js";
import { activeModelRoute, modelRouteFingerprint } from "../../src/modelRoutes.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  MergeRequest,
} from "../../src/family/types.js";
import type { DispatchContext, WorkerResult, WorkerSpec } from "../../src/types.js";

afterEach(() => {
  vi.unstubAllEnvs();
});

/**
 * A full family backend fake with the #296 verify/cmr/PR/abort/escalate
 * capabilities, scriptable per call. Records every interaction so the test can
 * assert what ran (no real container / codex / push).
 */
class CapableFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];
  readonly readFamilyHeadCalls: string[] = [];
  currentFamilyHead = "head-1";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
      pr?: (req: OpenFamilyPrRequest) => OpenFamilyPrResult;
    } = {},
  ) {}

  // ── core merge/ledger seam (unchanged from #293) ──
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(familyBase: string): Promise<string> {
    this.readFamilyHeadCalls.push(familyBase);
    return this.currentFamilyHead;
  }

  // ── #296 verify/cmr/PR capabilities (optional methods) ──
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    return this.script.cmr?.(req) ?? { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return this.script.pr?.(req) ?? {
      url: `pr://${req.familyBase}`,
      prHead: this.currentFamilyHead,
    };
  }

  // ── #298-owned abort/escalate seam (minimal shapes #296 only CALLS) ──
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
}

function currentRouteFingerprint(): string {
  return modelRouteFingerprint(activeModelRoute());
}

/** A #293-era backend WITHOUT the new optional methods (the no-op default). */
class BareFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

describe("#296 verify-cmr hook body — wave phase (fail-fast verify)", () => {
  it("GREEN wave verify → ok:true, ran:true; verify run against the family base; no abort", async () => {
    const backend = new CapableFamilyBackend({ verify: () => ({ ok: true }) });
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Verify ran against the family base, scoped to the wave phase.
    expect(backend.verifyCalls).toEqual([{ phase: "wave", familyBase: "family/291-base" }]);
    // No cmr at the wave barrier (that is the final phase), no abort.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.aborted).toEqual([]);
  });

  it("RED wave verify → ok:false (spine fails-fast), ran:true, and an `aborted` ledger event with the error package", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "tsc: TS2322 in regionApply" } }),
    });
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // ok:false → the spine aborts before the next wave (decision 3④).
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    // The red verify writes an `aborted` event carrying the error package +
    // family base (decision 3④/5; the schema is #298's, #296 only calls it).
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("wave");
    expect(backend.aborted[0]?.familyBase).toBe("family/291-base");
    expect(backend.aborted[0]?.errorPackage.reason).toContain("TS2322");
    // No PR / cmr on a red wave.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
  });
});

describe("#296 verify-cmr hook body — final phase (full verify → cmr → PR)", () => {
  it("ADR0032 pure floor predicate covers strong and non-strong survival combinations", () => {
    expect(meetsCmrFloor(["gpt-5.5"])).toBe(true);
    expect(meetsCmrFloor(["opus"])).toBe(true);
    expect(meetsCmrFloor(["agy"])).toBe(false);
    expect(meetsCmrFloor(["agy", "gemini"])).toBe(false);
    expect(meetsCmrFloor(["glm", "haiku", "spark"])).toBe(false);
  });

  it("ADR0032 floor: agy-only survived CMR ⇒ escalate, even when the worker reports converged", async () => {
    class AgyOnlyCmrBackend extends BareFamilyBackend {
      readonly escalations: FamilyEscalation[] = [];
      readonly prCalls: OpenFamilyPrRequest[] = [];

      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }

      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              cmrPass: ctx.cmrPass,
              converged: true,
              successfulLegs: ["agy"],
              skippedLegs: [
                { slug: "opus", reason: "auth unavailable" },
                { slug: "gpt-5.5", reason: "auth unavailable" },
              ],
            },
          };
        }
        this.prCalls.push({ familyBase: ctx.familyBase! });
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: ctx.familyBase!,
            status: "pr_opened",
            pr: `pr://${ctx.familyBase!}`,
          },
        };
      }

      async escalateFamily(esc: FamilyEscalation): Promise<void> {
        this.escalations.push(esc);
      }
    }

    const backend = new AgyOnlyCmrBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations[0]?.reason).toContain("floor");
    expect(backend.escalations[0]?.reason).toContain("agy");
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("floor"),
    }));
  });

  it("rejects route-undeclared strong legs before applying the CMR floor", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["agy", "opus"],
        skippedLegs: [{ slug: "gpt-5.5", reason: "auth unavailable" }],
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toEqual([]);
    expect(backend.escalations[0]?.reason).toContain("not declared");
    expect(backend.escalations[0]?.reason).toContain("opus");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      reason: expect.stringContaining("not declared"),
    }));
  });

  it("fingerprints the resolved route without re-throwing an already accepted tight-route violation", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.stubEnv("ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS", "opus");
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus"] }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toEqual([
      expect.objectContaining({
        cmrPass: "completeness",
        routeFingerprint: expect.stringContaining('"routeName":"claude-tight"'),
      }),
      expect.objectContaining({
        cmrPass: "correctness",
        routeFingerprint: expect.stringContaining('"routeName":"claude-tight"'),
      }),
    ]);
  });

  it("GREEN full verify + CONVERGED cmr → open the family PR, ok:true ran:true (止于 PR)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Order: full verify FIRST, then step5 completeness, step6 correctness, then PR.
    expect(backend.verifyCalls).toEqual([{ phase: "final", familyBase: "family/291-base" }]);
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
    // 止于 PR: the PR is opened (decision 4) — but NOT merged (no merge call here).
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.escalations).toEqual([]);
    // online review r2 (codex P1): a durable `shipped` terminal marker is persisted
    // carrying the family PR URL, so a resume sees the family is already delivered
    // and the spine's guard does not re-run the barrier / re-ship.
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      routeFingerprint: currentRouteFingerprint(),
    }));
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: "head-1",
      routeFingerprint: currentRouteFingerprint(),
    }));
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr: "pr://family/291-base",
      familyHeadAfter: "head-1",
    }));
  });

  it("resume skips a CMR pass that already passed for the current family HEAD", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      routeFingerprint: currentRouteFingerprint(),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
  });

  it("resume skips both CMR passes that already passed for the current family HEAD and ships", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
  });

  it("resume resolves a ref-like familyHeadAfter before checking existing CMR pass markers", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.currentFamilyHead = "head-1";
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "refs/heads/family/291-base",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
  });

  it("does not persist a shipped marker when the post-ship family HEAD cannot be resolved", async () => {
    class ReadHeadFailureBackend extends CapableFamilyBackend {
      override async readFamilyHead(familyBase: string): Promise<string> {
        this.readFamilyHeadCalls.push(familyBase);
        throw new Error("git rev-parse failed");
      }
    }
    const backend = new ReadHeadFailureBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "head-1",
        routeFingerprint: currentRouteFingerprint(),
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason:
        "family ship worker opened a PR, but the current family HEAD could not be resolved; refusing to persist a stale shipped marker",
      familyHeadAfter: "head-1",
    }));
  });

  it("resume reruns a CMR pass when the family HEAD advanced after the pass marker", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "old-head",
      routeFingerprint: currentRouteFingerprint(),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "new-head",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
  });

  it("resume reruns both passes when routeFingerprint changes even if the family HEAD matches", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["gpt-5.5", "agy"] }),
    });
    const normalFingerprint = currentRouteFingerprint();
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: normalFingerprint,
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "head-1",
        routeFingerprint: normalFingerprint,
      },
    );
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
  });

  it("resume reruns both passes when old completeness and correctness markers are for a stale HEAD", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "old-head",
        routeFingerprint: currentRouteFingerprint(),
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "old-head",
        routeFingerprint: currentRouteFingerprint(),
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "new-head",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
  });

  it("GREEN full verify + CONVERGED cmr records CMR passes with the family HEAD they reviewed", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      routeFingerprint: currentRouteFingerprint(),
    }));
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: "head-1",
      routeFingerprint: currentRouteFingerprint(),
    }));
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr: "pr://family/291-base",
      familyHeadAfter: "head-1",
    }));
  });

  it("records the post-CMR-worker family HEAD and uses it for the next pass resume guard", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => {
        if (req.cmrPass === "completeness") {
          backend.currentFamilyHead = "head-after-cmr-fix";
        }
        return { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
      },
    });
    backend.currentFamilyHead = "head-before-cmr";
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: "head-after-cmr-fix",
      routeFingerprint: currentRouteFingerprint(),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-before-cmr",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-after-cmr-fix",
      routeFingerprint: currentRouteFingerprint(),
    }));
    expect(
      backend.ledger.filter(
        (e) => e.status === "cmr_passed" && e.cmrPass === "correctness",
      ),
    ).toHaveLength(1);
    expect(backend.readFamilyHeadCalls).toEqual([
      "family/291-base",
      "family/291-base",
      "family/291-base",
      "family/291-base",
    ]);
  });

  it("RED full verify → ok:false, ran:true, aborted event, and NO cmr / NO PR (verify gates cmr)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "vitest: 3 failed" } }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("final");
    // cmr only runs on GREEN verify; a red final verify never reaches cmr or PR.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    // online review r2 (codex P1): NO `shipped` marker on a failed barrier — only a
    // real opened PR persists it, so a resume re-runs the barrier (does not skip).
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("GREEN verify but NOT-CONVERGED cmr → escalate续跑 (#298), ok:false, ran:true, NO PR", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: false,
        reason: "field-name mismatch across slices: region.cannon vs region.cityCannon",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Not converged → the load-bearing cmr gate is red; the spine returns
    // verify_failed (止于 PR is NOT reached).
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    // Escalate续跑 (#298): #296 only CALLS the escalate seam, carrying the cmr
    // non-convergence reason.
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("mismatch");
    // No PR while cmr is unresolved.
    expect(backend.prCalls).toEqual([]);
  });

  it("ESCALATED cmr worker → durable final aborted entry includes the cmr pass before escalate", async () => {
    class EscalatingCmrWorkerBackend extends BareFamilyBackend {
      readonly escalations: FamilyEscalation[] = [];
      currentFamilyHead = "head-after-final-verify";

      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }

      async readFamilyHead(_familyBase: string): Promise<string> {
        return this.currentFamilyHead;
      }

      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.currentFamilyHead = "head-after-cmr-worker-fix";
          return {
            kind: "escalated",
            escalation: {
              reason: `${ctx.cmrPass} cmr needs human review`,
              diagnosis: "review workers disagreed on whether the pass can converge",
            },
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: ctx.familyBase ?? "",
            status: "pr_opened",
            pr: `pr://${ctx.familyBase}`,
          },
        };
      }

      async escalateFamily(esc: FamilyEscalation): Promise<void> {
        this.escalations.push(esc);
      }
    }

    const backend = new EscalatingCmrWorkerBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-final-verify",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("completeness cmr");
    expect(backend.escalations[0]?.familyHeadAfter).toBe("head-after-cmr-worker-fix");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason:
        "completeness cmr needs human review — review workers disagreed on whether the pass can converge",
      familyHeadAfter: "head-after-cmr-worker-fix",
    }));
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("ESCALATED ship worker records the post-worker family head in the family pause", async () => {
    class EscalatingShipWorkerBackend extends BareFamilyBackend {
      readonly escalations: FamilyEscalation[] = [];
      currentFamilyHead = "head-after-final-verify";

      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }

      async readFamilyHead(_familyBase: string): Promise<string> {
        return this.currentFamilyHead;
      }

      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.currentFamilyHead = `head-after-${ctx.cmrPass}-cmr`;
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.5", "agy"],
            },
          };
        }
        this.currentFamilyHead = "head-after-ship-worker-bump";
        return {
          kind: "escalated",
          escalation: {
            reason: "ship needs human review",
            diagnosis: "release note conflict",
          },
        };
      }

      async escalateFamily(esc: FamilyEscalation): Promise<void> {
        this.escalations.push(esc);
      }
    }

    const backend = new EscalatingShipWorkerBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-final-verify",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]).toMatchObject({
      reason: "ship needs human review — release note conflict",
      familyHeadAfter: "head-after-ship-worker-bump",
    });
  });
});

describe("#296 verify-cmr hook body — graceful no-op when the backend lacks the capability", () => {
  it("a #293-era backend WITHOUT runFamilyVerify yields the no-op {ok:true, ran:false} (spine default path untouched)", async () => {
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: new BareFamilyBackend(),
    });
    expect(result).toEqual({ ok: true, ran: false });
  });

  it("a backend with verify but WITHOUT cmr (final phase) FAILS-SAFE to ok:false — it does NOT report a pass the 承重闸 never ran", async () => {
    // verify present, cmr absent: green verify, then the cmr capability is missing
    // → #296 must not throw AND must not fabricate a pass. A real verify ran, so the
    // hook cannot return the nothing-ran no-op {ok:true}; that would make the spine
    // call the run "success" with the load-bearing integrated cmr never executed
    // (decision 3⑥). It fails-safe to {ok:false, ran:true} (verify_failed at final).
    class VerifyOnlyBackend extends BareFamilyBackend {
      readonly verifyCalls: FamilyVerifyRequest[] = [];
      async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
        this.verifyCalls.push(req);
        return { ok: true };
      }
    }
    const backend = new VerifyOnlyBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Verify ran (ran:true), but with no cmr capability the hook reports a red
    // final barrier (ok:false) — NOT a false success.
    expect(backend.verifyCalls).toHaveLength(1);
    expect(result).toEqual({ ok: false, ran: true });
  });

  it("a backend with verify + cmr but WITHOUT openFamilyPr (final phase) FAILS-SAFE to ok:false — the terminal 止于-PR step could not run", async () => {
    // verify green + cmr converged, but the PR capability is missing → the terminal
    // action (decision 4, 止于 PR) cannot run. {ok:true} would report "success" for a
    // run whose PR never opened; fail-safe to {ok:false, ran:true} instead.
    class VerifyAndCmrBackend extends BareFamilyBackend {
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async runIntegratedCmr(): Promise<IntegratedCmrResult> {
        return { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
      }
    }
    const backend = new VerifyAndCmrBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
  });
});

// ═══════════════════ defensive catch around the family worker dispatch (cmr S336 r8) ═══════════════════

describe("cmr S336 r8 — a family worker that THROWS on startup is a documented gate result, not an escaped exception", () => {
  /**
   * The single-slice runner wraps its S7 ship dispatch in try/catch → S8(error);
   * verifyCmr did NOT wrap its cmr / ship dispatch. The token preflight (cmr S336 r8)
   * removes the missing-auth throw, but the worker ALSO `git checkout`s the family
   * base + writes the focus file + spins docker — any of which can still throw out of
   * `dispatchWorker` and reject the WHOLE family run, bypassing the INCOMPLETE_GATE
   * fail-safe. So verifyCmr must catch a thrown startup error, record it (observable),
   * and fail-safe to {ok:false, ran:true}.
   */
  class ThrowingDispatchBackend extends BareFamilyBackend {
    readonly aborted: FamilyAbortedEvent[] = [];
    currentFamilyHead = "head-before-worker";
    constructor(private readonly throwOnKind: "cmr" | "ship") {
      super();
    }
    async runFamilyVerify(): Promise<FamilyVerifyResult> {
      return { ok: true };
    }
    async readFamilyHead(_familyBase: string): Promise<string> {
      return this.currentFamilyHead;
    }
    async recordAborted(event: FamilyAbortedEvent): Promise<void> {
      this.aborted.push(event);
    }
    async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
      if (spec.kind === this.throwOnKind) {
        this.currentFamilyHead = `head-after-${spec.kind}-worker`;
        throw new Error(`${spec.kind} worker: git checkout ${ctx.familyBase} failed (no such ref)`);
      }
      // The cmr worker converges so the run reaches the ship stage (for the ship case).
      return {
        kind: "completed",
        output: { kind: "cmr", converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] },
      };
    }
  }

  it("a cmr worker that throws on startup ⇒ INCOMPLETE_GATE (ok:false, ran:true), abort recorded — never an escaped throw", async () => {
    const backend = new ThrowingDispatchBackend("cmr");
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/cmr worker threw on startup/i);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/no such ref/i);
    expect(backend.aborted[0]?.familyHeadAfter).toBe("head-after-cmr-worker");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason:
        "family integrated cmr completeness worker failed: family cmr worker threw on startup: cmr worker: git checkout family/291-base failed (no such ref)",
      familyHeadAfter: "head-after-cmr-worker",
    }));
  });

  it("a ship worker that throws on startup (after a converged cmr) ⇒ INCOMPLETE_GATE, abort recorded — never an escaped throw", async () => {
    const backend = new ThrowingDispatchBackend("ship");
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/ship worker threw on startup/i);
  });
});
