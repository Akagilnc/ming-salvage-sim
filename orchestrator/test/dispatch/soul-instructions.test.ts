import { describe, expect, it } from "vitest";
import type * as sc from "@ai-hero/sandcastle";
import {
  AGY_SOUL_RULES_FILE,
  sandboxSoulPath,
  soulFileName,
  withSoulInstructions,
} from "../../src/soulInstructions.js";

const base: sc.AgentProvider = {
  name: "fake", env: {}, captureSessions: false,
  buildPrintCommand: ({ prompt }) => ({ command: "agent", stdin: prompt }),
  parseStreamLine: () => [],
};

describe("selected soul stays separate from the task prompt", () => {
  it.each([
    ["claudeCode", "--append-system-prompt-file /home/agent/.orchestrator/souls/fixer.md"],
    ["grok", "--rules \"$(cat /home/agent/.orchestrator/souls/fixer.md)\""],
    ["codex", "-c developer_instructions=\"$(cat /home/agent/.orchestrator/souls/fixer.md)\""],
  ])("%s uses its native instruction channel", (provider, expected) => {
    const command = withSoulInstructions(base, provider, "fixer")
      .buildPrintCommand({ prompt: "TASK_SENTINEL" } as never);
    expect(command.command).toContain(expected);
    expect(command.stdin).toBe("TASK_SENTINEL");
  });

  it("agy leaves the task prompt untouched for its GEMINI.md overlay", () => {
    expect(withSoulInstructions(base, "agy", "fixer")
      .buildPrintCommand({ prompt: "TASK_SENTINEL" } as never))
      .toEqual({ command: "agent", stdin: "TASK_SENTINEL" });
    expect(AGY_SOUL_RULES_FILE).toBe("/home/agent/.gemini/GEMINI.md");
  });

  it("keeps exceptional soul filenames centralized", () => {
    expect(soulFileName("READ-ONLY")).toBe("reviewer.md");
    expect(sandboxSoulPath("merger")).toContain("/merger.md");
  });
});
