import { describe, expect, it } from "vitest";
import {
  AWAITING_CLOSED_REASON,
  FACE_GROUP,
  SETTLEMENT_CLOSED_REASON,
  WANG_AWAITING_SLIP,
  WANG_SETTLEMENT_SLIP,
  isFaceReachable,
  isSettlementDisplay,
  settlementClosedReason,
  settlementFaceAccess,
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
  wangSettlementSlipText,
  wangSettlementSlipVisible,
  yearMonthLabel,
  type FaceAccess,
  type SettlementFaceKey,
} from "./settlementPresentation";

describe("settlement presentation routing", () => {
  it("auto-opens only for a report produced by the just-settled month", () => {
    const orders = [{ dossier_progress: [{ turn: 4 }] }] as never;
    expect(shouldAutoOpenSecretOrdersAfterSettlement(orders, 5)).toBe(true);
    expect(shouldAutoOpenSecretOrdersAfterSettlement(orders, 6)).toBe(false);
    expect(shouldAutoOpenSecretOrdersAfterSettlement([{ status: "active" }] as never, 5)).toBe(false);
  });

  it("does not auto-open closed issue progress after settlement", () => {
    expect(shouldAutoOpenClosedIssuesAfterSettlement()).toBe(false);
  });

  it("#1234 year-month label is driven only by server settlement_display", () => {
    const base = { year: 1627, period: 10 };
    const plain = yearMonthLabel(base);
    expect(yearMonthLabel({ ...base, settlement_display: false })).toBe(plain);
    const marked = yearMonthLabel({ ...base, settlement_display: true });
    expect(marked).not.toBe(plain);
    expect(plain).toContain(String(base.year));
    expect(plain).toContain(String(base.period));
    expect(marked).toContain(String(base.year));
    expect(marked).toContain(String(base.period));
  });

  it("#1323 awaiting_decision 文案层：年月标按相位分叉；递话/关闭理由分口吻", () => {
    const base = { year: 1627, period: 10, settlement_display: true as const };
    const awaiting = yearMonthLabel({ ...base, phase: "awaiting_decision" });
    const settling = yearMonthLabel({ ...base, phase: "settling" });
    const plain = yearMonthLabel({ year: 1627, period: 10 });
    expect(awaiting).not.toBe(settling);
    expect(awaiting).not.toBe(plain);
    expect(settling).not.toBe(plain);
    expect(wangSettlementSlipText("awaiting_decision")).toBe(WANG_AWAITING_SLIP);
    expect(wangSettlementSlipText("settling")).toBe(WANG_SETTLEMENT_SLIP);
    expect(settlementClosedReason("awaiting_decision")).toBe(AWAITING_CLOSED_REASON);
    expect(settlementClosedReason("settling")).toBe(SETTLEMENT_CLOSED_REASON);
    expect(wangSettlementSlipText("awaiting_decision")).not.toBe(wangSettlementSlipText("settling"));
    expect(settlementClosedReason("awaiting_decision")).not.toBe(settlementClosedReason("settling"));
    expect(wangSettlementSlipVisible(true)).toBe(true);
    expect(wangSettlementSlipVisible(false)).toBe(false);
  });
});

/** 票面 r2 机械清单：关闭 / 只读 / 必达 / 呈现 / 排除（不缩表）。 */
const ROSTER: Record<Exclude<FaceAccess, "open">, SettlementFaceKey[]> = {
  closed: ["situation", "region", "army", "node_intel", "secret_orders", "edict", "chat_entry"],
  readonly: [
    "court_roster", "appointment_roster", "harem_roster", "building", "economy",
    "memorials", "gazette", "audience_archive", "history", "closed_issues", "legacies", "menu",
  ],
  must: ["decision_modal"],
  present: ["wang_slip"],
  excluded: ["cheat_console", "ending"],
};

describe("#1236 T3 settlement face gates (唯一谓词 settlement_display)", () => {
  it("mechanical roster covers every face key exactly once", () => {
    const listed = Object.values(ROSTER).flat();
    expect(new Set(listed).size).toBe(listed.length);
    expect(new Set(listed)).toEqual(new Set(Object.keys(FACE_GROUP)));
    for (const [group, keys] of Object.entries(ROSTER) as Array<[Exclude<FaceAccess, "open">, SettlementFaceKey[]]>) {
      for (const key of keys) expect(FACE_GROUP[key]).toBe(group);
    }
  });

  it("isSettlementDisplay reads only the server flag", () => {
    expect(isSettlementDisplay(undefined)).toBe(false);
    expect(isSettlementDisplay({})).toBe(false);
    expect(isSettlementDisplay({ settlement_display: false })).toBe(false);
    expect(isSettlementDisplay({ settlement_display: true })).toBe(true);
  });

  it("一开一关矩阵：非核账 open（excluded 除外）；核账返回组归属", () => {
    for (const [group, keys] of Object.entries(ROSTER) as Array<[Exclude<FaceAccess, "open">, SettlementFaceKey[]]>) {
      for (const key of keys) {
        if (group === "excluded") {
          expect(settlementFaceAccess(key, false)).toBe("excluded");
          expect(settlementFaceAccess(key, true)).toBe("excluded");
          expect(isFaceReachable(key, true)).toBe(true);
          continue;
        }
        expect(settlementFaceAccess(key, false)).toBe("open");
        expect(isFaceReachable(key, false)).toBe(true);
        expect(settlementFaceAccess(key, true)).toBe(group);
        expect(isFaceReachable(key, true)).toBe(group !== "closed");
      }
    }
    expect(wangSettlementSlipVisible(false)).toBe(false);
    expect(wangSettlementSlipVisible(true)).toBe(true);
    expect(wangSettlementSlipText("settling")).toBe(WANG_SETTLEMENT_SLIP);
    expect(settlementClosedReason("settling")).toBe(SETTLEMENT_CLOSED_REASON);
  });
});
