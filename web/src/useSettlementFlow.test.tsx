import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { yearMonthLabel } from "./settlementPresentation";
import type { GameState, PendingDecision } from "./types";
import { useSettlementFlow } from "./useSettlementFlow";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const validDecision: PendingDecision = {
  idx: 0,
  title: "关宁军饷",
  context: "辽东急报：军中已三月未饷。",
  options: [{ label: "拨帑速发", hint: "先解燃眉之急。" }],
};

/** 点击前盘面：无核账标；四键为月初值。 */
const preClickState = {
  turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
  metrics: { 国库: 1781, 内库: 320, 民心: 55, 皇威: 40 },
  budget: {
    国库: { balance: 1781 },
    内库: { balance: 320 },
  },
} as unknown as GameState;

/** 状态口在 awaiting 停窗下发：settlement_display + 快照叠影四键（与活值可不同，证明确读投影）。 */
const awaitingState = {
  turn: { year: 1627, period: 10, turn: 5, phase: "awaiting_decision", settlement_display: true },
  metrics: { 国库: 1781, 内库: 320, 民心: 55, 皇威: 40 },
  budget: {
    国库: { balance: 1781 },
    内库: { balance: 320 },
  },
  pending_decisions: [validDecision],
} as unknown as GameState;

function sseDecisionsResponse(): Response {
  const body = [
    "event: decisions",
    `data: ${JSON.stringify({ decisions: [validDecision] })}`,
    "",
    "",
  ].join("\n");
  return {
    ok: true,
    body: {
      getReader() {
        let done = false;
        return {
          read: async () => {
            if (done) return { value: undefined, done: true };
            done = true;
            return { value: new TextEncoder().encode(body), done: false };
          },
        };
      },
    },
  } as unknown as Response;
}

type HookApi = ReturnType<typeof useSettlementFlow>;

function mountHarness(opts: {
  loadState: () => Promise<GameState | null>;
  initial?: GameState;
}) {
  const hookRef = { current: null as HookApi | null };
  const stateRef = { current: opts.initial ?? preClickState };

  function Harness() {
    const [state, setState] = React.useState<GameState | null>(stateRef.current);
    const [busy, setBusy] = React.useState("");
    const [error, setError] = React.useState("");
    const [cheatDirective, setCheatDirective] = React.useState("");

    const loadState = React.useCallback(async () => {
      const next = await opts.loadState();
      if (next) {
        stateRef.current = next;
        setState(next);
      }
      return next;
    }, []);

    hookRef.current = useSettlementFlow({
      setBusy,
      setError,
      cheatDirective,
      setCheatDirective,
      loadState,
      surfacePendingActionFailures: async () => false,
      state,
    });

    const turn = state?.turn;
    const metrics = state?.metrics || {};
    const budget = state?.budget || {};
    return (
      <div>
        <div data-testid="busy">{busy}</div>
        <div data-testid="error">{error}</div>
        <div data-testid="year-month">{turn ? yearMonthLabel(turn) : ""}</div>
        <div data-testid="treasury">{String((budget as any)["国库"]?.balance ?? metrics["国库"] ?? "")}</div>
        <div data-testid="inner">{String((budget as any)["内库"]?.balance ?? metrics["内库"] ?? "")}</div>
        <div data-testid="minxin">{String(metrics["民心"] ?? "")}</div>
        <div data-testid="huangwei">{String(metrics["皇威"] ?? "")}</div>
        <div data-testid="pending-count">{String(hookRef.current.pendingDecisions.length)}</div>
        <div data-testid="settlement-display">{String(Boolean(turn?.settlement_display))}</div>
      </div>
    );
  }

  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(<Harness />);
  });
  return {
    host,
    hookRef,
    cleanup: () =>
      act(() => {
        root.unmount();
        host.remove();
      }),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("#1351 useSettlementFlow — advanceWithoutEdict 令牌与 409 幂等", () => {
  it("POST 携 state.turn 为 expected_turn", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ state: preClickState, pending_action_failures: [] }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/api/decree/advance_without_edict");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ expected_turn: 5 });
    expect(reload).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it("409 且服务端 turn>expected 时按已推进 reload，不设 error 条", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({
        detail: { message: "月份已变更（当前第 6 月），与退朝令牌不符，请刷新后再试。", turn: 6 },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(reload).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-testid=error]")?.textContent).toBe("");
    cleanup();
  });

  it("409 且服务端 turn<=expected 时仍报错条、不 reload", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({
        detail: { message: "月末结算进行中，请待结算完成后再操作。" },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.advanceWithoutEdict();
    });

    expect(reload).not.toHaveBeenCalled();
    expect(host.querySelector("[data-testid=error]")?.textContent || "").not.toBe("");
    cleanup();
  });
});

function sseErrorResponse(payload: Record<string, unknown>): Response {
  const body = [
    "event: error",
    `data: ${JSON.stringify(payload)}`,
    "",
    "",
  ].join("\n");
  return {
    ok: true,
    body: {
      getReader() {
        let done = false;
        return {
          read: async () => {
            if (done) return { value: undefined, done: true };
            done = true;
            return { value: new TextEncoder().encode(body), done: false };
          },
        };
      },
    },
  } as unknown as Response;
}

describe("#1277 useSettlementFlow — issueDecree 令牌与 409 幂等", () => {
  it("POST 携 state.turn 为 expected_turn；409 且 serverTurn>expected → reload 不设 error", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || "{}"));
      // 首发成功路径不在本测；直接回 409 陈旧令牌以钉 reload 惯用法。
      expect(body.expected_turn).toBe(5);
      expect(body).toMatchObject({ cheat: "" });
      return sseErrorResponse({
        message: "月份已变更（当前第 6 月），与颁诏令牌不符，请刷新后再试。",
        turn: 6,
        status_code: 409,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    const { host, hookRef, cleanup } = mountHarness({
      loadState: async () => preClickState,
      initial: preClickState,
    });

    await act(async () => {
      await hookRef.current!.issueDecree();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/api/decree/issue/stream");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-testid=error]")?.textContent).toBe("");
    cleanup();
  });
});

describe("#1234 useSettlementFlow — 同会话 awaiting 停窗消费状态口", () => {
  it("decisions 分支 await loadState：·待批出现（#1323）+ 四键为月初值，且不 reload", async () => {
    const loadState = vi.fn(async () => awaitingState);
    const reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload },
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/api/decree/issue/stream")) return sseDecisionsResponse();
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    const { host, hookRef, cleanup } = mountHarness({ loadState });

    // 点击前：无核账标
    expect(host.querySelector("[data-testid=year-month]")?.textContent).toBe("1627 年 10 月");
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("false");

    await act(async () => {
      await hookRef.current!.issueDecree();
    });

    expect(loadState).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();

    // 同会话不 reload：状态口投影驱动 HUD
    expect(host.querySelector("[data-testid=year-month]")?.textContent).toBe("1627 年 10 月 · 待批");
    expect(host.querySelector("[data-testid=settlement-display]")?.textContent).toBe("true");
    expect(host.querySelector("[data-testid=treasury]")?.textContent).toBe("1781");
    expect(host.querySelector("[data-testid=inner]")?.textContent).toBe("320");
    expect(host.querySelector("[data-testid=minxin]")?.textContent).toBe("55");
    expect(host.querySelector("[data-testid=huangwei]")?.textContent).toBe("40");
    expect(host.querySelector("[data-testid=pending-count]")?.textContent).toBe("1");
    expect(host.querySelector("[data-testid=busy]")?.textContent).toBe("");

    cleanup();
  });
});
