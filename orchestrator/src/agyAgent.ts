/**
 * #905 — Sandcastle AgentProvider for the real agy (Antigravity / Gemini) CLI.
 *
 * Historical mis-wires (opencode → grok under the `agy` slug) are forbidden:
 * when this leg is dead (Gemini consumer EOL), optional-leg degrade only —
 * never substitute another vendor's model under the agy name.
 *
 * Invocation contract mirrors `ak-cross-m-review/backends/gemini.sh`:
 *   `agy --sandbox [--model X] --print ''` with the prompt on stdin.
 * NEVER `--dangerously-skip-permissions` (re-consents a high scope and breaks
 * headless auth on the next run).
 */

import type * as sc from "@ai-hero/sandcastle";
import { shellEscape } from "./grokAgent.js";

/** Options for the in-house agy AgentProvider (not a sandcastle export). */
export interface AgyAgentOptions {
  /** Extra env injected by this provider. */
  readonly env?: Record<string, string>;
  /**
   * @deprecated agy sessions are not captured by the orchestrator; ignored.
   * Accepted for compatibility with provider option plumbing.
   */
  readonly captureSessions?: boolean;
}

/**
 * Map plain-text agy stdout lines into sandcastle ParsedStreamEvent.
 * agy print mode is prose, not streaming-json — each non-empty line is text.
 */
export function parseAgyStreamLine(line: string): Array<
  | { type: "text"; text: string }
  | { type: "result"; result: string }
> {
  if (line.length === 0) return [];
  return [
    { type: "text", text: line },
    { type: "result", result: line },
  ];
}

/**
 * Build a sandcastle AgentProvider that runs the real `agy` CLI headless
 * (`--sandbox --print ''` + stdin prompt).
 */
export function agyAgent(
  model: string,
  options?: AgyAgentOptions,
): sc.AgentProvider {
  const trimmedModel = model.trim();
  return {
    name: "agy",
    env: options?.env ?? {},
    captureSessions: false,
    buildPrintCommand({ prompt }) {
      // Ignore dangerouslySkipPermissions: agy hard-forbids that flag.
      const modelFlag = trimmedModel
        ? ` --model ${shellEscape(trimmedModel)}`
        : "";
      return {
        command: `agy --sandbox${modelFlag} --print ''`,
        stdin: prompt,
      };
    },
    buildInteractiveArgs({ prompt }) {
      const args = ["agy", "--sandbox"];
      if (trimmedModel) args.push("--model", trimmedModel);
      if (prompt) args.push("--print", prompt);
      return args;
    },
    parseStreamLine(line) {
      return parseAgyStreamLine(line);
    },
  };
}
