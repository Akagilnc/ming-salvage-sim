/**
 * family-ledger — append-only merged-child event ledger (ADR 0022 decision 5,
 * #293 seam 3).
 *
 * #293 records the thinnest entry `{childIssue, status:"merged"}` per merged
 * child, appended through the {@link FamilyBackend} seam (the real impl writes a
 * sibling file OUTSIDE the family base worktree). This module owns:
 *   - `recordMerged(backend, childIssue)` — append one merged event;
 *   - `mergedSet(entries)` — derive the set of merged child issue numbers the
 *     commander's unblock predicate (ADR 0022 decision 6②) reads.
 *
 * #298 extends the ENTRY schema + adds reconcile by growing THIS module, not the
 * spine — the spine only calls recordMerged / mergedSet.
 */

import { describe, expect, it } from "vitest";
import {
  cmrPassAlreadyPassed,
  familyAlreadyShipped,
  familyShippedRecordForReviewLoopResume,
  familyEscalationState,
  hasBoundShippedMarker,
  hasUnboundLegacyShippedMarker,
  mergedSet,
  recordAdmissionSkipped,
  recordCmrPassed,
  recordMerged,
  recordShipped,
} from "../../src/family/ledger.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../../src/family/types.js";

/** A zero-IO fake family backend that keeps the ledger in memory. */
class FakeFamilyBackend implements FamilyBackend {
  readonly appended: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "head" };
  }
  // #295 conflict-fallback seam `resolveMergeConflict` is OPTIONAL — this ledger
  // test never merges with a conflict, so the fake omits it entirely.
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("family-ledger.recordMerged (#293 seam 3)", () => {
  it("appends a thin {childIssue, status:'merged'} entry per merged child", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordMerged(backend, 11);
    expect(backend.appended).toEqual([
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged" },
    ]);
  });

  it("is append-only: a second record for the same child appends, never mutates", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordMerged(backend, 10);
    // Append-only — both events are retained (reconcile dedup is #298, not #293).
    expect(backend.appended).toHaveLength(2);
    expect(backend.appended.every((e) => e.childIssue === 10)).toBe(true);
  });
});

describe("family-ledger.recordAdmissionSkipped", () => {
  it("appends durable admission-skip audit rows without marking the child merged", async () => {
    const backend = new FakeFamilyBackend();

    await recordAdmissionSkipped(backend, {
      issue: 12,
      reason: "not_ready_for_agent",
      message: "family admission skipped child #12: missing ready-for-agent label",
    });

    expect(backend.appended).toMatchObject([
      {
        childIssue: 12,
        status: "admission_skipped",
        event: "admission_skipped",
        phase: "wave",
        reason: "not_ready_for_agent",
        message: "family admission skipped child #12: missing ready-for-agent label",
        stopSummary: {
          reason: "success",
          metadata: {
            admissionSkipped: [
              {
                issue: 12,
                reason: "not_ready_for_agent",
                message:
                  "family admission skipped child #12: missing ready-for-agent label",
              },
            ],
          },
        },
      },
    ]);
    expect(mergedSet(backend.appended)).toEqual(new Set());
  });
});

describe("family-ledger.recordShipped / familyAlreadyShipped (online review r2/r3, codex P1)", () => {
  it("recordShipped appends the terminal marker with the shipped family HEAD", async () => {
    const backend = new FakeFamilyBackend();
    await recordShipped(backend, { pr: "https://gh/pr/352", familyHeadAfter: "head-1" });
    expect(backend.appended).toMatchObject([
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "https://gh/pr/352",
        familyHeadAfter: "head-1",
        stopSummary: { reason: "success" },
      },
    ]);
    expect(backend.appended[0]?.ts).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("recordShipped rejects blank PR/head values before appending", async () => {
    const backend = new FakeFamilyBackend();

    await expect(
      recordShipped(backend, { pr: "   ", familyHeadAfter: "head-1" }),
    ).rejects.toThrow("family shipped marker must include a non-empty PR URL");
    await expect(
      recordShipped(backend, { pr: "https://gh/pr/352", familyHeadAfter: "   " }),
    ).rejects.toThrow("family shipped marker must include a non-empty familyHeadAfter");

    expect(backend.appended).toEqual([]);
  });

  it("familyAlreadyShipped is TRUE only for the complete shipped marker matching the current head", () => {
    expect(
      familyAlreadyShipped([
        { childIssue: 1, status: "merged" },
        {
          status: "shipped",
          event: "shipped",
          phase: "final",
          pr: "https://gh/pr/352",
          familyHeadAfter: "head-1",
        },
      ], "head-1"),
    ).toBe(true);
    expect(
      familyAlreadyShipped([
        {
          status: "shipped",
          event: "shipped",
          phase: "final",
          pr: "https://gh/pr/352",
          familyHeadAfter: "head-1",
        },
      ], "head-2"),
    ).toBe(false);
  });

  it("familyAlreadyShipped FAILS CLOSED on a malformed shipped row (no skip on garbage, r3 coderabbit)", () => {
    // A corrupt/hand-edited row must NOT let the spine skip the final barrier.
    expect(familyAlreadyShipped([{ status: "shipped" } as FamilyLedgerEntry], "head-1")).toBe(false);
    expect(
      familyAlreadyShipped([{ status: "shipped", event: "shipped", phase: "final", pr: "  " }], "head-1"),
    ).toBe(false);
    expect(
      familyAlreadyShipped([{ status: "shipped", event: "shipped", phase: "wave", pr: "u" } as FamilyLedgerEntry], "head-1"),
    ).toBe(false);
    expect(
      familyAlreadyShipped([{ status: "shipped", event: "shipped", phase: "final", pr: "u" }], "head-1"),
    ).toBe(false);
    expect(
      hasUnboundLegacyShippedMarker([{ status: "shipped", event: "shipped", phase: "final", pr: "u" }]),
    ).toBe(true);
    expect(
      hasUnboundLegacyShippedMarker([
        {
          status: "shipped",
          event: "shipped",
          phase: "final",
          pr: "u",
          familyHeadAfter: 123,
        } as unknown as FamilyLedgerEntry,
      ]),
    ).toBe(true);
    expect(
      hasBoundShippedMarker([
        {
          status: "shipped",
          event: "shipped",
          phase: "final",
          pr: "u",
          familyHeadAfter: "head-1",
        },
      ]),
    ).toBe(true);
  });

  it("pin r28: familyShippedRecordForReviewLoopResume crash-point matrix (family)", () => {
    const shipHead = "head-ship";
    const postFixHead = "head-postfix";
    const pr = "https://gh/pr/352";
    const shipped = {
      status: "shipped" as const,
      event: "shipped" as const,
      phase: "final" as const,
      pr,
      familyHeadAfter: shipHead,
    };
    const fixCommitted = {
      status: "online_review_fix_committed" as const,
      event: "online_review_fix_committed" as const,
      phase: "final" as const,
      familyHeadAfter: postFixHead,
      pr,
    };
    const retrigger = {
      status: "online_review_round_retrigger" as const,
      event: "online_review_round_retrigger" as const,
      phase: "final" as const,
      roundTriggerHeadOid: postFixHead,
      roundTriggerAt: "2026-07-08T13:00:00.000Z",
      onlineReviewRound: 2,
      pr,
    };
    const mergedOnly = [{ childIssue: 1, status: "merged" as const }];
    // crash before shipped → no resume anchor
    expect(
      familyShippedRecordForReviewLoopResume(
        [...mergedOnly, fixCommitted],
        postFixHead,
      ),
    ).toBeUndefined();
    // shipped only at ancestor, current head advanced, no markers → no loop resume
    expect(
      familyShippedRecordForReviewLoopResume(
        [...mergedOnly, shipped],
        postFixHead,
      ),
    ).toBeUndefined();
    // crash after fix_committed only → ancestor shipped + markers resume
    expect(
      familyShippedRecordForReviewLoopResume(
        [...mergedOnly, shipped, fixCommitted],
        postFixHead,
      ),
    ).toEqual({ pr, familyHeadAfter: shipHead });
    // crash after retrigger (fix_committed pending) → still resume
    expect(
      familyShippedRecordForReviewLoopResume(
        [...mergedOnly, shipped, retrigger],
        postFixHead,
      ),
    ).toEqual({ pr, familyHeadAfter: shipHead });
    // exact head match unchanged
    expect(
      familyShippedRecordForReviewLoopResume(
        [...mergedOnly, shipped],
        shipHead,
      )?.familyHeadAfter,
    ).toBe(shipHead);
  });

  it("familyShippedRecordForReviewLoopResume accepts ancestor shipped + in-loop markers (#600 r28)", () => {
    const shipHead = "head-ship";
    const postFixHead = "head-postfix";
    const pr = "https://gh/pr/352";
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 1, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr,
        familyHeadAfter: shipHead,
      },
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        phase: "final",
        familyHeadAfter: postFixHead,
        pr,
      },
    ];
    expect(familyShippedRecordForReviewLoopResume(ledger, postFixHead)).toEqual({
      pr,
      familyHeadAfter: shipHead,
    });
    expect(familyShippedRecordForReviewLoopResume(ledger, shipHead)?.familyHeadAfter).toBe(
      shipHead,
    );
    expect(familyShippedRecordForReviewLoopResume(ledger, "other-head")).toBeUndefined();
  });

  it("familyAlreadyShipped is FALSE for a ledger with only merged/aborted entries", () => {
    expect(
      familyAlreadyShipped([
        { childIssue: 1, status: "merged" },
        { status: "aborted", event: "aborted", phase: "final", reason: "x" },
      ], "head-1"),
    ).toBe(false);
  });
});

describe("family-ledger.recordCmrPassed / cmrPassAlreadyPassed (#434 resume guard)", () => {
  it("recordCmrPassed appends the pass marker with the family HEAD it reviewed", async () => {
    const backend = new FakeFamilyBackend();
    await recordCmrPassed(backend, {
      cmrPass: "completeness",
      familyHeadAfter: "head-1",
      routeFingerprint: "route:v1",
    });
    expect(backend.appended).toMatchObject([
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: "route:v1",
        stopSummary: { reason: "success" },
      },
    ]);
  });

  it("cmrPassAlreadyPassed is TRUE only for the matching pass, current family HEAD, and route fingerprint", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: "route:v1",
      },
    ];
    expect(
      cmrPassAlreadyPassed(entries, {
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: "route:v1",
      }),
    ).toBe(true);
    expect(
      cmrPassAlreadyPassed(entries, {
        cmrPass: "correctness",
        familyHeadAfter: "head-1",
        routeFingerprint: "route:v1",
      }),
    ).toBe(false);
    expect(
      cmrPassAlreadyPassed(entries, {
        cmrPass: "completeness",
        familyHeadAfter: "head-2",
        routeFingerprint: "route:v1",
      }),
    ).toBe(false);
    expect(
      cmrPassAlreadyPassed(entries, {
        cmrPass: "completeness",
        familyHeadAfter: "head-1",
        routeFingerprint: "route:v2",
      }),
    ).toBe(false);
  });

  it("cmrPassAlreadyPassed FAILS CLOSED on malformed, headless, or route-less rows", () => {
    expect(
      cmrPassAlreadyPassed(
        [{ status: "cmr_passed", cmrPass: "completeness" } as FamilyLedgerEntry],
        { cmrPass: "completeness", familyHeadAfter: "head-1", routeFingerprint: "route:v1" },
      ),
    ).toBe(false);
    expect(
      cmrPassAlreadyPassed(
        [
          {
            status: "cmr_passed",
            event: "cmr_passed",
            phase: "final",
            cmrPass: "completeness",
          },
        ],
        { cmrPass: "completeness", familyHeadAfter: "head-1", routeFingerprint: "route:v1" },
      ),
    ).toBe(false);
    expect(
      cmrPassAlreadyPassed(
        [
          {
            status: "cmr_passed",
            event: "cmr_passed",
            phase: "final",
            cmrPass: "completeness",
            familyHeadAfter: "head-1",
          },
        ],
        { cmrPass: "completeness", routeFingerprint: "route:v1" },
      ),
    ).toBe(false);
    expect(
      cmrPassAlreadyPassed(
        [
          {
            status: "cmr_passed",
            event: "cmr_passed",
            phase: "final",
            cmrPass: "completeness",
            familyHeadAfter: "head-1",
          },
        ],
        { cmrPass: "completeness", familyHeadAfter: "head-1", routeFingerprint: "route:v1" },
      ),
    ).toBe(false);
  });
});

describe("family-ledger.familyEscalationState", () => {
  it("accepts legacy escalation_answered rows without source as human answers", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "needs human decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "Continue the family flow.",
      },
    ];

    expect(familyEscalationState(entries)?.answer).toEqual({
      event: "escalation_answered",
      answer: "Continue the family flow.",
      source: "human",
    });
  });

  // #604 correctness r1 (P1-f): a CHILD-bound answer row (carrying `childIssue`)
  // must NOT release an unrelated FAMILY-level decision escalation. The family
  // escalation is the `event:"escalated"` row that carries NO childIssue; a
  // family-level answer must therefore also carry no childIssue.
  it("does not release a family-level escalation with a CHILD-bound answer row", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "family-level design decision needs a human",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        childIssue: 11,
        answer: "field X is optional; proceed",
        source: "human",
      } as FamilyLedgerEntry,
    ];

    // The child-bound answer must not count as the family answer: the family
    // escalation is returned WITHOUT an answer (still parked).
    const state = familyEscalationState(entries);
    expect(state).toBeDefined();
    expect(state?.answer).toBeUndefined();
  });

  it("still releases a family-level escalation with an UNBOUND (no childIssue) answer row", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        escalationKind: "decision",
        reason: "family-level design decision needs a human",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "proceed with the family flow",
        source: "human",
      },
    ];

    expect(familyEscalationState(entries)?.answer).toEqual({
      event: "escalation_answered",
      answer: "proceed with the family flow",
      source: "human",
    });
  });
});

describe("family-ledger.mergedSet (#293 seam 3)", () => {
  it("derives the set of merged child issue numbers", () => {
    const entries: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged" },
    ];
    const set = mergedSet(entries);
    expect(set.has(10)).toBe(true);
    expect(set.has(11)).toBe(true);
    expect(set.has(12)).toBe(false);
  });

  it("an empty ledger yields an empty merged set", () => {
    expect(mergedSet([]).size).toBe(0);
  });
});
