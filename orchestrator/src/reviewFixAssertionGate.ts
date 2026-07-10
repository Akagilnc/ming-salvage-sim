import { execFileSync } from "node:child_process";

import type { ReviewFixRefuseRecord } from "./types.js";

export type { ReviewFixRefuseRecord };

export interface AssertionDiffInput {
  readonly baseToBefore: string;
  readonly beforeToFix: string;
}

export interface ReviewFixDecisionGateInput {
  readonly records: ReadonlyArray<ReviewFixRefuseRecord>;
}

/**
 * Legal refuse outcome for "refuse one finding, fix the others".
 * This is NOT an escalate / decision-gate park — runner stays in the
 * fix → fresh re-review loop.
 */
export interface LegalRefuseOutcome {
  readonly kind: "legal_refuse";
  readonly refusedFindingIdentityKeys: readonly string[];
  readonly records: readonly ReviewFixRefuseRecord[];
}

type DiffLine = { readonly path: string; readonly line: string };

/** Test paths that may hold ratified acceptance pins (not only under test/). */
function isTestPath(path: string): boolean {
  return (
    /(^|\/)test\//.test(path) ||
    /\.(?:test|spec)\.(?:[cm]?[jt]sx?)$/.test(path) ||
    /(^|\/)__tests__\//.test(path)
  );
}

/**
 * Lines whose removal/rewrite is a mechanical signal that a ratified pin may
 * have been weakened: classic asserts, custom assert* helpers, and skip/disable
 * of an existing test shell.
 */
function isPinLine(text: string): boolean {
  return (
    /\bexpect\w*\s*\(/.test(text) ||
    /\bassert\w*\s*(?:\.|\()/.test(text) ||
    /\bto(?:Equal|Be|Throw|Match|StrictEqual|Contain|HaveLength)\s*\(/i.test(
      text,
    ) ||
    /\b(?:it|test|describe)\.skip\b/.test(text) ||
    /\b(?:xit|xtest|xdescribe)\b/.test(text) ||
    // Removing or rewriting an active test declaration can silence pins without
    // touching the expect() line body (it → it.skip, delete whole it block).
    /\b(?:it|test|describe)\s*\(/.test(text)
  );
}

function pinLines(diff: string, prefix: "+" | "-"): DiffLine[] {
  let path = "";
  const lines: DiffLine[] = [];
  for (const line of diff.split(/\r?\n/)) {
    if (line.startsWith("diff --git a/") && line.includes(" b/")) {
      path = line.slice(line.lastIndexOf(" b/") + 3);
    }
    if (line.startsWith("+++ b/")) path = line.slice(6);
    if (!isTestPath(path) || !line.startsWith(prefix)) continue;
    const text = line.slice(1).trim();
    if (isPinLine(text)) {
      lines.push({ path, line: text });
    }
  }
  return lines;
}

/** Mechanical signal only: it never decides whether a fix is acceptable. */
export function preexistingAssertionTouched(input: AssertionDiffInput): boolean {
  const sliceAdded = new Set(
    pinLines(input.baseToBefore, "+").map(({ path, line }) => `${path}\0${line}`),
  );
  return pinLines(input.beforeToFix, "-").some(
    ({ path, line }) => !sliceAdded.has(`${path}\0${line}`),
  );
}

/**
 * Build the legal refuse outcome for coder-fix (issue #677).
 *
 * Prefer another repair. When a finding cannot be fixed without overturning a
 * ratified AC/assertion, refuse that identity key, fix the others, commit, and
 * return this outcome — runner routes to fresh re-review. Never an escalate/park.
 */
export function reviewFixDecisionGate(
  input: ReviewFixDecisionGateInput,
): LegalRefuseOutcome | undefined {
  const records = input.records.filter(
    (r) =>
      r.identityKey.trim().length > 0 &&
      r.finding.trim().length > 0 &&
      r.acceptanceCriterion.trim().length > 0 &&
      r.conflictReason.trim().length > 0,
  );
  if (records.length === 0) return undefined;
  return {
    kind: "legal_refuse",
    refusedFindingIdentityKeys: records.map((r) => r.identityKey),
    records,
  };
}

export function reviewFixAssertionSignal(input: {
  readonly worktreePath: string;
  readonly sliceBase: string;
  readonly beforeFix: string;
  readonly afterFix: string;
}): boolean {
  const diff = (from: string, to: string): string => {
    try {
      return execFileSync(
        "git",
        [
          "-C",
          input.worktreePath,
          "diff",
          "--unified=0",
          from,
          to,
          "--",
          ":(glob)**/test/**",
          ":(glob)**/*.{test,spec}.{ts,tsx,js,jsx,mts,cts,mjs,cjs}",
          ":(glob)**/__tests__/**",
        ],
        {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      throw new Error(
        `reviewFixAssertionSignal: git diff failed (fail-closed): ${detail}`,
      );
    }
  };
  return preexistingAssertionTouched({
    baseToBefore: diff(input.sliceBase, input.beforeFix),
    beforeToFix: diff(input.beforeFix, input.afterFix),
  });
}

// ── CMR ratified-assertion hard-net (executable, no live LLM) ───────────────

export interface RatifiedAssertionFlipFixture {
  /** File path of the flipped assertion. */
  readonly path: string;
  /** Assertion text removed (the ratified pin). */
  readonly removedAssertion: string;
  /** Replacement text that weakens/overturns the pin. */
  readonly addedAssertion: string;
  /**
   * Authority that still pins the removed behavior (issue AC / ADR / prior CMR).
   * Non-empty authority that still requires the old pin ⇒ blocking finding.
   */
  readonly authority: string;
}

export interface RatifiedAssertionHuntFinding {
  readonly severity: "high";
  readonly category: "Correctness";
  readonly claim_quote: string;
  readonly location: string;
  readonly suggested_fix: string;
  readonly action: "fix_now";
}

/**
 * CMR correctness hard-net: a flipped preexisting assertion whose authority
 * still pins the old behavior is a blocking correctness finding (P1 minimum).
 * Pure fixture evaluator — no live LLM (#677 AC / #598 class).
 */
export function cmrBlockingFindingsForRatifiedAssertionFlips(
  flips: ReadonlyArray<RatifiedAssertionFlipFixture>,
): ReadonlyArray<RatifiedAssertionHuntFinding> {
  const findings: RatifiedAssertionHuntFinding[] = [];
  for (const flip of flips) {
    const authority = flip.authority.trim();
    if (authority.length === 0) continue;
    // Authority remains and the change conflicts with the ratified pin.
    if (flip.removedAssertion === flip.addedAssertion) continue;
    findings.push({
      severity: "high",
      category: "Correctness",
      claim_quote:
        `flipped ratified assertion without authority change: ` +
        `${flip.removedAssertion} → ${flip.addedAssertion} ` +
        `(authority still requires: ${authority})`,
      location: flip.path,
      suggested_fix:
        "restore the ratified assertion, or obtain an explicit owner/ADR decision " +
        "before changing the pin",
      action: "fix_now",
    });
  }
  return findings;
}
