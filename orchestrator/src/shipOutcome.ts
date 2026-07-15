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

import { parseLastTaggedJsonSoft } from "./lastTaggedJson.js";
import { classifyDecisionGate } from "./receiptRecovery.js";
import { decodeShipEnvelope } from "./stationReceiptContracts.js";
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
      /**
       * Opaque delivery status token from cargo when present — free-form
       * string, never synthesized. Fate is exit code + typed decision gate
       * only (#899 / ADR 0131).
       */
      readonly status?: string;
      /** Optional delivery cargo — never gates clean exit (#899). */
      readonly pr?: string;
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
 * Prefer Sandcastle typed T2 ship envelope for completion/escalate (#919 D /
 * ADR 0132). Machine sidecar is the opaque delivery-cargo channel only — never
 * promotes escalation into fate when typed output is absent (#899). Stdout is
 * telemetry only. Ordinary status/pr cargo uses tolerant field reads only — no
 * Zod/schema gate and no SO re-ask on cargo shape (PRD #899 / ADR 0131).
 */
export function shipOutcomeFromResult(result: {
  outcomePath?: string;
  stdout: string;
  output?: unknown;
}): ShipWorkerOutcome {
  // Typed Output.object is the sole fate channel for completion / escalate.
  if (result.output !== undefined) {
    // #919 D / CR N1: T2 ship envelope only — no decision-gate dual fallthrough.
    // Production decode miss fails closed for #598 (illegal after SO attach).
    const decoded = decodeShipEnvelope(result.output);
    if (!decoded.ok) {
      throw new Error(
        `ship: illegal ship station receipt: ${decoded.reason}`,
      );
    }
    if (decoded.value.status === "escalate") {
      return {
        kind: "escalate",
        reason: decoded.value.reason,
        diagnosis: decoded.value.diagnosis,
      };
    }
    // completed / shipped traffic: delivery cargo still enriches from sidecar.
    const cargo = shipCargoFromSidecar(result.outcomePath);
    if (decoded.value.status === "shipped") {
      if (cargo.kind === "shipped") return cargo;
      return { kind: "shipped" };
    }
    return cargo;
  }
  // No typed signal: exit code is enough for process success. Sidecar may still
  // enrich delivery cargo (status/pr) but MUST NOT supply escalate (#899).
  // Production ship attaches SO + requireTypedTrafficSignal before this path.
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
  const parsed = parseLastTaggedJsonSoft(stdout, "ship");
  if (parsed === undefined) return { kind: "completed" };
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
 * Delivery-cargo only: opaque sidecar transport. No status enum court, no
 * trim-based discard, no required-sibling gate, no synthesized status —
 * process fate is exit code + typed decision gate only (#899 / ADR 0131).
 * Known delivery fields are copied as-is when present; missing fields stay
 * missing so off-shape cargo never becomes a fourth channel.
 */
function classifyShipCargoPayload(parsed: unknown): ShipWorkerOutcome {
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { kind: "completed" };
  }
  const cargo = parsed as Record<string, unknown>;
  // Opaque transport: no closed status whitelist, no default status. Any
  // string status + optional branch/pr ride through when present.
  const status = typeof cargo.status === "string" ? cargo.status : undefined;
  const branch = typeof cargo.branch === "string" ? cargo.branch : undefined;
  const pr = typeof cargo.pr === "string" ? cargo.pr : undefined;
  if (status === undefined && branch === undefined && pr === undefined) {
    return { kind: "completed" };
  }
  return {
    kind: "shipped",
    ...(status !== undefined ? { status } : {}),
    ...(branch !== undefined ? { branch } : {}),
    ...(pr !== undefined ? { pr } : {}),
  };
}
