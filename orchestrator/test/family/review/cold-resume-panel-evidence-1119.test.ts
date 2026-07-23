/**
 * #1119 — cold-start ledger re-entry panel evidence (production spine).
 *
 * One seam: ensureFamilyCmrPanelEvidence via real runFamily → runVerifyCmr.
 * Durable evidence lives on FamilyBackend.read/writeFamilyPanelLegEvidence
 * (ledgerDir truth; not process-temp fix-findings).
 *
 * Authority: #1119 AC; #1117 invariant; #1118 single gate; ADR 0141 / 0147.
 * P1 identity: ledgerPhase + routeFingerprint + courtGeneration + HEAD.
 */
import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import {
  modelRouteFingerprint,
  resolveActiveModelRoute,
} from "../../../src/modelRoutes.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyPanelLegEvidence,
  IntegratedCmrPass,
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
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";
import { mintFourReasonRefuseRecord } from "../../helpers/coder-refuse-fixtures.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose (ADR 0141 legal paper)\n## Findings\nP2: none";
const FAMILY_HEAD = "head-parked-1119";
const EPIC: FamilyEpic = {
  issue: 1117,
  children: [{ issue: 1119, blockedBy: [] }],
};

/** Default production route fingerprint for identity-stamped seed evidence. */
function defaultRouteFingerprint(): string {
  return modelRouteFingerprint(resolveActiveModelRoute({}));
}

function legalTransports(
  stdout = "PRIOR durable panel paper\n## Findings\nnone",
): NonNullable<FamilyPanelLegEvidence["panelLegTransports"]> {
  return [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout },
    { slug: "grok-4.5", exitCode: 0, stdout },
  ];
}

/** Minimal child backend — children already merged; smoke only. */
class ChildSmokeBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("child must not run — already merged");
  }
  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    return {
      number: n,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    throw new Error("child must not run — already merged");
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("child must not run — already merged");
  }
  async writeLedger(
    _e: PersistentLedgerEntry,
    _d: string,
  ): Promise<void> {}
}

type CompletenessJudgeScript =
  | "always_converge"
  | "continue_then_converge";

/** Cold-start family backend: durable panel evidence + ledger park residue. */
class ColdSpineFamilyBackend implements FamilyBackend {
  ledger: FamilyLedgerEntry[];
  escalations: FamilyEscalation[] = [];
  panelDispatches: string[] = [];
  judgeLandings: Array<WorkerLandingPayload | undefined> = [];
  /** ledgerDir-shaped durable evidence (production: RealFamilyBackend file). */
  private durable = new Map<IntegratedCmrPass, FamilyPanelLegEvidence>();
  private readonly familyHead: string;
  private readonly failAllPanelLegs: boolean;
  private readonly completenessScript: CompletenessJudgeScript;
  private completenessJudgeOpens = 0;

  constructor(opts: {
    readonly familyHead?: string;
    readonly seedLedger: FamilyLedgerEntry[];
    readonly seedEvidence?: Partial<
      Record<IntegratedCmrPass, FamilyPanelLegEvidence>
    >;
    readonly failAllPanelLegs?: boolean;
    readonly completenessScript?: CompletenessJudgeScript;
  }) {
    this.familyHead = opts.familyHead ?? FAMILY_HEAD;
    this.ledger = [...opts.seedLedger];
    this.failAllPanelLegs = opts.failAllPanelLegs === true;
    this.completenessScript = opts.completenessScript ?? "always_converge";
    if (opts.seedEvidence !== undefined) {
      for (const [pass, ev] of Object.entries(opts.seedEvidence) as Array<
        [IntegratedCmrPass, FamilyPanelLegEvidence]
      >) {
        this.durable.set(pass, ev);
      }
    }
  }

  readFamilyPanelLegEvidence(
    pass: IntegratedCmrPass,
  ): FamilyPanelLegEvidence | undefined {
    return this.durable.get(pass);
  }
  writeFamilyPanelLegEvidence(
    pass: IntegratedCmrPass,
    evidence: FamilyPanelLegEvidence,
  ): void {
    this.durable.set(pass, evidence);
  }

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
  async mergeChildIntoFamilyBase(_c: MergeRequest) {
    return { familyHead: this.familyHead };
  }
  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("unused — child already merged");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry) {
    this.ledger.push(entry);
  }
  async readFamilyLedger() {
    return this.ledger;
  }
  async readFamilyHead() {
    return this.familyHead;
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
      expect(ctx.resumeSessionId).toBeUndefined();
      this.panelDispatches.push(`${ctx.cmrPass ?? "?"}:${spec.model}`);
      if (this.failAllPanelLegs) {
        return { kind: "failed", reason: `docker flake on ${spec.model}` };
      }
      return (
        completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
          kind: "failed",
          reason: "panel fixture missing",
        }
      );
    }
    if (spec.kind === "cmr") {
      this.judgeLandings.push(landing);
      if (ctx.cmrPass === "completeness") {
        this.completenessJudgeOpens += 1;
        if (
          this.completenessScript === "continue_then_converge" &&
          this.completenessJudgeOpens === 1
        ) {
          return completedJudge(
            judgeContinue([sampleFinding("builder must refuse", "x.ts:1")]),
            "judge-session-completeness-continue",
          );
        }
        return completedJudge(
          judgeConverged(),
          "judge-session-completeness-parked",
        );
      }
      return completedJudge(
        judgeConverged(),
        "judge-session-correctness-1",
      );
    }
    if (spec.kind === "coder") {
      // Legal refuse / no-op: HEAD unchanged (backend readFamilyHead fixed).
      const key = "1119:builder-refuse-no-op";
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 0,
          refusedFindingIdentityKeys: [key],
          refuseRecords: [
            mintFourReasonRefuseRecord({
              identityKey: key,
              reason: "not_established",
              evidence:
                "fixture refuse: finding does not hold on current code",
            }),
          ],
        },
        sessionId: "coder-fix-refuse-1119",
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          pr: "https://github.com/test/repo/pull/1119",
          prHead: this.familyHead,
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
    this.escalations.push(esc);
  }
}

function parkLedger(familyHead: string): FamilyLedgerEntry[] {
  return [
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
}

function mergedOnlyLedger(): FamilyLedgerEntry[] {
  return [
    {
      childIssue: 1119,
      status: "merged",
      childBranch: "feat/issue-1119",
    },
  ];
}

describe("#1119 cold-start runFamily panel evidence", () => {
  it("negative: empty durable landing → panel legs fan-out; judge gets transports", async () => {
    const backend = new ColdSpineFamilyBackend({
      seedLedger: parkLedger(FAMILY_HEAD),
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-cold-missing",
    });
    expect(
      backend.panelDispatches.some((s) => s.startsWith("completeness:")),
    ).toBe(true);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
    expect(
      backend.escalations.some((e) =>
        /transports are missing|zero successful panel legs/i.test(
          `${e.reason} ${e.diagnosis ?? ""}`,
        ),
      ),
    ).toBe(false);
  });

  it("control: same court generation + full identity → zero panel reburn; judge gets original 卷面", async () => {
    const priorTransports = legalTransports(
      "PRIOR durable completeness panel paper\n## Findings\nnone",
    );
    const backend = new ColdSpineFamilyBackend({
      seedLedger: parkLedger(FAMILY_HEAD),
      seedEvidence: {
        completeness: {
          familyHeadAfter: FAMILY_HEAD,
          ledgerPhase: "final",
          routeFingerprint: defaultRouteFingerprint(),
          courtGeneration: 0,
          panelLegTransports: priorTransports,
        },
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-cold-no-reburn",
    });
    // Completeness court must not reburn when durable identity matches.
    expect(
      backend.panelDispatches.filter((s) => s.startsWith("completeness:")),
    ).toEqual([]);
    const completenessLanding = backend.judgeLandings[0];
    expect(completenessLanding?.panelLegTransports).toEqual(priorTransports);
  });

  it("negative: all legs fail → durable runtime skip reasons land; pure judge not opened empty", async () => {
    // Fresh final barrier (no prior park) — zero-success host park path.
    const backend = new ColdSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      failAllPanelLegs: true,
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-zero-legs",
    });
    expect(backend.panelDispatches.length).toBeGreaterThan(0);
    // Host parks before pure judge — no silent empty court.
    expect(backend.judgeLandings.length).toBe(0);
    expect(backend.escalations.length).toBeGreaterThan(0);
    expect(backend.escalations[0]?.reason).toMatch(/zero successful panel legs/i);
    // F2: runtime skip reasons must be durable (re-court observable).
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.panelLegSkippedLegs?.length).toBeGreaterThan(0);
    expect(
      durable?.panelLegSkippedLegs?.every(
        (leg) =>
          typeof leg.slug === "string" &&
          typeof leg.reason === "string" &&
          /docker flake/i.test(leg.reason),
      ),
    ).toBe(true);
    // Identity stamped on zero-success durable write.
    expect(durable?.ledgerPhase).toBe("final");
    expect(durable?.routeFingerprint).toBe(defaultRouteFingerprint());
    expect(typeof durable?.courtGeneration).toBe("number");
  });

  it("P1: checkpoint-scoped durable correctness must not free-skip final correctness outer gate (same HEAD)", async () => {
    // Seed checkpoint-phase correctness 卷面 at the same HEAD the final barrier
    // will open with. Before the identity fix, HEAD-only reuse would starve final
    // of fresh legs; after fix, ledgerPhase mismatch forces fan-out.
    const backend = new ColdSpineFamilyBackend({
      seedLedger: parkLedger(FAMILY_HEAD),
      seedEvidence: {
        correctness: {
          familyHeadAfter: FAMILY_HEAD,
          ledgerPhase: "correctness_checkpoint",
          routeFingerprint: defaultRouteFingerprint(),
          courtGeneration: 0,
          panelLegTransports: legalTransports(
            "CHECKPOINT-only correctness paper — must not serve final",
          ),
        },
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-checkpoint-vs-final",
    });
    expect(
      backend.panelDispatches.some((s) => s.startsWith("correctness:")),
    ).toBe(true);
    const durableAfter = backend.readFamilyPanelLegEvidence("correctness");
    expect(durableAfter?.ledgerPhase).toBe("final");
  });

  it("P1: route/leg roster fingerprint mismatch must not reuse old-slug legal paper", async () => {
    const priorTransports = legalTransports(
      "STALE-ROSTER completeness paper from prior route",
    );
    const backend = new ColdSpineFamilyBackend({
      seedLedger: parkLedger(FAMILY_HEAD),
      seedEvidence: {
        completeness: {
          familyHeadAfter: FAMILY_HEAD,
          ledgerPhase: "final",
          routeFingerprint: "stale-route-fingerprint-not-current",
          courtGeneration: 0,
          panelLegTransports: priorTransports,
        },
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-roster-mismatch",
    });
    expect(
      backend.panelDispatches.filter((s) => s.startsWith("completeness:"))
        .length,
    ).toBeGreaterThan(0);
    const landing = backend.judgeLandings[0];
    // Fresh fan-out 卷面, not the stale seeded paper.
    expect(landing?.panelLegTransports).not.toEqual(priorTransports);
    expect(
      landing?.panelLegTransports?.some((t) =>
        (t.stdout ?? "").includes("fixture panel leg review prose"),
      ),
    ).toBe(true);
  });

  it("P1: builder refuse/no-op (HEAD unchanged) → outer gate reburns panels", async () => {
    // In-process: first completeness open fans panels → judge continue →
    // coder refuse (no HEAD move) → pure receive soft-accept advances generation
    // → outer gate must fan panels again (not reuse pre-builder durable 卷面).
    const backend = new ColdSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      completenessScript: "continue_then_converge",
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1119-refuse-outer-gate",
    });
    const completenessPanels = backend.panelDispatches.filter((s) =>
      s.startsWith("completeness:"),
    );
    // At least two completeness panel rounds (first open + outer gate).
    // Route has ≥1 leg; two rounds ⇒ length ≥ 2.
    expect(completenessPanels.length).toBeGreaterThanOrEqual(2);
    // Generation advanced past the first open (outer gate rewrote at gen ≥ 1).
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.courtGeneration).toBeGreaterThanOrEqual(1);
    expect(
      durable?.panelLegTransports &&
        durable.panelLegTransports.length > 0,
    ).toBe(true);
  });
});
