/**
 * integ-cmr 256 r5 — corrupt-ledger fail-closed (high).
 *
 * The persisted JSONL ledger is the #244 resume truth. The old `readLedger`
 * silently SKIPPED any non-empty line that failed `JSON.parse` (a
 * truncation-recovery with no explicit, tested rule). Two logic-visible
 * mis-recoveries followed:
 *
 *   (A) A corrupted tagged S8(error) line being skipped left S7 as the surviving
 *       last entry → planResume Case 3b/4 routes S7→{handoff,success} → an actual
 *       ERROR run is re-reported as SUCCESS (a wrong terminal-state rebuild).
 *
 *   (B) ALL lines corrupted made readLedger return `[]` (empty ledger) instead of
 *       `undefined`. `findResumeState`'s `if (ledger === undefined) return` no
 *       longer fired, `lastLedgerBranchHead([])` = undefined bypassed the codex#2
 *       HEAD-consistency check ({ok:true}, nothing to contradict), and planResume
 *       Case 1 ran it as fresh-from-S0 — over a RESIDENT branch that prepareWorktree
 *       reuses WITH prior commits. A corrupt ledger got silently reinterpreted as
 *       "no progress" instead of failing open/closed.
 *
 * Fix (fail closed, mirroring r2 F2 "completeness failure must not be a lenient
 * default"): any non-empty JSONL line that does not parse means the ledger is
 * CORRUPT — throw, so findResumeState bails to the same S8(error) path as the
 * codex#2 HEAD-mismatch. The rule is pinned here so the truncation-recovery
 * boundary (blank-line tolerance only, never terminal-state / branch-progress
 * drift) is a tested invariant, not an implicit one.
 */

import { describe, expect, it } from "vitest";
import { parseLedgerJsonl } from "../src/realBackend.js";

describe("parseLedgerJsonl — corrupt-line fail-closed (256 r5)", () => {
  const goodLine = (step: string) =>
    JSON.stringify({ step, branchHEAD: "a".repeat(40), ts: "t", sessionId: "s", prompt_hash: "h" });

  it("parses a well-formed JSONL ledger in order", () => {
    const raw = [goodLine("S0"), goodLine("S1"), goodLine("S7")].join("\n");
    const entries = parseLedgerJsonl(raw);
    expect(entries.map((e) => e.step)).toEqual(["S0", "S1", "S7"]);
  });

  it("tolerates blank / whitespace-only lines (truncation-recovery boundary)", () => {
    // Trailing newline, an interior blank line, and a whitespace-only line are
    // NOT corruption — they carry no record and are skipped without error.
    const raw = ["", goodLine("S0"), "   ", goodLine("S1"), "\t", ""].join("\n");
    const entries = parseLedgerJsonl(raw);
    expect(entries.map((e) => e.step)).toEqual(["S0", "S1"]);
  });

  it("an empty / all-blank file is a legitimately EMPTY ledger (not corrupt)", () => {
    // Distinct from corruption: a file with no records is the documented
    // empty-ledger case (ResumeState.ledger = [] ⇒ fresh run). It must NOT throw.
    expect(parseLedgerJsonl("")).toEqual([]);
    expect(parseLedgerJsonl("\n\n  \n\t\n")).toEqual([]);
  });

  it("(A) a single corrupt non-empty line throws (no silent skip → no terminal-state drift)", () => {
    // The corrupt line is what would have been the tagged S8(error). Skipping it
    // would leave S7 last and re-report ERROR as SUCCESS — so this must throw.
    const raw = [goodLine("S0"), goodLine("S7"), "{not json — truncated S8"].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("(B) ALL lines corrupt throws (never collapses to an empty/fresh ledger)", () => {
    const raw = ["{bad", "also bad}", "]["].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("a corrupt line anywhere (even first) throws — order does not matter", () => {
    const raw = ["@@@", goodLine("S0"), goodLine("S1")].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  // ── shape validation (online codex P2): a line can JSON.parse yet not be a
  // valid ledger entry. `planResume` dereferences `lastEntry.step` OUTSIDE any
  // catch, so a `null` / `{}` / wrong-typed `step` would crash raw or route
  // invalidly instead of failing closed to S8(error). Same corruption class as
  // an unparseable line → same throw.
  it("a syntactically-valid `null` record is corrupt (would crash lastEntry.step)", () => {
    const raw = [goodLine("S0"), "null"].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("a non-object JSON primitive is corrupt (number / string / boolean / array)", () => {
    for (const bad of ["42", '"S7"', "true", "[]", '["S7"]']) {
      const raw = [goodLine("S0"), bad].join("\n");
      expect(() => parseLedgerJsonl(raw), `bad=${bad}`).toThrow(/corrupt/i);
    }
  });

  it("an object missing `step` is corrupt (e.g. `{}` → lastEntry.step undefined)", () => {
    const raw = [goodLine("S0"), "{}"].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("an object whose `step` is not a valid StepId is corrupt", () => {
    // A typo'd / out-of-range step would route invalidly in planResume.
    const raw = [goodLine("S0"), goodLine("S9"), goodLine("FOO")].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("an object whose `step` is a non-string is corrupt", () => {
    const raw = [goodLine("S0"), JSON.stringify({ step: 7 })].join("\n");
    expect(() => parseLedgerJsonl(raw)).toThrow(/corrupt/i);
  });

  it("a shape-valid entry with only the required `step` still parses (output optional)", () => {
    // The minimal LedgerEntry is `{step}` — output/handoffStatus are optional, so
    // a bare valid-step record must NOT be rejected.
    const raw = [JSON.stringify({ step: "S0" }), JSON.stringify({ step: "S8" })].join("\n");
    const entries = parseLedgerJsonl(raw);
    expect(entries.map((e) => e.step)).toEqual(["S0", "S8"]);
  });
});
