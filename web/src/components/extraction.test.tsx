import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { CloseIssuesBlock } from "./extraction";

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

describe("CloseIssuesBlock", () => {
  it("renders acknowledged due-commitment close as a successful confirmation", () => {
    const cleanup = render(
      <CloseIssuesBlock
        data={[
          {
            issue_id: 136,
            reason: "acknowledged",
            narrative: "皇帝已复试孙承宗，此承诺已由圣裁处理。",
          },
        ]}
      />
    );

    const label = document.querySelector("b");
    expect(label?.className).toBe("good");
    expect(label?.textContent).toContain("确认");
    expect(document.body.textContent).not.toContain("失败");
    cleanup();
  });

  it("keeps failed close rows styled as failure", () => {
    const cleanup = render(
      <CloseIssuesBlock data={[{ issue_id: 137, reason: "failed", narrative: "局势败坏。" }]} />
    );

    const label = document.querySelector("b");
    expect(label?.className).toBe("bad");
    expect(label?.textContent).toContain("失败");
    cleanup();
  });
});
