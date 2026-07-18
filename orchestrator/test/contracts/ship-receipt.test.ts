/**
 * #336 / #919 — family ship step is a WORKER that invokes `gstack-ship`.
 *
 * Production fate is T2 ship station receipt only ({@link shipOutcomeFromResult}
 * + decodeShipEnvelope). Stdout/sidecar enrich delivery cargo; escalate rides
 * the typed envelope (`status:"escalate"`). The parseShipOutcome dual that
 * probed classifyDecisionGate was DELETED (#919 CR N1).
 */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { shipOutcomeFromResult } from "../../src/shipOutcome.js";

// ═══════════════════ shipOutcomeFromResult (T2 + machine sidecar) ═══════════════════

describe("#820 / #919 shipOutcomeFromResult — T2 envelope + machine sidecar", () => {
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
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("does not let stdout decision bells override non-bell sidecar cargo", () => {
    // #899: decision gates come only from Output.object, never from a stdout
    // compatibility tag that bypasses schema validation.
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
    // #899: typed decision signal is the sole fate channel. A no-gate typed
    // signal blocks sidecar escalate; delivery cargo still enriches.
    const dir = mkdtempSync(join(tmpdir(), "ship-typed-vs-sidecar-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        status: "pushed",
        branch: "feat/typed-wins",
        escalate: { reason: "sidecar spoof", diagnosis: "must not win" },
      }),
      "utf8",
    );

    expect(
      shipOutcomeFromResult({
        output: { station: "ship", status: "completed" },
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
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("never falls back to signaled ship stdout when no outcome sidecar path exists", () => {
    const o = shipOutcomeFromResult({
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
    });

    expect(o.kind).toBe("completed");
  });

  it("ignores non-bell sidecar parse failure; completion is exit + legal envelope", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-outcome-bad-unsignaled-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const o = shipOutcomeFromResult({
      stdout: '<ship>{"status": "pushed", "branch": "feat/fallback"}</ship>',
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("a signaled stdout-only delivery report remains untrusted cargo", () => {
    const o = shipOutcomeFromResult({
      stdout: '<ship>{"status": "pr_opened", "branch": "b", "pr": "u"}</ship>',
    });
    expect(o.kind).toBe("completed");
  });

  it("does not admit a sidecar decision bell into fate when typed output is absent", () => {
    // #899: escalate is a typed-only fate signal; sidecar is delivery cargo only.
    const dir = mkdtempSync(join(tmpdir(), "ship-sidecar-bell-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        escalate: { reason: "owner choice", diagnosis: "must not park from cargo" },
      }),
      "utf8",
    );

    const o = shipOutcomeFromResult({
      stdout: "",
      outcomePath,
    });

    expect(o.kind).toBe("completed");
  });

  it("sidecar pr_opened without pr stays shipped delivery cargo", () => {
    // #899: do not discard incomplete pr_opened for a missing pr URL.
    const dir = mkdtempSync(join(tmpdir(), "ship-pr-opened-no-pr-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ status: "pr_opened", branch: "feat/opaque" }),
      "utf8",
    );

    expect(
      shipOutcomeFromResult({
        output: { station: "ship", status: "completed" },
        outcomePath,
        stdout: "",
      }),
    ).toEqual({
      kind: "shipped",
      status: "pr_opened",
      branch: "feat/opaque",
    });
  });

  it("transports free-form status and branch without a closed status court", () => {
    // #899: ordinary ship cargo stays opaque — no whitelist on status tokens.
    const dir = mkdtempSync(join(tmpdir(), "ship-freeform-status-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        status: "already_open",
        branch: "feat/freeform",
        pr: "https://gh/pr/99",
        extra: "kept-out-of-fate",
      }),
      "utf8",
    );

    expect(
      shipOutcomeFromResult({
        output: { station: "ship", status: "completed" },
        outcomePath,
        stdout: "",
      }),
    ).toEqual({
      kind: "shipped",
      status: "already_open",
      branch: "feat/freeform",
      pr: "https://gh/pr/99",
    });
  });

  it("branch/pr alone still enrich delivery without inventing a status token", () => {
    // #899: opaque cargo — missing status stays missing; never synthesize.
    const dir = mkdtempSync(join(tmpdir(), "ship-branch-only-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ branch: "feat/branch-only", pr: "https://gh/pr/1" }),
      "utf8",
    );

    expect(
      shipOutcomeFromResult({
        output: { station: "ship", status: "completed" },
        outcomePath,
        stdout: "",
      }),
    ).toEqual({
      kind: "shipped",
      branch: "feat/branch-only",
      pr: "https://gh/pr/1",
    });
  });

  it("illegal non-T2 typed output fails closed (no decision-gate dual)", () => {
    // #919 CR N1: production decode miss must not fall through classifyDecisionGate.
    expect(() =>
      shipOutcomeFromResult({
        output: {},
        stdout: "",
      }),
    ).toThrow(/illegal ship station receipt/);
    expect(() =>
      shipOutcomeFromResult({
        output: { escalate: { reason: "legacy", diagnosis: "dual" } },
        stdout: "",
      }),
    ).toThrow(/illegal ship station receipt/);
  });

  it("T2 ship escalate parks via status:escalate (not nested escalate dual)", () => {
    const o = shipOutcomeFromResult({
      output: {
        station: "ship",
        status: "escalate",
        reason: "merge conflict",
        diagnosis: "cannot auto-resolve base merge",
      },
      stdout: "",
    });
    expect(o).toEqual({
      kind: "escalate",
      reason: "merge conflict",
      diagnosis: "cannot auto-resolve base merge",
    });
  });

  it("T2 ship shipped status promotes delivery cargo from sidecar", () => {
    const dir = mkdtempSync(join(tmpdir(), "ship-t2-shipped-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        status: "pr_opened",
        branch: "feat/x",
        pr: "https://gh/pr/1",
      }) + "\n",
      "utf8",
    );
    const o = shipOutcomeFromResult({
      output: { station: "ship", status: "shipped" },
      outcomePath,
      stdout: "",
    });
    expect(o).toEqual({
      kind: "shipped",
      status: "pr_opened",
      branch: "feat/x",
      pr: "https://gh/pr/1",
    });
  });

  it("T2 ship shipped without cargo is bare shipped", () => {
    expect(
      shipOutcomeFromResult({
        output: { station: "ship", status: "shipped" },
        stdout: "",
      }),
    ).toEqual({ kind: "shipped" });
  });

  it("a signal alone is not a machine outcome", () => {
    const o = shipOutcomeFromResult({
      stdout: "no tag here",
    });
    expect(o.kind).toBe("completed");
  });
});
