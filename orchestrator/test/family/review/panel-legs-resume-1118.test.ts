/**
 * #1117 / #1118 — integrated court resume re-dispatches fresh panel legs.
 *
 * Load-bearing cases enter through runFamily (production spine). Durable cargo
 * owner = FamilyBackend.read/writeFamilyPanelLegEvidence with full court
 * identity (phase + route fingerprint + generation + HEAD).
 *
 * Authority: #1118 AC; ADR 0130/0132/0141/0147.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { parseFamilyPanelLegEvidence } from "../../../src/family/cmrPanelLegs.js";
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
  modelRouteFingerprint,
  resolveActiveModelRoute,
} from "../../../src/modelRoutes.js";

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose for ADR 0141 legal paper body.\n## Findings\nnone";
const FAMILY_HEAD = "head-parked-1118";
const EPIC: FamilyEpic = {
  issue: 1117,
  children: [{ issue: 1118, blockedBy: [] }],
};

function defaultRouteFingerprint(): string {
  return modelRouteFingerprint(resolveActiveModelRoute());
}

function legalTransports(stdout: string = LEGAL_PANEL_STDOUT) {
  return [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout },
    { slug: "grok-4.5", exitCode: 0, stdout },
  ];
}

function fullIdentityEvidence(
  overrides: Partial<FamilyPanelLegEvidence> = {},
): FamilyPanelLegEvidence {
  return {
    familyHeadAfter: FAMILY_HEAD,
    ledgerPhase: "final",
    routeFingerprint: defaultRouteFingerprint(),
    courtGeneration: 0,
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
    expect(durable?.routeFingerprint).toBe(defaultRouteFingerprint());
  });

  it("control: full court identity match → zero panel reburn; judge gets original 卷面", async () => {
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

  it("P1: checkpoint-scoped durable must not free-skip final (same HEAD)", async () => {
    const checkpointPaper = legalTransports(
      "CHECKPOINT-only correctness paper — must not serve final",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        // Completeness has no durable → will fan-out (ok).
        // Correctness seeded as checkpoint-only at same HEAD → final must reburn.
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
      l?.panelLegTransports?.some((t) => t.slug === "gpt-5.6-sol"),
    );
    // Must not hand the pure court the checkpoint-only paper.
    expect(correctnessLanding?.panelLegTransports).not.toEqual(checkpointPaper);
  });

  it("P1: same HEAD but route/legs fingerprint mismatch → fresh reburn", async () => {
    const staleRosterPaper = legalTransports(
      "OLD-roster paper — slug set no longer matches route",
    );
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: mergedOnlyLedger(),
      seedEvidence: {
        completeness: fullIdentityEvidence({
          routeFingerprint: "stale-route-fingerprint-not-current",
          panelLegTransports: staleRosterPaper,
        }),
        correctness: fullIdentityEvidence({
          routeFingerprint: "stale-route-fingerprint-not-current",
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
    // #1118: zero-success still opens pure judge with skip reasons (ADR 0132).
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
    expect(durable?.routeFingerprint).toBe(defaultRouteFingerprint());
  });
});

describe("#1118 RealFamilyBackend durable evidence shape-safe parse", () => {
  it("malformed / wrong-shape sidecar → undefined (fan-out), never throw on .map", async () => {
    const { RealFamilyBackend, FAMILY_PANEL_LEG_EVIDENCE_PREFIX } =
      await import("../../../src/family/realFamilyBackend.js");
    const { fileURLToPath } = await import("node:url");
    const { dirname } = await import("node:path");
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

    // Wrong-shape: panelLegTransports is an object, not an array.
    const path = join(
      ledgerDir,
      `${FAMILY_PANEL_LEG_EVIDENCE_PREFIX}-completeness.json`,
    );
    writeFileSync(
      path,
      JSON.stringify({
        familyHeadAfter: FAMILY_HEAD,
        ledgerPhase: "final",
        routeFingerprint: "x",
        courtGeneration: 0,
        panelLegTransports: { slug: "not-an-array" },
      }) + "\n",
      "utf8",
    );
    const evidence = await backend.readFamilyPanelLegEvidence("completeness");
    // Shape-safe: returns parsed identity without inventing a cast array.
    expect(evidence?.panelLegTransports).toBeUndefined();
    // Pure parser rejects non-object garbage.
    expect(parseFamilyPanelLegEvidence(null)).toBeUndefined();
    expect(parseFamilyPanelLegEvidence("not-json-object")).toBeUndefined();
    expect(parseFamilyPanelLegEvidence([])).toBeUndefined();
    // Wrong-type transports array elements are dropped; no throw.
    const partial = parseFamilyPanelLegEvidence({
      familyHeadAfter: FAMILY_HEAD,
      panelLegTransports: [
        { slug: "ok", exitCode: 0, stdout: "paper" },
        { slug: 1, exitCode: "x" },
      ],
    });
    expect(partial?.panelLegTransports).toEqual([
      { slug: "ok", exitCode: 0, stdout: "paper" },
    ]);
  });
});
