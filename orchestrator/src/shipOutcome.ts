/**
 * shipOutcome.ts — classify the ship WORKER's `<ship>` tag (#336).
 *
 * The ship step is a WORKER invoking `gstack-ship` (ADR 0026 / PRD #330 R2),
 * replacing the inline `RealBackend.push` (single slice) + family `openFamilyPr`.
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
 * Both the single-slice ship worker (RealBackend) and the family ship worker
 * (RealFamilyBackend) emit the SAME `<ship>` tag and reuse this parser.
 */

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
  | {
      readonly kind: "shipped";
      readonly branch: string;
      readonly status: string;
      readonly pr?: string;
    }
  | { readonly kind: "escalate"; readonly reason: string; readonly diagnosis: string }
  | { readonly kind: "failed"; readonly reason: string; readonly diagnosis: string }
  | { readonly kind: "malformed"; readonly reason: string };

/** The ship worker's completion signal (matches prompts/ship.md + family_ship.md). */
export const SHIP_COMPLETION_SIGNAL = "SHIP_STEP_COMPLETE";

/**
 * Decide the ship worker outcome from a Sandcastle run result: gate on the
 * completion signal FIRST (mirrors the cmr / merger gate), then parse the `<ship>`
 * tag. Pure (a check on the run-result shape) so the gate is unit-tested without a
 * container. A complete-but-UNSIGNALED run (e.g. `maxIterations` hit mid-ship) is
 * ESCALATE (the safe direction — the worker did not declare it finished, so its
 * verdict is not trusted as a delivery success).
 */
export function shipOutcomeFromResult(result: {
  completionSignal?: string | string[];
  stdout: string;
}): ShipWorkerOutcome {
  const signal = result.completionSignal;
  const signaled = Array.isArray(signal)
    ? signal.includes(SHIP_COMPLETION_SIGNAL)
    : signal === SHIP_COMPLETION_SIGNAL;
  if (!signaled) {
    const actual =
      signal === undefined
        ? "none (no signal fired before the iteration limit)"
        : `"${String(signal)}"`;
    return {
      kind: "escalate",
      reason: "ship worker did not fire its completion signal",
      diagnosis:
        `expected "${SHIP_COMPLETION_SIGNAL}", got ${actual} (a complete-but-unsignaled ` +
        `ship run is not trusted as a delivery — escalate, never a fabricated PR)`,
    };
  }
  return parseShipOutcome(result.stdout);
}

/**
 * Parse the ship worker's `<ship>{…}</ship>` outcome from its stdout (#336). Pure so
 * it is unit-tested without a container. The shape mirrors prompts/ship.md:
 *   - `{"status": "pr_opened"|"pushed", "branch": string, "pr"?: string}` → shipped;
 *   - `{"escalate": {"reason": string, "diagnosis": string}}`             → escalate;
 *   - `{"failed":   {"reason": string, "diagnosis": string}}`             → failed.
 * Anything else (no tag / invalid JSON / non-object / none of the shapes / a shipped
 * object missing `branch`) → malformed (fail-closed: the gate must never read an
 * ambiguous run as a delivery). Only the LAST `<ship>` tag is read (the worker may
 * iterate / self-rerun).
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
  // `JSON.parse` succeeds on bare literals (`null` / `true` / `5`) — guard so the
  // property reads below cannot throw (mirrors parseCmrOutcome / parseMergerOutcome).
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "ship worker <ship> tag was not a JSON object" };
  }
  const obj = parsed as {
    status?: unknown;
    branch?: unknown;
    pr?: unknown;
    escalate?: { reason?: unknown; diagnosis?: unknown };
    failed?: { reason?: unknown; diagnosis?: unknown };
  };
  // escalate / failed FIRST — a stuck/failed ship never carries a usable status.
  if (obj.escalate !== null && typeof obj.escalate === "object") {
    const reason =
      typeof obj.escalate.reason === "string" ? obj.escalate.reason : "ship worker escalated";
    const diagnosis =
      typeof obj.escalate.diagnosis === "string" ? obj.escalate.diagnosis : reason;
    return { kind: "escalate", reason, diagnosis };
  }
  if (obj.failed !== null && typeof obj.failed === "object") {
    const reason =
      typeof obj.failed.reason === "string" ? obj.failed.reason : "ship worker failed";
    const diagnosis =
      typeof obj.failed.diagnosis === "string" ? obj.failed.diagnosis : reason;
    return { kind: "failed", reason, diagnosis };
  }
  // A successful ship MUST carry a branch (a PR / push with no branch is unusable).
  if (typeof obj.status === "string" && typeof obj.branch === "string") {
    return {
      kind: "shipped",
      branch: obj.branch,
      status: obj.status,
      ...(typeof obj.pr === "string" ? { pr: obj.pr } : {}),
    };
  }
  return {
    kind: "malformed",
    reason:
      "ship worker <ship> tag had no {status,branch} success, no `escalate` and no `failed`",
  };
}
