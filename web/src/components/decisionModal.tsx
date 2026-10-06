import React from "react";
import type {
  DecisionChoice, PendingActionFailure, PendingDecision,
} from "../types";

function isCheatConsoleTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(".cheat-console") !== null;
}

function decisionKeyOf(d: PendingDecision, fallbackIdx: number): string | undefined {
  if (d.decision_key) return String(d.decision_key);
  if (!d.kind) return undefined;
  const kind = String(d.kind || "decision");
  const turn = d.source_turn ?? d.turn ?? 0;
  return `${kind}:${turn}:${d.idx ?? fallbackIdx}`;
}

export function DecisionModal({
  decisions,
  failures = [],
  onResolve,
  busy = "",
}: {
  decisions: PendingDecision[];
  failures?: PendingActionFailure[];
  onResolve: (choices: DecisionChoice[]) => void;
  /** truthy 时禁用票拟/亲批/翻页与落印，handler 入口短路——禁二提交。 */
  busy?: string;
}) {
  const [cursor, setCursor] = React.useState(0);
  const [picks, setPicks] = React.useState<DecisionChoice[]>(() =>
    decisions.map((d, i) => {
      const key = decisionKeyOf(d, i);
      return key ? { decision_key: key } : {};
    }),
  );
  const pageRef = React.useRef<HTMLElement>(null);
  const locked = !!busy;

  const cur = decisions[cursor];
  const pick = picks[cursor] || {};
  const requiresListedChoice = (cur?.event_id || "").startsWith("dossier:");
  const decided = requiresListedChoice
    ? !!pick.label
    : !!(pick.label || (pick.note || "").trim());
  const last = cursor >= decisions.length - 1;
  const setPick = (choice: DecisionChoice) => {
    if (locked) return;
    setPicks((all) =>
      all.map((item, i) => {
        if (i !== cursor) return item;
        const key = item.decision_key || decisionKeyOf(cur, cursor);
        return key
          ? { ...item, ...choice, decision_key: key }
          : { ...item, ...choice };
      }),
    );
  };

  const next = () => {
    if (locked || !decided) return;
    if (last) onResolve(picks);
    else setCursor((value) => value + 1);
  };

  React.useEffect(() => {
    const page = pageRef.current;
    if (!page) return;

    const onKey = (event: KeyboardEvent) => {
      if (locked) return;
      if (isCheatConsoleTarget(event.target)) return;
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        next();
      }
    };
    page.addEventListener("keydown", onKey);
    return () => page.removeEventListener("keydown", onKey);
  });

  if (!cur) return null;

  const kickerKind = requiresListedChoice ? "案卷" : "请旨";

  return (
    <section
      className="decision-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="decision-page-title"
      ref={pageRef}
    >
      <article className="decision-document">
        <div className="decision-head">
          <span className="decision-kicker" aria-live="polite">
            月末批红 · {kickerKind} · 第 {cursor + 1} / {decisions.length} 疏
          </span>
          <h2 id="decision-page-title" className="decision-title">奏疏批红</h2>
        </div>
        {failures.length ? <div className="decision-failure-list" role="alert">
          {failures.map((failure) => <div className="decision-failure-item" key={failure.id}>{failure.message}</div>)}
        </div> : null}
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
