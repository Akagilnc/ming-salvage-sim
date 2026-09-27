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
  it("机械尾失败且空总评时 summary 为空、alert 含输入错误、有重试入口", () => {
    const onRetry = vi.fn();
    const inputError = "模型调用耗尽";
    const { host, cleanup } = render(
      <EndingModal
        ending={baseEnding}
        failure={{ error: inputError, error_pack_path: "/tmp/pack.json" }}
        onClose={() => {}}
        onRetry={onRetry}
      />,
    );

    expect(host.querySelector(".ending-summary-text")?.textContent).toBe("");
    const alert = host.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain(inputError);
    const retryButton = Array.from(host.querySelectorAll("button")).find(
      (node) => node.textContent === "重试",
    );
    expect(retryButton).toBeTruthy();
    act(() => retryButton?.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it("无失败且空总评且非 pending 时 summary 非空", () => {
    const { host, cleanup } = render(
      <EndingModal ending={baseEnding} onClose={() => {}} />,
    );

    const summaryText = host.querySelector(".ending-summary-text")?.textContent ?? "";
    expect(summaryText.length).toBeGreaterThan(0);
    cleanup();
  });
});
