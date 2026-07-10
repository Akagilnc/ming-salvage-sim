import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DecisionRecoveryPanel } from "./decisionRecovery";
import { DecisionModal } from "./decisionModal";
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

const validDecision2: PendingDecision = {
  idx: 1,
  title: "河工修治",
  context: "河决在即，地方请银修堤。",
  options: [{ label: "拨银修堤", hint: "保住沿河百姓。" }],
};

const PAUSED_MSG = "本回合仍在等待批红，但待批决策无法校验。请重新拉取后重试。";

type SimState = { turn: { phase: string }; pending_decisions: unknown[] };

/**
 * Production-wired fixture mirroring main.tsx decision routing:
 *   - Entry 1 (issueDecree decisions branch): routes outcome.data.decisions through pendingDecisionsFrom
 *   - Entry 2 (refresh-recovery effect): gates on phase === awaiting_decision, then routes
 *   - retryPendingDecisions: calls loadState (simulated), distinguishes stale-phase from still-corrupted
 * Uses the REAL pendingDecisionsFrom, REAL DecisionRecoveryPanel, REAL DecisionModal.
 */
function DecisionRoutingFixture({
  issueOutcome,
  refreshState,
  retryState,
}: {
  issueOutcome: { decisions: unknown[] };
  refreshState: SimState;
  retryState: SimState;
}) {
  const [pendingDecisions, setPendingDecisions] = React.useState<PendingDecision[]>([]);
  const [pausedDecisionError, setPausedDecisionError] = React.useState("");
  const [busy, setBusy] = React.useState("");

  const issue = () => {
    const decisions = pendingDecisionsFrom(issueOutcome.decisions || []);
    if (decisions.length === 0) {
      setPendingDecisions([]);
      setPausedDecisionError(PAUSED_MSG);
      return;
    }
    setPausedDecisionError("");
    setPendingDecisions(decisions);
  };

  const refresh = () => {
    if (refreshState.turn.phase !== "awaiting_decision") return;
    const decisions = pendingDecisionsFrom(refreshState.pending_decisions || []);
    if (decisions.length === 0) {
      setPendingDecisions([]);
      setPausedDecisionError(PAUSED_MSG);
      return;
    }
    setPausedDecisionError("");
    setPendingDecisions((prev) => (prev.length ? prev : decisions));
  };

  const retry = async () => {
    setBusy("重新拉取批红");
    setPausedDecisionError("");
    try {
      const decisions = pendingDecisionsFrom(retryState.pending_decisions || []);
      if (retryState.turn.phase !== "awaiting_decision") {
        setPendingDecisions([]);
        setPausedDecisionError("");
        return;
      }
      if (decisions.length === 0) {
        setPendingDecisions([]);
        setPausedDecisionError(PAUSED_MSG);
        return;
      }
      setPendingDecisions(decisions);
      setPausedDecisionError("");
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <button data-testid="issue" onClick={issue}>颁诏</button>
      <button data-testid="refresh" onClick={refresh}>刷新</button>
      {!busy && pausedDecisionError ? (
        <DecisionRecoveryPanel message={pausedDecisionError} busy={busy} onRetry={retry} />
      ) : null}
      {pendingDecisions.length > 0 && !busy ? (
        <DecisionModal decisions={pendingDecisions} onResolve={vi.fn()} />
      ) : null}
    </div>
  );
}

function clickIssue(host: HTMLElement) {
  act(() => (host.querySelector("[data-testid=issue]") as HTMLButtonElement).click());
}
function clickRefresh(host: HTMLElement) {
  act(() => (host.querySelector("[data-testid=refresh]") as HTMLButtonElement).click());
}
function clickRetry(host: HTMLElement) {
  return act(async () => {
    (host.querySelector(".decision-recovery-banner button") as HTMLButtonElement).click();
  });
}

describe("DecisionRecoveryPanel (unit)", () => {
  it("shows the paused-turn error and exposes a retry action", () => {
    const onRetry = vi.fn();

    const { host, cleanup } = render(
      <DecisionRecoveryPanel
        message={PAUSED_MSG}
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
        message={PAUSED_MSG}
        busy="重新拉取批红"
        onRetry={vi.fn()}
      />,
    );

    expect((host.querySelector("button") as HTMLButtonElement).disabled).toBe(true);
    cleanup();
  });
});

describe("decision routing — production-wired (issueDecree entry)", () => {
  it("rejects the whole batch when any decision is corrupt, not just the bad item (批示错位 guard)", () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [validDecision, { idx: "bad" }] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("rejects a decision whose options array is empty (空票拟 guard)", () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [{ idx: 0, title: "空票", context: "无票拟。", options: [] }] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("enters the decision modal when the entire batch is valid (both memorials preserved in order)", () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [validDecision, validDecision2] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector(".decision-page")).not.toBeNull();
    expect(host.querySelector(".decision-kicker")?.textContent).toContain("第 1 / 2 疏");
    expect(host.querySelector(".decision-document h3")?.textContent).toBe("关宁军饷");
    cleanup();
  });
});

describe("decision routing — production-wired (refresh entry)", () => {
  it("rejects the whole batch on page refresh when any decision is corrupt", () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [] }}
        refreshState={{ turn: { phase: "awaiting_decision" }, pending_decisions: [validDecision, { broken: true }] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickRefresh(host);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("skips routing when phase is not awaiting_decision on refresh", () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [validDecision] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickRefresh(host);
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });
});

describe("decision routing — production-wired (retry: stale-phase vs still-corrupted)", () => {
  it("clears the error banner when the turn has already advanced (not a failure)", async () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [{ idx: "bad" }] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "issued" }, pending_decisions: [] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')).not.toBeNull();

    await clickRetry(host);
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("recovers into the decision modal when valid decisions arrive on retry", async () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [{ idx: "bad" }] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "awaiting_decision" }, pending_decisions: [validDecision] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')).not.toBeNull();

    await clickRetry(host);
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.querySelector(".decision-page")).not.toBeNull();
    expect(host.querySelector(".decision-document h3")?.textContent).toBe("关宁军饷");
    cleanup();
  });

  it("keeps the error banner when still awaiting_decision and still corrupted", async () => {
    const { host, cleanup } = render(
      <DecisionRoutingFixture
        issueOutcome={{ decisions: [{ idx: "bad" }] }}
        refreshState={{ turn: { phase: "issued" }, pending_decisions: [] }}
        retryState={{ turn: { phase: "awaiting_decision" }, pending_decisions: [{ idx: "still bad" }] }}
      />,
    );

    clickIssue(host);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");

    await clickRetry(host);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("无法校验");
    expect(host.querySelector(".decision-page")).toBeNull();
    cleanup();
  });
});
