import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { MenuPage } from "./menuPage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return () => {
    act(() => root.unmount());
    host.remove();
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("MenuPage subtitle", () => {
  it("does not show incorrect era year 崇祯元年 in subtitle", () => {
    const cleanup = render(
      <MenuPage
        status={null}
        onRefresh={async () => { throw new Error("not called"); }}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );
    const subtitle = document.querySelector(".menu-subtitle");
    expect(subtitle?.textContent).not.toContain("崇祯元年");
    cleanup();
  });
});
