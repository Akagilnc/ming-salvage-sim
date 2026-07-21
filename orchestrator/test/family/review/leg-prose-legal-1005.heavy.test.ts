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
 *   3. {@link RealFamilyBackend.runCmrWorker} — production consumer
 *      extracts legTransports from sandbox-shaped results (top-level or
 *      typed-output soft cargo) and rebuilds presence without pre-mint.
 *   4. {@link runVerifyCmr} — court opens on production-derived cargo
 *      (no pre-minted successfulLegs stuffed into liveCmrJudge fixtures).
 *
 * Zero schema change on the judge↔runner envelope (ADR 0131).
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import type { RunResult } from "@ai-hero/sandcastle";

import {
  cmrOutcomeFromResult,
  RealFamilyBackend,
  type CmrAuth,
  type CmrWorkerOutcome,
} from "../../../src/family/realFamilyBackend.js";
import { cmrWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
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
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import { completeCmrPanelLegWorker } from "../../helpers/cmr-panel-leg-dispatch.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function realRepo1005(): { readonly repo: string; readonly head: string } {
  const repo = mkDir("1005-cmr-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], {
    cwd: repo,
  });
  execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
  const head = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repo,
    encoding: "utf8",
  }).trim();
  return { repo, head };
}

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

/**
 * Sandbox-shaped sc.run result: typed judge receipt WITHOUT successfulLegs
 * already-pass, plus host-observed legTransports (production consumer input).
 */
function sandboxResultWithProseLegTransports(input: {
  readonly place: "top-level" | "output-soft-cargo";
  readonly status?: "converged" | "continue";
  readonly successfulLegsCargo?: ReadonlyArray<string>;
  readonly fixPacketBody?: string;
}): RunResult & { readonly output: Record<string, unknown> } {
  const status = input.status ?? "converged";
  const baseOutput: Record<string, unknown> =
    status === "converged"
      ? {
          station: "judge",
          status: "converged",
          ...CMR_EVIDENCE,
          // Stale content-shape-empty list: host transport authority must win.
          successfulLegs: input.successfulLegsCargo ?? [],
        }
      : {
          station: "judge",
          status: "continue",
          findingDispositions: [
            { identityKey: "prose-leg:gap", action: "live" },
          ],
          fixPacketBody:
            input.fixPacketBody ??
            "judge distilled live finding from prose leg evidence",
          skippedLegs: [
            { slug: "agy", reason: "provider unavailable (transport dead)" },
          ],
          ...CMR_EVIDENCE,
          successfulLegs: input.successfulLegsCargo ?? [],
        };

  if (input.place === "output-soft-cargo") {
    return {
      branch: "fb",
      stdout: "",
      commits: [],
      iterations: [],
      output: {
        ...baseOutput,
        legTransports: [...PROSE_LEG_TRANSPORTS_485],
      },
    };
  }

  return {
    branch: "fb",
    stdout: "",
    commits: [],
    iterations: [],
    // Top-level host field (sandbox/result shape when producer lands transports).
    legTransports: [...PROSE_LEG_TRANSPORTS_485],
    output: baseOutput,
  } as RunResult & { readonly output: Record<string, unknown> };
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

/**
 * FamilyBackend whose cmr dispatch goes through production runCmrWorker with
 * a sandbox-shaped result that carries legTransports — never pre-mints
 * successfulLegs into a liveCmrJudge fixture.
 */
class ProductionSandboxProseLegBackend extends RealFamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  currentFamilyHead: string;
  private readonly sandboxPlace: "top-level" | "output-soft-cargo";
  private readonly continueBody?: string;

  constructor(opts: {
    readonly workingRepo: string;
    readonly ledgerDir: string;
    readonly familyHead: string;
    readonly sandboxPlace: "top-level" | "output-soft-cargo";
    readonly continueBody?: string;
  }) {
    // familyBase must exist as a git branch: runCmrWorker checks it out.
    // realRepo1005 creates branch "fb".
    super({
      workingRepo: opts.workingRepo,
      familyBase: "fb",
      ledgerDir: opts.ledgerDir,
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    this.currentFamilyHead = opts.familyHead;
    this.sandboxPlace = opts.sandboxPlace;
    this.continueBody = opts.continueBody;
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

  protected override mountCmrAuth(): CmrAuth {
    return { claudeToken: "tok" };
  }

  /**
   * Force the non-CLI path: runVerifyCmr → dispatchWorker → runCmrWorker.
   * RealFamilyBackend otherwise prefers monitored host CLI for productive seats.
   */
  override resolveCliMonitorDispatch(): undefined {
    return undefined;
  }

  protected override async runAgentSandbox(
    _options: Parameters<RealFamilyBackend["runAgentSandbox"]>[0],
  ): Promise<Awaited<ReturnType<RealFamilyBackend["runAgentSandbox"]>>> {
    // Converged green for happy court; continue when a fix packet is requested.
    if (this.continueBody !== undefined) {
      return sandboxResultWithProseLegTransports({
        place: this.sandboxPlace,
        status: "continue",
        fixPacketBody: this.continueBody,
        successfulLegsCargo: [],
      }) as Awaited<ReturnType<RealFamilyBackend["runAgentSandbox"]>>;
    }
    return sandboxResultWithProseLegTransports({
      place: this.sandboxPlace,
      status: "converged",
      successfulLegsCargo: [],
    }) as Awaited<ReturnType<RealFamilyBackend["runAgentSandbox"]>>;
  }

  override async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }

  override async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }

  override async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }

  override async runFamilyVerify(
    _req: FamilyVerifyRequest,
  ): Promise<FamilyVerifyResult> {
    return { ok: true };
  }

  override async mergeChildIntoFamilyBase(
    _child: MergeRequest,
  ): Promise<{ familyHead: string }> {
    return { familyHead: "unused" };
  }

  override async resolveMergeConflict(
    _req?: unknown,
  ): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  override async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    const panelLeg = completeCmrPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (spec.kind === "cmr") {
      // Production consumer: runCmrWorker extracts transports + overlays.
      return super.dispatchWorker(spec, ctx);
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "fb",
          status: "pr_opened",
          pr: `https://github.com/test/repo/pull/1090`,
          prHead: this.currentFamilyHead,
        },
      };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected kind ${spec.kind}` };
  }

  /** Expose production runCmrWorker for direct consumer assertions. */
  public invokeRunCmrWorker(
    spec: ReturnType<typeof cmrWorkerSpec>,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    return this.runCmrWorker(spec, ctx);
  }
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

  it("empty-after-filter legTransports falls back to cargo successfulLegs", () => {
    // Chatty garbage / empty array must not force successfulLegs=[] when the
    // intent of soft-parse absence is fall-back (same as transport-absent).
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        successfulLegs: ["grok", "opus"],
        // Empty array and all-invalid rows both filter to no legal rows.
        legTransports: [
          { notALeg: true },
          "chatty",
          { slug: "", exitCode: 0, stdout: "x" },
        ],
        evidencePaths: ["cmr/review-summary.json"],
      },
    });

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });

    const emptyArr = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        successfulLegs: ["opus"],
        legTransports: [],
        evidencePaths: ["cmr/review-summary.json"],
      },
    });
    expect(emptyArr).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus"],
    });
  });

  it("well-formed dead-only transports still rebuild successfulLegs to []", () => {
    // Fall-back is only for no well-formed rows — dead but well-formed
    // transports are real authority (all absent).
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        successfulLegs: ["should-not-survive"],
        legTransports: [
          { slug: "agy", exitCode: 1, stdout: "" },
          { slug: "grok", exitCode: 0, stdout: "   " },
        ],
        evidencePaths: ["cmr/review-summary.json"],
      },
    });

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: [],
    });
  });
});

describe("#1005 ADR 0141 runCmrWorker — production consumer extracts sandbox legTransports", () => {
  it("rebuilds successfulLegs from top-level sandbox legTransports (no pre-mint cargo)", async () => {
    const { repo, head } = realRepo1005();
    const be = new ProductionSandboxProseLegBackend({
      workingRepo: repo,
      ledgerDir: mkDir("1005-ledger-"),
      familyHead: head,
      sandboxPlace: "top-level",
    });

    const outcome = await be.invokeRunCmrWorker(
      cmrWorkerSpec("fresh", "completeness"),
      {
        familyBase: "fb",
        cmrPass: "completeness",
      },
    );

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });
  });

  it("rebuilds successfulLegs from typed-output soft cargo legTransports", async () => {
    // Production SO is passthrough for soft siblings — legTransports may land
    // on result.output (same object requireTypedTrafficSignal returns).
    const { repo, head } = realRepo1005();
    const be = new ProductionSandboxProseLegBackend({
      workingRepo: repo,
      ledgerDir: mkDir("1005-ledger-"),
      familyHead: head,
      sandboxPlace: "output-soft-cargo",
    });

    const outcome = await be.invokeRunCmrWorker(
      cmrWorkerSpec("fresh", "completeness"),
      {
        familyBase: "fb",
        cmrPass: "completeness",
      },
    );

    expect(outcome).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });
  });
});

describe("#1005 ADR 0141 family court — prose transports open the court", () => {
  it("live judge converged via production runCmrWorker sandbox path ships (no liveCmrJudge pre-mint)", async () => {
    // Court proof uses production consumer only: sandbox result carries
    // legTransports + empty successfulLegs cargo; runCmrWorker overlays presence.
    // No liveCmrJudgeGreen({ successfulLegs: [...] }) already-pass fixture.
    const { repo, head } = realRepo1005();
    const backend = new ProductionSandboxProseLegBackend({
      workingRepo: repo,
      ledgerDir: mkDir("1005-court-ledger-"),
      familyHead: head,
      sandboxPlace: "output-soft-cargo",
    });

    // Direct consumer nail: production-derived legs before court.
    const production = await backend.invokeRunCmrWorker(
      cmrWorkerSpec("fresh", "completeness"),
      { familyBase: "fb", cmrPass: "completeness" },
    );
    expect(production).toMatchObject({
      kind: "judge",
      status: "converged",
      successfulLegs: ["grok", "opus"],
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "fb",
      familyBackend: backend,
      familyHeadAfter: head,
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

  it("live judge continue via production sandbox legTransports still opens court", async () => {
    const { repo, head } = realRepo1005();
    const backend = new ProductionSandboxProseLegBackend({
      workingRepo: repo,
      ledgerDir: mkDir("1005-continue-ledger-"),
      familyHead: head,
      sandboxPlace: "top-level",
      continueBody: "judge distilled live finding from prose leg evidence",
    });

    const production = await backend.invokeRunCmrWorker(
      cmrWorkerSpec("fresh", "completeness"),
      { familyBase: "fb", cmrPass: "completeness" },
    );
    expect(production).toMatchObject({
      kind: "judge",
      status: "continue",
      successfulLegs: ["grok", "opus"],
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "fb",
      familyBackend: backend,
      familyHeadAfter: head,
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

// Keep a thin direct-overlay regression without court fixtures (no liveCmrJudge).
describe("#1005 ADR 0141 productionOutcome helper — transports only", () => {
  it("derives successfulLegs from prose transports without pre-mint cargo", () => {
    const production = productionOutcomeFromProseTransports({
      status: "converged",
      transports: [...PROSE_LEG_TRANSPORTS_485],
    });
    expect(production.successfulLegs).toEqual(["grok", "opus"]);
  });
});
