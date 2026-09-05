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

// 颁诏结算流：盖玺颁诏 / failed-only 退朝 / HITL 决策点续裁 / 失败重拉，共用 SSE 推演进度区。
// 结算完成一律整页刷新，草案/对话/局势/closed 弹窗全部按新 state 重新初始化。
export function useSettlementFlow({
  setBusy,
  setError,
  cheatDirective,
  setCheatDirective,
  loadState,
  surfacePendingActionFailures,
  state,
}: {
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  cheatDirective: string;
  setCheatDirective: (text: string) => void;
  loadState: () => Promise<GameState | null>;
  surfacePendingActionFailures: (failures?: PendingActionFailure[]) => Promise<boolean>;
  state: GameState | null;
}) {
  const [settleStage, setSettleStage] = React.useState("");
  const [settleProgress, setSettleProgress] = React.useState<{ current: number; total: number } | null>(null);
  const [settleThinking, setSettleThinking] = React.useState("");
  const [settleNarrative, setSettleNarrative] = React.useState("");
  // HITL 决策点：颁诏推演若出重大抉择，暂停弹窗逐个亲裁，裁完续跑结算。
  const [pendingDecisions, setPendingDecisions] = React.useState<PendingDecision[]>([]);
  const [decisionFailures, setDecisionFailures] = React.useState<PendingActionFailure[]>([]);
  const [pausedDecisionError, setPausedDecisionError] = React.useState("");

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

  const applyStage = (update: SettlementStageUpdate) => {
    setSettleStage(update.content);
    // Progress only from typed facts on the SSE payload — never reverse-lookup labels.
    if (
      typeof update.current === "number"
      && typeof update.total === "number"
      && update.total > 0
      && update.current > 0
    ) {
      setSettleProgress({ current: update.current, total: update.total });
    } else {
      setSettleProgress(null);
    }
  };

  // 颁诏/续裁共用：消费 SSE 推演流（settleStream.ts），stage/thinking/text 实时更新进度区。
  const consumeSettle = (response: Response) => consumeSettleStream(response, {
    onStage: applyStage,
    onThinking: (chunk) => setSettleThinking((prev) => prev + chunk),
    onNarrative: (chunk) => setSettleNarrative((prev) => prev + chunk),
  });

  const issueDecree = async () => {
    setBusy("月末结算");
    setSettleStage("");
    setSettleProgress(null);
    setSettleThinking("");
    setSettleNarrative("");
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
        // #1700 / #1418 r2 对称：phase-1 失败后 loadState，使 settling 续跑面可挂上。
        await loadState();
        // main #1442：pending_action_failures 落库面优先。欠账耗尽走失败单源（#1353 fold-in），无补写 CTA。
        const errMsg = typeof outcome.data === "string" ? outcome.data : (errData.message || "颁诏失败。");
        if (await surfacePendingActionFailures(errData?.pending_action_failures || [])) {
          setError(errMsg);
          return;
        }
        setError(errMsg);
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
      await forwardSteamEvents(outcome.data);
      if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
        return;
      }
      // 结算完成：强制整页刷新，草案/对话/局势/closed 弹窗全部按新 state 重新初始化
      window.location.reload();
      return;
    } catch (err) {
      // #1700：与 phase-2 catch 对称，失败后刷新权威相位。
      await loadState();
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  // 皇帝亲裁完所有决策点 / phase2 续跑：走 resolve_decisions/stream。
  // choices 按决策点 idx 顺序；all-decided 续跑可传 []——服务端幂等保留已存 choice。
  // dossier 批红 choice 须带回 dossier_id / dossier_decision（#1490）；勿收窄剥字段。
  // #1620：成功前不清 pendingDecisions——失败时 DecisionModal 不卸载，已选批语自然保留。
  const submitDecisions = async (choices: DecisionChoice[]) => {
    setBusy("月末结算");
    // HITL resume chrome only — no typed wait-progress on this client-side label.
    setSettleStage("圣意亲裁，续推时局");
    setSettleProgress(null);
    setSettleThinking("");
    setSettleNarrative("");
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
        if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
          setPausedDecisionError(msg);
          setError(msg);
          return;
        }
        setPausedDecisionError(msg);
        setError(msg);
        setBusy("");
        return;
      }
      // 成功：清空案头态再 reload（整页刷新仍是月完成权威入口）。
      setPendingDecisions([]);
      setDecisionFailures([]);
      setPausedDecisionError("");
      await forwardSteamEvents(outcome.data);
      if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
        return;
      }
      window.location.reload();
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
  const advanceWithoutEdict = async () => {
    setBusy("退朝");
    setError("");
    // #1351 A1：携客户端所见 turn 作令牌；409 且服务端已更大 → 视作已推进刷新，不报假错。
    const expectedTurn = state?.turn?.turn;
    try {
      const data = await api<{
        state: GameState;
        awaiting_decision?: boolean;
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
      if (await surfacePendingActionFailures(data.pending_action_failures || [])) {
        return;
      }
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
      window.location.reload();
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
      const failures = detail?.pending_action_failures;
      if (Array.isArray(failures) && await surfacePendingActionFailures(failures)) {
        setError(detail?.message || "退朝失败。");
        return;
      }
      const errMsg = err instanceof Error ? err.message : String(err);
      setError(errMsg);
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
    settleStage,
    settleProgress,
    settleThinking,
    settleNarrative,
    pendingDecisions,
    decisionFailures,
    pausedDecisionError,
    issueDecree,
    advanceWithoutEdict,
    submitDecisions,
    resumePhase2,
    retryPendingDecisions,
  };
}
