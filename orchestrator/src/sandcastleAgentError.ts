/**
 * #964 — recognize Sandcastle {@code AgentError} (incl. Effect FiberFailure wrap)
 * so worker-invocation Actions can form typed failure instead of uncaught
 * launcher death.
 *
 * Classification is by tagged name / `_tag` only — never free-log keyword parse
 * (voided #964 signature tripwire; grokAgent stream contract ignores non-JSON).
 */

import { walkErrorChain } from "./receiptRecovery.js";

function nodeLooksLikeAgentError(node: unknown): boolean {
  if (node === null || typeof node !== "object") return false;
  const e = node as { readonly _tag?: unknown; readonly name?: unknown };
  if (e._tag === "AgentError") return true;
  // Bare "AgentError" or Effect FiberFailure display name, e.g. "(FiberFailure) AgentError".
  // Word-boundary regex covers exact equality; no separate exact-eq branch.
  if (typeof e.name === "string" && /\bAgentError\b/.test(e.name)) return true;
  return false;
}

/** True when `err` is (or wraps) a Sandcastle AgentError. */
export function isSandcastleAgentError(err: unknown): boolean {
  for (const node of walkErrorChain(err)) {
    if (nodeLooksLikeAgentError(node)) return true;
  }
  return false;
}

/**
 * Best-effort human message from an AgentError chain (for Action reason strings).
 * Prefers the innermost AgentError message when present.
 */
export function formatSandcastleAgentError(err: unknown): string {
  let lastAgentMessage: string | undefined;
  let lastAnyMessage: string | undefined;
  for (const node of walkErrorChain(err)) {
    if (node instanceof Error && node.message.length > 0) {
      lastAnyMessage = node.message;
      if (nodeLooksLikeAgentError(node)) lastAgentMessage = node.message;
    } else if (
      node !== null &&
      typeof node === "object" &&
      typeof (node as { message?: unknown }).message === "string" &&
      (node as { message: string }).message.length > 0
    ) {
      const msg = (node as { message: string }).message;
      lastAnyMessage = msg;
      if (nodeLooksLikeAgentError(node)) lastAgentMessage = msg;
    }
  }
  return lastAgentMessage ?? lastAnyMessage ?? String(err);
}
