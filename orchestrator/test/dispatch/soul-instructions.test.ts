import { describe, expect, it } from "vitest";
import {
  agentForSlug,
  appendAgySoulMount,
} from "../../src/modelRegistry.js";
import {
  AGY_SOUL_RULES_FILE,
  sandboxSoulPath,
  soulFileName,
} from "../../src/soulInstructions.js";

const task = "TASK_SENTINEL";
const commandOptions = (resumeSession?: string) => ({
  prompt: task,
  dangerouslySkipPermissions: false,
  ...(resumeSession !== undefined ? { resumeSession } : {}),
});
const commandFor = (
  slug: string,
  soul: Parameters<typeof agentForSlug>[2],
  pool?: Parameters<typeof agentForSlug>[1],
) => agentForSlug(slug, pool, soul)
  .buildPrintCommand(commandOptions());

describe("real providers load the selected soul outside the task prompt", () => {
  it("Codex places developer_instructions before exec, including resume", () => {
    const agent = agentForSlug("gpt-5.6-terra", undefined, "fixer");
    for (const resumeSession of [undefined, "session-1"]) {
      const command = agent.buildPrintCommand(commandOptions(resumeSession));
      expect(command.command).toContain(
        `-c developer_instructions="$(cat ${sandboxSoulPath("fixer")})"`,
      );
      expect(command.command.indexOf("-c developer_instructions=")).toBeLessThan(
        command.command.indexOf(" exec"),
      );
      expect(command.stdin).toBe(task);
    }
  });

  it("Claude places append-system-prompt-file before its print prompt flags", () => {
    const command = commandFor("opus", "verify");
    expect(command.command).toMatch(
      /^claude --append-system-prompt-file .*verify\.md --print/,
    );
    expect(command.stdin).toBe(task);
  });

  it("Grok places --rules inside the grok subprocess, before wait", () => {
    const command = commandFor("grok-4.5", "READ-ONLY");
    expect(command.command).toContain(
      `--rules "$(cat ${sandboxSoulPath("READ-ONLY")})"`,
    );
    expect(command.command.indexOf("--rules")).toBeLessThan(
      command.command.indexOf(") & grok_pid="),
    );
    expect(command.stdin).toBe(task);
  });

  it("pool rewrite and Agy overlay use the same resolved provider", () => {
    const rewritten = commandFor("gpt-5.6-sol", "fixer", "grok-build");
    expect(rewritten.command).toContain("grok --prompt-file");
    expect(rewritten.command).toContain("--rules");

    const mounts: Array<{
      hostPath: string;
      sandboxPath: string;
      readonly?: boolean;
    }> = [];
    appendAgySoulMount(
      mounts,
      { model: "agy", soul: "landing" },
      undefined,
      "/sentinel/souls",
    );
    expect(mounts).toEqual([{
        hostPath: "/sentinel/souls/landing.md",
        sandboxPath: AGY_SOUL_RULES_FILE,
        readonly: true,
      }]);
    appendAgySoulMount(
      mounts,
      { model: "agy", soul: "landing" },
      "claude",
      "/sentinel/souls",
    );
    expect(mounts).toHaveLength(1);
  });

  it("keeps exceptional soul filenames centralized", () => {
    expect(soulFileName("READ-ONLY")).toBe("reviewer.md");
    expect(soulFileName("merger")).toBe("merger.md");
  });
});
