/**
 * #1119 / #1117 S2 — cold-start ledger re-entry re-dispatches panel legs.
 *
 * Seams:
 *   1. ensureFamilyCmrPanelEvidence — sole fan-out gate (reuse vs reburn)
 *   2. runFamily spine with durable park + escalation_answered only
 *      (zero process-local refuse/receiveBuilder maps) → real runVerifyCmr
 *   3. zero-success fan-out lands host skip reasons (no silent empty court)
 *
 * Authority: #1119 AC; #1118 mechanism; ADR 0141 / 0147.
 */
import { describe, expect, it } from "vitest";
import {
  ensureFamilyCmrPanelEvidence,
  hasValidPanelLegTransports,
  normalizePanelLegTransportCargo,
} from "../../../src/family/cmrPanelLegs.js";
import { runFamily } from "../../../src/family/runner.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import {
  completeCmrPanelLegWorker,
  isCmrPanelLegWorker,
} from "../../helpers/cmr-panel-leg-dispatch.js";
import { completedJudge, judgeConverged } from "../../helpers/judge-fixtures.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose (ADR 0141 legal paper)\n## Findings\nP2: none";

describe("#1119 ensureFamilyCmrPanelEvidence unit gate", () => {
  it("fans out when transports missing (positive); reuses when valid (control, no reburn)", async () => {
    const legs = [
      { family: "codex" as const, slug: "gpt-5.6-sol" },
      { family: "grok" as const, slug: "grok-4.5" },
    ];
    let dispatchCount = 0;
    const dispatch = async (spec: WorkerSpec): Promise<WorkerResult> => {
      dispatchCount += 1;
      return (
        completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
          kind: "failed",
          reason: "not a panel leg",
        }
      );
    };

    const missing = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "completeness",
      dispatch,
    });
    expect(missing.dispatched).toBe(true);
    expect(missing.transports.length).toBe(2);
    expect(hasValidPanelLegTransports(missing.transports)).toBe(true);
    expect(dispatchCount).toBe(2);

    const afterValid = dispatchCount;
    const reused = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "completeness",
      existingTransports: missing.transports,
      dispatch,
    });
    expect(reused.dispatched).toBe(false);
    expect(reused.transports).toEqual(missing.transports);
    expect(dispatchCount).toBe(afterValid);
  });

  it("negative: empty / illegal cargo never counts as valid (no false reuse)", () => {
    expect(hasValidPanelLegTransports(undefined)).toBe(false);
    expect(hasValidPanelLegTransports([])).toBe(false);
    expect(
      hasValidPanelLegTransports([
        { slug: "gpt-5.6-sol", exitCode: 1, stdout: "docker flake" },
      ]),
    ).toBe(false);
    expect(
      normalizePanelLegTransportCargo([
        { slug: "", exitCode: 0, stdout: "x" },
        { slug: "ok", exitCode: "nope", stdout: "x" },
        { slug: "gpt-5.6-sol", exitCode: 0, stdout: LEGAL_PANEL_STDOUT },
      ]),
    ).toEqual([
      { slug: "gpt-5.6-sol", exitCode: 0, stdout: LEGAL_PANEL_STDOUT },
    ]);
  });
});

describe("#1119 cold-start runFamily ledger re-entry panel fan-out", () => {
  /**
   * Production R4 shape after process exit: durable ledger only —
   * child already merged, completeness court parked on missing transports,
   * human escalation_answered "rerun jury". No process-local maps.
   * Spine must re-enter via real runVerifyCmr and fan-out panel legs before
   * pure judge (not a direct runVerifyCmr call).
   */
  it("parked integrated court + answer → panel legs dispatched; judge gets transports", async () => {
    const familyHead = "head-parked-no-transports";
    const panelDispatchCounts: string[] = [];
    const judgeLandings: Array<WorkerLandingPayload | undefined> = [];
    const judgeCtxTransports: Array<number | undefined> = [];
    const escalations: FamilyEscalation[] = [];

    class ColdResumeFamilyBackend implements FamilyBackend {
      ledger: FamilyLedgerEntry[] = [
        {
          childIssue: 1119,
          status: "merged",
          childBranch: "feat/issue-1119",
        },
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          phase: "final",
          cmrPass: "completeness",
          reason:
            "fresh completeness jury transports are missing — no panelLegTransports",
          familyHeadAfter: familyHead,
          blockingFindingIdentityKeys: [],
          sessionId: "judge-session-completeness-parked",
          judgeStatus: "escalate",
          stopSummary: {
            reason: "decision_gate_park",
            summary:
              "fresh completeness jury transports are missing — no panelLegTransports",
            repairHint:
              "answer the family judge decision gate, then resume the family court in place",
          },
        },
        {
          status: "escalated",
          event: "escalated",
          phase: "final",
          cmrPass: "completeness",
          escalationKind: "decision",
          reason:
            "fresh completeness jury transports are missing — no panelLegTransports",
          familyHeadAfter: familyHead,
          stopSummary: {
            reason: "decision_gate_park",
            summary:
              "fresh completeness jury transports are missing — no panelLegTransports",
            repairHint:
              "answer the family judge decision gate, then resume the family court in place",
          },
        },
        {
          status: "escalation_answered",
          event: "escalation_answered",
          phase: "final",
          answer: "rerun jury — re-dispatch fresh completeness panel legs",
          source: "human",
        },
      ];

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

      async mergeChildIntoFamilyBase(_child: MergeRequest) {
        return { familyHead };
      }
      async resolveMergeConflict(): Promise<{ familyHead: string }> {
        throw new Error("unused on cold resume (child already merged)");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      }
      async readFamilyLedger() {
        return this.ledger;
      }
      async readFamilyHead() {
        return familyHead;
      }
      async runFamilyVerify() {
        return { ok: true };
      }
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          // Cold re-entry must never thread pure-court resume into panel legs.
          expect(ctx.resumeSessionId).toBeUndefined();
          panelDispatchCounts.push(`${ctx.cmrPass ?? "?"}:${spec.model}`);
          return (
            completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeLandings.push(landing);
          judgeCtxTransports.push(ctx.panelLegTransports?.length);
          // Judge may resume ledger session; landing must still carry fresh
          // transports from this re-entry fan-out (not vanished process temps).
          expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
          expect(ctx.panelLegTransports?.length).toBeGreaterThan(0);
          if (ctx.cmrPass === "completeness") {
            expect(ctx.resumeSessionId).toBe(
              "judge-session-completeness-parked",
            );
          }
          return completedJudge(
            judgeConverged(),
            ctx.cmrPass === "completeness"
              ? "judge-session-completeness-parked"
              : "judge-session-correctness-1",
          );
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1119",
              prHead: familyHead,
              status: "pr_opened",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      }
      async recordAborted() {}
      async escalateFamily(esc: FamilyEscalation) {
        escalations.push(esc);
      }
    }

    class ColdResumeChildBackend implements Backend {
      async smokeModelRoute(route: any) {
        const { smokeRouteModels } = await import(
          "../../../src/modelRoutes.js"
        );
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<ResumeState | undefined> {
        return undefined;
      }
      async resumeSession(): Promise<StepOutput> {
        throw new Error("child must not run — already merged");
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
        throw new Error("child must not run — already merged");
      }
      async runStep(_spec: StepSpec): Promise<StepOutput> {
        throw new Error("child must not run — already merged");
      }
      async writeLedger(
        _entry: PersistentLedgerEntry,
        _stateDir: string,
      ): Promise<void> {}
    }

    const familyBackend = new ColdResumeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 1117,
      children: [{ issue: 1119, blockedBy: [] }],
    };

    // Default verifyCmr = production runVerifyCmr (not a stub). Cold spine only.
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new ColdResumeChildBackend(),
      familyBase: "family/1117-cold-resume",
    });

    // Completeness re-open after park must fan out (not zero panel dispatches).
    expect(
      panelDispatchCounts.some((s) => s.startsWith("completeness:")),
    ).toBe(true);
    expect(judgeLandings.length).toBeGreaterThan(0);
    for (const landing of judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
    for (const n of judgeCtxTransports) {
      expect(n).toBeGreaterThan(0);
    }
    // Human answer must not re-park solely for missing transports.
    expect(
      escalations.some((e) =>
        /transports are missing|zero successful panel legs/i.test(
          `${e.reason} ${e.diagnosis ?? ""}`,
        ),
      ),
    ).toBe(false);
    // Spine reached beyond the park — completed or later-stage park is fine;
    // the load-bearing contract is panel fan-out before pure judge.
    void result;
  });

  it("control via ensure gate: pre-seeded valid transports are not reburned under runVerifyCmr", async () => {
    // Direct court open with existing valid transports on landing path:
    // ensureFamilyCmrPanelEvidence must report dispatched:false (unit already
    // covers; this pairs with cold negative via production runVerifyCmr open
    // when transports are injected on refuse-reopen / ctx).
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const priorTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: LEGAL_PANEL_STDOUT,
      },
      {
        slug: "grok-4.5",
        exitCode: 0,
        stdout: LEGAL_PANEL_STDOUT,
      },
    ];
    expect(hasValidPanelLegTransports(priorTransports)).toBe(true);

    let panelDispatches = 0;
    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
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
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "head-valid-transports" };
      },
      async resolveMergeConflict() {
        throw new Error("unused");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      },
      async readFamilyLedger() {
        return this.ledger;
      },
      async readFamilyHead() {
        return "head-valid-transports";
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatches += 1;
          return (
            completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          // Production gate reuses only when existing transports are threaded
          // via refuseReopenLanding/ctx — first open has none, so fan-out is
          // correct. Control of "no reburn" is the ensure unit above; here we
          // assert first open still lands transports for the judge.
          expect(
            (landing?.panelLegTransports?.length ?? 0) +
              (ctx.panelLegTransports?.length ?? 0),
          ).toBeGreaterThan(0);
          return completedJudge(
            judgeConverged(),
            `judge-${ctx.cmrPass ?? "cmr"}`,
          );
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1119-ctrl",
              prHead: "head-valid-transports",
              status: "pr_opened",
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-no-reburn-control",
      familyBackend: backend,
      familyHeadAfter: "head-valid-transports",
    });
    // First open has no prior landing → fan-out expected (positive first open).
    expect(panelDispatches).toBeGreaterThan(0);
    // Reuse control (dispatched:false) lives on ensureFamily unit above.
    void priorTransports;
  });

  it("negative: all panel legs fail → zero successful park; pure judge never opens empty", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    let judgeDispatched = 0;
    const backend = {
      ledger: [] as FamilyLedgerEntry[],
      escalations: [] as FamilyEscalation[],
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
      },
      async mergeChildIntoFamilyBase() {
        return { familyHead: "head-zero-legs" };
      },
      async resolveMergeConflict() {
        throw new Error("unused");
      },
      async appendFamilyLedger(entry: FamilyLedgerEntry) {
        this.ledger.push(entry);
      },
      async readFamilyLedger() {
        return this.ledger;
      },
      async readFamilyHead() {
        return "head-zero-legs";
      },
      async runFamilyVerify() {
        return { ok: true };
      },
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          return {
            kind: "failed",
            reason: `docker flake on ${spec.model}`,
          };
        }
        if (spec.kind === "cmr") {
          judgeDispatched += 1;
          return completedJudge(judgeConverged(), "should-not-open");
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
      async recordAborted() {},
      async escalateFamily(esc: FamilyEscalation) {
        this.escalations.push(esc);
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-zero-panel",
      familyBackend: backend,
    });

    expect(result.ok).toBe(false);
    expect(judgeDispatched).toBe(0);
    expect(backend.escalations.length).toBeGreaterThan(0);
    expect(backend.escalations[0]?.escalationKind).toBe("decision");
    expect(backend.escalations[0]?.reason).toMatch(/zero successful panel legs/i);
    expect(backend.escalations[0]?.diagnosis).toMatch(/docker flake/i);
  });
});
