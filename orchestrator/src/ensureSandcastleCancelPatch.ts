/**
 * #1010 — ensure the local Sandcastle cancel patch is applied before any
 * `sc.run` / provider create. Safe to call repeatedly (idempotent apply script).
 *
 * Strategy: local patch of installed `@ai-hero/sandcastle@0.12.0` (exact pin;
 * no upstream bump available). AbortSignal + idle-timeout must kill the
 * docker/podman/no-sandbox exec child, not abandon the host Promise alone.
 *
 * Apply runs **in-process** (import the pure patch module under src/) — no
 * child_process spawn. That keeps #884's sole external-call chokepoint intact
 * and avoids preloading `externalCall`/`spawn` during vitest setup (which
 * would break tests that mock `node:child_process`).
 *
 * Apply is TypeScript so product `tsc` emits it into dist/ (no allowJs) —
 * production load of dist/ensureSandcastleCancelPatch.js must resolve the
 * sibling apply module without MODULE_NOT_FOUND.
 */
import { applySandcastleCancelPatch } from "./applySandcastleCancelPatch.js";

let applied = false;

/**
 * Apply the #1010 cancel patch to node_modules/@ai-hero/sandcastle if needed.
 * Throws when the package is missing or a dist needle is missing (loud fail).
 *
 * @param root Optional sandcastle package root. When provided, always runs
 *   apply (skips the process-level idempotency latch) so fail-loud paths stay
 *   testable after a successful production ensure.
 */
export function ensureSandcastleCancelPatch(root?: string): void {
  if (applied && root === undefined) return;
  try {
    applySandcastleCancelPatch(root);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(`ensureSandcastleCancelPatch failed: ${detail}`);
  }
  if (root === undefined) applied = true;
}
