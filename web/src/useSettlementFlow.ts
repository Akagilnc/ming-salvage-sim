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
import type {
  DecisionChoice, GameState, PendingActionFailure, PendingDecision,
} from "./types";

/** #1852：当次核账完成后的本面邸报阅读态（刷新不恢复；朕知道了只关此态）。 */
export type SettlementGazetteReading = {
  report: string;
  attendantMessage?: string;
  periodLabel?: string;
};

/**
 * #1888：一份回执的自有写权。发起结算请求时封存当时的会话代次，此后本次回执对当前局的
 * 一切副作用——成功邸报、停批、失败告警、账本刷新与异步收尾——都经此对象落地；
 * 退局／再入局推进代次后（clearSettlementHudError），过期写权整体不写。
 *
 * 这是结算回执的**唯一**归属闸口：各出口不再各自比对代次。
 */
type SettlementReceipt = {
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  setCheatDirective: (text: string) => void;
  /** #1808：phase-1 fail-closed 同时写共享 error（modal 带回）与 HUD 专用位。 */
  surfaceFailure: (message: string) => void;
  setPausedDecisionError: (message: string) => void;
  setPendingDecisions: (decisions: PendingDecision[]) => void;
  setDecisionFailures: (failures: PendingActionFailure[]) => void;
  setGazetteReading: (reading: SettlementGazetteReading | null) => void;
  setOverlayHold: (hold: boolean) => void;
  setAdvanceRefreshFailed: (failed: boolean) => void;
  /** 过月成功：清旧月拟诏会话态、卸盖玺弹层。 */
  advanceMonthLocals: () => void;
  /** 账本刷新。过期写权直接拒取——陈旧回执不得翻动当前局盘面。 */
  loadState: () => Promise<GameState | null>;
  /** 409 且服务端已更大：整页刷新恢复陈旧令牌。 */
  reload: () => void;
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
  const [failedEntryWasRetreat, setFailedEntryWasRetreat] = React.useState(false);
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

  // #1852：结算流只认终态；不再挂空 stage/thinking/text 回调。
  const consumeSettle = (response: Response) => consumeSettleStream(response);

  // #1796：盖玺/退朝共用开场——busy 挂同会话切面；清 HUD 失败位。
  // 真源仍是 settlement_display；submitDecisions 另有 HITL 续推文案，不经此路。
  // 发起时同步落 busy（此刻必属当前局），其后一律走回执写权。
  const beginSettlementWait = (retreat = false) => {
    setFailedEntryWasRetreat(retreat);
    setBusy("月末结算");
    setSettlementHudError("");
  };

  // #1808 C：退局/再入局清 HUD 残留——接缝归既有 exitToMenu / enterGameAfterMenu。
  const clearSettlementHudError = React.useCallback(() => {
    setSettlementHudError("");
    setFailedEntryWasRetreat(false);
    setSettlementGazetteReading(null);
    setPostAdvanceOverlayHold(false);
    setAdvanceRefreshFailed(false);
    sessionGeneration.current += 1;
  }, []);

  /**
   * #1888：回执归属的唯一闸口。发起结算请求时调用一次，封存当时的会话代次；
   * 此后本次回执的全部副作用都经返回的写权对象落地。退局／再入局推进代次后，
   * 过期写权的每个出口（成功、停批、失败、异步收尾、账本刷新、整页刷新）一律不写。
   *
   * 此前各出口零散比对代次，只有邸报成功出口设防，失败分支仍写当前局；且代次在
   * 「回执到达时」读取即拿自己跟自己比，闸门恒开。此处改为发起时封存，闸门才真正生效。
   */
  const claimReceipt = React.useCallback((): SettlementReceipt => {
    const generation = sessionGeneration.current;
    const owned = () => generation === sessionGeneration.current;
    const write = <T,>(apply: (value: T) => void) => (value: T) => {
      if (owned()) apply(value);
    };
    return {
      setBusy: write(setBusy),
      setError: write(setError),
      setCheatDirective: write(setCheatDirective),
      setPausedDecisionError: write(setPausedDecisionError),
      setPendingDecisions: write(setPendingDecisions),
      setDecisionFailures: write(setDecisionFailures),
      setGazetteReading: write(setSettlementGazetteReading),
      setOverlayHold: write(setPostAdvanceOverlayHold),
      setAdvanceRefreshFailed: write(setAdvanceRefreshFailed),
      // #1808：共享 error（modal 带回）与 HUD 专用位同落。
      surfaceFailure: (message: string) => {
        if (!owned()) return;
        setError(message);
        setSettlementHudError(message);
      },
      advanceMonthLocals: () => {
        if (!owned()) return;
        // 过月成功：旧月本地拟诏会话态不得带入新月；盖玺 activeModal 须卸掉。
        resetLocalEdictState?.();
        onMonthAdvanced?.();
      },
      // 陈旧回执连账本都不取：翻当前局盘面同样是当前局副作用。
      loadState: () => (owned() ? loadState() : Promise.resolve(null)),
      reload: () => { if (owned()) window.location.reload(); },
    };
  }, [loadState]);

  // #1888：重试亦是一次回执（玩家在旧局面上点的重试，回执可能迟到）——同经 claimReceipt。
  const retryAdvanceRefresh = async () => {
    const receipt = claimReceipt();
    try {
      const next = await receipt.loadState();
      if (!next) return;
      receipt.setAdvanceRefreshFailed(false);
      receipt.setError("");
      if (!settlementGazetteReading) receipt.setOverlayHold(false);
    } catch (err) {
      console.warn("[settlement] post-advance refresh retry failed", err);
      receipt.setError(err instanceof Error ? err.message : String(err));
    }
  };

  const dismissSettlementGazette = React.useCallback(() => {
    setSettlementGazetteReading(null);
    if (!advanceRefreshFailed) setPostAdvanceOverlayHold(false);
  }, [advanceRefreshFailed]);

  /**
   * #1852：月份已推进 → 刷账本 + 本面开阅读态（不 reload）。
   *
   * #1888：归属由 `receipt` 在请求发起时封存；此处不再自行比对代次。
   * 推进代次的接缝仍是既有 clearSettlementHudError（退局／再入局），不另造状态机。
   */
  const openGazetteAfterAdvance = async (
    receipt: SettlementReceipt,
    payload: Record<string, unknown> | null | undefined,
  ) => {
    const data = payload || {};
    // 新月盘面：立刻离开同会话核账面，避免 busy 残留把拟诏等关掉。
    receipt.setBusy("");
    // 先挡住过月自动弹层，再 loadState 翻 turn——否则 closed/密令/结局会抢在本面邸报之前。
    receipt.setOverlayHold(true);
    receipt.advanceMonthLocals();
    // 先保存已收到的邸报：随后刷新失败也不能丢掉当次阅读。
    const embedded = data.state as GameState | undefined;
    let next: GameState | null = null;
    try {
      next = await receipt.loadState();
    } catch (err) {
      console.warn("[settlement] post-advance refresh failed", err);
      receipt.setAdvanceRefreshFailed(true);
      receipt.setError(err instanceof Error ? err.message : String(err));
    }
    if (!next) receipt.setAdvanceRefreshFailed(true);
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
      receipt.setGazetteReading({
        report,
        attendantMessage: attendantMessage || undefined,
        periodLabel: periodLabel || undefined,
      });
    } else {
      receipt.setGazetteReading(null);
      receipt.setOverlayHold(false);
    }
  };

  const issueDecree = async () => {
    // #1888：发起即封存会话代次，回执据此判归属（见 claimReceipt）。
    const receipt = claimReceipt();
    beginSettlementWait();
    receipt.setError("");
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
        receipt.setCheatDirective("");
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
          receipt.reload();
          return;
        }
        // #1808 B 同类：phase-1 呈现先响亮落地；其后 loadState / pending 消费链 reject 不得吞掉已写告警。
        // #1700 / #1418 r2：loadState 使 settling 续跑面可挂上（best-effort）。
        // main #1442：pending_action_failures 落库面优先。欠账耗尽走失败单源（#1353 fold-in），无补写 CTA。
        const errMsg = typeof outcome.data === "string" ? outcome.data : (errData.message || "颁诏失败。");
        receipt.surfaceFailure(errMsg);
        try {
          await receipt.loadState();
        } catch (refreshErr) {
          // 刷新失败不抵消已落地的 phase-1 呈现；次级真因仍落痕（ADR 0005）。
          console.warn("[settlement] phase-1 failure refresh failed", refreshErr);
        }
        receipt.setBusy("");
        return;
      }
      if (outcome.kind === "decisions") {
        // 出重大抉择：暂停弹窗逐个亲裁，裁完调 submitDecisions 续跑结算。
        // #1234：同会话停窗经既有状态口刷新 React 态——yearMonthLabel / 顶栏四键读到 settlement_display 与快照叠影。
        // 此处不 reload；仅 409 且服务端已推进时以整页刷新恢复陈旧令牌。不自判核账态，不平行第二展示通道。
        receipt.setDecisionFailures(outcome.data?.pending_action_failures || []);
        const route = routeIssueDecisions(outcome.data.decisions || []);
        if (route.pendingDecisions !== null) receipt.setPendingDecisions(route.pendingDecisions);
        if (route.error !== null) receipt.setPausedDecisionError(route.error);
        await receipt.loadState();
        receipt.setBusy("");
        return;
      }
      if (outcome.data?.advanced === false) {
        // The month chain can stop at rescript/gazette without advancing.
        // Refresh its durable settling projection, not the whole page as if a new month began.
        await receipt.loadState();
        receipt.setBusy("");
        return;
      }
      // #1852：写成即推进——loadState + 本面阅读态；不整页 reload。
      await openGazetteAfterAdvance(receipt, outcome.data || {});
      receipt.setBusy("");
      return;
    } catch (err) {
      // #1808 B 同类：先响亮；#1700 loadState 刷新权威相位为 best-effort。
      receipt.surfaceFailure(err instanceof Error ? err.message : String(err));
      try {
        await receipt.loadState();
      } catch (refreshErr) {
        // 刷新失败不抵消已落地的 phase-1 呈现；次级真因仍落痕（ADR 0005）。
        console.warn("[settlement] phase-1 failure refresh failed", refreshErr);
      }
      receipt.setBusy("");
    }
  };

  // 皇帝亲裁完所有决策点 / phase2 续跑：走 resolve_decisions/stream。
  // choices 按决策点 idx 顺序；all-decided 续跑可传 []——服务端幂等保留已存 choice。
  // dossier 批红 choice 须带回 dossier_id / dossier_decision（#1490）；勿收窄剥字段。
  // #1620：成功前不清 pendingDecisions——失败时 DecisionModal 不卸载，已选批语自然保留。
  const submitDecisions = async (choices: DecisionChoice[]) => {
    // #1888：发起即封存会话代次，回执据此判归属。
    const receipt = claimReceipt();
    setBusy("月末结算");
    receipt.setError("");
    receipt.setPausedDecisionError("");
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
        await receipt.loadState();
        const msg = typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。");
        receipt.setPausedDecisionError(msg);
        receipt.setError(msg);
        receipt.setBusy("");
        return;
      }
      // 成功：清空案头态；写成即推进则本面开邸报。
      receipt.setPendingDecisions([]);
      receipt.setDecisionFailures([]);
      receipt.setPausedDecisionError("");
      if (outcome.data?.advanced === false) {
        await receipt.loadState();
        receipt.setBusy("");
        return;
      }
      await openGazetteAfterAdvance(receipt, outcome.data || {});
      receipt.setBusy("");
      return;
    } catch (err) {
      await receipt.loadState();
      const msg = err instanceof Error ? err.message : String(err);
      receipt.setPausedDecisionError(msg);
      receipt.setError(msg);
      receipt.setBusy("");
    }
  };

  /** #1418 r2：all-decided 续跑——重发 resolve_decisions/stream（空载荷；服务端用已存 choice）。 */
  const resumePhase2 = async () => submitDecisions([]);

  // #1560：failed-only 拟诏台确认后退朝；复用既有 /api/decree/advance_without_edict 接缝。
  // 真空仍禁用；draft/pending 走 issueDecree，不经此路。
  // #1796：与盖玺同 busy 标——同会话立即收拟诏台 + 切核账期面。
  const advanceWithoutEdict = async () => {
    // #1888：发起即封存会话代次，回执据此判归属。
    const receipt = claimReceipt();
    beginSettlementWait(true);
    receipt.setError("");
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
      // 不盲 reload——批红面经 loadState 状态口投影；仅 409 且服务端已推进时整页刷新。
      if (data.awaiting_decision) {
        receipt.setDecisionFailures(data.pending_action_failures || []);
        const route = routeIssueDecisions(data.decisions || []);
        if (route.pendingDecisions !== null) receipt.setPendingDecisions(route.pendingDecisions);
        if (route.error !== null) receipt.setPausedDecisionError(route.error);
        await receipt.loadState();
        return;
      }
      if (data.advanced === false) {
        await receipt.loadState();
        return;
      }
      // #1852：退朝写成即推进——本面阅读态，不 reload。
      await openGazetteAfterAdvance(receipt, {
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
        receipt.reload();
        return;
      }
      // #1808 B：catch 内 await 链 reject 不得全静默——phase-1 呈现先落地，再 best-effort 消费 pending。
      const failures = detail?.pending_action_failures;
      const hasPending = Array.isArray(failures) && failures.length > 0;
      receipt.surfaceFailure(
        hasPending
          ? (detail?.message || "退朝失败。")
          : (err instanceof Error ? err.message : String(err)),
      );
    } finally {
      receipt.setBusy("");
    }
  };

  // #1888：失败重拉亦是一次回执，同经 claimReceipt；否则退局后到达的旧局重拉
  // 会把上一局的批红/续跑态与告警写进新局。
  const retryPendingDecisions = async () => {
    const receipt = claimReceipt();
    setBusy("重新拉取批红");
    receipt.setPausedDecisionError("");
    try {
      const freshState = await receipt.loadState();
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
      if (route.pendingDecisions !== null) receipt.setPendingDecisions(route.pendingDecisions);
      if (route.error !== null) receipt.setPausedDecisionError(route.error);
    } catch (err) {
      receipt.setPausedDecisionError(`重新拉取待批决策失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy("");
    }
  };

  return {
    settlementGazetteReading,
    advanceRefreshFailed,
    retryAdvanceRefresh,
    dismissSettlementGazette,
    /** #1852：本面邸报阅读中或过月刚翻月尚未落阅读态时，挡住自动弹层。 */
    suppressPostAdvanceOverlays: Boolean(settlementGazetteReading) || postAdvanceOverlayHold,
    pendingDecisions,
    decisionFailures,
    pausedDecisionError,
    settlementHudError,
    failedEntryWasRetreat,
    clearSettlementHudError,
    issueDecree,
    advanceWithoutEdict,
    submitDecisions,
    resumePhase2,
    retryPendingDecisions,
  };
}
