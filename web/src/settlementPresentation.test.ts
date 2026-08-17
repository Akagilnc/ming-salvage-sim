import { describe, expect, it } from "vitest";
import {
  ALL_SETTLEMENT_FACE_KEYS,
  FACE_GROUP,
  SETTLEMENT_CLOSED_REASON,
  WANG_SETTLEMENT_SLIP,
  isFaceReachable,
  isFaceReadonly,
  isSettlementDisplay,
  settlementFaceAccess,
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
  wangSettlementSlipVisible,
  yearMonthLabel,
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
});

/** 票面 r2 机械清单：关闭 / 只读 / 必达 / 呈现 / 排除（不缩表）。 */
const CLOSED_KEYS: SettlementFaceKey[] = [
  "situation", "region", "army", "node_intel", "secret_orders", "edict", "chat_entry",
];
const READONLY_KEYS: SettlementFaceKey[] = [
  "court_roster", "appointment_roster", "harem_roster", "building", "economy",
  "memorials", "gazette", "audience_archive", "history", "closed_issues", "legacies", "menu",
];
const MUST_KEYS: SettlementFaceKey[] = [
  "decision_modal", "decision_recovery", "settle_resume",
];
const PRESENT_KEYS: SettlementFaceKey[] = ["wang_slip"];
const EXCLUDED_KEYS: SettlementFaceKey[] = ["cheat_console", "ending"];

describe("#1236 T3 settlement face gates (唯一谓词 settlement_display)", () => {
  it("mechanical roster covers every face key exactly once", () => {
    const listed = [...CLOSED_KEYS, ...READONLY_KEYS, ...MUST_KEYS, ...PRESENT_KEYS, ...EXCLUDED_KEYS];
    expect(new Set(listed).size).toBe(listed.length);
    expect(new Set(listed)).toEqual(new Set(ALL_SETTLEMENT_FACE_KEYS));
    for (const key of CLOSED_KEYS) expect(FACE_GROUP[key]).toBe("closed");
    for (const key of READONLY_KEYS) expect(FACE_GROUP[key]).toBe("readonly");
    for (const key of MUST_KEYS) expect(FACE_GROUP[key]).toBe("must");
    for (const key of PRESENT_KEYS) expect(FACE_GROUP[key]).toBe("present");
    for (const key of EXCLUDED_KEYS) expect(FACE_GROUP[key]).toBe("excluded");
  });

  it("isSettlementDisplay reads only the server flag", () => {
    expect(isSettlementDisplay(undefined)).toBe(false);
    expect(isSettlementDisplay({})).toBe(false);
    expect(isSettlementDisplay({ settlement_display: false })).toBe(false);
    expect(isSettlementDisplay({ settlement_display: true })).toBe(true);
  });

  it("when settlement_display is off, closed/readonly/must/present are open; excluded stays excluded", () => {
    for (const key of [...CLOSED_KEYS, ...READONLY_KEYS, ...MUST_KEYS, ...PRESENT_KEYS]) {
      expect(settlementFaceAccess(key, false)).toBe("open");
      expect(isFaceReachable(key, false)).toBe(true);
      expect(isFaceReadonly(key, false)).toBe(false);
    }
    for (const key of EXCLUDED_KEYS) {
      expect(settlementFaceAccess(key, false)).toBe("excluded");
    }
    expect(wangSettlementSlipVisible(false)).toBe(false);
  });

  it("逐 key：核账期关闭组不可达", () => {
    for (const key of CLOSED_KEYS) {
      expect(settlementFaceAccess(key, true)).toBe("closed");
      expect(isFaceReachable(key, true)).toBe(false);
      expect(isFaceReadonly(key, true)).toBe(false);
    }
  });

  it("逐 key：核账期只读组可达且只读", () => {
    for (const key of READONLY_KEYS) {
      expect(settlementFaceAccess(key, true)).toBe("readonly");
      expect(isFaceReachable(key, true)).toBe(true);
      expect(isFaceReadonly(key, true)).toBe(true);
    }
  });

  it("逐 key：必达三面核账期仍可达（门控不得误关）", () => {
    for (const key of MUST_KEYS) {
      expect(settlementFaceAccess(key, true)).toBe("must");
      expect(isFaceReachable(key, true)).toBe(true);
    }
  });

  it("王承恩递话条同谓词显隐；文案正向一句、无进度符号", () => {
    expect(settlementFaceAccess("wang_slip", true)).toBe("present");
    expect(wangSettlementSlipVisible(true)).toBe(true);
    expect(WANG_SETTLEMENT_SLIP.length).toBeGreaterThan(0);
    expect(WANG_SETTLEMENT_SLIP).not.toMatch(/%|％|\d+\s*秒|进度条/);
    expect(SETTLEMENT_CLOSED_REASON).toMatch(/核账/);
  });

  it("排除面不吃关闭门", () => {
    for (const key of EXCLUDED_KEYS) {
      expect(settlementFaceAccess(key, true)).toBe("excluded");
      expect(isFaceReachable(key, true)).toBe(true);
    }
  });
});
