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
import { cmrReviewLegs } from "../../../src/modelRoutes.js";

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
  private durable = new Map<IntegratedCmrPass, FamilyPanelLegEvidence>();
  private readonly familyHead: string;
  private readonly forbidPanelDispatch: boolean;
  private readonly expectedJudgePaper?: ReadonlyArray<{
    readonly slug: string;
    readonly exitCode: number;
    readonly stdout: string;
  }>;
  private readonly requireJudgeSkips: boolean;

  constructor(opts: {
    readonly familyHead?: string;
    readonly seedLedger: FamilyLedgerEntry[];
    readonly seedEvidence?: Partial<
      Record<IntegratedCmrPass, FamilyPanelLegEvidence>
    >;
    readonly forbidPanelDispatch?: boolean;
    readonly expectedJudgePaper?: ReadonlyArray<{
      readonly slug: string;
      readonly exitCode: number;
      readonly stdout: string;
    }>;
    readonly requireJudgeSkips?: boolean;
  }) {
    this.familyHead = opts.familyHead ?? FAMILY_HEAD;
    this.ledger = [...opts.seedLedger];
    this.forbidPanelDispatch = opts.forbidPanelDispatch === true;
    this.expectedJudgePaper = opts.expectedJudgePaper;
    this.requireJudgeSkips = opts.requireJudgeSkips === true;
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
      if (this.forbidPanelDispatch) {
        throw new Error("valid durable court evidence was incorrectly reburned");
      }
      expect(ctx.resumeSessionId).toBeUndefined();
      expect(ctx.billingPool).toBeUndefined();
      return (
        completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
          kind: "failed",
          reason: "panel fixture missing",
        }
      );
    }
    if (spec.kind === "cmr") {
      if (
        this.expectedJudgePaper !== undefined &&
        JSON.stringify(landing?.panelLegTransports) !==
          JSON.stringify(this.expectedJudgePaper)
      ) {
        throw new Error("judge did not receive the original durable paper");
      }
      if (
        this.requireJudgeSkips &&
        (landing?.panelLegSkippedLegs?.length ?? 0) === 0
      ) {
        throw new Error("judge did not receive durable skip reasons");
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
    const result = await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-empty-resume",
    });
    expect(result.status).toBe("completed");
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
      seedLedger: parkLedger(FAMILY_HEAD),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
        correctness: fullIdentityEvidence({
          panelLegTransports: priorTransports,
        }),
      },
      forbidPanelDispatch: true,
      expectedJudgePaper: priorTransports,
    });
    const result = await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-no-reburn",
    });
    expect(result.status).toBe("completed");
    expect(
      backend.readFamilyPanelLegEvidence("completeness")?.panelLegTransports,
    ).toEqual(priorTransports);
  });

  it("skip-only durable evidence lands directly without dispatching another leg", async () => {
    const skipped = [
      { slug: "gpt-5.6-sol", reason: "provider unavailable" },
      { slug: "opus", reason: "provider unavailable" },
    ];
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          panelLegTransports: [],
          panelLegSkippedLegs: skipped,
        }),
        correctness: fullIdentityEvidence({
          panelLegTransports: [],
          panelLegSkippedLegs: skipped,
        }),
      },
      forbidPanelDispatch: true,
      requireJudgeSkips: true,
    });
    const result = await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-skip-only",
    });
    expect(result.status).toBe("completed");
    expect(
      backend.readFamilyPanelLegEvidence("completeness")?.panelLegSkippedLegs,
    ).toEqual(skipped);
  });
});

describe("#1118 RealFamilyBackend durable evidence fail-loud read", () => {
  it("corrupt durable JSON fails loudly with its path", async () => {
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
    writeFileSync(path, "{ definitely not JSON\n", "utf8");
    await expect(
      backend.readFamilyPanelLegEvidence("completeness"),
    ).rejects.toThrow(path);
  });
});
