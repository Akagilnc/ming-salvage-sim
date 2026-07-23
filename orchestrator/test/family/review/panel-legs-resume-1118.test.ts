/**
 * #1117 / #1118 — integrated court resume re-dispatches fresh panel legs.
 *
 * Seams (production paths only):
 *   - ensureFamilyCmrPanelEvidence / createPanelCourtSession
 *   - runVerifyCmr → runIntegratedCmrPass panel gate
 *   - cmrSandboxConfig fix-findings env + readonly bind mount
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  createPanelCourtSession,
  ensureFamilyCmrPanelEvidence,
  hasValidPanelLegTransports,
  mintPanelCourtOpeningId,
} from "../../../src/family/cmrPanelLegs.js";
import type {
  FamilyEscalation,
  FamilyLedgerEntry,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

const LEGAL_PANEL_STDOUT =
  "fixture panel leg review prose for ADR 0141 legal paper body.\n";

describe("#1118 ensureFamilyCmrPanelEvidence + panel court opening", () => {
  it("mints unique opening ids when runId is missing (still testable uniqueness)", () => {
    const a = mintPanelCourtOpeningId({ cmrPass: "correctness", nonce: 1 });
    const b = mintPanelCourtOpeningId({ cmrPass: "correctness", nonce: 2 });
    expect(a).not.toBe(b);
    expect(a).toContain("norun-1");
    expect(b).toContain("norun-2");
  });

  it("same opening reuses valid transports (no reburn); new opening reburns", async () => {
    const session = createPanelCourtSession();
    let dispatchCount = 0;
    const dispatch = async (spec: WorkerSpec): Promise<WorkerResult> => {
      dispatchCount += 1;
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findingsCount: 0,
          findings: [],
          rawStdout: `${LEGAL_PANEL_STDOUT} model=${spec.model}`,
        },
      };
    };
    const legs = [
      { family: "codex" as const, slug: "gpt-5.6-sol" },
      { family: "grok" as const, slug: "grok-4.5" },
    ];

    const first = session.resolve({
      cmrPass: "completeness",
      familyHeadAfter: "head-same",
      runId: "run-A",
    });
    const round1 = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "completeness",
      openingId: first.openingId,
      dispatch,
    });
    expect(round1.dispatched).toBe(true);
    expect(hasValidPanelLegTransports(round1.transports)).toBe(true);
    session.record({
      openingId: round1.openingId,
      cmrPass: "completeness",
      familyHeadAfter: "head-same",
      runId: "run-A",
      transports: round1.transports,
      skippedLegs: round1.skippedLegs,
    });
    const afterFirst = dispatchCount;

    // Same opening (same session, same pass/head/runId, no escalation) → reuse.
    const second = session.resolve({
      cmrPass: "completeness",
      familyHeadAfter: "head-same",
      runId: "run-A",
    });
    expect(second.openingId).toBe(first.openingId);
    expect(second.existing).toBeDefined();
    const round2 = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "completeness",
      openingId: second.openingId,
      ...(second.existing !== undefined ? { existing: second.existing } : {}),
      dispatch,
    });
    expect(round2.dispatched).toBe(false);
    expect(dispatchCount).toBe(afterFirst);

    // Same pass + same HEAD + escalationAnswer (rerun jury) → new opening reburn.
    const rerun = session.resolve({
      cmrPass: "completeness",
      familyHeadAfter: "head-same",
      runId: "run-A",
      escalationAnswerPresent: true,
    });
    expect(rerun.openingId).not.toBe(first.openingId);
    expect(rerun.existing).toBeUndefined();
    const round3 = await ensureFamilyCmrPanelEvidence({
      legs,
      cmrPass: "completeness",
      openingId: rerun.openingId,
      dispatch,
    });
    expect(round3.dispatched).toBe(true);
    expect(dispatchCount).toBeGreaterThan(afterFirst);
  });

  it("builder invalidate forces reburn even when head is unchanged", async () => {
    const session = createPanelCourtSession();
    let dispatchCount = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      dispatchCount += 1;
      return {
        kind: "completed",
        output: {
          kind: "reviewer",
          findingsCount: 0,
          findings: [],
          rawStdout: LEGAL_PANEL_STDOUT,
        },
      };
    };
    const legs = [{ family: "codex" as const, slug: "gpt-5.6-sol" }];
    const o1 = session.resolve({
      cmrPass: "correctness",
      familyHeadAfter: "head-1",
      runId: "run-B",
    });
    const r1 = await ensureFamilyCmrPanelEvidence({
      legs,
      openingId: o1.openingId,
      dispatch,
    });
    session.record({
      openingId: r1.openingId,
      cmrPass: "correctness",
      familyHeadAfter: "head-1",
      runId: "run-B",
      transports: r1.transports,
      skippedLegs: r1.skippedLegs,
    });
    const n = dispatchCount;
    session.invalidate(); // builder beat
    const o2 = session.resolve({
      cmrPass: "correctness",
      familyHeadAfter: "head-1",
      runId: "run-B",
    });
    expect(o2.openingId).not.toBe(o1.openingId);
    await ensureFamilyCmrPanelEvidence({
      legs,
      openingId: o2.openingId,
      dispatch,
    });
    expect(dispatchCount).toBeGreaterThan(n);
  });
});

describe("#1118 runVerifyCmr spine — empty resume redispatch + zero-success open court", () => {
  it("process re-entry with empty landing + escalationAnswer re-dispatches panels before judge", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../../src/reviewLoopOutcome.js"
    );

    const panelDispatchCounts: string[] = [];
    const judgeLandings: Array<WorkerLandingPayload | undefined> = [];
    const familyHead = "head-parked-no-transports";

    const backend = {
      ledger: [
        {
          status: "cmr_reviewed" as const,
          event: "cmr_reviewed" as const,
          phase: "final" as const,
          cmrPass: "completeness" as const,
          reason:
            "fresh completeness jury transports are missing — no panelLegTransports",
          familyHeadAfter: familyHead,
          blockingFindingIdentityKeys: [] as string[],
          sessionId: "judge-session-completeness-parked",
          judgeStatus: "escalate" as const,
          stopSummary: {
            reason: "decision_gate_park" as const,
            summary:
              "fresh completeness jury transports are missing — no panelLegTransports",
            repairHint:
              "answer the family judge decision gate, then resume the family court in place",
          },
        },
      ] as FamilyLedgerEntry[],
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
        return { familyHead };
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
        return familyHead;
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
          expect(ctx.resumeSessionId).toBeUndefined();
          expect(ctx.billingPool).toBeUndefined();
          panelDispatchCounts.push(`${ctx.cmrPass ?? "?"}:${spec.model}`);
          return (
            completeCmrPanelLegWorker(spec) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeLandings.push(landing);
          expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
          expect(ctx.panelLegTransports?.length).toBeGreaterThan(0);
          return {
            kind: "completed",
            sessionId:
              ctx.cmrPass === "completeness"
                ? "judge-session-completeness-parked"
                : "judge-session-correctness-1",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
              evidencePaths: ["cmr/review-summary.json"],
            },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase!,
              pr: "https://github.com/test/repo/pull/1117",
              prHead: familyHead,
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

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1118-process-resume",
      familyBackend: backend,
      familyHeadAfter: familyHead,
      runId: "run-cold-resume-1118",
      escalationAnswer: {
        event: "escalation_answered",
        answer: "rerun jury — re-dispatch fresh completeness panel legs",
        source: "human",
      },
    });

    expect(result.ok).toBe(true);
    expect(
      panelDispatchCounts.some((s) => s.startsWith("completeness:")),
    ).toBe(true);
    expect(judgeLandings.length).toBeGreaterThan(0);
    for (const landing of judgeLandings) {
      expect(landing?.panelLegTransports?.length).toBeGreaterThan(0);
    }
    expect(
      backend.escalations.some((e) =>
        /transports are missing|zero successful panel legs/i.test(
          `${e.reason} ${e.diagnosis}`,
        ),
      ),
    ).toBe(false);
  });

  it("all panel legs fail: opens pure court with skip reasons (no runner zero-success direct-stop)", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { buildExplicitLandingLiveHooks } = await import(
      "../../../src/family/landing.js"
    );
    const { isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );

    let judgeDispatched = 0;
    let sawSkipOnJudge = false;
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
        return { familyHead: "head-1" };
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
        return "head-1";
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
          return {
            kind: "failed",
            reason: `docker flake on ${spec.model}`,
          };
        }
        if (spec.kind === "cmr") {
          judgeDispatched += 1;
          const skips =
            landing?.panelLegSkippedLegs ?? ctx.panelLegSkippedLegs ?? [];
          if (skips.length > 0) sawSkipOnJudge = true;
          // Judge sees empty/fail paper and escalates (sole closer — no host veto).
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "escalate",
              reason: `family integrated cmr ${ctx.cmrPass ?? "?"}: zero successful panel legs`,
              diagnosis: skips.map((s) => `${s.slug}: ${s.reason}`).join("; "),
            },
          };
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
      familyBase: "family/1118-zero-success-open-court",
      familyBackend: backend,
      runId: "run-zero-success-1118",
    });

    expect(result.ok).toBe(false);
    expect(judgeDispatched).toBeGreaterThan(0);
    expect(sawSkipOnJudge).toBe(true);
    expect(
      backend.ledger.some((e) => e.status === "cmr_passed"),
    ).toBe(false);
    expect(backend.escalations.length).toBeGreaterThan(0);
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
    const { dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const here = dirname(fileURLToPath(import.meta.url));
    const soulsDir = join(here, "..", "..", "..", "image", "souls");
    const promptsDir = join(here, "..", "..", "..", "prompts");

    class ConfigBackend extends RealFamilyBackend {
      public config(
        fixFindings: { path: string; sandboxPath: string },
      ): {
        env: Record<string, string>;
        mounts: ReadonlyArray<{
          hostPath: string;
          sandboxPath: string;
          readonly?: boolean;
        }>;
      } {
        return this.cmrSandboxConfig(
          {
            codexAuthDir: "/tmp/cmr-codex-auth-1118",
          },
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
