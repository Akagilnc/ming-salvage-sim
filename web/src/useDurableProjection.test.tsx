import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDurableProjection } from "./useDurableProjection";
import type { GameState, SecretOrder } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);
const marker = (data: GameState) => (data as unknown as { marker: string }).marker;

type HookApi = ReturnType<typeof useDurableProjection>;

function mount(states: string[], orders: string[]) {
  const hookRef = { current: null as HookApi | null };
  function Harness() {
    const applyState = React.useCallback((d: GameState) => { states.push(marker(d)); }, []);
    const applyOrders = React.useCallback((o: SecretOrder[]) => { orders.push((o[0] as unknown as { tag: string })?.tag); }, []);
    hookRef.current = useDurableProjection(applyState, applyOrders);
    return null;
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  act(() => createRoot(host).render(<Harness />));
  return hookRef;
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("持久刷新协调器（#499 App 消费的 useDurableProjection）", () => {
  it("撤回后旧 done 的 state / 密令响应迟到被弃写；新一代（撤回）胜出", async () => {
    const states: string[] = [];
    const orders: string[] = [];
    const hookRef = mount(states, orders);

    let releaseOld!: () => void;
    const oldGate = new Promise<void>((r) => { releaseOld = r; });
    let stateCall = 0;
    let ordersCall = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/game/state")) {
        stateCall += 1;
        if (stateCall === 1) { await oldGate; return jsonResp({ marker: "old-done", map_nodes: [] }); }  // 旧 done 的 state，迟到
        return jsonResp({ marker: "undo", map_nodes: [] });                                              // 撤回的 state，即时
      }
      if (u.pathname.endsWith("/secret_orders")) {
        ordersCall += 1;
        if (ordersCall === 1) { await oldGate; return jsonResp({ orders: [{ tag: "old-done" }] }); }
        return jsonResp({ orders: [{ tag: "undo" }] });
      }
      return jsonResp({});
    }));

    // 旧 done 刷新（gen1，state+密令都门控挂起）
    let pOld!: Promise<unknown>;
    act(() => { pOld = hookRef.current!.refresh({ secretOrders: true }); });
    await tick();
    // 撤回刷新（gen2，即时）→ 应用 undo
    await act(async () => { await hookRef.current!.refresh({ secretOrders: true }); });
    expect(states).toEqual(["undo"]);
    expect(orders).toEqual(["undo"]);

    releaseOld();  // 旧 done 的 old-done state/密令迟到——代次已推进，须弃写
    await act(async () => { await pOld; });
    expect(states).toEqual(["undo"]);            // old-done 未落（未还原撤回前 UI）
    expect(orders).toEqual(["undo"]);
  });
});
