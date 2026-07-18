/**
 * #1010 — ensure the local Sandcastle cancel patch is applied before any
 * `sc.run` / provider create. Safe to call repeatedly (idempotent apply script).
 *
 * Strategy: local patch of installed `@ai-hero/sandcastle@0.12.0` (latest;
 * no upstream bump available). AbortSignal + idle-timeout must kill the
 * docker/podman/no-sandbox exec child, not abandon the host Promise alone.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

let applied = false;

function patchScriptPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  // Compiled: dist/ensureSandcastleCancelPatch.js → ../scripts/
  // Source (vitest ts): src/ → ../scripts/
  const candidates = [
    join(here, "..", "scripts", "apply-sandcastle-cancel-patch.mjs"),
    join(here, "scripts", "apply-sandcastle-cancel-patch.mjs"),
  ];
  for (const p of candidates) {
    if (existsSync(p)) return p;
  }
  throw new Error(
    "ensureSandcastleCancelPatch: apply-sandcastle-cancel-patch.mjs not found",
  );
}

/**
 * Apply the #1010 cancel patch to node_modules/@ai-hero/sandcastle if needed.
 * Throws when the package is missing or the apply script fails.
 */
export function ensureSandcastleCancelPatch(): void {
  if (applied) return;
  const script = patchScriptPath();
  const result = spawnSync(process.execPath, [script], {
    encoding: "utf8",
    env: process.env,
  });
  if (result.status !== 0) {
    const detail =
      (result.stderr && result.stderr.trim()) ||
      (result.stdout && result.stdout.trim()) ||
      `exit ${result.status ?? "null"}`;
    throw new Error(`ensureSandcastleCancelPatch failed: ${detail}`);
  }
  applied = true;
}
