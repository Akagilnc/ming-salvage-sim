import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { IssueGroup, SituationDetailModal, SituationRow } from "./situation";
import type { Issue } from "../types";

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
