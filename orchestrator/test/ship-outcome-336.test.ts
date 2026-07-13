/**
 * #336 — the ship step is a WORKER that invokes `gstack-ship`, replacing the
 * inline `RealBackend.push` (single slice) + `openFamilyPr` (family).
 *
 * `gstack-ship` does more than push+PR (base merge / tests / diff review / VERSION
 * / CHANGELOG + STOP/HITL). The worker classifies its `<ship>` tag into a
 * {@link ShipWorkerOutcome}:
 *   - `shipped`    — a PR opened / push landed (the normal success);
 *   - `escalate`   — a genuine block (merge conflict / review ASK / hard defect a
 *     human must answer) — NOT a rerun-able failure (the worker reruns those itself);
 *   - `failed`     — a ship command / the tests hard-failed, no rerun cleared it;
 *   - `malformed`  — no parseable `<ship>` tag / no completion signal.
 *
 * Pure parse + the completion-signal gate, unit-tested WITHOUT a real container
 * (mirrors #335's parseCmrOutcome / cmrOutcomeFromResult).
 */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  parseShipOutcome,
  shipOutcomeFromResult,
} from "../src/shipOutcome.js";

// ═══════════════════════ parseShipOutcome (pure tag parse) ═══════════════════════

describe("#336 parseShipOutcome — the <ship> verdict tag", () => {
  it("status pr_opened + branch + pr ⇒ a shipped outcome carrying the PR", () => {
    const o = parseShipOutcome(
      'noise\n<ship>{"status": "pr_opened", "branch": "feat/x", "pr": "https://gh/pr/1"}</ship>\n',
    );
    expect(o.kind).toBe("shipped");
    if (o.kind === "shipped") {
      expect(o.branch).toBe("feat/x");
      expect(o.pr).toBe("https://gh/pr/1");
      expect(o.status).toBe("pr_opened");
    }
  });

  it("status pushed (no pr) ⇒ a shipped outcome without a PR url", () => {
    const o = parseShipOutcome('<ship>{"status": "pushed", "branch": "feat/y"}</ship>');
    expect(o.kind).toBe("shipped");
    if (o.kind === "shipped") {
      expect(o.branch).toBe("feat/y");
      expect(o.pr).toBeUndefined();
      expect(o.status).toBe("pushed");
    }
  });

  it("status pushed (no pr) + branch — pushed never needs a pr", () => {
    const o = parseShipOutcome('<ship>{"status": "pushed", "branch": "feat/z"}</ship>');
    expect(o.kind).toBe("shipped");
    if (o.kind === "shipped") {
      expect(o.status).toBe("pushed");
      expect(o.branch).toBe("feat/z");
      expect(o.pr).toBeUndefined();
    }
  });

  it("status pr_opened + branch + pr ⇒ shipped (the only valid pr_opened shape)", () => {
    const o = parseShipOutcome(
      '<ship>{"status": "pr_opened", "branch": "feat/p", "pr": "https://gh/pr/7"}</ship>',
    );
    expect(o.kind).toBe("shipped");
    if (o.kind === "shipped") {
      expect(o.status).toBe("pr_opened");
      expect(o.branch).toBe("feat/p");
      expect(o.pr).toBe("https://gh/pr/7");
    }
  });

  it("an UNKNOWN status (with branch) ⇒ malformed (fail-closed, contract is {pr_opened|pushed})", () => {
    const o = parseShipOutcome('<ship>{"status": "blocked", "branch": "feat/x"}</ship>');
    expect(o.kind).toBe("malformed");
    if (o.kind === "malformed") expect(o.reason).toContain("status");
  });

  it("pr_opened without cargo URL remains a shipped worker report", () => {
    const o = parseShipOutcome('<ship>{"status": "pr_opened", "branch": "feat/x"}</ship>');
    expect(o.kind).toBe("shipped");
  });

  it("an escalate object ⇒ an escalate outcome (a genuine block, not a rerun)", () => {
    const o = parseShipOutcome(
      '<ship>{"escalate": {"reason": "merge conflict", "diagnosis": "cannot auto-resolve base merge", "escalationKind": "decision"}}</ship>',
    );
    expect(o.kind).toBe("escalate");
    if (o.kind === "escalate") {
      expect(o.reason).toContain("merge conflict");
      expect(o.diagnosis).toContain("auto-resolve");
    }
  });

  it("a failed object ⇒ a failed outcome (a hard ship/test failure)", () => {
    const o = parseShipOutcome(
      '<ship>{"failed": {"reason": "tests red", "diagnosis": "vitest exited 1"}}</ship>',
    );
    expect(o.kind).toBe("failed");
    if (o.kind === "failed") {
      expect(o.reason).toContain("tests red");
    }
  });

  it("only the LAST <ship> tag is read (the worker may iterate / self-rerun)", () => {
    const o = parseShipOutcome(
      '<ship>{"failed": {"reason": "flake"}}</ship>\nrerun…\n<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    );
    expect(o.kind).toBe("shipped");
  });

  it("no <ship> tag ⇒ malformed (never silently a success)", () => {
    expect(parseShipOutcome("I pushed and opened a PR, all good.").kind).toBe("malformed");
  });

  it("a non-JSON / non-object <ship> body ⇒ malformed", () => {
    expect(parseShipOutcome("<ship>not json</ship>").kind).toBe("malformed");
    expect(parseShipOutcome("<ship>null</ship>").kind).toBe("malformed");
    expect(parseShipOutcome("<ship>true</ship>").kind).toBe("malformed");
  });

  it("a shipped object with no branch keeps optional cargo optional", () => {
    expect(parseShipOutcome('<ship>{"status": "pr_opened", "pr": "u"}</ship>').kind).toBe(
      "shipped",
    );
  });

  it("a <ship> object with no status, escalate or failed ⇒ malformed", () => {
    expect(parseShipOutcome('<ship>{"foo": 1}</ship>').kind).toBe("malformed");
  });

  // ── Finding 2 (cmr S336 r2): a garbage escalate/failed must NOT be coerced into
  // a structured result — both `reason` AND `diagnosis` MUST be non-empty strings
  // (prompts/ship.md + family_ship.md require both). Mirrors the既有 escalate
  // invariant (validate.ts isValidEscalation / integ-cmr-base-r1-seams F1): an
  // off-contract escalate/failed → malformed, never a fabricated stop signal.
  describe("Finding 2: a malformed escalate is never coerced into an escalate", () => {
    it("escalate:{} (empty) ⇒ malformed", () => {
      expect(parseShipOutcome('<ship>{"escalate": {}}</ship>').kind).toBe("malformed");
    });
    it("escalate with non-string reason ⇒ malformed", () => {
      expect(
        parseShipOutcome('<ship>{"escalate": {"reason": 123, "diagnosis": "x"}}</ship>').kind,
      ).toBe("malformed");
    });
    it("escalate missing diagnosis ⇒ malformed", () => {
      expect(parseShipOutcome('<ship>{"escalate": {"reason": "stuck"}}</ship>').kind).toBe(
        "malformed",
      );
    });
    it("escalate with empty-string fields ⇒ malformed", () => {
      expect(
        parseShipOutcome('<ship>{"escalate": {"reason": "", "diagnosis": "   "}}</ship>').kind,
      ).toBe("malformed");
    });
  });

  describe("Finding 2: a malformed failed is never coerced into a failed", () => {
    it("failed:{} (empty) ⇒ malformed", () => {
      expect(parseShipOutcome('<ship>{"failed": {}}</ship>').kind).toBe("malformed");
    });
    it("failed with non-string diagnosis ⇒ malformed", () => {
      expect(
        parseShipOutcome('<ship>{"failed": {"reason": "tests red", "diagnosis": 5}}</ship>').kind,
      ).toBe("malformed");
    });
    it("failed missing diagnosis ⇒ malformed", () => {
      expect(parseShipOutcome('<ship>{"failed": {"reason": "tests red"}}</ship>').kind).toBe(
        "malformed",
      );
    });
    it("failed with empty-string fields ⇒ malformed", () => {
      expect(
        parseShipOutcome('<ship>{"failed": {"reason": "  ", "diagnosis": ""}}</ship>').kind,
      ).toBe("malformed");
    });
  });

  // ── cmr S336 r3 (architecture centralization via strict zod): the per-slice cmr
  // kept finding NEW surfaces of the SAME fail-open class (a too-lax shape passes the
  // success branch). The zod discriminated union closes the whole class at once.
  //
  // F2 — empty / whitespace-only branch + pr are NOT a real delivery (a PR/push with a
  // blank branch or a blank URL is unusable). `isFilledString` existed but only gated
  // reason/diagnosis; the success shape leaked them.
  describe("cmr S336 r3 F2: blank branch / blank pr is never a shipped success", () => {
    it('pushed with empty-string branch ⇒ malformed', () => {
      expect(parseShipOutcome('<ship>{"status": "pushed", "branch": ""}</ship>').kind).toBe(
        "malformed",
      );
    });
    it('pushed with whitespace-only branch ⇒ malformed', () => {
      expect(parseShipOutcome('<ship>{"status": "pushed", "branch": "   "}</ship>').kind).toBe(
        "malformed",
      );
    });
    it('pr_opened with empty-string branch ⇒ malformed', () => {
      expect(
        parseShipOutcome('<ship>{"status": "pr_opened", "branch": "", "pr": "u"}</ship>').kind,
      ).toBe("malformed");
    });
    it('pr_opened with empty-string pr ⇒ malformed (a PR with no URL is unusable)', () => {
      expect(
        parseShipOutcome('<ship>{"status": "pr_opened", "branch": "b", "pr": ""}</ship>').kind,
      ).toBe("malformed");
    });
    it('pr_opened with whitespace-only pr ⇒ malformed', () => {
      expect(
        parseShipOutcome('<ship>{"status": "pr_opened", "branch": "b", "pr": "   "}</ship>').kind,
      ).toBe("malformed");
    });
  });

  // F3 — a MIXED payload (a success shape carrying an extra verdict key) was落到 the
  // success branch because the old guard only checked `typeof escalate === "object"`:
  // a non-object `failed`/`escalate` (a string) was skipped, and an extra verdict key
  // alongside a valid success was simply ignored → a "failed" run read as shipped.
  // `.strict()` rejects any object carrying keys outside the matched shape.
  describe("cmr S336 r3 F3: a mixed / extra-key payload is never coerced to shipped", () => {
    it('pr_opened carrying a `failed` string key ⇒ malformed (extra verdict key)', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pr_opened", "branch": "b", "pr": "u", "failed": "tests red"}</ship>',
        ).kind,
      ).toBe("malformed");
    });
    it('pr_opened carrying an `escalate` string key ⇒ malformed (extra verdict key)', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pr_opened", "branch": "b", "pr": "u", "escalate": "stuck"}</ship>',
        ).kind,
      ).toBe("malformed");
    });
    it('pushed carrying a `pr` key ⇒ malformed (pushed must NOT carry pr)', () => {
      expect(
        parseShipOutcome('<ship>{"status": "pushed", "branch": "b", "pr": "u"}</ship>').kind,
      ).toBe("malformed");
    });
    it('pushed carrying an extra `failed` key ⇒ malformed', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pushed", "branch": "b", "failed": {"reason": "x", "diagnosis": "y"}}</ship>',
        ).kind,
      ).toBe("malformed");
    });
    it('a success shape with an arbitrary extra key ⇒ malformed (.strict)', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pushed", "branch": "b", "junk": 1}</ship>',
        ).kind,
      ).toBe("malformed");
    });
    it('a non-object `failed` (string) does NOT leak the success branch ⇒ malformed', () => {
      // No status/branch success either, so this must be malformed (not silently shipped).
      expect(parseShipOutcome('<ship>{"failed": "tests red"}</ship>').kind).toBe("malformed");
    });
    it('a non-object `escalate` (string) ⇒ malformed', () => {
      expect(parseShipOutcome('<ship>{"escalate": "stuck"}</ship>').kind).toBe("malformed");
    });
    it('an escalate object with an extra key ⇒ malformed (.strict on the inner shape)', () => {
      expect(
        parseShipOutcome(
          '<ship>{"escalate": {"reason": "r", "diagnosis": "d", "extra": 1}}</ship>',
        ).kind,
      ).toBe("malformed");
    });
  });
});

// ═══════════════════ shipOutcomeFromResult (machine sidecar only) ═══════════════════

describe("#820 shipOutcomeFromResult — machine sidecar only", () => {
  it("accepts a valid machine sidecar without the worker SHIP_STEP_COMPLETE password", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ status: "pushed", branch: "worker-reported-wrong-branch" }) + "\n",
      "utf8",
    );

    const o = shipOutcomeFromResult({
      stdout: "ship completed without a sentinel",
      outcomePath,
    });

    expect(o).toEqual({
      kind: "shipped",
      branch: "worker-reported-wrong-branch",
      status: "pushed",
    });
  });

  it("does not parse human-readable stdout as the machine outcome", () => {
    const o = shipOutcomeFromResult({
      stdout: '<ship>{"status":"pushed","branch":"feat/from-prose"}</ship>',
    });

    expect(o.kind).toBe("malformed");
  });

  it("prefers a runner-owned outcome sidecar over malformed ship stdout", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ status: "pushed", branch: "feat/issue-496" }) + "\n",
      "utf8",
    );

    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: "<ship>not json</ship>\nSHIP_STEP_COMPLETE",
      outcomePath,
    });

    expect(o).toEqual({
      kind: "shipped",
      status: "pushed",
      branch: "feat/issue-496",
    });
  });

  it("parses sidecar payloads directly when free-form text contains a ship tag delimiter", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-delimiter-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        failed: {
          reason: "tests red",
          diagnosis: "log quoted the literal </ship> delimiter",
        },
      }) + "\n",
      "utf8",
    );

    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: "<ship>not json</ship>\nSHIP_STEP_COMPLETE",
      outcomePath,
    });

    expect(o).toEqual({
      kind: "failed",
      reason: "tests red",
      diagnosis: "log quoted the literal </ship> delimiter",
    });
  });

  it("fails closed instead of falling back to stdout when the ship outcome sidecar is malformed", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("malformed");
    if (o.kind === "malformed") expect(o.reason).toContain("sidecar");
  });

  it("rejects a blank guarded ship sidecar instead of falling back to stdout", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-blank-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "   \n", "utf8");

    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("malformed");
    if (o.kind === "malformed") expect(o.reason).toContain("sidecar");
  });

  it("never falls back to signaled ship stdout when no outcome sidecar path exists", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
    });

    expect(o.kind).toBe("malformed");
  });

  it("reports a malformed sidecar independently of the obsolete completion signal", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-unsignaled-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const o = shipOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("malformed");
    if (o.kind === "malformed") expect(o.reason).toContain("sidecar");
  });

  it("a signaled stdout-only run is still malformed", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("malformed");
  });

  it("an unsignaled stdout-only run is malformed, not escalated", () => {
    const o = shipOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("malformed");
  });

  it("a wrong-signal stdout-only run is malformed, not escalated", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("malformed");
  });

  it("a signal alone is not a machine outcome", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: "no tag here",
    });
    expect(o.kind).toBe("malformed");
  });
});
