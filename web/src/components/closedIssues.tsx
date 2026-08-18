import { FullscreenModal } from "./hud";
import { formatClosedEffect } from "../format";
import type { ClosedIssue } from "../types";

export function ClosedIssuesModal({ items, onClose }: { items: ClosedIssue[]; onClose: () => void }) {
  const resolved = items.filter((i) => i.status === "resolved");
  const failed = items.filter((i) => i.status === "failed");
  const dropped = items.filter((i) => i.status === "dropped");
  return (
    <FullscreenModal title="局势了结" subtitle={`本月共 ${items.length} 条局势了结`} bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        {resolved.length ? <ClosedGroup title="已结案" items={resolved} cls="resolved" /> : null}
        {failed.length ? <ClosedGroup title="已崩坏" items={failed} cls="failed" /> : null}
        {dropped.length ? <ClosedGroup title="已撤旨" items={dropped} cls="dropped" /> : null}
      </article>
    </FullscreenModal>
  );
}

function closedBarLabel(cls: string, item: ClosedIssue): string {
  const raw = cls === "resolved" ? item.bar_good_meaning : item.bar_bad_meaning;
  return (raw || "").trim();
}

function ClosedGroup({ title, items, cls }: { title: string; items: ClosedIssue[]; cls: string }) {
  return (
    <div className="document-section">
      <h3 className={`closed-group-title ${cls}`}>{title}</h3>
      <ul className="closed-list">
        {items.map((it) => {
          const barText = closedBarLabel(cls, it);
          return (
            <li key={it.id} className={`closed-card ${cls}`}>
              <div className="closed-card-head">
                <b>#{it.id} {it.title}</b>
                {barText ? <span>{barText}</span> : null}
              </div>
              {it.stage_text ? <p className="closed-card-stage">{it.stage_text}</p> : null}
              <div className="closed-card-effect">{formatClosedEffect(it.effect)}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

