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

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  it("the affix form 'non-converged' is NOT a pass (the `-` must not let \\bconverged\\b match through)", () => {
    // codex R1: `-` is a non-word char, so a naive `\bconverged\b` matches the
    // `converged` inside `non-converged` → a fabricated pass. Fail-closed: this is
    // a negated verdict, so it is findings.
    const v = parseReviewerVerdict("codex", "This change is non-converged: a seam bug remains.");
    expect(v.pass).toBe(false);
  });
  it("an interposed adverb ('not yet/fully converged') is NOT a pass", () => {
    // agy R1: an adverb between the negator and `converge` breaks a `\s+`-adjacency
    // guard, so the positive `\bconverged\b` fallback fires → a fabricated pass.
    expect(parseReviewerVerdict("agy", "The slices are not yet converged.").pass).toBe(false);
    expect(parseReviewerVerdict("codex", "This is not fully converged.").pass).toBe(false);
    expect(parseReviewerVerdict("claude", "Not completely converged — one seam left.").pass).toBe(false);
  });
  it("a HYPHENATED interposed adverb ('not fully-converged') is NOT a pass (online R1 Gemini)", () => {
    // online R1 (Gemini high): the interposed-adverb guard uses `\s+converg`, which
    // requires WHITESPACE right before `converg`. A hyphen joins the adverb to the
    // word — `not fully-converged` — so `\s+converg` cannot match (the separator is
    // `-`, not space), the negation falls through, and the positive `\bconverged\b`
    // matches the `converged` inside `fully-converged` → a FABRICATED pass. The
    // separator before `converg` must allow a hyphen too (`[\s-]+`).
    expect(parseReviewerVerdict("gemini", "This is not fully-converged.").pass).toBe(false);
    expect(parseReviewerVerdict("agy", "The slices are not yet-converged.").pass).toBe(false);
    expect(parseReviewerVerdict("codex", "It doesn't fully-converge here.").pass).toBe(false);
  });
  it("'failed to converge' / 'did not converge' are NOT a pass", () => {
    expect(parseReviewerVerdict("codex", "The review failed to converge.").pass).toBe(false);
    expect(parseReviewerVerdict("agy", "It did not converge cleanly.").pass).toBe(false);
  });
  it("the NOUN form 'failure to converge' is NOT a pass even when 'converged' also appears (cmr R2: `ure` suffix missed)", () => {
    // cmr R2: the negated form `failure to converge` was not matched by
    // `\bfail(?:s|ed|ing)?\s+to\s+converg` (it lacks `ure`). When the prose ALSO
    // contains the word `converged` (a reviewer describing why the diff is a
    // failure to converge despite some slices being converged), the unmatched
    // negation falls through to the positive `\bconverged\b` fallback → a
    // FABRICATED pass. The negation must catch the noun form so the negative wins.
    expect(
      parseReviewerVerdict(
        "codex",
        "Most slices are converged, but overall this is a failure to converge: the cannon/cannons seam still mismatches.",
      ).pass,
    ).toBe(false);
    expect(
      parseReviewerVerdict("agy", "Two slices converged; net result: failure to converge.").pass,
    ).toBe(false);
  });
  it("a genuine positive verdict still passes (the broadened negation must not over-trip)", () => {
    // Guard against the fix over-tripping: real convergence prose must still pass.
    expect(parseReviewerVerdict("codex", "All slices are converged. No findings.").pass).toBe(true);
    expect(parseReviewerVerdict("agy", "Reviewed the diff. No findings.").pass).toBe(true);
    expect(parseReviewerVerdict("claude", "CMR-VERDICT: converged").pass).toBe(true);
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
  diffArgs: string[] | undefined;
  diffFake = "diff --git a/x b/x\n+seam";
  protected override async runReviewer(vendor: string, diff: string): Promise<ReviewerOutput> {
    this.reviewerCalls.push({ vendor, diff });
    return this.reviewerOutputs[vendor] ?? { ok: false };
  }
  protected override sh(file: string, args: string[], _cwd?: string): string {
    if (file === "git" && args[0] === "diff") {
      this.diffArgs = args;
      return this.diffFake;
    }
    return "";
  }
  // expose the protected runCmr for the test
  async runCmrPublic(req: IntegratedCmrRequest) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (this as any).runCmr(req);
  }
}

function makeBackend(over: { familyBaseStartHead?: string } = {}): FixturedDriverBackend {
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
      familyBaseStartHead: over.familyBaseStartHead ?? "cut0sha",
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

  it("pins the diff from the REAL cut SHA (familyBaseStartHead), NOT the possibly-stale local base ref (cmr R2)", async () => {
    // cmr R2 #1: `familyBaseDiff` diffed `<opts.base>...<familyBase>`, but the
    // family base was cut from `origin/<base>` while the LOCAL `base` ref can be
    // stale — so a stale local base would show upstream commits as spurious family
    // additions in the reviewed diff. Diff from the recorded cut SHA instead, the
    // exact point the family base diverged.
    const b = makeBackend({ familyBaseStartHead: "cutsha123" });
    b.reviewerOutputs = {
      codex: { ok: true, prose: "converged" },
      claude: { ok: true, prose: "converged" },
      agy: { ok: true, prose: "converged" },
    };
    await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(b.diffArgs).toEqual(["diff", "cutsha123...family/291-base"]);
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

// ═══════════════════════ 4. spawnReviewer temp-file uniqueness (#291 r2 #5) ═══════════════════════

/**
 * A DriverFamilyBackend that captures the temp-file path each `spawnReviewer`
 * picks (the codex `-o <file>` arg and the agy `--log-file` arg), without a real
 * CLI: `shStdin` records the argv + writes a stub at the codex `-o` file so the
 * codex `readFileSync` succeeds. Exposes `spawnReviewer` for the test.
 */
class TempfileSpyBackend extends DriverFamilyBackend {
  shStdinArgs: string[][] = [];
  protected override async shStdin(
    _file: string,
    args: string[],
    _input: string,
    _cwd?: string,
  ): Promise<string> {
    this.shStdinArgs.push(args);
    const oIdx = args.indexOf("-o");
    if (oIdx >= 0 && args[oIdx + 1] !== undefined) {
      writeFileSync(args[oIdx + 1]!, "CMR-VERDICT: converged");
    }
    return "CMR-VERDICT: converged";
  }
  async spawnReviewerPublic(vendor: "codex" | "claude" | "agy", prompt: string): Promise<string> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (this as any).spawnReviewer(vendor, prompt);
  }
}

function makeTempfileSpy(): TempfileSpyBackend {
  return new TempfileSpyBackend(
    {
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "family/291-base",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: mkDir("cmr-prompts-"),
      imageName: "img",
      skillsMount: "/tmp/skills",
      familyBaseStartHead: "cut0sha",
    },
    undefined,
  );
}

// ═══════════════════════ 5. runCmr真并发 — shStdin is async (#291 r2 #3) ═══════════════════════

/**
 * A backend whose `shStdin` is the only spawn seam — it records how many legs are
 * IN-FLIGHT at once and blocks each leg on a barrier that only resolves once ALL
 * THREE legs have entered. If `shStdin` were synchronous (`execFileSync`,
 * event-loop-blocking), the first leg could never observe the other two enter →
 * the barrier would never resolve → timeout (the假并发). With a truly async
 * `shStdin`, all three enter, the barrier resolves, peak concurrency is 3.
 */
class ConcurrencySpyBackend extends DriverFamilyBackend {
  inflight = 0;
  peak = 0;
  private entered = 0;
  private releaseAll!: () => void;
  private readonly gate = new Promise<void>((r) => (this.releaseAll = r));
  protected override async shStdin(
    _file: string,
    args: string[],
    _input: string,
    _cwd?: string,
  ): Promise<string> {
    this.inflight += 1;
    this.peak = Math.max(this.peak, this.inflight);
    this.entered += 1;
    if (this.entered === 3) this.releaseAll(); // all three legs are concurrently in-flight
    await this.gate;
    const oIdx = args.indexOf("-o");
    if (oIdx >= 0 && args[oIdx + 1] !== undefined) {
      writeFileSync(args[oIdx + 1]!, "CMR-VERDICT: converged");
    }
    this.inflight -= 1;
    return "CMR-VERDICT: converged";
  }
  async runCmrPublic(req: IntegratedCmrRequest) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (this as any).runCmr(req);
  }
  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "diff") return "diff";
    return "";
  }
}

describe("#291 runCmr真并发 — the three reviewer legs run concurrently (r2 #3)", () => {
  it("fans the three legs out CONCURRENTLY (shStdin async, not event-loop-blocking)", async () => {
    const b = new ConcurrencySpyBackend(
      {
        workingRepo: mkDir("cmr-repo-"),
        familyBase: "family/291-base",
        ledgerDir: mkDir("cmr-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: mkDir("cmr-prompts-"),
        imageName: "img",
        skillsMount: "/tmp/skills",
        familyBaseStartHead: "cut0sha",
      },
      undefined,
    );
    // If shStdin blocked the event loop (the bug), this would deadlock — the test
    // timeout (5s default) catches it as a failure. With真并发 it resolves at once.
    const res = await b.runCmrPublic({ familyBase: "family/291-base" });
    expect(res).toEqual({ converged: true });
    expect(b.peak).toBe(3); // all three legs were in-flight simultaneously
  });
});

describe("#291 spawnReviewer temp-file uniqueness (r2 #5)", () => {
  it("two codex reviewer spawns in the SAME millisecond pick DISTINCT -o files (no Date.now() collision)", async () => {
    // r2 #5: the codex out-file was `cmr-codex-${Date.now()}.txt`; two legs spawned
    // in the SAME millisecond (the real path runs all three concurrently) would
    // pick the SAME path and clobber each other's last-message file. Pin Date.now to
    // a constant so the collision is deterministic — the name must carry a per-spawn
    // unique token beyond the timestamp.
    const spy = vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
    try {
      const b = makeTempfileSpy();
      await Promise.all([
        b.spawnReviewerPublic("codex", "p"),
        b.spawnReviewerPublic("codex", "p"),
      ]);
      const oFiles = b.shStdinArgs
        .map((a) => a[a.indexOf("-o") + 1])
        .filter((f): f is string => f !== undefined);
      expect(oFiles.length).toBe(2);
      expect(new Set(oFiles).size).toBe(2); // distinct despite identical Date.now()
    } finally {
      spy.mockRestore();
    }
  });

  it("two agy reviewer spawns in the SAME millisecond pick DISTINCT --log-file files", async () => {
    const spy = vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
    try {
      const b = makeTempfileSpy();
      await Promise.all([
        b.spawnReviewerPublic("agy", "p"),
        b.spawnReviewerPublic("agy", "p"),
      ]);
      const logFiles = b.shStdinArgs
        .map((a) => a[a.indexOf("--log-file") + 1])
        .filter((f): f is string => f !== undefined);
      expect(logFiles.length).toBe(2);
      expect(new Set(logFiles).size).toBe(2);
    } finally {
      spy.mockRestore();
    }
  });
});
