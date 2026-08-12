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

afterEach(() => { document.body.innerHTML = ""; });

describe("DecisionModal", () => {
  it("uses a non-main full-screen container inside the app landmark", () => {
    const cleanup = render(<DecisionModal decisions={decisions} onResolve={vi.fn()} />);
    const page = document.querySelector<HTMLElement>(".decision-page");

    expect(page?.tagName).toBe("SECTION");
    expect(page?.querySelector("main")).toBeNull();
    cleanup();
  });

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

    expect(document.querySelector(".decision-document-section h3")?.textContent).toBe("河工修治");
    expect(document.activeElement).toBe(document.querySelector<HTMLButtonElement>(".decision-option"));
    cleanup();
  });

  it("assembles each decision as ordered sections of one red-seal document", () => {
    const cleanup = render(<DecisionModal decisions={decisions} onResolve={vi.fn()} />);
    const documentPage = document.querySelector<HTMLElement>(".decision-document");
    expect(documentPage).not.toBeNull();
    expect(documentPage!.querySelector(".decision-document-section:nth-of-type(1) .decision-section-label")?.textContent).toBe("疏文");
    expect(documentPage!.querySelector(".decision-document-section:nth-of-type(1) h3")?.textContent).toBe("关宁军饷");
    expect(documentPage!.querySelector(".decision-document-section:nth-of-type(2) .decision-section-label")?.textContent).toBe("内阁票拟");
    expect(documentPage!.querySelector(".decision-document-section:nth-of-type(2) .decision-option-label")?.textContent).toBe("拟批：拨帑速发");
    expect(documentPage!.querySelector(".decision-document-section:nth-of-type(3) label")?.textContent).toBe("朱笔亲批");
    expect(documentPage!.querySelector(".decision-seal")?.getAttribute("aria-label")).toBe("批红落印");
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(document.body.textContent).toContain("河工修治");
    cleanup();
  });

  it("renders no page for a month with no decisions", () => {
    const cleanup = render(<DecisionModal decisions={[]} onResolve={vi.fn()} />);
    expect(document.querySelector(".decision-page")).toBeNull();
    cleanup();
  });

  it("requires a listed rescript action for dossier memorials", () => {
    const onResolve = vi.fn();
    const dossierDecision: PendingDecision = {
      ...decisions[0],
      event_id: "dossier:42",
      rejection_reason: "科臣封驳，谓此旨有碍成宪。",
      opposition: "都给事中韩一良（东林）",
      options: [{
        label: "强颁", hint: "以中旨颁行。",
        dossier_id: 42, dossier_decision: "force_promulgated",
      }],
    };
    const cleanup = render(<DecisionModal decisions={[dossierDecision]} onResolve={onResolve} />);
    expect(document.body.textContent).toContain("科臣封驳，谓此旨有碍成宪。");
    expect(document.body.textContent).toContain("都给事中韩一良（东林）");
    expect(document.body.textContent).not.toContain("six_offices");
    expect(document.body.textContent).not.toContain("faction");
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

  it("keeps the handwritten reply in the existing resolve payload", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    const note = document.querySelector<HTMLTextAreaElement>("textarea");
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理，不得有误。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{ note: "着即办理，不得有误。" }]);
    cleanup();
  });

  it("keeps the selected memorial's label and hint in the existing resolve payload", () => {
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => document.querySelector<HTMLButtonElement>(".decision-confirm")!.click());
    expect(onResolve).toHaveBeenCalledWith([{ label: "拨帑速发", hint: "先解燃眉之急。" }]);
    cleanup();
  });

  it("rejects the whole batch when any item is not a valid PendingDecision (reject-whole-batch guard)", () => {
    const mixedEventStream = [
      decisions[0],
      { id: 17, text: "着户部核拨军饷", status: "approved", source: "proactive" },
    ];
    const result = pendingDecisionsFrom(mixedEventStream);
    expect(result).toEqual([]);
    const cleanup = render(<DecisionModal decisions={result} onResolve={vi.fn()} />);
    expect(document.body.textContent).not.toContain("着户部核拨军饷");
    cleanup();
  });
});
