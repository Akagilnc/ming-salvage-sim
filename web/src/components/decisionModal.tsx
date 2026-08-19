import React from "react";
import type {
  DecisionChoice, PendingActionFailure, PendingDecision,
} from "../types";

function isCheatConsoleTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(".cheat-console") !== null;
}

export function DecisionModal({
  decisions,
  failures = [],
  onResolve,
}: {
  decisions: PendingDecision[];
  failures?: PendingActionFailure[];
  onResolve: (choices: DecisionChoice[]) => void;
}) {
  const [cursor, setCursor] = React.useState(0);
  const [picks, setPicks] = React.useState<DecisionChoice[]>(() => decisions.map(() => ({})));
  const pageRef = React.useRef<HTMLElement>(null);

  const cur = decisions[cursor];
  const pick = picks[cursor] || {};
  const requiresListedChoice = (cur?.event_id || "").startsWith("dossier:");
  const decided = requiresListedChoice
    ? !!pick.label
    : !!(pick.label || (pick.note || "").trim());
  const last = cursor >= decisions.length - 1;
  const setPick = (choice: DecisionChoice) => setPicks((all) => all.map((item, i) => i === cursor ? { ...item, ...choice } : item));

  const next = () => {
    if (!decided) return;
    if (last) onResolve(picks);
    else setCursor((value) => value + 1);
  };

  React.useEffect(() => {
    const page = pageRef.current;
    if (!page) return;

    const focusableSelector = [
      "button:not([disabled])",
      "textarea:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "a[href]",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const focusables = () => Array.from(page.querySelectorAll<HTMLElement>(focusableSelector));
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const keepFocusInPage = (event: KeyboardEvent) => {
      if (isCheatConsoleTarget(event.target)) return;
      if (event.ctrlKey && (event.key === "~" || event.key === "`")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        (focusables()[0] || page).focus();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusables();
      if (!elements.length) {
        event.preventDefault();
        page.focus();
        return;
      }

      const activeIndex = elements.indexOf(document.activeElement as HTMLElement);
      if (activeIndex === -1) {
        event.preventDefault();
        elements[event.shiftKey ? elements.length - 1 : 0].focus();
      } else if (event.shiftKey && activeIndex === 0) {
        event.preventDefault();
        elements[elements.length - 1].focus();
      } else if (!event.shiftKey && activeIndex === elements.length - 1) {
        event.preventDefault();
        elements[0].focus();
      }
    };

    const keepFocusInPageOnFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && page.contains(event.target)) return;
      if (isCheatConsoleTarget(event.target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      (focusables()[0] || page).focus();
    };

    document.addEventListener("keydown", keepFocusInPage, true);
    document.addEventListener("focusin", keepFocusInPageOnFocus, true);
    return () => {
      document.removeEventListener("keydown", keepFocusInPage, true);
      document.removeEventListener("focusin", keepFocusInPageOnFocus, true);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [decisions.length]);

  React.useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const firstFocusable = page.querySelector<HTMLElement>(
      "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
    );
    if (isCheatConsoleTarget(document.activeElement)) return;
    (firstFocusable || page).focus();
  }, [cursor, decisions.length]);

  if (decisions.length === 0) return null;

  return (
    <section
      ref={pageRef}
      className="decision-page"
      role="dialog"
      aria-modal="true"
      aria-labelledby="decision-page-title"
      tabIndex={-1}
    >
      <article className="decision-document">
        <div className="decision-head">
          <span className="decision-kicker" aria-live="polite">月末批红 · 第 {cursor + 1} / {decisions.length} 疏</span>
          <h2 id="decision-page-title" className="decision-title">奏疏批红</h2>
        </div>
        {failures.length ? <div className="decision-failure-list" role="alert">
          {failures.map((failure) => <div className="decision-failure-item" key={failure.id}>{failure.message}</div>)}
        </div> : null}
        <section aria-labelledby="decision-document-title">
          <div className="decision-document-section">
            <span className="decision-section-label">疏文</span>
            <h3 id="decision-document-title">{cur.title}</h3>
            <p>{cur.context || "臣等谨陈时局，请陛下裁夺。"}</p>
          </div>
          {cur.rejection_reason || cur.opposition ? <div className="decision-document-section">
            <span className="decision-section-label">封驳具由</span>
            {cur.rejection_reason ? <p>{cur.rejection_reason}</p> : null}
            {cur.opposition ? <p>持议者：{cur.opposition}</p> : null}
          </div> : null}
          <div className="decision-document-section">
            <span className="decision-section-label">内阁票拟</span>
            <div className="decision-options">
              {cur.options.map((option) => <button key={option.label} className={"decision-option" + (pick.label === option.label ? " is-picked" : "")} onClick={() => setPick(option)}>
                <span className="decision-option-label">拟批：{option.label}</span>
                {option.hint ? <span className="decision-option-hint">{option.hint}</span> : null}
              </button>)}
            </div>
          </div>
          <div className="decision-document-section decision-red-pen">
            <label className="decision-section-label" htmlFor="decision-note">朱笔亲批</label>
            <textarea id="decision-note" className="decision-note" placeholder="亲笔补批（可选）" value={pick.note || ""} onChange={(event) => setPick({ note: event.target.value })} />
          </div>
          {/* 印即确认键：复用既有 decision-confirm handler，不另挂第二控件 */}
          <button
            type="button"
            className="decision-confirm"
            disabled={!decided}
            onClick={next}
            aria-label={last ? "批红落印，续推时局" : "批下一疏"}
          >
            {last ? "批红落印" : "批下一疏"}
          </button>
        </section>
        <div className="decision-actions">
          <span className="decision-hint-line">{decided ? "已择，落印即行。" : requiresListedChoice ? "此疏须择一票拟。" : "请择一票拟，或亲笔批示。"}</span>
        </div>
      </article>
    </section>
  );
}
