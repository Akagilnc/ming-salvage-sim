import React from "react";
import { FullscreenModal } from "./hud";
import { ScrollMessages } from "./scrollMessages";
import type { AudienceScrollMessage, HistoryTurnItem, Minister } from "../types";
import { filterScrollForSelectedMinister } from "../ministerScrollLens";
import { AUDIENCE_SCENE_SPEAKER } from "../audienceScene";
import { api } from "../api";
import type { ReplyRetry, TranslationRetry } from "../types";

export function AudienceArchiveModal({ onClose, ministers }: { onClose: () => void; ministers: Minister[] }) {
  const [nights, setNights] = React.useState<HistoryTurnItem[]>([]);
  const [selected, setSelected] = React.useState<HistoryTurnItem | null>(null);
  const selectedNightId = React.useRef<number | null>(null);
  const [messages, setMessages] = React.useState<AudienceScrollMessage[] | null>(null);
  const [nightCharacters, setNightCharacters] = React.useState<Minister[]>([]);
  const [pendingTranslationTurnIds, setPendingTranslationTurnIds] = React.useState<number[]>([]);
  const [translationRetries, setTranslationRetries] = React.useState<TranslationRetry[]>([]);
  const [replyRetries, setReplyRetries] = React.useState<ReplyRetry[]>([]);
  type RetryKind = "translation" | "reply";
  const [retrying, setRetrying] = React.useState<{ nightId: number; chatTurnId: number; kind: RetryKind } | null>(null);
  const [retryError, setRetryError] = React.useState<{ chatTurnId: number; kind: RetryKind; message: string } | null>(null);
  const completedRetries = React.useRef(new Set<string>());
  const [error, setError] = React.useState("");
  const [ministerFilter, setMinisterFilter] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    void api<{ turns: HistoryTurnItem[] }>("/api/history/turns").then((data) => {
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
    setNightCharacters([]);
    completedRetries.current.clear();
    setPendingTranslationTurnIds([]);
    setTranslationRetries([]);
    setReplyRetries([]);
    setRetryError(null);
    setError("");
    void api<any>(`/api/audience/scroll?night_id=${selected.night_id}`).then((data) => { if (alive) { setMessages(data.messages || []); setNightCharacters(data.characters || []); setPendingTranslationTurnIds(data.pending_translation_turn_ids || []); setTranslationRetries(data.translation_retries || []); setReplyRetries(data.reply_retries || []); } })
      .catch((reason) => { if (alive) setError(reason?.message || "加载失败"); });
    return () => { alive = false; };
  }, [selected]);

  React.useEffect(() => {
    setMinisterFilter("");
  }, [selected?.night_id]);

  const retryRecord = async (kind: RetryKind, chatTurnId: number) => {
    if (!selected?.night_id || (retrying !== null && retrying.nightId === selected.night_id)) return;
    const nightId = selected.night_id;
    const key = `${kind}:${chatTurnId}`;
    setRetrying({ nightId, chatTurnId, kind });
    setRetryError(null);
    try {
      if (!completedRetries.current.has(key)) {
        await api(kind === "reply" ? "/api/audience/chat/retry" : "/api/audience/translation/retry", { method: "POST", body: JSON.stringify({ chat_turn_id: chatTurnId }) });
        if (selectedNightId.current !== nightId) return;
        completedRetries.current.add(key);
      }
      if (selectedNightId.current !== nightId) return;
      const data = await api<any>(`/api/audience/scroll?night_id=${nightId}`);
      if (selectedNightId.current !== nightId) return;
      setMessages(data.messages || []);
      setNightCharacters(data.characters || []);
      setPendingTranslationTurnIds(data.pending_translation_turn_ids || []);
      setTranslationRetries(data.translation_retries || []);
      setReplyRetries(data.reply_retries || []);
      completedRetries.current.delete(key);
    } catch (reason) {
      if (selectedNightId.current === nightId) setRetryError({ chatTurnId, kind, message: reason instanceof Error ? reason.message : String(reason) });
    } finally {
      setRetrying((current) => current?.nightId === nightId && current.chatTurnId === chatTurnId && current.kind === kind ? null : current);
    }
  };

  const turnNotices = new Map<number, React.ReactNode>();
  if (messages) for (const kind of ["reply", "translation"] as const) {
    const retries = kind === "reply" ? replyRetries : translationRetries.filter((retry) => retry.retryable);
    for (const retry of retries) {
      const notice = <div key={kind} className="chat-system-note danger chat-failure-note" role="alert" data-testid={`archive-${kind}-retry-${retry.chat_turn_id}`}>
        {retryError?.chatTurnId === retry.chat_turn_id && retryError.kind === kind ? `重试失败：${retryError.message}` : kind === "reply" ? ("recovery_phase" in retry && retry.recovery_phase ? "回话已保存，后续处理失败。" : "本轮问话未得回话。") : "本轮记录未能整理。"}{retry.error_pack_path ? `错误包：${retry.error_pack_path}；请交给作者。` : ""}
        <button type="button" disabled={retrying?.nightId === selected?.night_id} onClick={() => void retryRecord(kind, retry.chat_turn_id)}>重试</button>
      </div>;
      turnNotices.set(retry.chat_turn_id, <>{turnNotices.get(retry.chat_turn_id)}{notice}</>);
    }
  }

  return <FullscreenModal title="起居注：召对记录" subtitle="退朝后同源只读，不可编辑" bgClass="modal-bg-chat" onClose={onClose}>
    <div className="history-modal-body">
      <aside className="history-turn-list"><ul>{nights.slice().reverse().map((night) => <li key={night.night_id}>
        <button className={`history-turn-item ${night.night_id === selected?.night_id ? "active" : ""}`} onClick={() => {
          if (night.night_id === selected?.night_id) return;
          selectedNightId.current = night.night_id ?? null;
          setSelected(night);
        }}>
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
        {messages ? <ScrollMessages messages={ministerFilter ? filterScrollForSelectedMinister(messages, ministerFilter, { sceneSpeaker: AUDIENCE_SCENE_SPEAKER, pendingTranslationTurnIds }) : messages} ministerName="" ministers={[...nightCharacters, ...ministers]} turnNotices={turnNotices} /> : null}
      </article>
    </div>
  </FullscreenModal>;
}
