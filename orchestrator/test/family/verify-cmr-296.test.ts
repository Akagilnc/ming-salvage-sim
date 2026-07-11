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
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
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
import type { DispatchContext, Finding, WorkerResult, WorkerSpec } from "../../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

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
  readonly verifyShippedPrCalls: Parameters<NonNullable<FamilyBackend["verifyFamilyShippedPr"]>>[0][] = [];
  readonly readFamilyHeadCalls: string[] = [];
  currentFamilyHead = "head-1";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
      pr?: (req: OpenFamilyPrRequest) => OpenFamilyPrResult;
      verifyShippedPr?: (
        req: Parameters<NonNullable<FamilyBackend["verifyFamilyShippedPr"]>>[0],
      ) => Awaited<ReturnType<NonNullable<FamilyBackend["verifyFamilyShippedPr"]>>>;
      worker?: (spec: WorkerSpec, ctx: DispatchContext) => WorkerResult | Promise<WorkerResult>;
    } = {},
  ) {
    if (script.worker !== undefined) {
      this.dispatchWorker = async (spec, ctx) => script.worker!(spec, ctx);
    }
  }

  declare readonly dispatchWorker?: FamilyBackend["dispatchWorker"];

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
    return this.script.cmr?.(req) ?? { converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return this.script.pr?.(req) ?? {
      url: `pr://${req.familyBase}`,
      prHead: this.currentFamilyHead,
    };
  }
  async verifyFamilyShippedPr(
    req: Parameters<NonNullable<FamilyBackend["verifyFamilyShippedPr"]>>[0],
  ): Promise<Awaited<ReturnType<NonNullable<FamilyBackend["verifyFamilyShippedPr"]>>>> {
    this.verifyShippedPrCalls.push(req);
    return this.script.verifyShippedPr?.(req) ?? { ok: true };
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

  it("MODULE_NOT_FOUND verify failures persist a machine repair hint on the family ledger", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({
        ok: false,
        errorPackage: {
          reason: "Error: Cannot find module 'tsx'",
        },
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-before-final-verify",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: "Error: Cannot find module 'tsx'",
        familyHeadAfter: "head-before-final-verify",
        stopSummary: expect.objectContaining({
          reason: "infra_failure",
          repairHint: expect.stringContaining("install or restore"),
        }),
      }),
    );
  });
});

describe("#296 verify-cmr hook body — final phase (full verify → cmr → PR)", () => {
  it("ADR0032 pure floor predicate covers strong and non-strong survival combinations", () => {
    expect(meetsCmrFloor(["gpt-5.6-sol"])).toBe(true);
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
                { slug: "gpt-5.6-sol", reason: "auth unavailable" },
              ],
              ...CMR_EVIDENCE,
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
    expect(backend.escalations).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("floor"),
      stopSummary: expect.objectContaining({
        reason: "provider_degraded",
        metadata: expect.objectContaining({
          providerDegraded: expect.arrayContaining([
            expect.objectContaining({
              leg: "opus",
              reason: "auth unavailable",
              blocking: true,
            }),
            expect.objectContaining({
              leg: "gpt-5.6-sol",
              reason: "auth unavailable",
              blocking: true,
            }),
          ]),
        }),
      }),
    }));
  });

  it("#598 a cmr worker that CRASHES once then converges is retried fresh — the gate passes, no abort", async () => {
    // The retry DIRECTION for the cmr role (the throw-startup test above proves
    // only the exhaustion→INCOMPLETE_GATE direction). The cmr worker throws on its
    // first dispatch, then converges on the fresh retry — so the gate reaches
    // {ok:true} instead of aborting on the first crash.
    class CrashOnceCmrBackend extends BareFamilyBackend {
      cmrDispatches = 0;
      readonly aborted: FamilyAbortedEvent[] = [];
      currentFamilyHead = "head-before-worker";
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async readFamilyHead(_familyBase: string): Promise<string> {
        return this.currentFamilyHead;
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind !== "cmr") {
          return { kind: "completed", output: { kind: "ship", branch: "family/291-base", status: "pushed" } };
        }
        this.cmrDispatches += 1;
        if (this.cmrDispatches === 1) {
          throw new Error("cmr worker: container connection dropped mid-review");
        }
        return {
          kind: "completed",
          output: { kind: "cmr", converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"], ...CMR_EVIDENCE },
        };
      }
    }
    const backend = new CrashOnceCmrBackend();
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // The retry DIRECTION: the crash was retried FRESH (a second cmr dispatch),
    // NOT aborted on the first crash. Contrast the throw-startup test above, where
    // a PERSISTENT crash is dispatched once (well, exhausts) and records a "threw on
    // startup" abort. Here the transient crash is followed by a converging retry.
    expect(backend.cmrDispatches).toBeGreaterThanOrEqual(2);
    // No abort names the transient crash — it recovered instead of aborting.
    expect(
      backend.aborted.some((e) => /threw on startup|connection dropped/i.test(e.errorPackage.reason)),
    ).toBe(false);
  });

  it("checks CMR leg floor before routing fix_now findings to coder-fix", async () => {
    const weakLegFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "weak-leg review must not trigger coder-fix",
      location: "orchestrator/src/family/verifyCmr.ts:leg-floor-before-fix",
      suggested_fix: "validate CMR leg coverage before dispatching coder-fix",
      action: "fix_now",
    };
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: false,
        reason: "weak CMR leg reported a fixable finding",
        successfulLegs: ["agy"],
        skippedLegs: [
          { slug: "opus", reason: "auth unavailable" },
          { slug: "gpt-5.6-sol", reason: "auth unavailable" },
        ],
        findings: [weakLegFinding],
        ...CMR_EVIDENCE,
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("floor"),
      stopSummary: expect.objectContaining({ reason: "provider_degraded" }),
    }));
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(false);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
  });

  it("rejects route-undeclared strong legs before applying the CMR floor", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["agy", "opus"],
        skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toEqual([]);
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      reason: expect.stringContaining("not declared"),
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("leg accounting payload"),
        metadata: expect.objectContaining({
          routeAccounting: expect.objectContaining({
            declaredLegs: ["gpt-5.6-sol", "agy"],
            successfulLegs: ["agy", "opus"],
            skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
            routeFingerprint: expect.any(String),
            routeArtifact: expect.objectContaining({
              path: ".cmr-route.json",
              content: expect.objectContaining({
                legCollections: expect.objectContaining({
                  cmrReview: expect.arrayContaining([
                    expect.objectContaining({ slug: "gpt-5.6-sol" }),
                    expect.objectContaining({ slug: "agy" }),
                  ]),
                }),
              }),
            }),
            actualPayload: expect.objectContaining({
              successfulLegs: ["agy", "opus"],
              skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
            }),
            repairHint: expect.stringContaining("undeclared legs"),
          }),
        }),
      }),
    }));
  });

  it("does not rewrite CMR route-accounting malformed results", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    class RouteAccountingRewriteBackend extends CapableFamilyBackend {
      readonly rewriteCalls: Array<{
        spec: WorkerSpec;
        ctx: DispatchContext;
        protocolFailure: Extract<WorkerResult, { kind: "malformed" }>;
        attempt: number;
      }> = [];

      constructor() {
        super({ verify: () => ({ ok: true }) });
      }

      dispatchWorker = async (
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> => {
        if (spec.kind === "cmr") {
          return {
            kind: "malformed",
            reason: "successful leg opus is not declared in active route",
            sessionId: "cmr-route-accounting",
            cmrLegAccountingPayload: {
              successfulLegs: ["agy", "opus"],
              skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
            },
          };
        }
        throw new Error(`unexpected worker after route-accounting failure: ${spec.kind}`);
      };

      async rewriteWorkerOutcome(
        spec: WorkerSpec,
        ctx: DispatchContext,
        protocolFailure: Extract<WorkerResult, { kind: "malformed" }>,
        attempt: number,
      ): Promise<WorkerResult> {
        this.rewriteCalls.push({ spec, ctx, protocolFailure, attempt });
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: true,
            successfulLegs: ["gpt-5.6-sol", "agy"],
            ...CMR_EVIDENCE,
          },
        };
      }
    }

    const backend = new RouteAccountingRewriteBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.rewriteCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("not declared"),
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("leg accounting payload"),
        metadata: expect.objectContaining({
          routeAccounting: expect.objectContaining({
            successfulLegs: ["agy", "opus"],
            skippedLegs: [{ slug: "gpt-5.6-sol", reason: "auth unavailable" }],
          }),
        }),
      }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
    expect(backend.verifyShippedPrCalls).toEqual([{
      pr: "pr://family/291-base",
      familyBase: "family/291-base",
      expectedHead: "head-1",
    }]);
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
      stopSummary: expect.objectContaining({
        reason: "success",
        metadata: {
          heads: {
            reportedFamilyHead: "head-1",
            actualFamilyHead: "head-1",
            verifiedCmrHead: "head-1",
            sources: {
              reportedFamilyHead: "host-observed family HEAD used for PR truth",
              actualFamilyHead: "family head after ship worker",
              verifiedCmrHead: "latest cmr_passed ledger row",
            },
          },
        },
      }),
    }));
  });

  it("re-dispatches a fake PR locator to the bound, escalates, and never persists shipped", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      pr: () => ({ url: "pr://fake-locator", prHead: "head-1" }),
      verifyShippedPr: () => ({
        ok: false,
        kind: "pr_missing",
        reason: "gh pr view: PR not found",
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toHaveLength(MAX_DISPATCH_ATTEMPTS);
    expect(backend.verifyShippedPrCalls).toHaveLength(MAX_DISPATCH_ATTEMPTS);
    expect(backend.ledger.some((entry) => entry.status === "shipped")).toBe(false);
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("gh pr view: PR not found");
  });

  it("retries an unknown host observation without re-dispatching ship, then escalates", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      verifyShippedPr: () => ({
        ok: false,
        kind: "observation_failed",
        reason: "gh pr view: network timeout",
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toHaveLength(1);
    expect(backend.verifyShippedPrCalls).toHaveLength(MAX_DISPATCH_ATTEMPTS);
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("network timeout");
    expect(backend.ledger.some((entry) => entry.status === "shipped")).toBe(false);
  });

  it("re-dispatches after one host-verification miss and ships only after host truth succeeds", async () => {
    let verificationAttempt = 0;
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      verifyShippedPr: () => {
        verificationAttempt += 1;
        return verificationAttempt === 1
          ? { ok: false, kind: "pr_missing", reason: "gh pr view: PR not found" }
          : { ok: true };
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.prCalls).toHaveLength(2);
    expect(backend.verifyShippedPrCalls).toHaveLength(2);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      pr: "pr://family/291-base",
      familyHeadAfter: "head-1",
    }));
    expect(backend.escalations).toEqual([]);
  });

  it("rejects converged CMR when runner-protected prior findings are not explicitly claimed fixed", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
      priorCmrFindingIdentityKeys: ["medium|completeness|prior claim|scope"],
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.prCalls).toEqual([]);
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      reason: expect.stringContaining("were not explicitly claimed fixed"),
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        repairHint: expect.stringContaining("claimed-fixed closure payload"),
      }),
    }));
  });

  it("resume skips a CMR pass that already passed for the current family HEAD", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("resolve the current family HEAD"),
        metadata: {
          heads: expect.objectContaining({
            verifiedCmrHead: "head-1",
          }),
          ship: expect.objectContaining({
            latestVerifiedCmrHead: "head-1",
            reportedFamilyHead: "head-1",
            shipPrState: "current-family-head-unresolved",
          }),
        },
      }),
    }));
  });

  it("persists host family HEAD when the worker reports a stale PR head", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      pr: (req) => ({ url: `pr://${req.familyBase}`, prHead: "stale-pr-head" }),
    });
    backend.currentFamilyHead = "current-family-head";

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "verified-cmr-head",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      event: "shipped",
      phase: "final",
      familyHeadAfter: "current-family-head",
      stopSummary: expect.objectContaining({
        reason: "success",
        metadata: {
          heads: expect.objectContaining({
            actualFamilyHead: "current-family-head",
            reportedFamilyHead: "current-family-head",
          }),
        },
      }),
    }));
  });

  it("resume reruns a CMR pass when the family HEAD advanced after the pass marker", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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

  it("records the unchanged CMR-reviewed family HEAD and uses it for the next pass resume guard", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    backend.currentFamilyHead = "head-before-cmr";
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: "head-before-cmr",
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
      familyHeadAfter: "head-before-cmr",
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
      "family/291-base",
      "family/291-base",
      "family/291-base",
    ]);
  });

  it("continues a correctness coder-fix loop at correctness without re-running completeness", async () => {
    const correctnessKey =
      "correctness|ming_sim/issues.py:7089|db.validate_fiscal_config_value(key, new_val)";
    const finding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "db.validate_fiscal_config_value(key, new_val)",
      location: "ming_sim/issues.py:7089",
      suggested_fix:
        "Validate the final batch state before applying order-sensitive fiscal changes.",
      action: "fix_now",
    };
    let backend!: CapableFamilyBackend;
    backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => {
        if (req.cmrPass === "completeness") {
          return {
            converged: true,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          };
        }
        if (req.priorCmrFindingIdentityKeys?.includes(correctnessKey)) {
          return {
            converged: true,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            claimedFixedFindingIdentityKeys: [correctnessKey],
            priorFindingDispositions: [
              {
                identityKey: correctnessKey,
                status: "verified-closed",
                evidence: "regression and same-class scan passed after coder-fix",
              },
            ],
          };
        }
        return {
          converged: false,
          reason: "correctness found an order-sensitive fiscal config bug",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [finding],
          ...CMR_EVIDENCE,
        };
      },
      async worker(spec, ctx) {
        if (spec.kind === "cmr") {
          const cmr = await backend.runIntegratedCmr({
            familyBase: ctx.familyBase ?? "family/291-base",
            ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
            ...(ctx.priorCmrFindingIdentityKeys !== undefined
              ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
              : {}),
          });
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
              converged: cmr.converged,
              ...(cmr.reason !== undefined ? { reason: cmr.reason } : {}),
              ...(cmr.successfulLegs !== undefined
                ? { successfulLegs: cmr.successfulLegs }
                : {}),
              ...(cmr.claimedFixedFindingIdentityKeys !== undefined
                ? { claimedFixedFindingIdentityKeys: cmr.claimedFixedFindingIdentityKeys }
                : {}),
              ...(cmr.priorFindingDispositions !== undefined
                ? { priorFindingDispositions: cmr.priorFindingDispositions }
                : {}),
              ...(cmr.findings !== undefined ? { findings: cmr.findings } : {}),
              ...(cmr.evidencePaths !== undefined ? { evidencePaths: cmr.evidencePaths } : {}),
            },
          };
        }
        if (spec.kind === "coder") {
          expect(ctx.blockingFindingIdentityKeys).toEqual([correctnessKey]);
          backend.currentFamilyHead = "head-after-correctness-fix";
          return {
            kind: "completed",
            output: {
              kind: "coder",
              committed: true,
              commitsAdded: 1,
              repairEvidence: {
                findingScope: { identityKeys: [correctnessKey] },
                changedFiles: ["ming_sim/issues.py"],
                tests: ["pytest tests/test_fiscal_config.py::test_loss_rate_batch_rebalance"],
                sameClassBugScan: "rg 'validate_fiscal_config_value' ming_sim tests",
                introducedRegressionCheck:
                  "npm test -- --run test/family/verify-cmr-296.test.ts",
              },
            },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase ?? "family/291-base",
              pr: "pr://family/291-base",
              prHead: backend.currentFamilyHead,
              status: "pr_opened",
            },
          };
        }
        if (
          spec.kind === "verify" ||
          spec.kind === "fixer" ||
          spec.kind === "cleanup" ||
          spec.kind === "docRelease"
        ) {
          return {
            kind: "completed",
            output:
              spec.kind === "verify"
                ? { kind: "verify", converged: true }
                : spec.kind === "fixer"
                  ? {
                    kind: "fixer",
                    committed: true,
                    fixCommitSha: "fixsha1111111111111111111111111111111111",
                  }
                  : spec.kind === "cleanup"
                    ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                    : { kind: "docRelease", released: true },
          };
        }
        return { kind: "failed", reason: `unexpected worker ${spec.kind}` };
      },
    });
    backend.currentFamilyHead = "head-before-correctness-fix";

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-before-correctness-fix",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls.map((call) => call.cmrPass)).toEqual([
      "completeness",
      "correctness",
      "correctness",
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      cmrPass: "correctness",
      familyHeadAfter: "head-after-correctness-fix",
    }));
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
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("mismatch"),
      stopSummary: expect.objectContaining({
        reason: "contract_drift",
        summary: expect.stringContaining("mismatch"),
      }),
    }));
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
    expect(backend.escalations[0]?.familyHeadAfter).toBe("head-after-final-verify");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason:
        "completeness cmr needs human review — review workers disagreed on whether the pass can converge",
      familyHeadAfter: "head-after-final-verify",
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
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
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
        return { converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] };
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
        if (spec.kind === "ship") {
          this.currentFamilyHead = "head-after-ship-worker";
        }
        throw new Error(`${spec.kind} worker: git checkout ${ctx.familyBase} failed (no such ref)`);
      }
      // The cmr worker converges so the run reaches the ship stage (for the ship case).
      return {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
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
    expect(backend.aborted[0]?.familyHeadAfter).toBe("head-before-worker");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason:
        "family integrated cmr completeness worker failed: family cmr worker threw on startup: cmr worker: git checkout family/291-base failed (no such ref)",
      familyHeadAfter: "head-before-worker",
    }));
  });

  it("#598: a persistent family worker crash retries on current state up to MAX_DISPATCH_ATTEMPTS (every role)", async () => {
    // A backend that throws PERSISTENTLY on the given kind and counts dispatches of
    // it. Every role — read-only cmr and write-capable ship alike — re-dispatches a
    // fresh session on the CURRENT worktree as-is, up to MAX_DISPATCH_ATTEMPTS.
    class CountingThrowBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      currentFamilyHead = "head-before-worker";
      throwKindDispatches = 0;
      constructor(private readonly throwOnKind: "cmr" | "ship") {
        super();
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async readFamilyHead(): Promise<string> {
        return this.currentFamilyHead;
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === this.throwOnKind) {
          this.throwKindDispatches += 1;
          throw new Error(`${spec.kind} worker: git checkout ${ctx.familyBase} failed (no such ref)`);
        }
        return {
          kind: "completed",
          output: {
            kind: "cmr",
            converged: true,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            ...CMR_EVIDENCE,
          },
        };
      }
    }

    const shipBackend = new CountingThrowBackend("ship");
    const shipResult = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: shipBackend,
    });
    expect(shipResult).toEqual({ ok: false, ran: true });
    expect(shipBackend.throwKindDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(shipBackend.aborted[0]?.errorPackage.reason).toMatch(/ship worker threw on startup/i);

    const cmrBackend = new CountingThrowBackend("cmr");
    const cmrResult = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: cmrBackend,
    });
    expect(cmrResult).toEqual({ ok: false, ran: true });
    expect(cmrBackend.throwKindDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
  });

  it("a rewrite worker that throws while repairing malformed CMR outcome ⇒ infra outcome protocol failure, never an escaped throw", async () => {
    class ThrowingRewriteBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      currentFamilyHead = "head-before-worker";

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
        if (spec.kind !== "cmr") {
          throw new Error(`unexpected worker after protocol failure: ${spec.kind}`);
        }
        return {
          kind: "malformed",
          reason: `${ctx.cmrPass} cmr worker outcome sidecar was not valid JSON`,
          sessionId: "cmr-session-malformed",
        };
      }

      async rewriteWorkerOutcome(
        _spec: WorkerSpec,
        _ctx: DispatchContext,
        _protocolFailure: Extract<WorkerResult, { kind: "malformed" }>,
        _attempt: number,
      ): Promise<WorkerResult> {
        throw new Error("rewrite worker sandbox checkout failed");
      }
    }

    const backend = new ThrowingRewriteBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/outcome protocol failure/i);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/sandbox checkout failed/i);
    expect(backend.aborted[0]?.familyHeadAfter).toBe("head-before-worker");
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("outcome protocol failure"),
      familyHeadAfter: "head-before-worker",
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        summary: expect.stringContaining("sandbox checkout failed"),
        repairHint: expect.stringContaining("worker outcome writer/guard"),
      }),
    }));
  });

  it("a cmr worker failed result for missing dependencies is recorded as infra_failure", async () => {
    class FailedCmrBackend extends ThrowingDispatchBackend {
      constructor() {
        super("ship");
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          return {
            kind: "failed",
            reason: "Error: Cannot find module 'missing-cmr-runtime'",
          };
        }
        return super.dispatchWorker(spec, {
          familyBase: "family/291-base",
        });
      }
    }
    const backend = new FailedCmrBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("Cannot find module 'missing-cmr-runtime'"),
      familyHeadAfter: "head-before-worker",
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("install or restore"),
      }),
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

  it("a ship worker failed result for push/auth infra is recorded as infra_failure", async () => {
    class FailedShipBackend extends ThrowingDispatchBackend {
      constructor() {
        super("cmr");
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
            },
          };
        }
        this.currentFamilyHead = "head-after-ship-worker";
        return { kind: "failed", reason: "git push authentication failed" };
      }
    }
    const backend = new FailedShipBackend();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason: expect.stringContaining("git push authentication failed"),
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("ship worker infrastructure"),
      }),
    }));
  });
});

describe("#823 family ship malformed-output recovery", () => {
  it("re-dispatches malformed sidecar and wrong payload attempts before accepting the first valid ship result", async () => {
    class RecoveringShipBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      readonly escalations: FamilyEscalation[] = [];
      shipDispatches = 0;

      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async readFamilyHead(): Promise<string> {
        return "head-after-cmr";
      }
      async verifyFamilyShippedPr(): Promise<{ ok: true }> {
        return { ok: true };
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async escalateFamily(event: FamilyEscalation): Promise<void> {
        this.escalations.push(event);
      }
      async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
            },
          };
        }
        if (spec.kind === "verify") {
          return {
            kind: "completed",
            output: { kind: "verify", converged: true },
          };
        }
        if (spec.kind === "docRelease") {
          return {
            kind: "completed",
            output: { kind: "docRelease", released: true },
          };
        }
        if (spec.kind === "cleanup") {
          return {
            kind: "completed",
            output: {
              kind: "cleanup",
              terminal: true,
              ok: true,
              branchOutcome: "already_gone",
            },
          };
        }
        this.shipDispatches += 1;
        if (this.shipDispatches === 1) {
          return { kind: "malformed", reason: "ship outcome sidecar missing" };
        }
        if (this.shipDispatches === 2) {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
            },
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: ctx.familyBase ?? "",
            status: "pr_opened",
            pr: "pr://family/823",
          },
        };
      }
    }

    const backend = new RecoveringShipBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/823-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-cmr",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.shipDispatches).toBe(3);
    expect(backend.aborted).toEqual([]);
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      pr: "pr://family/823",
    }));
  });

  it("escalates only after the bounded malformed-output redispatch budget exhausts", async () => {
    class PersistentlyMalformedShipBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      readonly escalations: FamilyEscalation[] = [];
      shipDispatches = 0;

      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async readFamilyHead(): Promise<string> {
        return "head-after-cmr";
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async escalateFamily(event: FamilyEscalation): Promise<void> {
        this.escalations.push(event);
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "cmr",
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
            },
          };
        }
        this.shipDispatches += 1;
        return { kind: "malformed", reason: "ship outcome sidecar invalid" };
      }
    }

    const backend = new PersistentlyMalformedShipBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/823-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-cmr",
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.shipDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(backend.escalations).toHaveLength(1);
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toContain(
      `after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts`,
    );
  });
});
