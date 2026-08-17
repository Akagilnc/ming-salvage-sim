import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GameHud } from "./gameHud";
import { SettlementLock } from "./settlementLock";
import { MinisterCardList, AppointmentDrawer } from "./drawers";
import {
  SETTLEMENT_CLOSED_REASON,
  WANG_SETTLEMENT_SLIP,
} from "../settlementPresentation";
import type { GameState, Minister } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom 无 SVG getBBox；GameHud 在 ready 时挂 GrandMap。
vi.mock("./map", () => ({
  GrandMap: () => <div data-testid="grand-map-stub" />,
  NodeIntel: () => null,
}));

const mounted: Array<{ root: Root; host: HTMLElement }> = [];

function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => { root.render(node); });
  mounted.push({ root, host });
  return host;
}

afterEach(() => {
  for (const { root, host } of mounted.splice(0)) {
    act(() => root.unmount());
    host.remove();
  }
  vi.unstubAllGlobals();
});

const acct = () => ({
  balance: 100, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0,
});

function makeState(settlementDisplay: boolean): GameState {
  return {
    turn: { year: 1627, period: 10, turn: 5, phase: "awaiting_decision", settlement_display: settlementDisplay },
    metrics: { 民心: 50, 皇威: 40 },
    previous_summary: "上月邸报",
    treasury: "",
    issues: [{ id: 1, kind: "situation", title: "边饷", status: "open", progress: 10, fail_condition: "" } as never],
    legacies: [],
    closed_this_turn: [],
    budget: { 国库: acct(), 内库: acct() },
    region_warning: "", army_warning: "", power_warning: "",
    powers: [],
    victory_status: { status: "", summary: "" },
    ending: null,
    events: [],
    regions: [],
    armies: [],
    map_nodes: [{ id: "liaodong", name: "辽东", kind: "region" } as never],
    ministers: [],
    consorts: [],
    directives: [{ id: 1 } as never],
    pending_count: 0,
    last_decree: "",
    last_report: "",
  } as GameState;
}

function minister(name = "周延儒"): Minister {
  return {
    name, office: "首辅", office_type: "内阁", faction: "", style: "",
    status: "active", status_label: "在朝", summary: "辅臣", favorite: false, skills: [],
  };
}

describe("#1236 GameHud face gates eat settlement_display", () => {
  it("核账期：王承恩递话条出现；关闭组导航 aria-disabled；密令角标清零；局势不渲染", () => {
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={makeState(true)}
        mapNodes={[]}
        mapSelectedId=""
        onSelectMapNode={() => {}}
        activeDrawerKey=""
        navHandlers={{
          court: () => {}, harem: () => {}, army: () => {}, region: () => {},
          building: () => {}, economy: () => {}, appointment: () => {},
        }}
        secretOrderActiveCount={3}
        onOpenModal={() => {}}
      />,
    );

    expect(host.querySelector("[data-testid=wang-settlement-slip]")?.textContent).toContain(WANG_SETTLEMENT_SLIP);
    expect(host.textContent).toContain("· 核账");
    // 关闭组：省/兵
    const regionBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "省份列表");
    const armyBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "军队列表");
    expect(regionBtn?.getAttribute("aria-disabled")).toBe("true");
    expect(armyBtn?.getAttribute("aria-disabled")).toBe("true");
    expect(regionBtn?.getAttribute("data-settlement-face")).toBe("closed");
    // 只读组：朝堂可达
    const courtBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "朝堂·召见大臣");
    expect(courtBtn?.getAttribute("aria-disabled")).toBe("false");
    expect(courtBtn?.getAttribute("data-settlement-face")).toBe("readonly");
    // 密令角标清零 + 局势不渲染
    expect(host.querySelector(".hud2-cmd-badge")).toBeNull();
    expect(host.querySelector(".situation-panel")).toBeNull();
  });

  it("非核账：递话条隐藏；关闭组恢复可达；角标恢复", () => {
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={makeState(false)}
        mapNodes={[]}
        mapSelectedId=""
        onSelectMapNode={() => {}}
        activeDrawerKey=""
        navHandlers={{
          court: () => {}, harem: () => {}, army: () => {}, region: () => {},
          building: () => {}, economy: () => {}, appointment: () => {},
        }}
        secretOrderActiveCount={3}
        onOpenModal={() => {}}
      />,
    );
    expect(host.querySelector("[data-testid=wang-settlement-slip]")).toBeNull();
    const regionBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "省份列表");
    expect(regionBtn?.getAttribute("aria-disabled")).toBe("false");
    expect(host.querySelector(".hud2-cmd-badge")?.textContent).toBe("3");
  });

  it("关闭组点击触发戏内理由回调", () => {
    const attempts: string[] = [];
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={makeState(true)}
        mapNodes={[]}
        mapSelectedId=""
        onSelectMapNode={() => {}}
        activeDrawerKey=""
        navHandlers={{
          court: () => {}, harem: () => {}, army: () => {}, region: () => {},
          building: () => {}, economy: () => {}, appointment: () => {},
        }}
        secretOrderActiveCount={0}
        onOpenModal={() => {}}
        onClosedFaceAttempt={(r) => attempts.push(r)}
      />,
    );
    const regionBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "省份列表")!;
    act(() => { regionBtn.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(attempts).toEqual([SETTLEMENT_CLOSED_REASON]);
  });
});

describe("#1236 roster chat entry stripped in settlement_display", () => {
  it("MinisterCardList disables onOpenChat when chatEntryEnabled=false", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ layout: "{}" }) } as Response)));
    const opened: string[] = [];
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    mounted.push({ root, host });
    await act(async () => {
      root.render(
        <MinisterCardList
          list={[minister()]}
          portraitPrefix="minister_"
          selectedMinister=""
          emptyNote=""
          onOpenChat={(m) => opened.push(m.name)}
          chatEntryEnabled={false}
        />,
      );
    });
    const card = host.querySelector("button.minister-card") as HTMLButtonElement;
    expect(card.disabled).toBe(true);
    act(() => { card.click(); });
    expect(opened).toEqual([]);
    expect(host.textContent).toContain("周延儒"); // 名册仍在
  });

  it("AppointmentDrawer 任免行核账期只读", () => {
    const opened: string[] = [];
    const host = mount(
      <AppointmentDrawer
        ministers={[minister("温体仁")]}
        open={true}
        onOpenChat={(m) => opened.push(m.name)}
        onClose={() => {}}
        chatEntryEnabled={false}
      />,
    );
    expect(host.textContent).toContain("温体仁");
    const row = host.querySelector("button.right-drawer-row-minister") as HTMLButtonElement;
    expect(row.disabled).toBe(true);
    act(() => { row.click(); });
    expect(opened).toEqual([]);
  });
});

describe("#1236 SettlementLock 装饰层自身契约", () => {
  it("装饰层无 aria-modal、role=status、pointer-events 不吞全屏", () => {
    const host = mount(
      <SettlementLock stage="数值推演结算" thinking="推敲中" narrative="" />,
    );
    const decor = host.querySelector("[data-testid=settlement-lock-decor]");
    expect(decor).not.toBeNull();
    expect(decor?.getAttribute("aria-modal")).toBeNull();
    expect(decor?.getAttribute("role")).toBe("status");
  });
});
