/**
 * #1005 / ADR 0141 — leg prose is legal paper; typed contract is
 * judge↔runner only.
 *
 * Regression background: 2026-07-18 #485 final completeness parks where
 * container legs returned pure prose / unanchored candidates and the
 * family court never opened (leg-level content-shape admissibility
 * rejected the panel before the judge could emit a typed verdict).
 *
 * Seams under test (production path — not test-only helpers):
 *   1. {@link isLegalLegPaper} / {@link successfulLegsFromTransports} —
 *      transport-only panel presence (exit 0 + non-empty raw stdout).
 *   2. {@link cmrOutcomeFromResult} overlay — host path that builds
 *      successfulLegs from leg transports for family cmr cargo.
 *   3. {@link runVerifyCmr} — court opens on typed judge verdict whose
 *      successfulLegs were production-derived from prose transports
 *      (no pre-minted successfulLegs already-pass).
 *
 * Zero schema change on the judge↔runner envelope (ADR 0131).
 */

import { describe, expect, it } from "vitest";

import { cmrOutcomeFromResult } from "../../../src/family/realFamilyBackend.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import {
  isLegalLegPaper,
  successfulLegsFromTransports,
} from "../../../src/legPaper.js";
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
import {
  liveCmrJudgeContinue,
  liveCmrJudgeGreen,
} from "../../helpers/judge-fixtures.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

/** 485 autopsy shape: pure-prose / no-anchor legs that must still count present. */
const PURE_PROSE_STDOUT = [
  "## Completeness review",
  "I walked the delivery base against the AC set.",
  "No structural gap remains; module wiring covers the required surfaces.",
  "Note: this is free prose without candidate field tags.",
].join("\n");

const NO_ANCHOR_STDOUT = [
  "Progress: finished reading the diff.",
  "Overall impression: the family base looks complete enough to ship.",
  "I did not emit structured candidates with location anchors.",
].join("\n");

const PROGRESS_STDOUT =
  "Working… still scanning authority sources… almost done.";

/** Transports as the container would land them (exit + raw stdout only). */
const PROSE_LEG_TRANSPORTS_485 = [
  { slug: "grok", exitCode: 0, stdout: PURE_PROSE_STDOUT },
  { slug: "opus", exitCode: 0, stdout: NO_ANCHOR_STDOUT },
  { slug: "agy", exitCode: 1, stdout: "" },
] as const;

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

/**
 * Production path: typed judge envelope without successfulLegs already-pass,
 * plus host-observed leg transports → cmrOutcomeFromResult builds presence.
 */
function productionOutcomeFromProseTransports(input: {
  readonly status: "converged" | "continue";
  readonly transports: ReadonlyArray<{
    readonly slug: string;
    readonly exitCode: number;
    readonly stdout: string | null | undefined;
  }>;
  readonly fixPacketBody?: string;
}): Extract<
  ReturnType<typeof cmrOutcomeFromResult>,
  { readonly kind: "judge" }
> {
  const typedReceipt =
    input.status === "converged"
      ? {
          station: "judge" as const,
          status: "converged" as const,
          skippedLegs: [
            { slug: "agy", reason: "provider unavailable (transport dead)" },
          ],
          ...CMR_EVIDENCE,
          // Deliberately omit successfulLegs — host must build from transports.
        }
      : {
          station: "judge" as const,
          status: "continue" as const,
          findingDispositions: [
            {
              identityKey: "prose-leg:gap",
              action: "live" as const,
            },
          ],
          fixPacketBody:
            input.fixPacketBody ??
            "judge distilled live finding from prose leg evidence",
          // Soft cargo only — must not ride on strict traffic keys (reason is
          // escalate traffic; continue strict schema rejects unknown keys).
          skippedLegs: [
            { slug: "agy", reason: "provider unavailable (transport dead)" },
          ],
          ...CMR_EVIDENCE,
        };

  const outcome = cmrOutcomeFromResult({
    output: typedReceipt,
    legTransports: input.transports,
  });
  expect(outcome.kind).toBe("judge");
  if (outcome.kind !== "judge") {
    throw new Error("expected kind:judge from production overlay");
  }
  return outcome;
}

describe("#1005 ADR 0141 isLegalLegPaper — transport-only presence", () => {
  it("accepts pure prose stdout on exit 0 (485 grok-style leg)", () => {
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: PURE_PROSE_STDOUT }),
    ).toBe(true);
  });

  it("accepts unanchored / no-candidate free text on exit 0 (485 opus-style leg)", () => {
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: NO_ANCHOR_STDOUT }),
    ).toBe(true);
  });

  it("accepts progress-style narration on exit 0 (deleted 「进度散文＝无卷」)", () => {
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: PROGRESS_STDOUT }),
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

describe("#1005 ADR 0141 successfulLegsFromTransports — production panel builder", () => {
  it("builds successfulLegs from pure-prose / no-anchor exit0 transports", () => {
    expect(successfulLegsFromTransports([...PROSE_LEG_TRANSPORTS_485])).toEqual([
      "grok",
      "opus",
    ]);
  });

  it("includes progress-style narration legs and excludes dead transports", () => {
    expect(
      successfulLegsFromTransports([
        { slug: "grok", exitCode: 0, stdout: PROGRESS_STDOUT },
        { slug: "opus", exitCode: 0, stdout: "   " },
        { slug: "agy", exitCode: 2, stdout: "stderr only" },
      ]),
    ).toEqual(["grok"]);
  });
});

describe("#1005 ADR 0141 cmrOutcomeFromResult — host overlay builds successfulLegs", () => {
  it("overlays successfulLegs from prose legTransports when cargo omits them", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        // No successfulLegs — production must not require pre-mint.
        evidencePaths: ["cmr/review-summary.json"],
      },
      legTransports: [...PROSE_LEG_TRANSPORTS_485],
    });

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });
  });

  it("host legTransports override a content-shape-empty successfulLegs cargo", () => {
    // Skill/judge may still emit [] after a stale content-shape reject; host
    // presence authority is transport-only when legTransports are supplied.
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        successfulLegs: [],
        evidencePaths: ["cmr/review-summary.json"],
      },
      legTransports: [...PROSE_LEG_TRANSPORTS_485],
    });

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });
  });

  it("rebuilds successfulLegs from cargo legTransports via isLegalLegPaper", () => {
    // Soft cargo may land per-leg transports; host rebuilds presence.
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        legTransports: [...PROSE_LEG_TRANSPORTS_485],
        evidencePaths: ["cmr/review-summary.json"],
      },
    });

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });
  });
});

describe("#1005 ADR 0141 family court — prose transports open the court", () => {
  it("live judge converged with production-derived prose successfulLegs ships", async () => {
    // Production panel path: transports → cmrOutcomeFromResult → successfulLegs.
    // Court must open without a pre-minted successfulLegs already-pass fixture.
    const production = productionOutcomeFromProseTransports({
      status: "converged",
      transports: [...PROSE_LEG_TRANSPORTS_485],
    });
    expect(production.successfulLegs).toEqual(["grok", "opus"]);

    const backend = new ScriptedProseLegCourtBackend(
      liveCmrJudgeGreen({
        // Cargo comes only from production overlay — not hand-minted slugs.
        successfulLegs: production.successfulLegs,
        skippedLegs: production.skippedLegs,
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
    expect(
      backend.ledger.some(
        (entry) =>
          entry.status === "cmr_passed" &&
          (entry as { judgeStatus?: string }).judgeStatus === "converged",
      ),
    ).toBe(true);
  });

  it("live judge continue with production-derived prose-leg cargo still opens court", async () => {
    const liveFinding = {
      severity: "high" as const,
      category: "correctness",
      claim_quote: "prose-leg distilled a real gap the judge keeps live",
      location: "orchestrator/src/family/verifyCmr.ts:prose-leg",
      suggested_fix: "close the gap",
      action: "fix_now" as const,
    };

    const production = productionOutcomeFromProseTransports({
      status: "continue",
      transports: [...PROSE_LEG_TRANSPORTS_485],
      fixPacketBody: "judge distilled live finding from prose leg evidence",
    });
    expect(production.successfulLegs).toEqual(["grok", "opus"]);

    const backend = new ScriptedProseLegCourtBackend(
      liveCmrJudgeContinue([liveFinding], {
        successfulLegs: production.successfulLegs,
        skippedLegs: production.skippedLegs,
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
