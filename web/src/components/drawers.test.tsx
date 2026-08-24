import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmyDrawer, MinisterCardList, RegionDrawer } from "./drawers";
import type { Army, Minister, Region } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];

function renderArmyDrawer(army: Army) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <ArmyDrawer
        armies={[army]}
        open={true}
        selectedArmyId={army.id}
        onSelectArmy={() => {}}
        onClose={() => {}}
      />
    )
  );
  mountedRoots.push({ root, host });
  return host;
}

function makeRegion(overrides: Partial<Region> = {}): Region {
  return {
    id: "beizhili",
    name: "北直隶",
    kind: "两京",
    population: 7200000,
    public_support: 50,
    unrest: 20,
    natural_disaster: "无",
    human_disaster: "无",
    registered_land: 200,
    hidden_land: 0,
    tax_per_turn: 1,
    grain_security: 40,
    gentry_resistance: 30,
    military_pressure: 70,
    status: "平",
    controlled_by: "ming",
    ...overrides,
  };
}

function renderRegionDrawer(regions: Region[]) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() =>
    root.render(
      <RegionDrawer
        regions={regions}
        open={true}
        selectedRegionId={regions[0].id}
        onSelectRegion={() => {}}
        onClose={() => {}}
      />
    )
  );
  mountedRoots.push({ root, host });
  return host;
}

function minister(partial: Partial<Minister> & Pick<Minister, "name" | "office">): Minister {
  return {
    office_type: "",
    faction: "",
    style: "",
    status: "active",
    status_label: "在朝",
    summary: "",
    favorite: false,
    skills: [],
    ...partial,
  };
}

function cardPos(host: HTMLElement, name: string): { left: string; top: string } | null {
  const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
  const card = cards.find((el) => el.querySelector(".minister-name")?.textContent === name);
  if (!card) return null;
  return { left: card.style.left, top: card.style.top };
}

async function renderCourtList(
  list: Minister[],
  onOpenChat: (minister: Minister) => void = () => {}
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/api/court_layout")) {
        return { ok: true, json: async () => ({ layout: "{}" }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    })
  );
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(
      <MinisterCardList
        list={list}
        portraitPrefix="minister_"
        selectedMinister=""
        emptyNote="empty"
        onOpenChat={onOpenChat}
        courtMode={true}
      />
    );
  });
  // arrange() 在 loadCourtPos resolve 后 setPositions
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  mountedRoots.push({ root, host });
  return host;
}

afterEach(() => {
  for (const { root, host } of mountedRoots) {
    act(() => root.unmount());
    host.remove();
  }
  mountedRoots.length = 0;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("ArmyDrawer presentation", () => {
  it("shows backend arrears_text and mutiny_tier / morale_text directly", () => {
    const host = renderArmyDrawer({
      id: "denglai",
      name: "登莱兵与水师",
      station: "山东 / 登莱",
      theater: "山东",
      commander: "登莱巡抚",
      controller: "兵部",
      troop_type: "水师、火器兵、步卒",
      manpower: 26000,
      army_needed: 4,
      supply: 73,
      morale_text: "士气：尚稳",
      training: 73,
      equipment: 73,
      arrears_text: "欠饷约60万两，数月军饷",
      mobility: 73,
      mutiny_tier: "优秀",
      status: "可支援辽东和海运",
      owner_power: "ming",
    });

    expect(host.textContent).toContain("欠饷约60万两，数月军饷");
    expect(host.textContent).toContain("士气：尚稳");
    expect(host.textContent).toContain("优秀");
    expect(host.textContent).not.toContain("63万两");
    expect(host.textContent).not.toContain("忠诚73");
    // 旧 loyalty 五档词不得回潮
    expect(host.textContent).not.toContain("尚稳稳固");
    expect(host.textContent).not.toMatch(/危殆|浮动|不稳|稳固/);
  });

  // #321 AC1 链1 drawer：六档 mutiny_tier 直出，无二次 map / raw 轴
  it.each(["死忠", "优秀", "一般", "不满", "鼓噪", "哗变"] as const)(
    "renders mutiny_tier %s verbatim without loyalty remap",
    (tier) => {
      const host = renderArmyDrawer({
        id: "guanning",
        name: "关宁军",
        station: "辽东",
        theater: "辽东",
        commander: "祖大寿",
        controller: "祖大寿",
        troop_type: "边军",
        manpower: 10000,
        army_needed: 10,
        supply: 50,
        morale_text: "士气：不振",
        training: 50,
        equipment: 50,
        arrears_text: "无欠饷",
        mobility: 50,
        mutiny_tier: tier,
        status: "驻防",
        owner_power: "ming",
      });
      expect(host.textContent).toContain(tier);
      expect(host.textContent).toContain("士气：不振");
      expect(host.textContent).toContain("无欠饷");
      expect(host.textContent).not.toMatch(/危殆|浮动|不稳|稳固/);
      expect(host.textContent).not.toMatch(/\bmorale\b|\bloyalty\b|\barrears\b/);
    }
  );

  it("renders fractional payload arrears_text without raw 12.5", () => {
    const host = renderArmyDrawer({
      id: "denglai",
      name: "登莱兵与水师",
      station: "山东 / 登莱",
      theater: "山东",
      commander: "登莱巡抚",
      controller: "兵部",
      troop_type: "水师、火器兵、步卒",
      manpower: 26000,
      army_needed: 4,
      supply: 73,
      morale_text: "士气：尚稳",
      training: 73,
      equipment: 73,
      arrears_text: "欠饷约15万两，约两月军饷",
      mobility: 73,
      mutiny_tier: "优秀",
      status: "可支援辽东和海运",
      owner_power: "ming",
    });

    expect(host.textContent).toContain("欠饷约15万两");
    expect(host.textContent).not.toContain("12.5万两");
  });

  it("#1501 does not render static army status sentence", () => {
    const statusSentence = "宁锦守线尚可，欠饷严重，主动大举出击风险极高。";
    const host = renderArmyDrawer({
      id: "guanning",
      name: "关宁军 / 宁锦防线",
      station: "辽东 / 宁远锦州",
      theater: "辽东",
      commander: "祖大寿",
      controller: "祖大寿",
      troop_type: "边军",
      manpower: 72000,
      army_needed: 12,
      supply: 38,
      morale_text: "士气：不振",
      training: 68,
      equipment: 62,
      arrears_text: "欠饷约60万两，数月军饷",
      mobility: 48,
      mutiny_tier: "不满",
      status: statusSentence,
      owner_power: "ming",
    });

    // 即使 props 仍带旧 status，军牌 DOM 不得渲染之；欠饷栏仍在
    expect(host.textContent).not.toContain(statusSentence);
    expect(host.textContent).not.toContain("欠饷严重");
    expect(host.textContent).not.toMatch(/状态/);
    expect(host.textContent).toMatch(/欠饷/);
    // #321：欠饷只消费 arrears_text
    expect(host.textContent).toContain("欠饷约60万两，数月军饷");
    expect(host.querySelector(".right-drawer-detail")).toBeTruthy();
  });
});

describe("RegionDrawer #648 population (P7: LLM 长文，无 UI 模板)", () => {
  it("never renders fixed population strings (约N万口 / 不足一万口)", () => {
    const host = renderRegionDrawer([makeRegion({ population: 7200000 })]);
    expect(host.textContent).not.toContain("万口");
    expect(host.textContent).not.toContain("不足一万");
    expect(host.textContent).not.toContain("undefined");
  });
});

describe("朝堂空 layout 合法态（#1290/#1332）", () => {
  it("GET layout={} 时殿上仍按默认朝班落座（非 hidden）", async () => {
    // 契约：court_layout 是玩家拖拽覆盖；新局空 {} 合法，前端 courtSlots 生成默认位。
    // QA 只 curl 到空 API 不等于殿上无卡——本钉锁呈现层不把空当错。
    const host = await renderCourtList([
      minister({ name: "黄立极", office: "首辅,中极殿大学士" }),
      minister({ name: "毕自严", office: "户部尚书" }),
    ]);

    const huang = cardPos(host, "黄立极");
    const bi = cardPos(host, "毕自严");
    expect(huang).not.toBeNull();
    expect(bi).not.toBeNull();
    expect(huang!.left).not.toBe("");
    expect(huang!.top).not.toBe("");
    expect(bi!.left).not.toBe("");
    expect(bi!.top).not.toBe("");
    expect(`${huang!.left}|${huang!.top}`).not.toBe(`${bi!.left}|${bi!.top}`);

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    for (const c of cards) {
      expect(c.style.visibility).not.toBe("hidden");
      expect(c.style.position).toBe("absolute");
    }
  });

  it("layout fetch 未完成时也先默认落座，不堵首屏", async () => {
    let resolveLayout!: (v: { ok: boolean; json: () => Promise<{ layout: string }> }) => void;
    const pending = new Promise<{ ok: boolean; json: () => Promise<{ layout: string }> }>((r) => {
      resolveLayout = r;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/api/court_layout")) return pending as unknown as Response;
        return { ok: true, json: async () => ({}) } as Response;
      })
    );

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <MinisterCardList
          list={[
            minister({ name: "黄立极", office: "首辅,中极殿大学士" }),
            // 非固定槽官职：松手不吸回 FIXED_SLOTS，才能钉「完成拖拽后回包不回滚」
            minister({ name: "施凤来", office: "东阁大学士" }),
          ]}
          portraitPrefix="minister_"
          selectedMinister=""
          emptyNote="empty"
          onOpenChat={() => {}}
          courtMode={true}
        />
      );
    });
    // 同步 arrange({}) 后首帧即有坐标；不等待 fetch
    await act(async () => {
      await Promise.resolve();
    });

    const before = cardPos(host, "黄立极");
    expect(before).not.toBeNull();
    expect(before!.left).not.toBe("");

    // pending 期间真拖拽：jsdom 容器默认 0×0，须 stub 非零宽高，否则 onMove 除零失真
    const court = host.querySelector(".minister-list-court") as HTMLElement | null;
    expect(court).toBeTruthy();
    court!.getBoundingClientRect = () =>
      ({
        x: 0,
        y: 0,
        width: 1000,
        height: 1000,
        top: 0,
        right: 1000,
        bottom: 1000,
        left: 0,
        toJSON: () => ({}),
      }) as DOMRect;

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const shiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "施凤来");
    expect(shiCard).toBeTruthy();

    // 完整真实拖拽：mousedown → mousemove(>3px) → mouseup，之后再 resolve。
    // 契约是「完成拖拽后回包不回滚」，不得在持拖时 resolve 开例外路径。
    // 拖向左远槽（松手吸附 left:9≈37.7%/6.6%）；服务端回包瞄右近槽——两槽必须不同，mutation 才钉得死。
    await act(async () => {
      shiCard!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 500, clientY: 500 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 100, clientY: 100 }));
    });

    const dragged = cardPos(host, "施凤来");
    expect(dragged).not.toBeNull();
    expect(dragged!.left).not.toBe("");
    // 契约前提：拖后吸附位须异于将要回包的服务端 layout 吸附位（右近 86.2%/53.2%），否则钉不住回滚
    expect(`${dragged!.left}|${dragged!.top}`).not.toBe("86.2%|53.2%");

    await act(async () => {
      // 非空且刻意不同于拖后：右近槽锚点——若缺 savedPosRef 守卫会把本地拖拽滚回去
      resolveLayout({
        ok: true,
        json: async () => ({ layout: JSON.stringify({ 施凤来: { px: 0.9, py: 0.9 } }) }),
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    const after = cardPos(host, "施凤来");
    expect(after).not.toBeNull();
    expect(after!.left).not.toBe("");
    // 完成拖拽后 → 非空服务端 layout 回包不得回滚本地
    expect(after).toEqual(dragged);

    mountedRoots.push({ root, host });
  });

  it("#1463 慢载期间早拖：GET 回包合并脏键，不丢未拖大臣的服务端位，且 POST 不灌默认布局", async () => {
    // 复现：GET 未回时拖一张卡 → savedPosRef 被默认布局灌满 → 旧逻辑直接 return 丢弃服务端；
    // mouseup saveCourtPos 再把临时默认写穿服务器。修：脏键本地优先，其余合并服务端。
    let resolveLayout!: (v: { ok: boolean; json: () => Promise<{ layout: string }> }) => void;
    const pending = new Promise<{ ok: boolean; json: () => Promise<{ layout: string }> }>((r) => {
      resolveLayout = r;
    });
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/api/court_layout")) {
        if (init && String(init.method || "GET").toUpperCase() === "POST") {
          return { ok: true, json: async () => ({}) } as Response;
        }
        return pending as unknown as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <MinisterCardList
          list={[
            // 两名非固定槽：服务端位可观测，不与 FIXED_SLOTS 纠缠
            minister({ name: "施凤来", office: "东阁大学士" }),
            minister({ name: "张瑞图", office: "东阁大学士" }),
          ]}
          portraitPrefix="minister_"
          selectedMinister=""
          emptyNote="empty"
          onOpenChat={() => {}}
          courtMode={true}
        />
      );
    });
    await act(async () => { await Promise.resolve(); });

    const court = host.querySelector(".minister-list-court") as HTMLElement | null;
    expect(court).toBeTruthy();
    court!.getBoundingClientRect = () =>
      ({
        x: 0, y: 0, width: 1000, height: 1000,
        top: 0, right: 1000, bottom: 1000, left: 0, toJSON: () => ({}),
      }) as DOMRect;

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const shiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "施凤来");
    expect(shiCard).toBeTruthy();
    const zhangBeforeDrag = cardPos(host, "张瑞图");

    // 只拖施凤来；张瑞图保持默认位（尚未合并服务端）
    await act(async () => {
      shiCard!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 500, clientY: 500 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    const shiDragged = cardPos(host, "施凤来");
    expect(shiDragged).not.toBeNull();

    // 服务端：张瑞图在左远槽（默认第二人是右近 86.2%/53.2%，必须错开才钉得住合并）
    // 施凤来服务端旧位应被脏键盖住
    await act(async () => {
      resolveLayout({
        ok: true,
        json: async () => ({
          layout: JSON.stringify({
            施凤来: { px: 0.9, py: 0.9 },
            张瑞图: { px: 0.377, py: 0.066 },
          }),
        }),
      });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const shiAfter = cardPos(host, "施凤来");
    const zhangAfter = cardPos(host, "张瑞图");
    // 脏键：本地拖位保留
    expect(shiAfter).toEqual(shiDragged);
    // 未拖大臣：吃服务端左远槽，不得停在早拖前的临时默认（右近）
    expect(parseFloat(zhangAfter!.left)).toBeCloseTo(37.7, 5);
    expect(parseFloat(zhangAfter!.top)).toBeCloseTo(6.6, 5);
    expect(zhangBeforeDrag).toEqual({ left: "86.2%", top: "53.2%" });
    expect(zhangAfter).not.toEqual(zhangBeforeDrag);

    // POST 载荷须含合并结果：张瑞图服务端位 + 施凤来本地拖位；不得只剩默认布局
    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/api/court_layout") && c[1] && String((c[1] as RequestInit).method || "").toUpperCase() === "POST",
    );
    expect(posts.length).toBeGreaterThan(0);
    const lastPost = posts[posts.length - 1];
    const body = JSON.parse(String((lastPost[1] as RequestInit).body));
    const saved = JSON.parse(body.layout) as Record<string, { px: number; py: number }>;
    expect(saved["张瑞图"].px).toBeCloseTo(0.377, 5);
    expect(saved["张瑞图"].py).toBeCloseTo(0.066, 5);
    expect(saved["施凤来"]).toBeTruthy();
    expect(saved["施凤来"]).not.toEqual({ px: 0.9, py: 0.9 });

    mountedRoots.push({ root, host });
  });

  it("#1463 早拖后、GET 回前 list 变化：加载不被取消，合并后 POST 一次",
    async () => {
    // 复现：GET 挂起 → 早拖置 dirty/pending → listKey 变化 cleanup 取消唯一 GET
    // → 替换 effect 见 saved 非空且未 ready 只 arrange 不重载 → ready 永假、无合并无 POST。
    // 契约四件：未拖键取服务端、拖键取本地、合并完成前无 POST、完成后 POST 一次且载荷完整。
    let resolveLayout!: (v: { ok: boolean; json: () => Promise<{ layout: string }> }) => void;
    const pending = new Promise<{ ok: boolean; json: () => Promise<{ layout: string }> }>((r) => {
      resolveLayout = r;
    });
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/api/court_layout")) {
        if (init && String(init.method || "GET").toUpperCase() === "POST") {
          return { ok: true, json: async () => ({}) } as Response;
        }
        return pending as unknown as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const listA = [
      minister({ name: "施凤来", office: "东阁大学士" }),
      minister({ name: "张瑞图", office: "东阁大学士" }),
    ];
    // listKey 变化：第三人入列，触发重排 effect cleanup
    const listB = [
      ...listA,
      minister({ name: "李国樑", office: "东阁大学士" }),
    ];

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <MinisterCardList
          list={listA}
          portraitPrefix="minister_"
          selectedMinister=""
          emptyNote="empty"
          onOpenChat={() => {}}
          courtMode={true}
        />
      );
    });
    await act(async () => { await Promise.resolve(); });

    const court = host.querySelector(".minister-list-court") as HTMLElement | null;
    expect(court).toBeTruthy();
    court!.getBoundingClientRect = () =>
      ({
        x: 0, y: 0, width: 1000, height: 1000,
        top: 0, right: 1000, bottom: 1000, left: 0, toJSON: () => ({}),
      }) as DOMRect;

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const shiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "施凤来");
    expect(shiCard).toBeTruthy();

    // 早拖施凤来并松手（pending save）
    await act(async () => {
      shiCard!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 500, clientY: 500 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    const shiDragged = cardPos(host, "施凤来");
    expect(shiDragged).not.toBeNull();

    // 合并完成前不得 POST
    const postsBefore = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/api/court_layout") && c[1] && String((c[1] as RequestInit).method || "").toUpperCase() === "POST",
    );
    expect(postsBefore.length).toBe(0);

    // GET 仍挂起时 list 变化（重排生命周期不得取消加载）
    await act(async () => {
      root.render(
        <MinisterCardList
          list={listB}
          portraitPrefix="minister_"
          selectedMinister=""
          emptyNote="empty"
          onOpenChat={() => {}}
          courtMode={true}
        />
      );
    });
    await act(async () => { await Promise.resolve(); });

    // 仍无 POST
    const postsMid = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/api/court_layout") && c[1] && String((c[1] as RequestInit).method || "").toUpperCase() === "POST",
    );
    expect(postsMid.length).toBe(0);

    // 回包：张瑞图服务端左远槽；施凤来服务端旧位应被脏键盖住
    await act(async () => {
      resolveLayout({
        ok: true,
        json: async () => ({
          layout: JSON.stringify({
            施凤来: { px: 0.9, py: 0.9 },
            张瑞图: { px: 0.377, py: 0.066 },
          }),
        }),
      });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const shiAfter = cardPos(host, "施凤来");
    const zhangAfter = cardPos(host, "张瑞图");
    // 拖键取本地
    expect(shiAfter).toEqual(shiDragged);
    // 未拖键取服务端
    expect(parseFloat(zhangAfter!.left)).toBeCloseTo(37.7, 5);
    expect(parseFloat(zhangAfter!.top)).toBeCloseTo(6.6, 5);

    // 完成后 POST 一次且载荷完整
    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).includes("/api/court_layout") && c[1] && String((c[1] as RequestInit).method || "").toUpperCase() === "POST",
    );
    expect(posts.length).toBe(1);
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    const saved = JSON.parse(body.layout) as Record<string, { px: number; py: number }>;
    expect(saved["张瑞图"].px).toBeCloseTo(0.377, 5);
    expect(saved["张瑞图"].py).toBeCloseTo(0.066, 5);
    expect(saved["施凤来"]).toBeTruthy();
    expect(saved["施凤来"]).not.toEqual({ px: 0.9, py: 0.9 });

    mountedRoots.push({ root, host });
  });
});

describe("朝堂同衔分座（#1196 呈现层去冲突）", () => {
  it("同 role 双人大臣 arrange 后坐标不重合", async () => {
    // 来宗道/温体仁同「礼部尚书」开局叠座复现：次名起应降级自由槽
    const host = await renderCourtList([
      minister({ name: "来宗道", office: "礼部尚书,东阁大学士" }),
      minister({ name: "温体仁", office: "礼部尚书" }),
    ]);

    const a = cardPos(host, "来宗道");
    const b = cardPos(host, "温体仁");
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(a!.left).not.toBe("");
    expect(b!.left).not.toBe("");
    // 同坐标 → 下层点不到；验收=两人分占独立槽
    expect(`${a!.left}|${a!.top}`).not.toBe(`${b!.left}|${b!.top}`);
  });

  it("同 role 次名拖动松手不吸附回已占固定槽", async () => {
    const host = await renderCourtList([
      minister({ name: "来宗道", office: "礼部尚书,东阁大学士" }),
      minister({ name: "温体仁", office: "礼部尚书" }),
    ]);

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const secondary = cards.find((el) => el.querySelector(".minister-name")?.textContent === "温体仁");
    expect(secondary).toBeTruthy();

    // 模拟拖离原位再松手：mousemove 必须先 flush，否则 onUp 清空 dragging 后 setState 会空引用
    // 若 onUp 仍强制 fixed，会与首名叠回同一槽
    await act(async () => {
      secondary!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 180, clientY: 160 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 180, clientY: 160 }));
    });

    const a = cardPos(host, "来宗道");
    const b = cardPos(host, "温体仁");
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(`${a!.left}|${a!.top}`).not.toBe(`${b!.left}|${b!.top}`);
  });

  it("#1499-F1 StrictMode 松手：吸附副作用在 updater 外，POST 恰一次", async () => {
    // 判官 mutation 反例：把 drawers.tsx 回退至 57dc9cfe（副作用回到 setState updater 内），
    // StrictMode 双调 updater → commitSave 两发 → 本测试必须转红；非 StrictMode 不具判别力。
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/api/court_layout")) {
        if (init && String(init.method || "GET").toUpperCase() === "POST") {
          return { ok: true, json: async () => ({}) } as Response;
        }
        return { ok: true, json: async () => ({ layout: "{}" }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <React.StrictMode>
          <MinisterCardList
            list={[minister({ name: "施凤来", office: "东阁大学士" })]}
            portraitPrefix="minister_"
            selectedMinister=""
            emptyNote="empty"
            onOpenChat={() => {}}
            courtMode={true}
          />
        </React.StrictMode>
      );
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const court = host.querySelector(".minister-list-court") as HTMLElement | null;
    expect(court).toBeTruthy();
    court!.getBoundingClientRect = () =>
      ({
        x: 0, y: 0, width: 1000, height: 1000,
        top: 0, right: 1000, bottom: 1000, left: 0, toJSON: () => ({}),
      }) as DOMRect;

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const shiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "施凤来");
    expect(shiCard).toBeTruthy();

    await act(async () => {
      shiCard!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 500, clientY: 500 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 120, clientY: 80 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 120, clientY: 80 }));
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // 纯化 updater：同一次松手只允许一次 POST（StrictMode 双调下旧实现会发两发）
    const posts = fetchMock.mock.calls.filter(
      (c) =>
        String(c[0]).includes("/api/court_layout") &&
        c[1] &&
        String((c[1] as RequestInit).method || "").toUpperCase() === "POST",
    );
    expect(posts.length).toBe(1);
    const body = JSON.parse(String((posts[0][1] as RequestInit).body));
    const saved = JSON.parse(body.layout) as Record<string, { px: number; py: number }>;
    expect(saved["施凤来"]).toBeTruthy();

    mountedRoots.push({ root, host });
  });

  it("同衔两张 minister-card 依次点击均委派 onOpenChat", async () => {
    // 票面复现对：来宗道/温体仁同「礼部尚书」——每人一张卡，各自 click 须召对到本人
    const lai = minister({ name: "来宗道", office: "礼部尚书,东阁大学士" });
    const wen = minister({ name: "温体仁", office: "礼部尚书" });
    const onOpenChat = vi.fn();
    const host = await renderCourtList([lai, wen], onOpenChat);

    const cards = Array.from(host.querySelectorAll<HTMLElement>("button.minister-card"));
    const laiCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "来宗道");
    const wenCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "温体仁");
    expect(laiCard).toBeTruthy();
    expect(wenCard).toBeTruthy();

    await act(async () => {
      laiCard!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      wenCard!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenChat).toHaveBeenCalledTimes(2);
    expect(onOpenChat.mock.calls[0][0]).toBe(lai);
    expect(onOpenChat.mock.calls[1][0]).toBe(wen);
  });
});
