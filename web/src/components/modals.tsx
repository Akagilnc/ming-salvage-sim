import React from "react";
import { Check, Crown, Edit3, Landmark, Loader2, Lock, MessageSquare, RotateCcw, ScrollText, Send, Star, Trash2, X } from "lucide-react";
import { api } from "../api";
import { FullscreenModal, MinisterPortrait, cacheBust } from "./hud";
import { formatClosedEffect, stripOrganicMarkdown } from "../format";
import type { AudienceScrollMessage, ChatDisplayMessage, ChatMessage, ClosedIssue, Directive, EndingPayload, GameState, HistoryDetail, HistoryTurnItem, Minister, PendingActionFailure, SecretOrder, Suggestion } from "../types";

export function ReportModal({
  report,
  onClose,
}: {
  report: string;
  onClose: () => void;
}) {
  const activeText = stripOrganicMarkdown(report);
  return (
    <FullscreenModal title="月末邸报" subtitle="本月故事" bgClass="modal-bg-state" onClose={onClose}>
      <article className="state-document modal-scroll">
        <div className="document-section">
          <pre className="memorial-text">{activeText}</pre>
        </div>
      </article>
    </FullscreenModal>
  );
}

export function EndingModal({ ending, onClose }: { ending: EndingPayload; onClose: () => void }) {
  const lastTimeline = ending.timeline?.[ending.timeline.length - 1];
  const endingDate = lastTimeline ? `${lastTimeline.year}年${lastTimeline.period}月` : "终局";
  const timelineCount = ending.timeline?.length ?? 0;

  return (
    <FullscreenModal
      title="终章定论"
      subtitle="崇祯一朝，盖棺论定"
      bgClass="modal-bg-state modal-bg-ending"
      onClose={onClose}
    >
      <article className="state-document ending-document modal-scroll">
        <div className="ending-hero">
          <div className="ending-seal" aria-hidden="true">
            <Crown size={34} />
          </div>
          <div className="ending-hero-copy">
            <p>大明国史馆录</p>
            <h2>{ending.label}</h2>
            <span>{endingDate} · 第 {timelineCount || 1} 卷</span>
          </div>
        </div>

        <section className="ending-verdict-card" aria-label="结局总评">
          <div className="ending-section-kicker">
            <ScrollText size={17} />
            <span>国史编纂官总评</span>
          </div>
          <pre className="ending-summary-text">{ending.summary || "（无总评）"}</pre>
        </section>

        {ending.timeline && ending.timeline.length > 0 && (
          <section className="ending-chronicle" aria-label="逐月历程">
            <div className="ending-section-kicker">
              <Landmark size={17} />
              <span>崇祯一朝逐月历程</span>
            </div>
            <ol className="ending-timeline">
              {ending.timeline.map((it) => (
                <li key={it.turn} className="ending-timeline-item">
                  <div className="ending-timeline-date">
                    <b>{it.year}</b>
                    <span>{it.period}月</span>
                  </div>
                  <div className="ending-timeline-body">
                    {it.chapter ? (
                      <p className="ending-timeline-chapter">{it.chapter}</p>
                    ) : null}
                    {it.decree_brief ? (
                      <p className="ending-timeline-decree">诏：{it.decree_brief}</p>
                    ) : null}
                    {it.effect_brief ? (
                      <p className="ending-timeline-effect">效：{it.effect_brief}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
      </article>
    </FullscreenModal>
  );
}

export function SecretOrdersModal({
  orders,
  onClose,
  onOpenMinister,
}: {
  orders: SecretOrder[];
  onClose: () => void;
  onOpenMinister: (name: string) => void;
}) {
  const [tab, setTab] = React.useState<"active" | "pending_review" | "done" | "failed" | "all">("active");
  const [selectedOrder, setSelectedOrder] = React.useState<SecretOrder | null>(null);
  const statusLabel: Record<string, string> = {
    active: "进行中",
    pending_review: "待核议",
    done: "已完成",
    failed: "已失败",
    cancelled: "已撤销",
  };
  const statusCls: Record<string, string> = {
    active: "so-active",
    pending_review: "so-pending",
    done: "so-done",
    failed: "so-failed",
    cancelled: "so-cancelled",
  };
  const tabs: { key: typeof tab; label: string }[] = [
    { key: "active",         label: `进行中 (${orders.filter(o => o.status === "active").length})` },
    { key: "pending_review", label: `待核议 (${orders.filter(o => o.status === "pending_review").length})` },
    { key: "done",           label: `已完成 (${orders.filter(o => o.status === "done").length})` },
    { key: "failed",         label: `已失败 (${orders.filter(o => o.status === "failed").length})` },
    { key: "all",            label: `全部 (${orders.length})` },
  ];
  const visible = tab === "all" ? orders : orders.filter(o => o.status === tab);
  return (
    <FullscreenModal title="密令进度" subtitle={`共 ${orders.length} 条密令记录`} bgClass="modal-bg-edict" onClose={onClose}>
      <article className="state-document modal-scroll">
        <div className="so-tabs">
          {tabs.map(t => (
            <button key={t.key} className={`so-tab${tab === t.key ? " so-tab-active" : ""}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="secret-orders-list">
          {visible.length === 0 && <p className="so-empty">暂无此类密令。</p>}
          {visible.map((o) => (
            <button
              key={o.id}
              type="button"
              className={`secret-order-card secret-order-card-button ${statusCls[o.status] || ""}`}
              onClick={() => setSelectedOrder(o)}
            >
              <div className="so-header">
                <span className="so-title"><Lock size={13} />{o.title}</span>
                <span className={`so-status ${statusCls[o.status] || ""}`}>{statusLabel[o.status] || o.status}</span>
              </div>
              <div className="so-meta">第 {o.year_issued} 年 {o.period_issued} 月下令 · 承办：{o.minister_name}</div>
              <div className="so-open-hint">点击查看密令详情</div>
              {o.status === "active" && (
                <button
                  className="secondary-action so-goto"
                  onClick={(event) => {
                    event.stopPropagation();
                    onClose();
                    onOpenMinister(o.minister_name);
                  }}
                >
                  <MessageSquare size={13} />
                  召见 {o.minister_name}
                </button>
              )}
            </button>
          ))}
        </div>
      </article>
      {selectedOrder ? (
        <SecretOrderDetailDialog
          order={selectedOrder}
          statusLabel={statusLabel}
          statusCls={statusCls}
          onClose={() => setSelectedOrder(null)}
          onOpenMinister={(name) => {
            setSelectedOrder(null);
            onClose();
            onOpenMinister(name);
          }}
        />
      ) : null}
    </FullscreenModal>
  );
}

export function SecretOrderDetailDialog({
  order,
  statusLabel,
  statusCls,
  onClose,
  onOpenMinister,
}: {
  order: SecretOrder;
  statusLabel: Record<string, string>;
  statusCls: Record<string, string>;
  onClose: () => void;
  onOpenMinister: (name: string) => void;
}) {
  const deadlineText = order.due_turn
    ? `第 ${order.due_turn} 回合核议${order.due_turn <= order.turn_issued ? "" : `（限 ${order.due_turn - order.turn_issued} 个月）`}`
    : "无硬期限";
  const detailRows = [
    ["编号", `#${order.id}`],
    ["承办", order.minister_name],
    ["下令", `第 ${order.year_issued} 年 ${order.period_issued} 月 · 回合 ${order.turn_issued}`],
    ["期限", deadlineText],
    ["重要", String(order.importance || 0)],
    ["标签", order.tags?.length ? order.tags.join("、") : "无"],
  ];
  return (
    <div className="so-detail-layer" role="dialog" aria-modal="true" aria-label={`密令详情：${order.title}`}>
      <div className="so-detail-scrim" onClick={onClose} />
      <section className="so-detail-dialog">
        <header className="so-detail-header">
          <div>
            <span className={`so-status ${statusCls[order.status] || ""}`}>{statusLabel[order.status] || order.status}</span>
            <h2>{order.title}</h2>
          </div>
          <button className="icon-button" aria-label="关闭密令详情" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="so-detail-body">
          <dl className="so-detail-grid">
            {detailRows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <SecretOrderDetailBlock title="密令正文" text={order.content || "未记正文。"} />
          {order.sim_note ? <SecretOrderDetailBlock title="月度动向" text={order.sim_note} tone="green" /> : null}
          {(order.dossier_progress || []).map((report, index) => (
            <SecretOrderDetailBlock
              key={report.id}
              title={`${report.is_terminal ? "结案密奏" : `第 ${index + 1} 月密奏`} · ${report.progress_band}`}
              text={report.memorial_text}
              tone="green"
            />
          ))}
          {order.result ? (
            <SecretOrderDetailBlock title={order.status === "active" ? "承办回报" : "执行结果"} text={order.result} tone="green" />
          ) : null}
        </div>
        <footer className="so-detail-actions">
          {order.status === "active" ? (
            <button className="secondary-action" onClick={() => onOpenMinister(order.minister_name)}>
              <MessageSquare size={15} />
              召见 {order.minister_name}
            </button>
          ) : null}
          <button className="secondary-action" onClick={onClose}>返回列表</button>
        </footer>
      </section>
    </div>
  );
}

export function SecretOrderDetailBlock({ title, text, tone = "default" }: { title: string; text: string; tone?: "default" | "green" }) {
  return (
    <section className={`so-detail-block so-detail-block-${tone}`}>
      <h3>{title}</h3>
      <p>{text}</p>
    </section>
  );
}

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

export function ClosedGroup({ title, items, cls }: { title: string; items: ClosedIssue[]; cls: string }) {
  return (
    <div className="document-section">
      <h3 className={`closed-group-title ${cls}`}>{title}</h3>
      <ul className="closed-list">
        {items.map((it) => (
          <li key={it.id} className={`closed-card ${cls}`}>
            <div className="closed-card-head">
              <b>#{it.id} {it.title}</b>
              <span>{cls === "resolved" ? it.bar_good_meaning : it.bar_bad_meaning}</span>
            </div>
            {it.stage_text ? <p className="closed-card-stage">{it.stage_text}</p> : null}
            <div className="closed-card-effect">{formatClosedEffect(it.effect)}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HistoryModal({ onClose }: { onClose: () => void }) {
  const [turns, setTurns] = React.useState<HistoryTurnItem[]>([]);
  const [listLoading, setListLoading] = React.useState(true);
  const [listError, setListError] = React.useState("");
  const [selectedArchive, setSelectedArchive] = React.useState<HistoryTurnItem | null>(null);
  const [detail, setDetail] = React.useState<HistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch("/api/history/turns");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!alive) return;
        const list: HistoryTurnItem[] = (data.turns || []).filter((item: HistoryTurnItem) => item.kind === "month");
        setTurns(list);
        if (list.length) setSelectedArchive(list[list.length - 1]);
      } catch (e: any) {
        if (alive) setListError(e?.message || "加载失败");
      } finally {
        if (alive) setListLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  React.useEffect(() => {
    if (selectedArchive == null) return;
    const selectedTurn = selectedArchive.turn;
    let alive = true;
    setDetailLoading(true);
    setDetailError("");
    setDetail(null);
    void fetch(`/api/history/turn/${selectedTurn}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => { if (alive) setDetail(data); })
      .catch((error) => { if (alive) setDetailError(error?.message || "加载失败"); })
      .finally(() => { if (alive) setDetailLoading(false); });
    return () => { alive = false; };
  }, [selectedArchive]);

  const subtitle = turns.length ? `共 ${turns.length} 月档 · 仅收奏报与诏书` : "尚无奏报或诏书";

  return (
    <FullscreenModal title="史册：历代奏报与诏书" subtitle={subtitle} bgClass="modal-bg-state" onClose={onClose}>
      <div className="history-modal-body">
        <aside className="history-turn-list">
          {listLoading ? <p className="long-copy">加载中…</p> : null}
          {listError ? <p className="long-copy">加载失败：{listError}</p> : null}
          {!listLoading && !listError && turns.length === 0 ? (
            <p className="long-copy">尚无存档回合。</p>
          ) : null}
          <ul>
            {turns.slice().reverse().map((t) => {
              const active = t.turn === selectedArchive?.turn && t.night_id === selectedArchive?.night_id;
              const tags: string[] = [];
              if (t.has_report) tags.push("奏报");
              if (t.has_directive) tags.push("诏");
              return (
                <li key={`${t.turn}:${t.night_id ?? "month"}`}>
                  <button
                    className={`history-turn-item ${active ? "active" : ""}`}
                    onClick={() => setSelectedArchive(t)}
                  >
                    <b>{t.year} 年 {t.period} 月</b>
                    <small>第 {t.turn} 回合 · {tags.join(" / ") || "月档"}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
        <article className="history-detail modal-scroll">
          <HistoryDetailView
            loading={detailLoading}
            error={detailError}
            detail={detail}
            selectedTurn={selectedArchive?.turn ?? null}
          />
        </article>
      </div>
    </FullscreenModal>
  );
}

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

export function HistoryDetailView({
  loading,
  error,
  detail,
  selectedTurn,
}: {
  loading: boolean;
  error: string;
  detail: HistoryDetail | null;
  selectedTurn: number | null;
}) {
  if (selectedTurn == null) return <div className="document-section"><p className="long-copy">请从左侧择月。</p></div>;

  return (
    <>
      {loading ? <section className="document-section"><p className="long-copy">月档加载中…</p></section> : null}
      {error ? <section className="document-section"><p className="long-copy">月档加载失败：{error}</p></section> : null}
      {!loading && !error && (!detail || !detail.exists)
        ? <section className="document-section"><p className="long-copy">该回合无存档。</p></section>
        : null}
      {detail?.decree_text ? (
        <section className="document-section">
          <h3 className="extraction-section-title">本月诏书</h3>
          <pre className="memorial-text">{detail.decree_text}</pre>
        </section>
      ) : null}

      {detail?.directives?.length ? (
        <section className="document-section">
          <h3 className="extraction-section-title">已颁草案（{detail.directives.length} 道）</h3>
          <ul className="history-directive-list">
            {detail.directives.map((d) => (
              <li key={d.id} className="history-directive-item">
                <div className="history-directive-head">
                  <b>#{d.id}</b>
                  {d.event_title ? <span>事项：{d.event_title}</span> : null}
                  {d.actor ? <span>主官：{d.actor}</span> : null}
                  {d.skill_id ? <span>技能：{d.skill_id}</span> : null}
                  <span className="history-directive-source">{d.source}</span>
                </div>
                <pre className="memorial-text">{d.text}</pre>
                {d.notes ? <div className="history-directive-notes">备注：{d.notes}</div> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {detail?.report ? (
        <section className="document-section">
          <h3 className="extraction-section-title">月末邸报奏报</h3>
          <pre className="memorial-text">{detail.report}</pre>
        </section>
      ) : null}

    </>
  );
}

export function PreviousSummary({ summary }: { summary: string }) {
  if (!summary) {
    return <p className="long-copy">登基伊始，尚无上月回奏。</p>;
  }
  const lines = summary.split("\n").map((line) => line.trim()).filter(Boolean);
  const rows = lines
    .map((line) => {
      const idx = line.indexOf("：");
      if (idx <= 0) return null;
      return { label: line.slice(0, idx), value: line.slice(idx + 1) };
    })
    .filter((row): row is { label: string; value: string } => !!row && !!row.value);

  if (!rows.length) {
    return <p className="long-copy">{summary}</p>;
  }

  return (
    <table className="summary-table">
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th>{row.label}</th>
            <td>{row.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function StateModal({ state }: { state: GameState }) {
  const report = state.last_report || state.previous_summary;
  return (
    <article className="state-document modal-scroll">
      <section className="document-section">
        {report
          ? <pre className="memorial-text">{report}</pre>
          : <div className="empty-note">尚无上月奏报。</div>}
      </section>
    </article>
  );
}

export function BriefReport({ title, items }: { title: string; items: string[] }) {
  return (
    <article>
      <h2>{title}</h2>
      <ul className="brief-list">
        {items.map((item) => <li key={`${title}-${item}`}>{item}</li>)}
      </ul>
    </article>
  );
}


export function parseLeadingStageDirection(source: string): { action: string | null; content: string } {
  const match = source.match(/^（[^（）\r\n]+）/);
  return match
    ? { action: match[0], content: source.slice(match[0].length) }
    : { action: null, content: source };
}

function portraitSources(minister: Minister, portraitPrefix = "minister_") {
  const isCustom = minister.portrait_id?.startsWith("custom:");
  return {
    primary: isCustom
      ? `/portraits/custom/${encodeURIComponent(minister.name)}?t=${cacheBust(minister.portrait_id!)}`
      : `/portraits/${portraitPrefix}${minister.id ?? minister.name}.png`,
    fallback: !isCustom && minister.portrait_id ? `/portraits/${minister.portrait_id}.png` : undefined,
  };
}

function ScrollMessages({ messages, ministerName, ministers }: { messages: Array<ChatDisplayMessage | AudienceScrollMessage>; ministerName: string; ministers: Minister[] }) {
  return <>{messages.map((message, index) => {
    const pending = "pending" in message && message.pending;
    const speaker = "speaker" in message ? message.speaker : message.role === "user" ? "朕" : message.role === "attendant" ? "近臣" : ministerName;
    const beat = "beat" in message ? message.beat : "dialogue";
    if (message.role === "scene") return <div className={`chat-message scene beat-${beat}`} key={`${message.role}-${index}-${message.content}`}>{message.content ? <p>{message.content}</p> : beat === "divider" ? <hr aria-label={speaker ? `宣${speaker}` : "分隔"} /> : null}</div>;
    const isAside = message.role === "attendant" && "audibility" in message && message.audibility === "御前低语";
    const attendant = isAside ? ministers.find((candidate) => candidate.name === speaker) : undefined;
    const attendantPortrait = attendant ? portraitSources(attendant) : undefined;
    const text = message.role === "minister" ? stripOrganicMarkdown(message.content) : message.content;
    const { action, content } = parseLeadingStageDirection(text);
    return <div className={`chat-message ${message.role} ${isAside ? "aside" : ""} ${pending ? "pending" : ""}`} key={`${message.role}-${index}-${message.content}`}>
      {isAside ? <MinisterPortrait className="aside-avatar" primary={attendantPortrait?.primary ?? ""} fallback={attendantPortrait?.fallback} name={speaker} /> : null}
      <span>{speaker}</span>
      {action ? <em className="action">{action}</em> : null}
      <p>{content}</p>
    </div>;
  })}</>;
}

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
  extractionPendingCount,
  onInput,
  onSend,
  onRetryFailure,
  onRetryReply,
  onRetryExtraction,
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
  /** Last player-owned position for this campaign/night, if they temporarily left. */
  scrollPosition?: number;
  onScrollPositionChange?: (position: number) => void;
  onClose: () => void;
  onCancel?: () => void;
}) {
  const { primary: portraitPrimary, fallback: portraitFallback } = portraitSources(minister, portraitPrefix);
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
  const displayMessages: Array<ChatDisplayMessage | AudienceScrollMessage> = scrollMode === "legacy" || (effectiveScrollState.kind === "none" && currentNightId === 0)
    ? [...chat]
    : effectiveScrollState.kind === "night" ? effectiveScrollState.messages.filter((message) => !failedInThisScroll(message)) : [];

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
  }, [minister.name, chat, scrollState, pendingUserMessage, streamingMinisterMessage, chatNotice, chatFailures, busy, error, replyRetry, extractionPendingCount]);

  const handleScroll = () => {
    const node = chatLogRef.current;
    if (node) {
      followsTailRef.current = node.scrollHeight - node.scrollTop - node.clientHeight <= 24;
      onScrollPositionChange?.(node.scrollTop);
    }
  };

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
        <div className="chat-log" ref={chatLogRef} onScroll={handleScroll}>
          <ScrollMessages messages={displayMessages} ministerName={minister.name} ministers={ministers} />
          {(scrollState.kind === "error" || (scrollState.kind === "night" && scrollState.refreshError)) && (
            <div className="chat-system-note danger" role="alert">召对记录读取失败，请稍后重试。</div>
          )}
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
              暂离
            </button>
            <button className="secondary-action composer-retreat" onClick={() => onSend("退朝")} disabled={!!busy}>
              退朝
            </button>
            {composerHint && <div className="composer-hint">{composerHint}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

export function EdictModal({
  state,
  directiveText,
  editingDirectiveId,
  editingDirectiveText,
  decree,
  report,
  busy,
  error,
  onDirectiveTextChange,
  onEditingTextChange,
  onCreateDirective,
  onStartEdit,
  onCancelEdit,
  onSaveDirective,
  onDeleteDirective,
  onAdvanceWithoutEdict,
  onOpenFailureRecovery,
}: {
  state: GameState;
  directiveText: string;
  editingDirectiveId: number | null;
  editingDirectiveText: string;
  decree: string;
  report: string;
  busy: string;
  error: string;
  onDirectiveTextChange: (value: string) => void;
  onEditingTextChange: (value: string) => void;
  onCreateDirective: () => void;
  onStartEdit: (directive: Directive) => void;
  onCancelEdit: () => void;
  onSaveDirective: (directive: Directive) => void;
  onDeleteDirective: (directiveId: number) => void;
  onAdvanceWithoutEdict: () => void;
  onOpenFailureRecovery: () => void;
}) {
  // Conversational directives are approved when the audience turn settles (ADR 0049).
  // Historical `pending` labels are therefore ordinary drafts here, never a second review gate.
  const draftDirectives = state.directives;
  const hasPendingConversationalDraft = (state.pending_directive_count ?? 0) > 0;
  const hasNonEdictPendingActions = (state.pending_non_directive_action_count ?? 0) > 0;
  const hasFailedSecretOrders = (state.failed_secret_order_count ?? 0) > 0;

  // 御案只列尚未成案的候选；结束回合是唯一提交边界，不再生成月末复审工作台。
  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          <h2>本月指令{draftDirectives.length ? ` · ${draftDirectives.length} 道` : ""}</h2>
          <div className="directive-list">
            {draftDirectives.map((directive) => (
              <div className="directive-item" key={directive.id}>
                <div className="directive-head">
                  <b>#{directive.id}</b>
                  <span>{directive.source}</span>
                </div>
                {editingDirectiveId === directive.id ? (
                  <div className="directive-edit">
                    <textarea value={editingDirectiveText} onChange={(event) => onEditingTextChange(event.target.value)} />
                    <div>
                      <button className="icon-button" onClick={() => onSaveDirective(directive)} aria-label="保存草案"><Check size={15} /></button>
                      <button className="icon-button" onClick={onCancelEdit} aria-label="取消修改"><X size={15} /></button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p>{directive.text}</p>
                    {directive.notes ? <small>{directive.notes}</small> : null}
                    <div className="directive-tools">
                      <button onClick={() => onStartEdit(directive)}><Edit3 size={14} />改</button>
                      <button onClick={() => onDeleteDirective(directive.id)}><Trash2 size={14} />删</button>
                    </div>
                  </>
                )}
              </div>
            ))}
            {!draftDirectives.length && !hasPendingConversationalDraft && !hasNonEdictPendingActions && !hasFailedSecretOrders && <div className="empty-note">本月尚无明发诏令，可退朝或在右侧御笔自拟。</div>}
            {!draftDirectives.length && hasPendingConversationalDraft && <div className="empty-note pending-draft-hint">大臣已奉旨起草，退朝时按既有规则成案。</div>}
            {!draftDirectives.length && !hasPendingConversationalDraft && hasFailedSecretOrders && (
              <div className="empty-note failed-secret-note">
                <span>尚有密令落库失败可稍后处理；可先退朝，不阻断本月推进。</span>
                <button type="button" onClick={onOpenFailureRecovery} disabled={!!busy}>处理</button>
              </div>
            )}
            {!draftDirectives.length && !hasPendingConversationalDraft && !hasFailedSecretOrders && hasNonEdictPendingActions && (
              <div className="empty-note">尚有召对事项候旨，退朝后按沉默准行处理。</div>
            )}
          </div>
        </section>

        <section className="desk-pane desk-compose">
          <h2>御笔自拟</h2>
          <textarea
            value={directiveText}
            onChange={(event) => onDirectiveTextChange(event.target.value)}
            placeholder="例如：命毕自严核拨关宁、山海关、蓟镇辽饷一百五十二万两..."
          />
          <button className="desk-add-btn" onClick={onCreateDirective} disabled={!!busy || !directiveText.trim()}>
            <Edit3 size={14} />新增草案
          </button>
          {busy && <div className="busy-line"><Loader2 size={15} />{busy}...</div>}
          {error && <div className="error-line" role="alert">{error}</div>}
        </section>
      </div>

      <div className="desk-footer">
        <button className="seal-btn-compose" onClick={onAdvanceWithoutEdict} disabled={!!busy}>
          退朝 →
        </button>
      </div>
    </div>
  );
}


// 官职品级权重，数字越小品级越高（排越前）
export function officeRank(office: string): number {
  if (/首辅/.test(office)) return 1;
  if (/次辅/.test(office)) return 2;
  if (/大学士/.test(office)) return 3;
  if (/尚书/.test(office)) return 4;
  if (/侍郎/.test(office)) return 5;
  if (/都御史|巡抚|总督/.test(office)) return 6;
  if (/郎中/.test(office)) return 8;
  return 9;
}

export function filterMinisters(ministers: Minister[], group: string) {
  const courtMinisters = ministers.filter((m) => (m.power_id || "ming") === "ming");
  if (group === "内阁+六部" || group === "内阁" || group === "六部") {
    return courtMinisters
      .filter((m) =>
        (m.office_type === "内阁" || ["吏部", "户部", "礼部", "兵部", "刑部", "工部"].includes(m.office_type))
        && m.status === "active"
        && !!(m.office || "").trim()
        && !/前|罢|致仕/.test(m.office || "")  // 无实职不排朝班
      )
      .sort((a, b) => officeRank(a.office || "") - officeRank(b.office || ""));
  }
  if (group === "在职") return courtMinisters.filter((m) => m.status === "active");
  if (group === "收藏") return courtMinisters.filter((minister) => minister.favorite);
  return courtMinisters;
}

export function filterConsorts(consorts: Minister[], group: string) {
  const mingConsorts = consorts.filter((c) => (c.power_id || "ming") === "ming");
  if (group === "收藏") return mingConsorts.filter((c) => c.favorite);
  return mingConsorts;
}
