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

import { describe, expect, it } from "vitest";

import {
  parseShipOutcome,
  shipOutcomeFromResult,
  SHIP_COMPLETION_SIGNAL,
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

  it("a shipped object with no branch ⇒ malformed (a PR with no branch is unusable)", () => {
    expect(parseShipOutcome('<ship>{"status": "pr_opened", "pr": "u"}</ship>').kind).toBe(
      "malformed",
    );
  });

  it("a <ship> object with no status, escalate or failed ⇒ malformed", () => {
    expect(parseShipOutcome('<ship>{"foo": 1}</ship>').kind).toBe("malformed");
  });
});

// ═══════════════════ shipOutcomeFromResult (completion-signal gate) ═══════════════════

describe("#336 shipOutcomeFromResult — completion-signal gate (mirrors the cmr/merger gate)", () => {
  it("a signaled shipped run ⇒ a shipped outcome", () => {
    const o = shipOutcomeFromResult({
      completionSignal: SHIP_COMPLETION_SIGNAL,
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("shipped");
  });

  it("an UNSIGNALED run ⇒ escalate (a complete-but-unsignaled run is NOT a success)", () => {
    const o = shipOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("escalate");
  });

  it("a wrong-signal run ⇒ escalate", () => {
    const o = shipOutcomeFromResult({
      completionSignal: "SOME_OTHER_SIGNAL",
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("escalate");
  });

  it("a signaled but malformed run ⇒ malformed (signal alone is not a success)", () => {
    const o = shipOutcomeFromResult({
      completionSignal: SHIP_COMPLETION_SIGNAL,
      stdout: "no tag here",
    });
    expect(o.kind).toBe("malformed");
  });
});
