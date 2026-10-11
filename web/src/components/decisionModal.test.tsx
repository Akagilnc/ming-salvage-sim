import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DecisionModal } from "./decisionModal";
import { pendingDecisionsFrom } from "../decisionRouting";
import type { PendingDecision } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const decisions: PendingDecision[] = [
  {
    idx: 0,
    title: "关宁军饷",
    context: "辽东急报：军中已三月未饷。",
    options: [
      { label: "拨帑速发", hint: "先解燃眉之急。" },
      { label: "暂缓拨付", hint: "留银以备京师。" },
    ],
  },
  {
    idx: 1,
    title: "河工修治",
    context: "河决在即，地方请银修堤。",
    options: [{ label: "拨银修堤", hint: "保住沿河百姓。" }],
  },
];

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return () => act(() => { root.unmount(); host.remove(); });
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("DecisionModal", () => {

  it("exposes a modal dialog and keeps keyboard focus inside the red-seal page", () => {
    const background = document.createElement("button");
    background.textContent = "底层 HUD 控件";
    document.body.appendChild(background);
    background.focus();

    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const page = document.querySelector<HTMLElement>(".decision-page");
    const options = document.querySelectorAll<HTMLButtonElement>(".decision-option");
    const option = options[0];
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note");
    const confirm = document.querySelector<HTMLButtonElement>(".decision-confirm");

    expect(page?.getAttribute("role")).toBe("dialog");
    expect(page?.getAttribute("aria-modal")).toBe("true");
    expect(page?.getAttribute("aria-labelledby")).toBe("decision-page-title");
    expect(document.activeElement).toBe(option);

    act(() => background.focus());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true })));
    expect(document.activeElement).toBe(option);

    act(() => note!.focus());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true })));
    expect(document.activeElement).toBe(option);

    act(() => option!.focus());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true })));
    expect(document.activeElement).toBe(note);

    act(() => option!.click());
    act(() => confirm!.focus());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true })));
    expect(document.activeElement).toBe(option);

    act(() => option!.focus());
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true })));
    expect(document.activeElement).toBe(confirm);

    cleanup();
    expect(document.activeElement).toBe(background);
  });

  it("blocks background focus and shortcuts while the red-seal page is open", () => {
    const background = document.createElement("button");
    background.textContent = "底层 HUD 控件";
    document.body.appendChild(background);
    const shortcut = vi.fn();
    window.addEventListener("keydown", shortcut);

    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const option = document.querySelector<HTMLButtonElement>(".decision-option");
    const event = new KeyboardEvent("keydown", { key: "`", ctrlKey: true, bubbles: true, cancelable: true });

    act(() => background.focus());
    expect(document.activeElement).toBe(option);

    act(() => document.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(shortcut).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(option);

    window.removeEventListener("keydown", shortcut);
    cleanup();
  });

  it("leaves focus and Ctrl+` available to a cheat console opened before decisions arrive", () => {
    const cheatConsole = document.createElement("div");
    cheatConsole.className = "cheat-console";
    const cheatInput = document.createElement("textarea");
    cheatConsole.appendChild(cheatInput);
    document.body.appendChild(cheatConsole);
    cheatInput.focus();

    const closeCheatConsole = vi.fn();
    const shortcut = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key === "`") closeCheatConsole();
    };
    window.addEventListener("keydown", shortcut);

    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    expect(document.activeElement).toBe(cheatInput);

    const event = new KeyboardEvent("keydown", { key: "`", ctrlKey: true, bubbles: true, cancelable: true });
    act(() => cheatInput.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
    expect(closeCheatConsole).toHaveBeenCalledOnce();

    window.removeEventListener("keydown", shortcut);
    cleanup();
  });

  it("moves focus to the next memorial when continuing to the next decision", () => {
    const cleanup = render(<DecisionModal decisions={decisions} onResolve={vi.fn()} />);
    const options = document.querySelectorAll<HTMLButtonElement>(".decision-option");
    const confirm = document.querySelector<HTMLButtonElement>(".decision-confirm");

    act(() => options[0].click());
    act(() => confirm!.click());

    expect(document.activeElement).toBe(document.querySelector<HTMLButtonElement>(".decision-option"));
    expect(document.querySelector(".decision-document-section h3")?.textContent).toBe("河工修治");
    cleanup();
  });

  it("renders no page for a month with no decisions", () => {
    const cleanup = render(<DecisionModal decisions={[]} onResolve={vi.fn()} />);
    expect(document.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("requires a listed rescript action for dossier memorials", () => {
    const onResolve = vi.fn();
    const rejectionReasonMarker = "__opaque_rejection_reason_614__";
    const oppositionMarker = "__opaque_opposition_614__";
    const dossierDecision: PendingDecision = {
      ...decisions[0],
      event_id: "dossier:42",
      rejection_reason: rejectionReasonMarker,
      opposition: oppositionMarker,
      options: [{
        label: "强颁", hint: "以中旨颁行。",
        dossier_id: 42, dossier_decision: "force_promulgated",
      }],
    };
    const cleanup = render(<DecisionModal decisions={[dossierDecision]} onResolve={onResolve} />);
    const rejectionSection = Array.from(document.querySelectorAll(".decision-document-section")).find((section) => {
      const paragraphs = Array.from(section.querySelectorAll("p")).map((p) => p.textContent || "");
      return paragraphs.some((text) => text === rejectionReasonMarker)
        && paragraphs.some((text) => text.includes(oppositionMarker));
    });
    expect(rejectionSection).toBeTruthy();
    const note = document.querySelector<HTMLTextAreaElement>("textarea")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "朕意已决。");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelector<HTMLButtonElement>(".decision-confirm")!.disabled).toBe(true);
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{
      label: "强颁", hint: "以中旨颁行。",
      dossier_id: 42, dossier_decision: "force_promulgated",
      note: "朕意已决。",
    }]);
    cleanup();
  });

});

describe("DecisionModal #1202 seal-is-confirm first screen + pick affordance", () => {

  it("disables the seal only when no pick and handwritten note is empty; either path enables", () => {
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirm = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    const options = () => document.querySelectorAll<HTMLButtonElement>(".decision-option");

    // 路一：未择且批示空 → 禁用 + 提示
    expect(confirm().disabled).toBe(true);

    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);

    // 路二 a：择一票拟 → 可点；#1385 底栏文案态须反映已择
    act(() => options()[0].click());
    expect(confirm().disabled).toBe(false);
    expect(options()[0].classList.contains("is-picked")).toBe(true);

    cleanup();

    // 路二 b：仅亲笔批示有内容 → 可点（ADR 0043 留门）
    const cleanupNote = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);
    expect(confirm().disabled).toBe(false);
    cleanupNote();
  });

  it("submits via the existing decision-confirm handler path with zero payload drift", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    act(() => document.querySelectorAll<HTMLButtonElement>(".decision-option")[0].click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledOnce();
    expect(onResolve).toHaveBeenCalledWith([{ label: "拨帑速发", hint: "先解燃眉之急。" }]);
    cleanup();

    const onResolveNote = vi.fn();
    const cleanupNote = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolveNote} />);
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理，不得有误。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolveNote).toHaveBeenCalledWith([{ note: "着即办理，不得有误。" }]);
    cleanupNote();
  });

});
