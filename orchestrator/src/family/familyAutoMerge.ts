/**
 * Family-path auto-merge after review-loop convergence (#602).
 *
 * Shared by verifyCmr (fresh final barrier) and the family spine resume guard
 * (review_loop_converged without pr_merged).
 */

import { execFileSync } from "node:child_process";

import {
  docReleasePathsFromCommit,
  runAutoMergeStage,
  type AutoMergeStageResult,
} from "../autoMerge.js";
import { isLiveGithubReviewPollEnabled, pollPrReviewState } from "../botPolling.js";
import { buildRoundTrigger } from "../evidenceAdmissibility.js";
import { offlinePrReviewSnapshot } from "../onlineReviewLoop.js";
import { familyPrMergedForHead, recordPrMerged } from "./ledger.js";
import type { FamilyBackend } from "./types.js";

export interface FamilyAutoMergeInput {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly convergedHeadOid: string;
  readonly prUrl: string;
}

function familyGhSh(): (file: string, args: string[]) => string {
  return (file, args) =>
    execFileSync(file, args, {
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    }).trim();
}

function resolveFamilyDocReleasePaths(
  familyBackend: FamilyBackend,
  convergedHeadOid: string,
): readonly string[] | undefined {
  const repoPath = familyBackend.resolveFamilyWorkingRepo?.();
  return docReleasePathsFromCommit(repoPath, convergedHeadOid);
}

/** True when auto-merge did not reach a terminal success state. */
export function familyAutoMergeIncomplete(result: AutoMergeStageResult): boolean {
  if (!result.ok) return true;
  if (result.terminalState === "already_recorded") return false;
  if (result.terminalState === "merged") return result.record === undefined;
  return true;
}

/**
 * Run host-side PR auto-merge for a converged family head and record `pr_merged`
 * when merge is confirmed (or backfilled from live MERGED state).
 */
export async function runFamilyAutoMergeStage(
  input: FamilyAutoMergeInput,
): Promise<AutoMergeStageResult> {
  const familyRepo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const shipPr = input.prUrl.trim();
  if (shipPr.length === 0) {
    return {
      ok: false,
      terminalState: "decision_gate",
    };
  }

  const familyLedger = await input.familyBackend.readFamilyLedger();
  const priorPrMerged = familyPrMergedForHead(
    familyLedger,
    input.convergedHeadOid,
  );
  const docReleasePaths = resolveFamilyDocReleasePaths(
    input.familyBackend,
    input.convergedHeadOid,
  );
  const ghSh = familyGhSh();
  const autoMerge = await runAutoMergeStage({
    sh: ghSh,
    repo: familyRepo,
    prUrl: shipPr,
    convergedHeadOid: input.convergedHeadOid,
    docReleaseCompleted: true,
    priorConvergenceRecorded: true,
    prMergedMarkerPresent: priorPrMerged !== undefined,
    offlineSynthetic: !isLiveGithubReviewPollEnabled(shipPr, familyRepo),
    ...(docReleasePaths !== undefined ? { docReleasePaths } : {}),
    poll: async (round) => {
      if (isLiveGithubReviewPollEnabled(shipPr, familyRepo)) {
        return pollPrReviewState(ghSh, {
          repo: familyRepo,
          prUrl: shipPr,
          pollCount: round,
          roundTrigger: buildRoundTrigger(input.convergedHeadOid),
        });
      }
      return offlinePrReviewSnapshot({
        repo: familyRepo,
        prUrl: shipPr,
        headOid: input.convergedHeadOid,
        pollCount: round,
      });
    },
  });

  if (autoMerge.terminalState === "merged" && autoMerge.record !== undefined) {
    await recordPrMerged(input.familyBackend, {
      pr: shipPr,
      prNumber: autoMerge.record.prNumber,
      remoteBranchName: autoMerge.record.remoteBranchName,
      mergedHeadOid: autoMerge.record.mergedHeadOid,
      familyHeadAfter: input.convergedHeadOid,
    });
  }

  return autoMerge;
}
