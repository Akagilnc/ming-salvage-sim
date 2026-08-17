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

/** Resolve clamp(minpx, Nvw, maxpx) against a viewport width. */
function resolveClamp(minPx: number, vw: number, maxPx: number, viewportWidth: number) {
  return Math.min(maxPx, Math.max(minPx, (vw / 100) * viewportWidth));
}

function parseClamp(text: string): { minPx: number; vw: number; maxPx: number } | null {
  const m = text.match(/clamp\(\s*([\d.]+)px\s*,\s*([\d.]+)vw\s*,\s*([\d.]+)px\s*\)/i);
  if (!m) return null;
  return { minPx: Number(m[1]), vw: Number(m[2]), maxPx: Number(m[3]) };
}

function firstMatch(css: string, re: RegExp): string {
  const m = css.match(re);
  if (!m) throw new Error(`decision.css missing token /${re.source}/`);
  return m[1];
}

function pxToken(css: string, re: RegExp, fallback = 0): number {
  const m = css.match(re);
  return m ? Number(m[1]) : fallback;
}

/**
 * Block-flow estimator for the decision page at a fixed viewport.
 * jsdom has no layout engine; chrome tokens are read from decision.css so a
 * too-tall page layout fails this budget check for the standard fixture.
 */
function estimateConfirmBottom(css: string, viewportWidth: number) {
  const pagePad = parseClamp(firstMatch(css, /\.decision-page\s*\{[^}]*padding:\s*([^;]+);/s));
  const docPad = parseClamp(firstMatch(css, /\.decision-document\s*\{[^}]*padding:\s*([^;]+);/s));
  const shellPad = parseClamp(firstMatch(css, /\.decision-document section\s*\{[^}]*padding:\s*([^;]+);/s));
  if (!pagePad || !docPad || !shellPad) throw new Error("decision.css vertical clamp tokens unreadable");

  const pagePadY = resolveClamp(pagePad.minPx, pagePad.vw, pagePad.maxPx, viewportWidth);
  const docPadY = resolveClamp(docPad.minPx, docPad.vw, docPad.maxPx, viewportWidth);
  const sectionPad = resolveClamp(shellPad.minPx, shellPad.vw, shellPad.maxPx, viewportWidth);

  const sectionPadBottom = pxToken(css, /\.decision-document-section\s*\{[^}]*padding:\s*[\d.]+px\s+[\d.]+px\s+([\d.]+)px/s, 22);
  const sectionGap = pxToken(css, /\.decision-document-section \+ \.decision-document-section\s*\{[^}]*margin-top:\s*([\d.]+)px/s, 15);
  const headMargin = pxToken(css, /\.decision-head\s*\{[^}]*margin-bottom:\s*([\d.]+)px/s, 14);
  const optionsGap = pxToken(css, /\.decision-options\s*\{[^}]*gap:\s*([\d.]+)px/s, 10);
  const optionPadY = pxToken(css, /\.decision-option\s*\{[^}]*padding:\s*([\d.]+)px/s, 13);
  const noteMinH = pxToken(css, /\.decision-note\s*\{[^}]*min-height:\s*([\d.]+)px/s, 64);
  const noteMarginTop = pxToken(css, /\.decision-document \.decision-note\s*\{[^}]*margin-top:\s*([\d.]+)px/s, 10);
  // 印即确认键：.decision-confirm 自身呈印章，无独立装饰 seal
  const confirmMarginTop = pxToken(css, /\.decision-document \.decision-confirm\s*\{[^}]*margin:\s*([\d.]+)px/s, 10)
    || pxToken(css, /\.decision-confirm\s*\{[^}]*margin:\s*([\d.]+)px/s, 10);
  const confirmPadY = pxToken(css, /\.decision-document \.decision-confirm\s*\{[^}]*padding:\s*([\d.]+)px/s, 8)
    || pxToken(css, /\.decision-confirm\s*\{[^}]*padding:\s*([\d.]+)px/s, 8);
  const actionsMarginTop = pxToken(css, /\.decision-actions\s*\{[^}]*margin-top:\s*([\d.]+)px/s, 8);
  const actionsMinH = pxToken(css, /\.decision-actions\s*\{[^}]*min-height:\s*([\d.]+)px/s, 18);
  const pagePadX = parseClamp(firstMatch(css, /\.decision-page\s*\{[^}]*padding:\s*[^\s]+\s+([^;]+);/s));
  const docPadXClamp = (() => {
    // padding: Y X — capture X clamp
    const m = css.match(/\.decision-document\s*\{[^}]*padding:\s*clamp\([^)]+\)\s+(clamp\([^)]+\))/s);
    return m ? parseClamp(m[1]) : null;
  })();

  const doc = document.querySelector<HTMLElement>(".decision-document");
  const confirm = document.querySelector<HTMLElement>(".decision-confirm");
  if (!doc || !confirm) throw new Error("decision fixture missing");

  const padX = pagePadX ? resolveClamp(pagePadX.minPx, pagePadX.vw, pagePadX.maxPx, viewportWidth) : 12;
  const docPadX = docPadXClamp
    ? resolveClamp(docPadXClamp.minPx, docPadXClamp.vw, docPadXClamp.maxPx, viewportWidth)
    : 24;
  const innerWidth = Math.min(880, viewportWidth - 2 * padX) - 2 * docPadX;
  const contentWidth = Math.max(120, innerWidth - 2 * sectionPad);

  const measureTextBlock = (el: Element | null, fontPx: number, lineHeight: number, widthPx: number) => {
    if (!el) return 0;
    const text = (el.textContent || "").trim();
    if (!text) return 0;
    const charsPerLine = Math.max(1, Math.floor(widthPx / fontPx));
    return Math.ceil(text.length / charsPerLine) * fontPx * lineHeight;
  };

  let y = pagePadY + docPadY;

  const head = doc.querySelector(".decision-head");
  if (head) {
    y += headMargin;
    y += 13 + 8; // kicker font + margin-bottom
    y += 22; // title line
  }

  const shell = doc.querySelector(".decision-document > section");
  if (shell) y += sectionPad;

  const sections = Array.from(doc.querySelectorAll(".decision-document-section"));
  sections.forEach((section, index) => {
    if (index > 0) y += sectionGap;
    y += 4 + sectionPadBottom;
    const label = section.querySelector(".decision-section-label");
    y += measureTextBlock(label, 14, 1.4, contentWidth) || 18;
    if (section.querySelector("h3")) y += 2 + 6 + 20;
    section.querySelectorAll("p").forEach((p) => { y += measureTextBlock(p, 14, 1.8, contentWidth); });
    const options = Array.from(section.querySelectorAll(".decision-option"));
    options.forEach((opt, optIndex) => {
      if (optIndex > 0) y += optionsGap;
      y += optionPadY * 2;
      y += measureTextBlock(opt.querySelector(".decision-option-label"), 16, 1.3, contentWidth - 28);
      y += measureTextBlock(opt.querySelector(".decision-option-hint"), 13, 1.5, contentWidth - 28);
    });
    if (section.querySelector(".decision-note")) {
      y += noteMarginTop + noteMinH;
    }
  });

  // 印章确认键在文书 section 内（朱笔亲批之后）
  if (doc.querySelector(".decision-confirm")) {
    y += confirmMarginTop + confirmPadY * 2 + 18; // line box for seal text
  }
  if (shell) y += sectionPad;

  y += actionsMarginTop + actionsMinH; // hint line only
  y += docPadY + pagePadY;
  return y;
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
  it("keeps seal-confirm bounding-box bottom within the 1440×900 first screen", () => {
    injectDecisionCss();
    const cleanup = render(<DecisionModal decisions={[decisions[0]]} onResolve={vi.fn()} />);
    const confirmBottom = estimateConfirmBottom(DECISION_CSS, 1440);
    expect(confirmBottom).toBeLessThanOrEqual(900);
    cleanup();
  });

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

    // 印章视觉：双线朱红边 + 可点 cursor（非装饰去按钮化）
    const sealRule = ruleExact(".decision-document .decision-confirm") || ruleExact(".decision-confirm");
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

    // 路二 a：择一票拟 → 可点
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
    const focusRule = ruleExact(".decision-document .decision-option:focus-visible")
      || ruleExact(".decision-option:focus-visible")
      || ruleExact(".decision-document .decision-option:focus")
      || ruleExact(".decision-option:focus");

    expect(hoverRule).toBeTruthy();
    expect(pickedRule).toBeTruthy();
    expect(focusRule).toBeTruthy();

    const hoverKey = `${hoverRule!.style.borderColor}|${hoverRule!.style.background}|${hoverRule!.style.boxShadow}`;
    const pickedKey = `${pickedRule!.style.borderColor}|${pickedRule!.style.background}|${pickedRule!.style.boxShadow}`;
    expect(hoverKey).not.toBe(pickedKey);

    const focusKey = `${focusRule!.style.outline}|${focusRule!.style.outlineColor}|${focusRule!.style.boxShadow}`;
    const pickedFocusComparable = `${pickedRule!.style.outline}|${pickedRule!.style.outlineColor}|${pickedRule!.style.boxShadow}`;
    expect(focusKey).not.toBe(pickedFocusComparable);
    // Focus ring must carry a visible outline the picked fill does not use as its sole cue.
    expect((focusRule!.style.outline || focusRule!.style.outlineColor || "").length).toBeGreaterThan(0);

    const options = document.querySelectorAll<HTMLButtonElement>(".decision-option");
    expect(options[0].classList.contains("is-picked")).toBe(false);
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
});
