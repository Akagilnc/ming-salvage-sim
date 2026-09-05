import { describe, expect, it } from "vitest";
import {
  SETTLEMENT_ENDING_STAGE,
  SETTLEMENT_WAIT_STAGES,
  resolveSettlementWaitProgress,
} from "./settlementProgress";

describe("#1725 settlement wait progress (typed)", () => {
  it("maps the six stream stages to 1-based current/total without string inference", () => {
    expect(SETTLEMENT_WAIT_STAGES).toEqual([
      "固定月度财政入账",
      "回顾近来朝局",
      "推演月末邸报",
      "数值推演结算",
      "落库与事项推进",
      "记起居注",
    ]);

    const steps = SETTLEMENT_WAIT_STAGES.map((label) => resolveSettlementWaitProgress(label));
    expect(steps.map((p) => p && { current: p.current, total: p.total, label: p.label })).toEqual([
      { current: 1, total: 6, label: "固定月度财政入账" },
      { current: 2, total: 6, label: "回顾近来朝局" },
      { current: 3, total: 6, label: "推演月末邸报" },
      { current: 4, total: 6, label: "数值推演结算" },
      { current: 5, total: 6, label: "落库与事项推进" },
      { current: 6, total: 6, label: "记起居注" },
    ]);
  });

  it("does not invent progress for unknown or empty stage labels", () => {
    expect(resolveSettlementWaitProgress("")).toBeNull();
    expect(resolveSettlementWaitProgress(undefined)).toBeNull();
    expect(resolveSettlementWaitProgress("圣意亲裁，续推时局")).toBeNull();
    // 邻近文案不得靠包含关系猜步
    expect(resolveSettlementWaitProgress("回顾近来朝局中")).toBeNull();
    expect(resolveSettlementWaitProgress("stage_4")).toBeNull();
  });
});

describe("#1740 ending-round seventh stage progress", () => {
  it("resolves ending stage to step 7 of 7 without changing ordinary six-step totals", () => {
    expect(SETTLEMENT_ENDING_STAGE).toBe("国史编纂结局总评");
    expect(resolveSettlementWaitProgress(SETTLEMENT_ENDING_STAGE)).toEqual({
      label: SETTLEMENT_ENDING_STAGE,
      current: 7,
      total: 7,
    });
    // 六阶仍 total=6——普通回合不得被抬成「共 7 步」
    for (const label of SETTLEMENT_WAIT_STAGES) {
      expect(resolveSettlementWaitProgress(label)?.total).toBe(6);
    }
  });
});
