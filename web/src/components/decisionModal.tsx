import React from "react";
import type { PendingActionFailure, PendingDecision } from "../types";

type Choice = { label?: string; hint?: string; note?: string };

export function DecisionModal({
  decisions,
  failures = [],
  onResolve,
}: {
  decisions: PendingDecision[];
  failures?: PendingActionFailure[];
  onResolve: (choices: Choice[]) => void;
}) {
  const [cursor, setCursor] = React.useState(0);
  const [picks, setPicks] = React.useState<Choice[]>(() => decisions.map(() => ({})));
  if (decisions.length === 0) return null;

  const cur = decisions[cursor];
  const pick = picks[cursor] || {};
  const decided = !!(pick.label || (pick.note || "").trim());
  const last = cursor >= decisions.length - 1;
  const setPick = (choice: Choice) => setPicks((all) => all.map((item, i) => i === cursor ? { ...item, ...choice } : item));

  const next = () => {
    if (!decided) return;
    if (last) onResolve(picks);
    else setCursor((value) => value + 1);
  };

  return (
    <div className="decision-modal" role="dialog" aria-modal="true" aria-label="月末批红">
      <div className="decision-window decision-paper">
        <div className="decision-head">
          <span className="decision-kicker">月末批红 · 第 {cursor + 1} / {decisions.length} 疏</span>
          <h2 className="decision-title">奏疏批红</h2>
        </div>
        {failures.length ? <div className="decision-failure-list" role="alert">
          {failures.map((failure) => <div className="decision-failure-item" key={failure.id}>{failure.message}</div>)}
        </div> : null}
        <section className="decision-document" aria-labelledby="decision-document-title">
          <div className="decision-document-section">
            <span className="decision-section-label">疏文</span>
            <h3 id="decision-document-title">{cur.title}</h3>
            <p>{cur.context || "臣等谨陈时局，请陛下裁夺。"}</p>
          </div>
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
          <div className="decision-seal" aria-label="批红落印">批红落印</div>
        </section>
        <div className="decision-actions">
          <span className="decision-hint-line">{decided ? "" : "请择一票拟，或亲笔批示。"}</span>
          <button className="decision-confirm" disabled={!decided} onClick={next}>{last ? "批红落印，续推时局" : "批下一疏"}</button>
        </div>
      </div>
    </div>
  );
}
