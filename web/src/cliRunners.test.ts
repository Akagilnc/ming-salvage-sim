import { describe, expect, it } from "vitest";
import { CLI_RUNNER_FALLBACK, cliRunnerOptions } from "./cliRunners";

describe("cliRunnerOptions", () => {
  it("returns backend list when provided (single source wins)", () => {
    const backend = [
      { value: "agy", label: "agy（Gemini）" },
      { value: "codex", label: "codex" },
      { value: "claude", label: "claude" },
      { value: "cursor", label: "cursor" },
      { value: "kimi", label: "kimi" },
      { value: "grok", label: "grok" },
    ];
    expect(cliRunnerOptions(backend).map((o) => o.value)).toEqual([
      "agy", "codex", "claude", "cursor", "kimi", "grok",
    ]);
  });

  it("falls back to anchored constant when backend list missing/empty", () => {
    expect(cliRunnerOptions(undefined).map((o) => o.value)).toEqual(
      CLI_RUNNER_FALLBACK.map((o) => o.value),
    );
    expect(cliRunnerOptions([]).map((o) => o.value)).toEqual(
      CLI_RUNNER_FALLBACK.map((o) => o.value),
    );
  });

  it("fallback is non-empty unique options with value/label", () => {
    // #1902 F3：不锁完整 runner 字面名单；结构与唯一性即可。
    const values = CLI_RUNNER_FALLBACK.map((o) => o.value);
    expect(values.length).toBeGreaterThan(0);
    expect(new Set(values).size).toBe(values.length);
    for (const opt of CLI_RUNNER_FALLBACK) {
      expect(opt.value).toBeTruthy();
      expect(opt.label).toBeTruthy();
    }
  });
});
