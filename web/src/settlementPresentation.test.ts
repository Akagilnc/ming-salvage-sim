import { describe, expect, it } from "vitest";
import {
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
} from "./settlementPresentation";

describe("settlement presentation routing", () => {
  it("does not auto-open secret order progress after settlement", () => {
    expect(shouldAutoOpenSecretOrdersAfterSettlement()).toBe(false);
  });

  it("does not auto-open closed issue progress after settlement", () => {
    expect(shouldAutoOpenClosedIssuesAfterSettlement()).toBe(false);
  });
});
