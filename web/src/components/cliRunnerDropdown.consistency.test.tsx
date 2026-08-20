/**
 * #1274 W1：gameMenu（局内）与 menuPage（主菜单）CLI Runner 下拉选项一致性钉。
 *
 * 变异：任一侧漏项 / 硬编码分叉 → 本测必红。两边都吃 cliRunnerOptions(cli_runners)。
 */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CLI_RUNNER_FALLBACK } from "../cliRunners";
import { LLMConfigTab } from "./gameMenu";
import { MenuPage } from "./menuPage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SHARED_RUNNERS = [
  { value: "agy", label: "agy（Gemini）" },
  { value: "codex", label: "codex" },
  { value: "claude", label: "claude" },
  { value: "cursor", label: "cursor" },
  { value: "kimi", label: "kimi" },
  { value: "grok", label: "grok" },
];

function render(element: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<>{element}</>));
  return {
    host,
    cleanup: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

function runnerValuesIn(root: ParentNode): string[] {
  const select = Array.from(root.querySelectorAll("select")).find((el) =>
    Array.from(el.options).some((option) => option.value === "codex"),
  );
  return Array.from(select?.options || []).map((option) => option.value);
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("CLI runner dropdown consistency (#1274 W1)", () => {
  it("gameMenu and menuPage offer identical runner options from the shared backend list", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        channel: "cli",
        base_url: "",
        model: "",
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
        has_api_key: false,
        cli_runner: "agy",
        cli_model: "",
        cli_runners: SHARED_RUNNERS,
        cli_timeout_seconds: 300,
        persisted: {
          channel: "cli",
          base_url: "",
          model: "",
          has_api_key: false,
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
      }),
    } as Response);

    const game = render(<LLMConfigTab />);
    await act(async () => {});
    const gameValues = runnerValuesIn(game.host);

    game.cleanup();

    const menu = render(
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
            cli_runners: SHARED_RUNNERS,
            cli_timeout_seconds: 300,
            reasoning_strength: "",
            reasoning_supported: false,
            reasoning_strengths: [
              { value: "", label: "默认" },
              { value: "off", label: "关" },
              { value: "low", label: "低" },
              { value: "medium", label: "中" },
              { value: "high", label: "高" },
            ],
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => {
          throw new Error("not called");
        }}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />,
    );

    act(() => {
      Array.from(document.querySelectorAll("button"))
        .find((button) => button.textContent?.includes("模型后端"))
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const menuValues = runnerValuesIn(menu.host);
    menu.cleanup();

    expect(gameValues.length).toBeGreaterThan(0);
    expect(menuValues).toEqual(gameValues);
    expect(gameValues).toEqual(SHARED_RUNNERS.map((r) => r.value));
    expect(gameValues).toContain("grok");
  });

  it("both pages fall back to the same anchored constant when cli_runners is absent", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        channel: "cli",
        base_url: "",
        model: "",
        timeout_seconds: 180,
        thinking_level: "",
        reasoning_strength: "",
        reasoning_supported: false,
        reasoning_strengths: [{ value: "", label: "默认" }],
        advanced_model: "",
        advanced_base_url: "",
        has_advanced_api_key: false,
        advanced_thinking_level: "",
        has_api_key: false,
        cli_runner: "agy",
        cli_model: "",
        // no cli_runners — force fallback
        cli_timeout_seconds: 300,
        persisted: {
          channel: "cli",
          base_url: "",
          model: "",
          has_api_key: false,
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
      }),
    } as Response);

    const game = render(<LLMConfigTab />);
    await act(async () => {});
    const gameValues = runnerValuesIn(game.host);
    game.cleanup();

    const menu = render(
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
            // no cli_runners
            cli_timeout_seconds: 300,
            reasoning_strength: "",
            reasoning_supported: false,
            reasoning_strengths: [{ value: "", label: "默认" }],
            timeout_seconds: 180,
            thinking_level: "",
            advanced_model: "",
            advanced_base_url: "",
            has_advanced_api_key: false,
            advanced_thinking_level: "",
          },
        }}
        onRefresh={async () => {
          throw new Error("not called");
        }}
        onEnterGame={async () => {}}
        error=""
        setError={() => {}}
      />,
    );
    act(() => {
      Array.from(document.querySelectorAll("button"))
        .find((button) => button.textContent?.includes("模型后端"))
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const menuValues = runnerValuesIn(menu.host);
    menu.cleanup();

    const expected = CLI_RUNNER_FALLBACK.map((r) => r.value);
    expect(gameValues).toEqual(expected);
    expect(menuValues).toEqual(expected);
    expect(expected).toContain("grok");
  });
});
