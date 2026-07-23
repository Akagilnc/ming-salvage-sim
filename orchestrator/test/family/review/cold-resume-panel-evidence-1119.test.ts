/**
 * #1119 — durable panel evidence + cold crash after cmr_fix_committed.
 *
 * 1) pure identity + pending-receive matrix (no runFamily per cell)
 * 2) process-A→B file ledgerDir cold crash (runVerifyCmr)
 * 3) exact-generation no-reburn control (runFamily)
 *
 * Authority: #1119/#1117/#1118; ADR 0141/0147.
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  admissibleDurablePanelLegTransports,
  courtGenerationFromDurableEvidence,
} from "../../../src/family/cmrPanelLegs.js";
import {
  FAMILY_LEDGER_FILENAME,
  FAMILY_PANEL_LEG_EVIDENCE_PREFIX,
} from "../../../src/family/realFamilyBackend.js";
import {
  pendingBuilderReceiveFromFamilyLedger,
  parseFamilyLedgerJsonl,
} from "../../../src/family/ledger.js";
import { runFamily } from "../../../src/family/runner.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
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
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";
import { mintFourReasonRefuseRecord } from "../../helpers/coder-refuse-fixtures.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

const HEAD = "head-1119";
const ROUTE_FP = modelRouteFingerprint(resolveActiveModelRoute({}));
const LEGAL =
  "fixture panel leg review prose (ADR 0141)\n## Findings\nnone";
const REFUSE_KEY = "1119:cold-refuse";
const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length) rmSync(cleanups.pop()!, { recursive: true, force: true });
});
const tmp = (p: string) => {
  const d = mkdtempSync(join(tmpdir(), p));
  cleanups.push(d);
  return d;
};

describe("#1119 panel evidence identity (pure)", () => {
  const transports = [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout: LEGAL },
  ];
  const base = {
    familyHeadAfter: HEAD,
    ledgerPhase: "final" as const,
    routeFingerprint: ROUTE_FP,
    courtGeneration: 0,
    panelLegTransports: transports,
  };
  const scope = {
    familyHeadAfter: HEAD,
    ledgerPhase: "final" as const,
    routeFingerprint: ROUTE_FP,
    courtGeneration: 0,
  };

  it.each([
    { name: "full match", evidence: base, scope, ok: true },
    {
      name: "checkpoint≠final",
      evidence: { ...base, ledgerPhase: "correctness_checkpoint" as const },
      scope,
      ok: false,
    },
    {
      name: "roster mismatch",
      evidence: { ...base, routeFingerprint: "stale" },
      scope,
      ok: false,
    },
    {
      name: "generation mismatch",
      evidence: base,
      scope: { ...scope, courtGeneration: 1 },
      ok: false,
    },
    {
      name: "HEAD mismatch",
      evidence: { ...base, familyHeadAfter: "other" },
      scope,
      ok: false,
    },
    {
      name: "missing identity fail-closed",
      evidence: { familyHeadAfter: HEAD, panelLegTransports: transports },
      scope,
      ok: false,
    },
  ])("$name", ({ evidence, scope: s, ok }) => {
    expect(admissibleDurablePanelLegTransports(evidence, s) !== undefined).toBe(
      ok,
    );
  });

  it("pending receive from trailing cmr_fix_committed carries refuse cargo", () => {
    const p = pendingBuilderReceiveFromFamilyLedger(
      [
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          phase: "final",
          cmrPass: "completeness",
          judgeStatus: "continue",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          phase: "final",
          cmrPass: "completeness",
          familyHeadAfter: HEAD,
          refusedFindingIdentityKeys: ["k1"],
          refuseRecords: [
            mintFourReasonRefuseRecord({
              identityKey: "k1",
              reason: "not_established",
              evidence: "e",
            }),
          ],
        },
      ],
      "completeness",
      "final",
    );
    expect(p).toMatchObject({
      pending: true,
      refusedFindingIdentityKeys: ["k1"],
      familyHeadAfter: HEAD,
    });
    expect(p.refuseRecords?.length).toBe(1);
  });

  it("cmr_passed after fix clears pending receive", () => {
    expect(
      pendingBuilderReceiveFromFamilyLedger(
        [
          {
            status: "cmr_fix_committed",
            event: "cmr_fix_committed",
            phase: "final",
            cmrPass: "correctness",
          },
          {
            status: "cmr_passed",
            event: "cmr_passed",
            phase: "final",
            cmrPass: "correctness",
          },
        ],
        "correctness",
        "final",
      ).pending,
    ).toBe(false);
  });
});

/** File-backed spine: production ledgerDir + panel-leg-evidence-*.json layout. */
class FileSpine implements FamilyBackend {
  ledger: FamilyLedgerEntry[] = [];
  panelDispatches: string[] = [];
  courtOpenKinds: Array<"pure_receive" | "with_panels"> = [];
  judgeLandings: Array<{ refuseKeys?: readonly string[] }> = [];
  familyHead: string;
  private opens = 0;
  private sawFix = false;
  private readonly crashAfterFix: boolean;
  private readonly coderMode: "refuse" | "commit";
  constructor(
    readonly ledgerDir: string,
    opts: {
      familyHead?: string;
      crashAfterFix?: boolean;
      coderMode?: "refuse" | "commit";
      seedEvidence?: Partial<Record<IntegratedCmrPass, FamilyPanelLegEvidence>>;
    } = {},
  ) {
    mkdirSync(ledgerDir, { recursive: true });
    this.familyHead = opts.familyHead ?? HEAD;
    this.crashAfterFix = opts.crashAfterFix === true;
    this.coderMode = opts.coderMode ?? "refuse";
    this.loadLedger();
    for (const [pass, ev] of Object.entries(opts.seedEvidence ?? {}) as Array<
      [IntegratedCmrPass, FamilyPanelLegEvidence]
    >) {
      this.writeFamilyPanelLegEvidence(pass, ev);
    }
  }
  private lp() {
    return join(this.ledgerDir, FAMILY_LEDGER_FILENAME);
  }
  private ep(pass: IntegratedCmrPass) {
    return join(
      this.ledgerDir,
      `${FAMILY_PANEL_LEG_EVIDENCE_PREFIX}-${pass}.json`,
    );
  }
  private loadLedger() {
    try {
      this.ledger = parseFamilyLedgerJsonl(readFileSync(this.lp(), "utf8"));
    } catch {
      this.ledger = [];
    }
  }
  private saveLedger() {
    writeFileSync(
      this.lp(),
      this.ledger.map((e) => JSON.stringify(e)).join("\n") +
        (this.ledger.length ? "\n" : ""),
    );
  }
  readFamilyPanelLegEvidence(pass: IntegratedCmrPass) {
    try {
      return JSON.parse(readFileSync(this.ep(pass), "utf8")) as FamilyPanelLegEvidence;
    } catch {
      return undefined;
    }
  }
  writeFamilyPanelLegEvidence(pass: IntegratedCmrPass, e: FamilyPanelLegEvidence) {
    writeFileSync(this.ep(pass), `${JSON.stringify(e, null, 2)}\n`);
  }
  resolveLandingLiveHooks(i: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: i.prUrl,
      headOid: i.convergedHeadOid,
      remoteBranchName: i.familyBase,
    });
  }
  async mergeChildIntoFamilyBase() {
    return { familyHead: this.familyHead };
  }
  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("unused");
  }
  async appendFamilyLedger(e: FamilyLedgerEntry) {
    this.ledger.push(e);
    this.saveLedger();
    if (
      (e.status === "cmr_fix_committed" || e.event === "cmr_fix_committed") &&
      e.cmrPass === "completeness"
    ) {
      this.sawFix = true;
    }
  }
  async readFamilyLedger() {
    this.loadLedger();
    return this.ledger;
  }
  async readFamilyHead() {
    return this.familyHead;
  }
  async runFamilyVerify() {
    return { ok: true };
  }
  async escalateFamily(_e: FamilyEscalation) {}
  async recordAborted() {}
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (isCmrPanelLegWorker(spec)) {
      this.panelDispatches.push(`${ctx.cmrPass}:${spec.model}`);
      return completeCmrPanelLegWorker(spec, LEGAL)!;
    }
    if (spec.kind === "cmr") {
      if (
        this.crashAfterFix &&
        this.sawFix &&
        ctx.cmrPass === "completeness"
      ) {
        throw new Error("PROCESS_A_CRASH after cmr_fix_committed");
      }
      const kind =
        (landing?.panelLegTransports?.length ?? 0) > 0
          ? ("with_panels" as const)
          : ("pure_receive" as const);
      this.courtOpenKinds.push(kind);
      this.judgeLandings.push({ refuseKeys: ctx.refusedFindingIdentityKeys });
      if (ctx.cmrPass === "completeness") {
        this.opens += 1;
        if (this.opens === 1 && kind === "with_panels") {
          return completedJudge(
            judgeContinue([sampleFinding("need fix", "a.ts:1")]),
            "j1",
          );
        }
        return completedJudge(judgeConverged(), "jn");
      }
      return completedJudge(judgeConverged(), "jc");
    }
    if (spec.kind === "coder") {
      if (this.coderMode === "commit") {
        this.familyHead = `${this.familyHead}-fixed`;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: "fx",
        };
      }
      return {
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 0,
          refusedFindingIdentityKeys: [REFUSE_KEY],
          refuseRecords: [
            mintFourReasonRefuseRecord({
              identityKey: REFUSE_KEY,
              reason: "not_established",
              evidence: "cold-crash refuse",
            }),
          ],
        },
        sessionId: "fx",
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
    return (
      skeletonReviewLoopWorkerResult(spec.kind) ?? {
        kind: "failed",
        reason: spec.kind,
      }
    );
  }
}

const preBuilder = (): FamilyPanelLegEvidence => ({
  familyHeadAfter: HEAD,
  ledgerPhase: "final",
  routeFingerprint: ROUTE_FP,
  courtGeneration: 0,
  panelLegTransports: [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout: "PRE-BUILDER stale" },
    { slug: "grok-4.5", exitCode: 0, stdout: "PRE-BUILDER stale" },
  ],
});

describe("#1119 process-A→B cold crash after cmr_fix_committed", () => {
  async function processA(
    dir: string,
    coderMode: "refuse" | "commit",
  ): Promise<void> {
    const backend = new FileSpine(dir, {
      crashAfterFix: true,
      coderMode,
      seedEvidence: { completeness: preBuilder() },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-a",
      familyBackend: backend,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(result.ok).toBe(false);
    const ledger = await backend.readFamilyLedger();
    const fix = [...ledger]
      .reverse()
      .find(
        (e) =>
          (e.status === "cmr_fix_committed" ||
            e.event === "cmr_fix_committed") &&
          e.cmrPass === "completeness",
      );
    expect(fix).toBeDefined();
    if (coderMode === "refuse") {
      expect(fix?.refusedFindingIdentityKeys).toEqual([REFUSE_KEY]);
      expect(fix?.refuseRecords?.length).toBe(1);
    }
    const ev = backend.readFamilyPanelLegEvidence("completeness");
    expect(courtGenerationFromDurableEvidence(ev)).toBeGreaterThanOrEqual(1);
    expect(ev?.panelLegTransports?.length ?? 0).toBe(0);
  }

  async function processB(dir: string, coderMode: "refuse" | "commit") {
    const backend = new FileSpine(dir, { coderMode });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-b",
      familyBackend: backend,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    return backend;
  }

  it("refuse/no-op same HEAD: pure receive + refuse cargo → fresh panels; no pre-builder reuse", async () => {
    const dir = tmp("1119-refuse-");
    await processA(dir, "refuse");
    const b = await processB(dir, "refuse");
    expect(b.courtOpenKinds[0]).toBe("pure_receive");
    expect(b.courtOpenKinds.some((k) => k === "with_panels")).toBe(true);
    expect(b.judgeLandings[0]?.refuseKeys).toEqual([REFUSE_KEY]);
    expect(
      b.readFamilyPanelLegEvidence("completeness")?.panelLegTransports?.some(
        (t) => (t.stdout ?? "").includes("PRE-BUILDER"),
      ) ?? false,
    ).toBe(false);
    expect(b.panelDispatches.some((d) => d.startsWith("completeness:"))).toBe(
      true,
    );
  });

  it("commit HEAD moved: pure receive first → fresh panels; no pre-builder reuse", async () => {
    const dir = tmp("1119-commit-");
    await processA(dir, "commit");
    const b = await processB(dir, "commit");
    expect(b.courtOpenKinds[0]).toBe("pure_receive");
    expect(b.courtOpenKinds.some((k) => k === "with_panels")).toBe(true);
    expect(
      b.readFamilyPanelLegEvidence("completeness")?.panelLegTransports?.some(
        (t) => (t.stdout ?? "").includes("PRE-BUILDER"),
      ) ?? false,
    ).toBe(false);
  });
});

class SmokeChild implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<ResumeState | undefined> {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("unused");
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
    throw new Error("unused");
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("unused");
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string) {}
}

describe("#1119 control: exact-generation cold no-reburn", () => {
  it("same generation + full identity → zero completeness reburn", async () => {
    const prior = [
      { slug: "gpt-5.6-sol", exitCode: 0, stdout: "PRIOR" },
      { slug: "grok-4.5", exitCode: 0, stdout: "PRIOR" },
    ];
    const park: FamilyLedgerEntry[] = [
      { childIssue: 1119, status: "merged", childBranch: "feat/issue-1119" },
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        reason: "park",
        familyHeadAfter: HEAD,
        sessionId: "p",
        judgeStatus: "escalate",
        stopSummary: {
          reason: "decision_gate_park",
          summary: "park",
          repairHint: "resume",
        },
      },
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        cmrPass: "completeness",
        escalationKind: "decision",
        reason: "park",
        familyHeadAfter: HEAD,
        stopSummary: {
          reason: "decision_gate_park",
          summary: "park",
          repairHint: "resume",
        },
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "go",
        source: "human",
      },
    ];
    const durable = new Map<IntegratedCmrPass, FamilyPanelLegEvidence>([
      [
        "completeness",
        {
          familyHeadAfter: HEAD,
          ledgerPhase: "final",
          routeFingerprint: ROUTE_FP,
          courtGeneration: 0,
          panelLegTransports: prior,
        },
      ],
    ]);
    const panelDispatches: string[] = [];
    let firstLanding: WorkerLandingPayload | undefined;
    const backend: FamilyBackend = {
      readFamilyPanelLegEvidence: (p) => durable.get(p),
      writeFamilyPanelLegEvidence: (p, e) => {
        durable.set(p, e);
      },
      resolveLandingLiveHooks: (i) =>
        buildExplicitLandingLiveHooks({
          prUrl: i.prUrl,
          headOid: i.convergedHeadOid,
          remoteBranchName: i.familyBase,
        }),
      mergeChildIntoFamilyBase: async () => ({ familyHead: HEAD }),
      resolveMergeConflict: async () => {
        throw new Error("unused");
      },
      appendFamilyLedger: async (e) => {
        park.push(e);
      },
      readFamilyLedger: async () => park,
      readFamilyHead: async () => HEAD,
      runFamilyVerify: async () => ({ ok: true }),
      escalateFamily: async () => {},
      recordAborted: async () => {},
      dispatchWorker: async (spec, ctx, landing) => {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatches.push(`${ctx.cmrPass}:${spec.model}`);
          return completeCmrPanelLegWorker(spec, LEGAL)!;
        }
        if (spec.kind === "cmr") {
          if (firstLanding === undefined) firstLanding = landing;
          return completedJudge(judgeConverged(), "j");
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1",
              prHead: HEAD,
              status: "pr_opened",
            },
          };
        }
        return (
          skeletonReviewLoopWorkerResult(spec.kind) ?? {
            kind: "failed",
            reason: spec.kind,
          }
        );
      },
    };
    const epic: FamilyEpic = {
      issue: 1117,
      children: [{ issue: 1119, blockedBy: [] }],
    };
    await runFamily({
      epic,
      familyBackend: backend,
      singleSliceBackend: new SmokeChild(),
      familyBase: "family/1119-no-reburn",
    });
    expect(panelDispatches.filter((s) => s.startsWith("completeness:"))).toEqual(
      [],
    );
    expect(firstLanding?.panelLegTransports).toEqual(prior);
  });
});
