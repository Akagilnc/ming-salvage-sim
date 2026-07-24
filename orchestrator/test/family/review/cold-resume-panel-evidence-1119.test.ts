/**
 * #1119 — durable panel evidence crash windows + identity.
 *
 * Load-bearing A→B tracers (file ledgerDir, independent backend instances):
 *  1) fix ledger append OK → evidence invalidate fails → pure receive zero old 卷面
 *  2) outer evidence written → judge dies → same-generation zero reburn
 *
 * Identity/pending helpers: compact table-driven (no full spine per cell).
 * Authority: #1119/#1117/#1118; ADR 0141/0147.
 */
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  mkdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  admissibleDurablePanelLegEvidence,
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
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import {
  modelRouteFingerprint,
  resolveActiveModelRoute,
} from "../../../src/modelRoutes.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyPanelLegEvidence,
  IntegratedCmrPass,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
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
const LEGAL = "fixture panel prose\n## Findings\nnone";
const REFUSE_KEY = "1119:cold-refuse";
const PRE_BUILDER = "PRE-BUILDER stale paper";
const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length) {
    rmSync(cleanups.pop()!, { recursive: true, force: true });
  }
});
const tmp = (p: string) => {
  const d = mkdtempSync(join(tmpdir(), p));
  cleanups.push(d);
  return d;
};

// ── pure helpers ──────────────────────────────────────────────────────

describe("#1119 identity + pending helpers", () => {
  const transports = [{ slug: "gpt-5.6-sol", exitCode: 0, stdout: LEGAL }];
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
    { name: "matching transports", evidence: base, scope, ok: true },
    {
      name: "matching runtime skips",
      evidence: {
        ...base,
        panelLegTransports: undefined,
        panelLegSkippedLegs: [{ slug: "grok-4.5", reason: "quota exhausted" }],
      },
      scope,
      ok: true,
    },
    {
      name: "matching identity but no landed cargo",
      evidence: { ...base, panelLegTransports: undefined },
      scope,
      ok: false,
    },
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
  ])("$name", ({ evidence, scope: s, ok }) => {
    expect(admissibleDurablePanelLegEvidence(evidence, s) !== undefined).toBe(
      ok,
    );
  });

  it("pending: trailing cmr_fix_committed → pending + refuse cargo", () => {
    const p = pendingBuilderReceiveFromFamilyLedger(
      [
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
    expect(p.pending).toBe(true);
    expect(p.refusedFindingIdentityKeys).toEqual(["k1"]);
  });

  it("pending: soft-accept worker_dispatched with cmrPass+phase → not pending", () => {
    expect(
      pendingBuilderReceiveFromFamilyLedger(
        [
          {
            status: "cmr_fix_committed",
            event: "cmr_fix_committed",
            phase: "final",
            cmrPass: "completeness",
          },
          {
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep: "cmr:completeness",
            phase: "final",
            cmrPass: "completeness",
          },
        ],
        "completeness",
        "final",
      ).pending,
    ).toBe(false);
  });

  it("pending: advisory worker_dispatched without cmrPass does not clear", () => {
    expect(
      pendingBuilderReceiveFromFamilyLedger(
        [
          {
            status: "cmr_fix_committed",
            event: "cmr_fix_committed",
            phase: "final",
            cmrPass: "completeness",
          },
          {
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep: "cmr:completeness",
            reason: "git telemetry only",
          },
        ],
        "completeness",
        "final",
      ).pending,
    ).toBe(true);
  });
});

// ── file ledgerDir spine (production path layout) ─────────────────────

type CrashMode =
  | "none"
  | "after_fix_before_invalidate"
  | "after_outer_evidence_before_judge";

class FileLedgerBackend implements FamilyBackend {
  ledger: FamilyLedgerEntry[] = [];
  panelDispatches: string[] = [];
  judgeLandings: Array<{
    kind: "pure" | "panels";
    refuseKeys?: readonly string[];
    hasPreBuilder?: boolean;
    transports?: WorkerLandingPayload["panelLegTransports"];
    skippedLegs?: WorkerLandingPayload["panelLegSkippedLegs"];
  }> = [];
  familyHead = HEAD;
  private opens = 0;
  private sawFix = false;
  private outerEvidenceWritten = false;
  /** When false, every court open converges (process-B cold resume). */
  private readonly forceFirstContinue: boolean;
  constructor(
    readonly ledgerDir: string,
    private readonly crash: CrashMode = "none",
    seed?: FamilyPanelLegEvidence,
    opts?: { readonly forceFirstContinue?: boolean },
  ) {
    mkdirSync(ledgerDir, { recursive: true });
    this.forceFirstContinue = opts?.forceFirstContinue !== false;
    this.load();
    if (seed) this.writeFamilyPanelLegEvidence("completeness", seed);
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
  private load() {
    try {
      this.ledger = parseFamilyLedgerJsonl(readFileSync(this.lp(), "utf8"));
    } catch {
      this.ledger = [];
    }
  }
  private save() {
    writeFileSync(
      this.lp(),
      this.ledger.map((e) => JSON.stringify(e)).join("\n") +
        (this.ledger.length ? "\n" : ""),
    );
  }
  readFamilyPanelLegEvidence(pass: IntegratedCmrPass) {
    try {
      return JSON.parse(
        readFileSync(this.ep(pass), "utf8"),
      ) as FamilyPanelLegEvidence;
    } catch {
      return undefined;
    }
  }
  writeFamilyPanelLegEvidence(
    pass: IntegratedCmrPass,
    e: FamilyPanelLegEvidence,
  ) {
    // Precise fault: after fix row lands, first evidence write is invalidate.
    if (
      this.crash === "after_fix_before_invalidate" &&
      this.sawFix &&
      pass === "completeness" &&
      (e.panelLegTransports?.length ?? 0) === 0
    ) {
      throw new Error("INJECT: after fix ledger, before evidence invalidate");
    }
    writeFileSync(this.ep(pass), `${JSON.stringify(e, null, 2)}\n`);
    // Outer-gate paper is only written after the builder beat landed.
    if (
      this.sawFix &&
      pass === "completeness" &&
      (e.panelLegTransports?.length ?? 0) > 0
    ) {
      this.outerEvidenceWritten = true;
    }
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
    this.save();
    if (
      (e.status === "cmr_fix_committed" || e.event === "cmr_fix_committed") &&
      e.cmrPass === "completeness"
    ) {
      this.sawFix = true;
    }
  }
  async readFamilyLedger() {
    this.load();
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
        this.crash === "after_outer_evidence_before_judge" &&
        this.outerEvidenceWritten &&
        ctx.cmrPass === "completeness"
      ) {
        throw new Error("INJECT: after outer evidence, before judge complete");
      }
      const n = landing?.panelLegTransports?.length ?? 0;
      const kind = n > 0 ? ("panels" as const) : ("pure" as const);
      this.judgeLandings.push({
        kind,
        refuseKeys: ctx.refusedFindingIdentityKeys,
        hasPreBuilder: landing?.panelLegTransports?.some((t) =>
          (t.stdout ?? "").includes("PRE-BUILDER"),
        ),
        transports: landing?.panelLegTransports,
        skippedLegs: landing?.panelLegSkippedLegs,
      });
      if (ctx.cmrPass === "completeness") {
        this.opens += 1;
        if (
          this.forceFirstContinue &&
          this.opens === 1 &&
          kind === "panels"
        ) {
          return completedJudge(
            judgeContinue([sampleFinding("fix me", "a.ts:1")]),
            "j1",
          );
        }
        return completedJudge(judgeConverged(), "jn");
      }
      return completedJudge(judgeConverged(), "jc");
    }
    if (spec.kind === "coder") {
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
              evidence: "refuse",
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

const preBuilderSeed = (): FamilyPanelLegEvidence => ({
  familyHeadAfter: HEAD,
  ledgerPhase: "final",
  routeFingerprint: ROUTE_FP,
  courtGeneration: 0,
  panelLegTransports: [
    { slug: "gpt-5.6-sol", exitCode: 0, stdout: PRE_BUILDER },
    { slug: "grok-4.5", exitCode: 0, stdout: PRE_BUILDER },
  ],
});

describe("#1119 A→B crash windows (file ledgerDir)", () => {
  it("window1: fix append OK / evidence invalidate dies → B pure receive has zero pre-builder 卷面", async () => {
    const dir = tmp("1119-w1-");
    const a = new FileLedgerBackend(
      dir,
      "after_fix_before_invalidate",
      preBuilderSeed(),
    );
    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/1119-w1-a",
        familyBackend: a,
        familyHeadAfter: HEAD,
        familyIssue: 1119,
      }),
    ).rejects.toThrow(/INJECT: after fix ledger/);
    // Fix row durable; evidence may still hold pre-builder paper (invalidate died).
    const ledger = await a.readFamilyLedger();
    expect(
      ledger.some(
        (e) =>
          (e.status === "cmr_fix_committed" ||
            e.event === "cmr_fix_committed") &&
          e.cmrPass === "completeness",
      ),
    ).toBe(true);
    const stale = a.readFamilyPanelLegEvidence("completeness");
    expect(
      stale?.panelLegTransports?.some((t) =>
        (t.stdout ?? "").includes("PRE-BUILDER"),
      ),
    ).toBe(true);

    // Process B: only files — pure receive must not surface pre-builder paper.
    const b = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w1-b",
      familyBackend: b,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(b.judgeLandings[0]?.kind).toBe("pure");
    expect(b.judgeLandings[0]?.hasPreBuilder).toBeFalsy();
    expect(b.judgeLandings[0]?.refuseKeys).toEqual([REFUSE_KEY]);
    // Later outer gate may fan panels; none may carry PRE-BUILDER.
    expect(
      b.judgeLandings.some((j) => j.hasPreBuilder === true),
    ).toBe(false);
  });

  it("window2: outer evidence OK / judge dies → B same-generation zero panel reburn", async () => {
    const dir = tmp("1119-w2-");
    const a = new FileLedgerBackend(
      dir,
      "after_outer_evidence_before_judge",
      preBuilderSeed(),
    );
    // Outer judge throw is process-root collapsed to a stage failure.
    const r = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w2-a",
      familyBackend: a,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(r.ok).toBe(false);
    const mid = a.readFamilyPanelLegEvidence("completeness");
    expect((mid?.panelLegTransports?.length ?? 0) > 0).toBe(true);
    expect(
      mid?.panelLegTransports?.some((t) =>
        (t.stdout ?? "").includes("PRE-BUILDER"),
      ),
    ).toBe(false);
    const gen = courtGenerationFromDurableEvidence(mid);
    // Soft-accept completion marker must be durable.
    const ledger = await a.readFamilyLedger();
    expect(
      pendingBuilderReceiveFromFamilyLedger(ledger, "completeness", "final")
        .pending,
    ).toBe(false);

    const b = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w2-b",
      familyBackend: b,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    // Completeness outer gate must not reburn — reuse durable same generation.
    expect(
      b.panelDispatches.filter((d) => d.startsWith("completeness:")).length,
    ).toBe(0);
    const after = b.readFamilyPanelLegEvidence("completeness");
    expect(courtGenerationFromDurableEvidence(after)).toBe(gen);
    // First completeness open on B is panel-backed reuse (not pure re-receive).
    expect(b.judgeLandings[0]?.kind).toBe("panels");
    expect(b.judgeLandings[0]?.hasPreBuilder).toBeFalsy();
    expect(b.judgeLandings[0]?.transports).toEqual(mid?.panelLegTransports);
  });

  it("matching skip-only evidence reaches the judge unchanged without reburn", async () => {
    const dir = tmp("1119-skips-");
    const skippedLegs = [
      { slug: "gpt-5.6-sol", reason: "provider quota exhausted" },
    ];
    const b = new FileLedgerBackend(
      dir,
      "none",
      {
        familyHeadAfter: HEAD,
        ledgerPhase: "final",
        routeFingerprint: ROUTE_FP,
        courtGeneration: 0,
        panelLegSkippedLegs: skippedLegs,
      },
      {
        forceFirstContinue: false,
      },
    );

    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-skips",
      familyBackend: b,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });

    expect(
      b.panelDispatches.filter((d) => d.startsWith("completeness:")).length,
    ).toBe(0);
    expect(b.judgeLandings[0]?.skippedLegs).toEqual(skippedLegs);
  });
});
