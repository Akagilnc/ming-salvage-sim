/**
 * #1117 / #1118 — integrated court resume re-dispatches fresh panel legs.
 *
 * Load-bearing cases enter through runFamily (production spine) or
 * cmrSandboxConfig (real backend mount path). Durable cargo owner =
 * FamilyBackend.read/writeFamilyPanelLegEvidence — not optional
 * VerifyCmrInput test seams.
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

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose for ADR 0141 legal paper body.\n## Findings\nnone";
const FAMILY_HEAD = "head-parked-1118";
const EPIC: FamilyEpic = {
  issue: 1117,
  children: [{ issue: 1118, blockedBy: [] }],
};

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
    // Durable cargo written by production path (not test-injected VerifyCmrInput).
    const durable = backend.readFamilyPanelLegEvidence("completeness");
    expect(durable?.panelLegTransports?.length).toBeGreaterThan(0);
    expect(durable?.familyHeadAfter).toBe(FAMILY_HEAD);
  });

  it("control: durable valid transports at same head → zero panel reburn; judge gets original 卷面", async () => {
    const priorTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: "PRIOR durable completeness panel paper\n## Findings\nnone",
      },
      {
        slug: "grok-4.5",
        exitCode: 0,
        stdout: "PRIOR durable completeness panel paper\n## Findings\nnone",
      },
    ];
    // Park without escalation_answered so resume does not force reburn —
    // control case is "landing already has valid transports".
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: [
        {
          childIssue: 1118,
          status: "merged",
          childBranch: "feat/issue-1118",
        },
      ],
      seedEvidence: {
        completeness: {
          familyHeadAfter: FAMILY_HEAD,
          panelLegTransports: priorTransports,
        },
        correctness: {
          familyHeadAfter: FAMILY_HEAD,
          panelLegTransports: priorTransports,
        },
      },
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-no-reburn",
    });
    // Both courts must reuse durable same-head transports (no reburn).
    expect(backend.panelDispatches).toEqual([]);
    expect(backend.judgeLandings.length).toBeGreaterThan(0);
    for (const landing of backend.judgeLandings) {
      expect(landing?.panelLegTransports).toEqual(priorTransports);
    }
  });

  it("stale durable head → reburn (never re-stamp old cargo as current head)", async () => {
    const staleTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: "STALE head paper must not be reused\n## Findings\nnone",
      },
    ];
    // No escalationAnswer — head provenance alone must reject stale cargo.
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: [
        {
          childIssue: 1118,
          status: "merged",
          childBranch: "feat/issue-1118",
        },
      ],
      seedEvidence: {
        completeness: {
          familyHeadAfter: "head-old-stale",
          panelLegTransports: staleTransports,
        },
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
    // Production rewrite carries the CURRENT head, not the stale one.
    expect(durable?.familyHeadAfter).toBe(FAMILY_HEAD);
  });

  it("negative: all legs fail → skip reasons land on pure court (zero silent empty)", async () => {
    // #1118: zero-success still opens pure judge with skip reasons (ADR 0132
    // JudgeVerdictStatus sole closer) — not a runner early-park before judge.
    const backend = new ResumeSpineFamilyBackend({
      seedLedger: [
        {
          childIssue: 1118,
          status: "merged",
          childBranch: "feat/issue-1118",
        },
      ],
      failAllPanelLegs: true,
    });
    await runFamily({
      epic: EPIC,
      familyBackend: backend,
      singleSliceBackend: new ChildSmokeBackend(),
      familyBase: "family/1118-zero-legs",
    });
    expect(backend.panelDispatches.length).toBeGreaterThan(0);
    // Pure court still opens; skip reasons visible on landing + durable.
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
  });
});

describe("#1118 cmrSandboxConfig fix-findings env + readonly bind mount", () => {
  it("sets ORCHESTRATOR_FIX_FINDINGS_PATH and mounts the file readonly", async () => {
    const { RealFamilyBackend } = await import(
      "../../../src/family/realFamilyBackend.js"
    );
    const { SANDBOX_FIX_FINDINGS_PATH_ENV } = await import(
      "../../../src/realBackend.js"
    );
    const { cmrWorkerSpec } = await import(
      "../../../src/family/dispatchFamilyWorker.js"
    );
    const here = dirname(fileURLToPath(import.meta.url));
    const soulsDir = join(here, "..", "..", "..", "image", "souls");
    const promptsDir = join(here, "..", "..", "..", "prompts");

    class ConfigBackend extends RealFamilyBackend {
      public config(fixFindings: {
        path: string;
        sandboxPath: string;
      }): {
        env: Record<string, string>;
        mounts: ReadonlyArray<{
          hostPath: string;
          sandboxPath: string;
          readonly?: boolean;
        }>;
      } {
        return this.cmrSandboxConfig(
          { codexAuthDir: "/tmp/cmr-codex-auth-1118" },
          cmrWorkerSpec(),
          undefined,
          undefined,
          fixFindings,
        );
      }
    }

    const workingRepo = mkdtempSync(join(tmpdir(), "cmr-1118-repo-"));
    const fixPath = join(workingRepo, ".orchestrator-fix-findings.json");
    writeFileSync(fixPath, "{}\n", "utf8");
    const backend = new ConfigBackend({
      workingRepo,
      familyBase: "family/1118-sandbox",
      ledgerDir: mkdtempSync(join(tmpdir(), "cmr-1118-ledger-")),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
    const cfg = backend.config({
      path: fixPath,
      sandboxPath: ".orchestrator-fix-findings.json",
    });
    expect(cfg.env[SANDBOX_FIX_FINDINGS_PATH_ENV]).toBe(
      ".orchestrator-fix-findings.json",
    );
    const mount = cfg.mounts.find(
      (m) => m.sandboxPath === ".orchestrator-fix-findings.json",
    );
    expect(mount).toBeDefined();
    expect(mount?.hostPath).toBe(fixPath);
    expect(mount?.readonly).toBe(true);
  });
});
