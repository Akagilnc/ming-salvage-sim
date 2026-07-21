import React from "react";
import { api } from "./api";
import type { GameState, SecretOrder } from "./types";

/**
 * #499 持久投影（游戏 state + 密令列表）唯一 latest-wins 协调器：App 对该投影的**所有**重取型
 * 刷新（done / 撤回 / 重试 / 结算 / load）都经 `refresh`，共享一个代次。任一新刷新推进代次，在飞的
 * 旧响应据此弃写——杜绝「旧 done 或密令响应在撤回后迟到、把已撤回的 UI 又还原」。
 *
 * applyState / applySecretOrders 须为稳定回调（setState 等本就稳定）；协调器只负责取数 + 代次门控。
 */
export function useDurableProjection(
  applyState: (data: GameState) => void,
  applySecretOrders: (orders: SecretOrder[]) => void,
) {
  const genRef = React.useRef(0);

  /**
   * 推进代次 → 取 state（可选并取密令列表）→ 仅当仍是最新代次才落 UI。
   * - 陈旧代次（更新的刷新已发生）：**返回 null**——消费者据此拒收陈旧 cargo，绝不用陈旧 state。
   * - `onSecretOrders`：密令就绪且仍最新时回调（如换回合标记已呈现，同代次门控）。
   * - `autoOpen`：**延迟呈现由本协调器归属**：密令就绪且 when(orders) 为真则起 afterMs 定时器，
   *   fire 时仍是最新代次才 open()——更新的撤回/刷新推进代次后陈旧定时器 no-op（不弹已作废窗）。
   *   计时器交本协调器持有，避免 App 端裸 setTimeout 无归属。
   */
  const refresh = React.useCallback(
    async (opts?: {
      secretOrders?: boolean;
      onSecretOrders?: (orders: SecretOrder[]) => void;
      autoOpen?: { afterMs: number; when: (orders: SecretOrder[]) => boolean; open: () => void };
    }): Promise<GameState | null> => {
      const gen = ++genRef.current;
      const isLatest = () => genRef.current === gen;
      if (opts?.secretOrders) {
        api<{ orders: SecretOrder[] }>("/api/secret_orders")
          .then(({ orders }) => {
            if (!isLatest()) return;
            applySecretOrders(orders);
            opts.onSecretOrders?.(orders);
            const auto = opts.autoOpen;
            if (auto && auto.when(orders)) {
              setTimeout(() => { if (isLatest()) auto.open(); }, auto.afterMs);
            }
          })
          .catch(() => {});
      }
      const data = await api<GameState>("/api/game/state");
      if (!isLatest()) return null;  // 陈旧代次 → 拒收
      applyState(data);
      return data;
    },
    [applyState, applySecretOrders],
  );

  // 直接改持久投影的变更（草案增/改/删/准/驳、撤回、重试）在**应用其响应前**推进代次，
  // 作废任何在飞的旧刷新——旧 done 刷新迟到 resolve 时代次已变、返 null 弃写，不覆盖本变更结果。
  const beginMutation = React.useCallback(() => {
    genRef.current += 1;
  }, []);

  return { refresh, beginMutation };
}
