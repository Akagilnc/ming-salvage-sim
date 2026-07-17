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
