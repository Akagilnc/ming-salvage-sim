import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ArmyDrawer } from "./drawers";
import type { Army } from "../types";

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

afterEach(() => {
  for (const { root, host } of mountedRoots) {
    act(() => root.unmount());
    host.remove();
  }
  mountedRoots.length = 0;
  document.body.innerHTML = "";
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
});
