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
   * - `onSecretOrders`：密令列表就绪且仍是最新代次时回调（供换回合自动弹窗等，同代次门控）。
   */
  const refresh = React.useCallback(
    async (opts?: {
      secretOrders?: boolean;
      onSecretOrders?: (orders: SecretOrder[]) => void;
    }): Promise<GameState | null> => {
      const gen = ++genRef.current;
      const isLatest = () => genRef.current === gen;
      if (opts?.secretOrders) {
        api<{ orders: SecretOrder[] }>("/api/secret_orders")
          .then(({ orders }) => {
            if (!isLatest()) return;
            applySecretOrders(orders);
            opts.onSecretOrders?.(orders);
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

  return { refresh };
}
