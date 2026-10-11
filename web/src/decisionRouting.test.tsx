import { describe, expect, it } from "vitest";
import {
  PAUSED_DECISION_MSG,
  needsPhase2Resume,
  replacePendingDecisionsOnRefresh,
  routeIssueDecisions,
  routeRefreshDecisions,
  routeRetryDecisions,
} from "./decisionRouting";
import type { PendingDecision } from "./types";

const validDecision: PendingDecision = {
  idx: 0,
  title: "关宁军饷",
  context: "辽东急报：军中已三月未饷。",
  options: [{ label: "拨帑速发", hint: "先解燃眉之急。" }],
};

describe("decision routing — issueDecree entry (routeIssueDecisions)", () => {
  it("rejects the whole batch when any decision is corrupt, not just the bad item (批示错位 guard)", () => {
    const route = routeIssueDecisions([validDecision, { idx: "bad" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("rejects a decision whose options array is empty (空票拟 guard)", () => {
    const route = routeIssueDecisions([{ idx: 0, title: "空票", context: "无票拟。", options: [] }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

});

describe("decision routing — refresh entry (routeRefreshDecisions)", () => {

  it("rejects the whole batch on page refresh when any decision is corrupt", () => {
    const route = routeRefreshDecisions("awaiting_decision", [validDecision, { broken: true }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(replacePendingDecisionsOnRefresh([validDecision], route.pendingDecisions)).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("skips routing when phase is not awaiting_decision on refresh", () => {
    const route = routeRefreshDecisions("issued", [validDecision]);
    expect(route.pendingDecisions).toBeNull();
    expect(route.error).toBeNull();
  });

  it("fail-closed：畸形 {status:decided} 不得清空决策态，须显示 PAUSED_DECISION_MSG", () => {
    const route = routeRefreshDecisions("awaiting_decision", [{ status: "decided" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });
});

describe("decision routing — retry (routeRetryDecisions: stale-phase vs still-corrupted)", () => {
  it("#1625 awaiting 空案头且入口在飞：重拉只等待", () => {
    // refresh inflight wait is owned by useSettlementFlow's effect gate;
    // routeRefreshDecisions no longer takes an inflight flag.
    const route = routeRetryDecisions("awaiting_decision", [], false, true);
    expect(route.pendingDecisions).toBeNull();
    expect(route.error).toBeNull();
    expect(route.resumePhase2).toBeFalsy();
  });

  it("keeps the error banner when still awaiting_decision and still corrupted", () => {
    const route = routeRetryDecisions("awaiting_decision", [{ idx: "still bad" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("fail-closed：畸形 {status:decided} 重拉不得静默清空，须显示 PAUSED_DECISION_MSG", () => {
    const route = routeRetryDecisions("awaiting_decision", [{ status: "decided" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
    expect(route.resumePhase2).toBeFalsy();
  });
});

describe("#1418 r2 needsPhase2Resume（all-decided 续跑谓词）", () => {
  const decided = { ...validDecision, status: "decided" };

  it("负向：仍有待批 / 非 awaiting / 空批 → 不触发", () => {
    expect(needsPhase2Resume("awaiting_decision", [validDecision], true)).toBe(false);
    expect(needsPhase2Resume("settling", [decided], true)).toBe(false);
    expect(needsPhase2Resume("player", [decided], true)).toBe(false);
    expect(needsPhase2Resume("awaiting_decision", [], true)).toBe(false);
  });

  it("负向：畸形 {status:decided} 不得当 all-decided", () => {
    expect(needsPhase2Resume("awaiting_decision", [{ status: "decided" }], true)).toBe(false);
  });

  it("#657 服务端 typed resume_phase2", () => {
    expect(needsPhase2Resume("settling", [], true, true)).toBe(false);
  });
});
