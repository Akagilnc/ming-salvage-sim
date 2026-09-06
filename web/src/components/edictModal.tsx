import React from "react";
import { Check, Edit3, Loader2, Trash2, X } from "lucide-react";
import type { CasedDirective, Directive, GameState, LocalDirectiveItem } from "../types";

/** #1764：呈现层对 source/actor 结构化字段特征化（P7：不写死模板句）。 */
function sourceLabel(source: string, actor: string): string {
  const src = (source || "").trim();
  const who = (actor || "").trim();
  if (who && src) return `${src} · ${who}`;
  return who || src;
}

function isMinisterSourced(source: string, actor: string): boolean {
  const src = (source || "").trim();
  if (actor && actor.trim()) return true;
  // 既有 source 取值域特征：大臣拟旨 / chat 等；不锁展示措辞。
  return src.includes("大臣") || src === "chat" || src.startsWith("legacy");
}

/** 结构化 phase / dossier_status → 短特征词（测试只咬 data-phase，不锁措辞）。 */
function phaseFeature(phase: string, dossierStatus?: string): string {
  if (phase === "inflight") return "拟稿中";
  if (phase === "failed") return "未收下";
  if (phase === "cased") {
    const st = (dossierStatus || "").trim();
    if (st === "proposed" || !st) return "已成案·待盖玺";
    return st;
  }
  return phase;
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
  localDirectives = [],
  onDirectiveTextChange,
  onEditingTextChange,
  onCreateDirective,
  onStartEdit,
  onCancelEdit,
  onSaveDirective,
  onDeleteDirective,
  onIssueDecree,
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
  /** #1764：本地在飞/失败项（会话态）。 */
  localDirectives?: LocalDirectiveItem[];
  onDirectiveTextChange: (value: string) => void;
  onEditingTextChange: (value: string) => void;
  onCreateDirective: () => void;
  onStartEdit: (directive: Directive) => void;
  onCancelEdit: () => void;
  onSaveDirective: (directive: Directive) => void;
  onDeleteDirective: (directiveId: number) => void;
  /** #1277/#1560：有可结算工作（草案或 resolve_turn 可消费 pending）时主钮走盖玺颁诏；真空禁用。 */
  onIssueDecree: () => void;
  /** #1560：failed-only 确认后退朝；复用既有 advance_without_edict 客户端接缝。 */
  onAdvanceWithoutEdict: () => void;
  onOpenFailureRecovery: () => void;
}) {
  // Conversational directives are approved when the audience turn settles (ADR 0049).
  // Historical `pending` labels are therefore ordinary drafts here, never a second review gate.
  const draftDirectives = state.directives;
  const casedDirectives: CasedDirective[] = state.cased_directives ?? [];
  const deskCount = draftDirectives.length + casedDirectives.length + localDirectives.length;
  const hasDrafts = draftDirectives.length > 0;
  const hasCased = casedDirectives.length > 0;
  const hasPendingConversationalDraft = (state.pending_directive_count ?? 0) > 0;
  const hasNonEdictPendingActions = (state.pending_non_directive_action_count ?? 0) > 0;
  const hasPendingSecretOrders = (state.pending_secret_order_count ?? 0) > 0;
  const hasFailedSecretOrders = (state.failed_secret_order_count ?? 0) > 0;
  // draft/pending/cased 走 issue/stream；failed-only 另开确认后退朝；真空禁用。
  // #1764：已成案·待盖玺亦是可结算工作（list_directives 滤掉后仍须能盖玺）。
  const hasSettleWork =
    hasDrafts || hasCased || hasPendingConversationalDraft || hasNonEdictPendingActions || hasPendingSecretOrders;
  const failedOnly = !hasSettleWork && hasFailedSecretOrders;
  // #1732 B：failed-only 页脚就地条，补退朝语义；取消零请求。
  const [confirmAdvance, setConfirmAdvance] = React.useState(false);
  React.useEffect(() => {
    if (!failedOnly) setConfirmAdvance(false);
  }, [failedOnly]);
  const onFooterClick = hasSettleWork
    ? onIssueDecree
    : failedOnly
      ? () => setConfirmAdvance(true)
      : undefined;

  // 御案：未成案候选（可改删）⊕ 已成案只读投影（0048 无准驳）⊕ 本地在飞/失败。
  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          <h2>本月指令{deskCount ? ` · ${deskCount} 道` : ""}</h2>
          <div className="directive-list">
            {draftDirectives.map((directive) => {
              const minister = isMinisterSourced(directive.source, directive.actor);
              return (
                <div
                  className={`directive-item${minister ? " minister-sourced" : ""}`}
                  key={`draft-${directive.id}`}
                  data-directive-phase="draft"
                  data-directive-id={directive.id}
                  data-source={directive.source || ""}
                  data-actor={directive.actor || ""}
                >
                  <div className="directive-head">
                    <b>#{directive.id}</b>
                    <span data-role="source-label">{sourceLabel(directive.source, directive.actor)}</span>
                  </div>
                  {editingDirectiveId === directive.id ? (
                    <div className="directive-edit">
                      <textarea value={editingDirectiveText} onChange={(event) => onEditingTextChange(event.target.value)} />
                      <div>
                        <button className="icon-button" onClick={() => onSaveDirective(directive)} aria-label="保存草案" disabled={!!busy}><Check size={15} /></button>
                        <button className="icon-button" onClick={onCancelEdit} aria-label="取消修改" disabled={!!busy}><X size={15} /></button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p>{directive.text}</p>
                      {directive.notes ? <small>{directive.notes}</small> : null}
                      <div className="directive-tools">
                        <button onClick={() => onStartEdit(directive)} disabled={!!busy}><Edit3 size={14} />改</button>
                        <button onClick={() => onDeleteDirective(directive.id)} disabled={!!busy}><Trash2 size={14} />删</button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}

            {casedDirectives.map((cased) => {
              const minister = isMinisterSourced(cased.source, cased.actor);
              return (
                <div
                  className={`directive-item cased${minister ? " minister-sourced" : ""}`}
                  key={`cased-${cased.id}`}
                  data-directive-phase="cased"
                  data-directive-id={cased.id}
                  data-dossier-id={cased.dossier_id}
                  data-dossier-status={cased.dossier_status}
                  data-source={cased.source || ""}
                  data-actor={cased.actor || ""}
                >
                  <div className="directive-head">
                    <b>#{cased.id}</b>
                    <span className="directive-phase-chip" data-role="phase-chip" data-phase="cased">
                      {phaseFeature("cased", cased.dossier_status)}
                    </span>
                  </div>
                  <div className="directive-head secondary">
                    <span data-role="source-label">{sourceLabel(cased.source, cased.actor)}</span>
                  </div>
                  <p>{cased.text}</p>
                  {cased.notes ? <small>{cased.notes}</small> : null}
                  {/* 0048：已成案只读，无改删准驳。 */}
                </div>
              );
            })}

            {localDirectives.map((local) => (
              <div
                className={`directive-item local-${local.phase}`}
                key={local.localKey}
                data-directive-phase={local.phase}
                data-local-key={local.localKey}
              >
                <div className="directive-head">
                  <b data-role="local-mark" />
                  <span
                    className="directive-phase-chip"
                    data-role="phase-chip"
                    data-phase={local.phase}
                  >
                    {local.phase === "inflight" ? <Loader2 size={12} className="spin" /> : null}
                    {phaseFeature(local.phase)}
                  </span>
                </div>
                <p>{local.text}</p>
                {local.phase === "failed" && local.error ? (
                  <small className="local-fail-note" data-role="local-error" role="alert">{local.error}</small>
                ) : null}
              </div>
            ))}

            {!deskCount && !hasPendingConversationalDraft && hasFailedSecretOrders && (
              <div className="empty-note failed-secret-note">
                <button type="button" onClick={onOpenFailureRecovery} disabled={!!busy}>处理</button>
              </div>
            )}
          </div>
        </section>

        <section className="desk-pane desk-compose">
          <h2>御笔自拟</h2>
          <textarea
            value={directiveText}
            onChange={(event) => onDirectiveTextChange(event.target.value)}
            placeholder="例如：命户部核拨关宁、山海关、蓟镇辽饷一百五十二万两..."
            disabled={!!busy}
          />
          <button className="desk-add-btn" onClick={onCreateDirective} disabled={!!busy || !directiveText.trim()}>
            <Edit3 size={14} />新增草案
          </button>
          {/* #1764：去掉 compose 全局 busy-line；按钮 disabled 即禁写互斥。 */}
        </section>
      </div>

      {error && <div className="error-line" role="alert">{error}</div>}

      <div className="desk-footer">
        {/* #1560：真空禁用；draft/pending 走 issue；failed-only 确认后 advance。 */}
        {failedOnly && confirmAdvance ? (
          <div className="edict-footer-confirm" role="group" aria-label="退朝确认">
            <div className="edict-footer-confirm-title">退朝确认</div>
            <div className="edict-footer-confirm-body">
              本月无可颁诏草案，仍有失败密令未处理。确认不经盖玺颁诏、直接退朝结束本月？
            </div>
            <div className="edict-footer-confirm-actions">
              <button type="button" className="seal-btn-compose" disabled={!!busy} onClick={() => setConfirmAdvance(false)}>
                取消
              </button>
              <button type="button" className="seal-btn-issue" disabled={!!busy} onClick={onAdvanceWithoutEdict}>
                退朝结束本月
              </button>
            </div>
          </div>
        ) : (
          <button
            className={hasSettleWork || failedOnly ? "seal-btn-issue" : "seal-btn-compose"}
            onClick={onFooterClick}
            disabled={!!busy || (!hasSettleWork && !failedOnly)}
          >
            {hasSettleWork ? "盖玺颁诏过月 →" : "退朝结束本月 →"}
          </button>
        )}
      </div>
    </div>
  );
}
