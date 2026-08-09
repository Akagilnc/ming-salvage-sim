import { describe, expect, it } from "vitest";
import {
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
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
