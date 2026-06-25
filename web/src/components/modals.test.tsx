import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatModal, ReportModal } from "./modals";
import type { Minister } from "../types";

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
        canUndoLastChat={false}
        composerHint=""
        input=""
        error=""
        secretOrders={[]}
        onInput={() => {}}
        onSend={() => {}}
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

afterEach(() => {
  // Unmount every root rendered this test (whether the body passed or threw).
  for (const { root, host } of mountedRoots) {
    act(() => root.unmount());
    host.remove();
  }
  mountedRoots.length = 0;
  document.body.innerHTML = "";
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
