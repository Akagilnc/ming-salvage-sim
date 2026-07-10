/**
 * Cross-round finding family synthesis (#711).
 *
 * Verify / integrated-CMR judge workers may emit `findingFamilies` (or wire
 * alias `finding_families`) — grouped findings with recurring-class markers.
 * Malformed families degrade to no brief (accelerator, not a gate). The runner
 * forwards sanitized families to fixer workers as `.fix-focus.md` without
 * interpreting them — pure data serialization only.
 */

import { z } from "zod";

import { fixMarkedKeysFromVerify } from "./onlineReviewSideEffects.js";
import { fixerLedgerOutputProceeds } from "./reviewLoopOutcome.js";
import type {
  Finding,
  FindingFamily,
  PriorRoundFindingSnapshot,
  StepOutput,
  VerifyResult,
} from "./types.js";
import { findingIdentityKey } from "./findings.js";

export type { FindingFamily, PriorRoundFindingSnapshot } from "./types.js";

export const FIX_FOCUS_LANDING_FILE = ".fix-focus.md";

const findingFamilySchema = z
  .object({
    family: z.string().min(1),
    members: z.array(z.string().min(1)).min(1),
    recurringFromRounds: z.array(z.number().int().positive()),
    brief: z.string().min(1),
  })
  .strict();

function isJsonRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Normalize one family entry from snake_case wire aliases to camelCase. */
export function normalizeFindingFamilyEntry(entry: unknown): unknown {
  if (!isJsonRecord(entry)) return entry;
  const out: Record<string, unknown> = { ...entry };
  if (
    out.recurringFromRounds === undefined &&
    out.recurring_from_rounds !== undefined
  ) {
    out.recurringFromRounds = out.recurring_from_rounds;
    delete out.recurring_from_rounds;
  }
  return out;
}

/**
 * Normalize top-level + nested finding-family wire aliases so both
 * `finding_families` / `recurring_from_rounds` (spec) and camelCase work.
 * Extra/snake keys are rewritten before `.strict()` schemas run.
 */
export function normalizeFindingFamiliesWireAliases(raw: unknown): unknown {
  if (!isJsonRecord(raw)) return raw;
  const out: Record<string, unknown> = { ...raw };
  // Both wire spellings are ambiguous.  Drop the accelerator entirely before
  // the strict verdict schema sees the duplicate key; a malformed brief must
  // never reject an otherwise usable verify verdict.
  if (out.findingFamilies !== undefined && out.finding_families !== undefined) {
    delete out.findingFamilies;
    delete out.finding_families;
  }
  if (out.findingFamilies === undefined && out.finding_families !== undefined) {
    out.findingFamilies = out.finding_families;
    delete out.finding_families;
  }
  if (Array.isArray(out.findingFamilies)) {
    out.findingFamilies = out.findingFamilies.map(normalizeFindingFamilyEntry);
  }
  return out;
}

/**
 * Shape-check and normalize `findingFamilies`. Invalid top-level values or
 * entries are dropped; an empty result becomes `undefined` (no brief).
 * Accepts snake_case wire fields (`recurring_from_rounds`).
 */
export function sanitizeFindingFamilies(
  raw: unknown,
): ReadonlyArray<FindingFamily> | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return undefined;
  const families: FindingFamily[] = [];
  for (const entry of raw) {
    const parsed = findingFamilySchema.safeParse(
      normalizeFindingFamilyEntry(entry),
    );
    if (parsed.success) {
      families.push(parsed.data);
    }
  }
  return families.length > 0 ? families : undefined;
}

export function isFindingFamilyArray(
  value: unknown,
): value is ReadonlyArray<FindingFamily> {
  return (
    Array.isArray(value) &&
    value.every((entry) => findingFamilySchema.safeParse(entry).success)
  );
}

/**
 * Runner-owned markdown param file — mechanical serialization of family data
 * only. Method instructions live in versioned fixer/coder-fix souls.
 */
export function formatFixFocusMarkdown(
  families: ReadonlyArray<FindingFamily>,
): string {
  const sections = families.map((family) => {
    const members = family.members.join(", ");
    const rounds =
      family.recurringFromRounds.length > 0
        ? family.recurringFromRounds.join(", ")
        : "(none)";
    return [
      `## ${family.family}`,
      "",
      `- Members: ${members}`,
      `- Recurring from rounds: ${rounds}`,
      `- Brief: ${family.brief}`,
      "",
    ].join("\n");
  });
  return "# Fix focus — pattern-level briefs (#711)\n\n" + sections.join("\n");
}

/**
 * Merge prior-round snapshots from multiple sources by round number.
 * Later sources win for the same round (e.g. in-process over ledger).
 */
export function mergePriorRoundFindings(
  ...sources: ReadonlyArray<ReadonlyArray<PriorRoundFindingSnapshot>>
): ReadonlyArray<PriorRoundFindingSnapshot> {
  const byRound = new Map<number, PriorRoundFindingSnapshot>();
  for (const source of sources) {
    for (const snap of source) {
      byRound.set(snap.round, {
        round: snap.round,
        fixMarkedFindingIdentityKeys: [...snap.fixMarkedFindingIdentityKeys],
        ...(snap.findingDispositions !== undefined
          ? { findingDispositions: snap.findingDispositions }
          : {}),
        ...(snap.blockingFindingIdentityKeys !== undefined
          ? {
              blockingFindingIdentityKeys: [
                ...snap.blockingFindingIdentityKeys,
              ],
            }
          : {}),
      });
    }
  }
  return [...byRound.values()].sort((a, b) => a.round - b.round);
}

/**
 * Prior S9 verify rounds for the current online-review round (1-based).
 *
 * Key by logical round, not array position. CI-pending timeouts persist extra
 * S9 verify rows without incrementing the round (runner.ts), so position-based
 * `slice(0, priorCount)` would keep stale pending rows and drop later real
 * fix-marked findings. Prefer non-empty fix keys when a later empty pending
 * re-poll would overwrite.
 */
export function priorOnlineReviewFindingsFromLedger(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly output?: StepOutput;
    readonly onlineReviewRound?: number;
  }>,
  currentRound: number,
): ReadonlyArray<PriorRoundFindingSnapshot> {
  if (currentRound <= 1) return [];
  const byRound = new Map<number, PriorRoundFindingSnapshot>();
  let inferredRound = 1;

  for (const entry of ledger) {
    if (entry.step === "S10" && fixerLedgerOutputProceeds(entry.output)) {
      inferredRound += 1;
      continue;
    }
    if (entry.step !== "S9" || entry.output?.kind !== "verify") {
      continue;
    }
    const verify = entry.output;
    const round =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
        ? entry.onlineReviewRound
        : inferredRound;
    if (round >= currentRound) continue;

    const keys = fixMarkedKeysFromVerify(verify);
    const existing = byRound.get(round);
    // Empty pending re-poll must not erase a prior non-empty snapshot for the
    // same round; a later non-empty re-verify may still overwrite.
    if (
      existing !== undefined &&
      keys.length === 0 &&
      existing.fixMarkedFindingIdentityKeys.length > 0
    ) {
      continue;
    }
    byRound.set(round, {
      round,
      fixMarkedFindingIdentityKeys: keys,
      ...(verify.findingDispositions !== undefined
        ? { findingDispositions: verify.findingDispositions }
        : {}),
    });
  }

  return [...byRound.values()]
    .filter((s) => s.round < currentRound)
    .sort((a, b) => a.round - b.round);
}

type FamilyOnlineReviewLedgerEntry = {
  readonly event?: string;
  readonly onlineReviewRound?: number;
  readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
};

/**
 * Prior online-review rounds from the family ledger (#711).
 *
 * Family loop only persists fix/retrigger markers (not S9 verify outputs).
 * Prefer `online_review_fix_committed` rows that carry
 * `fixMarkedFindingIdentityKeys` + `onlineReviewRound`.
 */
export function priorOnlineReviewFindingsFromFamilyLedger(
  ledger: ReadonlyArray<FamilyOnlineReviewLedgerEntry>,
  currentRound: number,
): ReadonlyArray<PriorRoundFindingSnapshot> {
  if (currentRound <= 1) return [];
  const byRound = new Map<number, PriorRoundFindingSnapshot>();
  for (const entry of ledger) {
    if (entry.event !== "online_review_fix_committed") continue;
    const keys = entry.fixMarkedFindingIdentityKeys;
    if (!Array.isArray(keys) || keys.length === 0) continue;
    const round =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
        ? entry.onlineReviewRound
        : undefined;
    if (round === undefined || round >= currentRound) continue;
    byRound.set(round, {
      round,
      fixMarkedFindingIdentityKeys: [...keys],
    });
  }
  return [...byRound.values()].sort((a, b) => a.round - b.round);
}

type CmrLedgerEntry = {
  readonly event?: string;
  readonly cmrPass?: string;
  readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
  readonly output?: { readonly kind?: string; readonly findings?: ReadonlyArray<Finding> };
};

/** Prior integrated-CMR blocking rounds from the family ledger (#711). */
export function priorCmrFindingsFromFamilyLedger(
  ledger: ReadonlyArray<CmrLedgerEntry>,
  cmrPass: "completeness" | "correctness",
): ReadonlyArray<PriorRoundFindingSnapshot> {
  const snapshots: PriorRoundFindingSnapshot[] = [];
  let round = 1;
  for (const entry of ledger) {
    if (
      entry.event === "cmr_reviewed" &&
      entry.cmrPass === cmrPass &&
      entry.blockingFindingIdentityKeys !== undefined &&
      entry.blockingFindingIdentityKeys.length > 0
    ) {
      snapshots.push({
        round,
        fixMarkedFindingIdentityKeys: [],
        blockingFindingIdentityKeys: [...entry.blockingFindingIdentityKeys],
      });
      round += 1;
    }
    if (
      entry.cmrPass === cmrPass &&
      entry.output?.kind === "cmr" &&
      entry.output.findings !== undefined
    ) {
      const blocking = entry.output.findings
        .filter((f) => f.action === "fix_now")
        .map((f) => findingIdentityKey(f));
      if (blocking.length > 0) {
        snapshots.push({
          round,
          fixMarkedFindingIdentityKeys: [],
          blockingFindingIdentityKeys: blocking,
        });
        round += 1;
      }
    }
  }
  return snapshots;
}

export function attachSanitizedFindingFamilies<
  T extends Record<string, unknown>,
>(parsed: T, rawFamilies: unknown): T & { findingFamilies?: ReadonlyArray<FindingFamily> } {
  const findingFamilies = sanitizeFindingFamilies(rawFamilies);
  return findingFamilies !== undefined ? { ...parsed, findingFamilies } : parsed;
}
