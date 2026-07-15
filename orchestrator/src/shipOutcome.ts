/**
 * shipOutcome.ts — classify the ship WORKER's `<ship>` tag (#336).
 *
 * The ship step is a WORKER invoking `gstack-ship` (ADR 0026 / PRD #330 R2),
 * replacing the family backend's former inline PR delivery.
 * `gstack-ship` does more than push+PR (base merge / tests / diff review / VERSION
 * / CHANGELOG + STOP/HITL), so the worker's outcome transports delivery cargo or
 * the worker's decision bell.
 *
 * The worker reruns rerun-able failures itself (per the user's note: gstack-ship
 * offers rerun on internal review/test flakes → "有 rerun 自己 rerun" = autonomy);
 * only a GENUINE block (a merge conflict it cannot resolve, a review ASK, a hard
 * defect needing a human decision) is `escalate`. All other clean-exit text is
 * cargo and cannot alter process fate.
 *
 * The family ship worker (RealFamilyBackend) emits this `<ship>` tag.
 */

import { z } from "zod";
import { classifyDecisionGate } from "./receiptRecovery.js";
import { readWorkerOutcomeSidecar } from "./workerOutcomeSidecar.js";
import type { Escalation } from "./types.js";

/**
 * The transported outcome of a cleanly exited ship WORKER (#336). One of:
 *   - `shipped`   — a PR opened (`status:"pr_opened"`, `pr` set) or a push landed
 *     (`status:"pushed"`) — the normal success the consumer routes to S8(success);
 *   - `escalate`  — a genuine block (merge conflict the skill cannot resolve / a
 *     review ASK / a hard defect a human must decide) → the runner's escalate续跑
 *     fork (NOT a rerun-able flake — the worker reruns those itself);
 *   - `completed` — no decision bell and no useful delivery cargo.
 */
export type ShipWorkerOutcome =
  | { readonly kind: "completed" }
  | {
      readonly kind: "shipped";
      readonly branch?: string;
      readonly status: "pushed";
      readonly pr?: never;
    }
  | {
      readonly kind: "shipped";
      readonly branch?: string;
      readonly status: "pr_opened";
      readonly pr: string;
    }
  | {
      readonly kind: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
      readonly escalation?: Escalation;
    };

/**
 * A genuinely non-empty string (rejects `""` and whitespace-only). Mirrors
 * validate.ts `isFilledString`. Used by the downstream delivery-cargo consumer.
 */
export function isFilledString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

/**
 * A genuinely non-empty string at the SCHEMA layer (cmr S336 r3): trimmed,
 * min-length 1 — rejects `""` and whitespace-only delivery cargo.
 */
const nonEmpty = z.string().trim().min(1);

/**
 * Cargo decoding for the non-bell `<ship>` shapes. The independent escalation
 * probe runs first and tolerates every sibling key; these schemas only enrich
 * transported cargo and never decide whether a clean worker process may continue.
 *
 * Mirrors family_ship.md:
 *   1. `{status:"pushed",    branch}`            — shipped, no pr (pr MUST be absent);
 *   2. `{status:"pr_opened", branch, pr}`        — shipped, pr REQUIRED;
 *   3. `{escalate:{reason, diagnosis}}` — a genuine decision bell.
 * Known success fields are non-empty when present. Unknown sibling fields remain
 * cargo.
 */
const pushedSchema = z
  .object({ status: z.literal("pushed"), branch: nonEmpty.optional() })
  .passthrough();
const prOpenedSchema = z
  .object({
    status: z.literal("pr_opened"),
    branch: nonEmpty.optional(),
    pr: nonEmpty,
  })
  .passthrough();

/**
 * Prefer Sandcastle typed decision signal for gates (#899). Machine sidecar is
 * the opaque delivery-cargo channel only — never promotes escalation into fate
 * when typed output is absent (#899). Stdout is telemetry only.
 */
export function shipOutcomeFromResult(result: {
  completionSignal?: string | string[];
  outcomePath?: string;
  stdout: string;
  output?: unknown;
}): ShipWorkerOutcome {
  // Typed Output.object is the sole fate channel for decision gates.
  if (result.output !== undefined) {
    const gate = classifyDecisionGate(result.output, "ship");
    if (gate.kind === "bell") {
      return {
        kind: "escalate",
        reason: gate.reason,
        diagnosis: gate.diagnosis,
      };
    }
    // Signal present with no gate (`{}`): enrich delivery cargo from sidecar only.
    // Do not re-parse escalate from cargo (fourth channel).
    return shipCargoFromSidecar(result.outcomePath);
  }
  // No typed signal: exit code is enough for process success. Sidecar may still
  // enrich delivery cargo (status/pr) but MUST NOT supply escalate (#899).
  return shipCargoFromSidecar(result.outcomePath);
}

function shipCargoFromSidecar(outcomePath: string | undefined): ShipWorkerOutcome {
  try {
    if (outcomePath !== undefined) {
      const sidecar = readWorkerOutcomeSidecar(outcomePath);
      if (sidecar !== undefined) {
        return classifyShipCargoPayload(sidecar);
      }
    }
  } catch {
    // Unreadable sidecar: do not promote stdout delivery or bells into fate.
    return { kind: "completed" };
  }
  return { kind: "completed" };
}

/**
 * Probe a ship worker's `<ship>{…}</ship>` stdout for the independent decision
 * bell, while preserving useful delivery cargo when present. Non-bell parse misses
 * are completed cargo and cannot decide control flow. The shape mirrors family_ship.md:
 *   - `{"status": "pushed",    "branch": string}`              → shipped (no pr);
 *   - `{"status": "pr_opened", "branch": string, "pr": string}`→ shipped (pr REQUIRED);
 *   - `{"escalate": {"reason": string, "diagnosis": string}}`  → escalate;
 * The escalation block is probed before cargo parsing and accepts unknown sibling
 * fields. A cargo parse miss cannot override the clean exit or suppress a bell.
 * Only the LAST `<ship>` tag is read (the worker may iterate / self-rerun).
 *
 * @deprecated Prefer {@link shipOutcomeFromResult}. Stdout is not a fate channel
 * for production ship seats (#820 / #899); kept for unit tests of tag shapes.
 */
export function parseShipOutcome(stdout: string): ShipWorkerOutcome {
  const re = /<ship>([\s\S]*?)<\/ship>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) last = m[1];
  if (last === undefined) {
    return { kind: "completed" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "completed" };
  }
  return classifyShipOutcomePayload(parsed);
}

/** Full classify including decision-gate fate (typed channel / unit tests). */
function classifyShipOutcomePayload(parsed: unknown): ShipWorkerOutcome {
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "completed" };
  }
  // Malformed decision gates fail the Action for #598 — never enter the human
  // loop as empty bells and never silently degrade to completed (#899).
  const gate = classifyDecisionGate(parsed, "ship");
  if (gate.kind === "bell") {
    return {
      kind: "escalate",
      reason: gate.reason,
      diagnosis: gate.diagnosis,
    };
  }
  return classifyShipCargoPayload(parsed);
}

/**
 * Delivery-cargo only: status/pr enrichment. Never promotes escalate into fate
 * (sidecar/stdout fourth-channel ban, #899).
 */
function classifyShipCargoPayload(parsed: unknown): ShipWorkerOutcome {
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "completed" };
  }
  const pushed = pushedSchema.safeParse(parsed);
  if (pushed.success) {
    return {
      kind: "shipped",
      status: "pushed",
      ...(pushed.data.branch !== undefined ? { branch: pushed.data.branch } : {}),
    };
  }
  const prOpened = prOpenedSchema.safeParse(parsed);
  if (prOpened.success) {
    return {
      kind: "shipped",
      status: "pr_opened",
      ...(prOpened.data.branch !== undefined ? { branch: prOpened.data.branch } : {}),
      pr: prOpened.data.pr,
    };
  }
  return { kind: "completed" };
}
