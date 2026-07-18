/**
 * Shared execFileSync / child_process failure stream capture.
 *
 * Node's `Command failed: …` message alone drops the locatable reason —
 * vitest puts FAIL bodies on **stdout**, noise often on stderr. Callers that
 * surface a failure package (baseline health gate, family verify) must keep
 * BOTH streams labeled from one helper (DRY; codex R3 / #1006 CR).
 */

/** Decode an exec `stderr`/`stdout` field (string | Buffer | undefined) to trimmed text. */
export function decodeChildOutput(v: unknown): string {
  if (typeof v === "string") return v.trim();
  if (v instanceof Buffer) return v.toString("utf8").trim();
  return "";
}

/**
 * Capture exec failure detail: message + labeled stdout + stderr.
 * Single source for baseline health gate and family verify summarizeError.
 */
export function formatExecFailureOutput(err: unknown): string {
  const parts: string[] = [];
  if (err instanceof Error) {
    parts.push(err.message);
  } else if (err != null) {
    parts.push(String(err));
  }
  if (err !== null && typeof err === "object") {
    const e = err as { stdout?: unknown; stderr?: unknown };
    const stderr = decodeChildOutput(e.stderr);
    const stdout = decodeChildOutput(e.stdout);
    if (stderr.length > 0) parts.push(`stderr: ${stderr}`);
    if (stdout.length > 0) parts.push(`stdout: ${stdout}`);
  }
  return parts.join("\n");
}
