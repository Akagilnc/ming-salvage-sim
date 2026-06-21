/**
 * #291 last gap — DriverFamilyBackend.runCmr: the integrated cmr 承重闸 as a real
 * autonomous 3-leg reviewer-CLI orchestration (claude + codex + agy, 1+1+1).
 *
 * The integrated cmr is ship-pre-grade. `ak-cross-m-review` is a Claude *skill*
 * orchestrated through the agent harness, NOT stably invocable from inside the
 * runtime — so the real cmr here directly spawns the THREE reviewer CLIs and
 * parses their PROSE verdicts (no sentinel-JSON format gate — codex is a prose
 * reviewer; demanding sentinel-JSON would throw away the strongest leg).
 *
 * Tested WITHOUT real CLIs:
 *   - parseReviewerVerdict: prose → pass / findings (CMR-VERDICT sentinel, the
 *     "converged" word, "no findings", or genuine findings prose);
 *   - aggregateCmr: all-pass → converged; any leg with findings → not converged
 *     + an aggregated reason; a DOWN leg degrades (reviewer-missing ≠ findings);
 *   - DriverFamilyBackend.runCmr: fans the 3 legs out through the injected
 *     `runReviewer` seam (fixtured prose), pins the diff via `this.sh` git, and
 *     aggregates — converged / findings / a down leg degrade / all-down.
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  DriverFamilyBackend,
  aggregateCmr,
  parseReviewerVerdict,
  type ReviewerLeg,
  type ReviewerOutput,
} from "../../src/familyDriver.js";
import type { IntegratedCmrRequest } from "../../src/family/types.js";

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

// ═══════════════════════ 1. parseReviewerVerdict (pure prose) ═══════════════════════

describe("#291 parseReviewerVerdict — prose verdict, no sentinel-JSON gate", () => {
  it("the explicit CMR-VERDICT: converged sentinel ⇒ pass", () => {
    const v = parseReviewerVerdict("codex", "I reviewed the diff.\n\nCMR-VERDICT: converged\n");
    expect(v.pass).toBe(true);
    expect(v.vendor).toBe("codex");
  });
  it("the word 'converged' in prose (no sentinel) ⇒ pass", () => {
    const v = parseReviewerVerdict("claude", "Cross-slice seams look consistent; this is converged.");
    expect(v.pass).toBe(true);
  });
  it("'no findings' prose ⇒ pass", () => {
    const v = parseReviewerVerdict("agy", "Reviewed the family base diff. No findings.");
    expect(v.pass).toBe(true);
  });
  it("genuine findings prose ⇒ NOT pass, and the reason carries the prose", () => {
    const prose =
      "CMR-VERDICT: not converged\nP1: field name `cannon` in slice A vs `cannons` in slice B.";
    const v = parseReviewerVerdict("codex", prose);
    expect(v.pass).toBe(false);
    expect(v.reason).toContain("cannon");
  });
  it("an explicit non-converged sentinel OVERRIDES an incidental 'converged' word", () => {
    // A reviewer that writes "this is not converged" must not be read as pass just
    // because the substring "converged" appears.
    const v = parseReviewerVerdict("claude", "This is not converged: there is a seam bug.");
    expect(v.pass).toBe(false);
  });
});

// ═══════════════════════ 2. aggregateCmr (3-leg + degradation) ═══════════════════════

describe("#291 aggregateCmr — all-pass converge, any-findings red, down-leg degrade", () => {
  it("all three legs pass ⇒ converged", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "codex", status: "pass" },
      { vendor: "claude", status: "pass" },
      { vendor: "agy", status: "pass" },
    ];
    expect(aggregateCmr(legs)).toEqual({ converged: true });
  });
  it("any leg with findings ⇒ NOT converged, reason names the leg + its finding", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "codex", status: "findings", reason: "P1 seam: type mismatch" },
      { vendor: "claude", status: "pass" },
      { vendor: "agy", status: "pass" },
    ];
    const res = aggregateCmr(legs);
    expect(res.converged).toBe(false);
    expect(res.reason).toContain("codex");
    expect(res.reason).toContain("type mismatch");
  });
  it("a DOWN leg degrades (reviewer-missing ≠ findings): the other two passing ⇒ converged", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "agy", status: "down", reason: "auth/quota down" },
      { vendor: "codex", status: "pass" },
      { vendor: "claude", status: "pass" },
    ];
    const res = aggregateCmr(legs);
    expect(res.converged).toBe(true); // the down leg does NOT block convergence
  });
  it("a down leg AND a findings leg ⇒ NOT converged (the findings win)", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "agy", status: "down" },
      { vendor: "codex", status: "findings", reason: "P0 cross-slice regression" },
      { vendor: "claude", status: "pass" },
    ];
    const res = aggregateCmr(legs);
    expect(res.converged).toBe(false);
    expect(res.reason).toContain("P0 cross-slice regression");
  });
  it("ALL legs down ⇒ NOT converged fail-closed (no reviewer ran, never a fake pass)", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "codex", status: "down" },
      { vendor: "claude", status: "down" },
      { vendor: "agy", status: "down" },
    ];
    const res = aggregateCmr(legs);
    expect(res.converged).toBe(false);
    expect(res.reason).toMatch(/no reviewer|all.*down|缺/i);
  });
  it("two findings legs ⇒ both reasons aggregated", () => {
    const legs: ReviewerLeg[] = [
      { vendor: "codex", status: "findings", reason: "A" },
      { vendor: "claude", status: "findings", reason: "B" },
      { vendor: "agy", status: "pass" },
    ];
    const res = aggregateCmr(legs);
    expect(res.converged).toBe(false);
    expect(res.reason).toContain("A");
    expect(res.reason).toContain("B");
  });
});

// ═══════════════════════ 3. DriverFamilyBackend.runCmr orchestration ═══════════════════════

/**
 * A DriverFamilyBackend whose `runReviewer` seam is FIXTURED per vendor and whose
 * `sh` git is intercepted — so the 3-leg orchestration + diff-pin + aggregation run
 * with NO real claude/codex/agy CLI and NO real git.
 */
class FixturedDriverBackend extends DriverFamilyBackend {
  reviewerOutputs: Record<string, ReviewerOutput> = {};
  reviewerCalls: Array<{ vendor: string; diff: string }> = [];
  diffFake = "diff --git a/x b/x\n+seam";
  protected override async runReviewer(vendor: string, diff: string): Promise<ReviewerOutput> {
    this.reviewerCalls.push({ vendor, diff });
    return this.reviewerOutputs[vendor] ?? { ok: false };
  }
  protected override sh(file: string, args: string[], _cwd?: string): string {
    if (file === "git" && args[0] === "diff") return this.diffFake;
    return "";
  }
  // expose the protected runCmr for the test
  async runCmrPublic(req: IntegratedCmrRequest) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (this as any).runCmr(req);
  }
}

function makeBackend(): FixturedDriverBackend {
  return new FixturedDriverBackend(
    {
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "family/291-base",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: mkDir("cmr-prompts-"),
      imageName: "img",
      skillsMount: "/tmp/skills",
    },
    undefined, // no injected cmrImpl ⇒ the REAL 3-leg path runs
  );
}

describe("#291 DriverFamilyBackend.runCmr — real 3-leg reviewer orchestration", () => {
  it("fans the diff out to all three reviewer legs (claude + codex + agy)", async () => {
    const b = makeBackend();
    b.reviewerOutputs = {
      codex: { ok: true, prose: "CMR-VERDICT: converged" },
      claude: { ok: true, prose: "converged, no findings" },
      agy: { ok: true, prose: "No findings." },
    };
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(res).toEqual({ converged: true });
    expect(b.reviewerCalls.map((c) => c.vendor).sort()).toEqual(["agy", "claude", "codex"]);
    // every leg got the SAME pinned diff
    expect(b.reviewerCalls.every((c) => c.diff === b.diffFake)).toBe(true);
  });

  it("one leg reports findings ⇒ NOT converged, reason names the leg", async () => {
    const b = makeBackend();
    b.reviewerOutputs = {
      codex: { ok: true, prose: "CMR-VERDICT: not converged\nP1 seam: cannon vs cannons mismatch." },
      claude: { ok: true, prose: "converged" },
      agy: { ok: true, prose: "no findings" },
    };
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(res.converged).toBe(false);
    expect(res.reason).toContain("codex");
    expect(res.reason).toContain("cannon");
  });

  it("agy down (non-zero exit / empty output) degrades: the other two pass ⇒ converged", async () => {
    const b = makeBackend();
    b.reviewerOutputs = {
      codex: { ok: true, prose: "CMR-VERDICT: converged" },
      claude: { ok: true, prose: "converged" },
      agy: { ok: false }, // CLI down (agy is commonly down on this host)
    };
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(res).toEqual({ converged: true });
  });

  it("a leg that exits ok but emits EMPTY prose is treated as down (degrade, not pass)", async () => {
    const b = makeBackend();
    b.reviewerOutputs = {
      codex: { ok: true, prose: "   " }, // empty/whitespace ⇒ down
      claude: { ok: true, prose: "converged" },
      agy: { ok: true, prose: "no findings" },
    };
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    // codex degraded; the other two passed ⇒ converged
    expect(res).toEqual({ converged: true });
  });

  it("ALL three legs down ⇒ NOT converged fail-closed (never a fabricated pass)", async () => {
    const b = makeBackend();
    b.reviewerOutputs = {
      codex: { ok: false },
      claude: { ok: false },
      agy: { ok: false },
    };
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(res.converged).toBe(false);
  });
});
