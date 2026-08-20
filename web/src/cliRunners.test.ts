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

  it("fallback includes grok/cursor/kimi (anchor _CLI_BACKENDS)", () => {
    const values = CLI_RUNNER_FALLBACK.map((o) => o.value);
    expect(values).toContain("grok");
    expect(values).toContain("cursor");
    expect(values).toContain("kimi");
    expect(values).toContain("agy");
  });
});
