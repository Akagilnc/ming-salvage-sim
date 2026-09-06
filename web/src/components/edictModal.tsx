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

/**
 * 视觉 phase 装饰。状态可感知性不靠本 chip / data-* / 固定词表：
 * 忙碌=卡根 aria-busy；失败=卡内原始 role=alert + describedby 关联；
 * 草稿 vs 已发 = 两区铬字分区（「草稿」/「已发的旨意」）+ 卡归属 + 已发只读无改删。
 */
function PhaseChip({ phase }: { phase: string }) {
  return (
    <span className="directive-phase-chip" data-role="phase-chip" data-phase={phase} aria-hidden="true">
      {phase === "inflight" ? <Loader2 size={12} className="spin" /> : null}
      {phase === "failed" ? <X size={12} /> : null}
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

/** 卡级 ARIA：忙碌=aria-busy；失败=后代 role=alert + describedby 原始错误；不成 invalid。 */
function cardStateA11y(
  phase: string,
  bodyId: string,
  error?: { id: string; message?: string },
): React.HTMLAttributes<HTMLDivElement> {
  const described = [bodyId];
  if (phase === "failed" && error?.message) described.push(error.id);
  return {
    "aria-busy": phase === "inflight" ? true : undefined,
    "aria-describedby": described.join(" "),
  };
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

  const renderBody = (text: string, bodyId: string, notes?: string) => (
    <>
      <p id={bodyId}>{text}</p>
      {notes ? <small>{notes}</small> : null}
    </>
  );

  const renderFailNote = (message: string | undefined, errorId: string) =>
    message ? (
      <small id={errorId} className="local-fail-note" data-role="local-error" role="alert">{message}</small>
    ) : null;

  // 御案两区：草稿（可改删 + 本地 create + 失败密令恢复）/ 已发的旨意（成案只读，0048 无准驳）。
  // 空区不渲；恢复入口挂草稿区侧，draft 数组为零仍可出区（failed-only 契约）。
  const showDraftZone =
    draftDirectives.length > 0 || createLocals.length > 0 || showFailureRecoveryEntry;
  const showIssuedZone = casedDirectives.length > 0;
  const draftHeadingId = "edict-zone-draft-title";
  const issuedHeadingId = "edict-zone-issued-title";

  return (
    <div className="edict-stage edict-stage-desk">
      <div className="desk-columns">
        <section className="desk-pane desk-memorials">
          <h2>本月指令{deskCount ? ` · ${deskCount} 道` : ""}</h2>
          <div className="directive-list">
            {showDraftZone ? (
              <section className="edict-zone-draft" aria-labelledby={draftHeadingId}>
                <h3 id={draftHeadingId}>草稿</h3>
                {draftDirectives.map((directive) => {
                  const req = requestByDirectiveId.get(directive.id);
                  const phase = req?.phase ?? "draft";
                  const minister = isMinisterSourced(directive.source);
                  const editing = editingDirectiveId === directive.id;
                  const inflight = req?.phase === "inflight";
                  const bodyId = `edict-body-${directive.id}`;
                  const errorId = `edict-err-${directive.id}`;
                  const failMsg = req?.phase === "failed" ? req.error : undefined;
                  return (
                    <div
                      className={cardClassName({ phase, minister, request: req })}
                      key={`draft-${directive.id}`}
                      data-directive-phase={phase === "draft" ? "draft" : phase}
                      data-directive-id={directive.id}
                      data-source={directive.source || ""}
                      data-actor={directive.actor || ""}
                      data-request-op={req?.op || ""}
                      {...cardStateA11y(phase, bodyId, { id: errorId, message: failMsg })}
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
                            id={bodyId}
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
                            {/* 纯本地取消：只清编辑态，不发请求，不吃 requestLocked。 */}
                            <button
                              className="icon-button"
                              onClick={onCancelEdit}
                              aria-label="取消修改"
                            >
                              <X size={15} />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          {renderBody(
                            req?.op === "save" && req.text ? req.text : directive.text,
                            bodyId,
                            directive.notes,
                          )}
                          {renderFailNote(failMsg, errorId)}
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
                      {editing && !inflight ? renderFailNote(failMsg, errorId) : null}
                    </div>
                  );
                })}

                {createLocals.map((local) => {
                  const bodyId = `edict-body-local-${local.localKey}`;
                  const errorId = `edict-err-local-${local.localKey}`;
                  const failMsg = local.phase === "failed" ? local.error : undefined;
                  return (
                    <div
                      className={cardClassName({ phase: local.phase })}
                      key={local.localKey}
                      data-directive-phase={local.phase}
                      data-local-key={local.localKey}
                      {...cardStateA11y(local.phase, bodyId, { id: errorId, message: failMsg })}
                    >
                      <div className="directive-head">
                        <b data-role="local-mark" />
                        <PhaseChip phase={local.phase} />
                      </div>
                      {renderBody(local.text, bodyId)}
                      {renderFailNote(failMsg, errorId)}
                    </div>
                  );
                })}

                {showFailureRecoveryEntry ? (
                  <div className="empty-note failed-secret-note">
                    <button type="button" onClick={onOpenFailureRecovery} disabled={requestLocked}>处理</button>
                  </div>
                ) : null}
              </section>
            ) : null}

            {showIssuedZone ? (
              <section className="edict-zone-issued" aria-labelledby={issuedHeadingId}>
                <h3 id={issuedHeadingId}>已发的旨意</h3>
                {casedDirectives.map((cased) => {
                  const minister = isMinisterSourced(cased.source);
                  const bodyId = `edict-body-cased-${cased.id}`;
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
                      {...cardStateA11y("cased", bodyId)}
                    >
                      <div className="directive-head">
                        <b>#{cased.id}</b>
                        <span data-role="source-label">{sourceLabel(cased.source, cased.actor)}</span>
                      </div>
                      {renderBody(cased.text, bodyId, cased.notes)}
                      {/* 0048：已发区只读，无改删准驳；身份由所在区铬字表达，不写固定状态词、不渲空 chip。 */}
                    </div>
                  );
                })}
              </section>
            ) : null}
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
              {/* 纯本地取消：只收起确认条，不发请求，不吃 requestLocked。 */}
              <button type="button" className="seal-btn-compose" onClick={() => setConfirmAdvance(false)}>
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
