import React from "react";
import { Check, Edit3, Loader2, Trash2, X } from "lucide-react";
import type { CasedDirective, Directive, GameState, LocalDirectiveItem } from "../types";

/** #1764：source/actor 结构化字段直接并列（P7/0142；非角色台词模板）。 */
function sourceLabel(source: string, actor: string): string {
  const src = (source || "").trim();
  const who = (actor || "").trim();
  if (who && src) return `${src} · ${who}`;
  return who || src;
}

/** 权威 source 写入值（session/db）；不猜测 chat/legacy/子串。 */
function isMinisterSourced(source: string): boolean {
  return (source || "").trim() === "大臣拟旨";
}

/** 非文本 phase 辨识：data-phase + 图标；不写固定状态词。 */
function PhaseChip({ phase }: { phase: string }) {
  return (
    <span className="directive-phase-chip" data-role="phase-chip" data-phase={phase}>
      {phase === "inflight" ? <Loader2 size={12} className="spin" aria-hidden /> : null}
      {phase === "failed" ? <X size={12} aria-hidden /> : null}
    </span>
  );
}

type CardRequest = LocalDirectiveItem | undefined;

function cardClassName(opts: {
  phase: string;
  minister?: boolean;
  request?: CardRequest;
}): string {
  const parts = ["directive-item"];
  if (opts.phase === "cased") parts.push("cased");
  if (opts.minister) parts.push("minister-sourced");
  if (opts.request) parts.push(`local-${opts.request.phase}`);
  else if (opts.phase === "inflight" || opts.phase === "failed") parts.push(`local-${opts.phase}`);
  return parts.join(" ");
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
  // save/delete 绑在既有草案卡，不另占席；仅 create 会话卡计入桌面条数。
  const createLocals = localDirectives.filter((item) => item.directiveId == null);
  const requestByDirectiveId = new Map(
    localDirectives
      .filter((item) => item.directiveId != null)
      .map((item) => [item.directiveId as number, item]),
  );
  // deskCount 仅呈现条数（含本地 create 卡）；动作/恢复门控不得依赖它（#1764）。
  const deskCount = draftDirectives.length + casedDirectives.length + createLocals.length;
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
  // 恢复入口：持久桌空 + 失败密令。本地失败 create 卡不挡（非 settle 工作谓词）。
  const showFailureRecoveryEntry =
    !hasDrafts && !hasCased && !hasPendingConversationalDraft && hasFailedSecretOrders;
  // 请求按钮禁重复点击：全局 busy 或任一卡在飞。
  const requestLocked =
    !!busy || localDirectives.some((item) => item.phase === "inflight");
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

  const renderBody = (text: string, notes?: string) => (
    <>
      <p>{text}</p>
      {notes ? <small>{notes}</small> : null}
    </>
  );

  const renderFailNote = (message?: string) =>
    message ? (
      <small className="local-fail-note" data-role="local-error" role="alert">{message}</small>
    ) : null;

  // 御案：未成案候选（可改删）⊕ 已成案只读投影（0048 无准驳）⊕ 本地 create 在飞/失败。
  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          <h2>本月指令{deskCount ? ` · ${deskCount} 道` : ""}</h2>
          <div className="directive-list">
            {draftDirectives.map((directive) => {
              const req = requestByDirectiveId.get(directive.id);
              const phase = req?.phase ?? "draft";
              const minister = isMinisterSourced(directive.source);
              const editing = editingDirectiveId === directive.id;
              const inflight = req?.phase === "inflight";
              return (
                <div
                  className={cardClassName({ phase, minister, request: req })}
                  key={`draft-${directive.id}`}
                  data-directive-phase={phase === "draft" ? "draft" : phase}
                  data-directive-id={directive.id}
                  data-source={directive.source || ""}
                  data-actor={directive.actor || ""}
                  data-request-op={req?.op || ""}
                >
                  <div className="directive-head">
                    <b>#{directive.id}</b>
                    {req ? <PhaseChip phase={req.phase} /> : (
                      <span data-role="source-label">{sourceLabel(directive.source, directive.actor)}</span>
                    )}
                  </div>
                  {editing && !inflight ? (
                    <div className="directive-edit">
                      <textarea
                        value={editingDirectiveText}
                        onChange={(event) => onEditingTextChange(event.target.value)}
                      />
                      <div>
                        <button
                          className="icon-button"
                          onClick={() => onSaveDirective(directive)}
                          aria-label="保存草案"
                          disabled={requestLocked}
                        >
                          <Check size={15} />
                        </button>
                        <button
                          className="icon-button"
                          onClick={onCancelEdit}
                          aria-label="取消修改"
                          disabled={requestLocked}
                        >
                          <X size={15} />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {renderBody(req?.op === "save" && req.text ? req.text : directive.text, directive.notes)}
                      {renderFailNote(req?.phase === "failed" ? req.error : undefined)}
                      {!inflight ? (
                        <div className="directive-tools">
                          <button onClick={() => onStartEdit(directive)} disabled={requestLocked}>
                            <Edit3 size={14} />改
                          </button>
                          <button onClick={() => onDeleteDirective(directive.id)} disabled={requestLocked}>
                            <Trash2 size={14} />删
                          </button>
                        </div>
                      ) : null}
                    </>
                  )}
                  {editing && !inflight ? renderFailNote(req?.phase === "failed" ? req.error : undefined) : null}
                </div>
              );
            })}

            {casedDirectives.map((cased) => {
              const minister = isMinisterSourced(cased.source);
              return (
                <div
                  className={cardClassName({ phase: "cased", minister })}
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
                    <PhaseChip phase="cased" />
                  </div>
                  <div className="directive-head secondary">
                    <span data-role="source-label">{sourceLabel(cased.source, cased.actor)}</span>
                  </div>
                  {renderBody(cased.text, cased.notes)}
                  {/* 0048：已成案只读，无改删准驳。 */}
                </div>
              );
            })}

            {createLocals.map((local) => (
              <div
                className={cardClassName({ phase: local.phase })}
                key={local.localKey}
                data-directive-phase={local.phase}
                data-local-key={local.localKey}
              >
                <div className="directive-head">
                  <b data-role="local-mark" />
                  <PhaseChip phase={local.phase} />
                </div>
                {renderBody(local.text)}
                {renderFailNote(local.phase === "failed" ? local.error : undefined)}
              </div>
            ))}

            {showFailureRecoveryEntry && (
              <div className="empty-note failed-secret-note">
                <button type="button" onClick={onOpenFailureRecovery} disabled={requestLocked}>处理</button>
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
          />
          <button
            className="desk-add-btn"
            onClick={onCreateDirective}
            disabled={requestLocked || !directiveText.trim()}
          >
            <Edit3 size={14} />新增草案
          </button>
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
              <button type="button" className="seal-btn-compose" disabled={requestLocked} onClick={() => setConfirmAdvance(false)}>
                取消
              </button>
              <button type="button" className="seal-btn-issue" disabled={requestLocked} onClick={onAdvanceWithoutEdict}>
                退朝结束本月
              </button>
            </div>
          </div>
        ) : (
          <button
            className={hasSettleWork || failedOnly ? "seal-btn-issue" : "seal-btn-compose"}
            onClick={onFooterClick}
            disabled={requestLocked || (!hasSettleWork && !failedOnly)}
          >
            {hasSettleWork ? "盖玺颁诏过月 →" : "退朝结束本月 →"}
          </button>
        )}
      </div>
    </div>
  );
}
