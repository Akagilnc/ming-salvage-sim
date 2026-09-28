import React from "react";
import { ApiRequestError, api } from "./api";
import { consumeSettleStream, type SettlementStageUpdate } from "./settleStream";
import {
  needsPhase2Resume,
  replacePendingDecisionsOnRefresh,
  routeIssueDecisions,
  routeRefreshDecisions,
  routeRetryDecisions,
} from "./decisionRouting";
import { forwardSteamEvents } from "./steamEvents";
import type {
  DecisionChoice, GameState, PendingActionFailure, PendingDecision,
} from "./types";

/** #1852：当次核账完成后的本面邸报阅读态（刷新不恢复；朕知道了只关此态）。 */
export type SettlementGazetteReading = {
  report: string;
  attendantMessage?: string;
  periodLabel?: string;
};

// 颁诏结算流：盖玺颁诏 / failed-only 退朝 / HITL 决策点续裁 / 失败重拉。
// #1852：核账等待面不呈现推演段文/推敲/进度；写成即推进后本面开邸报阅读态，不整页 reload。
export function useSettlementFlow({
  setBusy,
  setError,
  cheatDirective,
  setCheatDirective,
  loadState,
  state,
  resetLocalEdictState,
  onMonthAdvanced,
}: {
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  cheatDirective: string;
  setCheatDirective: (text: string) => void;
  loadState: () => Promise<GameState | null>;
  state: GameState | null;
  /** #1852：写成即推进后清旧月本地拟诏会话态（compose / failed 卡）。 */
  resetLocalEdictState?: () => void;
  /**
   * #1852：写成即推进成功回调（清 activeModal 等）。
   * 勿在 busy 起时清——#1796 失败清 busy 后拟诏台须能带回 error。
   */
  onMonthAdvanced?: () => void;
}) {
  // HITL 决策点：颁诏推演若出重大抉择，暂停弹窗逐个亲裁，裁完续跑结算。
  const [pendingDecisions, setPendingDecisions] = React.useState<PendingDecision[]>([]);
  const [decisionFailures, setDecisionFailures] = React.useState<PendingActionFailure[]>([]);
  const [pausedDecisionError, setPausedDecisionError] = React.useState("");
  // #1808：phase-1 fail-closed 的 HUD 专用位——与共享 error 分轨，避免召对等通道泄漏到普通 HUD。
  const [settlementHudError, setSettlementHudError] = React.useState("");
  const [settlementGazetteReading, setSettlementGazetteReading] =
    React.useState<SettlementGazetteReading | null>(null);
  // #1852：写成即推进期间挡住 closed/密令/结局自动弹层，避免盖住本面邸报；无正文可呈时随即放下。
  const [postAdvanceOverlayHold, setPostAdvanceOverlayHold] = React.useState(false);
  const sessionGeneration = React.useRef(0);
  const [advanceRefreshFailed, setAdvanceRefreshFailed] = React.useState(false);

  // 刷新恢复：若回合停在 awaiting_decision 且有未裁决策点，自动重弹决策弹窗。
  // #657：typed resume_phase2 时空 pending 不报 PAUSED，接到 phase2 空 POST 续跑。
  React.useEffect(() => {
    if (!state) return;
    // #1625: an observation-page refresh can land while another settlement entry
    // is consuming the desk. Reuse the injected state loader until that wait ends.
    // Gate on inflight alone — entry begins before turn_phase becomes settling
    // (still summoning/reviewing under settlement_display), so phase conjunction
    // would stall the observation page on the locked pre-settle face.
    if (state.settlement_entry_inflight) {
      let cancelled = false;
      let refreshTimer: number;
      const refresh = () => {
        refreshTimer = window.setTimeout(() => {
          void loadState()
            .catch((err) => {
              console.warn("[settlement] inflight refresh failed", err);
            })
            .finally(() => {
              if (!cancelled) refresh();
            });
        }, 1000);
      };
      refresh();
      return () => {
        cancelled = true;
        window.clearTimeout(refreshTimer);
      };
    }
    const route = routeRefreshDecisions(
      state.turn.phase,
      state.pending_decisions || [],
      state.resume_phase2,
    );
    // #1620：all-decided / resume_phase2 时 route 返 pendingDecisions:null——须清本地 residual modal，
    // 接到 settle-resume；未决 pending（!== null）仍走 replace，保留 picks。
    if (route.resumePhase2 === true) {
      setPendingDecisions([]);
    } else if (route.pendingDecisions !== null) {
      const next = route.pendingDecisions;
      setPendingDecisions((prev) => replacePendingDecisionsOnRefresh(prev, next) || []);
    }
    if (route.error !== null) setPausedDecisionError(route.error);
  }, [state, loadState]);

  // 后台机械尾未终结时观察状态：总评落位或代码异常均在原页面呈现。
  React.useEffect(() => {
    if (!state?.mechanical_tail_pending && !state?.ending?.summary_pending) return;
    let cancelled = false;
    let refreshTimer = 0;
    const refresh = () => {
      refreshTimer = window.setTimeout(() => {
        void loadState()
          .catch((err) => {
            console.warn("[ending] summary refresh failed", err);
          })
          .finally(() => {
            if (!cancelled) refresh();
          });
      }, 1000);
    };
    refresh();
    return () => {
      cancelled = true;
      window.clearTimeout(refreshTimer);
    };
  }, [state?.mechanical_tail_pending, state?.ending?.summary_pending, loadState]);

  // #1852：SSE stage/thinking/text 仍消费（流不可断），但不驱动任何等待面呈现。
  const consumeSettle = (response: Response) => consumeSettleStream(response, {
    onStage: (_update: SettlementStageUpdate) => {},
    onThinking: () => {},
    onNarrative: () => {},
  });

  // #1796：盖玺/退朝共用开场——busy 挂同会话切面；清 HUD 失败位。
  // 真源仍是 settlement_display；submitDecisions 另有 HITL 续推文案，不经此路。
  const beginSettlementWait = () => {
    setBusy("月末结算");
    setSettlementHudError("");
  };

  // #1808：phase-1 fail-closed 同时写共享 error（modal 带回）与 HUD 专用位。
  const surfacePhase1Failure = (message: string) => {
    setError(message);
    setSettlementHudError(message);
  };

  // #1808 C：退局/再入局清 HUD 残留——接缝归既有 exitToMenu / enterGameAfterMenu。
  const clearSettlementHudError = React.useCallback(() => {
    setSettlementHudError("");
    setSettlementGazetteReading(null);
    setPostAdvanceOverlayHold(false);
    setAdvanceRefreshFailed(false);
    sessionGeneration.current += 1;
  }, []);

  // 刷新失败后的统一提示与重试交 #1854；本 hook 只保留失败态门闩，不提供独立重试面。
  const dismissSettlementGazette = React.useCallback(() => {
    setSettlementGazetteReading(null);
    if (!advanceRefreshFailed) setPostAdvanceOverlayHold(false);
  }, [advanceRefreshFailed]);

  /** #1852：月份已推进 → 刷账本 + 本面开阅读态（不 reload）。 */
  const openGazetteAfterAdvance = async (payload: Record<string, unknown> | null | undefined) => {
    const data = payload || {};
    const generation = sessionGeneration.current;
    await forwardSteamEvents(data);
    if (generation !== sessionGeneration.current) return;
    // 新月盘面：立刻离开同会话核账面，避免 busy 残留把拟诏等关掉。
    setBusy("");
    // 先挡住过月自动弹层，再 loadState 翻 turn——否则 closed/密令/结局会抢在本面邸报之前。
    setPostAdvanceOverlayHold(true);
    // 过月成功：旧月本地拟诏会话态不得带入新月。
    resetLocalEdictState?.();
    // 盖玺时 activeModal 可能仍挂 edict（busy 仅藏台、未清槽）；成功过月须卸掉，免弹回盖住本面邸报。
    onMonthAdvanced?.();
    // 先保存已收到的邸报：随后刷新失败也不能丢掉当次阅读。
    const embedded = data.state as GameState | undefined;
    let next: GameState | null = null;
    try {
      next = await loadState();
    } catch (err) {
      console.warn("[settlement] post-advance refresh failed", err);
      if (generation !== sessionGeneration.current) return;
      setAdvanceRefreshFailed(true);
      setError(err instanceof Error ? err.message : String(err));
    }
    if (generation !== sessionGeneration.current) return;
    const fromPayload = typeof data.report === "string" ? data.report : "";
    const fromState = next?.previous_summary
      || (typeof embedded?.previous_summary === "string" ? embedded.previous_summary : "")
      || "";
    const report = fromPayload.trim() ? fromPayload : fromState;
    const attendantMessage = next?.last_attendant_message
      || embedded?.last_attendant_message
      || "";
    const periodLabel = next?.previous_reign_period_label
      || embedded?.previous_reign_period_label
      || "";
    if (report.trim() || String(attendantMessage || "").trim()) {
      setSettlementGazetteReading({
        report,
        attendantMessage: attendantMessage || undefined,
        periodLabel: periodLabel || undefined,
      });
    } else {
      setSettlementGazetteReading(null);
      setPostAdvanceOverlayHold(false);
    }
  };

  const issueDecree = async () => {
    beginSettlementWait();
    setError("");
    // #1277/#1351：携客户端所见 turn 作令牌；409 且服务端已更大 → 视作已推进刷新，不报假错。
    // 与 advanceWithoutEdict 同口径；禁前端防抖顶替服务端令牌。
    const expectedTurn = state?.turn?.turn;
    try {
      // 作弊强制结算项随颁诏一次性穿入；发出即清空，绝不跨回合。
      const cheatPayload = cheatDirective.trim();
      const body: Record<string, unknown> = { cheat: cheatPayload };
      if (expectedTurn != null && Number.isFinite(Number(expectedTurn))) {
        body.expected_turn = Number(expectedTurn);
      }
      const response = await fetch("/api/decree/issue/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (cheatPayload) {
        setCheatDirective("");
      }
      const outcome = await consumeSettle(response);
      if (outcome.kind === "error") {
        const errData = typeof outcome.data === "string" ? { message: outcome.data } : (outcome.data || {});
        const serverTurn = Number(errData?.turn);
        if (
          Number(errData?.status_code) === 409
          && expectedTurn != null
          && Number.isFinite(serverTurn)
          && serverTurn > Number(expectedTurn)
        ) {
          window.location.reload();
          return;
        }
        // #1808 B 同类：phase-1 呈现先响亮落地；其后 loadState / pending 消费链 reject 不得吞掉已写告警。
        // #1700 / #1418 r2：loadState 使 settling 续跑面可挂上（best-effort）。
        // main #1442：pending_action_failures 落库面优先。欠账耗尽走失败单源（#1353 fold-in），无补写 CTA。
        const errMsg = typeof outcome.data === "string" ? outcome.data : (errData.message || "颁诏失败。");
        surfacePhase1Failure(errMsg);
        try {
          await loadState();
        } catch (refreshErr) {
          // 刷新失败不抵消已落地的 phase-1 呈现；次级真因仍落痕（ADR 0005）。
          console.warn("[settlement] phase-1 failure refresh failed", refreshErr);
        }
        setBusy("");
        return;
      }
      if (outcome.kind === "decisions") {
        // 出重大抉择：暂停弹窗逐个亲裁，裁完调 submitDecisions 续跑结算。
        // #1234：同会话停窗经既有状态口刷新 React 态——yearMonthLabel / 顶栏四键读到 settlement_display 与快照叠影。
        // 不 reload（整页刷新只在月完成）；不自判核账态；不平行第二展示通道。
        const failures = outcome.data?.pending_action_failures || [];
        setDecisionFailures(failures);
        const route = routeIssueDecisions(outcome.data.decisions || []);
        if (route.pendingDecisions !== null) setPendingDecisions(route.pendingDecisions);
        if (route.error !== null) setPausedDecisionError(route.error);
        await loadState();
        setBusy("");
        return;
      }
      if (outcome.data?.advanced === false) {
        // The month chain can stop at rescript/gazette without advancing.
        // Refresh its durable settling projection, not the whole page as if a new month began.
        await loadState();
        setBusy("");
        return;
      }
      // #1852：写成即推进——loadState + 本面阅读态；不整页 reload。
      await openGazetteAfterAdvance(outcome.data || {});
      setBusy("");
      return;
    } catch (err) {
      // #1808 B 同类：先响亮；#1700 loadState 刷新权威相位为 best-effort。
      surfacePhase1Failure(err instanceof Error ? err.message : String(err));
      try {
        await loadState();
      } catch (refreshErr) {
        // 刷新失败不抵消已落地的 phase-1 呈现；次级真因仍落痕（ADR 0005）。
        console.warn("[settlement] phase-1 failure refresh failed", refreshErr);
      }
      setBusy("");
    }
  };

  // 皇帝亲裁完所有决策点 / phase2 续跑：走 resolve_decisions/stream。
  // choices 按决策点 idx 顺序；all-decided 续跑可传 []——服务端幂等保留已存 choice。
  // dossier 批红 choice 须带回 dossier_id / dossier_decision（#1490）；勿收窄剥字段。
  // #1620：成功前不清 pendingDecisions——失败时 DecisionModal 不卸载，已选批语自然保留。
  const submitDecisions = async (choices: DecisionChoice[]) => {
    setBusy("月末结算");
    setError("");
    setPausedDecisionError("");
    try {
      const response = await fetch("/api/decree/resolve_decisions/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choices }),
      });
      const outcome = await consumeSettle(response);
      if (outcome.kind === "error") {
        // #1418 r2：同会话 phase2 失败后 loadState，使 settle-resume 续跑面可挂上。
        // #1620：loadState 刷新合法 pending 时 route 不碰 stream error；pending 保留 → picks 仍在。
        await loadState();
        const msg = typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。");
        setPausedDecisionError(msg);
        setError(msg);
        setBusy("");
        return;
      }
      // 成功：清空案头态；写成即推进则本面开邸报。
      setPendingDecisions([]);
      setDecisionFailures([]);
      setPausedDecisionError("");
      if (outcome.data?.advanced === false) {
        await loadState();
        setBusy("");
        return;
      }
      await openGazetteAfterAdvance(outcome.data || {});
      setBusy("");
      return;
    } catch (err) {
      await loadState();
      const msg = err instanceof Error ? err.message : String(err);
      setPausedDecisionError(msg);
      setError(msg);
      setBusy("");
    }
  };

  /** #1418 r2：all-decided 续跑——重发 resolve_decisions/stream（空载荷；服务端用已存 choice）。 */
  const resumePhase2 = async () => submitDecisions([]);

  // #1560：failed-only 拟诏台确认后退朝；复用既有 /api/decree/advance_without_edict 接缝。
  // 真空仍禁用；draft/pending 走 issueDecree，不经此路。
  // #1796：与盖玺同 busy 标——同会话立即收拟诏台 + 切核账期面。
  const advanceWithoutEdict = async () => {
    beginSettlementWait();
    setError("");
    // #1351 A1：携客户端所见 turn 作令牌；409 且服务端已更大 → 视作已推进刷新，不报假错。
    const expectedTurn = state?.turn?.turn;
    try {
      const data = await api<{
        state: GameState;
        awaiting_decision?: boolean;
        advanced?: boolean;
        decisions?: PendingDecision[];
        pending_action_failures?: PendingActionFailure[];
      }>(
        "/api/decree/advance_without_edict",
        {
          method: "POST",
          body: JSON.stringify(
            expectedTurn != null && Number.isFinite(Number(expectedTurn))
              ? { expected_turn: Number(expectedTurn) }
              : {},
          ),
        },
      );
      // #1433 / #1337 hop 族：退朝若停在批红，消费 awaiting_decision/decisions（同 issueDecree），
      // 不盲 reload——整页刷新只在月完成；批红面经 loadState 状态口投影不丢。
      if (data.awaiting_decision) {
        const failures = data.pending_action_failures || [];
        setDecisionFailures(failures);
        const route = routeIssueDecisions(data.decisions || []);
        if (route.pendingDecisions !== null) setPendingDecisions(route.pendingDecisions);
        if (route.error !== null) setPausedDecisionError(route.error);
        await loadState();
        return;
      }
      if (data.advanced === false) {
        await loadState();
        return;
      }
      // #1852：退朝写成即推进——本面阅读态，不 reload。
      await openGazetteAfterAdvance({
        ...data,
        report: data.state?.previous_summary,
      });
    } catch (err: any) {
      const detail = err instanceof ApiRequestError
        ? err.detail
        : (err?.detail && typeof err.detail === "object" ? err.detail : err);
      const serverTurn = Number(detail?.turn);
      if (
        Number(detail?.status_code) === 409
        && expectedTurn != null
        && Number.isFinite(serverTurn)
        && serverTurn > Number(expectedTurn)
      ) {
        window.location.reload();
        return;
      }
      // #1808 B：catch 内 await 链 reject 不得全静默——phase-1 呈现先落地，再 best-effort 消费 pending。
      const failures = detail?.pending_action_failures;
      const hasPending = Array.isArray(failures) && failures.length > 0;
      surfacePhase1Failure(
        hasPending
          ? (detail?.message || "退朝失败。")
          : (err instanceof Error ? err.message : String(err)),
      );
    } finally {
      setBusy("");
    }
  };

  const retryPendingDecisions = async () => {
    setBusy("重新拉取批红");
    setPausedDecisionError("");
    try {
      const freshState = await loadState();
      if (!freshState) return;  // 陈旧代次被协调器拒收（返 null）→ 拒收陈旧 cargo，不据此路由决策
      const events = freshState.pending_decisions || [];
      const route = routeRetryDecisions(
        freshState.turn.phase, events, freshState.resume_phase2,
        freshState.settlement_entry_inflight,
      );
      // #1418 r2 / #657：all-decided 或 typed resume 不得当成功空批清横幅——接到 phase2 续跑。
      // 移交 resumePhase2 前先放行本函数 busy，避免 finally 清掉续跑中的「月末结算」。
      if (
        route.resumePhase2
        || needsPhase2Resume(
          freshState.turn.phase,
          events,
          freshState.turn.settlement_display,
          freshState.resume_phase2,
        )
      ) {
        setBusy("");
        await resumePhase2();
        return;
      }
      if (route.pendingDecisions !== null) setPendingDecisions(route.pendingDecisions);
      if (route.error !== null) setPausedDecisionError(route.error);
    } catch (err) {
      setPausedDecisionError(`重新拉取待批决策失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy("");
    }
  };

  return {
    settlementGazetteReading,
    advanceRefreshFailed,
    dismissSettlementGazette,
    /** #1852：本面邸报阅读中或过月刚翻月尚未落阅读态时，挡住自动弹层。 */
    suppressPostAdvanceOverlays: Boolean(settlementGazetteReading) || postAdvanceOverlayHold,
    pendingDecisions,
    decisionFailures,
    pausedDecisionError,
    settlementHudError,
    clearSettlementHudError,
    issueDecree,
    advanceWithoutEdict,
    submitDecisions,
    resumePhase2,
    retryPendingDecisions,
  };
}
