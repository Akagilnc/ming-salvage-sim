import { existsSync, readFileSync } from "node:fs";

/**
 * Unwrap a ```json … ``` (or bare ``` … ```) fenced code block to its inner
 * payload, mirroring Sandcastle's fence-aware tag extraction.
 */
export function stripJsonFence(s: string): string {
  const fence = /^```(?:json)?\s*\n?([\s\S]*?)\n?```$/;
  const m = fence.exec(s.trim());
  return m ? m[1].trim() : s;
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
  if (!existsSync(path)) return undefined;
  const raw = readFileSync(path, "utf8").trim();
  if (raw.length === 0) return undefined;
  return JSON.parse(stripJsonFence(raw));
}
