import React from "react";
import { Loader2, Lock, RotateCcw, Send, Star, X } from "lucide-react";
import { MinisterPlaceOffice, MinisterPortrait } from "./hud";
import { api } from "../api";
import { filterScrollForSelectedMinister } from "../ministerScrollLens";
import { ScrollMessages, portraitSources } from "./scrollMessages";
import type {
  AudienceScrollMessage,
  ChatDisplayMessage,
  ChatMessage,
  Minister,
  PendingActionFailure,
  SecretOrder,
  Suggestion,
} from "../types";

export function ChatModal({
  minister,
  portraitPrefix,
  ministers,
  scrollMode = "audience",
  currentCampaignId,
  currentNightId,
  undoneChatIdentity,
  chat,
  suggestions,
  pendingUserMessage,
  pendingIdentity,
  failedIdentity,
  scrollGeneration,
  streamingMinisterMessage,
  chatNotice,
  chatFailures,
  canUndoLastChat,
  composerHint,
  input,
  busy,
  error,
  secretOrders,
  replyRetry,
  onInput,
  onIntent,
  onSend,
  onRetryFailure,
  onRetryReply,
  onUndo,
  onHint,
  onFavorite,
  scrollPosition,
  onScrollPositionChange,
  onClose,
  onCancel,
}: {
  minister: Minister;
  portraitPrefix: string;
  ministers: Minister[];
  scrollMode?: "audience" | "legacy";
  /** Complete ownership of the currently open scroll. */
  currentCampaignId: string;
  currentNightId: number;
  /** Complete persisted identity returned by the latest successful withdrawal. */
  undoneChatIdentity: { campaign_id: string; night_id: number; chat_turn_id: number } | null;
  chat: ChatMessage[];
  suggestions: Suggestion[];
  pendingUserMessage: string;
  pendingIdentity: { campaign_id: string; night_id: number; chat_turn_id: number } | null;
  /** Provider-failed persisted turn whose generating snapshot must be retired. */
  failedIdentity: { campaign_id: string; night_id: number; chat_turn_id: number } | null;
  /** 成功落账代次；变化时重读公共卷轴。 */
  scrollGeneration?: number;
  streamingMinisterMessage: string;
  chatNotice: string;
  chatFailures: PendingActionFailure[];
  canUndoLastChat: boolean;
  composerHint: string;
  input: string;
  busy: string;
  error: string;
  secretOrders: SecretOrder[];
  /** #505：系统层回话重试（崩溃后问话保留）。 */
  replyRetry?: { chat_turn_id: number; question: string } | null;
  onInput: (value: string) => void;
  onIntent?: (intent: "secret_order" | undefined) => void;
  onSend: (ministerName: string, text?: string) => void;
  onRetryFailure: (failure: PendingActionFailure) => void;
  onRetryReply?: (ministerName: string) => void;
  onUndo: (ministerName: string) => void;
  onHint: (value: string) => void;
  onFavorite: (minister: Minister) => void;
  /** Last player-owned position for this campaign/night, if they temporarily left. */
  scrollPosition?: number;
  onScrollPositionChange?: (position: number) => void;
  onClose: () => void;
  onCancel?: () => void;
}) {
  const chatLogRef = React.useRef<HTMLDivElement | null>(null);
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  const [scrollState, setScrollState] = React.useState<
    { kind: "loading" } | { kind: "none" } | {
      kind: "night";
      nightId: number;
      messages: AudienceScrollMessage[];
      refreshError: boolean;
    } | { kind: "error" }
  >({ kind: "loading" });
  const followsTailRef = React.useRef(true);
  const restoredNightRef = React.useRef<number | false>(false);
  const withdrawnFromThisScroll = (message: AudienceScrollMessage): boolean => !!(
    undoneChatIdentity
    && undoneChatIdentity.campaign_id === currentCampaignId
    && undoneChatIdentity.night_id === currentNightId
    && message.chat_turn_id === undoneChatIdentity.chat_turn_id
  );
  const failedInThisScroll = (message: AudienceScrollMessage): boolean => !!(
    failedIdentity
    && failedIdentity.campaign_id === currentCampaignId
    && failedIdentity.night_id === currentNightId
    && message.chat_turn_id === failedIdentity.chat_turn_id
  );
  const snapshotStillCurrent = (state: typeof scrollState): boolean =>
    state.kind !== "night" || (state.nightId === currentNightId && !state.messages.some(withdrawnFromThisScroll));
  const effectiveScrollState = snapshotStillCurrent(scrollState) ? scrollState : { kind: "loading" as const };
  // The night scroll is the sole live authority. Personal chat history is only the legacy fallback;
  // mixing it here reintroduces cross-night records and snapshot-difference heuristics.
  // #1511: open-night branch applies a pure selected-minister lens — never dump the campaign-wide scroll.
  // Half-turn claim is window-local presentation only (replyRetry / in-flight pendingIdentity).
  const claimedTurnId = replyRetry?.chat_turn_id
    ?? (
      pendingIdentity
      && pendingIdentity.campaign_id === currentCampaignId
      && pendingIdentity.night_id === currentNightId
        ? pendingIdentity.chat_turn_id
        : null
    );
  const displayMessages: Array<ChatDisplayMessage | AudienceScrollMessage> = scrollMode === "legacy" || (effectiveScrollState.kind === "none" && currentNightId === 0)
    ? [...chat]
    : effectiveScrollState.kind === "night"
      ? filterScrollForSelectedMinister(
        effectiveScrollState.messages.filter((message) => !failedInThisScroll(message)),
        minister.name,
        { claimedTurnId },
      )
      : [];

  React.useEffect(() => {
    let alive = true;
    // Once an open night is known, refreshes retain that single authority while loading;
    // first load/minister switches never flash the old per-minister projection.
    setScrollState((current) => current.kind === "night" && snapshotStillCurrent(current) ? current : { kind: "loading" });
    if (scrollMode === "legacy") {
      setScrollState({ kind: "none" });
      return () => { alive = false; };
    }
    api<{ night_id: number; messages: AudienceScrollMessage[] }>("/api/audience/scroll")
      .then((data) => {
        if (!alive) return;
        setScrollState(data.night_id ? {
          kind: "night",
          nightId: data.night_id,
          messages: data.messages || [],
          refreshError: false,
        } : { kind: "none" });
      })
      .catch(() => {
        if (!alive) return;
        setScrollState((current) => current.kind === "night" && snapshotStillCurrent(current)
          ? { ...current, refreshError: true }
          : { kind: "error" });
      });
    return () => { alive = false; };
  }, [minister.name, scrollMode, currentCampaignId, currentNightId, undoneChatIdentity, failedIdentity,
    // App supplies the explicit durable-settlement generation. Standalone/legacy consumers
    // retain the historical chat-driven refresh contract until they adopt that signal.
    scrollGeneration === undefined ? chat : scrollGeneration]);

  const pendingAlreadyPersisted = !!pendingIdentity
    && pendingIdentity.campaign_id === currentCampaignId
    && pendingIdentity.night_id === currentNightId
    && displayMessages.some((message) => "chat_turn_id" in message && message.chat_turn_id === pendingIdentity.chat_turn_id);
  if (pendingUserMessage && !pendingAlreadyPersisted) {
    displayMessages.push({ role: "user", content: pendingUserMessage, pending: true });
  }
  // The scroll remains the only authority: derive the sidebar lens from its latest
  // recognised entrance/divider anchor instead of storing parallel scene state.
  // Minister dialogue can be an interjection from someone standing at the side.
  const currentMinister = scrollMode === "audience"
    ? displayMessages.reduce<Minister | undefined>((current, message) => {
        if (!("speaker" in message) || !message.speaker) return current;
        const isAudienceAnchor = message.beat === "entrance" || message.beat === "divider";
        return isAudienceAnchor ? ministers.find((candidate) => candidate.name === message.speaker) ?? current : current;
      }, undefined) ?? minister
    : minister;
  if (streamingMinisterMessage) {
    displayMessages.push({
      role: "minister",
      speaker: currentMinister.name,
      audibility: "",
      time: null,
      content: streamingMinisterMessage,
      soft_boundary: false,
      beat: "dialogue",
      highlights: [],
      container: { time_of_day: "", location: "", audience_type: "" },
      pending: true,
    } as ChatDisplayMessage & AudienceScrollMessage);
  }
  const { primary: portraitPrimary, fallback: portraitFallback } = portraitSources(currentMinister, portraitPrefix);
  const visibleSecretOrders = secretOrders.filter((order) => order.minister_name === currentMinister.name);
  // Night-level audience_type lives on the raw scroll container — not the filtered lens.
  // Blank selected-minister windows must still show 召法.
  const audienceType = scrollMode === "audience" && effectiveScrollState.kind === "night"
    ? effectiveScrollState.messages.find((message) => message.container?.audience_type)?.container?.audience_type ?? ""
    : "";

  React.useEffect(() => {
    inputRef.current?.focus();
  }, [minister.name]);

  // Elapsed-seconds timer: count up only while truly thinking (waiting for the
  // minister reply, before streaming starts). Once streaming begins the timer
  // stops so no background interval fires / re-renders during stream render.
  React.useEffect(() => {
    const isThinking = !!busy && !streamingMinisterMessage;
    if (!isThinking) {
      setElapsedSeconds(0);
      return;
    }
    setElapsedSeconds(0);
    const id = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [busy, streamingMinisterMessage]);

  React.useEffect(() => {
    const node = chatLogRef.current;
    if (!node) return;
    const nightId = scrollState.kind === "night" ? scrollState.nightId : 0;
    const firstNightRestore = !!nightId && restoredNightRef.current !== nightId;
    if (firstNightRestore) {
      node.scrollTop = scrollPosition ?? node.scrollHeight;
      followsTailRef.current = scrollPosition === undefined || node.scrollHeight - node.scrollTop - node.clientHeight <= 24;
      restoredNightRef.current = nightId;
    } else if (followsTailRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [minister.name, chat, scrollState, pendingUserMessage, streamingMinisterMessage, chatNotice, chatFailures, busy, error, replyRetry]);

  const handleScroll = () => {
    const node = chatLogRef.current;
    if (node) {
      followsTailRef.current = node.scrollHeight - node.scrollTop - node.clientHeight <= 24;
      onScrollPositionChange?.(node.scrollTop);
    }
  };

  const handleSend = () => {
    onSend(currentMinister.name, input);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    onSend(currentMinister.name, input);
  };

  const sendSuggestion = (suggestion: Suggestion) => {
    if (suggestion.prefix) {
      onIntent?.(suggestion.intent === "secret_order" ? suggestion.intent : undefined);
      onInput(suggestion.text);
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      onSend(currentMinister.name, suggestion.text);
    }
  };

  return (
    <div className="chat-full-grid">
      <aside className="modal-pane minister-side">
        <div className="minister-profile">
          <div>
            <h2>{currentMinister.name}</h2>
            <p>
              {currentMinister.status !== "active" && (
                <span className={`minister-status status-${currentMinister.status}`}>{currentMinister.status_label}</span>
              )}
              <MinisterPlaceOffice minister={currentMinister} officeClassName="profile-office" />
            </p>
          </div>
          <button className="icon-button" aria-label="收藏大臣" onClick={() => onFavorite(currentMinister)}>
            <Star size={16} fill={currentMinister.favorite ? "currentColor" : "none"} />
          </button>
        </div>
        <p className="profile-copy">{currentMinister.summary}</p>
        <div className="chat-portrait-wrap">
          <MinisterPortrait primary={portraitPrimary} fallback={portraitFallback} name={currentMinister.name} />
        </div>
        {visibleSecretOrders.length > 0 && (
          <div className="chat-secret-orders">
            <div className="secret-orders-label"><Lock size={12} />密令</div>
            {visibleSecretOrders.map((o) => (
              <div key={o.id} className="secret-order-item">
                <div className="secret-order-title">{o.title}</div>
                <div className="secret-order-meta">第 {o.year_issued} 年 {o.period_issued} 月下令</div>
                {o.content && <div className="secret-order-content">{o.content}</div>}
                {o.sim_note && <div className="secret-order-content"><b>月度动向：</b>{o.sim_note}</div>}
                {o.result && <div className="secret-order-content"><b>承办回报：</b>{o.result}</div>}
              </div>
            ))}
          </div>
        )}
      </aside>

      <section className="modal-pane chat-main">
        <div className="chat-log chat-stage" ref={chatLogRef} onScroll={handleScroll} data-testid="chat-stage">
          {audienceType ? <div className="audience-type-label">{audienceType}</div> : null}
          {/* #1370：空对话区只给等候/引导 chrome（ADR 0046），不代笔叙事开场白（P7）。 */}
          {!displayMessages.length && !busy && !streamingMinisterMessage && effectiveScrollState.kind !== "loading" && effectiveScrollState.kind !== "error" && (
            <div className="chat-empty-chrome" role="status">请陛下问话</div>
          )}
          <ScrollMessages messages={displayMessages} ministerName={currentMinister.name} ministers={ministers} />
          {(scrollState.kind === "error" || (scrollState.kind === "night" && scrollState.refreshError)) && (
            <div className="chat-system-note danger" role="alert">召对记录读取失败，请稍后重试。</div>
          )}
          {busy && !streamingMinisterMessage && (
            <div className="chat-message minister thinking">
              <span>{currentMinister.name}</span>
              <p><Loader2 size={14} />{portraitPrefix === "consort_" ? "思索中..." : "大臣思索中..."}{elapsedSeconds > 0 ? `（${elapsedSeconds}秒）` : ""}</p>
            </div>
          )}
          {chatNotice && <div className="chat-system-note">{chatNotice}</div>}
          {/* #505：系统层恢复——崩溃后问话保留，给重试（非给皇帝的内容选项按钮）。 */}
          {replyRetry && onRetryReply && (
            <div className="chat-system-note danger chat-failure-note" role="alert" data-testid="reply-retry">
              <span>上回问话未得回话（「{replyRetry.question}」），可重新生成回话。</span>
              <button type="button" onClick={() => onRetryReply(currentMinister.name)} disabled={!!busy}>
                重新生成回话
              </button>
            </div>
          )}
          {chatFailures.map((failure) => (
            <div className="chat-system-note danger chat-failure-note" role="alert" key={failure.id}>
              <span>{failure.minister_name && failure.minister_name !== minister.name ? `${failure.minister_name}：` : ""}{failure.message}</span>
              {failure.kind === "secret_order" && failure.retryable && (
                <button type="button" onClick={() => onRetryFailure(failure)} disabled={!!busy}>
                  重试
                </button>
              )}
            </div>
          ))}
          {error && <div className="chat-system-note danger" role="alert">{error}</div>}
        </div>
        <div className="chat-composer">
          <div className="hitl-bar">
            {suggestions.map((suggestion) => (
              <button
                key={`${suggestion.label}-${suggestion.text}`}
                onClick={() => sendSuggestion(suggestion)}
                disabled={!!busy}
                title={suggestion.prefix ? `填入前缀：${suggestion.text}` : suggestion.text}
                className={suggestion.prefix ? "hitl-prefix" : ""}
              >
                {suggestion.label}
              </button>
            ))}
          </div>
          <label className="chat-input">
            <span>问话</span>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(event) => {
                onInput(event.target.value);
                if (composerHint) onHint("");
              }}
              onKeyDown={handleKeyDown}
              placeholder={portraitPrefix === "consort_"
                ? "询问后宫近况、心思、见闻，或吩咐她做事... Enter 发送，Shift+Enter 换行"
                : "问大臣军情、钱粮、地方，或要求他拟旨... Enter 发送，Shift+Enter 换行"}
            />
          </label>
          <div className="composer-actions">
            <button className={`primary-action ${!input.trim() ? "is-empty" : ""}`} onClick={handleSend} disabled={!!busy}>
              <Send size={15} />
              发送
            </button>
            <button className="secondary-action composer-undo" onClick={() => onUndo(currentMinister.name)} disabled={!!busy || !canUndoLastChat}>
              <RotateCcw size={15} />
              撤回本轮
            </button>
            {busy === "大臣思索中" && onCancel && (
              <button className="secondary-action composer-cancel" onClick={onCancel}>
                <X size={15} />
                离开等待
              </button>
            )}
            <button className="secondary-action composer-exit" onClick={onClose}>
              <X size={15} />
              退出召对
            </button>
            <button className="secondary-action composer-retreat" onClick={() => onSend(currentMinister.name, "退朝")} disabled={!!busy}>
              散夜
            </button>
            {composerHint && <div className="composer-hint">{composerHint}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
