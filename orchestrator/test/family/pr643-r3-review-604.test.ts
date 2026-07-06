/**
 * PR #643 R3 bot-review round (#604 Layer 3).
 *
 * Gemini R3 flagged the SAME null-tolerance class it raised in R1, now spread
 * across the runner + verifyCmr ledger scanners: optional ARRAY carrier fields
 * (`blockingFindingIdentityKeys`, `cmrDispositions`) were guarded with strict
 * `=== undefined` / `!== undefined` before a `.length` access. A durable JSONL
 * row that serialized an absent field as `null` (rather than omitting it) slips
 * past the strict guard and throws `TypeError: Cannot read properties of null
 * (reading 'length')`. This is R3, so the whole class is swept CLOSED in one
 * pass (`== null` / `!= null`) instead of chased file-by-file across more rounds.
 *
 * (Gemini's CRITICAL "pass is not defined" claim on runner.ts:537 was a false
 * positive — `pass` is declared at runner.ts:546 before use, and tsc is clean —
 * so it is rejected, not fixed.)
 */

import { describe, expect, it } from "vitest";
import { pendingPriorCmrFindingIdentityKeysByPass } from "../../src/family/runner.js";
import { latestFamilyCmrDispositions } from "../../src/family/verifyCmr.js";
import type { FamilyLedgerEntry } from "../../src/family/types.js";

describe("PR#643 R3 (Gemini) — ledger scanners tolerate a null optional array field", () => {
  it("pendingPriorCmrFindingIdentityKeysByPass: an aborted row with null blockingFindingIdentityKeys does not throw", () => {
    const ledger = [
      {
        status: "aborted",
        event: "aborted",
        phase: "final",
        cmrPass: "correctness",
        // A JSONL round-trip serialized the absent envelope as null.
        blockingFindingIdentityKeys: null,
      } as unknown as FamilyLedgerEntry,
    ];
    // Before the fix this threw `TypeError: ... reading 'length'` at the
    // classified-abort `.length` check; now the null row is treated as an
    // UNCLASSIFIED abort (no envelope) and yields no pending keys.
    const result = pendingPriorCmrFindingIdentityKeysByPass(ledger);
    expect(result.correctness).toBeUndefined();
  });

  it("pendingPriorCmrFindingIdentityKeysByPass: a cmr_fix_committed row with null keys does not throw", () => {
    const ledger = [
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        phase: "final",
        cmrPass: "correctness",
        blockingFindingIdentityKeys: null,
      } as unknown as FamilyLedgerEntry,
    ];
    const result = pendingPriorCmrFindingIdentityKeysByPass(ledger);
    expect(result.correctness).toBeUndefined();
  });

  it("latestFamilyCmrDispositions: a row with null cmrDispositions is skipped, not a throw", () => {
    const ledger = [
      { cmrDispositions: null } as unknown as {
        readonly cmrDispositions?: null;
      },
    ];
    // Before the fix `entry.cmrDispositions !== undefined` was true for null →
    // `null.length` threw. Now `!= null` skips it and returns undefined.
    expect(latestFamilyCmrDispositions(ledger as never)).toBeUndefined();
  });
});
