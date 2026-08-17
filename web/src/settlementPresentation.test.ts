import { describe, expect, it } from "vitest";
import {
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
  yearMonthLabel,
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
