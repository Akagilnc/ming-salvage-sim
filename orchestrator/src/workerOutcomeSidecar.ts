import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** Repo-root filename excluded from git for the runner-owned outcome sidecar. */
export const WORKER_OUTCOME_REPO_FILE = ".orchestrator-outcome.json";

/**
 * Worker-visible path for the runner-owned machine outcome sidecar.
 *
 * Sandcastle's Docker provider resolves the sandbox repo directory to
 * /home/agent/workspace. Keep the env var absolute so a worker that has cd'd into
 * a subdirectory still writes and validates the mounted root sidecar.
 */
export const WORKER_OUTCOME_SANDBOX_FILE =
  `/home/agent/workspace/${WORKER_OUTCOME_REPO_FILE}`;

/**
 * Unwrap a ```json … ``` (or bare ``` … ```) fenced code block to its inner
 * payload, mirroring Sandcastle's fence-aware tag extraction.
 */
export function stripJsonFence(s: string): string {
  const fence = /^```(?:json)?\s*\n?([\s\S]*?)\n?```$/;
  const m = fence.exec(s.trim());
  return m ? m[1].trim() : s;
}

function nestedOutcomePath(path: string): string {
  return join(path, "outcome.json");
}

function readableSidecarPath(path: string): string | undefined {
  if (!existsSync(path)) return undefined;
  if (!statSync(path).isDirectory()) return path;
  const nested = nestedOutcomePath(path);
  return existsSync(nested) && !statSync(nested).isDirectory()
    ? nested
    : undefined;
}

/**
 * Read a runner-owned worker outcome sidecar.
 *
 * Missing/blank means "legacy worker did not write the new protocol file yet" and
 * callers may fall back to their old stdout/typed-output path. A non-blank file is
 * the machine protocol truth and must parse as JSON; malformed JSON throws rather
 * than falling back to human-readable stdout.
 */
export function readWorkerOutcomeSidecar(path: string | undefined): unknown | undefined {
  if (path === undefined) return undefined;
  const readPath = readableSidecarPath(path);
  if (readPath === undefined) return undefined;
  const raw = readFileSync(readPath, "utf8").trim();
  if (raw.length === 0) return undefined;
  return JSON.parse(stripJsonFence(raw));
}

/** Read a sidecar that the runner already prepared and mounted for this worker. */
export function readRequiredWorkerOutcomeSidecar(path: string): unknown {
  if (!existsSync(path)) {
    throw new Error("worker outcome sidecar was not written");
  }
  const readPath = readableSidecarPath(path);
  if (readPath === undefined) {
    throw new Error(
      "worker outcome sidecar path was a directory and contained no outcome.json",
    );
  }
  const raw = readFileSync(readPath, "utf8").trim();
  if (raw.length === 0) {
    throw new Error("worker outcome sidecar was blank");
  }
  return JSON.parse(stripJsonFence(raw));
}
