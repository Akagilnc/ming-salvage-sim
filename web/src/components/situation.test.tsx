import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { IssueGroup, SituationDetailModal, SituationPanel, SituationRow } from "./situation";
import { StateModal } from "./stateModal";
import type { GameState, Issue } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const commitmentText = "限至第4月·到期待裁";

function makeIssue(): Issue & { commitment_progress_text: string } {
  return {
    id: 136,
    kind: "initiative",
    title: "按月补发关宁欠饷",
    bar_value: 55,
    bar_good_meaning: "欠饷清偿",
    bar_bad_meaning: "军心溃散",
    phase: "持续拨付",
    stage_text: "辽饷承诺已入账，仍须按月查核。",
    severity: 2,
    tags: ["圣旨承诺"],
    inertia: 0,
    resolve_condition: "补齐关宁欠饷",
    fail_condition: "朝廷停拨或军中哗变",
    ongoing_text: "国库每月拨银补发关宁欠饷",
    effect_on_resolve: {},
    effect_on_fail: {},
    commitment_progress_text: commitmentText,
  };
}

function makeCommitmentWithoutProgressText(): Issue {
  const issue: Issue = { ...makeIssue() };
  delete issue.commitment_progress_text;
  return {
    ...issue,
    commitment_progress: { months_elapsed: 1 },
  };
}

function makeOrdinaryIssueWithoutProgressText(): Issue {
  const issue: Issue = { ...makeIssue() };
  delete issue.commitment_progress;
  delete issue.commitment_progress_text;
  return {
    ...issue,
    tags: [],
  };
}

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return () => {
    act(() => root.unmount());
    host.remove();
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("commitment progress display", () => {
  it("shows commitment progress in the issue board", () => {
    const cleanup = render(<IssueGroup title="待办" issues={[makeIssue()]} />);
    expect(document.body.textContent).toContain(commitmentText);
    cleanup();
  });

  it("uses a styled fallback when a commitment has progress but no text", () => {
    const cleanup = render(<IssueGroup title="待办" issues={[makeCommitmentWithoutProgressText()]} />);
    const progress = document.querySelector(".issue-commitment-progress");
    expect(progress?.textContent).toBe("未知进度");
    cleanup();
  });

  it("does not show fallback progress for ordinary issues", () => {
    const cleanup = render(<IssueGroup title="待办" issues={[makeOrdinaryIssueWithoutProgressText()]} />);
    expect(document.body.textContent).not.toContain("未知进度");
    expect(document.querySelector(".issue-commitment-progress")).toBeNull();
    cleanup();
  });

  it("shows commitment progress in the situation detail", () => {
    const cleanup = render(
      <SituationDetailModal issue={makeIssue()} onClose={() => undefined} />
    );
    expect(document.body.textContent).toContain(commitmentText);
    cleanup();
  });

  it("shows commitment progress in the situation hover tooltip", () => {
    const cleanup = render(<SituationRow issue={makeIssue()} />);
    const row = document.querySelector(".situation-row") as HTMLDivElement;
    row.getBoundingClientRect = () => ({
      x: 10,
      y: 20,
      width: 200,
      height: 48,
      top: 20,
      right: 210,
      bottom: 68,
      left: 10,
      toJSON: () => ({}),
    });

    act(() => {
      row.dispatchEvent(
        new MouseEvent("mouseover", { bubbles: true, relatedTarget: document.body })
      );
    });

    expect(document.body.textContent).toContain("承诺进度");
    expect(document.body.textContent).toContain(commitmentText);
    cleanup();
  });
});

describe("empty bar label presentation (#626)", () => {
  function makeEmptyBarIssue(): Issue {
    return {
      ...makeIssue(),
      bar_good_meaning: "",
      bar_bad_meaning: "",
      tags: [],
    };
  }

  it("detail modal omits empty parentheses when bar meanings are blank", () => {
    const cleanup = render(
      <SituationDetailModal issue={makeEmptyBarIssue()} onClose={() => undefined} />
    );
    const text = document.body.textContent || "";
    expect(text).toContain("达成");
    expect(text).toContain("失败");
    expect(text).not.toContain("达成（）");
    expect(text).not.toContain("失败（）");
    cleanup();
  });

  it("detail modal keeps parentheses when bar meanings are present", () => {
    const cleanup = render(
      <SituationDetailModal issue={makeIssue()} onClose={() => undefined} />
    );
    const text = document.body.textContent || "";
    expect(text).toContain("达成（欠饷清偿）");
    expect(text).toContain("失败（军心溃散）");
    cleanup();
  });

  it("issue board progress ends stay blank rather than showing empty labels", () => {
    const cleanup = render(<IssueGroup title="待办" issues={[makeEmptyBarIssue()]} />);
    const ends = Array.from(document.querySelectorAll(".issue-progress > span"));
    expect(ends).toHaveLength(2);
    expect(ends.every((el) => (el.textContent || "").trim() === "")).toBe(true);
    cleanup();
  });
});

describe("#1726 StateModal 奏疏收件箱", () => {
  function baseState(memorials: GameState["memorials"] = []): GameState {
    return {
      turn: { year: 1627, period: 10, turn: 1, phase: "player" },
      metrics: {},
      previous_summary: "",
      issues: [makeIssue()],
      memorials,
      unread_memorial_count: (memorials || []).filter((m) => m.unread).length,
      legacies: [],
      closed_this_turn: [],
      budget: {
        国库: { balance: 0, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0 },
        内库: { balance: 0, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0 },
        army_pay_due_total: 0,
        settled_army_pay: null,
      },
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
    };
  }

  it("呈真实奏疏正文与上疏人；不借局势 issues；不渲染结构化字段", () => {
    const body = "臣已拨银十万两，库藏尚可周转。";
    const cleanup = render(
      <StateModal
        state={baseState([
          {
            key: "progress:7",
            kind: "progress",
            turn: 1,
            author_name: "杨嗣昌",
            memorial_text: body,
            unread: true,
          },
        ])}
      />,
    );

    const doc = document.querySelector(".state-document");
    expect(doc).toBeTruthy();
    expect(doc!.querySelector(".situation-panel")).toBeNull();
    expect(doc!.querySelector(".situation-row")).toBeNull();
    expect(doc!.textContent).not.toContain(makeIssue().title);
    expect(doc!.textContent).toContain("杨嗣昌");
    expect(doc!.querySelector("pre.memorial-text")?.textContent).toBe(body);
    expect(doc!.textContent).not.toContain("progress:7");
    expect(doc!.textContent).not.toContain("progress_band");
    expect(doc!.textContent).not.toContain("本月无疏");
    cleanup();
  });

  it("无奏疏时示空态，不因有局势而填充", () => {
    const cleanup = render(<StateModal state={baseState([])} />);
    expect(document.body.textContent).toContain("本月无疏");
    expect(document.querySelector(".situation-panel")).toBeNull();
    cleanup();
  });

  it("SituationPanel 真渲染有议题时不返回 null", () => {
    const issue = makeIssue();
    const cleanup = render(
      <SituationPanel issues={[issue]} closedIssues={[]} hasLegacies={false} />
    );
    expect(document.querySelector(".situation-panel")).toBeTruthy();
    expect(document.body.textContent).toContain(issue.title);
    cleanup();
  });
});
