import React, { act } from "react";
import { readFileSync } from "node:fs";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DecisionModal } from "./decisionModal";
import { pendingDecisionsFrom } from "../decisionRouting";
import type { PendingDecision } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DECISION_CSS = readFileSync(`${process.cwd()}/src/styles/decision.css`, "utf8");

function injectDecisionCss() {
  const style = document.createElement("style");
  style.setAttribute("data-decision-fixture", "true");
  style.textContent = DECISION_CSS;
  document.head.appendChild(style);
  return style;
}

function cssRulesMatching(substr: string): CSSStyleRule[] {
  const matched: CSSStyleRule[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule && rule.selectorText.includes(substr)) matched.push(rule);
    }
  }
  return matched;
}

function ruleExact(selector: string): CSSStyleRule | undefined {
  return cssRulesMatching(selector).find((rule) => rule.selectorText === selector);
}


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

beforeEach(() => {
  document.querySelectorAll("[data-decision-fixture]").forEach((node) => node.remove());
});

afterEach(() => {
  document.querySelectorAll("[data-decision-fixture]").forEach((node) => node.remove());
  document.body.innerHTML = "";
  document.head.querySelectorAll("[data-decision-fixture]").forEach((node) => node.remove());
});

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
    // 印即确认键：文书序末位为 .decision-confirm 真按钮，无独立装饰 seal
    const sealConfirm = documentPage!.querySelector<HTMLButtonElement>(".decision-confirm");
    expect(sealConfirm).not.toBeNull();
    expect(sealConfirm!.tagName).toBe("BUTTON");
    expect(documentPage!.querySelector(".decision-seal")).toBeNull();
    expect(document.querySelectorAll(".decision-confirm")).toHaveLength(1);
    act(() => document.querySelector<HTMLButtonElement>(".decision-option")!.click());
    act(() => sealConfirm!.click());
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

describe("DecisionModal #1202 seal-is-confirm first screen + pick affordance", () => {
  it("makes the unique decision-confirm the seal button with no parallel decorative seal", () => {
    injectDecisionCss();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirms = document.querySelectorAll(".decision-confirm");
    expect(confirms).toHaveLength(1);
    expect(document.querySelector(".decision-seal")).toBeNull();

    const seal = confirms[0] as HTMLButtonElement;
    expect(seal.tagName).toBe("BUTTON");
    expect(seal.getAttribute("aria-hidden")).not.toBe("true");
    expect(seal.disabled).toBe(true);

    // 印章样式只在文书作用域一份；不得保留全局 .decision-confirm 平行兜底
    expect(ruleExact(".decision-confirm")).toBeUndefined();
    const sealRule = ruleExact(".decision-document .decision-confirm");
    expect(sealRule).toBeTruthy();
    expect(sealRule!.style.pointerEvents === "" || sealRule!.style.pointerEvents === "auto").toBe(true);
    expect(sealRule!.style.cursor).toBe("pointer");
    expect(sealRule!.style.border.includes("double") || sealRule!.style.borderStyle === "double").toBe(true);
    cleanup();
  });

  it("disables the seal only when no pick and handwritten note is empty; either path enables", () => {
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirm = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    const options = () => document.querySelectorAll<HTMLButtonElement>(".decision-option");
    const hint = () => document.querySelector(".decision-hint-line")?.textContent || "";

    // 路一：未择且批示空 → 禁用 + 提示
    expect(confirm().disabled).toBe(true);
    expect(hint()).toContain("请择一票拟，或亲笔批示。");
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);

    // 路二 a：择一票拟 → 可点；#1385 底栏文案态须反映已择
    act(() => options()[0].click());
    expect(confirm().disabled).toBe(false);
    expect(options()[0].classList.contains("is-picked")).toBe(true);
    expect(hint()).toMatch(/已择|落印/);
    expect(hint()).not.toContain("请择一票拟");
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

  it("mechanically distinguishes hover, focus ring, and is-picked styles", () => {
    injectDecisionCss();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);

    // Root fix: hover and is-picked must not share one selector list.
    const shared = cssRulesMatching("decision-option").filter((rule) =>
      rule.selectorText.includes(":hover") && rule.selectorText.includes("is-picked"),
    );
    expect(shared).toEqual([]);

    const hoverRule = ruleExact(".decision-document .decision-option:hover")
      || ruleExact(".decision-option:hover");
    const pickedRule = ruleExact(".decision-document .decision-option.is-picked")
      || ruleExact(".decision-option.is-picked");
    // #1434②：开屏 autofocus 的 :focus 不得冒充已选；焦点环走 :focus-visible
    const focusRule = ruleExact(".decision-document .decision-option:focus-visible")
      || ruleExact(".decision-option:focus-visible");
    const bareFocusRules = cssRulesMatching("decision-option").filter((rule) =>
      /\.decision-option:focus(?!-visible)/.test(rule.selectorText)
      || /\.decision-document \.decision-option:focus(?!-visible)/.test(rule.selectorText),
    );

    expect(hoverRule).toBeTruthy();
    expect(pickedRule).toBeTruthy();
    expect(focusRule).toBeTruthy();
    expect(bareFocusRules).toEqual([]);

    const hoverKey = `${hoverRule!.style.borderColor}|${hoverRule!.style.background}|${hoverRule!.style.boxShadow}`;
    const pickedKey = `${pickedRule!.style.borderColor}|${pickedRule!.style.background}|${pickedRule!.style.boxShadow}`;
    expect(hoverKey).not.toBe(pickedKey);

    const focusKey = `${focusRule!.style.outline}|${focusRule!.style.outlineColor}|${focusRule!.style.boxShadow}`;
    const pickedFocusComparable = `${pickedRule!.style.outline}|${pickedRule!.style.outlineColor}|${pickedRule!.style.boxShadow}`;
    expect(focusKey).not.toBe(pickedFocusComparable);
    // Focus ring must carry a visible outline the picked fill does not use as its sole cue.
    expect((focusRule!.style.outline || focusRule!.style.outlineColor || "").length).toBeGreaterThan(0);

    const options = document.querySelectorAll<HTMLButtonElement>(".decision-option");
    // 真渲染：程序聚焦 ≠ 已选（is-picked 只由点击/择票拟写入）
    expect(options[0].classList.contains("is-picked")).toBe(false);
    act(() => options[0].focus());
    expect(document.activeElement).toBe(options[0]);
    expect(options[0].classList.contains("is-picked")).toBe(false);
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);

    act(() => options[0].click());
    expect(options[0].classList.contains("is-picked")).toBe(true);
    // Picked uses fill/border cue; focus rule uses outline — different channels.
    expect(pickedRule!.style.background || pickedRule!.style.borderColor).toBeTruthy();
    expect(focusRule!.style.outline.includes("none") || focusRule!.style.outline === "").toBe(false);

    cleanup();
  });

  it("keeps the three-state invariant for listed picks without sealing the handwritten-only path", () => {
    const cleanupListed = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirm = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    const options = () => document.querySelectorAll<HTMLButtonElement>(".decision-option");

    // 无择票拟 ⇔ 无选中样 ⇔ 确认不可用（须择票拟语义下）
    expect(options()[0].classList.contains("is-picked")).toBe(false);
    expect(options()[1].classList.contains("is-picked")).toBe(false);
    expect(confirm().disabled).toBe(true);

    act(() => options()[0].click());
    expect(options()[0].classList.contains("is-picked")).toBe(true);
    expect(confirm().disabled).toBe(false);

    cleanupListed();

    // 亲笔批示-only 路径（ADR 0043 留门）不得改死
    const onResolve = vi.fn();
    const cleanupNote = render(<DecisionModal decisions={[decisions[0]]} onResolve={onResolve} />);
    const note = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "着即办理。");
      (note as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);
    expect(confirm().disabled).toBe(false);
    act(() => confirm().click());
    expect(onResolve).toHaveBeenCalledWith([{ note: "着即办理。" }]);
    cleanupNote();

    // dossier 路径仍须择票拟：仅亲笔不可确认
    const dossierDecision: PendingDecision = {
      ...decisions[0],
      event_id: "dossier:7",
      options: [{
        label: "强颁", hint: "以中旨颁行。",
        dossier_id: 7, dossier_decision: "force_promulgated",
      }],
    };
    const cleanupDossier = render(<DecisionModal decisions={[dossierDecision]} onResolve={vi.fn()} />);
    const dossierNote = document.querySelector<HTMLTextAreaElement>(".decision-note")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(dossierNote, "朕意已决。");
      (dossierNote as HTMLTextAreaElement & { _valueTracker?: { setValue: (value: string) => void } })._valueTracker?.setValue("");
      dossierNote.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(confirm().disabled).toBe(true);
    expect(document.querySelectorAll(".decision-option.is-picked")).toHaveLength(0);
    expect(document.querySelector(".decision-hint-line")?.textContent).toContain("此疏须择一票拟。");
    cleanupDossier();
  });

  it("#657 同页两类 + 六动作可点 + 留中默认", () => {
    const mixed: PendingDecision[] = [
      {
        idx: 0,
        kind: "rescript_draft",
        decision_key: "rescript_draft:1:0",
        title: "陕西告饥",
        context: "秦地赤旱",
        actor_name: "杨嗣昌",
        options: [
          {
            label: "发帑赈济", hint: "所安者饥民",
            draft_capability: "cap1", action_type: "assignment",
            target_kind: "region", target_id: "shaanxi",
            locality_scope: "single", region_id: "shaanxi",
            transaction_category: "督赈",
          },
          { label: "缓征", hint: "h", draft_capability: "cap2" },
        ],
      },
      {
        idx: 1,
        kind: "decision",
        decision_key: "decision:1:1",
        title: "打回件",
        context: "科臣封驳",
        options: [
          { label: "准", hint: "" },
          { label: "驳", hint: "" },
        ],
      },
    ];
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={mixed} onResolve={onResolve} />);
    const confirmBtn = () => document.querySelector<HTMLButtonElement>(".decision-confirm")!;
    // 急务六钮
    const six = document.querySelector("[data-testid='rescript-six-actions']");
    expect(six).toBeTruthy();
    const actions = Array.from(document.querySelectorAll("[data-action]")).map(
      (el) => el.getAttribute("data-action"),
    );
    expect(actions).toEqual([
      "follow_draft", "return_revise", "midzhi", "deliberate", "hold", "summon",
    ]);
    // 显式留中可点并落印推进
    act(() => {
      (document.querySelector('[data-action="hold"]') as HTMLButtonElement).click();
    });
    expect(confirmBtn().disabled).toBe(false);
    act(() => confirmBtn().click());
    // 第二疏 decision
    expect(document.getElementById("decision-page-title")).toBeTruthy();
    act(() => {
      const opt = Array.from(document.querySelectorAll(".decision-option")).find(
        (b) => b.textContent?.includes("准"),
      ) as HTMLButtonElement;
      opt.click();
    });
    act(() => confirmBtn().click());
    expect(onResolve).toHaveBeenCalledTimes(1);
    const payload = onResolve.mock.calls[0][0];
    expect(payload[0].action).toBe("hold");
    expect(payload[0].decision_key).toBe("rescript_draft:1:0");
    expect(payload[1].label).toBe("准");
    expect(payload[1].decision_key).toBe("decision:1:1");
    cleanup();

    // V7：急务不点六钮 → 确认可点 → onResolve 该行无 action 且有 decision_key
    const onResolveDefault = vi.fn();
    const cleanupDefault = render(
      <DecisionModal decisions={[mixed[0]]} onResolve={onResolveDefault} />,
    );
    expect(document.querySelector<HTMLButtonElement>(".decision-confirm")!.disabled).toBe(false);
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolveDefault).toHaveBeenCalledTimes(1);
    const defPayload = onResolveDefault.mock.calls[0][0][0];
    expect(defPayload.decision_key).toBe("rescript_draft:1:0");
    expect(defPayload.action).toBeUndefined();
    cleanupDefault();
  });

  it("#657 跨月 draft idx=2 首行可点，submit 携带 decision_key（禁 idx===position 拒收）", () => {
    const crossMonth: PendingDecision[] = [
      {
        idx: 2,
        kind: "rescript_draft",
        source_turn: 3,
        decision_key: "rescript_draft:3:2",
        title: "跨月急务",
        context: "上月遗留",
        options: [
          {
            label: "发帑", hint: "h",
            draft_capability: "cap-x", action_type: "assignment",
            target_kind: "region", target_id: "shaanxi",
            locality_scope: "single", region_id: "shaanxi",
            transaction_category: "督赈",
          },
          { label: "缓", hint: "h", draft_capability: "cap-y" },
        ],
      },
    ];
    expect(pendingDecisionsFrom(crossMonth)).toEqual(crossMonth);
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={crossMonth} onResolve={onResolve} />);
    act(() => {
      (document.querySelector('[data-action="hold"]') as HTMLButtonElement).click();
    });
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolve).toHaveBeenCalledTimes(1);
    expect(onResolve.mock.calls[0][0][0].decision_key).toBe("rescript_draft:3:2");
    expect(onResolve.mock.calls[0][0][0].action).toBe("hold");
    cleanup();
  });

  it("#657 midzhi projects non-assignment §C.4 closed-set keys from selected option", () => {
    const decisions = [
      {
        idx: 0,
        kind: "rescript_draft",
        decision_key: "rescript_draft:1:0",
        title: "中旨非 assignment",
        context: "c",
        actor_name: "杨嗣昌",
        options: [
          {
            label: "加衔恩赏",
            hint: "荣誉",
            draft_capability: "cap-grant",
            action_type: "grant_allocation",
            grant_action: "加衔",
            target_kind: "character",
            target_id: "杨嗣昌",
            name: "杨嗣昌",
            locality_scope: "none",
            office: "太子太保",
          },
          { label: "备", hint: "h", draft_capability: "cap2" },
        ],
      },
    ];
    const onResolve = vi.fn();
    const cleanup = render(<DecisionModal decisions={decisions} onResolve={onResolve} />);
    // 先点选非 assignment option，再点中旨——投影须用选中项闭集键
    act(() => {
      const opt = Array.from(document.querySelectorAll(".decision-option")).find(
        (b) => b.textContent?.includes("加衔恩赏"),
      ) as HTMLButtonElement | undefined;
      opt?.click();
    });
    act(() => {
      (document.querySelector('[data-action="midzhi"]') as HTMLButtonElement).click();
    });
    act(() => {
      document.querySelector<HTMLButtonElement>(".decision-confirm")!.click();
    });
    expect(onResolve).toHaveBeenCalledTimes(1);
    const choice = onResolve.mock.calls[0][0][0];
    expect(choice.action).toBe("midzhi");
    // P7：decree_text 回退 label——必须保留所选 option 的 LLM 文案，禁结构钮文泄漏
    expect(choice.label).toBe("加衔恩赏");
    expect(choice.hint).toBe("荣誉");
    expect(choice.label).not.toBe("另旨·中旨");
    expect(String(choice.hint || "")).not.toBe("中旨直发");
    expect(choice.action_type).toBe("grant_allocation");
    expect(choice.grant_action).toBe("加衔");
    expect(choice.target_kind).toBe("character");
    expect(choice.target_id).toBe("杨嗣昌");
    expect(choice.name).toBe("杨嗣昌");
    expect(choice.office).toBe("太子太保");
    expect(choice.locality_scope).toBe("none");
    cleanup();
  });
});
