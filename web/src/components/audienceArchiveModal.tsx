import React from "react";
import { FullscreenModal } from "./hud";
import { ScrollMessages } from "./scrollMessages";
import type { AudienceScrollMessage, HistoryTurnItem, Minister } from "../types";
import { filterScrollForSelectedMinister } from "../ministerScrollLens";
import { AUDIENCE_SCENE_SPEAKER } from "../audienceScene";
import { api } from "../api";
import type { TranslationRetry } from "../types";

export function AudienceArchiveModal({ onClose, ministers }: { onClose: () => void; ministers: Minister[] }) {
  const [nights, setNights] = React.useState<HistoryTurnItem[]>([]);
  const [selected, setSelected] = React.useState<HistoryTurnItem | null>(null);
  const selectedNightId = React.useRef<number | null>(null);
  const [messages, setMessages] = React.useState<AudienceScrollMessage[] | null>(null);
  const [pendingTranslationTurnIds, setPendingTranslationTurnIds] = React.useState<number[]>([]);
  const [translationRetries, setTranslationRetries] = React.useState<TranslationRetry[]>([]);
  const [retrying, setRetrying] = React.useState<number | null>(null);
  const [retryError, setRetryError] = React.useState<{ chatTurnId: number; message: string } | null>(null);
  const [error, setError] = React.useState("");
  const [ministerFilter, setMinisterFilter] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    void fetch("/api/history/turns").then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }).then((data) => {
      if (!alive) return;
      const list = ((data.turns || []) as HistoryTurnItem[]).filter((item) => item.kind === "night");
      setNights(list);
      selectedNightId.current = list[list.length - 1]?.night_id ?? null;
      setSelected(list[list.length - 1] || null);
    }).catch((reason) => { if (alive) setError(reason?.message || "加载失败"); });
    return () => { alive = false; };
  }, []);

  React.useEffect(() => {
    if (!selected?.night_id) return;
    let alive = true;
    setMessages(null);
    setPendingTranslationTurnIds([]);
    setTranslationRetries([]);
    setRetryError(null);
    setError("");
    void fetch(`/api/audience/scroll?night_id=${selected.night_id}`).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }).then((data) => { if (alive) { setMessages(data.messages || []); setPendingTranslationTurnIds(data.pending_translation_turn_ids || []); setTranslationRetries(data.translation_retries || []); } })
      .catch((reason) => { if (alive) setError(reason?.message || "加载失败"); });
    return () => { alive = false; };
  }, [selected]);

  React.useEffect(() => {
    setMinisterFilter("");
  }, [selected?.night_id]);

  const retryTranslation = async (chatTurnId: number) => {
    if (!selected?.night_id || retrying !== null) return;
    const nightId = selected.night_id;
    setRetrying(chatTurnId);
    setRetryError(null);
    try {
      await api("/api/audience/translation/retry", { method: "POST", body: JSON.stringify({ chat_turn_id: chatTurnId }) });
      if (selectedNightId.current !== nightId) return;
      const response = await fetch(`/api/audience/scroll?night_id=${nightId}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (selectedNightId.current !== nightId) return;
      setMessages(data.messages || []);
      setPendingTranslationTurnIds(data.pending_translation_turn_ids || []);
      setTranslationRetries(data.translation_retries || []);
    } catch (reason) {
      if (selectedNightId.current === nightId) setRetryError({ chatTurnId, message: reason instanceof Error ? reason.message : String(reason) });
    } finally {
      setRetrying(null);
    }
  };

  const turnNotices = new Map<number, React.ReactNode>();
  if (messages) for (const retry of translationRetries) {
    if (!retry.retryable) continue;
    turnNotices.set(retry.chat_turn_id, <div key={retry.chat_turn_id} className="chat-system-note danger chat-failure-note" role="alert" data-testid={`archive-translation-retry-${retry.chat_turn_id}`}>
      {retryError?.chatTurnId === retry.chat_turn_id ? `转译重试失败：${retryError.message}` : "本轮记录未能整理。"}{retry.error_pack_path ? `错误包：${retry.error_pack_path}；请交给作者。` : ""}
      <button type="button" disabled={retrying !== null} onClick={() => void retryTranslation(retry.chat_turn_id)}>重试</button>
    </div>);
  }

  return <FullscreenModal title="起居注：召对记录" subtitle="退朝后同源只读，不可编辑" bgClass="modal-bg-chat" onClose={onClose}>
    <div className="history-modal-body">
      <aside className="history-turn-list"><ul>{nights.slice().reverse().map((night) => <li key={night.night_id}>
        <button className={`history-turn-item ${night.night_id === selected?.night_id ? "active" : ""}`} onClick={() => { selectedNightId.current = night.night_id ?? null; setMessages(null); setPendingTranslationTurnIds([]); setTranslationRetries([]); setRetryError(null); setSelected(night); }}>
          <b>{night.title}</b><small>涉及人物：{night.involved_people?.join("、") || "无载"}</small>
        </button>
      </li>)}</ul>{!nights.length && !error ? <p className="long-copy">尚无召对记录。</p> : null}</aside>
      <article className="history-detail modal-scroll scroll-messages">
        {selected?.involved_people?.length ? <label>按臣过滤
          <select aria-label="按臣过滤" value={ministerFilter} onChange={(event) => setMinisterFilter(event.target.value)}>
            <option value="">全卷</option>
            {selected.involved_people.map((name) => <option value={name} key={name}>{name}</option>)}
          </select>
        </label> : null}
        {error ? <p className="long-copy">加载失败：{error}</p> : null}
        {messages ? <ScrollMessages messages={ministerFilter ? filterScrollForSelectedMinister(messages, ministerFilter, { sceneSpeaker: AUDIENCE_SCENE_SPEAKER, pendingTranslationTurnIds }) : messages} ministerName="" ministers={ministers} turnNotices={turnNotices} /> : null}
      </article>
    </div>
  </FullscreenModal>;
}
