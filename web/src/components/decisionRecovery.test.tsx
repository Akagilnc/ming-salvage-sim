import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DecisionRecoveryPanel } from "./decisionRecovery";
import {
  PAUSED_DECISION_MSG,
  needsPhase2Resume,
  replacePendingDecisionsOnRefresh,
  routeIssueDecisions,
  routeRefreshDecisions,
  routeRetryDecisions,
} from "../decisionRouting";
import type { PendingDecision } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return { host, cleanup: () => act(() => { root.unmount(); host.remove(); }) };
}

const validDecision: PendingDecision = {
  idx: 0,
  title: "关宁军饷",
  context: "辽东急报：军中已三月未饷。",
  options: [{ label: "拨帑速发", hint: "先解燃眉之急。" }],
};

const validDecision2: PendingDecision = {
  idx: 1,
  title: "河工修治",
  context: "河决在即，地方请银修堤。",
  options: [{ label: "拨银修堤", hint: "保住沿河百姓。" }],
};

describe("DecisionRecoveryPanel (unit)", () => {
  it("shows the paused-turn error and exposes a retry action", () => {
    const onRetry = vi.fn();

    const { host, cleanup } = render(
      <DecisionRecoveryPanel
        message={PAUSED_DECISION_MSG}
        busy=""
        onRetry={onRetry}
      />,
    );

    expect(host.querySelector('[role="alert"]')?.textContent).toContain("仍在等待批红");
    act(() => (host.querySelector("button") as HTMLButtonElement).click());
    expect(onRetry).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it("disables retry while the recovery request is running", () => {
    const { host, cleanup } = render(
      <DecisionRecoveryPanel
        message={PAUSED_DECISION_MSG}
        busy="重新拉取批红"
        onRetry={vi.fn()}
      />,
    );

    expect((host.querySelector("button") as HTMLButtonElement).disabled).toBe(true);
    cleanup();
  });
});

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

  it("rejects the batch when idx values are swapped — [idx:1, idx:0] must not pass (idx invariant guard)", () => {
    const swapped: PendingDecision[] = [
      { idx: 1, title: "河工修治", context: "河决在即。", options: [{ label: "拨银", hint: "保百姓。" }] },
      { idx: 0, title: "关宁军饷", context: "辽东急报。", options: [{ label: "拨帑", hint: "解燃眉。" }] },
    ];
    const route = routeIssueDecisions(swapped);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("accepts the entire batch when all decisions are valid and idx matches enumerated position", () => {
    const route = routeIssueDecisions([validDecision, validDecision2]);
    expect(route.pendingDecisions).toEqual([validDecision, validDecision2]);
    expect(route.error).toBe("");
  });
});

describe("decision routing — refresh entry (routeRefreshDecisions)", () => {
  it("replaces an old batch when refresh rejects the new batch", () => {
    const route = routeRefreshDecisions("awaiting_decision", [validDecision, { broken: true }]);
    expect(replacePendingDecisionsOnRefresh([validDecision], route.pendingDecisions)).toEqual([]);
  });

  it("rejects the whole batch on page refresh when any decision is corrupt", () => {
    const route = routeRefreshDecisions("awaiting_decision", [validDecision, { broken: true }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("#1307 settling with empty pending is a normal intermediate — no error, no 重新拉取", () => {
    const route = routeRefreshDecisions("settling", []);
    expect(route.pendingDecisions).toBeNull();
    expect(route.error).toBeNull();
    expect(route.error).not.toBe(PAUSED_DECISION_MSG);
  });

  it("skips routing when phase is not awaiting_decision on refresh", () => {
    const route = routeRefreshDecisions("issued", [validDecision]);
    expect(route.pendingDecisions).toBeNull();
    expect(route.error).toBeNull();
  });

  it("rejects swapped idx [idx:1, idx:0] on refresh entry too (idx invariant guard)", () => {
    const swapped: PendingDecision[] = [
      { idx: 1, title: "河工修治", context: "河决在即。", options: [{ label: "拨银", hint: "保百姓。" }] },
      { idx: 0, title: "关宁军饷", context: "辽东急报。", options: [{ label: "拨帑", hint: "解燃眉。" }] },
    ];
    const route = routeRefreshDecisions("awaiting_decision", swapped);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("accepts a valid batch on refresh", () => {
    const route = routeRefreshDecisions("awaiting_decision", [validDecision]);
    expect(route.pendingDecisions).toEqual([validDecision]);
    expect(route.error).toBe("");
  });

  it("#1374 phase2 全员 decided：刷新不重开批红弹窗（无「可再提交」假象）", () => {
    const decided = { ...validDecision, status: "decided" };
    const route = routeRefreshDecisions("awaiting_decision", [decided]);
    expect(route.pendingDecisions).toBeNull();
    expect(route.error).toBeNull();
    // #1418 r2：接到续跑 affordance，不当「无事发生」
    expect(route.resumePhase2).toBe(true);
  });

  it("fail-closed：畸形 {status:decided} 不得清空决策态，须显示 PAUSED_DECISION_MSG", () => {
    const route = routeRefreshDecisions("awaiting_decision", [{ status: "decided" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });
});

describe("decision routing — retry (routeRetryDecisions: stale-phase vs still-corrupted)", () => {
  it("clears the error banner when the turn has already advanced (not a failure)", () => {
    const route = routeRetryDecisions("issued", []);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe("");
  });

  it("#1307 settling retry keeps quiet intermediate — empty pending is not 重新拉取 error", () => {
    const route = routeRetryDecisions("settling", []);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe("");
    expect(route.error).not.toContain("重新拉取");
  });

  it("recovers into the decision modal when valid decisions arrive on retry", () => {
    const route = routeRetryDecisions("awaiting_decision", [validDecision]);
    expect(route.pendingDecisions).toEqual([validDecision]);
    expect(route.error).toBe("");
  });

  it("keeps the error banner when still awaiting_decision and still corrupted", () => {
    const route = routeRetryDecisions("awaiting_decision", [{ idx: "still bad" }]);
    expect(route.pendingDecisions).toEqual([]);
    expect(route.error).toBe(PAUSED_DECISION_MSG);
  });

  it("#1418 r2 phase2 全员 decided：重拉不报损坏、不重开弹窗、不得 error:\"\" 清横幅", () => {
    const decided = { ...validDecision, status: "decided" };
    const route = routeRetryDecisions("awaiting_decision", [decided]);
    expect(route.pendingDecisions).toBeNull();
    // 禁 error:"" 当成功清横幅——改 resumePhase2 信号接到 settle-resume
    expect(route.error).toBeNull();
    expect(route.error).not.toBe("");
    expect(route.resumePhase2).toBe(true);
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

  it("awaiting + 全员 decided + settlement_display 真 → 需续跑", () => {
    expect(needsPhase2Resume("awaiting_decision", [decided], true)).toBe(true);
  });

  it("负向：快照已清（正常完成月）不触发续跑面", () => {
    expect(needsPhase2Resume("awaiting_decision", [decided], false)).toBe(false);
    expect(needsPhase2Resume("awaiting_decision", [decided], undefined)).toBe(false);
  });

  it("负向：仍有待批 / 非 awaiting / 空批 → 不触发", () => {
    expect(needsPhase2Resume("awaiting_decision", [validDecision], true)).toBe(false);
    expect(needsPhase2Resume("settling", [decided], true)).toBe(false);
    expect(needsPhase2Resume("player", [decided], true)).toBe(false);
    expect(needsPhase2Resume("awaiting_decision", [], true)).toBe(false);
  });

  it("负向：畸形 {status:decided} 不得当 all-decided", () => {
    expect(needsPhase2Resume("awaiting_decision", [{ status: "decided" }], true)).toBe(false);
  });
});
