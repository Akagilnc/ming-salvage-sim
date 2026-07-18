import {
  existsSync,
  mkdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";

/**
 * Precise FS absence predicate (#934 ID-011 / ID-015).
 *
 * ONLY `code === "ENOENT"` is absence. Any other operational FS error
 * (EACCES / EISDIR / EIO / …) must fail closed at the call site — never soft
 * as "missing".
 */
export function isFileNotFound(err: unknown): boolean {
  return (
    err !== null &&
    typeof err === "object" &&
    (err as { code?: unknown }).code === "ENOENT"
  );
}

/**
 * Process exit status on an `execFileSync` / child_process throw (`err.status`),
 * or `undefined` when the error is not an exit-code failure (e.g. ENOENT spawning).
 *
 * Git predicates: exit 1 is often a legitimate negative answer
 * (`rev-parse --verify` missing ref; `merge-base --is-ancestor` not-ancestor);
 * exit 128 / spawn failures are operational and must propagate.
 */
export function gitExitStatus(err: unknown): number | undefined {
  const status = (err as { status?: unknown } | null)?.status;
  return typeof status === "number" ? status : undefined;
}

/**
 * #1012 — docker bind-mount footgun class: host path was auto-created as a
 * *directory* when a missing file was mounted (`-v hostFile:containerFile`).
 * Subsequent host `open()` / `writeFileSync` throw `EISDIR`. Also matches the
 * hostCliWorkerRunner / mechanical-retry reason string form.
 */
export function isEisdirClassHostFsError(err: unknown): boolean {
  if (err !== null && typeof err === "object") {
    if ((err as { code?: unknown }).code === "EISDIR") return true;
  }
  const msg =
    err instanceof Error
      ? err.message
      : typeof err === "string"
        ? err
        : String(err);
  return /\bEISDIR\b/.test(msg);
}

/**
 * #1012 — ensure `path` is a regular file suitable for docker file bind-mount.
 *
 * DELETE-preferring: if a leftover directory occupies the path (docker auto-
 * created placeholder), remove it; if missing, touch an empty file. Existing
 * regular-file content is left untouched (callers overwrite with real payload).
 */
export function ensureRegularFileForBindMount(path: string): void {
  if (existsSync(path)) {
    const st = statSync(path);
    if (st.isFile()) return;
    // Directory (or non-file) at a file path = docker footgun residue / corruption.
    rmSync(path, { recursive: true, force: true });
  } else {
    mkdirSync(dirname(path), { recursive: true });
  }
  if (!existsSync(path)) {
    writeFileSync(path, "", "utf8");
  }
}
