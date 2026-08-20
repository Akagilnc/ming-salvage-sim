import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArmyDrawer, MinisterCardList } from "./drawers";
import type { Army, Minister } from "../types";

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
  it("shows approximate total arrears and qualitative abstract stats", () => {
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
      morale: 73,
      training: 73,
      equipment: 73,
      arrears: 63,
      mobility: 73,
      loyalty: 73,
      status: "可支援辽东和海运",
      owner_power: "ming",
    });

    expect(host.textContent).toContain("欠饷约60万两");
    expect(host.textContent).toContain("忠诚尚稳");
    expect(host.textContent).not.toContain("63万两");
    expect(host.textContent).not.toContain("忠诚73");
  });

  it("renders fractional payload arrears with half-step approximation", () => {
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
      morale: 73,
      training: 73,
      equipment: 73,
      arrears: 12.5,
      mobility: 73,
      loyalty: 73,
      status: "可支援辽东和海运",
      owner_power: "ming",
    });

    expect(host.textContent).toContain("欠饷约15万两");
    expect(host.textContent).not.toContain("12.5万两");
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
            minister({ name: "施凤来", office: "次辅" }),
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
    const huangCard = cards.find((el) => el.querySelector(".minister-name")?.textContent === "黄立极");
    expect(huangCard).toBeTruthy();

    // 真拖拽：mousedown → mousemove(>3px) → mouseup。
    // 首辅松手会吸回固定槽；要钉「回包不回滚」，须在仍持拖拽位移时让 fetch 落地
    // （onMove 已写 savedPosRef；mouseup 仍派发以走完手势/卸监听）。
    await act(async () => {
      huangCard!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 100, clientY: 100 }));
    });
    await act(async () => {
      window.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 700, clientY: 100 }));
    });

    const dragged = cardPos(host, "黄立极");
    expect(dragged).not.toBeNull();
    expect(dragged!.left).not.toBe("");
    // 契约前提：拖中坐标须异于将要回包的服务端 layout，否则钉不住回滚
    expect(`${dragged!.left}|${dragged!.top}`).not.toBe("7.7%|53.2%");

    await act(async () => {
      // 非空且刻意不同于拖后：默认首辅锚点——若缺 savedPosRef 守卫会把本地拖拽滚回去
      resolveLayout({
        ok: true,
        json: async () => ({ layout: JSON.stringify({ 黄立极: { px: 0.077, py: 0.532 } }) }),
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    const after = cardPos(host, "黄立极");
    expect(after).not.toBeNull();
    expect(after!.left).not.toBe("");
    // pending 期间已拖 → 非空服务端 layout 回包不得回滚本地
    expect(after).toEqual(dragged);

    await act(async () => {
      window.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 700, clientY: 100 }));
    });
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
