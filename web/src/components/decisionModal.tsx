import React from "react";
import type { DecisionChoice, PendingDecision } from "../types";

function isCheatConsoleTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(".cheat-console") !== null;
}

function decisionKeyOf(d: PendingDecision, fallbackIdx: number): string | undefined {
  if (d.decision_key) return String(d.decision_key);
  if (!d.kind) return undefined;
  const kind = (d.kind || "decision");
  const turn = d.source_turn ?? d.turn ?? 0;
  return `${kind}:${turn}:${d.idx ?? fallbackIdx}`;
}

export function DecisionModal({
  decisions,
  onResolve,
  busy = "",
  suspended = false,
}: {
  decisions: PendingDecision[];
  onResolve: (choices: DecisionChoice[]) => void | Promise<void>;
  /** truthy 时禁用票拟/亲批/翻页与落印，handler 入口短路——禁二提交。 */
  busy?: string;
  /** Keep picks mounted while the live gazette occupies the main face. */
  suspended?: boolean;
}) {
  const keyOf = (d: PendingDecision, i: number) => decisionKeyOf(d, i) ?? String(d.idx ?? i);
  const [currentKey, setCurrentKey] = React.useState(() => decisions[0] ? keyOf(decisions[0], 0) : "");
  const cursor = Math.max(0, decisions.findIndex((d, i) => keyOf(d, i) === currentKey));
  const [picks, setPicks] = React.useState<Record<string, { choice: DecisionChoice; sending?: boolean }>>({});
  const pageRef = React.useRef<HTMLElement>(null);
  const cur = decisions[cursor];
  const key = cur ? keyOf(cur, cursor) : "";
  const pick = picks[key]?.choice || {};
  const locked = !!busy || !!picks[key]?.sending;
  const requiresListedChoice = (cur?.event_id || "").startsWith("dossier:");
  const decided = requiresListedChoice
    ? !!pick.label
    : !!(pick.label || (pick.note || "").trim());
  const last = cursor >= decisions.length - 1;
  const setPick = (choice: DecisionChoice) => {
    if (locked) return;
    const decisionKey = decisionKeyOf(cur, cursor);
    setPicks((all) => ({ ...all, [key]: { choice: {
      ...pick, ...choice, ...(decisionKey ? { decision_key: decisionKey } : {}),
    } } }));
  };

  const next = () => {
    if (locked || !decided) return;
    setPicks((all) => ({ ...all, [key]: { choice: pick, sending: true } }));
    // Keep the current raw pick for retry; only this row is locked while sending.
    void Promise.resolve(onResolve([pick])).finally(() => {
      setPicks((all) => ({ ...all, [key]: { choice: pick, sending: false } }));
    });
    if (!last) setCurrentKey(keyOf(decisions[cursor + 1], cursor + 1));
  };

  React.useEffect(() => {
    if (suspended) return;
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
  }, [decisions.length, suspended]);

  React.useEffect(() => {
    if (suspended) return;
    const page = pageRef.current;
    if (!page) return;
    const firstFocusable = page.querySelector<HTMLElement>(
      "button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
    );
    if (isCheatConsoleTarget(document.activeElement)) return;
    (firstFocusable || page).focus();
  }, [cursor, decisions.length, suspended]);

  if (decisions.length === 0) return null;
  if (!cur) return null;

  const kickerKind = requiresListedChoice ? "案卷" : "请旨";

  return (
    <section
      ref={pageRef}
      className="decision-page"
      hidden={suspended}
      style={{ display: suspended ? "none" : undefined }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="decision-page-title"
      tabIndex={-1}
    >
      <article className="decision-document">
        <div className="decision-head">
          <span className="decision-kicker" aria-live="polite">
            月末批红 · {kickerKind} · 第 {cursor + 1} / {decisions.length} 疏
          </span>
          <h2 id="decision-page-title" className="decision-title">奏疏批红</h2>
        </div>
        <section aria-labelledby="decision-document-title">
          <div className="decision-document-section">
            <span className="decision-section-label">疏文</span>
            <h3 id="decision-document-title">{cur.title}</h3>
            <p>{cur.context}</p>
          </div>
          {cur.rejection_reason || cur.opposition ? <div className="decision-document-section">
            <span className="decision-section-label">封驳具由</span>
            {cur.rejection_reason ? <p>{cur.rejection_reason}</p> : null}
            {cur.opposition ? <p>持议者：{cur.opposition}</p> : null}
          </div> : null}

          <div className="decision-document-section">
            <span className="decision-section-label">内阁票拟</span>
            <div className="decision-options">
              {cur.options.map((option) => (
                <button
                  key={option.label}
                  type="button"
                  className={"decision-option" + (pick.label === option.label ? " is-picked" : "")}
                  disabled={locked}
                  onClick={() => setPick(option)}
                >
                  <span className="decision-option-label">拟批：{option.label}</span>
                  {option.hint ? <span className="decision-option-hint">{option.hint}</span> : null}
                </button>
              ))}
            </div>
          </div>

          <div className="decision-document-section decision-red-pen">
            <label className="decision-section-label" htmlFor="decision-note">朱笔亲批</label>
            <textarea
              id="decision-note"
              className="decision-note"
              placeholder="亲笔补批（可选）"
              value={pick.note || ""}
              disabled={locked}
              onChange={(event) => setPick({ note: event.target.value })}
            />
          </div>
          <button
            type="button"
            className="decision-confirm"
            disabled={locked || !decided}
            onClick={next}
            aria-label={last ? "批红落印，续推时局" : "批下一疏"}
          >
            {last ? "批红落印" : "批下一疏"}
          </button>
        </section>
        <div className="decision-actions">
          <span className="decision-hint-line">
            {decided
              ? "已择，落印即行。"
              : requiresListedChoice
                ? "此疏须择一票拟。"
                : "请择一票拟，或亲笔批示。"}
          </span>
        </div>
      </article>
    </section>
  );
}
