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
    expect(yearMonthLabel({ year: 1627, period: 10 })).toBe("1627 年 10 月");
    expect(yearMonthLabel({ year: 1627, period: 10, settlement_display: false })).toBe("1627 年 10 月");
    expect(yearMonthLabel({ year: 1627, period: 10, settlement_display: true })).toBe("1627 年 10 月 · 核账");
  });

  it("#1323 awaiting_decision 文案层：年月标 ·待批；递话/关闭理由分口吻", () => {
    expect(yearMonthLabel({
      year: 1627, period: 10, settlement_display: true, phase: "awaiting_decision",
    })).toBe("1627 年 10 月 · 待批");
    expect(yearMonthLabel({
      year: 1627, period: 10, settlement_display: true, phase: "settling",
    })).toBe("1627 年 10 月 · 核账");
    expect(wangSettlementSlipText("awaiting_decision")).toBe(WANG_AWAITING_SLIP);
    expect(wangSettlementSlipText("settling")).toBe(WANG_SETTLEMENT_SLIP);
    expect(settlementClosedReason("awaiting_decision")).toBe(AWAITING_CLOSED_REASON);
    expect(settlementClosedReason("settling")).toBe(SETTLEMENT_CLOSED_REASON);
    // P4：正向短句，无进度条/百分比/秒数/模板长文
    expect(WANG_AWAITING_SLIP).toMatch(/待批/);
    expect(WANG_AWAITING_SLIP).toMatch(/批红/);
    expect(WANG_AWAITING_SLIP).not.toMatch(/%|％|\d+\s*秒|进度条/);
    expect(WANG_AWAITING_SLIP.length).toBeLessThan(40);
    expect(AWAITING_CLOSED_REASON).toMatch(/待批/);
    expect(AWAITING_CLOSED_REASON).toMatch(/批红/);
    // 显隐谓词仍只看 settlement_display（phase 不充门控真源）
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
  must: ["decision_modal", "decision_recovery", "settle_resume"],
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
    expect(WANG_SETTLEMENT_SLIP.length).toBeGreaterThan(0);
    expect(WANG_SETTLEMENT_SLIP).not.toMatch(/%|％|\d+\s*秒|进度条/);
    expect(SETTLEMENT_CLOSED_REASON).toMatch(/核账/);
  });
});
