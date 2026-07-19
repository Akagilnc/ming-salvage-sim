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

    // 旧「换回合密令刷新」（gen1，state+密令都门控挂起）——代表旧 turn fetch
    let pOld!: Promise<GameState | null>;
    const oldOrdersSeen: string[] = [];
    act(() => {
      pOld = hookRef.current!.refresh({
        secretOrders: true,
        onSecretOrders: (o) => oldOrdersSeen.push((o[0] as unknown as { tag: string }).tag),
      });
    });
    await tick();
    // 更新的 done/撤回刷新（gen2，即时）→ 应用 undo，返回非 null（已应用）
    let undoResult: GameState | null = null;
    await act(async () => { undoResult = await hookRef.current!.refresh({ secretOrders: true }); });
    expect(marker(undoResult!)).toBe("undo");   // 新刷新已应用、返回真 state
    expect(states).toEqual(["undo"]);
    expect(orders).toEqual(["undo"]);

    releaseOld();  // 旧 turn fetch 的 old-done state/密令迟到——代次已推进，须弃写
    let staleReturn: GameState | null = null;
    await act(async () => { staleReturn = await pOld; });
    expect(staleReturn).toBeNull();              // 陈旧刷新返回 null（消费者据此拒收，不用陈旧 cargo）
    expect(oldOrdersSeen).toEqual([]);           // onSecretOrders 也按代次门控，旧密令未回调
    expect(states).toEqual(["undo"]);            // 旧 turn fetch 未覆盖更新的 done/undo 结果
    expect(orders).toEqual(["undo"]);
  });

  it("beginMutation 推进代次：作废在飞的旧刷新（返 null、不落陈旧 state），直接变更结果不被覆盖", async () => {
    const states: string[] = [];
    const orders: string[] = [];
    const hookRef = mount(states, orders);
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/game/state")) { await gate; return jsonResp({ marker: "old", map_nodes: [] }); }
      return jsonResp({});
    }));

    let pOld!: Promise<GameState | null>;
    act(() => { pOld = hookRef.current!.refresh(); });   // 旧刷新在飞
    await tick();
    act(() => { hookRef.current!.beginMutation(); });     // 直接变更（草案增/删等）应用响应前推进代次
    release();
    let ret: GameState | null = null;
    await act(async () => { ret = await pOld; });
    expect(ret).toBeNull();        // 旧刷新被作废、返 null
    expect(states).toEqual([]);    // 未落陈旧 state（本变更结果不被覆盖）
  });

  it("延迟呈现纳入代次归属：onSecretOrders 的 isLatest 在 beginMutation（撤回）后转 false", async () => {
    const states: string[] = [];
    const orders: string[] = [];
    const hookRef = mount(states, orders);
    let captured: (() => boolean) | null = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/secret_orders")) return jsonResp({ orders: [{ tag: "x" }] });
      return jsonResp({ marker: "s", map_nodes: [] });
    }));

    await act(async () => {
      await hookRef.current!.refresh({ secretOrders: true, onSecretOrders: (_o, isLatest) => { captured = isLatest; } });
    });
    expect(captured!()).toBe(true);   // 呈现时仍最新 → 400ms 定时器会弹窗
    act(() => { hookRef.current!.beginMutation(); });  // 撤回移除全部 active 单：推进代次
    expect(captured!()).toBe(false);  // 陈旧定时器 fire 时 isLatest=false → no-op，不弹已作废窗
  });
});
