import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GameHud } from "./gameHud";
import { SettlementLock } from "./settlementLock";
import { MinisterCardList, AppointmentDrawer } from "./drawers";
import {
  AWAITING_CLOSED_REASON,
  SETTLEMENT_CLOSED_REASON,
  WANG_AWAITING_SLIP,
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

function makeState(
  settlementDisplay: boolean,
  extra: Partial<GameState> = {},
  phase: string = "settling",
): GameState {
  return {
    turn: { year: 1627, period: 10, turn: 5, phase, settlement_display: settlementDisplay },
    metrics: { 民心: 50, 皇威: 40 },
    previous_summary: "上月邸报",
    issues: [{ id: 1, kind: "situation", title: "半程军饷议题", status: "open", progress: 10, fail_condition: "" } as never],
    legacies: [],
    closed_this_turn: [{
      id: 2, kind: "situation", title: "月初已结漕运", status: "resolved",
      bar_value: 0, bar_good_meaning: "妥", bar_bad_meaning: "",
      closed_turn: 4, stage_text: "", effect: {},
    } as never],
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
    ...extra,
  } as GameState;
}

function minister(name = "周延儒"): Minister {
  return {
    name, office: "首辅", office_type: "内阁", faction: "", style: "",
    status: "active", status_label: "在朝", summary: "辅臣", favorite: false, skills: [],
  };
}

describe("#1236 GameHud face gates eat settlement_display", () => {
  it("核账期：王承恩递话条出现；关闭组导航 aria-disabled；密令角标清零；半程局势藏、上月已结只读可达", () => {
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
    expect(host.textContent).not.toContain("· 待批");
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
    // 密令角标清零（核账期 secret_orders 关闭；勿被奏疏 issues badge 误伤）
    const secretCmd = Array.from(host.querySelectorAll("button.hud2-cmd")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("密令"),
    );
    expect(secretCmd?.querySelector(".hud2-cmd-badge")).toBeNull();
    // 奏疏 badge/sub 同源 situation：核账期 badge=0，勿报半程 N
    const memorialBtn = Array.from(host.querySelectorAll("button.hud2-cmd")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("奏疏"),
    );
    const memorialCap = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("奏疏"),
    );
    expect(memorialBtn?.querySelector(".hud2-cmd-badge")).toBeNull();
    expect(memorialCap?.textContent).toMatch(/0\s*件待览/);
    expect(memorialCap?.getAttribute("aria-label")).toMatch(/0\s*件待览/);
    expect(memorialCap?.textContent).not.toContain("半程");
    // situation 关闭 / closed_issues 只读：半程议题不渲染，上月已结仍在
    expect(host.textContent).not.toContain("半程军饷议题");
    expect(host.querySelector(".situation-list")).toBeNull();
    expect(host.querySelector(".situation-closed-list")).not.toBeNull();
    expect(host.textContent).toContain("月初已结漕运");
    expect(host.querySelector(".hud2-issue-quad")?.getAttribute("data-settlement-face")).toBe("readonly");
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
    // 密令木牌角标（奏疏/拟诏也可能有 badge，勿用全局首枚）
    const secretCmd = Array.from(host.querySelectorAll("button.hud2-cmd")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("密令"),
    );
    expect(secretCmd?.querySelector(".hud2-cmd-badge")?.textContent).toBe("3");
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

  it("#1323 awaiting_decision：递话/角标文案为有本待批；锁面机制仍关", () => {
    const attempts: string[] = [];
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={makeState(true, {}, "awaiting_decision")}
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
    expect(host.querySelector("[data-testid=wang-settlement-slip]")?.textContent).toContain(WANG_AWAITING_SLIP);
    expect(host.textContent).toContain("· 待批");
    expect(host.textContent).not.toContain("· 核账");
    const regionBtn = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "省份列表")!;
    expect(regionBtn.getAttribute("aria-disabled")).toBe("true");
    act(() => { regionBtn.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(attempts).toEqual([AWAITING_CLOSED_REASON]);
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
          phase="settling"
        />,
      );
    });
    const card = host.querySelector("button.minister-card") as HTMLButtonElement;
    expect(card.disabled).toBe(true);
    expect(card.getAttribute("title")).toBe(SETTLEMENT_CLOSED_REASON);
    act(() => { card.click(); });
    expect(opened).toEqual([]);
    expect(host.textContent).toContain("周延儒"); // 名册仍在
  });

  it("#1323 awaiting：MinisterCardList title 吃 settlementClosedReason(phase)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ layout: "{}" }) } as Response)));
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
          onOpenChat={() => {}}
          chatEntryEnabled={false}
          phase="awaiting_decision"
        />,
      );
    });
    const card = host.querySelector("button.minister-card") as HTMLButtonElement;
    expect(card.disabled).toBe(true);
    expect(card.getAttribute("title")).toBe(AWAITING_CLOSED_REASON);
    expect(card.getAttribute("title")).not.toMatch(/核账/);
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
        phase="settling"
      />,
    );
    expect(host.textContent).toContain("温体仁");
    const row = host.querySelector("button.right-drawer-row-minister") as HTMLButtonElement;
    expect(row.disabled).toBe(true);
    expect(row.getAttribute("title")).toBe(SETTLEMENT_CLOSED_REASON);
    act(() => { row.click(); });
    expect(opened).toEqual([]);
  });

  it("#1323 awaiting：AppointmentDrawer title 吃 settlementClosedReason(phase)", () => {
    const host = mount(
      <AppointmentDrawer
        ministers={[minister("温体仁")]}
        open={true}
        onOpenChat={() => {}}
        onClose={() => {}}
        chatEntryEnabled={false}
        phase="awaiting_decision"
      />,
    );
    const row = host.querySelector("button.right-drawer-row-minister") as HTMLButtonElement;
    expect(row.disabled).toBe(true);
    expect(row.getAttribute("title")).toBe(AWAITING_CLOSED_REASON);
    expect(row.getAttribute("title")).not.toMatch(/核账/);
  });
});

describe("QA A-1 #1276/#1282/#1285 GameHud HUD 对齐", () => {
  function mountHud(opts: {
    state?: GameState;
    onOpenModal?: (modal: string) => void;
    navHandlers?: Record<string, () => void>;
    edictOpen?: boolean;
    onCloseEdict?: () => void;
  } = {}) {
    const opened: string[] = [];
    const navCalls: string[] = [];
    const closed: string[] = [];
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={opts.state ?? makeState(false, {
          issues: [
            { id: 1, kind: "situation", title: "户部亏空", status: "open", progress: 10, fail_condition: "" } as never,
            { id: 2, kind: "situation", title: "辽东索饷", status: "open", progress: 10, fail_condition: "" } as never,
            { id: 3, kind: "situation", title: "陕西流寇起", status: "open", progress: 10, fail_condition: "" } as never,
          ],
          events: [],
        })}
        mapNodes={[]}
        mapSelectedId=""
        onSelectMapNode={() => {}}
        activeDrawerKey=""
        navHandlers={opts.navHandlers ?? {
          court: () => navCalls.push("court"),
          harem: () => navCalls.push("harem"),
          army: () => navCalls.push("army"),
          region: () => navCalls.push("region"),
          building: () => navCalls.push("building"),
          economy: () => navCalls.push("economy"),
          appointment: () => navCalls.push("appointment"),
        }}
        secretOrderActiveCount={0}
        edictOpen={opts.edictOpen}
        onCloseEdict={() => {
          closed.push("edict");
          opts.onCloseEdict?.();
        }}
        onOpenModal={(modal) => {
          opened.push(modal);
          opts.onOpenModal?.(modal);
        }}
      />,
    );
    return { host, opened, navCalls, closed };
  }

  it("#1276 邸报木牌 caption/动作对齐 gazette，不再挂起居注", () => {
    const { host, opened } = mountHud();
    const dibao = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("邸报"),
    );
    expect(dibao).toBeTruthy();
    expect(dibao?.textContent).toContain("邸报");
    expect(dibao?.textContent).toContain("上月抄报");
    expect(dibao?.textContent).not.toContain("起居注");
    // 起居注不得再占命令木牌 caption
    const mislabeled = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      b.textContent?.includes("起居注"),
    );
    expect(mislabeled).toBeFalsy();
    act(() => { dibao?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(opened).toEqual(["report"]);
  });

  it("#1282 owner 先隐：礼木牌不渲染；政仍走朝堂；礼部槽位资源保留待立项", () => {
    const { host, navCalls } = mountHud();
    const zheng = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "朝堂·召见大臣");
    const li = Array.from(host.querySelectorAll("button")).find((b) => b.getAttribute("aria-label") === "礼部");
    expect(zheng).toBeTruthy();
    expect(li).toBeFalsy(); // 隐掉，不删 HUD_SLOTS.导航.礼部
    const navLabels = Array.from(host.querySelectorAll("button.hud2-nav")).map((b) => b.textContent?.trim());
    expect(navLabels).not.toContain("礼");
    expect(navLabels).toEqual(expect.arrayContaining(["政", "吏", "后"]));
    act(() => { zheng?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(navCalls).toEqual(["court"]);
  });

  it("#1285 奏疏 badge/副文接 issues；木牌 gatedModal face=memorials 打开 state 槽", () => {
    const { host, opened } = mountHud();
    const memorial = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").startsWith("奏疏"),
    );
    expect(memorial).toBeTruthy();
    expect(memorial?.textContent).toMatch(/3\s*件待览/);
    // badge 挂在木牌按钮上（events=[] 时仍应显示 issues 数；禁平行 badge 源）
    const badge = host.querySelector(".hud2-cmd-badge");
    expect(badge?.textContent).toBe("3");
    act(() => { memorial?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    // ModalName 仍用 state 槽承载奏疏面（main 以 memorials 面键门控）
    expect(opened).toEqual(["state"]);
  });

  it("#1277 拟诏木牌：0 草案写退朝过月；有草案同步盖玺颁诏过月", () => {
    // makeState 默认带 1 道草案；0 草案须显式清空
    const { host: host0, opened } = mountHud({
      state: makeState(false, { directives: [] }),
    });
    const edict0 = Array.from(host0.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").includes("拟诏"),
    );
    expect(edict0).toBeTruthy();
    expect(edict0?.textContent).toMatch(/拟诏·退朝过月/);
    expect(edict0?.textContent).not.toContain("结束回合");
    act(() => { edict0?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(opened).toEqual(["edict"]);

    // 有草案（makeState 默认）：木牌与拟诏台主钮同步为盖玺颁诏过月
    const { host: hostDraft } = mountHud();
    const edict1 = Array.from(hostDraft.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").includes("拟诏"),
    );
    expect(edict1?.textContent).toMatch(/拟诏·盖玺颁诏过月/);
    expect(edict1?.textContent).not.toMatch(/退朝过月/);
  });

  it("#1454 拟诏台开着：木牌名实降为收起，不再与主钮同文盖玺颁诏过月", () => {
    const { host } = mountHud({ edictOpen: true });
    const edict = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").includes("拟诏"),
    );
    expect(edict).toBeTruthy();
    expect(edict?.textContent).toMatch(/拟诏·收起/);
    expect(edict?.textContent).toMatch(/收起拟诏台/);
    // 名实：台开时不得再挂与 seal-btn-issue 同文的「盖玺颁诏过月」
    expect(edict?.textContent).not.toMatch(/盖玺颁诏过月/);
    expect(edict?.getAttribute("aria-label") || "").not.toMatch(/盖玺颁诏过月/);
    // 图钮 aria 同步
    const cmd = Array.from(host.querySelectorAll("button.hud2-cmd")).find((b) =>
      (b.getAttribute("aria-label") || "").includes("拟诏"),
    );
    expect(cmd?.getAttribute("aria-label") || "").toMatch(/拟诏·收起/);
    expect(cmd?.getAttribute("aria-label") || "").not.toMatch(/盖玺颁诏过月/);
  });

  it("#1454 拟诏台开着：木牌可点收起，不二次打开/不造第二条颁诏路径", () => {
    const { host, opened, closed } = mountHud({ edictOpen: true });
    const edict = Array.from(host.querySelectorAll(".hud2-cmd-caption")).find((b) =>
      (b.getAttribute("aria-label") || "").includes("拟诏"),
    );
    expect(edict).toBeTruthy();
    // 可点性：台开态木牌必须响应（不再被 desk-footer 挡成空等）
    act(() => { edict?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(closed).toEqual(["edict"]);
    // 勿再走 onOpenModal("edict")——那会变成无反馈/二次开台，不是收起
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
