/**
 * #807 — Sandcastle AgentProvider for the real SuperGrok / grok-build CLI.
 *
 * sandcastle's built-in `sc.pi()` targets a different product (`pi -p --mode json
 * …`, sessions under `~/.pi/`). Owner ruled (#807) that the grok-build pool's
 * executable is the existing `grok` CLI (`~/.grok/auth.json`, `grok -p …`).
 *
 * Sandcastle still exposes the pluggable {@link sc.AgentProvider} seam consumed
 * by `sc.run({ agent })`, so we implement that interface rather than pretending
 * `sc.pi` matches the grok CLI contract.
 */

import type * as sc from "@ai-hero/sandcastle";
import { shellEscape } from "./shellEscape.js";
import {
  makeGrokSessionStorage,
  type GrokSessionStorageOptions,
} from "./grokSessionStorage.js";

export { shellEscape } from "./shellEscape.js";

/** Options for the in-house grok AgentProvider (not a sandcastle export). */
export interface GrokAgentOptions {
  /** Maps to `grok --reasoning-effort`. */
  readonly effort?:
    | "none"
    | "minimal"
    | "low"
    | "medium"
    | "high"
    | "xhigh"
    | "max";
  /** Extra env injected by this provider. */
  readonly env?: Record<string, string>;
  /** When false, session capture is disabled. Default: true (#955). */
  readonly captureSessions?: boolean;
  /** Override grok session directories for tests or non-standard installs. */
  readonly sessionStorage?: GrokSessionStorageOptions;
}

/**
 * Stateful mapper from grok headless `streaming-json` lines to sandcastle
 * ParsedStreamEvent.
 *
 * Documented event shapes (host probe 2026-07-11; stream shape stable through
 * the #964 pin @xai-official/grok@0.2.102):
 *   {"type":"text","data":"…"}
 *   {"type":"thought","data":"…"}
 *   {"type":"end","stopReason":"…","sessionId":"…"}
 *
 * Headless streaming-json does NOT emit tool_call events even when tools run
 * (probe: echo OK via bash succeeded; stream only showed thought/text/end).
 *
 * `result` semantics (#899 hotfix, 2026-07-15; #928 exit+sidecar): sandcastle
 * keeps only the LAST result event's payload as the iteration's
 * `result`/`stdout` — that is what typed-envelope / sidecar receipt extraction
 * reads after clean exit. Grok emits text in per-message chunks, so mapping
 * every chunk to a result event made that a last-chunk roulette: on #899 the
 * coder's receipt lived in earlier chunks and escalate cargo degraded to
 * committed:false. Chunks now emit text events only and accumulate; the
 * single result event is emitted on `end` with the full turn (codex parity,
 * whose CLI emits one final result record natively). Liveness is heartbeat /
 * log growth only — not a password string in the stream. Non-JSON lines are
 * ignored (no auth/device-code keyword tripwire — #964).
 */
export function createGrokStreamParser(): (line: string) => Array<
  | { type: "text"; text: string }
  | { type: "result"; result: string }
  | { type: "tool_call"; name: string; args: string }
  | { type: "session_id"; sessionId: string }
> {
  let accumulated = "";
  return (line) => {
  const trimmed = line.trim();
  if (!trimmed.startsWith("{")) return [];
  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;
    const type = obj.type;
    if (type === "text" && typeof obj.data === "string") {
      accumulated += obj.data;
      return [{ type: "text", text: obj.data }];
    }
    if (type === "end") {
      const events: Array<
        | { type: "session_id"; sessionId: string }
        | { type: "result"; result: string }
      > = [];
      if (typeof obj.sessionId === "string") {
        events.push({ type: "session_id", sessionId: obj.sessionId });
      }
      // The accumulated turn is the result; an end event's own embedded text
      // is only a fallback for streams that never chunked any text.
      const turn =
        accumulated.length > 0
          ? accumulated
          : typeof obj.text === "string"
            ? obj.text
            : "";
      accumulated = "";
      if (turn.length > 0) {
        events.push({ type: "result", result: turn });
      }
      return events;
    }
    // Defensive: if a future grok build starts emitting tool events, surface them.
    // Tool id for bash is `run_terminal_cmd` (README); map to `bash` so the
    // existing route-smoke observer (`/^(bash|shell)$/i`) accepts it.
    if (type === "tool_call" || type === "tool_use" || type === "tool") {
      const rawName =
        (typeof obj.name === "string" && obj.name) ||
        (typeof obj.tool === "string" && obj.tool) ||
        (typeof obj.toolName === "string" && obj.toolName) ||
        "";
      if (!rawName) return [];
      const name =
        rawName === "run_terminal_cmd" || rawName === "Bash" ? "bash" : rawName;
      const args =
        typeof obj.args === "string"
          ? obj.args
          : typeof obj.command === "string"
            ? obj.command
            : obj.input !== undefined
              ? JSON.stringify(obj.input)
              : "";
      return [{ type: "tool_call", name, args }];
    }
  } catch {
    // Non-JSON line — ignore (same as other sandcastle providers).
  }
  return [];
  };
}

/**
 * Build a sandcastle AgentProvider that runs the real `grok` CLI in headless
 * mode (stdin materialized to a temporary `--prompt-file` + streaming-json +
 * always-approve).
 */
export function grokAgent(
  model: string,
  options?: GrokAgentOptions,
): sc.AgentProvider {
  return {
    name: "grok",
    env: options?.env ?? {},
    // #955: grok sessions are directories under ~/.grok/sessions; capture and
    // resume ride the sandcastle sessionStorage contract below.
    captureSessions: options?.captureSessions !== false,
    sessionStorage: makeGrokSessionStorage(options?.sessionStorage),
    buildPrintCommand({ prompt, resumeSession, forkSession }) {
      const modelFlag = model ? ` -m ${shellEscape(model)}` : "";
      const effortFlag = options?.effort
        ? ` --reasoning-effort ${shellEscape(options.effort)}`
        : "";
      // #955: grok natively supports `--resume <id>` (+ `--fork-session`).
      const resumeFlag = resumeSession
        ? ` --resume ${shellEscape(resumeSession)}`
        : "";
      const forkFlag = resumeSession && forkSession ? " --fork-session" : "";
      // Sandcastle supplies prompts through a Node child-process pipe. Grok
      // reopens --prompt-file itself, and reopening /dev/stdin fails with ENXIO
      // for that pipe shape. Materialize stdin into a private mode-600 temporary
      // file so large prompts still avoid the Linux argv limit and Grok reads a
      // regular file. EXIT owns normal/auth-failure cleanup; explicit signal
      // handlers clean before re-raising the original signal so worker
      // interruption cannot strand a full-context prompt file or turn into a
      // successful exit.
      // Headless-only:
      // never `grok login` / device-auth (#964). Auth death is the CLI's native
      // non-interactive fail ("Not signed in" on pin ≥0.2.102) → AgentError →
      // owning Action typed failure (not an interactive wait).
      return {
        command:
          `prompt_file=$(mktemp); chmod 600 "$prompt_file"; ` +
          `cleanup_prompt() { rm -f "$prompt_file"; }; ` +
          `relay_signal() { signal="$1"; trap - EXIT HUP INT TERM; ` +
          `if [ -n "$grok_pid" ]; then kill -s "$signal" "$grok_pid" 2>/dev/null; wait "$grok_pid" 2>/dev/null; fi; ` +
          `cleanup_prompt; kill -s "$signal" "$$"; }; ` +
          `trap cleanup_prompt EXIT; ` +
          `trap 'relay_signal HUP' HUP; trap 'relay_signal INT' INT; trap 'relay_signal TERM' TERM; ` +
          `cat > "$prompt_file"; ` +
          `(exec env --default-signal=HUP,INT,TERM grok --prompt-file "$prompt_file" --output-format streaming-json` +
          ` --always-approve --permission-mode bypassPermissions` +
          `${modelFlag}${effortFlag}${resumeFlag}${forkFlag}) & ` +
          `grok_pid=$!; wait "$grok_pid"`,
        stdin: prompt,
      };
    },
    buildInteractiveArgs({ prompt }) {
      const args = ["grok", "--model", model, "--always-approve"];
      if (prompt) args.push(prompt);
      return args;
    },
    // Per-provider accumulator: each dispatch builds its own provider via
    // agentForSlug, so turns never bleed across concurrent workers.
    parseStreamLine: createGrokStreamParser(),
  };
}
