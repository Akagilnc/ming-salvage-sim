import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { NodeIntel } from "./map";
import type { MapNode, Region } from "../types";

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

describe("NodeIntel monthly tax display", () => {
  it("shows tax_per_turn=1 as 1万/月, not rounded quarterly 0", () => {
    const host = renderNodeIntel(makeNode(makeRegion({ tax_per_turn: 1 })));

    expect(host.textContent).toContain("月税");
    expect(host.textContent).toContain("1万/月");
    expect(host.textContent).not.toMatch(/月税\s*0万\/月/);
  });
});
