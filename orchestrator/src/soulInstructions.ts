import { join } from "node:path";
import type * as sc from "@ai-hero/sandcastle";
import type { WorkerSoul } from "./types.js";
import { shellEscape } from "./shellEscape.js";

export type { WorkerSoul } from "./types.js";
export const SANDBOX_SOULS_DIR = "/home/agent/.orchestrator/souls";
export const AGY_SOUL_RULES_FILE = "/home/agent/.gemini/GEMINI.md";

const SOUL_FILE: Readonly<Record<WorkerSoul, string>> = {
  coder: "coder.md",
  "READ-ONLY": "reviewer.md",
  "cmr-completeness": "cmr-completeness.md",
  "cmr-correctness": "cmr-correctness.md",
  ship: "ship.md",
  verify: "verify.md",
  fixer: "fixer.md",
  landing: "landing.md",
  merger: "merger.md",
  collector: "collector.md",
};
export const EXECUTABLE_SOUL_FILES: ReadonlyArray<string> = Object.freeze([
  ...new Set(Object.values(SOUL_FILE)),
]);

export function soulFileName(soul: WorkerSoul): string {
  return SOUL_FILE[soul];
}

export function sandboxSoulPath(soul: WorkerSoul): string {
  return join(SANDBOX_SOULS_DIR, soulFileName(soul));
}

export function agySoulRulesMount(soulsDir: string, soul: WorkerSoul) {
  return {
    hostPath: join(soulsDir, soulFileName(soul)),
    sandboxPath: AGY_SOUL_RULES_FILE,
    readonly: true as const,
  };
}

export function withSoulInstructions(
  agent: sc.AgentProvider,
  provider: string,
  soul: WorkerSoul,
): sc.AgentProvider {
  if (provider === "agy" || provider === "grok") return agent;
  const path = sandboxSoulPath(soul);
  return {
    ...agent,
    buildPrintCommand(options) {
      const command = agent.buildPrintCommand(options);
      const suffix =
        provider === "claudeCode"
          ? `--append-system-prompt-file ${shellEscape(path)} `
          : provider === "codex"
            ? `-c developer_instructions="$(cat ${shellEscape(path)})" `
            : "";
      return {
        ...command,
        command: command.command.replace(/^([^ ]+ )/, `$1${suffix}`),
      };
    },
  };
}
