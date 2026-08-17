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

async function renderCourtList(list: Minister[]) {
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
        onOpenChat={() => {}}
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
});
