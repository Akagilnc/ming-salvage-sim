/**
 * PR #982 online bot findings (HQ fix_now) — regression nails.
 * Prior: G1 spread · C1 ledgerPhase · C2 route smoke
 * R2: P1 phase-scoped cmr pass · dual snapshot continue · severity ·
 *     failedPhase comment · S8 failed terminal
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ORCH = join(dirname(fileURLToPath(import.meta.url)), "../..");
const SRC = join(ORCH, "src");

function readSrc(rel: string): string {
  return readFileSync(join(SRC, rel), "utf8");
}

describe("PR #982 online bot fix_now regressions", () => {
  it("G1: residualOpenReviewer keeps fixPacketBody after ...extra (cannot override)", () => {
    const src = readSrc("dogfoodReplay.ts");
    const fn = src.match(
      /function residualOpenReviewer[\s\S]*?^}/m,
    )?.[0];
    expect(fn).toBeTruthy();
    // Mandatory body must win over spread extras.
    expect(fn).toMatch(/\.\.\.extra,\s*\n\s*fixPacketBody,/);
    expect(fn).not.toMatch(/fixPacketBody,\s*\n\s*\.\.\.extra,/);
  });

  it("C1: runIntegratedCmrPass threads ledgerPhase into runCmrCoderFix", () => {
    const src = readSrc("family/verifyCmr.ts");
    // Sole production call site: after familyIssue / resolvedRoute, ledgerPhase present.
    const call = src.match(
      /const fixRound = await runCmrCoderFix\(\{[\s\S]*?\n    \}\);/,
    )?.[0];
    expect(call).toBeTruthy();
    expect(call).toMatch(/\bledgerPhase\b/);
    // Must not only appear in the function signature default.
    expect(call).toMatch(/ledgerPhase,/);
  });

  it("C2: routeSmokeFailureResult uses route_smoke_failed (not worktree_prepare)", () => {
    const src = readSrc("familyDriver.ts");
    const fn = src.match(
      /function routeSmokeFailureResult[\s\S]*?^}/m,
    )?.[0];
    expect(fn).toBeTruthy();
    expect(fn).toMatch(/cause:\s*"route_smoke_failed"/);
    expect(fn).not.toMatch(/cause:\s*"worktree_prepare_failed"/);
  });

  it("P1: cmrPassAlreadyPassed is phase-scoped (checkpoint ≢ final)", () => {
    const src = readSrc("family/ledger.ts");
    const fn = src.match(
      /export function cmrPassAlreadyPassed[\s\S]*?^export function/m,
    )?.[0];
    expect(fn).toBeTruthy();
    expect(fn).toMatch(/cmrBarrierPhaseOf/);
    expect(fn).toMatch(/queryPhase/);
    // Must not treat both phases as equivalent court identity for admission.
    expect(fn).not.toMatch(
      /final and correctness_checkpoint share the same court identity/,
    );
  });

  it("verifyCmr passes ledgerPhase into cmrPassAlreadyPassed", () => {
    const src = readSrc("family/verifyCmr.ts");
    const call = src.match(
      /cmrPassAlreadyPassed\([\s\S]*?\}\)/,
    )?.[0];
    expect(call).toBeTruthy();
    expect(call).toMatch(/phase:\s*ledgerPhase/);
  });

  it("priorCmrFindings continue after explicit blocking keys (no dual snapshot)", () => {
    const src = readSrc("priorRoundFindings.ts");
    const fn = src.match(
      /export function priorCmrFindingsFromFamilyLedger[\s\S]*?^}/m,
    )?.[0];
    expect(fn).toBeTruthy();
    expect(fn).toMatch(/continue;/);
    expect(fn).toMatch(/Prefer explicit persisted keys/);
  });

  it("FamilyRunResultBase.failedPhase comment includes correctness_checkpoint", () => {
    const src = readSrc("family/types.ts");
    expect(src).toMatch(
      /Barrier phase diagnostic \(wave\|correctness_checkpoint\|final\)/,
    );
    expect(src).not.toMatch(
      /Barrier phase diagnostic \(wave\|final\); not public status/,
    );
  });

  it("planResume only reopens parked+decision — not failed+decision", () => {
    const src = readSrc("runner.ts");
    // Reopen branch must require parked (not parked|failed).
    expect(src).toMatch(
      /handoffStatus === "parked" &&\s*\n\s*lastEntry\.escalationKind !== undefined/,
    );
    expect(src).not.toMatch(
      /handoffStatus === "parked" \|\| lastEntry\.handoffStatus === "failed"\) &&\s*\n\s*lastEntry\.escalationKind/,
    );
  });
});
