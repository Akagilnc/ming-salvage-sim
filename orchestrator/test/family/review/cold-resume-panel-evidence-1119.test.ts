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
  judgeEscalate,
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
  private readonly parkFirstCompleteness: boolean;
  constructor(
    readonly ledgerDir: string,
    private readonly crash: CrashMode = "none",
    seed?: FamilyPanelLegEvidence,
    opts?: {
      readonly forceFirstContinue?: boolean;
      readonly parkFirstCompleteness?: boolean;
    },
  ) {
    mkdirSync(ledgerDir, { recursive: true });
    this.forceFirstContinue = opts?.forceFirstContinue !== false;
    this.parkFirstCompleteness = opts?.parkFirstCompleteness === true;
    this.load();
    if (seed) this.writeFamilyPanelLegEvidence("completeness", seed);
  }
  private ledgerPath() {
    return join(this.ledgerDir, FAMILY_LEDGER_FILENAME);
  }
  private panelEvidencePath(pass: IntegratedCmrPass) {
    return join(
      this.ledgerDir,
      `${FAMILY_PANEL_LEG_EVIDENCE_PREFIX}-${pass}.json`,
    );
  }
  private load() {
    try {
      this.ledger = parseFamilyLedgerJsonl(
        readFileSync(this.ledgerPath(), "utf8"),
      );
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        this.ledger = [];
        return;
      }
      throw err;
    }
  }
  private save() {
    writeFileSync(
      this.ledgerPath(),
      this.ledger.map((e) => JSON.stringify(e)).join("\n") +
        (this.ledger.length ? "\n" : ""),
    );
  }
  readFamilyPanelLegEvidence(pass: IntegratedCmrPass) {
    try {
      return JSON.parse(
        readFileSync(this.panelEvidencePath(pass), "utf8"),
      ) as FamilyPanelLegEvidence;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw err;
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
    writeFileSync(
      this.panelEvidencePath(pass),
      `${JSON.stringify(e, null, 2)}\n`,
    );
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
          this.parkFirstCompleteness &&
          this.opens === 1 &&
          kind === "panels"
        ) {
          return completedJudge(
            judgeEscalate("owner decision needed", "park for cold resume"),
            "j-park",
          );
        }
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
  it("cold decision-park resume fans out when both durable cargo arrays are empty", async () => {
    const dir = tmp("1119-cold-park-");
    const processA = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
      parkFirstCompleteness: true,
    });
    const parked = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-park-a",
      familyBackend: processA,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(parked.ok).toBe(false);
    expect(
      (await processA.readFamilyLedger()).some(
        (entry) =>
          entry.cmrPass === "completeness" &&
          entry.judgeStatus === "escalate",
      ),
    ).toBe(true);

    const parkedEvidence =
      processA.readFamilyPanelLegEvidence("completeness");
    expect((parkedEvidence?.panelLegTransports?.length ?? 0) > 0).toBe(true);
    processA.writeFamilyPanelLegEvidence("completeness", {
      familyHeadAfter: HEAD,
      ledgerPhase: "final",
      routeFingerprint: ROUTE_FP,
      courtGeneration: courtGenerationFromDurableEvidence(parkedEvidence),
      panelLegTransports: [],
      panelLegSkippedLegs: [],
    });

    const processB = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-park-b",
      familyBackend: processB,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });

    expect(
      processB.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ).length,
    ).toBeGreaterThan(0);
    const resumedEvidence =
      processB.readFamilyPanelLegEvidence("completeness");
    expect(
      (resumedEvidence?.panelLegTransports?.length ?? 0) +
        (resumedEvidence?.panelLegSkippedLegs?.length ?? 0),
    ).toBeGreaterThan(0);
    expect(processB.judgeLandings[0]?.transports).toEqual(
      resumedEvidence?.panelLegTransports,
    );
  });

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
    const transportOnlyEvidence = {
      ...mid,
      panelLegTransports: [
        {
          slug: "gpt-5.6-sol",
          exitCode: 1,
          stdout: "opaque review prose carried for the judge",
        },
      ],
    };
    a.writeFamilyPanelLegEvidence("completeness", transportOnlyEvidence);
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
    expect(b.judgeLandings[0]?.transports).toEqual(
      transportOnlyEvidence.panelLegTransports,
    );
    expect(b.judgeLandings[0]?.skippedLegs).toBeUndefined();
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
