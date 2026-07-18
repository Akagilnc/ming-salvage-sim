/**
 * #964 — recognize Sandcastle {@code AgentError} (incl. Effect FiberFailure wrap)
 * so worker-invocation Actions can form typed failure instead of uncaught
 * launcher death.
 *
 * Classification is by tagged name / `_tag` only — never free-log keyword parse
 * (voided #964 signature tripwire; grokAgent stream contract ignores non-JSON).
 *
 * Single court for ALL Worker Invocation seats (merger + generic workers): convert
 * AgentError → Action-typed failure. Do not fork parallel converters per role.
 */

import { walkErrorChain } from "./receiptRecovery.js";
import { runnerSynthesizedFailureEscalation } from "./runnerEscalation.js";
import type { WorkerResult } from "./types.js";

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

/**
 * #964 Worker Invocation court — map AgentError to Action-typed failure.
 *
 * Uses host-synthesized escalated (same class as missing-auth preflight) so:
 * - mechanical process-root redispatch does NOT re-burn dead credentials
 * - owning Action / verifyCmr treat it as synthesized failure (not decision gate)
 * - no new public cause token
 *
 * Returns `undefined` when `err` is not an AgentError (caller rethrows / handles).
 */
export function workerResultFromAgentError(
  err: unknown,
  seat: string,
): Extract<WorkerResult, { kind: "escalated" }> | undefined {
  if (!isSandcastleAgentError(err)) return undefined;
  const detail = formatSandcastleAgentError(err);
  return {
    kind: "escalated",
    escalation: runnerSynthesizedFailureEscalation({
      reason: `${seat} agent invocation failed: ${detail}`,
      diagnosis:
        "Sandcastle AgentError at Worker Invocation (e.g. mid-run provider auth death); " +
        "owning Action forms typed failure — no process-root redispatch of the same dead credentials",
    }),
  };
}
