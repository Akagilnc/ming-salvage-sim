/**
 * #684 host-side CLI monitor bridge.
 *
 * Spawned by {@link dispatchMonitoredCliWorker} when a real backend returns a
 * {@link CliMonitorSpawnSpec}. Reconstructs the backend from the job file,
 * runs the existing `dispatchWorker` / `dispatchFamilyWorker` seam (hooks are
 * short-circuited via ORCHESTRATOR_CLI_MONITOR_CHILD), writes the WorkerResult
 * sidecar, and exits non-zero on non-completed outcomes.
 *
 * Invoked as: `node hostCliWorkerRunner.js <jobPath>`
 */

import { readFileSync, writeFileSync } from "node:fs";

import { dispatchWorker } from "./dispatchWorker.js";
import { dispatchFamilyWorker } from "./family/dispatchFamilyWorker.js";
import { RealFamilyBackend } from "./family/realFamilyBackend.js";
import type { RealFamilyBackendOptions } from "./family/realFamilyBackend.js";
import { RealBackend } from "./realBackend.js";
import type { RealBackendOptions } from "./realBackend.js";
import type { CliMonitorJobFile } from "./cliMonitorHooks.js";
import {
  isQuotaWaitForResetError,
  serializeQuotaWaitForResetBridge,
} from "./quotaProbe.js";
import type { WorkerResult } from "./types.js";

async function main(): Promise<void> {
  const jobPath = process.argv[2];
  if (jobPath === undefined || jobPath.length === 0) {
    process.stderr.write(
      "hostCliWorkerRunner: missing job path argument\n",
    );
    process.exit(2);
  }

  let job: CliMonitorJobFile;
  try {
    job = JSON.parse(readFileSync(jobPath, "utf8")) as CliMonitorJobFile;
  } catch (err) {
    process.stderr.write(
      `hostCliWorkerRunner: failed to read job ${jobPath}: ${
        err instanceof Error ? err.message : String(err)
      }\n`,
    );
    process.exit(2);
  }

  let result: WorkerResult;
  try {
    if (job.backendKind === "real") {
      const backend = new RealBackend(job.backendOpts as RealBackendOptions);
      result = await dispatchWorker(
        backend,
        job.spec,
        job.ctx,
        job.landing,
      );
    } else if (job.backendKind === "realFamily") {
      const backend = new RealFamilyBackend(
        job.backendOpts as RealFamilyBackendOptions,
      );
      result = await dispatchFamilyWorker(
        backend,
        job.spec,
        job.ctx,
        job.landing,
      );
    } else {
      result = {
        kind: "failed",
        reason: `hostCliWorkerRunner: unknown backendKind ${String(
          (job as { backendKind?: string }).backendKind,
        )}`,
      };
    }
  } catch (err) {
    // #683: Sandcastle-fallback 429 inside the bridge child must still park —
    // serialize so the parent can re-throw QuotaWaitForResetError (not a bare
    // failed WorkerResult that collapses into errorTermination).
    if (isQuotaWaitForResetError(err)) {
      result = {
        kind: "failed",
        reason: serializeQuotaWaitForResetBridge(err),
      };
    } else {
      result = {
        kind: "failed",
        reason: `hostCliWorkerRunner: worker threw: ${
          err instanceof Error ? err.message : String(err)
        }`,
      };
    }
  }

  try {
    writeFileSync(job.resultPath, `${JSON.stringify(result)}\n`, "utf8");
  } catch (err) {
    process.stderr.write(
      `hostCliWorkerRunner: failed to write result sidecar: ${
        err instanceof Error ? err.message : String(err)
      }\n`,
    );
    process.exit(3);
  }

  // Append completion signal to stdout (merged into monitor log by parent spawn).
  process.stdout.write(`${job.spec.completionSignal}\n`);
  process.exit(result.kind === "completed" ? 0 : 1);
}

main().catch((err) => {
  process.stderr.write(
    `hostCliWorkerRunner: fatal: ${
      err instanceof Error ? err.message : String(err)
    }\n`,
  );
  process.exit(1);
});
