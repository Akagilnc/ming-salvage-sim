/**
 * #336 — the family ship step is a WORKER that invokes `gstack-ship`.
 *
 * `gstack-ship` does more than push+PR (base merge / tests / diff review / VERSION
 * / CHANGELOG + STOP/HITL). The worker classifies its `<ship>` tag into a
 * {@link ShipWorkerOutcome}:
 *   - `shipped`    — a PR opened / push landed (the normal success);
 *   - `escalate`   — a genuine block (merge conflict / review ASK / hard defect a
 *     human must answer) — NOT a rerun-able failure (the worker reruns those itself);
 *   - `completed`  — clean exit with no decision bell or useful delivery cargo.
 *
 * Pure decision-bell probing + best-effort cargo parse, unit-tested WITHOUT a real container
 * (mirrors #335's parseCmrOutcome / cmrOutcomeFromResult).
 */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  parseShipOutcome,
  shipOutcomeFromResult,
} from "../../src/shipOutcome.js";

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

  it("an escalate object ⇒ an escalate outcome (a genuine block, not a rerun)", () => {
    const o = parseShipOutcome(
      '<ship>{"escalate": {"reason": "merge conflict", "diagnosis": "cannot auto-resolve base merge"}}</ship>',
    );
    expect(o.kind).toBe("escalate");
    if (o.kind === "escalate") {
      expect(o.reason).toContain("merge conflict");
      expect(o.diagnosis).toContain("auto-resolve");
    }
  });

  it("rings the ship decision bell before judging unrelated receipt cargo", () => {
    const o = parseShipOutcome(
      '<ship>{"status": 42, "unknownCargo": {"kept": true}, "escalate": {"reason": "scope decision", "diagnosis": "owner must choose"}}</ship>',
    );
    expect(o).toMatchObject({
      kind: "escalate",
      reason: "scope decision",
      diagnosis: "owner must choose",
    });
  });

  it("only the LAST <ship> tag is read (the worker may iterate / self-rerun)", () => {
    const o = parseShipOutcome(
      '<ship>{"failed": {"reason": "flake"}}</ship>\nrerun…\n<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    );
    expect(o.kind).toBe("shipped");
  });

  it("a shipped object with no branch keeps optional cargo optional", () => {
    expect(parseShipOutcome('<ship>{"status": "pr_opened", "pr": "u"}</ship>').kind).toBe(
      "shipped",
    );
  });

  // #899: only well-formed bells (non-empty reason+diagnosis) are fate signals.
  // Malformed escalate fails the Action for #598 — never invents a park.
  describe("malformed decision bells fail the Action", () => {
    it("escalate:{} (empty) throws", () => {
      expect(() => parseShipOutcome('<ship>{"escalate": {}}</ship>')).toThrow(
        /malformed decision gate/,
      );
    });
    it("escalate with non-string reason throws", () => {
      expect(() =>
        parseShipOutcome('<ship>{"escalate": {"reason": 123, "diagnosis": "x"}}</ship>'),
      ).toThrow(/malformed decision gate/);
    });
    it("escalate missing diagnosis throws", () => {
      expect(() =>
        parseShipOutcome('<ship>{"escalate": {"reason": "stuck"}}</ship>'),
      ).toThrow(/malformed decision gate/);
    });
    it("escalate with empty-string fields throws", () => {
      expect(() =>
        parseShipOutcome('<ship>{"escalate": {"reason": "", "diagnosis": "   "}}</ship>'),
      ).toThrow(/malformed decision gate/);
    });
  });

  // F3 — a MIXED payload (a success shape carrying an extra verdict key) was落到 the
  // success branch because the old guard only checked `typeof escalate === "object"`:
  // a non-object `failed`/`escalate` (a string) was skipped, and an extra verdict key
  // alongside a valid success was simply ignored → a "failed" run read as shipped.
  // `.strict()` rejects any object carrying keys outside the matched shape.
  describe("unknown ship receipt fields remain cargo", () => {
    it('pr_opened carrying a `failed` string key remains shipped', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pr_opened", "branch": "b", "pr": "u", "failed": "tests red"}</ship>',
        ).kind,
      ).toBe("shipped");
    });
    it('pr_opened carrying a malformed `escalate` string key fails the Action', () => {
      // #899: present-but-malformed escalate is never silent cargo — Action fails
      // for #598 rather than shipping with a half-pressed gate.
      expect(() =>
        parseShipOutcome(
          '<ship>{"status": "pr_opened", "branch": "b", "pr": "u", "escalate": "stuck"}</ship>',
        ),
      ).toThrow(/malformed decision gate/);
    });
    it('pushed carrying a `pr` key remains pushed cargo', () => {
      expect(
        parseShipOutcome('<ship>{"status": "pushed", "branch": "b", "pr": "u"}</ship>').kind,
      ).toBe("shipped");
    });
    it('pushed carrying an extra `failed` key remains pushed cargo', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pushed", "branch": "b", "failed": {"reason": "x", "diagnosis": "y"}}</ship>',
        ).kind,
      ).toBe("shipped");
    });
    it('a success shape with an arbitrary extra key remains shipped cargo', () => {
      expect(
        parseShipOutcome(
          '<ship>{"status": "pushed", "branch": "b", "junk": 1}</ship>',
        ).kind,
      ).toBe("shipped");
    });
    it('an escalate object with an extra key still rings the decision bell', () => {
      expect(
        parseShipOutcome(
          '<ship>{"escalate": {"reason": "r", "diagnosis": "d", "extra": 1}}</ship>',
        ).kind,
      ).toBe("escalate");
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

    expect(o.kind).toBe("completed");
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

    expect(o).toEqual({ kind: "completed" });
  });

  it("keeps malformed sidecar text as non-fateful cargo without promoting stdout", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("does not let stdout decision bells override non-bell sidecar cargo", () => {
    // #899: decision gates come only from Output.object / machine sidecar payload,
    // never from a stdout compatibility tag that bypasses schema validation.
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-bell-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, JSON.stringify({ unrelatedCargo: true }), "utf8");

    const o = shipOutcomeFromResult({
      stdout: '<ship>{"junk": true, "escalate": {"reason": "owner choice", "diagnosis": "ship fork"}}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("does not let sidecar bells override a schema-validated typed ship receipt", () => {
    // #899: when typed Output.object exists it is the sole fate channel.
    const dir = mkdtempSync(join(tmpdir(), "ship-typed-vs-sidecar-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        escalate: { reason: "sidecar spoof", diagnosis: "must not win" },
      }),
      "utf8",
    );

    expect(
      shipOutcomeFromResult({
        output: { status: "pushed", branch: "feat/typed-wins" },
        outcomePath,
        stdout: "",
      }),
    ).toEqual({
      kind: "shipped",
      status: "pushed",
      branch: "feat/typed-wins",
    });
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

    expect(o.kind).toBe("completed");
  });

  it("never falls back to signaled ship stdout when no outcome sidecar path exists", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
    });

    expect(o.kind).toBe("completed");
  });

  it("ignores non-bell sidecar parse failure independently of the obsolete completion signal", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-unsignaled-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const o = shipOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("a signaled stdout-only delivery report remains untrusted cargo", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("completed");
  });

  it("an unsignaled stdout-only delivery report is cargo, not a decision bell", () => {
    const o = shipOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("completed");
  });

  it("a wrong-signal stdout-only delivery report is cargo, not a decision bell", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("completed");
  });

  it("a signal alone is not a machine outcome", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SHIP_STEP_COMPLETE",
      stdout: "no tag here",
    });
    expect(o.kind).toBe("completed");
  });
});
