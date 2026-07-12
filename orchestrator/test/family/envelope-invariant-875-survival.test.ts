/**
 * #875 [873·S1] envelope survival guards T1–T3 (Opus ballot / ADR 0129).
 *
 * Pins the write-point invariant so r5–r11 thrash courts cannot re-enter:
 *   T1 — count has no independent setter; successful parse always derives
 *        findingsCount / openCount from findings?.length ?? 0
 *   T2 — count-vs-array mismatch is malformed at write/parse (rewrite feedback),
 *        never a happy-path verifyCmr court
 *   T3 — verifyCmr has no residual executable shape-fork / 补数 / invent-findings
 *        paths based on independent count-vs-array
 *
 * Authority: orchestrator/docs/875-envelope-invariant-ballot.md
 */

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  cmrOutcomeFromResult,
  parseCmrOutcome,
} from "../../src/family/realFamilyBackend.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";
import type {
  CmrResult,
  DispatchContext,
  Finding,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const VERIFY_CMR_SRC = join(here, "../../src/family/verifyCmr.ts");
const REAL_BACKEND_SRC = join(here, "../../src/family/realFamilyBackend.ts");

const LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;
const EVIDENCE = {
  claimedFixedFindingIdentityKeys: [] as string[],
  priorFindingDispositions: [] as never[],
  evidencePaths: ["cmr/review-summary.json"],
};

const ONE_BLOCKER: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "one structured blocker",
  location: "orchestrator/src/family/verifyCmr.ts:1",
  suggested_fix: "fix the blocker",
  action: "fix_now",
};

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

function writeSidecar(payload: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "875-envelope-surv-"));
  const path = join(dir, "outcome.json");
  writeFileSync(path, `${JSON.stringify(payload)}\n`, "utf8");
  return path;
}

function assertDerivedCount(
  outcome: ReturnType<typeof parseCmrOutcome> | ReturnType<typeof cmrOutcomeFromResult>,
): void {
  expect(outcome.kind).toBe("verdict");
  if (outcome.kind !== "verdict") return;
  const expected = outcome.findings?.length ?? 0;
  expect(outcome.findingsCount).toBe(expected);
}

// ───────────────────────────── T1 ─────────────────────────────

describe("#875 T1 — count has no independent setter (type/schema layer)", () => {
  it("successful <cmr> parse always derives findingsCount === findings?.length ?? 0 (empty)", () => {
    const outcome = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: [...LEGS],
        ...EVIDENCE,
      })}</cmr>`,
    );
    assertDerivedCount(outcome);
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 0 });
  });

  it("successful parse with structured findings derives findingsCount from array length", () => {
    const outcome = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: false,
        reason: "one open blocker",
        successfulLegs: [...LEGS],
        ...EVIDENCE,
        findings: [ONE_BLOCKER],
      })}</cmr>`,
    );
    assertDerivedCount(outcome);
    expect(outcome).toMatchObject({
      kind: "verdict",
      findingsCount: 1,
      findings: [expect.objectContaining({ claim_quote: ONE_BLOCKER.claim_quote })],
    });
  });

  it("wire findingsCount field is not an independent input (strict schema rejects it)", () => {
    // Count is not a constructible wire field — only derived after successful parse.
    const outcome = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: false,
        reason: "lying count field on wire",
        successfulLegs: [...LEGS],
        ...EVIDENCE,
        findings: [ONE_BLOCKER],
        findingsCount: 99,
      })}</cmr>`,
    );
    expect(outcome.kind).toBe("malformed");
  });

  it("sidecar live path: successful verdict never carries count≠length", () => {
    const path = writeSidecar({
      converged: false,
      reason: "two open blockers",
      successfulLegs: [...LEGS],
      ...EVIDENCE,
      findings: [ONE_BLOCKER, { ...ONE_BLOCKER, claim_quote: "second" }],
    });
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 2\nCMR_STEP_COMPLETE\n",
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    assertDerivedCount(outcome);
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 2 });
  });

  it("classify/parse overwrites any ambient count: derived count always equals array length", () => {
    // Multi-finding and empty are both derived, never free-standing.
    for (const findings of [[], [ONE_BLOCKER], [ONE_BLOCKER, ONE_BLOCKER]] as const) {
      const outcome = parseCmrOutcome(
        `<cmr>${JSON.stringify({
          converged: false,
          reason: `n=${findings.length}`,
          successfulLegs: [...LEGS],
          ...EVIDENCE,
          ...(findings.length > 0 ? { findings: [...findings] } : {}),
        })}</cmr>`,
      );
      assertDerivedCount(outcome);
    }
  });
});

// ───────────────────────────── T2 ─────────────────────────────

describe("#875 T2 — malformed at write point (pos/neg pair)", () => {
  it("POSITIVE: well-formed structured findings + matching sentinel → write/parse accepts", () => {
    const path = writeSidecar({
      converged: false,
      reason: "well-formed one blocker",
      successfulLegs: [...LEGS],
      ...EVIDENCE,
      findings: [ONE_BLOCKER],
    });
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 1\nCMR_STEP_COMPLETE\n",
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome.kind).toBe("verdict");
    assertDerivedCount(outcome);
    if (outcome.kind === "verdict") {
      expect(outcome.findings).toHaveLength(1);
      expect(outcome.findingsCount).toBe(1);
    }
  });

  it("NEGATIVE: findings=N sentinel vs empty/absent array → malformed at write/parse", () => {
    const path = writeSidecar({
      converged: true,
      successfulLegs: [...LEGS],
      ...EVIDENCE,
      // no findings array
    });
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 3\nCMR_STEP_COMPLETE\n",
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome).toMatchObject({
      kind: "malformed",
      reason: expect.stringMatching(
        /does not match structured findings length|write-point|count is derived/i,
      ),
    });
    // Feedback for rewrite — not a live routing verdict.
    expect(outcome.kind).not.toBe("verdict");
  });

  it("NEGATIVE: count alone (findings=N with empty array) → write-point malformed", () => {
    const path = writeSidecar({
      converged: false,
      reason: "count alone",
      successfulLegs: [...LEGS],
      ...EVIDENCE,
      findings: [],
    });
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 2\nCMR_STEP_COMPLETE\n",
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome.kind).toBe("malformed");
    if (outcome.kind === "malformed") {
      expect(outcome.reason).toMatch(/does not match structured findings length/i);
      // priorVerdict may be retained for rewrite context — still not live routing.
      expect(outcome.priorVerdict?.kind).toBe("verdict");
      if (outcome.priorVerdict?.kind === "verdict") {
        expect(outcome.priorVerdict.findingsCount).toBe(0);
      }
    }
  });

  it("NEGATIVE: sentinel shorter than structured array → write-point malformed", () => {
    const path = writeSidecar({
      converged: false,
      reason: "array longer than sentinel",
      successfulLegs: [...LEGS],
      ...EVIDENCE,
      findings: [ONE_BLOCKER, { ...ONE_BLOCKER, claim_quote: "second" }],
    });
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 1\nCMR_STEP_COMPLETE\n",
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome.kind).toBe("malformed");
    if (outcome.kind === "malformed") {
      expect(outcome.reason).toMatch(/does not match structured findings length/i);
    }
  });

  it("stdout-only path: matching sentinel + structured findings → accepts (same write-point)", () => {
    // Empty/missing sidecar falls through to stdout <cmr> — still ADR 0129 write-point.
    const outcome = cmrOutcomeFromResult({
      stdout:
        `<cmr>${JSON.stringify({
          converged: false,
          reason: "stdout path one blocker",
          successfulLegs: [...LEGS],
          ...EVIDENCE,
          findings: [ONE_BLOCKER],
        })}</cmr>\nfindings = 1\nCMR_STEP_COMPLETE\n`,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    assertDerivedCount(outcome);
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 1 });
  });

  it("NEGATIVE: stdout-only path lying findings=N with empty array → malformed (not cmr_passed)", () => {
    // Ship-pre correctness r3: without sentinel check on stdout fallback,
    // findings=3 + empty structured array could derive open-count 0.
    const outcome = cmrOutcomeFromResult({
      stdout:
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: [...LEGS],
          ...EVIDENCE,
        })}</cmr>\nfindings = 3\nCMR_STEP_COMPLETE\n`,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome.kind).toBe("malformed");
    if (outcome.kind === "malformed") {
      expect(outcome.reason).toMatch(
        /does not match structured findings length|omitted required findings/i,
      );
    }
  });

  it("NEGATIVE: blank outcomePath sidecar falls through to stdout sentinel check", () => {
    const dir = mkdtempSync(join(tmpdir(), "875-envelope-blank-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8"); // blank → readWorkerOutcomeSidecar undefined → stdout
    const outcome = cmrOutcomeFromResult({
      stdout:
        `<cmr>${JSON.stringify({
          converged: true,
          successfulLegs: [...LEGS],
          ...EVIDENCE,
        })}</cmr>\nfindings = 2\nCMR_STEP_COMPLETE\n`,
      outcomePath: path,
      cmrReviewLegs: LEGS.map((slug) => ({ slug })),
    });
    expect(outcome.kind).toBe("malformed");
  });

  it("write-point malformation is rewrite feedback, not verifyCmr thrash-court fate", async () => {
    // A malformed outcome never becomes a completed CmrResult happy path.
    // Scripted completed payloads that reach verifyCmr only carry derived
    // array-length open-count — count-vs-array mismatch is filtered before.
    class Backend implements FamilyBackend {
      ledger: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(
        _c: MergeRequest,
      ): Promise<{ familyHead: string }> {
        return { familyHead: "unused" };
      }
      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return "head-1";
      }
      async runFamilyVerify(
        _r: FamilyVerifyRequest,
      ): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async verifyFamilyShippedPr(): Promise<{ ok: true }> {
        return { ok: true };
      }
      async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          // Only array-derived shape can arrive as completed verdict.
          const output: CmrResult = {
            kind: "cmr",
            converged: false,
            reason: "array-derived open count",
            successfulLegs: [...LEGS],
            findings: [ONE_BLOCKER],
            findingsCount: 1, // matches array; runner still ignores this field
            evidencePaths: EVIDENCE.evidencePaths,
          };
          return { kind: "completed", output };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: ctx.familyBase ?? "family/875",
              status: "pr_opened",
              pr: "pr://875",
              prHead: "head-1",
            },
          };
        }
        return (
          skeletonReviewLoopWorkerResult(spec.kind) ?? {
            kind: "failed",
            reason: `unexpected: ${spec.kind}`,
          }
        );
      }
    }
    const backend = new Backend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-s1",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });
    // Three-channel: open findings → coder-fix, not protocol/infra court death.
    expect(result).toEqual({ ok: false, ran: true });
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" && e.stopSummary?.reason === "infra_failure",
      ),
    ).toBe(false);
  });
});

// ───────────────────────────── T3 ─────────────────────────────

describe("#875 T3 — downstream has no shape fork (deletion stays deleted)", () => {
  it("verifyCmr executable source has zero independent findingsCount routing", () => {
    const code = stripComments(readFileSync(VERIFY_CMR_SRC, "utf8"));
    // openFindingsCount is the only count symbol — derived from array length.
    expect(code).toMatch(/\bopenFindingsCount\b/);
    // Independent field must not drive routing (openFindingsCount is allowed).
    const bareFindingsCount = code.match(/\bfindingsCount\b/g) ?? [];
    expect(bareFindingsCount).toEqual([]);
    // openFindingsCount must be array-derived, not read from findingsCount field.
    expect(code).toMatch(
      /openFindingsCount\s*=\s*cmrResult\.output\.findings\?\.length\s*\?\?\s*0/,
    );
    expect(code).not.toMatch(/findingsCount\s*\?\?/);
    expect(code).not.toMatch(/output\.findingsCount/);
  });

  it("verifyCmr has zero live thrash-court patterns for count-vs-array shape fails", () => {
    const code = stripComments(readFileSync(VERIFY_CMR_SRC, "utf8"));
    const forbidden: RegExp[] = [
      /does not match structured findings length/i,
      /without structured findings/i,
      /reportedFindingsCount/,
      /count\s*[!=]==?\s*.*findings\.length/,
      /findings\.length\s*[!=]==?\s*.*findingsCount/,
      /invent(?:ed|ing)?\s+findings/i,
      /补数/,
      /findingsCount\s*>\s*0\s*&&[\s\S]{0,80}findings\s*===\s*undefined/,
      /findingsCount\s*>\s*0[\s\S]{0,120}findings\.length\s*===\s*0/,
    ];
    for (const re of forbidden) {
      expect(code, `forbidden live thrash pattern: ${re}`).not.toMatch(re);
    }
  });

  it("write-point (realFamilyBackend) retains count≠length reject; runner does not", () => {
    const writePoint = stripComments(readFileSync(REAL_BACKEND_SRC, "utf8"));
    const runner = stripComments(readFileSync(VERIFY_CMR_SRC, "utf8"));
    // Write-point owns the mismatch reject (ADR 0129).
    expect(writePoint).toMatch(/does not match structured findings length/);
    expect(writePoint).toMatch(/findingsCount:\s*derivedCount|findingsCount:\s*redFindings/);
    // Runner must not re-host that court.
    expect(runner).not.toMatch(/does not match structured findings length/);
  });

  it("runner open-count is array-only even when CmrResult carries a lying findingsCount", async () => {
    // Behavioral pin of T3: independent field is ignored; array drives fix loop.
    class Backend implements FamilyBackend {
      ledger: FamilyLedgerEntry[] = [];
      dispatched: WorkerSpec["kind"][] = [];
      async mergeChildIntoFamilyBase(
        _c: MergeRequest,
      ): Promise<{ familyHead: string }> {
        return { familyHead: "unused" };
      }
      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return "head-1";
      }
      async runFamilyVerify(
        _r: FamilyVerifyRequest,
      ): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async verifyFamilyShippedPr(): Promise<{ ok: true }> {
        return { ok: true };
      }
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          const output: CmrResult = {
            kind: "cmr",
            converged: false,
            reason: "lying count field must not fork shape",
            successfulLegs: [...LEGS],
            findings: [ONE_BLOCKER],
            findingsCount: 0, // lie — runner must still see openCount=1
            evidencePaths: EVIDENCE.evidencePaths,
          };
          return { kind: "completed", output };
        }
        this.dispatched.push(spec.kind);
        return (
          skeletonReviewLoopWorkerResult(spec.kind) ?? {
            kind: "failed",
            reason: `coder-fix probe: ${spec.kind}`,
          }
        );
      }
    }
    const backend = new Backend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/875-s1",
      familyBackend: backend,
      familyHeadAfter: "head-1",
    });
    expect(result).toEqual({ ok: false, ran: true });
    // Array length 1 ⇒ coder-fix channel, not empty not_converged / not court death.
    expect(backend.dispatched.filter((k) => k === "coder")).toEqual([
      "coder",
      "coder",
      "coder",
    ]);
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" && e.stopSummary?.reason === "infra_failure",
      ),
    ).toBe(false);
  });
});
