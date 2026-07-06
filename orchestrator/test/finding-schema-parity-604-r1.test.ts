/**
 * #604 ship-pre CMR correctness r1 — P2-a / P2-b finding-contract parity.
 *
 * P2-a: an `accepted_suppressed` governance disposition is ONLY valid on
 *   wont_fix/rejected. On fix_now (or any other action) it must be rejected —
 *   classifyFindings treats fix_now as blocking, so a fix_now + accepted_suppressed
 *   would silently turn the governance suppression into a blocker.
 *
 * P2-b: ADR 0062 removed all non-suppression route disposition kinds, so `defer`
 *   can no longer carry a valid non-suppression disposition. A stray defer fails
 *   closed as MALFORMED across every real entry — the TS validate path AND the
 *   Python outcome-guard (which slice-4 missed, and which still accepted the old
 *   route kinds same_module / cross_module / spec_conflict / infra_failure /
 *   owning_issue_still_red).
 */

import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isValidFinding } from "../src/validate.js";

const GUARD = resolve(process.cwd(), "image/bin/orchestrator-outcome-guard");

const suppression = {
  kind: "accepted_suppressed" as const,
  source: "ADR 0030 accepted scope",
  scope: "existing invariant",
  reason: "accepted as outside slice",
  boundedReopen: "reopen if severity escalates or new evidence changes scope",
};

function baseFinding(): Record<string, unknown> {
  return {
    severity: "medium",
    category: "correctness",
    claim_quote: "claim",
    location: "src/x.ts:1",
    suggested_fix: "fix it",
  };
}

describe("#604 r1 P2-a — accepted_suppressed only valid on wont_fix/rejected (validate.ts)", () => {
  it("rejects a fix_now finding carrying an accepted_suppressed disposition", () => {
    const finding = {
      ...baseFinding(),
      action: "fix_now",
      disposition: suppression,
    };
    expect(isValidFinding(finding)).toBe(false);
  });

  it("accepts a wont_fix finding carrying an accepted_suppressed disposition", () => {
    const finding = {
      ...baseFinding(),
      action: "wont_fix",
      disposition_reason: "r",
      disposition: suppression,
    };
    expect(isValidFinding(finding)).toBe(true);
  });
});

describe("#604 r1 P2-b — a stray defer is malformed (validate.ts)", () => {
  it("rejects a defer finding with an accepted_suppressed disposition", () => {
    const finding = {
      ...baseFinding(),
      action: "defer",
      disposition: suppression,
    };
    expect(isValidFinding(finding)).toBe(false);
  });

  it("rejects a defer finding with no disposition", () => {
    const finding = { ...baseFinding(), action: "defer" };
    expect(isValidFinding(finding)).toBe(false);
  });
});

// ─── Python outcome-guard parity (P2-b: guard slice-4 miss) ─────────────────────

function runGuardOnFindings(findings: unknown[]): ReturnType<typeof spawnSync> {
  const dir = mkdtempSync(join(tmpdir(), "guard-parity-604-r1-"));
  try {
    mkdirSync(join(dir, "cmr"), { recursive: true });
    writeFileSync(join(dir, "cmr", "review.json"), '{"finding":true}\n', "utf8");
    const draftPath = join(dir, "draft.json");
    const sidecarPath = join(dir, "outcome.json");
    writeFileSync(
      draftPath,
      JSON.stringify({
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: ["gpt-5.5"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings,
        evidencePaths: ["cmr/review.json"],
      }),
      "utf8",
    );
    writeFileSync(sidecarPath, "sentinel\n", "utf8");
    return spawnSync(
      GUARD,
      [
        "--role",
        "cmr",
        "--draft",
        draftPath,
        "--outcome",
        sidecarPath,
        "--evidence-root",
        dir,
        "--completion-signal",
        "CMR_STEP_COMPLETE",
      ],
      { encoding: "utf8" },
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("#604 r1 P2-b — Python outcome-guard口径 parity", () => {
  it("rejects the deleted route kinds (cross_module) that slice-4 missed", () => {
    const result = runGuardOnFindings([
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "old route kind must no longer validate",
        location: "orchestrator/src/family/runner.ts:1",
        suggested_fix: "report it fix_now",
        action: "wont_fix",
        disposition_reason: "r",
        disposition: {
          kind: "cross_module",
          targetModule: "some-module",
          reason: "claimed cross module",
        },
      },
    ]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("kind is not a supported value");
  });

  it("rejects a stray defer as malformed", () => {
    const result = runGuardOnFindings([
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "stray defer must be malformed",
        location: "orchestrator/src/family/runner.ts:1",
        suggested_fix: "report it fix_now",
        action: "defer",
        disposition: suppression,
      },
    ]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("defer");
  });

  it("rejects a fix_now finding carrying an accepted_suppressed disposition", () => {
    const result = runGuardOnFindings([
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "accepted suppression on fix_now must be rejected",
        location: "orchestrator/src/family/runner.ts:1",
        suggested_fix: "pair suppression with wont_fix/rejected",
        action: "fix_now",
        disposition: suppression,
      },
    ]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("accepted_suppressed");
  });

  it("accepts a wont_fix finding carrying a valid accepted_suppressed disposition", () => {
    // The one governance disposition that survives must still pass the guard.
    const result = runGuardOnFindings([
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "valid governance suppression still passes",
        location: "orchestrator/src/family/runner.ts:1",
        suggested_fix: "n/a",
        action: "wont_fix",
        disposition_reason: "r",
        disposition: { ...suppression, findingIdentity: "correctness|x|y" },
      },
    ]);
    expect(result.status).toBe(0);
  });

  // #604 correctness r2 (C3): `targetModule` was deleted from the TS reviewer
  // contract (findingDispositionSchema / cmrDispositionEvidenceSchema `.strict()`),
  // so the family parser now rejects it. The Python guard's `allowed` set still
  // whitelisted `targetModule`, letting it pass — a cross-entry parity drift
  // (guard says OK, family parser rejects). The guard must reject an
  // accepted_suppressed disposition carrying the deleted `targetModule` field.
  it("rejects an accepted_suppressed disposition carrying the deleted targetModule field", () => {
    const result = runGuardOnFindings([
      {
        severity: "medium",
        category: "correctness",
        claim_quote: "deleted targetModule field must no longer validate",
        location: "orchestrator/src/family/runner.ts:1",
        suggested_fix: "n/a",
        action: "wont_fix",
        disposition_reason: "r",
        disposition: {
          ...suppression,
          findingIdentity: "correctness|x|y",
          targetModule: "some-module",
        },
      },
    ]);
    expect(result.status).toBe(1);
  });
});
