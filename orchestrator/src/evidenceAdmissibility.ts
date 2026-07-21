/**
 * Central evidence admissibility gate (#600 round-4).
 *
 * Evidence counts toward convergence ONLY when (a) it is fresh for the current
 * head/round — head SHA match when the artifact carries one, else timestamp on
 * or after the round trigger's UTC second (GitHub comment/reaction times are
 * second-precision) — and (b) its producer completed alive. Failure, fallback,
 * staleness, silence, and synthesis are terminal/escalate states, never green.
 */

import {
  isCanonicalGithubPrUrl,
  isPollableGithubPrUrl,
} from "./botPolling.js";
import type { DispatchContext } from "./types.js";

/** ISO-8601 instant marking when the current review round began (ship or re-trigger). */
export interface RoundTrigger {
  readonly headOid: string;
  readonly triggeredAt: string;
}

export type EvidenceTerminalState =
  | "fresh_live"
  | "stale"
  | "synthetic"
  | "failed"
  | "fallback"
  | "silent";

export interface EvidenceRecord {
  readonly headOid?: string;
  readonly timestamp?: string;
  readonly terminalState: EvidenceTerminalState;
}

export function isOfflineTestPrUrl(prUrl: string): boolean {
  return prUrl.trim().startsWith("pr://");
}

/** True when offline synthesis is explicitly allowed for a test PR handle. */
export function offlineSyntheticPollAdmissible(
  prUrl: string,
  defaultRepo: string,
): boolean {
  const branchCargo = prUrl.trim().startsWith("pr://slice/branch-cargo/");
  const offlineEnabled =
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1";
  if (!offlineEnabled && !branchCargo) {
    return false;
  }
  if (isOfflineTestPrUrl(prUrl)) {
    return !isPollableGithubPrUrl(prUrl, defaultRepo);
  }
  return offlineEnabled && isCanonicalGithubPrUrl(prUrl);
}

/**
 * Review-loop skeleton synthesis is allowed only in the same explicit offline/test
 * handles as synthetic bot polling (`pr://…` or canonical PR URL + offline flag).
 */
export function offlineReviewLoopDispatchAdmissible(
  ctx: Pick<DispatchContext, "prUrl" | "repo">,
  defaultRepo?: string,
): boolean {
  const repo =
    ctx.repo?.trim() ??
    defaultRepo?.trim() ??
    process.env.ORCHESTRATOR_REPO?.trim() ??
    "Akagilnc/ming-salvage-sim";
  const prUrl = ctx.prUrl?.trim() ?? "";
  return offlineSyntheticPollAdmissible(prUrl, repo);
}

/**
 * Refuse offline empty-green synthesis for real GitHub PR URLs outside test mode.
 * Throws so callers fail closed (escalate/error) instead of fabricating convergence.
 */
export function assertOfflineSyntheticPollAdmissible(
  prUrl: string,
  defaultRepo: string,
): void {
  if (offlineSyntheticPollAdmissible(prUrl, defaultRepo)) {
    return;
  }
  if (isPollableGithubPrUrl(prUrl, defaultRepo)) {
    throw new Error(
      `offline review poll inadmissible: synthetic snapshot refused for live GitHub PR ${prUrl}`,
    );
  }
  if (process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1") {
    throw new Error(
      `offline review poll inadmissible: synthetic snapshot refused for non-test PR handle ${prUrl}`,
    );
  }
  throw new Error(
    `offline review poll inadmissible: synthetic snapshot refused for non-admissible PR handle ${prUrl}`,
  );
}

export function buildRoundTrigger(
  headOid: string,
  triggeredAt?: string,
): RoundTrigger {
  return {
    headOid,
    triggeredAt: triggeredAt ?? new Date().toISOString(),
  };
}

/**
 * Head key for family convergence markers and abort/escalation head fields.
 * When any in-loop fix round occurred
 * (`postFixHead` set), key to the post-fix / recheck head; otherwise prefer the
 * ship head. `snapshotHead` / `branchHeadAfter` are family landing fallbacks.
 */
export function convergenceHeadToRecord(input: {
  readonly shipHead?: string;
  readonly snapshotHead?: string;
  readonly postFixHead?: string;
  readonly branchHeadAfter?: string;
}): string | undefined {
  const key =
    input.postFixHead ??
    input.snapshotHead ??
    input.branchHeadAfter ??
    input.shipHead;
  if (key === undefined || key.trim().length === 0) return undefined;
  return key;
}

function parseInstantMs(ts: string): number | undefined {
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? undefined : ms;
}

/** Classify whether a live artifact correlates to the current head/round. */
export function classifyEvidenceFreshness(
  artifact: { readonly headOid?: string; readonly timestamp?: string },
  head: string,
  roundTrigger: RoundTrigger,
): "fresh_live" | "stale" {
  if (artifact.headOid !== undefined) {
    return artifact.headOid === head ? "fresh_live" : "stale";
  }
  if (artifact.timestamp !== undefined) {
    const artifactMs = parseInstantMs(artifact.timestamp);
    const triggerMs = parseInstantMs(roundTrigger.triggeredAt);
    if (artifactMs === undefined || triggerMs === undefined) {
      return "stale";
    }
    // GitHub REST returns second-precision timestamps; round triggers often
    // carry millisecond precision. Floor both to UTC seconds so a post-trigger
    // ACK truncated to the same wall second is not falsely stale (Codex R10 P2).
    // Earlier seconds remain stale — does not admit prior-round evidence.
    const artifactSec = Math.floor(artifactMs / 1000);
    const triggerSec = Math.floor(triggerMs / 1000);
    return artifactSec >= triggerSec ? "fresh_live" : "stale";
  }
  return "stale";
}

export function evidenceAdmissible(
  evidence: EvidenceRecord,
  head: string,
  roundTrigger: RoundTrigger,
): boolean {
  if (evidence.terminalState !== "fresh_live") {
    return false;
  }
  return classifyEvidenceFreshness(evidence, head, roundTrigger) === "fresh_live";
}

export function liveArtifactEvidenceRecord(input: {
  readonly headOid?: string;
  readonly timestamp?: string;
  readonly head: string;
  readonly roundTrigger: RoundTrigger;
}): EvidenceRecord {
  const freshness = classifyEvidenceFreshness(
    { headOid: input.headOid, timestamp: input.timestamp },
    input.head,
    input.roundTrigger,
  );
  return {
    headOid: input.headOid,
    timestamp: input.timestamp,
    terminalState: freshness,
  };
}
