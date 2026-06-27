import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LLMConfigTab } from "./gameMenu";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE_LLM_RESPONSE = {
  channel: "api" as const,
  base_url: "https://api.example.com/v1",
  model: "gpt-4o-mini",
  max_tokens: 8000,
  timeout_seconds: 180,
  thinking_level: "",
  reasoning_strength: "",
  reasoning_supported: false,
  reasoning_strengths: [
    { value: "", label: "默认" },
    { value: "off", label: "关" },
    { value: "low", label: "低" },
    { value: "medium", label: "中" },
    { value: "high", label: "高" },
  ],
  advanced_model: "",
  advanced_base_url: "",
  has_advanced_api_key: false,
  advanced_thinking_level: "",
  has_api_key: true,
  cli_runner: "agy",
  cli_model: "",
  cli_timeout_seconds: 300,
  persisted: {
    channel: "api" as const,
    base_url: "https://api.example.com/v1",
    model: "gpt-4o-mini",
    has_api_key: true,
    max_tokens: 8000,
    timeout_seconds: 180,
    thinking_level: "",
    reasoning_strength: "",
    advanced_model: "",
    advanced_base_url: "",
    has_advanced_api_key: false,
    advanced_thinking_level: "",
    cli_runner: "agy",
    cli_model: "",
    cli_timeout_seconds: 300,
  },
};

function mockFetch(response: object) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => response,
  } as Response);
}

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return {
    cleanup: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("LLMConfigTab — channel-gated field rendering", () => {
  beforeEach(() => {
    mockFetch(BASE_LLM_RESPONSE);
  });

  it("shows API fields and hides CLI fields when channel=api (initial render)", async () => {
    const { cleanup } = render(<LLMConfigTab />);
    // flush fetch + state updates
    await act(async () => {});

    const text = document.body.textContent ?? "";
    expect(text).toContain("Base URL");
    expect(text).toContain("推理强度");
    expect(text).not.toContain("CLI Runner");
    expect(text).not.toContain("CLI 超时");
    cleanup();
  });

  it("shows CLI fields and hides API fields when channel is switched to cli", async () => {
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    // switch channel select to "cli"
    const selects = document.querySelectorAll("select");
    const channelSelect = Array.from(selects).find((s) =>
      s.querySelector('option[value="cli"]')
    );
    expect(channelSelect).toBeTruthy();
    act(() => {
      channelSelect!.value = "cli";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const text = document.body.textContent ?? "";
    expect(text).toContain("CLI Runner");
    expect(text).toContain("CLI 超时");
    expect(text).not.toContain("Base URL");
    cleanup();
  });

  it("restores API fields when channel is switched back to api", async () => {
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const selects = document.querySelectorAll("select");
    const channelSelect = Array.from(selects).find((s) =>
      s.querySelector('option[value="cli"]')
    );

    // switch to cli
    act(() => {
      channelSelect!.value = "cli";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // switch back to api
    act(() => {
      channelSelect!.value = "api";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const text = document.body.textContent ?? "";
    expect(text).toContain("Base URL");
    expect(text).not.toContain("CLI Runner");
    cleanup();
  });

  it("loads channel=cli from server and shows CLI fields", async () => {
    mockFetch({ ...BASE_LLM_RESPONSE, channel: "cli", persisted: { ...BASE_LLM_RESPONSE.persisted, channel: "cli" } });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const text = document.body.textContent ?? "";
    expect(text).toContain("CLI Runner");
    expect(text).not.toContain("Base URL");
    cleanup();
  });

  it("clears the legacy thinking_level shadow on save so the unified selector owns reasoning (#358 cmr)", async () => {
    // 旧档持有 thinking_level=high、reasoning_strength 空。统一选择器以旧值迁移初始化，
    // 保存时须清掉旧 thinking_level，否则它仍作隐藏旋钮、用户选「默认」也清不掉。
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({
        ok: true,
        json: async () => ({
          ...BASE_LLM_RESPONSE,
          thinking_level: "high",
          reasoning_strength: "",
          reasoning_supported: true,
          persisted: { ...BASE_LLM_RESPONSE.persisted, thinking_level: "high", reasoning_strength: "" },
        }),
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    // selector migrated the legacy value into the unified strength
    const select = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(select?.value).toBe("high");

    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    expect(saveBtn).toBeTruthy();
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
    expect(post).toBeTruthy();
    const body = JSON.parse(String(post!.init!.body));
    expect(body.reasoning_strength).toBe("high");
    expect(body.thinking_level).toBe("");
    cleanup();
  });
});
