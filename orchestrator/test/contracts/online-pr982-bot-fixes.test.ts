/**
 * PR #982 online bot findings (HQ fix_now) — regression nails.
 * G1 spread order · C1 ledgerPhase on coder-fix · C2 route smoke public cause
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
});
