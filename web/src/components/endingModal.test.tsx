import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EndingModal } from "./endingModal";
import type { EndingPayload } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const baseEnding: EndingPayload = {
  status: "collapse",
  label: "社稷倾覆",
  summary: "",
  timeline: [],
  summary_pending: false,
};

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return {
    host,
    cleanup: () => {
      act(() => {
        root.unmount();
        host.remove();
      });
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EndingModal — #1845 终局失败空总评呈现", () => {
  it("机械尾失败且空总评时不显示「（无总评）」冒充完成", () => {
    const onRetry = vi.fn();
    const { host, cleanup } = render(
      <EndingModal
        ending={baseEnding}
        failure={{ error: "模型调用耗尽", error_pack_path: "/tmp/pack.json" }}
        onClose={() => {}}
        onRetry={onRetry}
      />,
    );

    expect(host.textContent).toContain("机械尾执行失败");
    expect(host.textContent).toContain("模型调用耗尽");
    expect(host.textContent).not.toContain("（无总评）");
    cleanup();
  });

  it("无失败且空总评且非 pending 时仍可显示「（无总评）」", () => {
    const { host, cleanup } = render(
      <EndingModal ending={baseEnding} onClose={() => {}} />,
    );

    expect(host.textContent).toContain("（无总评）");
    cleanup();
  });

  it("总评 pending 时空正文，不显示「（无总评）」", () => {
    const { host, cleanup } = render(
      <EndingModal
        ending={{ ...baseEnding, summary_pending: true }}
        onClose={() => {}}
      />,
    );

    expect(host.querySelector(".ending-summary-text")?.textContent).toBe("");
    expect(host.textContent).not.toContain("（无总评）");
    cleanup();
  });
});
