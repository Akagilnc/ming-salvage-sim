import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LLMConfigInfo } from "../types";
import {
  ExitToMenuTab,
  GameMenuModal,
  LLMConfigTab,
  LoadTab,
  SavesList,
  ShutdownTab,
  mergePersistedSaveSnapshot,
} from "./gameMenu";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE_LLM_RESPONSE = {
  channel: "api" as const,
  base_url: "https://api.example.com/v1",
  model: "gpt-4o-mini",
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

function changeInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
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

  it("labels codex off reasoning as the codex low floor", async () => {
    mockFetch({
      ...BASE_LLM_RESPONSE,
      channel: "cli",
      cli_runner: "codex",
      reasoning_strength: "off",
      reasoning_supported: true,
      persisted: {
        ...BASE_LLM_RESPONSE.persisted,
        channel: "cli",
        cli_runner: "codex",
        cli_model: "gpt-5.5",
        cli_timeout_seconds: 240,
        cli_reasoning_strength: "off",
      },
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    expect(strength?.value).toBe("off");
    const offOption = Array.from(strength?.options || []).find((option) => option.value === "off");
    expect(offOption?.textContent).toBe("关（codex 最低=低）");
    cleanup();
  });

  it("offers grok in the CLI runner dropdown and enables reasoning for it (#1271)", async () => {
    mockFetch({
      ...BASE_LLM_RESPONSE,
      channel: "cli",
      cli_runner: "grok",
      reasoning_strength: "high",
      reasoning_supported: true,
      cli_reasoning_runners: ["codex", "claude", "grok"],
      persisted: {
        ...BASE_LLM_RESPONSE.persisted,
        channel: "cli",
        cli_runner: "grok",
        cli_model: "",
        cli_timeout_seconds: 240,
        cli_reasoning_strength: "high",
      },
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const runnerSelect = Array.from(document.querySelectorAll("select")).find((select) =>
      Array.from(select.options).some((option) => option.value === "codex")
    );
    expect(runnerSelect).toBeTruthy();
    const runnerValues = Array.from(runnerSelect?.options || []).map((option) => option.value);
    // #1274 W1：runner 下拉吃后端/fallback 单源，含 grok + cursor/kimi（=_CLI_BACKENDS）。
    expect(runnerValues).toContain("grok");
    expect(runnerValues).toContain("cursor");
    expect(runnerValues).toContain("kimi");
    expect(runnerSelect?.value).toBe("grok");

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    const offOption = Array.from(strength?.options || []).find((option) => option.value === "off");
    expect(offOption?.textContent).toBe("关（grok 最低=低）");
    cleanup();
  });

  it("in-game CLI runner dropdown includes grok from shared source (#1274 W1)", async () => {
    mockFetch({
      ...BASE_LLM_RESPONSE,
      channel: "cli",
      cli_runner: "agy",
      cli_runners: [
        { value: "agy", label: "agy（Gemini）" },
        { value: "codex", label: "codex" },
        { value: "claude", label: "claude" },
        { value: "cursor", label: "cursor" },
        { value: "kimi", label: "kimi" },
        { value: "grok", label: "grok" },
      ],
      persisted: {
        ...BASE_LLM_RESPONSE.persisted,
        channel: "cli",
        cli_runner: "agy",
      },
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const runnerSelect = Array.from(document.querySelectorAll("select")).find((select) =>
      Array.from(select.options).some((option) => option.value === "codex")
    );
    const runnerValues = Array.from(runnerSelect?.options || []).map((option) => option.value);
    expect(runnerValues).toEqual(["agy", "codex", "claude", "cursor", "kimi", "grok"]);
    expect(runnerValues).toContain("grok");
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
          advanced_thinking_level: "high",
          reasoning_supported: true,
          persisted: {
            ...BASE_LLM_RESPONSE.persisted,
            thinking_level: "high",
            reasoning_strength: "",
            advanced_thinking_level: "high",
          },
        }),
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    // selector migrated the legacy value into the unified strength
    const select = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(select?.value).toBe("high");
    expect(document.body.textContent).not.toContain("Advanced Thinking Level");

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
    expect(body.advanced_thinking_level).toBe("");
    cleanup();
  });

  it("uses the saved CLI reasoning strength when switching from API to CLI", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({
        ok: true,
        json: async () => ({
          ...BASE_LLM_RESPONSE,
          channel: "api",
          reasoning_strength: "",
          reasoning_supported: true,
          persisted: {
            ...BASE_LLM_RESPONSE.persisted,
            channel: "api",
            reasoning_strength: "",
            cli_runner: "codex",
            cli_model: "gpt-5.5",
            cli_timeout_seconds: 240,
            cli_reasoning_strength: "high",
          },
        }),
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const channelSelect = Array.from(document.querySelectorAll("select")).find((s) =>
      s.querySelector('option[value="cli"]')
    ) as HTMLSelectElement | undefined;
    expect(channelSelect).toBeTruthy();
    act(() => {
      channelSelect!.value = "cli";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.value).toBe("high");
    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
    const body = JSON.parse(String(post!.init!.body));
    expect(body.channel).toBe("cli");
    expect(body.reasoning_strength).toBe("high");
    cleanup();
  });

  it("uses the saved API reasoning strength when switching from CLI to API", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({
        ok: true,
        json: async () => ({
          ...BASE_LLM_RESPONSE,
          channel: "cli",
          cli_runner: "codex",
          reasoning_strength: "high",
          reasoning_supported: true,
          persisted: {
            ...BASE_LLM_RESPONSE.persisted,
            channel: "cli",
            api_reasoning_strength: "low",
            cli_reasoning_strength: "high",
          },
        }),
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const channelSelect = Array.from(document.querySelectorAll("select")).find((s) =>
      s.querySelector('option[value="api"]')
    ) as HTMLSelectElement | undefined;
    act(() => {
      channelSelect!.value = "api";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.value).toBe("low");
    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
    const body = JSON.parse(String(post!.init!.body));
    expect(body.channel).toBe("api");
    expect(body.reasoning_strength).toBe("low");
    cleanup();
  });

  it.each(["disabled", "none"])(
    "migrates legacy %s thinking level to unified off",
    async (legacyThinkingLevel) => {
      const calls: Array<{ url: string; init?: RequestInit }> = [];
      global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return Promise.resolve({
          ok: true,
          json: async () => ({
            ...BASE_LLM_RESPONSE,
            base_url: "https://api.minimax.io/v1",
            model: "minimax-test",
            thinking_level: legacyThinkingLevel,
            reasoning_strength: "",
            reasoning_supported: true,
            persisted: { ...BASE_LLM_RESPONSE.persisted, thinking_level: legacyThinkingLevel, reasoning_strength: "" },
          }),
        } as Response);
      });
      const { cleanup } = render(<LLMConfigTab />);
      await act(async () => {});

      const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
      expect(strength?.value).toBe("off");
      const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
        (b.textContent ?? "").includes("保存并应用")
      );
      await act(async () => {
        saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });

      const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
      const body = JSON.parse(String(post!.init!.body));
      expect(body.thinking_level).toBe("");
      expect(body.reasoning_strength).toBe("off");
      cleanup();
    }
  );

  it("uses advanced model capability for API reasoning support", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...BASE_LLM_RESPONSE,
        base_url: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        advanced_base_url: "https://api.example.com/v1",
        advanced_model: "gpt-5",
        reasoning_supported: true,
      }),
    } as Response);
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    cleanup();
  });

  it("trusts backend reasoning_supported over local API model heuristics", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...BASE_LLM_RESPONSE,
        base_url: "https://api.example.com/v1",
        model: "gpt-5",
        reasoning_supported: false,
      }),
    } as Response);
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    expect(document.body.textContent).toContain("该后端不支持推理强度设置");
    cleanup();
  });

  it("keeps trusting backend reasoning support for whitespace-only API edits", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...BASE_LLM_RESPONSE,
        base_url: "https://api.example.com/v1",
        model: "gpt-5",
        reasoning_supported: false,
      }),
    } as Response);
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="gpt-4o-mini"]');
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(modelInput!, " gpt-5 ");
    });

    expect(strength?.disabled).toBe(true);
    cleanup();
  });

  it("keeps the save snapshot when initial load failed and the response has no persisted block", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (!init?.method) {
        return Promise.reject(new Error("load failed"));
      }
      const response: Partial<LLMConfigInfo> = {
        ...BASE_LLM_RESPONSE,
        base_url: "https://api.example.com/v1",
        model: "gpt-5",
        reasoning_supported: true,
      };
      delete response.persisted;
      delete response.cli_model_choices;
      return Promise.resolve({
        ok: true,
        json: async () => response,
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const baseUrlInput = document.querySelector<HTMLInputElement>('input[placeholder="https://api.openai.com/v1"]');
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="gpt-4o-mini"]');
    expect(baseUrlInput).toBeTruthy();
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(baseUrlInput!, "https://api.example.com/v1");
      changeInput(modelInput!, "gpt-5");
    });

    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    expect(saveBtn).toBeTruthy();
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    expect(calls.some((call) => call.init?.method === "POST")).toBe(true);
    cleanup();
  });

  it("merges save response fields into existing persisted snapshot when the response omits persisted", () => {
    const current: LLMConfigInfo = {
      ...BASE_LLM_RESPONSE,
      persisted: {
        ...BASE_LLM_RESPONSE.persisted,
        base_url: "https://old.example.com/v1",
        model: "old-model",
        api_reasoning_strength: "low",
        cli_reasoning_strength: "medium",
        cli_runner: "codex",
        cli_model: "raw-cli-model",
        cli_timeout_seconds: 120,
      },
    };
    const response: Partial<LLMConfigInfo> = {
      ...BASE_LLM_RESPONSE,
      base_url: "https://api.example.com/v1",
      model: "gpt-5",
      reasoning_strength: "high",
      reasoning_supported: true,
    };
    delete response.persisted;

    expect(mergePersistedSaveSnapshot(response as LLMConfigInfo, current)).toMatchObject({
      base_url: "https://api.example.com/v1",
      model: "gpt-5",
      api_reasoning_strength: "high",
      cli_reasoning_strength: "medium",
      cli_runner: "codex",
      cli_model: "raw-cli-model",
      cli_timeout_seconds: 120,
    });
  });

  it("refreshes reasoning support from the save response before trusting the saved backend snapshot", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const response = init?.method === "POST"
        ? {
            ...BASE_LLM_RESPONSE,
            base_url: "https://api.deepseek.com/v1",
            model: "deepseek-chat",
            reasoning_strength: "",
            reasoning_supported: false,
          }
        : {
            ...BASE_LLM_RESPONSE,
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            reasoning_strength: "high",
            reasoning_supported: true,
          };
      return Promise.resolve({
        ok: true,
        json: async () => response,
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    const baseUrlInput = document.querySelector<HTMLInputElement>('input[placeholder="https://api.openai.com/v1"]');
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="gpt-4o-mini"]');
    expect(baseUrlInput).toBeTruthy();
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(baseUrlInput!, "https://api.deepseek.com/v1");
      changeInput(modelInput!, "deepseek-chat");
    });
    expect(strength?.disabled).toBe(true);

    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    expect(saveBtn).toBeTruthy();
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
    expect(post).toBeTruthy();
    expect(strength?.disabled).toBe(true);
    expect(document.body.textContent).toContain("该后端不支持推理强度设置");
    cleanup();
  });

  it("uses normalized save response fields when deciding whether backend reasoning support is current", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const response = init?.method === "POST"
        ? {
            ...BASE_LLM_RESPONSE,
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            reasoning_strength: "",
            reasoning_supported: true,
          }
        : {
            ...BASE_LLM_RESPONSE,
            base_url: "https://api.deepseek.com/v1",
            model: "deepseek-chat",
            reasoning_strength: "",
            reasoning_supported: false,
          };
      return Promise.resolve({
        ok: true,
        json: async () => response,
      } as Response);
    });
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    const baseUrlInput = document.querySelector<HTMLInputElement>('input[placeholder="https://api.openai.com/v1"]');
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="gpt-4o-mini"]');
    expect(baseUrlInput).toBeTruthy();
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(baseUrlInput!, "https://api.example.com");
      changeInput(modelInput!, " gpt-5 ");
    });

    const saveBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("保存并应用")
    );
    expect(saveBtn).toBeTruthy();
    await act(async () => {
      saveBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((c) => c.init?.method === "POST" && c.url === "/api/llm/config");
    expect(post).toBeTruthy();
    expect(baseUrlInput?.value).toBe("https://api.example.com/v1");
    expect(modelInput?.value).toBe("gpt-5");
    expect(strength?.disabled).toBe(false);
    cleanup();
  });

  it("falls back to local API capability when the loaded backend setting is edited", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...BASE_LLM_RESPONSE,
        base_url: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        reasoning_supported: false,
      }),
    } as Response);
    const { cleanup } = render(<LLMConfigTab />);
    await act(async () => {});

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    const baseUrlInput = document.querySelector<HTMLInputElement>('input[placeholder="https://api.openai.com/v1"]');
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="gpt-4o-mini"]');
    expect(baseUrlInput).toBeTruthy();
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(baseUrlInput!, "https://api.example.com/v1");
      changeInput(modelInput!, "gpt-5");
    });

    expect(strength?.disabled).toBe(false);
    cleanup();
  });
});

describe("#1732 GameMenu · 就地消解", () => {
  it("不再提供「重开新局」页签", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ saves: [] }),
    } as Response);
    const { cleanup } = render(
      <GameMenuModal onClose={() => {}} onAfterLoad={() => {}} onExitToMenu={() => {}} />
    );
    await act(async () => {});
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("重开新局");
    expect(text).toContain("回到主菜单");
    cleanup();
  });

  it("回到主菜单：面板直通，不调 window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const onExit = vi.fn(async () => {});
    const { cleanup } = render(<ExitToMenuTab onExit={onExit} />);
    const btn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("回到主菜单")
    );
    expect(btn).toBeTruthy();
    await act(async () => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(confirm).not.toHaveBeenCalled();
    expect(onExit).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it("退出游戏：面板直通，不调 window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    global.fetch = vi.fn().mockResolvedValue({ ok: true } as Response);
    const { cleanup } = render(<ShutdownTab />);
    const btn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("退出游戏")
    );
    await act(async () => {
      btn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(confirm).not.toHaveBeenCalled();
    expect(global.fetch).toHaveBeenCalledWith("/api/menu/shutdown", { method: "POST" });
    cleanup();
  });

  it("加载存档：取消就地确认零请求；确认后 POST load", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (String(url) === "/api/saves" && !init?.method) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ saves: [{ name: "slot_a", mtime: 1, size: 2048 }] }),
        } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    const onAfterLoad = vi.fn();
    const { cleanup } = render(<LoadTab onAfterLoad={onAfterLoad} />);
    await act(async () => {});

    const loadBtn = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").trim() === "加载" || (b.textContent || "").includes("加载")
    );
    expect(loadBtn).toBeTruthy();
    await act(async () => {
      loadBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel = document.querySelector('[aria-label="确认加载 slot_a"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(calls.some((c) => String(c.url).includes("/load"))).toBe(false);

    await act(async () => {
      loadBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel2 = document.querySelector('[aria-label="确认加载 slot_a"]');
    const yes = Array.from(panel2!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("加载")
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(calls.some((c) => String(c.url).includes("/api/saves/slot_a/load") && c.init?.method === "POST")).toBe(true);
    expect(onAfterLoad).toHaveBeenCalled();
    cleanup();
  });

  it("删除存档：行下展开；取消零请求；确认后 DELETE", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response);
    });
    const onRefresh = vi.fn();
    const { cleanup } = render(
      <SavesList saves={[{ name: "keep", mtime: 1, size: 1024 }]} onRefresh={onRefresh} />
    );
    const del = Array.from(document.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("删")
    );
    await act(async () => {
      del!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const panel = document.querySelector('[aria-label="确认删除 keep"]');
    expect(panel).not.toBeNull();
    const cancel = Array.from(panel!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("取消")
    );
    await act(async () => {
      cancel!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);

    await act(async () => {
      del!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const yes = Array.from(document.querySelector('[aria-label="确认删除 keep"]')!.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("删除")
    );
    await act(async () => {
      yes!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(calls.some((c) => String(c.url).includes("/api/saves/keep") && c.init?.method === "DELETE")).toBe(true);
    expect(onRefresh).toHaveBeenCalled();
    cleanup();
  });
});
