/**
 * #905 / #915 — Sandcastle AgentProvider for the real agy (Antigravity / Gemini) CLI.
 *
 * Historical mis-wires (opencode → grok under the `agy` slug) are forbidden:
 * when this leg is dead (Gemini consumer EOL), optional-leg degrade only —
 * never substitute another vendor's model under the agy name.
 *
 * ## Invocation class (one contract, two modes)
 *
 * 1. **Headless / print** (workers + bare-ping):  
 *    `agy --sandbox [--model X] --print-timeout 15m --print <prompt>`.  
 *    The token after `--print` MUST be the non-empty prompt. agy 1.1.2
 *    rejects empty `--print` / `--print ''` with "empty prompt" and does
 *    **not** fall through to stdin (#915 accident on #899 ignition).
 *    Never bare `-p`/`--print` without a value (next flag would be swallowed).
 * 2. **Interactive** (Sandcastle TTY; `process.stdin` is the keyboard):  
 *    `agy --sandbox [--model X] --prompt-interactive <seed>`.  
 *    NEVER use `--print <seed>` here — that is print-mode, not interactive.
 *
 * NEVER `--dangerously-skip-permissions` (re-consents a high scope and breaks
 * headless auth on the next run).
 */

import type * as sc from "@ai-hero/sandcastle";
import { shellEscape } from "./shellEscape.js";

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
 *
 * R5-1: one parser instance is only valid for **one** Sandcastle iteration.
 * Call {@link createAgyStreamParser} again (or the agent’s build* reset) at the
 * start of each print/interactive invocation — do not share body across maxIter.
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
 * agy default print timeout is 5m — too short for long family/CMR legs.
 * Correctness C10: pin ≥15m. Value MUST be a Go duration string (`15m`,
 * `900000ms`) — bare milliseconds (`"900000"`) are rejected by the CLI.
 */
export const AGY_PRINT_TIMEOUT = "15m";

/**
 * Headless / print-mode argv (workers + bare-ping; shared seam).
 * Invariant (#915 / agy 1.1.2): the token after `--print` is the prompt
 * itself — never `""`. Empty `--print` is a hard CLI error ("empty prompt");
 * stdin is not consulted for the print body on current agy.
 */
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
      prompt,
    ],
    // Prompt already rides `--print`; keep stdin empty so bare-ping / shell
    // paths do not pretend a second delivery channel exists.
    stdin: "",
  };
}

/**
 * Interactive / TTY argv (Sandcastle `buildInteractiveArgs` — no stdin pipe for
 * the seed; process.stdin is the keyboard).
 * Invariant: never `--print`; seed uses `--prompt-interactive` when non-empty.
 * Leading binary name is `agy` (full argv for interactive exec).
 */
export function agyInteractiveArgs(
  model: string,
  prompt: string,
): readonly string[] {
  const args: string[] = ["agy", "--sandbox"];
  const trimmedModel = model.trim();
  if (trimmedModel !== "") args.push("--model", trimmedModel);
  if (prompt) args.push("--prompt-interactive", prompt);
  return args;
}

/**
 * Build a sandcastle AgentProvider that runs the real `agy` CLI.
 *
 * Both buildPrintCommand and buildInteractiveArgs go through the shared
 * helpers above (class seam — no second copy of print/interactive shape).
 * Stream accumulation is one {@link createAgyStreamParser} per iteration:
 * build* replaces the parser so maxIter cannot leak prior body (R5-1) while
 * multi-line within an iteration still accumulates (B1).
 */
export function agyAgent(
  model: string,
  options?: AgyAgentOptions,
): sc.AgentProvider {
  let parseStreamLine = createAgyStreamParser();
  const resetStreamParser = (): void => {
    parseStreamLine = createAgyStreamParser();
  };
  return {
    name: "agy",
    env: options?.env ?? {},
    captureSessions: false,
    buildPrintCommand({ prompt }) {
      // Ignore dangerouslySkipPermissions: agy hard-forbids that flag.
      resetStreamParser();
      const inv = agyPrintInvocation(model, prompt);
      return {
        command: `agy ${inv.args.map(shellEscape).join(" ")}`,
        stdin: inv.stdin,
      };
    },
    buildInteractiveArgs({ prompt }) {
      resetStreamParser();
      return [...agyInteractiveArgs(model, prompt)];
    },
    parseStreamLine: (line) => parseStreamLine(line),
  };
}
