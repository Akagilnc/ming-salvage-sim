/**
 * #1117 / #1118 — integrated court resume re-dispatches fresh panel legs.
 *
 * Load-bearing cases enter through runFamily (production spine). Durable cargo
 * owner = FamilyBackend.read/writeFamilyPanelLegEvidence with court identity
 * (HEAD + ledgerPhase + declared panel-leg roster only).
 *
 * Authority: #1118 AC; ADR 0130/0132/0141/0147.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { panelLegsRosterFingerprint } from "../../../src/family/cmrPanelLegs.js";
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
import {
  cmrReviewLegs,
  resolveActiveModelRoute,
  type ResolvedModelRoute,
} from "../../../src/modelRoutes.js";

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose for ADR 0141 legal paper body.\n## Findings\nnone";
const FAMILY_HEAD = "head-parked-1118";
const EPIC: FamilyEpic = {
  issue: 1117,
  children: [{ issue: 1118, blockedBy: [] }],
};

function defaultPanelLegsFingerprint(): string {
  return panelLegsRosterFingerprint(cmrReviewLegs());
}

function legalTransports(stdout: string = LEGAL_PANEL_STDOUT) {
  return [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout },
    { slug: "opus", exitCode: 0, stdout },
  ];
}

function fullIdentityEvidence(
  overrides: Partial<FamilyPanelLegEvidence> = {},
): FamilyPanelLegEvidence {
  return {
    familyHeadAfter: FAMILY_HEAD,
    ledgerPhase: "final",
    panelLegsFingerprint: defaultPanelLegsFingerprint(),
    panelLegTransports: legalTransports(),
    ...overrides,
  };
}

function routeWithCoderShipShift(base: ResolvedModelRoute): ResolvedModelRoute {
  // Shift only coder/ship slots — cmrReview roster stays identical so durable
  // panel evidence must still reuse (#1118 AC2: identity is panel-roster only).
  return {
    ...base,
    slots: {
      ...base.slots,
      coder: "sonnet",
      coderFix: "sonnet",
      ship: "gpt-5.6-terra",
    },
  };
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

/**
 * Family backend for #1118 spine: durable panel evidence + ledger park residue.
 * Mirrors production RealFamilyBackend read/writeFamilyPanelLegEvidence.
 */
class ResumeSpineFamilyBackend implements FamilyBackend {
  ledger: FamilyLedgerEntry[];
  escalations: FamilyEscalation[] = [];
  panelDispatches: string[] = [];
  judgeLandings: Array<WorkerLandingPayload | undefined> = [];
  private durable = new Map<IntegratedCmrPass, FamilyPanelLegEvidence>();
  private readonly familyHead: string;
  private readonly failAllPanelLegs: boolean;

  constructor(opts: {
    readonly familyHead?: string;
    readonly seedLedger: FamilyLedgerEntry[];
    readonly seedEvidence?: Partial<
      Record<IntegratedCmrPass, FamilyPanelLegEvidence>
    >;
    readonly failAllPanelLegs?: boolean;
  }) {
    this.familyHead = opts.familyHead ?? FAMILY_HEAD;
    this.ledger = [...opts.seedLedger];
    this.failAllPanelLegs = opts.failAllPanelLegs === true;
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
      expect(ctx.billingPool).toBeUndefined();
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
          pr: "https://github.com/test/repo/pull/1118",
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
      childIssue: 1118,
      status: "merged",
      childBranch: "feat/issue-1118",
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
      childIssue: 1118,
      status: "merged",
      childBranch: "feat/issue-1118",
    },
  ];
}

describe("#1118 runFamily resume panel evidence", () => {
  it("negative: empty durable + escalation answer → panel legs fan-out; judge gets transports", async () => {
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: parkLedger(FAMILY_HEAD),
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-empty-resume",
    });
    expect(
      backend.panelDispatches.some((s) => s.startsWith("completeness:")),
    ).toBe(true);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.panelLegTransports?.length).toBeGreaterThan(0);
    expect(durable?.familyHeadAfter).toBe(FAMILY_HEAD);
    expect(durable?.ledgerPhase).toBe("final");
    expect(durable?.panelLegsFingerprint).toBe(defaultPanelLegsFingerprint());
  });

  it("control: full identity match → zero panel reburn; judge gets original 卷面", async () => {
    const priorTransports = legalTransports(
      "PRIOR durable completeness panel paper\n## Findings\nnone",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
        correctness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-no-reburn",
    });
    expect(backend.panelDispatches).toEqual([]);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports).toEqual(priorTransports);
    }
  });

  it("AC2: coder/ship route shift with same panel roster → still reuses (no reburn)", async () => {
    const priorTransports = legalTransports(
      "ROSTER-STABLE paper under coder/ship shift\n## Findings\nnone",
    );
    const base = resolveActiveModelRoute();
    const shifted = routeWithCoderShipShift(base);
    // Sanity: panel roster identity is unchanged by the slot shift.
    expect(panelLegsRosterFingerprint(shifted.legCollections.cmrReview)).toBe(
      panelLegsRosterFingerprint(base.legCollections.cmrReview),
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
        correctness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-coder-ship-shift",
      admittedRoute: { route: shifted, dropped: [] },
    });
    expect(backend.panelDispatches).toEqual([]);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports).toEqual(priorTransports);
    }
  });

  it("AC2: declared panel roster change → must fresh reburn", async () => {
    const staleRosterPaper = legalTransports(
      "OLD-roster paper — declared legs fingerprint no longer matches",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          panelLegsFingerprint: "stale-panel-roster-fingerprint",
          panelLegTransports: staleRosterPaper,
        }),
        correctness: fullIdentityEvidence({
          panelLegsFingerprint: "stale-panel-roster-fingerprint",
          panelLegTransports: staleRosterPaper,
        }),
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-roster-mismatch",
    });
    expect(backend.panelDispatches.length).toBeGreaterThan(0);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports).not.toEqual(staleRosterPaper);
    }
  });

  it("P1: checkpoint-scoped durable must not free-skip final (same HEAD)", async () => {
    const checkpointPaper = legalTransports(
      "CHECKPOINT-only correctness paper — must not serve final",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        correctness: fullIdentityEvidence({
          ledgerPhase: "correctness_checkpoint",
          panelLegTransports: checkpointPaper,
        }),
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-checkpoint-vs-final",
    });
    expect(
      backend.panelDispatches.filter((s) => s.startsWith("correctness:")).length,
    ).toBeGreaterThan(0);
    const correctnessLanding = backend.judgeLandings.find((l) =>
      (l?.panelLegTransports?.length ?? 0) > 0,
    );
    expect(correctnessLanding?.panelLegTransports).not.toEqual(checkpointPaper);
  });

  it("stale durable head → reburn (never re-stamp old cargo as current head)", async () => {
    const staleTransports = legalTransports(
      "STALE head paper must not be reused\n## Findings\nnone",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          familyHeadAfter: "head-old-stale",
          panelLegTransports: staleTransports,
        }),
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-stale-head",
    });
    expect(
      backend.panelDispatches.filter((s) => s.startsWith("completeness:"))
        .length,
    ).toBeGreaterThan(0);
    const completenessLanding = backend.judgeLandings[0];
    expect(completenessLanding?.panelLegTransports).not.toEqual(staleTransports);
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.familyHeadAfter).toBe(FAMILY_HEAD);
  });

  it("negative: all legs fail → skip reasons land on pure court (zero silent empty)", async () => {
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      failAllPanelLegs: true,
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-zero-legs",
    });
    expect(backend.panelDispatches.length).toBeGreaterThan(0);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
    const withSkips = backend.judgeLandings.find(
      (l) => (l?.panelLegSkippedLegs?.length ?? 0) > 0,
    );
    expect(withSkips).toBeDefined();
    expect(
      withSkips?.panelLegSkippedLegs?.every(
        (leg) =>
          typeof leg.slug === "string" &&
          typeof leg.reason === "string" &&
          /docker flake/i.test(leg.reason),
      ),
    ).toBe(true);
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.panelLegSkippedLegs?.length).toBeGreaterThan(0);
    expect(durable?.ledgerPhase).toBe("final");
    expect(durable?.panelLegsFingerprint).toBe(defaultPanelLegsFingerprint());
  });

  it("malformed durable (no legal transports after shape gate) → runFamily fans out", async () => {
    // Production shape gate drops wrong-type transports; identity alone is not
    // enough for reuse — missing legal paper forces fan-out (external behavior).
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: {
          familyHeadAfter: FAMILY_HEAD,
          ledgerPhase: "final",
          panelLegsFingerprint: defaultPanelLegsFingerprint(),
          // no panelLegTransports — same as post-parse wrong-shape sidecar
        },
        correctness: {
          familyHeadAfter: FAMILY_HEAD,
          ledgerPhase: "final",
          panelLegsFingerprint: defaultPanelLegsFingerprint(),
        },
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-malformed-fanout",
    });
    expect(backend.panelDispatches.length).toBeGreaterThan(0);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
  });
});

describe("#1118 RealFamilyBackend durable evidence shape-safe parse", () => {
  it("wrong-shape sidecar via RealFamilyBackend → no reusable transports (no throw)", async () => {
    const { RealFamilyBackend, FAMILY_PANEL_LEG_EVIDENCE_PREFIX } =
      await import("../../../src/family/realFamilyBackend.js");
    const here = dirname(fileURLToPath(import.meta.url));
    const promptsDir = join(here, "..", "..", "..", "prompts");
    const soulsDir = join(here, "..", "..", "..", "image", "souls");
    const ledgerDir = mkdtempSync(join(tmpdir(), "cmr-1118-ledger-"));
    const workingRepo = mkdtempSync(join(tmpdir(), "cmr-1118-repo-"));
    const backend = new RealFamilyBackend({
      workingRepo,
      familyBase: "family/1118-parse",
      ledgerDir,
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "ming-orchestrator-coder:latest",
    });

    const path = join(
      ledgerDir,
      `${FAMILY_PANEL_LEG_EVIDENCE_PREFIX}-completeness.json`,
    );
    writeFileSync(
      path,
      JSON.stringify({
        familyHeadAfter: FAMILY_HEAD,
        ledgerPhase: "final",
        panelLegsFingerprint: "x",
        panelLegTransports: { slug: "not-an-array" },
      }) + "\n",
      "utf8",
    );
    const evidence = await backend.readFamilyPanelLegEvidence("completeness");
    // External entry: wrong-shape transports are not reusable arrays.
    expect(evidence?.panelLegTransports).toBeUndefined();
  });
});
