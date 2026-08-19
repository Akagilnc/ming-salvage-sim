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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function streamResponse(chunks: string[], ok = true): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const body = {
    getReader() {
      return {
        async read() {
          if (index >= chunks.length) return { value: undefined, done: true };
          const value = encoder.encode(chunks[index++]);
          return { value, done: false };
        },
      };
    },
  };
  return { ok, status: ok ? 200 : 500, body } as unknown as Response;
}

const readyStatus = {
  has_api_key: false,
  llm_ready: true,
  has_running_game: false,
  has_main_db: true,
  saves: [] as [],
  campaigns: [] as [],
  llm: {
    channel: "cli" as const,
    base_url: "",
    model: "",
    has_api_key: false,
    cli_runner: "codex",
    cli_model: "gpt-5.3-codex-spark",
    cli_model_saved: "gpt-5.3-codex-spark",
    cli_model_choices: { codex: [{ value: "gpt-5.3-codex-spark", label: "gpt-5.3-codex-spark" }] },
    cli_timeout_seconds: 300,
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
    advanced_model: "",
    advanced_base_url: "",
    has_advanced_api_key: false,
    advanced_thinking_level: "",
  },
};

describe("MenuPage continue SSE stages (#1195)", () => {
  it("updates busy label from stage events then enters game", async () => {
    const enterGame = vi.fn(async () => {});
    const setError = vi.fn();
    // 分块推送：第一读只给首条 stage，便于断言 busy 已更新；再推后续。
    const encoder = new TextEncoder();
    let pull = 0;
    const chunks = [
      'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
      'event: stage\ndata: {"content":"载入上次进度..."}\n\n',
      'event: stage\ndata: {"content":"重整朝堂名册..."}\n\n',
      'event: done\ndata: {"state":{"ok":true}}\n\n',
    ];
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url !== "/api/menu/continue") {
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      }
      const body = {
        getReader() {
          return {
            async read() {
              if (pull >= chunks.length) return { value: undefined, done: true };
              const value = encoder.encode(chunks[pull++]);
              return { value, done: false };
            },
          };
        },
      };
      return Promise.resolve({ ok: true, status: 200, body } as unknown as Response);
    });

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={enterGame}
        error=""
        setError={setError}
      />
    );

    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    expect(continueBtn).toBeTruthy();
    expect(continueBtn?.disabled).toBe(false);

    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // 让微任务跑完首条 stage 的 setBusy
      await Promise.resolve();
      await Promise.resolve();
    });

    // 流消费完成后应进游戏；busy 区在 finally 清空
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch).toHaveBeenCalledWith("/api/menu/continue", { method: "POST" });
    expect(enterGame).toHaveBeenCalledTimes(1);
    // guard 开头会 setError("") 清旧错；成功路径不应再写入非空错误
    const errorPayloads = setError.mock.calls.map((c) => c[0]).filter((m) => m);
    expect(errorPayloads).toEqual([]);
    // 终态 busy 已清（进 HUD 由 onEnterGame 负责）
    expect(document.querySelector(".menu-busy")).toBeNull();
    cleanup();
  });

  it("surfaces SSE error message without entering game", async () => {
    const enterGame = vi.fn(async () => {});
    const setError = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(
      streamResponse([
        'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
        'event: error\ndata: {"message":"未配 API key，请先到设置页填写。"}\n\n',
      ]),
    );

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={enterGame}
        error=""
        setError={setError}
      />
    );

    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      // 等 reader 抽完 stage+error 并 throw→guard catch
      for (let i = 0; i < 10; i++) await Promise.resolve();
    });

    expect(enterGame).not.toHaveBeenCalled();
    const errMsg = setError.mock.calls.map((c) => String(c[0] || "")).find((m) => m.includes("未配 API key"));
    expect(errMsg).toBeTruthy();
    cleanup();
  });

  it("replaces busy label when stage events arrive mid-stream", async () => {
    const encoder = new TextEncoder();
    let pull = 0;
    let resumeRead: (() => void) | null = null;
    const waitPull = () => new Promise<void>((resolve) => { resumeRead = resolve; });
    const chunks = [
      'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
      'event: stage\ndata: {"content":"重整朝堂名册..."}\n\n',
      'event: done\ndata: {"state":{}}\n\n',
    ];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader() {
          return {
            async read() {
              if (pull >= chunks.length) return { value: undefined, done: true };
              if (pull > 0) await waitPull();
              const value = encoder.encode(chunks[pull++]);
              return { value, done: false };
            },
          };
        },
      },
    } as unknown as Response);

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );
    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
    expect(document.querySelector(".menu-busy")?.textContent).toContain("检查模型后端");

    await act(async () => {
      resumeRead?.();
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
    expect(document.querySelector(".menu-busy")?.textContent).toContain("重整朝堂名册");

    await act(async () => {
      resumeRead?.();
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
    cleanup();
  });

  it("shows initial 载入上次进度 label immediately on click before first chunk", async () => {
    let release!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    global.fetch = vi.fn().mockReturnValue(gate);

    const cleanup = render(
      <MenuPage
        status={readyStatus as any}
        onRefresh={async () => readyStatus as any}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />
    );

    const continueBtn = Array.from(document.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "继续"
    );
    await act(async () => {
      continueBtn!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const busy = document.querySelector(".menu-busy");
    expect(busy?.textContent).toContain("载入上次进度");
    // 禁百分比/进度条/剩余秒数
    expect(busy?.textContent || "").not.toMatch(/%|进度条|\d+\s*秒/);

    await act(async () => {
      release(
        streamResponse([
          'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
          'event: done\ndata: {"state":{}}\n\n',
        ]),
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    cleanup();
  });
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

  it("offers grok in the CLI runner dropdown and enables reasoning for it (#1271)", () => {
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
            cli_runner: "grok",
            cli_model: "",
            cli_model_saved: "",
            cli_model_choices: { grok: [{ value: "", label: "默认 · grok" }] },
            cli_timeout_seconds: 240,
            reasoning_strength: "high",
            cli_reasoning_strength: "high",
            reasoning_supported: true,
            cli_reasoning_runners: ["codex", "claude", "grok"],
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

    const runnerSelect = Array.from(document.querySelectorAll("select")).find((select) =>
      Array.from(select.options).some((option) => option.value === "codex")
    );
    expect(runnerSelect).toBeTruthy();
    const runnerValues = Array.from(runnerSelect?.options || []).map((option) => option.value);
    expect(runnerValues).toContain("grok");
    expect(runnerValues).not.toContain("cursor");
    expect(runnerValues).not.toContain("kimi");
    expect(runnerSelect?.value).toBe("grok");

    const strength = document.querySelector<HTMLSelectElement>('select[name="reasoning_strength"]');
    expect(strength?.disabled).toBe(false);
    const offOption = Array.from(strength?.options || []).find((option) => option.value === "off");
    expect(offOption?.textContent).toBe("关（grok 最低=低）");
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
