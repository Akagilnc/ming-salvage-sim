/**
 * #1119 — durable panel evidence crash windows + identity.
 *
 * Load-bearing A→B tracers (file ledgerDir, independent backend instances):
 *  1) cold fix row + invalidated evidence → fresh completeness panels first
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
  readdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  courtGenerationFromDurableEvidence,
} from "../../../src/family/cmrPanelLegs.js";
import {
  FAMILY_LEDGER_FILENAME,
} from "../../../src/family/realFamilyBackend.js";
import { FilePanelEvidenceStore } from "../../../src/family/panelEvidenceStore.js";
import {
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
    pass?: IntegratedCmrPass;
    kind: "pure" | "panels";
    refuseKeys?: readonly string[];
    transports?: WorkerLandingPayload["panelLegTransports"];
    skippedLegs?: WorkerLandingPayload["panelLegSkippedLegs"];
  }> = [];
  familyHead = HEAD;
  private opens = 0;
  private sawFix = false;
  private outerEvidenceWritten = false;
  private readonly panelEvidenceStore: FilePanelEvidenceStore;
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
    this.panelEvidenceStore = new FilePanelEvidenceStore(ledgerDir);
    this.forceFirstContinue = opts?.forceFirstContinue !== false;
    this.parkFirstCompleteness = opts?.parkFirstCompleteness === true;
    this.load();
    if (seed) this.writeFamilyPanelLegEvidence("completeness", seed);
  }
  private ledgerPath() {
    return join(this.ledgerDir, FAMILY_LEDGER_FILENAME);
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
    return this.panelEvidenceStore.read(pass);
  }
  panelEvidenceStorePath(pass: IntegratedCmrPass) {
    return this.panelEvidenceStore.path(pass);
  }
  writeFamilyPanelLegEvidence(
    pass: IntegratedCmrPass,
    e: FamilyPanelLegEvidence,
  ) {
    if (
      this.crash === "after_fix_before_invalidate" &&
      this.sawFix &&
      pass === "completeness" &&
      (e.panelLegTransports?.length ?? 0) === 0
    ) {
      throw new Error("INJECT: fix row durable before generation tombstone");
    }
    this.panelEvidenceStore.write(pass, e);
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
        pass: ctx.cmrPass,
        kind,
        refuseKeys: ctx.refusedFindingIdentityKeys,
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

describe("#1119 A→B crash windows (file ledgerDir)", () => {
  it("an interrupted evidence replacement preserves the last valid court paper", () => {
    const dir = tmp("1119-interrupted-evidence-write-");
    const priorEvidence: FamilyPanelLegEvidence = {
      familyHeadAfter: HEAD,
      ledgerPhase: "final",
      routeFingerprint: ROUTE_FP,
      courtGeneration: 0,
      panelLegTransports: [
        { slug: "gpt-5.6-sol", exitCode: 0, stdout: "prior opaque prose" },
      ],
    };
    const store = new FilePanelEvidenceStore(dir);
    store.write("completeness", priorEvidence);
    const interruptedStore = new FilePanelEvidenceStore(dir, {
      rename: () => {
        throw new Error("INJECT: interrupted before atomic replace");
      },
    });

    expect(() =>
      interruptedStore.write("completeness", {
        ...priorEvidence,
        panelLegTransports: [
          { slug: "gpt-5.6-sol", exitCode: 0, stdout: "new opaque prose" },
        ],
      }),
    ).toThrow("INJECT: interrupted before atomic replace");
    expect(store.read("completeness")).toEqual(priorEvidence);
    expect(
      readdirSync(dir).filter((name) => name.includes(".tmp")),
    ).toEqual([]);
  });

  it("cold resume fails loud when durable panel cargo has malformed entries", async () => {
    const dir = tmp("1119-cold-malformed-cargo-");
    const processA = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
      parkFirstCompleteness: true,
    });
    const parked = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-malformed-a",
      familyBackend: processA,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(parked.ok).toBe(false);

    writeFileSync(
      processA.panelEvidenceStorePath("completeness"),
      `${JSON.stringify({
        familyHeadAfter: HEAD,
        ledgerPhase: "final",
        routeFingerprint: ROUTE_FP,
        courtGeneration: 0,
        panelLegTransports: [{ slug: "gpt-5.6-sol", stdout: LEGAL }],
        panelLegSkippedLegs: [{ slug: "agy" }],
      })}\n`,
    );

    const processB = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/1119-malformed-b",
        familyBackend: processB,
        familyHeadAfter: HEAD,
        familyIssue: 1119,
      }),
    ).rejects.toThrow("invalid panel evidence cargo");
    expect(processB.judgeLandings).toEqual([]);
  });

  it("cold decision-park resume replaces non-empty same-generation evidence before the judge", async () => {
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
          entry.judgeStatus === "escalate" &&
          entry.freshPanelReviewRequired === true,
      ),
    ).toBe(true);

    const parkedEvidence =
      processA.readFamilyPanelLegEvidence("completeness");
    expect((parkedEvidence?.panelLegTransports?.length ?? 0) > 0).toBe(true);
    const oldTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: "opaque same-generation evidence from the parked court",
      },
    ];
    processA.writeFamilyPanelLegEvidence("completeness", {
      ...parkedEvidence,
      panelLegTransports: oldTransports,
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
    expect(processB.judgeLandings[0]?.transports).not.toEqual(oldTransports);
  });

  it("cold cmr_fix_committed resumes its resident judge before the fresh outer gate", async () => {
    const dir = tmp("1119-w1-");
    const preFixEvidence: FamilyPanelLegEvidence = {
      familyHeadAfter: HEAD,
      ledgerPhase: "final",
      routeFingerprint: ROUTE_FP,
      courtGeneration: 0,
      panelLegTransports: [
        { slug: "gpt-5.6-sol", exitCode: 0, stdout: "opaque pre-fix cargo" },
      ],
    };
    const processBeforeCrash = new FileLedgerBackend(
      dir,
      "after_fix_before_invalidate",
      preFixEvidence,
    );
    await expect(
      runVerifyCmr({
        phase: "final",
        familyBase: "family/1119-w1-a",
        familyBackend: processBeforeCrash,
        familyHeadAfter: HEAD,
        familyIssue: 1119,
      }),
    ).rejects.toThrow("generation tombstone");

    const processAfterRestart = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w1-b",
      familyBackend: processAfterRestart,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(
      processAfterRestart.judgeLandings
        .map((landing) => landing.kind)
        .slice(0, 2),
    ).toEqual(["pure", "panels"]);
    expect(
      processAfterRestart.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ).length,
    ).toBeGreaterThan(0);
    expect(processAfterRestart.judgeLandings[0]?.refuseKeys).toEqual([
      REFUSE_KEY,
    ]);
    expect(processAfterRestart.judgeLandings[0]?.transports).toEqual([]);
    expect(processAfterRestart.judgeLandings[1]?.transports).toEqual(
      processAfterRestart.readFamilyPanelLegEvidence("completeness")
        ?.panelLegTransports,
    );
    expect(processAfterRestart.judgeLandings[1]?.transports).not.toEqual(
      preFixEvidence.panelLegTransports,
    );
  });

  it("window2: outer evidence OK / judge dies → B same-generation zero panel reburn", async () => {
    const dir = tmp("1119-w2-");
    const processBeforeCrash = new FileLedgerBackend(
      dir,
      "after_outer_evidence_before_judge",
    );
    // Outer judge throw is process-root collapsed to a stage failure.
    const firstRunResult = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w2-a",
      familyBackend: processBeforeCrash,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    expect(firstRunResult.ok).toBe(false);
    const postFixEvidence =
      processBeforeCrash.readFamilyPanelLegEvidence("completeness");
    expect((postFixEvidence?.panelLegTransports?.length ?? 0) > 0).toBe(true);
    const transportOnlyEvidence = {
      ...postFixEvidence,
      panelLegTransports: [
        {
          slug: "gpt-5.6-sol",
          exitCode: 1,
          stdout: "opaque review prose carried for the judge",
        },
      ],
    };
    processBeforeCrash.writeFamilyPanelLegEvidence(
      "completeness",
      transportOnlyEvidence,
    );

    const processAfterRestart = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-w2-b",
      familyBackend: processAfterRestart,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });
    // Completeness outer gate must not reburn — reuse durable same generation.
    expect(
      processAfterRestart.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ).length,
    ).toBe(0);
    expect(processAfterRestart.judgeLandings[0]?.kind).toBe("panels");
    expect(processAfterRestart.judgeLandings[0]?.transports).toEqual(
      transportOnlyEvidence.panelLegTransports,
    );
    expect(
      processAfterRestart.judgeLandings[0]?.skippedLegs,
    ).toBeUndefined();
  });

  it("cold restart keeps a current-HEAD completeness pass while correctness remains pending", async () => {
    const correctnessFixHead = "head-1119-h1";
    const currentHead = "head-1119-h2";
    const dir = tmp("1119-correctness-pending-");
    const processBeforeCrash = new FileLedgerBackend(dir, "none", undefined, {
      forceFirstContinue: false,
    });
    await processBeforeCrash.appendFamilyLedger({
      status: "cmr_reviewed",
      event: "cmr_reviewed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: correctnessFixHead,
    });
    await processBeforeCrash.appendFamilyLedger({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadBefore: correctnessFixHead,
      familyHeadAfter: correctnessFixHead,
      expectedCourtGeneration: 1,
    });
    await processBeforeCrash.appendFamilyLedger({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadBefore: correctnessFixHead,
      familyHeadAfter: currentHead,
      expectedCourtGeneration: 1,
    });
    await processBeforeCrash.appendFamilyLedger({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "completeness",
      familyHeadAfter: currentHead,
      routeFingerprint: ROUTE_FP,
    });

    const processAfterRestart = new FileLedgerBackend(
      dir,
      "none",
      undefined,
      { forceFirstContinue: false },
    );
    processAfterRestart.familyHead = currentHead;
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-correctness-pending",
      familyBackend: processAfterRestart,
      familyHeadAfter: currentHead,
      familyIssue: 1119,
    });

    expect(
      processAfterRestart.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ),
    ).toHaveLength(0);
    expect(
      processAfterRestart.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("correctness:"),
      ).length,
    ).toBeGreaterThan(0);
    expect(processAfterRestart.judgeLandings.slice(0, 2)).toMatchObject([
      {
        pass: "correctness",
        kind: "pure",
      },
      {
        pass: "correctness",
        kind: "panels",
      },
    ]);
    expect(processAfterRestart.judgeLandings[1]).toMatchObject({
      pass: "correctness",
      kind: "panels",
    });
    const correctnessEvidence =
      processAfterRestart.readFamilyPanelLegEvidence("correctness");
    expect(correctnessEvidence?.familyHeadAfter).toBe(currentHead);
    expect(processAfterRestart.judgeLandings[1]?.transports).toEqual(
      correctnessEvidence?.panelLegTransports,
    );

    const missingPassDir = tmp("1119-correctness-pending-no-pass-");
    const processWithoutPostTriggerPass = new FileLedgerBackend(
      missingPassDir,
      "none",
      undefined,
      { forceFirstContinue: false },
    );
    processWithoutPostTriggerPass.familyHead = currentHead;
    await processWithoutPostTriggerPass.appendFamilyLedger({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadBefore: correctnessFixHead,
      familyHeadAfter: correctnessFixHead,
      expectedCourtGeneration: 1,
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/1119-correctness-pending-no-pass",
      familyBackend: processWithoutPostTriggerPass,
      familyHeadAfter: currentHead,
      familyIssue: 1119,
    });
    expect(
      processWithoutPostTriggerPass.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ).length,
    ).toBeGreaterThan(0);
  });

  it("matching skip-only evidence reaches the judge unchanged without reburn", async () => {
    const dir = tmp("1119-skips-");
    const skippedLegs = [
      { slug: "gpt-5.6-sol", reason: "provider quota exhausted" },
    ];
    const processAfterRestart = new FileLedgerBackend(
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
      familyBackend: processAfterRestart,
      familyHeadAfter: HEAD,
      familyIssue: 1119,
    });

    expect(
      processAfterRestart.panelDispatches.filter((dispatch) =>
        dispatch.startsWith("completeness:"),
      ).length,
    ).toBe(0);
    expect(processAfterRestart.judgeLandings[0]?.skippedLegs).toEqual(
      skippedLegs,
    );
  });
});
