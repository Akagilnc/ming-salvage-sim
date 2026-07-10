import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DecisionRecoveryPanel } from "./decisionRecovery";
import { pendingDecisionsFrom } from "../decisionRouting";
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

function RejectedDecisionRecoveryFixture() {
  const [events, setEvents] = React.useState<unknown[]>([{ idx: "invalid" }]);
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length > 0) {
    return <div data-testid="decision-modal">批红：{decisions[0].title}</div>;
  }
  return (
    <DecisionRecoveryPanel
      message="本回合仍在等待批红，但待批决策无法校验。"
      busy=""
      onRetry={() => setEvents([validDecision])}
    />
  );
}

describe("DecisionRecoveryPanel", () => {
  it("turns an all-rejected decision payload into an error state and retries into red-seal review", () => {
    const { host, cleanup } = render(<RejectedDecisionRecoveryFixture />);

    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");
    act(() => (host.querySelector("button") as HTMLButtonElement).click());
    expect(host.querySelector('[data-testid="decision-modal"]')?.textContent).toContain("关宁军饷");
    cleanup();
  });

  it("shows the paused-turn error and exposes a retry action", () => {
    const onRetry = vi.fn();

    const { host, cleanup } = render(
      <DecisionRecoveryPanel
        message="本回合仍在等待批红，但待批决策无法校验。"
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
        message="本回合仍在等待批红，但待批决策无法校验。"
        busy="重新拉取批红"
        onRetry={vi.fn()}
      />,
    );

    expect((host.querySelector("button") as HTMLButtonElement).disabled).toBe(true);
    cleanup();
  });
});
