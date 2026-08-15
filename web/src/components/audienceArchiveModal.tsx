import React from "react";
import { FullscreenModal } from "./hud";
import { ScrollMessages } from "./scrollMessages";
import type { AudienceScrollMessage, HistoryTurnItem, Minister } from "../types";

export function AudienceArchiveModal({ onClose, ministers }: { onClose: () => void; ministers: Minister[] }) {
  const [nights, setNights] = React.useState<HistoryTurnItem[]>([]);
  const [selected, setSelected] = React.useState<HistoryTurnItem | null>(null);
  const [messages, setMessages] = React.useState<AudienceScrollMessage[] | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    void fetch("/api/history/turns").then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }).then((data) => {
      if (!alive) return;
      const list = ((data.turns || []) as HistoryTurnItem[]).filter((item) => item.kind === "night");
      setNights(list);
      setSelected(list[list.length - 1] || null);
    }).catch((reason) => { if (alive) setError(reason?.message || "加载失败"); });
    return () => { alive = false; };
  }, []);

  React.useEffect(() => {
    if (!selected?.night_id) return;
    let alive = true;
    setMessages(null);
    setError("");
    void fetch(`/api/audience/scroll?night_id=${selected.night_id}`).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }).then((data) => { if (alive) setMessages(data.messages || []); })
      .catch((reason) => { if (alive) setError(reason?.message || "加载失败"); });
    return () => { alive = false; };
  }, [selected]);

  return <FullscreenModal title="起居注：召对记录" subtitle="退朝后同源只读，不可编辑" bgClass="modal-bg-chat" onClose={onClose}>
    <div className="history-modal-body">
      <aside className="history-turn-list"><ul>{nights.slice().reverse().map((night) => <li key={night.night_id}>
        <button className={`history-turn-item ${night.night_id === selected?.night_id ? "active" : ""}`} onClick={() => setSelected(night)}>
          <b>{night.title}</b><small>涉及人物：{night.involved_people?.join("、") || "无载"}</small>
        </button>
      </li>)}</ul>{!nights.length && !error ? <p className="long-copy">尚无召对记录。</p> : null}</aside>
      <article className="history-detail modal-scroll scroll-messages">
        {error ? <p className="long-copy">加载失败：{error}</p> : null}
        {messages ? <ScrollMessages messages={messages} ministerName="" ministers={ministers} /> : null}
      </article>
    </div>
  </FullscreenModal>;
}
