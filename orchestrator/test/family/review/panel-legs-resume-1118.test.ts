/**
 * #1117 / #1118 — integrated court resume re-dispatches fresh panel legs.
 *
 * All load-bearing cases go through runVerifyCmr (or cmrSandboxConfig) — not
 * orphan helper branches.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { createPanelCourtSession } from "../../../src/family/cmrPanelLegs.js";
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

async function baseBackend(familyHead: string) {
  const { buildExplicitLandingLiveHooks } = await import(
    "../../../src/family/landing.js"
  );
  return {
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
    async recordAborted() {},
    async escalateFamily(esc: FamilyEscalation) {
      this.escalations.push(esc);
    },
  };
}

describe("#1118 runVerifyCmr — panel resume / reuse / reburn", () => {
  it("empty landing resume re-dispatches panels before pure judge", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../../src/reviewLoopOutcome.js"
    );

    const panelModels: string[] = [];
    const judgeLandings: Array<WorkerLandingPayload | undefined> = [];
    const familyHead = "head-empty-resume";
    const backend = {
      ...(await baseBackend(familyHead)),
      ledger: [
        {
          status: "cmr_reviewed" as const,
          event: "cmr_reviewed" as const,
          phase: "final" as const,
          cmrPass: "completeness" as const,
          reason: "fresh completeness jury transports are missing",
          familyHeadAfter: familyHead,
          blockingFindingIdentityKeys: [] as string[],
          sessionId: "judge-sess-parked",
          judgeStatus: "escalate" as const,
          stopSummary: {
            reason: "decision_gate_park" as const,
            summary: "fresh completeness jury transports are missing",
            repairHint: "rerun jury",
          },
        },
      ] as FamilyLedgerEntry[],
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          expect(ctx.resumeSessionId).toBeUndefined();
          expect(ctx.billingPool).toBeUndefined();
          panelModels.push(spec.model ?? "?");
          return (
            completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          judgeLandings.push(landing);
          expect((landing?.panelLegTransports?.length ?? 0) > 0).toBe(true);
          return {
            kind: "completed",
            sessionId: "judge-sess-1",
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
              pr: "https://github.com/test/repo/pull/1118",
              prHead: familyHead,
              status: "pr_opened",
            },
          };
        }
        return (
          skeletonReviewLoopWorkerResult(spec.kind) ?? {
            kind: "failed",
            reason: `unexpected ${spec.kind}`,
          }
        );
      },
    };

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1118-empty-resume",
      familyBackend: backend,
      familyHeadAfter: familyHead,
      runId: "run-empty-resume",
      escalationAnswer: {
        event: "escalation_answered",
        answer: "rerun jury",
        source: "human",
      },
    });
    expect(result.ok).toBe(true);
    expect(panelModels.length).toBeGreaterThan(0);
    expect(judgeLandings.length).toBeGreaterThan(0);
  });

  it("stamped landing with valid transports reuses — no panel reburn through runVerifyCmr", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );

    let panelDispatchCount = 0;
    const familyHead = "head-reuse";
    // correctness_checkpoint = single court so reuse is not confounded by
    // completeness→correctness pass mismatch reburn.
    const openingId = "run-reuse:correctness:seeded-opening-id";
    const stampedTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: LEGAL_PANEL_STDOUT,
      },
      {
        slug: "grok-4.5",
        exitCode: 0,
        stdout: LEGAL_PANEL_STDOUT,
      },
    ];
    const backend = {
      ...(await baseBackend(familyHead)),
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatchCount += 1;
          return {
            kind: "failed",
            reason: "must not reburn when stamped landing is valid",
          };
        }
        if (spec.kind === "cmr") {
          expect((landing?.panelLegTransports?.length ?? 0) > 0).toBe(true);
          expect(landing?.panelCourtOpeningId).toBe(openingId);
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
              evidencePaths: ["cmr/review-summary.json"],
            },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
    };

    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/1118-reuse-landing",
      familyBackend: backend,
      familyHeadAfter: familyHead,
      runId: "run-reuse",
      panelCourtSession: createPanelCourtSession(),
      stampedPanelLanding: {
        panelCourtOpeningId: openingId,
        panelLegTransports: stampedTransports,
      },
    });
    expect(result.ok).toBe(true);
    expect(panelDispatchCount).toBe(0);
  });

  it("same pass+head with escalationAnswer still reburns panels (process re-entry)", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );

    let panelDispatchCount = 0;
    const familyHead = "head-same";
    const openingId = "run-reburn:correctness:old-opening";
    const stampedTransports = [
      {
        slug: "gpt-5.6-sol",
        exitCode: 0,
        stdout: LEGAL_PANEL_STDOUT,
      },
    ];
    const backend = {
      ...(await baseBackend(familyHead)),
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          panelDispatchCount += 1;
          return (
            completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          expect(landing?.panelCourtOpeningId).not.toBe(openingId);
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "converged",
              successfulLegs: ["gpt-5.6-sol", "grok-4.5"],
              evidencePaths: ["cmr/review-summary.json"],
            },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      },
    };

    // Cold session + old stamped landing + escalationAnswer → reburn.
    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/1118-same-head-reburn",
      familyBackend: backend,
      familyHeadAfter: familyHead,
      runId: "run-reburn",
      panelCourtSession: createPanelCourtSession(),
      stampedPanelLanding: {
        panelCourtOpeningId: openingId,
        panelLegTransports: stampedTransports,
      },
      escalationAnswer: {
        event: "escalation_answered",
        answer: "rerun jury — fresh panel required",
        source: "human",
      },
    });
    expect(result.ok).toBe(true);
    expect(panelDispatchCount).toBeGreaterThan(0);
  });

  it("process re-entry mints non-colliding opening ids (missing runId safe)", async () => {
    const { runVerifyCmr } = await import("../../../src/family/verifyCmr.js");
    const { completeCmrPanelLegWorker, isCmrPanelLegWorker } = await import(
      "../../helpers/cmr-panel-leg-dispatch.js"
    );
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../../src/reviewLoopOutcome.js"
    );

    const openingIds: string[] = [];
    const familyHead = "head-collision";
    const makeBackend = async () => ({
      ...(await baseBackend(familyHead)),
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (isCmrPanelLegWorker(spec)) {
          return (
            completeCmrPanelLegWorker(spec, LEGAL_PANEL_STDOUT) ?? {
              kind: "failed",
              reason: "panel fixture missing",
            }
          );
        }
        if (spec.kind === "cmr") {
          if (typeof landing?.panelCourtOpeningId === "string") {
            openingIds.push(landing.panelCourtOpeningId);
          }
          return {
            kind: "completed",
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
              pr: "https://github.com/test/repo/pull/1118",
              prHead: familyHead,
              status: "pr_opened",
            },
          };
        }
        return (
          skeletonReviewLoopWorkerResult(spec.kind) ?? {
            kind: "failed",
            reason: `unexpected ${spec.kind}`,
          }
        );
      },
    });

    // Two cold process re-entries with NO runId — opening ids must not collide.
    await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/1118-opening-a",
      familyBackend: await makeBackend(),
      familyHeadAfter: familyHead,
      // runId intentionally omitted
    });
    await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/1118-opening-b",
      familyBackend: await makeBackend(),
      familyHeadAfter: familyHead,
    });
    expect(openingIds.length).toBeGreaterThanOrEqual(2);
    expect(new Set(openingIds).size).toBe(openingIds.length);
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
