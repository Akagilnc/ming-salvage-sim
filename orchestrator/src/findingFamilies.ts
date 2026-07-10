/**
 * Cross-round finding family synthesis (#711).
 *
 * Verify / integrated-CMR judge workers may emit `findingFamilies` — grouped
 * findings with recurring-class markers. Malformed families degrade to no brief
 * (accelerator, not a gate). The runner forwards sanitized families to fixer
 * workers as `.fix-focus.md` without interpreting them.
 */

import { z } from "zod";

import { fixMarkedKeysFromVerify } from "./onlineReviewSideEffects.js";
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

/**
 * Shape-check and normalize `findingFamilies`. Invalid top-level values or
 * entries are dropped; an empty result becomes `undefined` (no brief).
 */
export function sanitizeFindingFamilies(
  raw: unknown,
): ReadonlyArray<FindingFamily> | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return undefined;
  const families: FindingFamily[] = [];
  for (const entry of raw) {
    const parsed = findingFamilySchema.safeParse(entry);
    if (parsed.success) {
      families.push(parsed.data);
    }
  }
  return families.length > 0 ? families : undefined;
}

export function isFindingFamilyArray(
  value: unknown,
): value is ReadonlyArray<FindingFamily> {
  const sanitized = sanitizeFindingFamilies(value);
  return sanitized !== undefined && sanitized.length === (value as unknown[]).length;
}

/** Runner-owned markdown param file — mechanical serialization, no judgment. */
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
  return (
    "# Fix focus — pattern-level briefs (#711)\n\n" +
    "When present, run same-type sweeps per family (not per isolated finding).\n\n" +
    sections.join("\n")
  );
}

/** Prior S9 verify rounds for the current online-review round (1-based). */
export function priorOnlineReviewFindingsFromLedger(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly output?: StepOutput;
  }>,
  currentRound: number,
): ReadonlyArray<PriorRoundFindingSnapshot> {
  if (currentRound <= 1) return [];
  const priorCount = currentRound - 1;
  const s9Outputs: VerifyResult[] = [];
  for (const entry of ledger) {
    if (entry.step === "S9" && entry.output?.kind === "verify") {
      s9Outputs.push(entry.output);
    }
  }
  return s9Outputs.slice(0, priorCount).map((verify, index) => ({
    round: index + 1,
    fixMarkedFindingIdentityKeys: fixMarkedKeysFromVerify(verify),
    ...(verify.findingDispositions !== undefined
      ? { findingDispositions: verify.findingDispositions }
      : {}),
  }));
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
    if (entry.output?.kind === "cmr" && entry.output.findings !== undefined) {
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