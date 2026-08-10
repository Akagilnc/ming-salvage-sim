import React from "react";
import { Check, Edit3, Loader2, Trash2, X } from "lucide-react";
import type { Directive, GameState } from "../types";

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
  onWriteDecree,
  onAdvanceWithoutEdict,
  onSaveDecree,
  onResetDecree,
  onIssueDecree,
  onConfirmDirective,
  onRejectDirective,
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
  onWriteDecree: () => void;
  onAdvanceWithoutEdict: () => void;
  onSaveDecree: (text: string) => void;
  onResetDecree: () => void;
  onIssueDecree: () => void;
  onConfirmDirective: (directiveId: number) => void;
  onRejectDirective: (directiveId: number) => void;
  onOpenFailureRecovery: () => void;
}) {
  const pendingDirectives = state.directives.filter((d) => d.status === "pending");
  const draftDirectives = state.directives.filter((d) => d.status !== "pending");
  const hasPending = pendingDirectives.length > 0;
  const hasPendingConversationalDraft = (state.pending_directive_count ?? 0) > 0;
  const hasNonEdictPendingActions = (state.pending_non_directive_action_count ?? 0) > 0;
  const hasFailedSecretOrders = (state.failed_secret_order_count ?? 0) > 0;
  const canAdvanceWithoutEdict = !draftDirectives.length && !hasPendingConversationalDraft;
  const [decreeDraft, setDecreeDraft] = React.useState(decree);
  React.useEffect(() => {
    setDecreeDraft(decree);
  }, [decree]);

  // 分幕：随 decree/report 态切。无诏文=御案理政；有诏文未结算=诏书御览；已结算=颁诏奏章。
  const phase: "desk" | "review" | "issued" = report ? "issued" : decree ? "review" : "desk";

  if (phase === "issued") {
    return (
      <div className="edict-stage edict-stage-issued">
        {error && <div className="error-line" role="alert">{error}</div>}
        <DecreeScroll text={decree} sealed />
        {report ? (
          <section className="edict-gazette">
            <h2>月末奏章</h2>
            <pre>{report}</pre>
          </section>
        ) : null}
      </div>
    );
  }

  if (phase === "review") {
    return (
      <div className="edict-stage edict-stage-review">
        {busy && <div className="busy-line"><Loader2 size={15} />{busy}...</div>}
        {error && <div className="error-line" role="alert">{error}</div>}
        <DecreeScroll text={decreeDraft} editable onChange={setDecreeDraft} />
        <div className="edict-review-bar">
          <button
            className="seal-btn-ghost"
            onClick={onResetDecree}
            disabled={!!busy}
          >
            <Edit3 size={15} />返工改稿
          </button>
          {decreeDraft !== decree && (
            <button
              className="seal-btn-save"
              onClick={() => onSaveDecree(decreeDraft)}
              disabled={!!busy || !decreeDraft.trim()}
            >
              <Check size={15} />存改
            </button>
          )}
          <button
            className="seal-btn-issue"
            onClick={onIssueDecree}
            disabled={!!busy || decreeDraft !== decree}
            title={decreeDraft !== decree ? "请先存改诏文" : "盖玉玺，诏告天下"}
          >
            盖玺颁布
          </button>
        </div>
      </div>
    );
  }

  // phase === "desk"：御案理政
  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          {hasPending && (
            <div className="pending-directives" role="region" aria-label="待核定大臣拟旨">
              <h3>朱批待定 · 大臣拟旨（{pendingDirectives.length}）</h3>
              {pendingDirectives.map((directive) => (
                <div className="directive-item pending" key={directive.id}>
                  <div className="directive-head">
                    <b>#{directive.id}</b>
                    <span>{directive.source}</span>
                  </div>
                  <p>{directive.text}</p>
                  {directive.notes ? <small>{directive.notes}</small> : null}
                  <div className="directive-tools">
                    <button className="vermilion-yes" onClick={() => onConfirmDirective(directive.id)} disabled={!!busy}><Check size={14} />准</button>
                    <button className="vermilion-no" onClick={() => onRejectDirective(directive.id)} disabled={!!busy}><X size={14} />驳</button>
                  </div>
                </div>
              ))}
            </div>
          )}
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
            {!draftDirectives.length && !hasPending && !hasPendingConversationalDraft && !hasNonEdictPendingActions && !hasFailedSecretOrders && <div className="empty-note">本月尚无明发诏令，可退朝或在右侧御笔自拟。</div>}
            {!draftDirectives.length && !hasPending && hasPendingConversationalDraft && <div className="empty-note pending-draft-hint">大臣已奉旨起草，点「拟诏」即可正式成稿。</div>}
            {!draftDirectives.length && !hasPending && !hasPendingConversationalDraft && hasFailedSecretOrders && (
              <div className="empty-note failed-secret-note">
                <span>尚有密令落库失败可稍后处理；可先退朝，不阻断本月推进。</span>
                <button type="button" onClick={onOpenFailureRecovery} disabled={!!busy}>处理</button>
              </div>
            )}
            {!draftDirectives.length && !hasPending && !hasPendingConversationalDraft && !hasFailedSecretOrders && hasNonEdictPendingActions && (
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
        {hasPending && <small className="pending-hint">尚有 {pendingDirectives.length} 道大臣拟旨待朱批（准/驳），核定后方可拟诏。</small>}
        {canAdvanceWithoutEdict ? (
          <button
            className="seal-btn-compose"
            onClick={onAdvanceWithoutEdict}
            disabled={!!busy || hasPending}
          >
            退朝 →
          </button>
        ) : (
          <button
            className="seal-btn-compose"
            onClick={onWriteDecree}
            disabled={!!busy || (!draftDirectives.length && !hasPendingConversationalDraft) || hasPending}
          >
            拟诏 →
          </button>
        )}
      </div>
    </div>
  );
}


// 明黄诏书卷轴：竖排右起，古制体例。editable 时点开变 textarea 改稿。
function DecreeScroll({
  text,
  editable,
  sealed,
  onChange,
}: {
  text: string;
  editable?: boolean;
  sealed?: boolean;
  onChange?: (value: string) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  return (
    <div className={`decree-scroll${sealed ? " sealed" : ""}`}>
      <div className="decree-scroll-knob top" aria-hidden="true" />
      <div className="decree-scroll-paper">
        {editable && editing ? (
          <textarea
            className="decree-scroll-edit"
            value={text}
            autoFocus
            onChange={(event) => onChange?.(event.target.value)}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <div
            className="decree-scroll-body"
            onClick={editable ? () => setEditing(true) : undefined}
            title={editable ? "点此朱笔改稿" : undefined}
          >
            {text || "（诏文待拟）"}
          </div>
        )}
        {sealed ? <div className="decree-seal-mark" aria-hidden="true">勅</div> : null}
      </div>
      <div className="decree-scroll-knob bottom" aria-hidden="true" />
    </div>
  );
}


// 官职品级权重，数字越小品级越高（排越前）
