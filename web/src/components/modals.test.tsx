import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatModal, EdictModal, ReportModal } from "./modals";
import type { BudgetAccount, GameState, Minister, PendingActionFailure } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Centralised teardown registry: every rendered root is unmounted in afterEach so a
// FAILED assertion (which aborts the test body before any inline cleanup) can never
// leak a mounted React root into the next test (gemini cmr r1).
const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];

const MINISTER_MOCK: Minister = {
  name: "周延儒",
  office: "内阁首辅",
  office_type: "cabinet",
  faction: "东林",
  style: "字玉绳",
  status: "active",
  status_label: "在朝",
  summary: "东林领袖",
  favorite: false,
  skills: [],
};

const CONSORT_MOCK: Minister = {
  name: "周贵人",
  office: "贵人",
  office_type: "后宫",
  faction: "",
  style: "",
  status: "active",
  status_label: "在宫",
  summary: "后宫嫔妃",
  favorite: false,
  skills: [],
};

function renderModal(props: {
  minister: Minister;
  portraitPrefix: string;
  busy?: string;
  onCancel?: () => void;
  chatFailures?: PendingActionFailure[];
  onRetryFailure?: (failure: PendingActionFailure) => void;
}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ChatModal
        minister={props.minister}
        portraitPrefix={props.portraitPrefix}
        busy={props.busy ?? ""}
        chat={[]}
        suggestions={[]}
        pendingUserMessage=""
        streamingMinisterMessage=""
        chatNotice=""
        chatFailures={props.chatFailures ?? []}
        canUndoLastChat={false}
        composerHint=""
        input=""
        error=""
        secretOrders={[]}
        onInput={() => {}}
        onSend={() => {}}
        onRetryFailure={props.onRetryFailure ?? (() => {})}
        onUndo={() => {}}
        onHint={() => {}}
        onFavorite={() => {}}
        onOpenEdict={() => {}}
        onClose={() => {}}
        onCancel={props.onCancel}
      />
    )
  );
  // Register for centralised teardown (afterEach) — no inline cleanup, so a failing
  // assertion can never skip unmount and leak a root into the next test.
  mountedRoots.push({ root, host });
}

function renderReportModal(props: { report: string; accountReport?: string }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ReportModal
        report={props.report}
        accountReport={props.accountReport ?? ""}
        onClose={() => {}}
      />
    )
  );
  mountedRoots.push({ root, host });
}

const EMPTY_BUDGET_ACCOUNT: BudgetAccount = {
  balance: 0,
  income: [],
  expense: [],
  income_total: 0,
  expense_total: 0,
  net: 0,
  movements: [],
  movements_total: 0,
};

function baseGameState(overrides: Partial<GameState> = {}): GameState {
  return {
    turn: { year: 1627, period: 10, turn: 1, phase: "summoning" },
    metrics: {},
    previous_summary: "",
    treasury: "",
    issues: [],
    legacies: [],
    closed_this_turn: [],
    budget: { 国库: EMPTY_BUDGET_ACCOUNT, 内库: EMPTY_BUDGET_ACCOUNT },
    region_warning: "",
    army_warning: "",
    power_warning: "",
    powers: [],
    victory_status: { status: "ongoing", summary: "" },
    ending: null,
    events: [],
    regions: [],
    armies: [],
    map_nodes: [],
    ministers: [],
    consorts: [],
    directives: [],
    pending_count: 0,
    pending_directive_count: 0,
    pending_secret_order_count: 0,
    pending_non_directive_action_count: 0,
    last_decree: "",
    last_report: "",
    ...overrides,
  };
}

function renderEdictModal(props: { state: GameState; onAdvanceWithoutEdict?: () => void }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <EdictModal
        state={props.state}
        directiveText=""
        editingDirectiveId={null}
        editingDirectiveText=""
        decree=""
        report=""
        busy=""
        error=""
        onDirectiveTextChange={() => {}}
        onEditingTextChange={() => {}}
        onCreateDirective={() => {}}
        onStartEdit={() => {}}
        onCancelEdit={() => {}}
        onSaveDirective={() => {}}
        onDeleteDirective={() => {}}
        onWriteDecree={() => {}}
        onAdvanceWithoutEdict={props.onAdvanceWithoutEdict ?? (() => {})}
        onSaveDecree={() => {}}
        onResetDecree={() => {}}
        onIssueDecree={() => {}}
        onConfirmDirective={() => {}}
        onRejectDirective={() => {}}
      />
    )
  );
  mountedRoots.push({ root, host });
  return { host, root };
}

afterEach(() => {
  // Unmount every root rendered this test (whether the body passed or threw).
  for (const { root, host } of mountedRoots) {
    act(() => root.unmount());
    host.remove();
  }
  mountedRoots.length = 0;
  document.body.innerHTML = "";
});

describe("EdictModal — hidden secret-order default approval", () => {
  it("shows no-edict advance when only hidden secret orders are pending", () => {
    const onAdvance = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ pending_secret_order_count: 1, pending_non_directive_action_count: 1 }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("退朝")
    ) as HTMLButtonElement | undefined;

    expect(button).toBeTruthy();
    expect(host.textContent).not.toContain("密令已候旨");
    expect(host.textContent).toContain("尚有召对事项候旨");
    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it("shows no-edict advance for non-directive pending actions beyond new secret orders", () => {
    const onAdvance = vi.fn();
    const { host } = renderEdictModal({
      state: baseGameState({ pending_non_directive_action_count: 1 }),
      onAdvanceWithoutEdict: onAdvance,
    });
    const button = Array.from(host.querySelectorAll("button")).find((item) =>
      item.textContent?.includes("退朝")
    ) as HTMLButtonElement | undefined;

    expect(button).toBeTruthy();
  });
});

describe("ChatModal — placeholder switches on character type", () => {
  it("shows 大臣 and 他 in placeholder for ministers", () => {
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).toContain("大臣");
    expect(textarea.placeholder).toContain("他");
  });

  it("does NOT show 大臣 or 他 in placeholder for consorts", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder).not.toContain("大臣");
    expect(textarea.placeholder).not.toContain("他");
  });

  it("consort placeholder has meaningful length", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_" });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.placeholder.length).toBeGreaterThan(5);
  });

  it("shows secret-order landing failure with retry action", () => {
    const failure: PendingActionFailure = {
      id: 7,
      kind: "secret_order",
      action: "新建",
      retryable: true,
      message: "密令未能正式落库，请重试；若暂不处理，也不会阻断继续召对。",
    };
    const retry = vi.fn();

    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chatFailures: [failure],
      onRetryFailure: retry,
    });

    expect(document.querySelector(".chat-failure-note")?.textContent).toContain("密令未能正式落库");
    const button = Array.from(document.querySelectorAll("button")).find((node) => node.textContent === "重试");
    expect(button).toBeTruthy();
    act(() => button?.click());
    expect(retry).toHaveBeenCalledWith(failure);
  });

  it("does not show retry action for unsupported failure kinds", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      chatFailures: [{
        id: 8,
        kind: "office",
        action: "任命",
        message: "任免未能正式落库，已记录为失败；若暂不处理，也不会阻断继续召对。",
      }],
    });

    expect(document.querySelector(".chat-failure-note")?.textContent).toContain("任免未能正式落库");
    const button = Array.from(document.querySelectorAll("button")).find((node) => node.textContent === "重试");
    expect(button).toBeUndefined();
  });
});

describe("ChatModal — thinking/loading text switches on character type (gemini cmr r1)", () => {
  const thinkingText = (): string =>
    (document.querySelector(".chat-message.thinking p")?.textContent ?? "");

  it("shows 大臣思索中 while a minister is thinking", () => {
    renderModal({ minister: MINISTER_MOCK, portraitPrefix: "minister_", busy: "思考中" });
    expect(thinkingText()).toContain("大臣思索中");
  });

  it("does NOT show 大臣 while a consort is thinking (neutral text)", () => {
    renderModal({ minister: CONSORT_MOCK, portraitPrefix: "consort_", busy: "思考中" });
    const text = thinkingText();
    expect(text).not.toContain("大臣");
    expect(text.length).toBeGreaterThan(0);
  });
});

describe("ChatModal — cancel button during busy (issue #353)", () => {
  it("shows an observer-exit button when busy and onCancel is provided", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
      onCancel: vi.fn(),
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).not.toBeNull();
    expect(cancelBtn?.textContent).toContain("离开等待");
  });

  it("does NOT show a cancel button when idle", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "",
      onCancel: vi.fn(),
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).toBeNull();
  });

  it("calls onCancel when cancel button is clicked", () => {
    const onCancel = vi.fn();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
      onCancel,
    });
    const cancelBtn = document.querySelector(".composer-cancel") as HTMLButtonElement;
    act(() => cancelBtn.click());
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does NOT show cancel button when busy but onCancel is not provided", () => {
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
    });
    const cancelBtn = document.querySelector(".composer-cancel");
    expect(cancelBtn).toBeNull();
  });
});

describe("ChatModal — elapsed timer during thinking (issue #353)", () => {
  it("shows elapsed time in the thinking indicator while busy", () => {
    vi.useFakeTimers();
    renderModal({
      minister: MINISTER_MOCK,
      portraitPrefix: "minister_",
      busy: "大臣思索中",
    });
    // Timer starts at 0; advance 3 seconds
    act(() => { vi.advanceTimersByTime(3000); });
    const thinkingP = document.querySelector(".chat-message.thinking p");
    expect(thinkingP?.textContent).toMatch(/\d+\s*秒/);
    vi.useRealTimers();
  });
});

describe("ReportModal — two-page settlement bulletin", () => {
  it("shows narrative as page 1 and account text as manually selected page 2", () => {
    renderReportModal({
      report: "辽东有警，诸臣奏闻。",
      accountReport: "人事：卢象升调任。\n有司奏：某军窒碍未行。",
    });

    expect(document.body.textContent).toContain("辽东有警");
    expect(document.body.textContent).not.toContain("卢象升调任");

    const page2 = Array.from(document.querySelectorAll("button"))
      .find((btn) => btn.textContent?.includes("实账"));
    expect(page2).toBeTruthy();
    act(() => (page2 as HTMLButtonElement).click());

    expect(document.body.textContent).toContain("卢象升调任");
    expect(document.body.textContent).toContain("窒碍未行");
    expect(document.body.textContent).not.toContain("辽东有警");
  });
});
