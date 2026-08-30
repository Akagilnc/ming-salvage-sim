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
  onAdvanceWithoutEdict,
  onIssueDecree,
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
  /** #1277/#1560：有草案时主钮走盖玺颁诏；0 草案时主钮禁用。 */
  onIssueDecree: () => void;
  onOpenFailureRecovery: () => void;
}) {
  // Conversational directives are approved when the audience turn settles (ADR 0049).
  // Historical `pending` labels are therefore ordinary drafts here, never a second review gate.
  const draftDirectives = state.directives;
  const hasDrafts = draftDirectives.length > 0;
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
            {!draftDirectives.length && !hasPendingConversationalDraft && !hasNonEdictPendingActions && !hasFailedSecretOrders && <div className="empty-note">本月尚无明发诏令，可退朝结束本月或在右侧御笔自拟。</div>}
            {!draftDirectives.length && hasPendingConversationalDraft && <div className="empty-note pending-draft-hint">大臣已奉旨起草，退朝结束本月时按既有规则成案。</div>}
            {!draftDirectives.length && !hasPendingConversationalDraft && hasFailedSecretOrders && (
              <div className="empty-note failed-secret-note">
                <span>尚有密令落库失败可稍后处理；可先退朝结束本月，不阻断推进。</span>
                <button type="button" onClick={onOpenFailureRecovery} disabled={!!busy}>处理</button>
              </div>
            )}
            {!draftDirectives.length && !hasPendingConversationalDraft && !hasFailedSecretOrders && hasNonEdictPendingActions && (
              <div className="empty-note">尚有召对事项候旨，退朝结束本月后按沉默准行处理。</div>
            )}
          </div>
        </section>

        <section className="desk-pane desk-compose">
          <h2>御笔自拟</h2>
          <textarea
            value={directiveText}
            onChange={(event) => onDirectiveTextChange(event.target.value)}
            placeholder="例如：命户部核拨关宁、山海关、蓟镇辽饷一百五十二万两..."
          />
          <button className="desk-add-btn" onClick={onCreateDirective} disabled={!!busy || !directiveText.trim()}>
            <Edit3 size={14} />新增草案
          </button>
          {busy && <div className="busy-line"><Loader2 size={15} />{busy}...</div>}
          {error && <div className="error-line" role="alert">{error}</div>}
        </section>
      </div>

      <div className="desk-footer">
        {/* #1560：未成案时保留主钮但禁用；成案后盖玺颁诏过月。 */}
        <button
          className={hasDrafts ? "seal-btn-issue" : "seal-btn-compose"}
          onClick={hasDrafts ? onIssueDecree : onAdvanceWithoutEdict}
          disabled={!!busy || !hasDrafts}
        >
          {hasDrafts ? "盖玺颁诏过月 →" : "退朝结束本月 →"}
        </button>
      </div>
    </div>
  );
}
