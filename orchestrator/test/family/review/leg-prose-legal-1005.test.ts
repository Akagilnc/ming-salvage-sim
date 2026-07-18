/**
 * #1005 / ADR 0141 — leg prose is legal paper; typed contract is
 * judge↔runner only.
 *
 * Regression background: 2026-07-18 #485 final completeness parks where
 * container legs returned pure prose / unanchored candidates and the
 * family court never opened (leg-level content-shape admissibility
 * rejected the panel before the judge could emit a typed verdict).
 *
 * Seams under test:
 *   1. {@link isLegalLegPaper} — transport-only leg presence (exit 0 +
 *      non-empty raw stdout); content shape is never a gate.
 *   2. {@link runVerifyCmr} real family court entry — when the CMR worker
 *      emits a live typed judge verdict with prose-leg cargo present, the
 *      court opens and closes; runner does not park for "no usable legs".
 *
 * Zero schema change on the judge↔runner envelope (ADR 0131).
 */

import { describe, expect, it } from "vitest";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { isLegalLegPaper } from "../../../src/legPaper.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  JudgeResult,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import { liveCmrJudgeContinue, liveCmrJudgeGreen } from "../../helpers/judge-fixtures.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

/** 485 autopsy shape: legs that returned prose / no-anchor candidates. */
const PROSE_LEGS_485 = ["grok", "opus"] as const;

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

class ScriptedProseLegCourtBackend implements FamilyBackend {
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

  readonly ledger: FamilyLedgerEntry[] = [];
  currentFamilyHead = "head-485-prose";
  private cmrIndex = 0;

  constructor(
    private readonly cmrOutputs: ReadonlyArray<JudgeResult> | JudgeResult,
  ) {}

  async mergeChildIntoFamilyBase(
    _child: MergeRequest,
  ): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind === "cmr") {
      const outputs = Array.isArray(this.cmrOutputs)
        ? this.cmrOutputs
        : [this.cmrOutputs];
      const output = outputs[Math.min(this.cmrIndex, outputs.length - 1)]!;
      this.cmrIndex += 1;
      return { kind: "completed", output };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/1005",
          status: "pr_opened",
          pr: `pr://${ctx.familyBase ?? "family/1005"}`,
          prHead: this.currentFamilyHead,
        },
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected kind ${spec.kind}` };
  }
}

describe("#1005 ADR 0141 isLegalLegPaper — transport-only presence", () => {
  it("accepts pure prose stdout on exit 0 (485 grok-style leg)", () => {
    const prose = [
      "## Completeness review",
      "I walked the delivery base against the AC set.",
      "No structural gap remains; module wiring covers the required surfaces.",
      "Note: this is free prose without candidate field tags.",
    ].join("\n");
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: prose }),
    ).toBe(true);
  });

  it("accepts unanchored / no-candidate free text on exit 0 (485 opus-style leg)", () => {
    // No path:line anchors, no structured candidate blocks — still legal paper.
    const noAnchor = [
      "Progress: finished reading the diff.",
      "Overall impression: the family base looks complete enough to ship.",
      "I did not emit structured candidates with location anchors.",
    ].join("\n");
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: noAnchor }),
    ).toBe(true);
  });

  it("accepts progress-style narration on exit 0 (deleted 「进度散文＝无卷」)", () => {
    expect(
      isLegalLegPaper({
        exitCode: 0,
        stdout: "Working… still scanning authority sources… almost done.",
      }),
    ).toBe(true);
  });

  it("rejects empty / whitespace-only stdout even on exit 0", () => {
    expect(isLegalLegPaper({ exitCode: 0, stdout: "" })).toBe(false);
    expect(isLegalLegPaper({ exitCode: 0, stdout: "   \n\t  " })).toBe(false);
    expect(isLegalLegPaper({ exitCode: 0, stdout: null })).toBe(false);
    expect(isLegalLegPaper({ exitCode: 0, stdout: undefined })).toBe(false);
  });

  it("rejects non-zero exit even with non-empty stdout (transport dead)", () => {
    expect(
      isLegalLegPaper({
        exitCode: 1,
        stdout: "I wrote a full prose review but the CLI failed.",
      }),
    ).toBe(false);
  });
});

describe("#1005 ADR 0141 family court — prose legs still open the court", () => {
  it("live judge converged with pure-prose successfulLegs ships (court opens, typed verdict)", async () => {
    // 485 shape: two vendor legs present as transport success; judge distilled
    // a typed converged verdict. Runner must not park for content-shape.
    const backend = new ScriptedProseLegCourtBackend(
      liveCmrJudgeGreen({
        successfulLegs: [...PROSE_LEGS_485],
        skippedLegs: [
          { slug: "agy", reason: "provider unavailable (transport dead)" },
        ],
        ...CMR_EVIDENCE,
      }),
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1005-prose-legs",
      familyBackend: backend,
      familyHeadAfter: "head-485-prose",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(
      backend.ledger.filter((entry) => entry.status === "cmr_passed"),
    ).toHaveLength(2);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /no usable|jury floor|admissib|unanchored|progress.?prose|废票|无卷/i.test(
            typeof entry.reason === "string" ? entry.reason : "",
          ),
      ),
    ).toBe(false);
    // Typed judge path: court recorded cmr_passed with judgeStatus converged.
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "cmr_passed" &&
          (entry as { judgeStatus?: string }).judgeStatus === "converged",
      ),
    ).toBe(true);
  });

  it("live judge continue with prose-leg cargo still emits typed continue (court opens)", async () => {
    const liveFinding = {
      severity: "high" as const,
      category: "correctness",
      claim_quote: "prose-leg distilled a real gap the judge keeps live",
      location: "orchestrator/src/family/verifyCmr.ts:prose-leg",
      suggested_fix: "close the gap",
      action: "fix_now" as const,
    };
    const backend = new ScriptedProseLegCourtBackend(
      liveCmrJudgeContinue([liveFinding], {
        successfulLegs: [...PROSE_LEGS_485],
        reason: "judge distilled live finding from prose leg evidence",
        ...CMR_EVIDENCE,
      }),
    );

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1005-prose-continue",
      familyBackend: backend,
      familyHeadAfter: "head-485-prose",
    });

    // continue + live → coder-fix path; court opened (cmr_reviewed), not
    // content-shape park for "no usable legs".
    expect(result.ran).toBe(true);
    expect(
      backend.ledger.some((entry) => entry.status === "cmr_reviewed"),
    ).toBe(true);
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "aborted" &&
          /no usable|jury floor|admissib/i.test(
            typeof entry.reason === "string" ? entry.reason : "",
          ),
      ),
    ).toBe(false);
  });
});
