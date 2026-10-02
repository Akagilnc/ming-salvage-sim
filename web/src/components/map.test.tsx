import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { GrandMap, NodeIntel } from "./map";
import type { MapNode, Region } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];

function stubSvgGetBBox() {
  const proto = SVGElement.prototype as SVGElement & { getBBox?: () => DOMRect };
  if (typeof proto.getBBox !== "function") {
    proto.getBBox = () => ({
      x: 0, y: 0, width: 1, height: 1,
      top: 0, left: 0, bottom: 1, right: 1,
      toJSON() { return this; },
    }) as DOMRect;
  }
}

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
});


describe("GrandMap #1505 dongjiang_area merged pin", () => {
  it("renders a clickable control that selects dongjiang_area", () => {
    stubSvgGetBBox();
    const region = makeRegion({ id: "dongjiang_area", name: "东江海域" });
    const node: MapNode = {
      id: "dongjiang_area",
      kind: "theater",
      x: 68.9,
      y: 43.7,
      label: "东江 / 皮岛",
      risk: 80,
      region,
      armies: [],
    };
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const selected: string[] = [];
    act(() => {
      root.render(
        <GrandMap nodes={[node]} selectedId="" onSelect={(id) => selected.push(id)} />,
      );
    });
    mountedRoots.push({ root, host });

    const button = host.querySelector('button[data-node-id="dongjiang_area"]');
    expect(button).not.toBeNull();
    act(() => {
      (button as HTMLButtonElement).click();
    });
    expect(selected).toEqual(["dongjiang_area"]);
  });
});
