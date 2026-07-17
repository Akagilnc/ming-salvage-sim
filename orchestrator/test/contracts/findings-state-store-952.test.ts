/**
 * #952 — findings state store: internal terminal `suppressed` + write-point
 * transition validation (ADR 0129).
 *
 * Seams:
 * 1. status vocabulary single source (includes suppressed)
 * 2. write-point transition validation
 * 3. open-for-fixer predicate (only unrepaired/open)
 */

import { describe, expect, it } from "vitest";

import {
  FINDING_STORE_STATUSES,
  isOpenForFixer,
  recordFindingStoreFlip,
  validateFindingStoreTransition,
} from "../../src/findingsStateStore.js";

describe("#952 findings state store statuses", () => {
  it("includes suppressed as an internal terminal (positive)", () => {
    expect(FINDING_STORE_STATUSES).toContain("suppressed");
    expect(FINDING_STORE_STATUSES).toContain("refuted");
    // Two-seam vocabulary: CMR governance carrier stays distinct (4b).
    expect(FINDING_STORE_STATUSES).toContain("accepted_suppressed");
  });

  it("only unrepaired is open for fixer (positive + negative)", () => {
    expect(isOpenForFixer("unrepaired")).toBe(true);
    expect(isOpenForFixer("suppressed")).toBe(false);
    expect(isOpenForFixer("refuted")).toBe(false);
    expect(isOpenForFixer("accepted_suppressed")).toBe(false);
    expect(isOpenForFixer("wont_fix")).toBe(false);
    expect(isOpenForFixer("rejected")).toBe(false);
  });
});

describe("#952 findings state store transitions at write point", () => {
  it("allows open/absent → suppressed (positive)", () => {
    expect(validateFindingStoreTransition(undefined, "suppressed")).toEqual({
      ok: true,
      value: true,
    });
    expect(validateFindingStoreTransition("unrepaired", "suppressed")).toEqual({
      ok: true,
      value: true,
    });
  });

  it("allows open/absent → refuted (positive, existing kill path)", () => {
    expect(validateFindingStoreTransition("unrepaired", "refuted").ok).toBe(true);
    expect(validateFindingStoreTransition(undefined, "refuted").ok).toBe(true);
  });

  it("rejects terminal → suppressed re-flip (negative)", () => {
    for (const from of [
      "suppressed",
      "refuted",
      "accepted_suppressed",
      "wont_fix",
      "rejected",
    ] as const) {
      const result = validateFindingStoreTransition(from, "suppressed");
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.reason).toMatch(/transition|terminal|illegal/i);
      }
    }
  });

  it("recordFindingStoreFlip persists suppressed and is queryable (positive)", () => {
    const written = recordFindingStoreFlip({
      identityKey: "cat|loc|claim",
      from: "unrepaired",
      to: "suppressed",
      reason: "owner deferred via ticket",
      severity: "medium",
      source: "groundTicket:949",
    });
    expect(written.ok).toBe(true);
    if (written.ok) {
      expect(written.value).toMatchObject({
        identityKey: "cat|loc|claim",
        status: "suppressed",
        reason: "owner deferred via ticket",
        source: "groundTicket:949",
      });
      expect(isOpenForFixer(written.value.status)).toBe(false);
    }
  });

  it("recordFindingStoreFlip rejects illegal terminal→suppressed (negative)", () => {
    const written = recordFindingStoreFlip({
      identityKey: "cat|loc|claim",
      from: "refuted",
      to: "suppressed",
      reason: "should fail",
      severity: "low",
    });
    expect(written.ok).toBe(false);
    if (!written.ok) {
      expect(written.reason).toMatch(/transition|terminal|illegal/i);
    }
  });
});
