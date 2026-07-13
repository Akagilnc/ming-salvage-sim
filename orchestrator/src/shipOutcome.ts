/**
 * shipOutcome.ts — classify the ship WORKER's `<ship>` tag (#336).
 *
 * The ship step is a WORKER invoking `gstack-ship` (ADR 0026 / PRD #330 R2),
 * replacing the family backend's former inline PR delivery.
 * `gstack-ship` does more than push+PR (base merge / tests / diff review / VERSION
 * / CHANGELOG + STOP/HITL), so the worker's outcome is a discriminated union the
 * full {@link WorkerResult} mapping needs — NOT just success/error.
 *
 * The worker reruns rerun-able failures itself (per the user's note: gstack-ship
 * offers rerun on internal review/test flakes → "有 rerun 自己 rerun" = autonomy);
 * only a GENUINE block (a merge conflict it cannot resolve, a review ASK, a hard
 * defect needing a human decision) is `escalate`. A hard, non-rerun ship/test
 * failure is `failed`. Mirrors #335's `parseCmrOutcome` / `cmrOutcomeFromResult`.
 *
 * The family ship worker (RealFamilyBackend) emits this `<ship>` tag.
 */

import { z } from "zod";
import { readWorkerOutcomeSidecar } from "./workerOutcomeSidecar.js";
import { probeWorkerDecisionBell } from "./workerReceipt.js";

/**
 * The classified outcome of a ship WORKER's run (#336). One of:
 *   - `shipped`   — a PR opened (`status:"pr_opened"`, `pr` set) or a push landed
 *     (`status:"pushed"`) — the normal success the consumer routes to S8(success);
 *   - `escalate`  — a genuine block (merge conflict the skill cannot resolve / a
 *     review ASK / a hard defect a human must decide) → the runner's escalate续跑
 *     fork (NOT a rerun-able flake — the worker reruns those itself);
 *   - `failed`    — a ship command / the tests hard-failed and no rerun cleared it
 *     (the delivery could not complete);
 *   - `malformed` — no parseable `<ship>` tag / no completion signal — the gate must
 *     never read it as a success (fail-closed).
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
    }
  | { readonly kind: "failed"; readonly reason: string; readonly diagnosis: string }
  | { readonly kind: "malformed"; readonly reason: string };

/**
 * A genuinely non-empty string (rejects `""` and whitespace-only). Mirrors
 * validate.ts `isFilledString` — the escalate/failed contract (both prompts) is
 * `{reason: non-empty string, diagnosis: non-empty string}`, so a garbage
 * escalate/failed (`{}`, wrong types, blank strings) is NOT a real verdict and
 * must NOT be coerced into a structured escalate/failed (cmr S336 r2, F2). Also
 * the family consumer's defense-in-depth `pr` belt (realFamilyBackend).
 */
export function isFilledString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

/**
 * A genuinely non-empty string at the SCHEMA layer (cmr S336 r3): trimmed,
 * min-length 1 — rejects `""` and whitespace-only `branch` / `pr` / `reason` /
 * `diagnosis`. Centralizes the `isFilledString` rule into the zod shapes below so
 * the success path can no longer leak a blank branch/pr (the r3 F2 fail-open).
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
 *   3. `{escalate:{reason, diagnosis}}` — a genuine block;
 *   4. `{failed:{reason, diagnosis}}`            — a hard ship/test failure.
 * Known success fields are non-empty when present. Unknown sibling fields remain
 * cargo. The legacy `failed` decoder stays narrow, but failing it has no routing
 * effect after a clean process exit.
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
const failedSchema = z
  .object({ failed: z.object({ reason: nonEmpty, diagnosis: nonEmpty }).strict() })
  .strict();

/**
 * Read the runner-owned machine sidecar for a process that already exited cleanly.
 * `completionSignal` and `stdout` remain in the input shape as worker telemetry,
 * but neither can decide the route (ADR 0062 / #820). The bell is probed across
 * sidecar and stdout independently; everything else is best-effort cargo.
 */
export function shipOutcomeFromResult(result: {
  completionSignal?: string | string[];
  outcomePath?: string;
  stdout: string;
}): ShipWorkerOutcome {
  try {
    if (result.outcomePath !== undefined) {
      const sidecar = readWorkerOutcomeSidecar(result.outcomePath);
      if (sidecar !== undefined) {
        const classified = classifyShipOutcomePayload(sidecar, "ship worker outcome sidecar");
        if (classified.kind === "escalate") return classified;
        const stdoutBell = parseShipOutcome(result.stdout);
        if (stdoutBell.kind === "escalate") return stdoutBell;
        return classified.kind === "shipped" ? classified : { kind: "completed" };
      }
    }
  } catch (err) {
    const stdoutBell = parseShipOutcome(result.stdout);
    return stdoutBell.kind === "escalate" ? stdoutBell : { kind: "completed" };
  }
  const stdoutBell = parseShipOutcome(result.stdout);
  return stdoutBell.kind === "escalate" ? stdoutBell : { kind: "completed" };
}

/**
 * Legacy telemetry parser for a ship worker's `<ship>{…}</ship>` stdout (#336).
 * Production routing no longer calls this function: prose cannot decide control
 * flow under ADR 0062 / #820. Kept pure for historical telemetry decoding. The
 * shape mirrors family_ship.md:
 *   - `{"status": "pushed",    "branch": string}`              → shipped (no pr);
 *   - `{"status": "pr_opened", "branch": string, "pr": string}`→ shipped (pr REQUIRED);
 *   - `{"escalate": {"reason": string, "diagnosis": string}}`  → escalate;
 *   - `{"failed":   {"reason": string, "diagnosis": string}}`  → failed.
 * The escalation block is probed before cargo parsing and accepts unknown sibling
 * fields. Success/failed decoding below is retained for telemetry enrichment only;
 * a cargo parse miss cannot override the clean exit or suppress a bell. Only the
 * LAST `<ship>` tag is read (the worker may iterate / self-rerun).
 */
export function parseShipOutcome(stdout: string): ShipWorkerOutcome {
  const re = /<ship>([\s\S]*?)<\/ship>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) last = m[1];
  if (last === undefined) {
    return { kind: "malformed", reason: "ship worker emitted no <ship> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "ship worker <ship> tag was not valid JSON" };
  }
  return classifyShipOutcomePayload(parsed, "ship worker <ship> tag");
}

function classifyShipOutcomePayload(
  parsed: unknown,
  source: string,
): ShipWorkerOutcome {
  // `JSON.parse` succeeds on bare literals (`null` / `true` / `5`); the strict
  // object schemas below reject every non-object, but guard explicitly so the
  // malformed message stays specific (mirrors parseCmrOutcome / parseMergerOutcome).
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: `${source} was not a JSON object` };
  }
  const decisionBell = probeWorkerDecisionBell(parsed);
  if (decisionBell !== undefined) {
    return {
      kind: "escalate",
      ...decisionBell,
    };
  }
  // Best-effort cargo enrichment after the independent bell probe. A parse miss
  // may reduce cargo richness, but shipOutcomeFromResult never lets it change fate.
  const failed = failedSchema.safeParse(parsed);
  if (failed.success) {
    return { kind: "failed", reason: failed.data.failed.reason, diagnosis: failed.data.failed.diagnosis };
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
  // No strict schema matched → off-contract (unknown status, blank branch/pr, a
  // mixed payload, a garbage escalate/failed, …). Fail-CLOSED: the gate must never
  // read an ambiguous run as a delivery (#336 cmr S336 r1/r2/r3).
  return {
    kind: "malformed",
    reason:
      `${source} matched no valid shape (expected one of: {status:"pushed",branch}, ` +
      '{status:"pr_opened",branch,pr}, {escalate:{reason,diagnosis}}, {failed:{reason,diagnosis}} — ' +
      "non-empty strings, no extra keys)",
  };
}
