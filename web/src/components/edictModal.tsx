import React from "react";
import { Loader2, Trash2, X } from "lucide-react";
import type { CasedDirective, GameState, LocalDirectiveItem } from "../types";

/** #1764：source/actor 结构化字段直接并列（P7/0142；非角色台词模板）。 */
function sourceLabel(source: string, actor: string): string {
  // #1834 F16：判空用 trim 副本；展示取值保原文。
  const src = source || "";
  const who = actor || "";
  if (who.trim() && src.trim()) return `${src} · ${who}`;
  return who.trim() ? who : src;
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
  busy,
  error,
  localDirectives = [],
  onDeleteDirective,
  onIssueDecree,
}: {
  state: GameState;
  busy: string;
  error: string;
  /** #1764：本地在飞/失败项（会话态）。 */
  localDirectives?: LocalDirectiveItem[];
  onDeleteDirective: (directiveId: number) => void;
  /** #1277/#1560：有可结算工作（草案或 resolve_turn 可消费 pending）时主钮走盖玺颁诏；真空禁用。 */
  onIssueDecree: () => void;
}) {
  // Conversational directives are approved when the audience turn settles (ADR 0049).
  // Historical `pending` labels are therefore ordinary drafts here, never a second review gate.
  const draftDirectives = state.directives;
  const casedDirectives: CasedDirective[] = state.cased_directives ?? [];
  // save/delete 绑在既有草案卡，不另占席（#1902 J4：无 directiveId 的会话卡已删）。
  const requestByDirectiveId = new Map(
    localDirectives.map((item) => [item.directiveId, item]),
  );
  // deskCount 仅呈现条数；动作/恢复门控不得依赖它（#1764）。
  const deskCount = draftDirectives.length + casedDirectives.length;
  const hasDrafts = draftDirectives.length > 0;
  const hasCased = casedDirectives.length > 0;
  const hasPendingConversationalDraft = (state.pending_directive_count ?? 0) > 0;
  const hasNonEdictPendingActions = (state.pending_non_directive_action_count ?? 0) > 0;
  const hasPendingSecretOrders = (state.pending_secret_order_count ?? 0) > 0;
  // draft/pending/cased 走 issue/stream；真空禁用。
  // #1764：已成案·待盖玺亦是可结算工作（list_directives 滤掉后仍须能盖玺）。
  // #1853 J5：终态业务拒收不再以 failed 计数开启退朝确认支线。
  const hasSettleWork =
    hasDrafts || hasCased || hasPendingConversationalDraft || hasNonEdictPendingActions || hasPendingSecretOrders;
  // 请求按钮禁重复点击：全局 busy 或任一卡在飞。
  const requestLocked =
    !!busy || localDirectives.some((item) => item.phase === "inflight");
  const onFooterClick = hasSettleWork ? onIssueDecree : undefined;

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

  // 御案两区：草稿（可删）/ 已发的旨意（成案只读，0048 无准驳）。
  const showDraftZone = draftDirectives.length > 0;
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
                        {/* 来源头与 phase chip 并列：save/delete 在飞或失败时来源仍可辨，不与 req 互斥。 */}
                        <span data-role="source-label">{sourceLabel(directive.source, directive.actor)}</span>
                        {req ? <PhaseChip phase={req.phase} /> : null}
                      </div>
                      {renderBody(directive.text, bodyId, directive.notes)}
                      {renderFailNote(failMsg, errorId)}
                      {!inflight ? (
                        <div className="directive-tools">
                          <button onClick={() => onDeleteDirective(directive.id)} disabled={requestLocked}>
                            <Trash2 size={14} />删
                          </button>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
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

        {/* #1902：御笔自拟面板（拟新旨/改稿）随拟诏台手写入口退役；旨意只从召对来。 */}
      </div>

      {error && <div className="error-line" role="alert">{error}</div>}

      <div className="desk-footer">
        {/* #1560：真空禁用；draft/pending 走 issue。#1853 J5：清退 failed-only 退朝确认。 */}
        <button
          className={hasSettleWork ? "seal-btn-issue" : "seal-btn-compose"}
          onClick={onFooterClick}
          disabled={requestLocked || !hasSettleWork}
        >
          {hasSettleWork ? "盖玺颁诏过月 →" : "退朝结束本月 →"}
        </button>
      </div>
    </div>
  );
}
