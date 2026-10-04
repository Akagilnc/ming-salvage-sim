import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettlementGazettePanel } from "./settlementGazettePanel";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
});

describe("#1852 SettlementGazettePanel", () => {
  it("本面落位：正文直写；朕知道了只调 onDismiss", () => {
    const onDismiss = vi.fn();
    const host = mount(
      <SettlementGazettePanel
        report={"十月邸报\n一、边报"}
        attendantMessage="奴婢呈报。"
        periodLabel="天启七年十月"
        onDismiss={onDismiss}
      />,
    );
    expect(host.querySelector("[data-testid=settlement-gazette-panel]")).not.toBeNull();
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(host.querySelector("pre.memorial-text")?.textContent).toBe("十月邸报\n一、边报");
    expect(host.querySelector("[data-testid=gazette-attendant]")).not.toBeNull();
    expect(host.querySelector(".gazette-masthead")).not.toBeNull();

    const btn = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("朕知道了"),
    );
    expect(btn).toBeTruthy();
    act(() => { btn!.click(); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
