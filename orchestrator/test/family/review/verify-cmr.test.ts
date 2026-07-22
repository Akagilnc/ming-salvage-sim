/**
 * #296 — the verify-cmr HOOK BODY (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * Production default is the real `runVerifyCmr` (not a success no-op). The spine
 * calls it at the wave barrier + end-of-run with phase + context and acts on
 * `ok`. This module is that body behind the same `runVerifyCmr(input)` signature
 * — it never rewrites the spine call sites:
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
 * familyBackend}`). Missing `runFamilyVerify` fails closed (`verify_failed`).
 * Tests inject stubs only when needed. Zero-container fakes — no real codex /
 * container / push.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  mechanicalRedispatchAttemptsFromFamilyLedger,
  runVerifyCmr,
} from "../../../src/family/verifyCmr.js";
import { legacyDispatchFamilyWorker } from "../../../src/family/dispatchFamilyWorker.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../../src/dispatchRetry.js";
import { activeModelRoute, modelRouteFingerprint } from "../../../src/modelRoutes.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import { runnerSynthesizedFailureEscalation } from "../../../src/runnerEscalation.js";
import { dispatchReviewLoopThroughAdmission } from "../../helpers/review-loop-admission-dispatch.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  Finding,
  JudgeResult,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  judgeToolchain,
  liveCmrJudgeContinue,
  legacyCmrScriptToWorkerOutput,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";
import { unusableResidualOpenCountPaper } from "../../../src/judgeStation.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { completeCmrPanelLegWorker } from "../../helpers/cmr-panel-leg-dispatch.js";


/**
 * Test-fake boundary (#919 E / R7 / CR N2): scripts may declare positive
 * findingsCount as continue intent — mint **live** kind:judge continue here.
 * Production residual is {@link unusableResidualOpenCountPaper} only.
 */
function cmrScriptToWorkerOutput(
  cmr: IntegratedCmrResult,
): JudgeResult | ReturnType<typeof unusableResidualOpenCountPaper> {
  return legacyCmrScriptToWorkerOutput(cmr);
}

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

interface TestShipRequest {
  readonly familyBase: string;
}

interface TestShipResult {
  readonly url: string;
  readonly prHead?: string;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

/**
 * A full family backend fake with the #296 verify/cmr/PR/abort/escalate
 * capabilities, scriptable per call. Records every interaction so the test can
 * assert what ran (no real container / codex / push).
 */
class CapableFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  readonly ledger: FamilyLedgerEntry[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: TestShipRequest[] = [];
  readonly readFamilyHeadCalls: string[] = [];
  currentFamilyHead = "head-1";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
      pr?: (req: TestShipRequest) => TestShipResult;
      readFamilyHead?: (familyBase: string) => string;
      worker?: (spec: WorkerSpec, ctx: DispatchContext) => WorkerResult | Promise<WorkerResult>;
    } = {},
  ) {}

  // ── core merge/ledger seam (unchanged from #293) ──
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(familyBase: string): Promise<string> {
    this.readFamilyHeadCalls.push(familyBase);
    return this.script.readFamilyHead?.(familyBase) ?? this.currentFamilyHead;
  }

  // ── #296 verify/cmr/PR capabilities (optional methods) ──
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    // Default green is boolean converged without open-count — fake emits live
    // kind:judge (happy 直出). findingsCount:0 stays residual unusable
    // (never silent pass; #919 M2/R7).
    const result =
      this.script.cmr?.(req) ?? {
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    const panelLeg = completeCmrPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (this.script.worker !== undefined) {
      return this.script.worker(spec, ctx);
    }
    if (spec.kind === "cmr") {
      const cmr = await this.runIntegratedCmr({
        familyBase: ctx.familyBase!,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        ...(ctx.priorCmrFindingIdentityKeys !== undefined
          ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
          : {}),
      });
      return {
        kind: "completed",
        output: cmrScriptToWorkerOutput(cmr),
      };
    }
    if (spec.kind === "ship") {
      const request = { familyBase: ctx.familyBase! };
      this.prCalls.push(request);
      const shipped = this.script.pr?.(request) ?? {
        url: `https://github.com/test/repo/pull/291`,
        prHead: this.currentFamilyHead,
      };
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: request.familyBase,
          pr: shipped.url,
          ...(shipped.prHead !== undefined ? { prHead: shipped.prHead } : {}),
          status: "pr_opened",
        },
      };
    }
    return dispatchReviewLoopThroughAdmission(this, spec, ctx);
  }

  // ── #298-owned abort/escalate seam (minimal shapes #296 only CALLS) ──
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
}

describe("test fake review-loop admission parity", () => {
  it("does not synthesize verify success for an inadmissible GitHub handle", async () => {
    const backend = new CapableFamilyBackend();
    const result = await legacyDispatchFamilyWorker(
      backend,
      { kind: "verify" } as WorkerSpec,
      {
        familyBase: "family/291-base",
        prUrl: "https://github.com/test/repo/pull/291",
        repo: "test/repo",
      } as DispatchContext,
    );

    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toContain("offline skeleton synthesis inadmissible");
    }
  });
});

function currentRouteFingerprint(): string {
  return modelRouteFingerprint(activeModelRoute());
}

/**
 * A minimal #293-era backend. Ship-focused subclasses inherit host verification
 * so their fixtures reach the ship behavior they are exercising; the no-op path
 * still has no verify/cmr/ship dispatch capability.
 */
class BareFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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

  it("RED wave verify → triage judge toolchain verdict → verify_failed + `aborted`, fixer zero-spin (#1027 S2 AC2)", async () => {
    // #1027 S2 / ADR 0145 owner FINAL: red is handed UNIFORMLY to the triage
    // judge (no runner text/exit-code classification). A `toolchain` verdict is
    // the runner's unchanged verify_failed terminal — and NO coder-fix spins.
    const coderDispatches: WorkerSpec[] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "tsc: TS2322 in regionApply" } }),
      worker: (spec) => {
        if (spec.kind === "coder") coderDispatches.push(spec);
        if (spec.kind === "cmr") {
          return completedJudge(
            judgeToolchain("MODULE_NOT_FOUND after merge", "missing dep, not a regression"),
          );
        }
        throw new Error(`unexpected wave worker dispatch: ${spec.kind}`);
      },
    });
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // #922: stage-named failedStatus (not a bare {ok,ran} mash).
    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    // The toolchain terminal writes an `aborted` event carrying the error
    // package + family base.
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("wave");
    expect(backend.aborted[0]?.familyBase).toBe("family/291-base");
    // AC2 negative: fixer never spins on a toolchain red.
    expect(coderDispatches).toEqual([]);
    // No PR on a red wave.
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
      worker: (spec) => {
        if (spec.kind === "cmr") {
          return completedJudge(
            judgeToolchain("Error: Cannot find module 'tsx'", "install dependency"),
          );
        }
        throw new Error(`unexpected worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-before-final-verify",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: expect.stringContaining("Cannot find module 'tsx'"),
        stopSummary: expect.objectContaining({
          reason: "verify_failed",
          repairHint: expect.stringContaining("toolchain/dependency"),
        }),
      }),
    );
  });
});

describe("#1027 S2 / ADR 0145 — wave-verify triage judge court", () => {
  const completedCoder = (): WorkerResult => ({
    kind: "completed",
    output: { kind: "coder", committed: true, commitsAdded: 1 },
  });

  it("AC1 tracer: red → judge continue → coder-fix → resume judge → green hard-pre → converge (#1085 hub)", async () => {
    let verifyCalls = 0;
    let judgeCalls = 0;
    const coderDispatches: WorkerSpec[] = [];
    const judgePhases: Array<DispatchContext["phase"]> = [];
    const backend = new CapableFamilyBackend({
      // #1 initial wave verify (red) → court; #2 re-verify after fix (green
      // observe). exit_loop reuses that observe when HEAD unchanged (#1085 F1)
      // — no third full-family verify.
      verify: () => {
        verifyCalls += 1;
        return verifyCalls >= 2
          ? { ok: true }
          : { ok: false, errorPackage: { reason: "cross-slice seam red: 7 failing" } };
      },
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          judgeCalls += 1;
          // #1085: after builder beat the hub resumes judge — second call
          // must exit_loop (converged); green alone never skips the hub.
          judgePhases.push(ctx.phase);
          return completedJudge(
            judgeCalls === 1
              ? judgeContinue([sampleFinding("seam regression", "a.ts:9")])
              : { kind: "judge", status: "converged" },
          );
        }
        if (spec.kind === "coder") {
          coderDispatches.push(spec);
          return completedCoder();
        }
        throw new Error(`unexpected wave worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1027-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    // ADR 0145 green hard-pre on exit_loop + ADR 0147 builder→judge hub.
    expect(result).toEqual({ ok: true, ran: true });
    // Initial red + post-fix green observe (exit reuses observe; no double-run).
    expect(verifyCalls).toBe(2);
    expect(judgeCalls).toBe(2);
    expect(judgePhases).toEqual(["wave", "wave"]);
    expect(coderDispatches).toHaveLength(1);
    expect(coderDispatches[0]?.kind).toBe("coder");
    // Ledger records the wave triage + fix rounds (与 CMR 庭同构).
    const steps = backend.ledger.map((e) => e.workerStep);
    expect(steps).toContain("wave-verify-judge");
    expect(steps).toContain("wave-verify-fix");
    // #1111 r4: first JUDGE_STEP is round receipt (reason carries the failure
    // the judge answered), not a pre-dispatch intent ahead of any FIX beat.
    const firstJudge = backend.ledger.find(
      (e) =>
        e.event === "worker_dispatched" && e.workerStep === "wave-verify-judge",
    );
    expect(firstJudge?.reason).toMatch(/triage judge round 1 for:/);
    // Converged on green → no abort.
    expect(backend.aborted).toEqual([]);
  });

  it("#1111 r4 negative: JUDGE_STEP dispatch-intent row must not clear pending receive on green resume", async () => {
    // Crash window the r1 A1 patch left open: FIX pending landed, then a
    // wave-verify-judge worker_dispatched was appended BEFORE dispatchOrAbort;
    // process died before the resident judge returned. Top-level verify is
    // green — pending scan must still re-enter the court (intent ≠ receipt).
    let judgeCalls = 0;
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          expect(ctx.waveVerifyFailure).toMatch(/resident judge must receive/);
          judgeCalls += 1;
          return completedJudge({ kind: "judge", status: "converged" });
        }
        throw new Error(`unexpected wave worker dispatch: ${spec.kind}`);
      },
    });
    backend.ledger.push(
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "wave-verify-fix",
        reason:
          "wave verify green after fixer beat — resident judge must receive before exit",
        familyHeadAfter: "head-after-fix",
      },
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "wave-verify-judge",
        reason:
          "wave verify triage judge round 1 for: wave verify green after fixer beat — resident judge must receive before exit",
      },
    );

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1111-pending-receive",
      familyBackend: backend,
      familyHeadAfter: "head-after-fix",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(judgeCalls).toBe(1);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        event: "worker_dispatched",
        workerStep: "wave-verify-judge",
        reason: expect.stringMatching(/converged after 1 round/),
      }),
    );
  });

  it("AC3 negative: judge converged but re-verify RED → forced continue (green receipt is the hard precondition)", async () => {
    let verifyCalls = 0;
    let judgeCalls = 0;
    const coderDispatches: WorkerSpec[] = [];
    const backend = new CapableFamilyBackend({
      // #1 initial red; #2 still red (after the first exit_loop — must NOT
      // close); #3 green after fix (observe). Final exit_loop reuses #3 when
      // HEAD unchanged (#1085 F1) — no fourth full-family verify.
      verify: () => {
        verifyCalls += 1;
        return verifyCalls >= 3
          ? { ok: true }
          : { ok: false, errorPackage: { reason: `still red @ verify ${verifyCalls}` } };
      },
      worker: (spec) => {
        if (spec.kind === "cmr") {
          judgeCalls += 1;
          // Round 1: judge says converged — but the re-verify is still red, so
          // the court must FORCE another round (not close on the judge's word).
          // Round 2: continue drives the coder-fix.
          // Round 3: after builder beat hub resumes judge → exit_loop.
          if (judgeCalls === 1) {
            return completedJudge({ kind: "judge", status: "converged" });
          }
          if (judgeCalls === 2) {
            return completedJudge(
              judgeContinue([sampleFinding("seam regression", "b.ts:3")]),
            );
          }
          return completedJudge({ kind: "judge", status: "converged" });
        }
        if (spec.kind === "coder") {
          coderDispatches.push(spec);
          return completedCoder();
        }
        throw new Error(`unexpected wave worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1027-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    // Round 1 converged did NOT exit (re-verify red) → round 2 continue → fix
    // → round 3 exit_loop reuses post-fix green observe.
    expect(judgeCalls).toBe(3);
    expect(coderDispatches).toHaveLength(1);
    // initial + red-after-exit + green-after-fix (final exit reuses observe)
    expect(verifyCalls).toBe(3);
    expect(backend.aborted).toEqual([]);
  });

  it("checkpoint positive red → judge continue → coder-fix → mechanical re-verify green → continue to correctness court", async () => {
    let verifyCalls = 0;
    const coderDispatches: WorkerSpec[] = [];
    const coderIssues: Array<number | undefined> = [];
    const verifyJudgePhases: Array<DispatchContext["phase"]> = [];
    const backend = new CapableFamilyBackend({
      verify: (req) => {
        verifyCalls += 1;
        return verifyCalls >= 2
          ? { ok: true }
          : { ok: false, errorPackage: { reason: "correctness checkpoint red: test failure" } };
      },
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            verifyJudgePhases.push(ctx.phase);
            return completedJudge(
              verifyJudgePhases.length === 1
                ? judgeContinue([sampleFinding("checkpoint finding", "src/a.ts:1")])
                : judgeConverged(),
            );
          }
          return completedJudge(judgeConverged());
        }
        if (spec.kind === "coder") {
          coderDispatches.push(spec);
          coderIssues.push(ctx.familyIssue);
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
        throw new Error(`unexpected worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/checkpoint-base",
      familyBackend: backend,
      familyHeadAfter: "head-cp-1",
      familyIssue: 1107,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(verifyCalls).toBe(2);
    expect(backend.verifyCalls[0]?.phase).toBe("correctness_checkpoint");
    expect(backend.verifyCalls[1]?.phase).toBe("correctness_checkpoint");
    expect(backend.verifyCalls.map((call) => call.issue)).toEqual([1107, 1107]);
    expect(verifyJudgePhases).toEqual([
      "correctness_checkpoint",
      "correctness_checkpoint",
    ]);
    expect(coderDispatches).toHaveLength(1);
    expect(coderIssues).toEqual([1107]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "cmr_passed",
        phase: "correctness_checkpoint",
        familyHeadAfter: "head-1",
      }),
    );
    expect(backend.aborted).toEqual([]);
  });

  it("checkpoint real toolchain red → stageGate verify_failed (no coder fix)", async () => {
    const coderDispatches: WorkerSpec[] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "MODULE_NOT_FOUND in correctness checkpoint" } }),
      worker: (spec) => {
        if (spec.kind === "coder") coderDispatches.push(spec);
        if (spec.kind === "cmr") {
          return completedJudge(
            judgeToolchain("MODULE_NOT_FOUND", "missing dep during checkpoint verify"),
          );
        }
        throw new Error(`unexpected worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/checkpoint-base",
      familyBackend: backend,
      familyHeadAfter: "head-cp-1",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("correctness_checkpoint");
    expect(backend.aborted[0]?.familyBase).toBe("family/checkpoint-base");
    // Phase-aware abort label: must not be wave/final mis-tagged.
    expect(backend.aborted[0]?.errorPackage.reason).toContain(
      "correctness_checkpoint verify toolchain",
    );
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "correctness_checkpoint",
        reason: expect.stringContaining("correctness_checkpoint verify toolchain"),
        stopSummary: expect.objectContaining({
          reason: "verify_failed",
          summary: expect.stringContaining("correctness_checkpoint verify toolchain"),
          repairHint: expect.stringContaining("toolchain/dependency"),
        }),
      }),
    );
    expect(coderDispatches).toEqual([]);
  });

  it("final verify positive red → judge continue → coder-fix → mechanical re-verify green → continue to CMR courts & ship", async () => {
    let verifyCalls = 0;
    const coderDispatches: WorkerSpec[] = [];
    const verifyJudgePhases: Array<DispatchContext["phase"]> = [];
    const backend: CapableFamilyBackend = new CapableFamilyBackend({
      verify: () => {
        verifyCalls += 1;
        return verifyCalls >= 2
          ? { ok: true }
          : { ok: false, errorPackage: { reason: "final verify red: test failure" } };
      },
      worker: (spec, ctx): WorkerResult | Promise<WorkerResult> => {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            verifyJudgePhases.push(ctx.phase);
            return completedJudge(
              verifyJudgePhases.length === 1
                ? judgeContinue([sampleFinding("final verify finding", "src/b.ts:5")])
                : judgeConverged(),
            );
          }
          return completedJudge(judgeConverged());
        }
        if (spec.kind === "coder") {
          coderDispatches.push(spec);
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
        if (spec.kind === "ship") {
          backend.prCalls.push({ familyBase: "family/291-base" });
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: "family/291-base",
              pr: "https://github.com/test/repo/pull/291",
              prHead: "head-1",
              status: "pr_opened",
            },
          };
        }
        return dispatchReviewLoopThroughAdmission(backend, spec, ctx);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-final-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(verifyCalls).toBe(2);
    expect(backend.verifyCalls[0]?.phase).toBe("final");
    expect(backend.verifyCalls[1]?.phase).toBe("final");
    expect(verifyJudgePhases).toEqual(["final", "final"]);
    expect(coderDispatches).toHaveLength(1);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toEqual([
      expect.objectContaining({ familyHeadAfter: "head-1" }),
      expect.objectContaining({ familyHeadAfter: "head-1" }),
    ]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.aborted).toEqual([]);
  });

  it("final verify real toolchain red → stageGate verify_failed (no coder fix, no ship)", async () => {
    const coderDispatches: WorkerSpec[] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "MODULE_NOT_FOUND in final verify" } }),
      worker: (spec) => {
        if (spec.kind === "coder") coderDispatches.push(spec);
        if (spec.kind === "cmr") {
          return completedJudge(
            judgeToolchain("MODULE_NOT_FOUND", "missing dep during final verify"),
          );
        }
        throw new Error(`unexpected worker dispatch: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/final-base",
      familyBackend: backend,
      familyHeadAfter: "head-final-1",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("final");
    expect(backend.aborted[0]?.familyBase).toBe("family/final-base");
    expect(backend.aborted[0]?.errorPackage.reason).toContain("final verify toolchain");
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: expect.stringContaining("final verify toolchain"),
        stopSummary: expect.objectContaining({
          reason: "verify_failed",
          summary: expect.stringContaining("final verify toolchain"),
          repairHint: expect.stringContaining("toolchain/dependency"),
        }),
      }),
    );
    expect(coderDispatches).toEqual([]);
    expect(backend.prCalls).toEqual([]);
  });

  // #1110 P1 / ADR 0145: mid-court re-verify after a CMR fixer is the same
  // family-verify mechanism (phase = scope). Red must enter the shared court —
  // not runFamilyVerifyOrAbort hard-die. Semantic choice: start the verify
  // triage court (not "resume CMR continue") because the red is a verify-barrier
  // fact that may be toolchain, and green re-verify is the hard precondition
  // before re-opening any CMR court.
  it("mid-court after correctness fixer: red → verify triage continue → fixer → green → re-open CMR & ship", async () => {
    const correctnessKey =
      "correctness|src/mid-court.ts:1|mid-court regression after cmr fix";
    const finding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "mid-court regression after cmr fix",
      location: "src/mid-court.ts:1",
      suggested_fix: "repair the regression the CMR fixer introduced",
      action: "fix_now",
    };
    let verifyCalls = 0;
    let verifyJudgeCalls = 0;
    let coderDispatchCount = 0;
    let verifyFixHeadObserved = false;
    let backend!: CapableFamilyBackend;
    backend = new CapableFamilyBackend({
      readFamilyHead: () => {
        if (backend.currentFamilyHead !== "head-after-verify-fix") {
          return backend.currentFamilyHead;
        }
        if (!verifyFixHeadObserved) {
          verifyFixHeadObserved = true;
          return backend.currentFamilyHead;
        }
        throw new Error("later HEAD observation unavailable — use propagated HEAD");
      },
      verify: () => {
        verifyCalls += 1;
        // #1 initial final verify green → enter CMR.
        // #2 mid-court after CMR fixer red → shared verify court.
        // #3 court mechanical re-verify green → resume correctness court.
        if (verifyCalls === 2) {
          return {
            ok: false,
            errorPackage: { reason: "mid-court verify red after cmr fixer" },
          };
        }
        return { ok: true };
      },
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
          };
        }
        return {
          converged: false,
          findingsCount: 1,
          reason: "correctness found a mid-court seam bug",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [finding],
          ...CMR_EVIDENCE,
        };
      },
      async worker(spec, ctx) {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            verifyJudgeCalls += 1;
            return completedJudge(
              verifyJudgeCalls === 1
                ? judgeContinue([
                    sampleFinding("mid-court verify finding", "src/mid-court.ts:1"),
                  ])
                : judgeConverged(),
            );
          }
          const cmr = await backend.runIntegratedCmr({
            familyBase: ctx.familyBase ?? "family/1110-mid-court",
            ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
            ...(ctx.priorCmrFindingIdentityKeys !== undefined
              ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
              : {}),
          });
          return {
            kind: "completed",
            output: cmrScriptToWorkerOutput(cmr),
          };
        }
        if (spec.kind === "coder") {
          coderDispatchCount += 1;
          // First coder = CMR fixer; second = verify-court fixer after mid-court red.
          if (coderDispatchCount === 1) {
            backend.currentFamilyHead = "head-after-cmr-fix";
          } else if (coderDispatchCount === 2) {
            backend.currentFamilyHead = "head-after-verify-fix";
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "ship") {
          backend.prCalls.push({
            familyBase: ctx.familyBase ?? "family/1110-mid-court",
          });
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase ?? "family/1110-mid-court",
              pr: "https://github.com/test/repo/pull/1110",
              prHead: backend.currentFamilyHead,
              status: "pr_opened",
            },
          };
        }
        return dispatchReviewLoopThroughAdmission(backend, spec, ctx);
      },
    });
    backend.currentFamilyHead = "head-before-cmr-fix";

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1110-mid-court",
      familyBackend: backend,
      familyHeadAfter: "head-before-cmr-fix",
      familyIssue: 1110,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(verifyCalls).toBe(3);
    expect(verifyJudgeCalls).toBe(2);
    expect(coderDispatchCount).toBe(2);
    const steps = backend.ledger.map((e) => e.workerStep);
    expect(steps).toContain("wave-verify-judge");
    expect(steps).toContain("wave-verify-fix");
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual([
      "completeness",
      "correctness",
      "correctness",
      "correctness",
    ]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "cmr_passed",
        phase: "final",
        familyHeadAfter: "head-after-verify-fix",
      }),
    );
    expect(backend.prCalls).toEqual([{ familyBase: "family/1110-mid-court" }]);
    expect(backend.aborted).toEqual([]);
  });

  it("mid-court after correctness fixer: real toolchain red → verify_failed (verify-court fixer zero-spin)", async () => {
    const finding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "toolchain red after cmr fix",
      location: "src/mid-court-toolchain.ts:1",
      suggested_fix: "irrelevant — mid-court verify is toolchain",
      action: "fix_now",
    };
    let verifyCalls = 0;
    let coderDispatchCount = 0;
    let backend!: CapableFamilyBackend;
    backend = new CapableFamilyBackend({
      verify: () => {
        verifyCalls += 1;
        // Initial green; mid-court after CMR fixer stays red (toolchain).
        if (verifyCalls === 1) return { ok: true };
        return {
          ok: false,
          errorPackage: { reason: "MODULE_NOT_FOUND mid-court after cmr fixer" },
        };
      },
      cmr: (req) => {
        if (req.cmrPass === "completeness") {
          return {
            converged: true,
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          };
        }
        return {
          converged: false,
          findingsCount: 1,
          reason: "correctness finding before mid-court toolchain red",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [finding],
          ...CMR_EVIDENCE,
        };
      },
      async worker(spec, ctx) {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            return completedJudge(
              judgeToolchain(
                "MODULE_NOT_FOUND",
                "missing dep during mid-court re-verify",
              ),
            );
          }
          const cmr = await backend.runIntegratedCmr({
            familyBase: ctx.familyBase ?? "family/1110-mid-toolchain",
            ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
            ...(ctx.priorCmrFindingIdentityKeys !== undefined
              ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
              : {}),
          });
          return {
            kind: "completed",
            output: cmrScriptToWorkerOutput(cmr),
          };
        }
        if (spec.kind === "coder") {
          coderDispatchCount += 1;
          backend.currentFamilyHead = "head-after-cmr-fix-toolchain";
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "ship") {
          throw new Error("ship must not run after mid-court toolchain abort");
        }
        return dispatchReviewLoopThroughAdmission(backend, spec, ctx);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1110-mid-toolchain",
      familyBackend: backend,
      familyHeadAfter: "head-before",
      familyIssue: 1110,
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    // Only the CMR fixer spun; verify-court toolchain = zero verify-fixer.
    expect(coderDispatchCount).toBe(1);
    expect(backend.ledger.map((e) => e.workerStep)).toContain("wave-verify-judge");
    expect(backend.ledger.map((e) => e.workerStep)).not.toContain("wave-verify-fix");
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("final");
    expect(backend.aborted[0]?.errorPackage.reason).toContain("final verify toolchain");
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: expect.stringContaining("final verify toolchain"),
        stopSummary: expect.objectContaining({
          reason: "verify_failed",
          repairHint: expect.stringContaining("toolchain/dependency"),
        }),
      }),
    );
    expect(backend.prCalls).toEqual([]);
    // Correctness never re-opens after toolchain mid-court abort.
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual([
      "completeness",
      "correctness",
    ]);
    expect(verifyCalls).toBeGreaterThanOrEqual(2);
  });

  // #1110 FIX3 / ADR 0145: completeness mid-court is the same family-verify
  // mechanism as the correctness mid-court cases above — phase is scope only.
  // Completeness fixer then mechanical re-verify red must enter the shared
  // verify triage court (not hard-die), then fixer → green → resume CMR.
  it("mid-court after completeness fixer: red → verify triage continue → fixer → green → re-open CMR & ship", async () => {
    const completenessKey =
      "completeness|src/mid-court-completeness.ts:1|mid-court regression after completeness fix";
    const finding: Finding = {
      severity: "medium",
      category: "completeness",
      claim_quote: "mid-court regression after completeness fix",
      location: "src/mid-court-completeness.ts:1",
      suggested_fix: "repair the regression the completeness fixer introduced",
      action: "fix_now",
    };
    let verifyCalls = 0;
    let verifyJudgeCalls = 0;
    let coderDispatchCount = 0;
    let verifyFixHeadObserved = false;
    let backend!: CapableFamilyBackend;
    backend = new CapableFamilyBackend({
      readFamilyHead: () => {
        if (
          backend.currentFamilyHead !==
          "head-after-completeness-verify-fix"
        ) {
          return backend.currentFamilyHead;
        }
        if (!verifyFixHeadObserved) {
          verifyFixHeadObserved = true;
          return backend.currentFamilyHead;
        }
        throw new Error("later HEAD observation unavailable — use propagated HEAD");
      },
      verify: () => {
        verifyCalls += 1;
        // #1 initial final verify green → enter CMR.
        // #2 mid-court after completeness fixer red → shared verify court.
        // #3 court mechanical re-verify green → resume completeness court.
        if (verifyCalls === 2) {
          return {
            ok: false,
            errorPackage: {
              reason: "mid-court verify red after completeness fixer",
            },
          };
        }
        return { ok: true };
      },
      cmr: (req) => {
        if (req.cmrPass === "completeness") {
          if (req.priorCmrFindingIdentityKeys?.includes(completenessKey)) {
            return {
              converged: true,
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              claimedFixedFindingIdentityKeys: [completenessKey],
            };
          }
          return {
            converged: false,
            findingsCount: 1,
            reason: "completeness found a mid-court seam bug",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            findings: [finding],
            ...CMR_EVIDENCE,
          };
        }
        return {
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        };
      },
      async worker(spec, ctx) {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            verifyJudgeCalls += 1;
            return completedJudge(
              verifyJudgeCalls === 1
                ? judgeContinue([
                    sampleFinding(
                      "mid-court completeness verify finding",
                      "src/mid-court-completeness.ts:1",
                    ),
                  ])
                : judgeConverged(),
            );
          }
          const cmr = await backend.runIntegratedCmr({
            familyBase: ctx.familyBase ?? "family/1110-mid-court-completeness",
            ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
            ...(ctx.priorCmrFindingIdentityKeys !== undefined
              ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
              : {}),
          });
          return {
            kind: "completed",
            output: cmrScriptToWorkerOutput(cmr),
          };
        }
        if (spec.kind === "coder") {
          coderDispatchCount += 1;
          // First coder = completeness CMR fixer; second = verify-court fixer
          // after mid-court red.
          if (coderDispatchCount === 1) {
            backend.currentFamilyHead = "head-after-completeness-fix";
          } else if (coderDispatchCount === 2) {
            backend.currentFamilyHead = "head-after-completeness-verify-fix";
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "ship") {
          backend.prCalls.push({
            familyBase: ctx.familyBase ?? "family/1110-mid-court-completeness",
          });
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase ?? "family/1110-mid-court-completeness",
              pr: "https://github.com/test/repo/pull/1110",
              prHead: backend.currentFamilyHead,
              status: "pr_opened",
            },
          };
        }
        return dispatchReviewLoopThroughAdmission(backend, spec, ctx);
      },
    });
    backend.currentFamilyHead = "head-before-completeness-fix";

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1110-mid-court-completeness",
      familyBackend: backend,
      familyHeadAfter: "head-before-completeness-fix",
      familyIssue: 1110,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(verifyCalls).toBe(3);
    expect(verifyJudgeCalls).toBe(2);
    expect(coderDispatchCount).toBe(2);
    const steps = backend.ledger.map((e) => e.workerStep);
    expect(steps).toContain("wave-verify-judge");
    expect(steps).toContain("wave-verify-fix");
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual([
      "completeness",
      "completeness",
      "completeness",
      "correctness",
    ]);
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "cmr_passed",
        phase: "final",
        familyHeadAfter: "head-after-completeness-verify-fix",
      }),
    );
    expect(backend.prCalls).toEqual([
      { familyBase: "family/1110-mid-court-completeness" },
    ]);
    expect(backend.aborted).toEqual([]);
  });

  it("mid-court after completeness fixer: real toolchain red → verify_failed (verify-court fixer zero-spin)", async () => {
    const finding: Finding = {
      severity: "medium",
      category: "completeness",
      claim_quote: "toolchain red after completeness fix",
      location: "src/mid-court-completeness-toolchain.ts:1",
      suggested_fix: "irrelevant — mid-court verify is toolchain",
      action: "fix_now",
    };
    let verifyCalls = 0;
    let coderDispatchCount = 0;
    let backend!: CapableFamilyBackend;
    backend = new CapableFamilyBackend({
      verify: () => {
        verifyCalls += 1;
        // Initial green; mid-court after completeness fixer stays red (toolchain).
        if (verifyCalls === 1) return { ok: true };
        return {
          ok: false,
          errorPackage: {
            reason: "MODULE_NOT_FOUND mid-court after completeness fixer",
          },
        };
      },
      cmr: (req) => {
        if (req.cmrPass === "completeness") {
          return {
            converged: false,
            findingsCount: 1,
            reason: "completeness finding before mid-court toolchain red",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            findings: [finding],
            ...CMR_EVIDENCE,
          };
        }
        throw new Error("correctness must not open after completeness mid-court toolchain abort");
      },
      async worker(spec, ctx) {
        if (spec.kind === "cmr") {
          if (spec.promptFile === "wave_verify_judge.md") {
            return completedJudge(
              judgeToolchain(
                "MODULE_NOT_FOUND",
                "missing dep during completeness mid-court re-verify",
              ),
            );
          }
          const cmr = await backend.runIntegratedCmr({
            familyBase:
              ctx.familyBase ?? "family/1110-mid-completeness-toolchain",
            ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
            ...(ctx.priorCmrFindingIdentityKeys !== undefined
              ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
              : {}),
          });
          return {
            kind: "completed",
            output: cmrScriptToWorkerOutput(cmr),
          };
        }
        if (spec.kind === "coder") {
          coderDispatchCount += 1;
          backend.currentFamilyHead = "head-after-completeness-fix-toolchain";
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.kind === "ship") {
          throw new Error(
            "ship must not run after completeness mid-court toolchain abort",
          );
        }
        return dispatchReviewLoopThroughAdmission(backend, spec, ctx);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1110-mid-completeness-toolchain",
      familyBackend: backend,
      familyHeadAfter: "head-before",
      familyIssue: 1110,
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "verify_failed",
    });
    // Only the completeness CMR fixer spun; verify-court toolchain = zero
    // verify-fixer.
    expect(coderDispatchCount).toBe(1);
    expect(backend.ledger.map((e) => e.workerStep)).toContain("wave-verify-judge");
    expect(backend.ledger.map((e) => e.workerStep)).not.toContain(
      "wave-verify-fix",
    );
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("final");
    expect(backend.aborted[0]?.errorPackage.reason).toContain(
      "final verify toolchain",
    );
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: expect.stringContaining("final verify toolchain"),
        stopSummary: expect.objectContaining({
          reason: "verify_failed",
          repairHint: expect.stringContaining("toolchain/dependency"),
        }),
      }),
    );
    expect(backend.prCalls).toEqual([]);
    // Completeness never re-opens; correctness never opens after toolchain
    // mid-court abort.
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual(["completeness"]);
    expect(verifyCalls).toBeGreaterThanOrEqual(2);
  });
});

describe("#296 verify-cmr hook body — final phase (full verify → cmr → PR)", () => {
  it("worker-declared zero passes even when leg prose reports missing cross-vendor coverage", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["agy"],
        skippedLegs: [
          { slug: "opus", reason: "auth unavailable" },
          { slug: "gpt-5.6-sol", reason: "auth unavailable" },
        ],
        ...CMR_EVIDENCE,
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(backend.prCalls).toHaveLength(1);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toHaveLength(2);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          entry.stopSummary?.reason === "provider_degraded",
      ),
    ).toBe(false);
  });
  it("positive open-count routes to coder-fix regardless of leg prose", async () => {
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
        findingsCount: 1,
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

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.prCalls).toEqual([]);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(true);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_fix_committed"),
    ).toBe(false);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          entry.stopSummary?.reason === "provider_degraded",
      ),
    ).toBe(false);
  });

  it("#875: undeclared successful legs no longer kill the run (leg-accounting court demolished)", async () => {
    // Pre-#875: extra undeclared "opus" on claude-tight → infra_failure court death.
    // Post-#875: leg lists are prose and do not enter runner routing.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["gpt-5.6-sol", "agy", "opus"],
      }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /not declared|leg accounting/i.test(
            typeof entry.reason === "string" ? entry.reason : "",
          ),
      ),
    ).toBe(false);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toHaveLength(2);
  });

  it("does not route on an anchor-leg skip reported as worker prose", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["gpt-5.6-sol", "agy"],
        skippedLegs: [{ slug: "opus", reason: "provider unavailable" }],
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toHaveLength(2);
    expect(backend.prCalls).toHaveLength(1);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toHaveLength(2);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          entry.stopSummary?.reason === "provider_degraded",
      ),
    ).toBe(false);
  });

  it("fingerprints the resolved route without re-throwing an already accepted tight-route violation", async () => {
    // #936: slot/CMR env overrides deleted — fingerprint the preset route only.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["gpt-5.6-sol"] }),
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
      pr: "https://github.com/test/repo/pull/291",
      familyHeadAfter: "head-1",
      stopSummary: expect.objectContaining({
        reason: "success",
        metadata: {
          heads: {
            reportedFamilyHead: "head-1",
            actualFamilyHead: "head-1",
            verifiedCmrHead: "head-1",
            sources: {
              reportedFamilyHead: "family HEAD carried after ship worker completion",
              actualFamilyHead: "family head after ship worker completion",
              verifiedCmrHead: "latest cmr_passed ledger row",
            },
          },
        },
      }),
    }));
  });

  it("accepts family ship completed without re-judging its PR on the host", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      pr: () => ({ url: "https://github.com/test/repo/pull/291", prHead: "head-1" }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.prCalls).toHaveLength(1);
    expect(backend.ledger.some((entry) => entry.status === "shipped")).toBe(true);
    expect(backend.escalations).toEqual([]);
  });

  it("does not require a family host-verification capability before dispatch", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/823-base",
      familyBackend: backend,
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.prCalls).toHaveLength(1);
    expect(backend.ledger.some((entry) => entry.status === "shipped")).toBe(true);
  });

  it("#875: converged CMR ships even when runner-protected priors are not claimed fixed (coverage court demolished)", async () => {
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

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /were not explicitly claimed fixed/i.test(
            typeof entry.reason === "string" ? entry.reason : "",
          ),
      ),
    ).toBe(false);
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toHaveLength(2);
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

  it("keeps completed authoritative when post-ship local HEAD cargo is unavailable", async () => {
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

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(true);
    expect(backend.ledger.some((e) => e.status === "aborted")).toBe(false);
  });

  it("persists host family HEAD when the worker reports a stale PR head", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
      pr: (req) => ({ url: `https://github.com/test/repo/pull/291`, prHead: "stale-pr-head" }),
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

  // #881 (#434 live-semantic revision): align resume with the live final-barrier
  // loop — after a later pass's coder-fix advances HEAD, completeness is NOT
  // re-run live; resume must likewise skip when the advance is explained only by
  // barrier-internal cmr_fix_committed rows.
  it("#881: resume skips a prior pass when HEAD advanced only via barrier-internal fix commits", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    backend.currentFamilyHead = "head-after-correctness-fix";
    backend.ledger.push(
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-at-completeness-pass",
        routeFingerprint: currentRouteFingerprint(),
      },
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadAfter: "head-at-completeness-pass",
      },
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        phase: "final",
        cmrPass: "correctness",
        familyHeadBefore: "head-at-completeness-pass",
        familyHeadAfter: "head-after-correctness-fix",
      },
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-correctness-fix",
    });

    expect(result).toEqual({ ok: true, ran: true });
    // Completeness already passed; only correctness re-runs at the advanced head.
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
  });

  it("#881: resume re-verifies a prior pass when HEAD advanced outside the barrier (no fix chain)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    backend.currentFamilyHead = "head-from-external-advance";
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: "head-at-completeness-pass",
      routeFingerprint: currentRouteFingerprint(),
    });
    // No cmr_fix_committed bridging the two heads → barrier-external advance.

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-from-external-advance",
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
      pr: "https://github.com/test/repo/pull/291",
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
    // Landing Action re-reads family HEAD twice for post-doc marker keying
    // (entry already_done lookup + post-docs completionHeadOid; C1 / #972).
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
          findingsCount: 1,
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
            output: cmrScriptToWorkerOutput(cmr),
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
            },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase ?? "family/291-base",
              pr: "https://github.com/test/repo/pull/291",
              prHead: backend.currentFamilyHead,
              status: "pr_opened",
            },
          };
        }
        if (
          spec.kind === "verify" ||
          spec.kind === "fixer" ||
          spec.kind === "cleanup" ||
          spec.kind === "landing"
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
                    : { kind: "landing", released: true },
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
      runId: "run-786-correctness-reverify",
      familyIssue: 786,
    });

    expect(result).toEqual({ ok: true, ran: true });
    // #1080: correctness continue → fix → pure receive → panel outer gate.
    expect(backend.cmrCalls.map((call) => call.cmrPass)).toEqual([
      "completeness",
      "correctness",
      "correctness",
      "correctness",
    ]);
    expect(backend.verifyCalls).toEqual([
      {
        phase: "final",
        familyBase: "family/291-base",
        runId: "run-786-correctness-reverify",
        issue: 786,
      },
      {
        phase: "final",
        familyBase: "family/291-base",
        runId: "run-786-correctness-reverify",
        issue: 786,
      },
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      cmrPass: "correctness",
      familyHeadAfter: "head-after-correctness-fix",
    }));
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
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
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
            pr: `https://github.com/test/repo/pull/291`,
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

    // Decision park: omit failedStatus so the spine escalates (not stage death).
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]).toMatchObject({
      reason: "completeness cmr needs human review",
      diagnosis: "review workers disagreed on whether the pass can converge",
      escalationKind: "decision",
      familyHeadAfter: "head-after-final-verify",
      stopSummary: {
        reason: "decision_gate_park",
        summary:
          "completeness cmr needs human review — review workers disagreed on whether the pass can converge",
      },
    });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: "completeness cmr needs human review",
      familyHeadAfter: "head-after-final-verify",
      stopSummary: expect.objectContaining({ reason: "decision_gate_park" }),
    }));
    expect(backend.ledger.some((e) => e.status === "shipped")).toBe(false);
  });

  it("runner-synthesized CMR startup failure is stamped failure, never decision", async () => {
    const backend = new CapableFamilyBackend({
      worker: (spec) => {
        if (spec.kind !== "cmr") {
          throw new Error(`unexpected worker ${spec.kind}`);
        }
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason: "cmr worker auth missing",
            diagnosis: "startup preflight rejected the launch",
          }),
        };
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-final-verify",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.escalations).toContainEqual(expect.objectContaining({
      escalationKind: "failure",
      reason: "cmr worker auth missing",
      stopSummary: expect.objectContaining({ reason: "cmr_failed" }),
    }));
  });

  it("runner-synthesized coder-fix startup failure is stamped failure, never decision", async () => {
    const backend = new CapableFamilyBackend({
      worker: (spec) => {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: liveCmrJudgeContinue(
              [{
                severity: "high",
                category: "correctness",
                claim_quote: "startup marker must retain runner provenance",
                location: "src/family/verifyCmr.ts:coder-fix",
                suggested_fix: "stamp the synthesized failure",
                action: "fix_now",
              }],
              {
                successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
                ...CMR_EVIDENCE,
              },
            ),
          };
        }
        if (spec.kind === "coder") {
          return {
            kind: "escalated",
            escalation: runnerSynthesizedFailureEscalation({
              reason: "coder-fix worker auth missing",
              diagnosis: "startup preflight rejected the launch",
            }),
          };
        }
        throw new Error(`unexpected worker ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-final-verify",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.escalations).toContainEqual(expect.objectContaining({
      escalationKind: "failure",
      reason: "coder-fix worker auth missing",
      stopSummary: expect.objectContaining({ reason: "cmr_failed" }),
    }));
  });

  it("runner-synthesized ship startup failure is stamped failure, never decision", async () => {
    const backend = new CapableFamilyBackend({
      worker: (spec) => {
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
              ...CMR_EVIDENCE,
            },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "escalated",
            escalation: runnerSynthesizedFailureEscalation({
              reason: "ship worker auth missing",
              diagnosis: "startup preflight rejected the launch",
            }),
          };
        }
        throw new Error(`unexpected worker ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
      familyHeadAfter: "head-after-final-verify",
    });

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
    expect(backend.escalations).toContainEqual(expect.objectContaining({
      escalationKind: "failure",
      reason: "ship worker auth missing",
      stopSummary: expect.objectContaining({ reason: "ship_failed" }),
    }));
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
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "converged",
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

    // Decision park: omit failedStatus so the spine escalates (not stage death).
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]).toMatchObject({
      reason: "ship needs human review",
      diagnosis: "release note conflict",
      escalationKind: "decision",
      familyHeadAfter: "head-after-ship-worker-bump",
      stopSummary: {
        reason: "decision_gate_park",
        summary: "ship needs human review — release note conflict",
      },
    });
  });
});

describe("#296 verify-cmr hook body — required verify capability (#939)", () => {
  it("BareFamilyBackend with explicit green verify yields ok:true, ran:true (no success no-op)", async () => {
    // #939 deleted the optional missing-capability success NOOP. Fakes must
    // implement runFamilyVerify; a green verify is real work (ran:true).
    // Type-level required capability replaces HEAD's runtime-missing fail-closed
    // test (which needed optional `runFamilyVerify?`).
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: new BareFamilyBackend(),
    });
    expect(result).toEqual({ ok: true, ran: true });
  });

  it("#940: cmr worker process failure after green verify is cmr_failed — never empty-success", async () => {
    // #940 / ID-012: production/test contract guarantees dispatchWorker; the
    // host no longer has a missing-capability fake exit. A real dispatch that
    // fails still fails the final barrier (not a silent pass).
    class CmrWorkerFailedBackend extends BareFamilyBackend {
      readonly verifyCalls: FamilyVerifyRequest[] = [];
      async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
        this.verifyCalls.push(req);
        return { ok: true };
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "failed",
            reason: "family cmr worker unavailable: test pin",
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      }
    }
    const backend = new CmrWorkerFailedBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(backend.verifyCalls).toHaveLength(1);
    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
  });

  it("#940: residual IntegratedCmrResult alone is not a court pass (live judge required)", async () => {
    // Live dispatchWorker returns residual unusable paper; #919 M2 residual
    // never silent-cleans from boolean green. Fail-safe is cmr_failed.
    class ResidualOnlyBackend extends BareFamilyBackend {
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            // residual open-count paper — not kind:judge
            output: { kind: "reviewer", findingsCount: 0, findings: [] },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      }
    }
    const backend = new ResidualOnlyBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
  });
});

// ═══════════════════ durable family mechanical redispatch budget (#934) ═══════════════════

describe("#934 family mechanical redispatch budget reconstruction", () => {
  it("reads trailing failure markers for the workerStep (crash re-entry continues budget)", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "cmr:completeness",
        mechanicalRedispatchAttempt: 1,
        reason: "boom-1",
      },
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        // spawn adoption between retries — no attempt counter
      },
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "cmr:completeness",
        mechanicalRedispatchAttempt: 4,
        reason: "boom-4",
      },
    ];
    expect(
      mechanicalRedispatchAttemptsFromFamilyLedger(ledger, "cmr:completeness"),
    ).toBe(4);
  });

  it("resets budget after a later non-marker phase outcome (no inherit across success)", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "coder",
        mechanicalRedispatchAttempt: 3,
        reason: "old streak",
      },
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
      },
    ];
    expect(mechanicalRedispatchAttemptsFromFamilyLedger(ledger, "coder")).toBe(0);
  });

  it("does not count a different workerStep's markers", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "ship",
        mechanicalRedispatchAttempt: 5,
        reason: "ship crash",
      },
    ];
    expect(
      mechanicalRedispatchAttemptsFromFamilyLedger(ledger, "cmr:correctness"),
    ).toBe(0);
    expect(mechanicalRedispatchAttemptsFromFamilyLedger(ledger, "ship")).toBe(5);
  });

  it("exhausted durable budget equals MAX_DISPATCH_ATTEMPTS", () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: "verify",
        mechanicalRedispatchAttempt: MAX_DISPATCH_ATTEMPTS,
        reason: "last attempt failed",
      },
    ];
    expect(
      mechanicalRedispatchAttemptsFromFamilyLedger(ledger, "verify"),
    ).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

// ═══════════════════ defensive catch around the family worker dispatch (cmr S336 r8) ═══════════════════

describe("cmr S336 r8 — a family worker that THROWS on startup is a documented gate result, not an escaped exception", () => {
  /**
   * The single-slice runner wraps its former terminal dispatch path in try/catch → S8(error);
   * verifyCmr did NOT wrap its cmr / ship dispatch. The token preflight (cmr S336 r8)
   * removes the missing-auth throw, but the worker ALSO `git checkout`s the family
   * base + writes the focus file + spins docker — any of which can still throw out of
   * `dispatchWorker` and reject the WHOLE family run, bypassing the stage-named
   * fail-safe. So verifyCmr must catch a thrown startup error, record it (observable),
   * and fail-safe to {ok:false, ran:true} with the matching stage status.
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
      const panelLeg = completeCmrPanelLegWorker(spec);
      if (panelLeg !== undefined) return panelLeg;
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
              kind: "judge",
              status: "converged",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          ...CMR_EVIDENCE,
        },
      };
    }
  }

  it("a cmr worker that throws on startup ⇒ cmr_failed gate (ok:false, ran:true), abort recorded — never an escaped throw", async () => {
    const backend = new ThrowingDispatchBackend("cmr");
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
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

  it("#598: read-only and ship worker crashes both use the bounded mechanical retry", async () => {
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
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === this.throwOnKind) {
          this.throwKindDispatches += 1;
          throw new Error(`${spec.kind} worker: git checkout ${ctx.familyBase} failed (no such ref)`);
        }
        return {
          kind: "completed",
          output: {
              kind: "judge",
              status: "converged",
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
    expect(shipResult).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
    expect(shipBackend.throwKindDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(shipBackend.aborted[0]?.errorPackage.reason).toMatch(/git checkout/i);

    const cmrBackend = new CountingThrowBackend("cmr");
    const cmrResult = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: cmrBackend,
    });
    expect(cmrResult).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(cmrBackend.throwKindDispatches).toBe(MAX_DISPATCH_ATTEMPTS);
  });

  it("#909: QuotaWaitForResetError from family cmr is rethrown — not swallowed as failed leg-kill", async () => {
    // dispatchOrAbort's outer catch used to map ANY throw into
    // `{kind:"failed", reason:"…threw on startup"}`, collapsing a 429 park signal
    // into generic leg failure. Quota wait must surface as QuotaWaitForResetError
    // so upper family/runner park/relay can consume it (same as single-slice).
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    class QuotaWaitCmrBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      dispatches = 0;
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          this.dispatches += 1;
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "zai",
              resetAt,
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "zai",
                resetAt: resetAt.toISOString(),
                reason: "quota limited (429); wait for reset",
                step: "S3",
                workerPid: 0,
                ts: "2026-07-08T12:00:00.000Z",
              },
            },
            pool: "zai"
          });
        }
        return {
          kind: "completed",
          output: {
              kind: "judge",
              status: "converged",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            ...CMR_EVIDENCE,
          },
        };
      }
    }

    const backend = new QuotaWaitCmrBackend();
    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/291-base",
        familyBackend: backend,
      }),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
    // Not mechanical-retried either (withMechanicalRetry already rethrows).
    expect(backend.dispatches).toBe(1);
    // Must NOT look like generic startup failed / stage fail-safe abort.
    expect(backend.aborted).toHaveLength(0);
  });

  it("#909: QuotaWaitForResetError from family ship is rethrown — not failed ship leg", async () => {
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    class QuotaWaitShipBackend extends BareFamilyBackend {
      readonly aborted: FamilyAbortedEvent[] = [];
      shipDispatches = 0;
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async recordAborted(event: FamilyAbortedEvent): Promise<void> {
        this.aborted.push(event);
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "ship") {
          this.shipDispatches += 1;
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "zai",
              resetAt,
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "zai",
                resetAt: resetAt.toISOString(),
                reason: "quota limited (429); wait for reset",
                step: "S7",
                workerPid: 0,
                ts: "2026-07-08T12:00:00.000Z",
              },
            },
            pool: "zai"
          });
        }
        return {
          kind: "completed",
          output: {
              kind: "judge",
              status: "converged",
            successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
            ...CMR_EVIDENCE,
          },
        };
      }
    }

    const backend = new QuotaWaitShipBackend();
    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/291-base",
        familyBackend: backend,
      }),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
    expect(backend.shipDispatches).toBe(1);
    expect(backend.aborted).toHaveLength(0);
  });

  it("a cmr worker failed result for missing dependencies is recorded as cmr_failed", async () => {
    class FailedCmrBackend extends ThrowingDispatchBackend {
      constructor() {
        super("ship");
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
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

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("Cannot find module 'missing-cmr-runtime'"),
      familyHeadAfter: "head-before-worker",
      stopSummary: expect.objectContaining({
        reason: "cmr_failed",
        repairHint: expect.stringContaining("install or restore"),
      }),
    }));
  });

  it("a ship worker that throws on startup (after a converged cmr) ⇒ ship_failed gate, abort recorded — never an escaped throw", async () => {
    const backend = new ThrowingDispatchBackend("ship");
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toMatch(/git checkout/i);
  });

  it("a ship worker failed result for push/auth infra is recorded as ship_failed", async () => {
    class FailedShipBackend extends ThrowingDispatchBackend {
      constructor() {
        super("cmr");
      }
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeCmrPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "converged",
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

    expect(result).toMatchObject({
      ok: false,
      ran: true,
      failedStatus: "ship_failed",
    });
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      reason: expect.stringContaining("git push authentication failed"),
      stopSummary: expect.objectContaining({
        reason: "ship_failed",
        repairHint: expect.stringContaining("ship worker infrastructure"),
      }),
    }));
  });
});
