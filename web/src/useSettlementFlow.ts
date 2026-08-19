import React from "react";
import { ApiRequestError, api } from "./api";
import { consumeSettleStream } from "./settleStream";
import {
  needsPhase2Resume,
  replacePendingDecisionsOnRefresh,
  routeIssueDecisions,
  routeRefreshDecisions,
  routeRetryDecisions,
} from "./decisionRouting";
import { forwardSteamEvents } from "./steamEvents";
import type { GameState, PendingActionFailure, PendingDecision } from "./types";

// 颁诏结算流：盖玺颁诏 / 退朝 / HITL 决策点续裁 / 失败重拉，共用 SSE 推演进度区。
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
  const [settleThinking, setSettleThinking] = React.useState("");
  const [settleNarrative, setSettleNarrative] = React.useState("");
  // HITL 决策点：颁诏推演若出重大抉择，暂停弹窗逐个亲裁，裁完续跑结算。
  const [pendingDecisions, setPendingDecisions] = React.useState<PendingDecision[]>([]);
  const [decisionFailures, setDecisionFailures] = React.useState<PendingActionFailure[]>([]);
  const [pausedDecisionError, setPausedDecisionError] = React.useState("");

  // 刷新恢复：若回合停在 awaiting_decision 且有未裁决策点，自动重弹决策弹窗。
  React.useEffect(() => {
    if (!state) return;
    const route = routeRefreshDecisions(state.turn.phase, state.pending_decisions || []);
    if (route.pendingDecisions !== null) {
      const next = route.pendingDecisions;
      setPendingDecisions((prev) => replacePendingDecisionsOnRefresh(prev, next) || []);
    }
    if (route.error !== null) setPausedDecisionError(route.error);
  }, [state]);

  // 颁诏/续裁共用：消费 SSE 推演流（settleStream.ts），stage/thinking/text 实时更新进度区。
  const consumeSettle = (response: Response) => consumeSettleStream(response, {
    onStage: (text) => setSettleStage(text),
    onThinking: (chunk) => setSettleThinking((prev) => prev + chunk),
    onNarrative: (chunk) => setSettleNarrative((prev) => prev + chunk),
  });

  const issueDecree = async () => {
    setBusy("月末结算");
    setSettleStage("");
    setSettleThinking("");
    setSettleNarrative("");
    setError("");
    try {
      // 作弊强制结算项随颁诏一次性穿入；发出即清空，绝不跨回合。
      const cheatPayload = cheatDirective.trim();
      const response = await fetch("/api/decree/issue/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cheat: cheatPayload }),
      });
      if (cheatPayload) {
        setCheatDirective("");
      }
      const outcome = await consumeSettle(response);
      if (outcome.kind === "error") {
        if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
          setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "颁诏失败。"));
          return;
        }
        setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "颁诏失败。"));
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
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  // 皇帝亲裁完所有决策点 / phase2 续跑：走 resolve_decisions/stream。
  // choices 按决策点 idx 顺序；all-decided 续跑可传 []——服务端幂等保留已存 choice。
  const submitDecisions = async (choices: { label?: string; hint?: string; note?: string }[]) => {
    setPendingDecisions([]);
    setDecisionFailures([]);
    setBusy("月末结算");
    setSettleStage("圣意亲裁，续推时局");
    setSettleThinking("");
    setSettleNarrative("");
    setError("");
    try {
      const response = await fetch("/api/decree/resolve_decisions/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choices }),
      });
      const outcome = await consumeSettle(response);
      if (outcome.kind === "error") {
        // #1418 r2：同会话 phase2 失败后 loadState，使 settle-resume 续跑面可挂上
        // （pending=[] 且 error 横幅被清时仍有 affordance）。
        await loadState();
        if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
          setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。"));
          return;
        }
        setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。"));
        setBusy("");
        return;
      }
      await forwardSteamEvents(outcome.data);
      if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
        return;
      }
      window.location.reload();
      return;
    } catch (err) {
      await loadState();
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  /** #1418 r2：all-decided 续跑——重发 resolve_decisions/stream（空载荷；服务端用已存 choice）。 */
  const resumePhase2 = async () => submitDecisions([]);

  const retryPendingDecisions = async () => {
    setBusy("重新拉取批红");
    setPausedDecisionError("");
    try {
      const freshState = await loadState();
      if (!freshState) return;  // 陈旧代次被协调器拒收（返 null）→ 拒收陈旧 cargo，不据此路由决策
      const events = freshState.pending_decisions || [];
      const route = routeRetryDecisions(freshState.turn.phase, events);
      // #1418 r2：all-decided 不得当成功空批清横幅——接到 phase2 续跑 affordance。
      // 移交 resumePhase2 前先放行本函数 busy，避免 finally 清掉续跑中的「月末结算」。
      if (
        route.resumePhase2
        || needsPhase2Resume(freshState.turn.phase, events, freshState.turn.settlement_display)
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

  const advanceWithoutEdict = async () => {
    setBusy("退朝");
    setError("");
    // #1351 A1：携客户端所见 turn 作令牌；409 且服务端已更大 → 视作已推进刷新，不报假错。
    const expectedTurn = state?.turn?.turn;
    try {
      const data = await api<{ state: GameState; pending_action_failures?: PendingActionFailure[] }>(
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
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  return {
    settleStage,
    settleThinking,
    settleNarrative,
    pendingDecisions,
    decisionFailures,
    pausedDecisionError,
    issueDecree,
    submitDecisions,
    resumePhase2,
    retryPendingDecisions,
    advanceWithoutEdict,
  };
}
