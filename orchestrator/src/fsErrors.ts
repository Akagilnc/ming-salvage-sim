import {
  closeSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  rmSync,
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
 * #1012 / #1017 — ensure `path` is a regular file suitable for docker file
 * bind-mount.
 *
 * DELETE-preferring: leftover directory (docker auto-created placeholder) is
 * removed; missing path is touched empty. Existing regular-file content is
 * left untouched (callers overwrite with real payload).
 *
 * Fail-closed on symlinks (`lstat` — never follow): a swapped symlink must not
 * redirect bind-mount writes. Create uses `O_EXCL` so a TOCTOU symlink land
 * cannot open the target through us.
 */
export function ensureRegularFileForBindMount(path: string): void {
  try {
    const st = lstatSync(path);
    if (st.isSymbolicLink()) {
      throw new Error(
        `ensureRegularFileForBindMount: refuse symlink at ${path}`,
      );
    }
    if (st.isFile()) return;
    // Directory (or non-file) at a file path = docker footgun residue / corruption.
    rmSync(path, { recursive: true, force: true });
  } catch (err) {
    if (!isFileNotFound(err)) throw err;
  }

  mkdirSync(dirname(path), { recursive: true });

  try {
    // Exclusive create: fails if a symlink/file appears between check and open.
    const fd = openSync(
      path,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
    );
    closeSync(fd);
  } catch (err) {
    if (
      err === null ||
      typeof err !== "object" ||
      (err as { code?: unknown }).code !== "EEXIST"
    ) {
      throw err;
    }
    // Path appeared; only accept a real regular file — never a symlink toehold.
    const st = lstatSync(path);
    if (st.isSymbolicLink()) {
      throw new Error(
        `ensureRegularFileForBindMount: refuse symlink at ${path}`,
      );
    }
    if (st.isFile()) return;
    throw new Error(
      `ensureRegularFileForBindMount: path is not a regular file: ${path}`,
    );
  }
}
