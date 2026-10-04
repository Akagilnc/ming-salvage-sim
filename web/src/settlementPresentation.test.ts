import { describe, expect, it } from "vitest";
import {
  FACE_GROUP,
  isFaceReachable,
  isSettlementDisplay,
  settlementFaceAccess,
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
  wangSettlementSlipVisible,
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
  });
});
