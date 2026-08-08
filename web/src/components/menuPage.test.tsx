import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
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

function changeInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
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
    const subtitle = document.querySelector(".menu-tagline");
    expect(subtitle?.textContent).not.toContain("崇祯元年");
    cleanup();
  });
});

describe("ApiSettingsModal reasoning strength", () => {
  it("disables reasoning strength for unsupported CLI runners", () => {
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: false,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "cli",
            base_url: "",
            model: "",
            has_api_key: false,
            cli_runner: "agy",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "high",
            reasoning_supported: false,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => { throw new Error("not called"); }}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const select = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(select?.disabled).toBe(true);
    expect(document.body.textContent).toContain("该后端不支持推理强度设置");
    cleanup();
  });

  it("labels codex off reasoning as the codex low floor", () => {
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: false,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "cli",
            base_url: "",
            model: "",
            has_api_key: false,
            cli_runner: "codex",
            cli_model: "gpt-5.5",
            cli_model_saved: "gpt-5.5",
            cli_model_choices: { codex: [{ value: "gpt-5.5", label: "gpt-5.5" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "off",
            cli_reasoning_strength: "off",
            reasoning_supported: true,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => { throw new Error("not called"); }}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    expect(strength?.value).toBe("off");
    const offOption = Array.from(strength?.options || []).find((option) => option.value === "off");
    expect(offOption?.textContent).toBe("关（codex 最低=低）");
    cleanup();
  });

  it("does not expose or save a separate advanced thinking selector", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      } as Response);
    });
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "api",
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            has_api_key: true,
            cli_runner: "agy",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "medium",
            reasoning_supported: true,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "gpt-5",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "high",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(document.body.textContent).not.toContain("Advanced Thinking Level");
    const save = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent === "保存"
    );
    expect(save).toBeTruthy();
    await act(async () => {
      save!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const post = calls.find((call) => call.url === "/api/menu/llm");
    expect(post).toBeTruthy();
    const body = JSON.parse(String(post!.init!.body));
    expect(body.reasoning_strength).toBe("medium");
    expect(body.advanced_thinking_level).toBe("");
    cleanup();
  });

  it("uses the saved CLI reasoning strength when switching from API to CLI", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      } as Response);
    });
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "api",
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            has_api_key: true,
            cli_runner: "codex",
            cli_model: "gpt-5.5",
            cli_model_saved: "gpt-5.5",
            cli_model_choices: { codex: [{ value: "gpt-5.5", label: "gpt-5.5" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "",
            cli_reasoning_strength: "high",
            reasoning_supported: true,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const channelSelect = Array.from(document.querySelectorAll("select")).find((select) =>
      select.querySelector('option[value="cli"]')
    ) as HTMLSelectElement | undefined;
    act(() => {
      channelSelect!.value = "cli";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.value).toBe("high");
    const save = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent === "保存"
    );
    await act(async () => {
      save!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const body = JSON.parse(String(calls.find((call) => call.url === "/api/menu/llm")!.init!.body));
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
        json: async () => ({}),
      } as Response);
    });
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "cli",
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            has_api_key: true,
            cli_runner: "codex",
            cli_model: "gpt-5.5",
            cli_model_saved: "gpt-5.5",
            cli_model_choices: { codex: [{ value: "gpt-5.5", label: "gpt-5.5" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "high",
            api_reasoning_strength: "low",
            cli_reasoning_strength: "high",
            reasoning_supported: true,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const channelSelect = Array.from(document.querySelectorAll("select")).find((select) =>
      select.querySelector('option[value="api"]')
    ) as HTMLSelectElement | undefined;
    act(() => {
      channelSelect!.value = "api";
      channelSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.value).toBe("low");
    const save = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent === "保存"
    );
    await act(async () => {
      save!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const body = JSON.parse(String(calls.find((call) => call.url === "/api/menu/llm")!.init!.body));
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
          json: async () => ({}),
        } as Response);
      });
      const cleanup = render(
        <MenuPage
          status={{
            has_api_key: true,
            llm_ready: true,
            has_running_game: false,
            has_main_db: false,
            saves: [],
            campaigns: [],
            llm: {
              channel: "api",
              base_url: "https://api.minimax.io/v1",
              model: "minimax-test",
              has_api_key: true,
              cli_runner: "agy",
              cli_model: "",
              cli_model_saved: "",
              cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
              cli_timeout_seconds: 240,
              reasoning_strength: "",
              reasoning_supported: true,
              reasoning_strengths: [
                { value: "", label: "默认" },
                { value: "off", label: "关" },
                { value: "low", label: "低" },
                { value: "medium", label: "中" },
                { value: "high", label: "高" },
              ],
              max_tokens: 8000,
              timeout_seconds: 180,
              thinking_level: legacyThinkingLevel,
              advanced_model: "",
              advanced_base_url: "",
              has_advanced_api_key: false,
              advanced_thinking_level: "",
            },
          }}
          onRefresh={async () => ({} as any)}
          onEnterGame={async () => {}}
          error=""
          setError={() => {}}
        />
      );

      act(() => {
        Array.from(document.querySelectorAll("button")).find((button) =>
          button.textContent?.includes("模型后端")
        )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });

      const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
      expect(strength?.value).toBe("off");
      const save = Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent === "保存"
      );
      await act(async () => {
        save!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });

      const body = JSON.parse(String(calls.find((call) => call.url === "/api/menu/llm")!.init!.body));
      expect(body.thinking_level).toBe("");
      expect(body.reasoning_strength).toBe("off");
      cleanup();
    }
  );

  it("uses advanced model capability for API reasoning support", () => {
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "api",
            base_url: "https://api.deepseek.com/v1",
            model: "deepseek-chat",
            has_api_key: true,
            cli_runner: "agy",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "",
            reasoning_supported: true,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "gpt-5",
            advanced_base_url: "https://api.example.com/v1",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    cleanup();
  });

  it("trusts backend reasoning_supported over local API model heuristics", () => {
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "api",
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            has_api_key: true,
            cli_runner: "agy",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "",
            reasoning_supported: false,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    expect(document.body.textContent).toContain("该后端不支持推理强度设置");
    cleanup();
  });

  it("keeps trusting backend reasoning support for whitespace-only API edits", () => {
    const cleanup = render(
      <MenuPage
        status={{
          has_api_key: true,
          llm_ready: true,
          has_running_game: false,
          has_main_db: false,
          saves: [],
          campaigns: [],
          llm: {
            channel: "api",
            base_url: "https://api.example.com/v1",
            model: "gpt-5",
            has_api_key: true,
            cli_runner: "agy",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { agy: [{ value: "", label: "默认 · gemini" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "",
            reasoning_supported: false,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            max_tokens: 8000,
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => ({} as any)}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    act(() => {
      Array.from(document.querySelectorAll("button")).find((button) =>
        button.textContent?.includes("模型后端")
      )?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(true);
    const modelInput = document.querySelector<HTMLInputElement>('input[placeholder="deepseek-chat"]');
    expect(modelInput).toBeTruthy();
    act(() => {
      changeInput(modelInput!, " gpt-5 ");
    });

    expect(strength?.disabled).toBe(true);
    cleanup();
  });
});
