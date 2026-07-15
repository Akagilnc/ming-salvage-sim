/**
 * Materialise reviewer raw-product pointers into the fixer sandbox cwd so the
 * container can read them (#899). Host monitor log/sidecar paths are not
 * visible inside the worker box; copy readable files next to the worktree and
 * rewrite the landing JSON to sandbox-relative names.
 */

import { copyFileSync, existsSync, statSync } from "node:fs";
import { join } from "node:path";

import type { WorkerLandingPayload } from "./types.js";

/** Sandbox-cwd-relative name for the reviewer's captured stdout log. */
export const RAW_REVIEWER_STDOUT_SANDBOX_FILE = ".orchestrator-raw-reviewer.stdout";
/** Sandbox-cwd-relative name for the reviewer's result sidecar. */
export const RAW_REVIEWER_SIDECAR_SANDBOX_FILE = ".orchestrator-raw-reviewer.sidecar";

export type RawReviewerArtifacts = NonNullable<
  WorkerLandingPayload["rawReviewerArtifacts"]
>;

function isReadableFile(path: string): boolean {
  try {
    return existsSync(path) && statSync(path).isFile();
  } catch {
    return false;
  }
}

/**
 * Copy host-only artifact files into `sandboxCwd` and return pointers whose
 * paths are readable from that cwd (relative basenames). Session id + statement
 * always survive; missing host files are omitted rather than leaving broken
 * absolute host paths for the fixer container.
 */
export function materializeRawReviewerArtifactsForSandbox(
  artifacts: RawReviewerArtifacts,
  sandboxCwd: string,
): RawReviewerArtifacts {
  const out: {
    stdoutPath?: string;
    sidecarPath?: string;
    reviewerSessionId?: string;
    statement: "the previous reviewer raw artifacts are here";
  } = {
    statement: "the previous reviewer raw artifacts are here",
  };
  if (artifacts.reviewerSessionId !== undefined) {
    out.reviewerSessionId = artifacts.reviewerSessionId;
  }
  if (
    artifacts.stdoutPath !== undefined &&
    isReadableFile(artifacts.stdoutPath)
  ) {
    const dest = join(sandboxCwd, RAW_REVIEWER_STDOUT_SANDBOX_FILE);
    copyFileSync(artifacts.stdoutPath, dest);
    out.stdoutPath = RAW_REVIEWER_STDOUT_SANDBOX_FILE;
  }
  if (
    artifacts.sidecarPath !== undefined &&
    isReadableFile(artifacts.sidecarPath)
  ) {
    const dest = join(sandboxCwd, RAW_REVIEWER_SIDECAR_SANDBOX_FILE);
    copyFileSync(artifacts.sidecarPath, dest);
    out.sidecarPath = RAW_REVIEWER_SIDECAR_SANDBOX_FILE;
  }
  return out;
}
