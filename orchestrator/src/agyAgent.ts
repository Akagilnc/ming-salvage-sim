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

type AgyParsedStreamEvent =
  | { type: "text"; text: string }
  | { type: "result"; result: string };

/**
 * Map plain-text agy stdout lines into sandcastle ParsedStreamEvent.
 * agy print mode is prose, not streaming-json — each non-empty line is text.
 *
 * Correctness B1: Sandcastle keeps only the last `{type:"result"}` as the run
 * body (`resultText = parsed.result`). Emitting a per-line result collapses
 * multi-line tags (e.g. `<merger>…</merger>` + `STEP_COMPLETE`) to the final
 * line. A stateful parser re-emits the **accumulated** body on every result so
 * last-wins still retains the full stdout.
 */
export function createAgyStreamParser(): (
  line: string,
) => Array<AgyParsedStreamEvent> {
  let body = "";
  return (line: string): Array<AgyParsedStreamEvent> => {
    if (line.length === 0) return [];
    body = body.length === 0 ? line : `${body}\n${line}`;
    return [
      { type: "text", text: line },
      { type: "result", result: body },
    ];
  };
}

/**
 * Single-line helper (stateless). For multi-line workers use
 * {@link createAgyStreamParser} / {@link agyAgent} so the final result retains
 * the full body under Sandcastle's last-wins result semantics.
 */
export function parseAgyStreamLine(line: string): Array<AgyParsedStreamEvent> {
  return createAgyStreamParser()(line);
}

/**
 * Shared headless agy invocation (gemini.sh contract):
 *   `agy --sandbox [--model X] --print ''` with the prompt on stdin.
 *
 * Single source for {@link agyAgent} and bare-ping smoke — never put the
 * prompt after `--print` (agy 1.0.7 treats the next token as the print value).
 */
/**
 * agy default print timeout is 5m — too short for long family/CMR legs.
 * Correctness C10: pin ≥15m. Value MUST be a Go duration string (`15m`,
 * `900000ms`) — bare milliseconds (`"900000"`) are rejected by the CLI.
 */
export const AGY_PRINT_TIMEOUT = "15m";
/** @deprecated use AGY_PRINT_TIMEOUT (`"15m"`); bare ms numbers break agy CLI. */
export const AGY_PRINT_TIMEOUT_MS = 15 * 60 * 1000;

export function agyPrintInvocation(
  model: string,
  prompt: string,
): { readonly args: readonly string[]; readonly stdin: string } {
  const trimmedModel = model.trim();
  return {
    args: [
      "--sandbox",
      ...(trimmedModel !== "" ? (["--model", trimmedModel] as const) : []),
      // C10: Go duration with unit (agy rejects bare "900000").
      "--print-timeout",
      AGY_PRINT_TIMEOUT,
      "--print",
      "",
    ],
    stdin: prompt,
  };
}

/**
 * Build a sandcastle AgentProvider that runs the real `agy` CLI headless
 * (`--sandbox --print ''` + stdin prompt).
 */
export function agyAgent(
  model: string,
  options?: AgyAgentOptions,
): sc.AgentProvider {
  // One accumulator per agent instance — multi-line stdout must not collapse.
  const parseStreamLine = createAgyStreamParser();
  return {
    name: "agy",
    env: options?.env ?? {},
    captureSessions: false,
    buildPrintCommand({ prompt }) {
      // Ignore dangerouslySkipPermissions: agy hard-forbids that flag.
      const inv = agyPrintInvocation(model, prompt);
      return {
        command: `agy ${inv.args.map(shellEscape).join(" ")}`,
        stdin: inv.stdin,
      };
    },
    buildInteractiveArgs({ prompt }) {
      // Interactive path still uses --print <value> (not the headless empty+stdin form).
      const args = ["agy", "--sandbox"];
      const trimmed = model.trim();
      if (trimmed) args.push("--model", trimmed);
      if (prompt) args.push("--print", prompt);
      return args;
    },
    parseStreamLine,
  };
}
