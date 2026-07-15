/**
 * #921 — Judge verdict + full-wave station completion thin envelope contracts.
 *
 * Pure-function seams only (prefactor). Every positive case has a paired negative.
 * Bad shapes return `{ ok:false, reason }` — never throw bare exceptions.
 */

import { describe, expect, it } from "vitest";

import {
  LEGAL_REFUSE_REASONS,
  decodeCoderEnvelope,
  decodeJudgeVerdict,
  decodeShipEnvelope,
  decodeStationEnvelope,
  encodeCoderEnvelope,
  encodeJudgeVerdict,
  encodeShipEnvelope,
  parseFindingDisposition,
  parseLegalRefuseReason,
  type CoderStationEnvelope,
  type JudgeVerdict,
  type ShipStationEnvelope,
} from "../../src/stationReceiptContracts.js";

// ─── Seams ───────────────────────────────────────────────────────────────────
// 1. Judge verdict three-state encode/decode/validate
// 2. Finding disposition table (four legal reasons + evidence on kill rows)
// 3. Coder refuse envelope (refused + identity keys + cargo pointer; no cargo body)
// 4. Canonical refused* vocabulary (refuted* / dual fields rejected)
// 5. Full-wave thin envelopes (judge / coder / coderFix / familyCoderFix / ship)

describe("#921 judge verdict three-state", () => {
  it.each([
    ["converged"],
    ["continue"],
    ["escalate"],
  ] as const)("accepts status %s (positive)", (status) => {
    const raw =
      status === "continue"
        ? {
            station: "judge",
            status: "continue",
            findingDispositions: [],
          }
        : status === "escalate"
          ? {
              station: "judge",
              status: "escalate",
              reason: "stuck trend",
              diagnosis: "same disease N rounds",
            }
          : { station: "judge", status: "converged" };

    const parsed = decodeJudgeVerdict(raw);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value.status).toBe(status);
      expect(parsed.value.station).toBe("judge");
    }
  });

  it("rejects unknown status (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "maybe",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/status|converged|continue|escalate/i);
    }
  });

  it("rejects non-object input with readable reason (negative)", () => {
    const parsed = decodeJudgeVerdict(null);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason.length).toBeGreaterThan(0);
      expect(parsed.reason).not.toMatch(/^Error:/);
    }
  });

  it("does not throw on garbage input", () => {
    expect(() => decodeJudgeVerdict(undefined)).not.toThrow();
    expect(() => decodeJudgeVerdict(42)).not.toThrow();
    expect(() => decodeJudgeVerdict("converged")).not.toThrow();
    expect(() => decodeJudgeVerdict([])).not.toThrow();
  });

  it("continue may carry advanceCoder suggestion (positive)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      advanceCoder: "terra@med",
      findingDispositions: [],
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok && parsed.value.status === "continue") {
      expect(parsed.value.advanceCoder).toBe("terra@med");
    }
  });

  it("rejects empty advanceCoder string (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      advanceCoder: "   ",
      findingDispositions: [],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/advanceCoder/i);
    }
  });

  it("escalate requires non-empty reason + diagnosis (positive)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "escalate",
      reason: "design fork",
      diagnosis: "owner must choose",
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok && parsed.value.status === "escalate") {
      expect(parsed.value.reason).toBe("design fork");
      expect(parsed.value.diagnosis).toBe("owner must choose");
    }
  });

  it("rejects escalate missing diagnosis (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "escalate",
      reason: "stuck",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/diagnosis/i);
    }
  });

  it("round-trips encode → decode for continue with dispositions", () => {
    const verdict: JudgeVerdict = {
      station: "judge",
      status: "continue",
      advanceCoder: "sol@med",
      cargoPointer: "artifacts/judge-cargo-1.json",
      findingDispositions: [
        {
          identityKey: "correctness|src/a.ts:1|claim",
          action: "refute",
          reason: "unconstitutional",
          evidence: "conflicts with ADR 0131",
        },
        {
          identityKey: "correctness|src/b.ts:2|other",
          action: "live",
        },
      ],
    };
    const encoded = encodeJudgeVerdict(verdict);
    const decoded = decodeJudgeVerdict(encoded);
    expect(decoded).toEqual({ ok: true, value: verdict });
  });
});

describe("#921 finding disposition table (judge-side four reasons)", () => {
  it.each([...LEGAL_REFUSE_REASONS] as const)(
    "accepts kill row with reason %s + evidence (positive)",
    (reason) => {
      const parsed = parseFindingDisposition({
        identityKey: "cat|loc|claim",
        action: "refute",
        reason,
        evidence: `evidence for ${reason}`,
      });
      expect(parsed.ok).toBe(true);
      if (parsed.ok) {
        expect(parsed.value).toEqual({
          identityKey: "cat|loc|claim",
          action: "refute",
          reason,
          evidence: `evidence for ${reason}`,
        });
      }
    },
  );

  it("accepts live disposition without reason (positive)", () => {
    const parsed = parseFindingDisposition({
      identityKey: "cat|loc|claim",
      action: "live",
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value).toEqual({
        identityKey: "cat|loc|claim",
        action: "live",
      });
    }
  });

  it("rejects kill row with unknown reason (negative)", () => {
    const parsed = parseFindingDisposition({
      identityKey: "cat|loc|claim",
      action: "refute",
      reason: "too_hard",
      evidence: "hard is not a legal reason",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/reason|unconstitutional|over_defense|not_established|scope_creep/i);
    }
  });

  it("rejects kill row missing evidence (negative)", () => {
    const parsed = parseFindingDisposition({
      identityKey: "cat|loc|claim",
      action: "refute",
      reason: "not_established",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/evidence/i);
    }
  });

  it("rejects empty identityKey (negative)", () => {
    const parsed = parseFindingDisposition({
      identityKey: "  ",
      action: "live",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/identityKey/i);
    }
  });

  it("rejects live row that smuggles a reason field (negative)", () => {
    const parsed = parseFindingDisposition({
      identityKey: "cat|loc|claim",
      action: "live",
      reason: "unconstitutional",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/live|reason/i);
    }
  });

  it.each([...LEGAL_REFUSE_REASONS] as const)(
    "parseLegalRefuseReason accepts %s",
    (reason) => {
      expect(parseLegalRefuseReason(reason)).toEqual({ ok: true, value: reason });
    },
  );

  it("parseLegalRefuseReason rejects invent (negative)", () => {
    const parsed = parseLegalRefuseReason("difficult");
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/legal refuse reason/i);
    }
  });

  it("decodeJudgeVerdict rejects disposition with illegal reason (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      findingDispositions: [
        {
          identityKey: "k",
          action: "refute",
          reason: "owner_said_so",
          evidence: "nope",
        },
      ],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/reason|findingDispositions/i);
    }
  });
});

describe("#921 coder refuse envelope (envelope-level only)", () => {
  it("accepts refused + identity keys + cargo pointer (positive)", () => {
    const raw = {
      station: "coderFix",
      status: "refused",
      refusedFindingIdentityKeys: ["a|b|c", "d|e|f"],
      cargoPointer: "artifacts/refuse-cargo.json",
    };
    const parsed = decodeCoderEnvelope(raw);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value).toEqual({
        station: "coderFix",
        status: "refused",
        refusedFindingIdentityKeys: ["a|b|c", "d|e|f"],
        cargoPointer: "artifacts/refuse-cargo.json",
      });
    }
  });

  it("does not validate cargo body content even when present as sibling (positive opaque)", () => {
    // Cargo body may ride as opaque sibling keys under a pointer-only schema —
    // only traffic fields are validated. Extra cargo body keys are stripped, not rejected.
    const raw = {
      station: "coder",
      status: "refused",
      refusedFindingIdentityKeys: ["k1"],
      cargoPointer: "ptr://opaque",
      // These would be cargo body if read by the judge later; envelope must not schema-gate them.
      refuseRecords: [
        {
          identityKey: "k1",
          reason: "not_a_legal_reason_typo",
          evidence: "",
        },
      ],
      proseEssay: "whatever the coder wrote",
    };
    const parsed = decodeCoderEnvelope(raw);
    expect(parsed.ok).toBe(true);
    if (parsed.ok && parsed.value.status === "refused") {
      expect(parsed.value.refusedFindingIdentityKeys).toEqual(["k1"]);
      expect(parsed.value.cargoPointer).toBe("ptr://opaque");
      // envelope value must not surface cargo body fields
      expect(parsed.value).not.toHaveProperty("refuseRecords");
      expect(parsed.value).not.toHaveProperty("proseEssay");
    }
  });

  it("rejects refused without identity keys (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coderFix",
      status: "refused",
      cargoPointer: "ptr",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/refusedFindingIdentityKeys/i);
    }
  });

  it("rejects refused with empty identity key list (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coderFix",
      status: "refused",
      refusedFindingIdentityKeys: [],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/refusedFindingIdentityKeys/i);
    }
  });

  it("accepts completed coder envelope (positive)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coder",
      status: "completed",
      cargoPointer: "artifacts/coder-done.json",
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value.status).toBe("completed");
    }
  });

  it("rejects completed that carries refusedFindingIdentityKeys (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coder",
      status: "completed",
      refusedFindingIdentityKeys: ["k"],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/completed|refusedFindingIdentityKeys/i);
    }
  });

  it("round-trips encode → decode for refused", () => {
    const env: CoderStationEnvelope = {
      station: "familyCoderFix",
      status: "refused",
      refusedFindingIdentityKeys: ["id-1"],
      cargoPointer: "c.json",
    };
    expect(decodeCoderEnvelope(encodeCoderEnvelope(env))).toEqual({
      ok: true,
      value: env,
    });
  });
});

describe("#921 envelope field vocabulary — refused* only", () => {
  it("rejects refutedFindingIdentityKeys spelling (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coderFix",
      status: "refused",
      refutedFindingIdentityKeys: ["k"],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/refuted|refusedFindingIdentityKeys|canonical/i);
    }
  });

  it("rejects dual refused* + refuted* fields (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coderFix",
      status: "refused",
      refusedFindingIdentityKeys: ["k"],
      refutedFindingIdentityKeys: ["k"],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/refuted|dual|canonical|refused/i);
    }
  });

  it("rejects refuted* keys on judge envelopes too (negative)", () => {
    const parsed = decodeJudgeVerdict({
      station: "judge",
      status: "continue",
      findingDispositions: [],
      refutedFindingIdentityKeys: ["x"],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/refuted|canonical/i);
    }
  });

  it("rejects refuted status token as coder completion state (negative)", () => {
    const parsed = decodeCoderEnvelope({
      station: "coder",
      status: "refuted",
      refusedFindingIdentityKeys: ["k"],
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/status|refused|completed|escalate/i);
    }
  });
});

describe("#921 full-wave station thin envelopes", () => {
  it.each([
    ["judge", { station: "judge", status: "converged" }],
    ["coder", { station: "coder", status: "completed" }],
    ["coderFix", { station: "coderFix", status: "completed" }],
    ["familyCoderFix", { station: "familyCoderFix", status: "completed" }],
    [
      "ship",
      {
        station: "ship",
        status: "shipped",
        cargoPointer: "artifacts/ship.json",
      },
    ],
  ] as const)("accepts %s station envelope (positive)", (station, raw) => {
    const parsed = decodeStationEnvelope(raw);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value.station).toBe(station);
      expect(parsed.value.cargoPointer === undefined || typeof parsed.value.cargoPointer === "string").toBe(
        true,
      );
    }
  });

  it("rejects unknown station (negative)", () => {
    const parsed = decodeStationEnvelope({
      station: "merger",
      status: "completed",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/station/i);
    }
  });

  it("rejects empty cargoPointer when provided (negative)", () => {
    const parsed = decodeStationEnvelope({
      station: "ship",
      status: "completed",
      cargoPointer: "  ",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/cargoPointer/i);
    }
  });

  it("ship escalate requires reason+diagnosis (positive)", () => {
    const env: ShipStationEnvelope = {
      station: "ship",
      status: "escalate",
      reason: "merge conflict",
      diagnosis: "cannot auto-resolve",
    };
    expect(decodeShipEnvelope(encodeShipEnvelope(env))).toEqual({
      ok: true,
      value: env,
    });
  });

  it("rejects ship escalate without reason (negative)", () => {
    const parsed = decodeShipEnvelope({
      station: "ship",
      status: "escalate",
      diagnosis: "x",
    });
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) {
      expect(parsed.reason).toMatch(/reason/i);
    }
  });

  it("shared traffic fields are station + status + optional cargoPointer only", () => {
    // Document the thin envelope surface: no business cargo body required.
    const thin = {
      station: "coderFix" as const,
      status: "refused" as const,
      refusedFindingIdentityKeys: ["only-key"],
      // cargoPointer optional — refused keys alone are enough traffic
    };
    const parsed = decodeCoderEnvelope(thin);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      const keys = Object.keys(parsed.value).sort();
      expect(keys).toEqual(
        ["refusedFindingIdentityKeys", "station", "status"].sort(),
      );
    }
  });
});
