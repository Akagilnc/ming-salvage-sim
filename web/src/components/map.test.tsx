import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { NodeIntel } from "./map";
import type { Army, MapNode, Region } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];

function renderNodeIntel(node: MapNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<NodeIntel node={node} />));
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
});

function makeRegion(overrides: Partial<Region> = {}): Region {
  return {
    id: "liaodong",
    name: "辽东",
    kind: "边镇",
    population: 100,
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
    status: "前线",
    controlled_by: "ming",
    ...overrides,
  };
}

function makeNode(region: Region): MapNode {
  return {
    id: region.id,
    kind: "region",
    x: 50,
    y: 50,
    label: region.name,
    risk: 0,
    region,
    armies: [],
  };
}

describe("NodeIntel #648 population (P7: LLM 长文，无 UI 模板)", () => {
  it("never renders fixed population strings (约N万口 / 不足一万口)", () => {
    const host = renderNodeIntel(makeNode(makeRegion({ population: 7200000 })));
    expect(host.textContent).not.toContain("万口");
    expect(host.textContent).not.toContain("不足一万");
    expect(host.textContent).not.toContain("undefined");
  });
});

describe("NodeIntel monthly tax display", () => {
  it("shows tax_per_turn=1 as 1万/月, not rounded quarterly 0", () => {
    const host = renderNodeIntel(makeNode(makeRegion({ tax_per_turn: 1 })));

    expect(host.textContent).toContain("月税");
    expect(host.textContent).toContain("1万/月");
    expect(host.textContent).not.toMatch(/月税\s*0万\/月/);
  });
});

describe("NodeIntel #1401 theater naming", () => {
  it("shows region.name when theater carries region (liaodong pin)", () => {
    // name/label 必须可区分：若误先渲染 label，本断言应红（#1448）
    const region = makeRegion({ id: "liaodong", name: "辽东省名-优先" });
    const node: MapNode = {
      id: "liaodong",
      kind: "theater",
      x: 57.76,
      y: 42.21,
      label: "theater-label-不应先显",
      risk: 120,
      region,
      armies: [],
    };
    const host = renderNodeIntel(node);
    expect(host.textContent).toContain("辽东省名-优先");
    expect(host.textContent).not.toContain("theater-label-不应先显");
  });

  it("falls back to label when theater has no region", () => {
    const node: MapNode = {
      id: "shanhaiguan",
      kind: "theater",
      x: 55.52,
      y: 42.84,
      label: "山海关",
      risk: 120,
      armies: [],
    };
    const host = renderNodeIntel(node);
    expect(host.textContent).toContain("山海关");
  });
});

describe("NodeIntel #1352 garrison layout / army-list口径", () => {
  function makeArmy(overrides: Partial<Army> = {}): Army {
    return {
      id: "shanhai",
      name: "山海关守军",
      station: "北直隶 / 山海关",
      theater: "蓟辽",
      commander: "赵率教",
      controller: "ming",
      troop_type: "关宁军",
      manpower: 28000,
      army_needed: 1.1,
      supply: 50,
      morale_text: "士气：不振",
      training: 45,
      equipment: 50,
      arrears_text: "欠饷不足十万两，约两月军饷",
      mobility: 40,
      mutiny_tier: "不满",
      status: "驻防",
      owner_power: "ming",
      ...overrides,
    };
  }

  it("驻军表兵力全数呈现且月饷带万，表头士气不拆字 class", () => {
    const node = makeNode(makeRegion({ name: "山海关", id: "shanhaiguan" }));
    node.armies = [makeArmy()];
    node.label = "山海关";
    const host = renderNodeIntel(node);

    const table = host.querySelector(".intel-table");
    expect(table).not.toBeNull();
    // 与军队列表同口径：全数兵力 + 月饷万两
    expect(host.textContent).toContain("28000");
    expect(host.textContent).not.toMatch(/(?<![\d])2800(?![\d])/);
    expect(host.textContent).toMatch(/1\.1\s*万/);
    // 表头保留完整「士气」词（布局 class 钉 nowrap，禁拆字）
    const headers = Array.from(host.querySelectorAll(".intel-table thead th")).map((th) => th.textContent || "");
    expect(headers.some((h) => h.includes("士气"))).toBe(true);
    expect(host.querySelector(".intel-table--garrison")).not.toBeNull();
  });
});
