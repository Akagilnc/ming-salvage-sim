/**
 * #1145 host mount/copy helper for the worker-owned online-review durable store
 * (DecisionGate A).
 *
 * Sole store: `{workingRepo}/.orchestrator-online-review-durable/`
 * Host may only ensure dir + RW-mount + ship bin.mjs — never parse/classify.
 * Workers call the shipped bin.mjs for progress/receipts/blobs.
 */

import {
  copyFileSync,
  existsSync,
  mkdirSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { ensureGitInfoExclude } from "../gitInfoExclude.js";

// ─── Paths / env (sole names) ─────────────────────────────────────────

/** Host + sandbox relative directory name (sole durable store). */
export const ONLINE_REVIEW_DURABLE_DIR = ".orchestrator-online-review-durable";

/** Env pointing at the mounted durable root inside the sandbox. */
export const ONLINE_REVIEW_DURABLE_PATH_ENV =
  "ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH";

/** Sandbox mount / env value (relative to worker workdir). */
export const ONLINE_REVIEW_DURABLE_SANDBOX_PATH = ONLINE_REVIEW_DURABLE_DIR;

const BLOBS_DIR = "blobs";
const BIN_NAME = "bin.mjs";

function bundledBinSourcePath(): string {
  // Prefer scripts/ next to package root (src/family → ../../scripts).
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, "..", "..", "scripts", "online-review-durable-bin.mjs");
}

/**
 * Host-only: mkdir store, ship bin.mjs, git-exclude.
 * Must not read/parse state.jsonl.
 */
export function ensureOnlineReviewDurableDir(workingRepo: string): {
  readonly hostPath: string;
  readonly sandboxPath: string;
} {
  const hostPath = join(workingRepo, ONLINE_REVIEW_DURABLE_DIR);
  mkdirSync(join(hostPath, BLOBS_DIR), { recursive: true });
  const binSrc = bundledBinSourcePath();
  const binDest = join(hostPath, BIN_NAME);
  if (!existsSync(binSrc)) {
    throw new Error(
      `online-review durable bin source missing: ${binSrc}`,
    );
  }
  copyFileSync(binSrc, binDest);
  ensureGitInfoExclude(workingRepo, ONLINE_REVIEW_DURABLE_DIR);
  ensureGitInfoExclude(workingRepo, `${ONLINE_REVIEW_DURABLE_DIR}/`);
  return {
    hostPath,
    sandboxPath: ONLINE_REVIEW_DURABLE_SANDBOX_PATH,
  };
}

/** Mount descriptor for familyReviewLoopSandboxConfig (RW). */
export function onlineReviewDurableMount(workingRepo: string): {
  readonly hostPath: string;
  readonly sandboxPath: string;
  readonly readonly?: boolean;
} {
  const ensured = ensureOnlineReviewDurableDir(workingRepo);
  return {
    hostPath: ensured.hostPath,
    sandboxPath: ensured.sandboxPath,
    // RW — workers append state / blobs
  };
}
