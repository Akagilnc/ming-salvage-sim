import React from "react";
import { Loader2, Lock, RotateCcw, ScrollText, Send, Star, X } from "lucide-react";
import { MinisterPortrait, cacheBust } from "./hud";
import { stripOrganicMarkdown } from "../format";
import type { ChatDisplayMessage, ChatMessage, Minister, PendingActionFailure, SecretOrder, Suggestion } from "../types";

export function ChatModal({
  minister,
  portraitPrefix,
  chat,
  suggestions,
  pendingUserMessage,
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
  extractionPendingCount,
  onInput,
  onSend,
  onRetryFailure,
  onRetryReply,
  onRetryExtraction,
  onUndo,
  onHint,
  onFavorite,
  onOpenEdict,
  onClose,
  onCancel,
}: {
  minister: Minister;
  portraitPrefix: string;
  chat: ChatMessage[];
  suggestions: Suggestion[];
  pendingUserMessage: string;
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
  /** #501：本夜待补叙事抽取条数。 */
  extractionPendingCount?: number;
  onInput: (value: string) => void;
  onSend: (text?: string) => void;
  onRetryFailure: (failure: PendingActionFailure) => void;
  onRetryReply?: () => void;
  onRetryExtraction?: () => void;
  onUndo: () => void;
  onHint: (value: string) => void;
  onFavorite: () => void;
  onOpenEdict: () => void;
  onClose: () => void;
  onCancel?: () => void;
}) {
  const isCustom = minister.portrait_id?.startsWith("custom:");
  const portraitPrimary = isCustom
    ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
    : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`;
  const portraitFallback = !isCustom && minister.portrait_id
    ? `/portraits/${minister.portrait_id}.png`
    : undefined;
  const chatLogRef = React.useRef<HTMLDivElement | null>(null);
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  const displayMessages: ChatDisplayMessage[] = [...chat];

  if (pendingUserMessage) {
    displayMessages.push({ role: "user", content: pendingUserMessage, pending: true });
  }
  if (streamingMinisterMessage) {
    displayMessages.push({ role: "minister", content: streamingMinisterMessage, pending: true });
  }

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
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [minister.name, chat, pendingUserMessage, streamingMinisterMessage, chatNotice, chatFailures, busy, error, replyRetry, extractionPendingCount]);

  const handleSend = () => {
    onSend(input);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    onSend(input);
  };

  const sendSuggestion = (suggestion: Suggestion) => {
    if (suggestion.prefix) {
      // 填前缀到输入框，不直接发送，光标跟到末尾
      onInput(suggestion.text);
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      onSend(suggestion.text);
    }
  };

  return (
    <div className="chat-full-grid">
      <aside className="modal-pane minister-side">
        <div className="minister-profile">
          <div>
            <h2>{minister.name}</h2>
            <p>
              {minister.status !== "active" && (
                <span className={`minister-status status-${minister.status}`}>{minister.status_label}</span>
              )}
              {minister.office && <span className="profile-office">{minister.office}</span>}
            </p>
          </div>
          <button className="icon-button" aria-label="收藏大臣" onClick={onFavorite}>
            <Star size={16} fill={minister.favorite ? "currentColor" : "none"} />
          </button>
        </div>
        <p className="profile-copy">{minister.summary}</p>
        <button className="secondary-action" onClick={onOpenEdict}>
          <ScrollText size={15} />
          转入诏书草案
        </button>
        <div className="chat-portrait-wrap">
          <MinisterPortrait primary={portraitPrimary} fallback={portraitFallback} name={minister.name} />
        </div>
        {secretOrders.length > 0 && (
          <div className="chat-secret-orders">
            <div className="secret-orders-label"><Lock size={12} />密令</div>
            {secretOrders.map((o) => (
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
        <div className="chat-log" ref={chatLogRef}>
          {displayMessages.map((message, index) => (
            <div className={`chat-message ${message.role} ${message.pending ? "pending" : ""}`} key={`${message.role}-${index}-${message.content}`}>
              <span>
                {message.role === "user"
                  ? "朕"
                  : message.role === "attendant"
                    ? "近臣"
                    : minister.name}
              </span>
              <p>{message.role === "minister" ? stripOrganicMarkdown(message.content) : message.content}</p>
            </div>
          ))}
          {busy && !streamingMinisterMessage && (
            <div className="chat-message minister thinking">
              <span>{minister.name}</span>
              <p><Loader2 size={14} />{portraitPrefix === "consort_" ? "思索中..." : "大臣思索中..."}{elapsedSeconds > 0 ? `（${elapsedSeconds}秒）` : ""}</p>
            </div>
          )}
          {chatNotice && <div className="chat-system-note">{chatNotice}</div>}
          {/* #505：系统层恢复——崩溃后问话保留，给重试（非给皇帝的内容选项按钮）。 */}
          {replyRetry && onRetryReply && (
            <div className="chat-system-note danger chat-failure-note" role="alert" data-testid="reply-retry">
              <span>上回问话未得回话（「{replyRetry.question}」），可重新生成回话。</span>
              <button type="button" onClick={onRetryReply} disabled={!!busy}>
                重新生成回话
              </button>
            </div>
          )}
          {/* #501：待补叙事抽取——显眼提示 + 原地重试（不锁档）。 */}
          {!!extractionPendingCount && extractionPendingCount > 0 && onRetryExtraction && (
            <div className="chat-system-note danger chat-failure-note" role="alert" data-testid="extraction-pending">
              <span>本夜有 {extractionPendingCount} 段召对账待补写，可原地重试。</span>
              <button type="button" onClick={onRetryExtraction} disabled={!!busy}>
                重试补写
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
            <button className="secondary-action composer-undo" onClick={onUndo} disabled={!!busy || !canUndoLastChat}>
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
            {composerHint && <div className="composer-hint">{composerHint}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

