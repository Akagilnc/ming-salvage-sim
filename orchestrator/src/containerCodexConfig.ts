/**
 * containerCodexConfig.ts — the per-container codex `config.toml` writer.
 *
 * The orchestrator mirrors the host's codex CREDENTIALS (`auth.json`) into each
 * container's codex dir, but it must NOT copy the host's `config.toml`. Two reasons:
 *
 *   1. Self-sandbox nesting is impossible. The host config carries
 *      `sandbox_mode = "workspace-write"`, which makes the in-container codex try
 *      to spin up its OWN bwrap sandbox. Nested inside the orchestrator's already-
 *      sandboxed container that fails (`bwrap: No permissions to create a new
 *      namespace`), so the cmr/ship codex review legs — which run via
 *      `codex exec`/`codex-review.sh` and do NOT pass
 *      `--dangerously-bypass-approvals-and-sandbox` — silently degrade to
 *      static-only and can no longer EXERCISE. The container IS the sandbox
 *      boundary; codex must not self-sandbox.
 *   2. The host config is host-personal (notify hook paths, plugins, machine-
 *      local timeouts) — none of it means anything inside a container.
 *
 * So at every auth-mount site we copy `auth.json` (required credentials) but
 * WRITE this minimal, purpose-built config instead of copying the host's.
 *
 * Keys (verified against codex-cli 0.137.0 via `codex doctor`):
 *   - `sandbox_mode = "danger-full-access"` — codex does not self-sandbox; the
 *     container is the boundary. This alone removes the nested-bwrap failure.
 *   - `approval_policy = "never"` — headless, never prompt for approval. Belt-and-
 *     suspenders for `codex exec` non-interactive runs; the modern top-level key
 *     (the legacy host config used `[projects.*] approval_mode`). `codex doctor`
 *     reports "approval policy Never" + "filesystem sandbox unrestricted" for it.
 */
import { chmodSync, writeFileSync } from "node:fs";

/**
 * The minimal in-container codex config.toml body. The container is the sandbox
 * boundary, so codex must NOT self-sandbox (nested bwrap is impossible); and the
 * run is headless, so it must never block on an approval prompt.
 */
export const CONTAINER_CODEX_CONFIG_TOML =
  'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n';

/**
 * Write the minimal per-container codex `config.toml` to {@link destPath} (0o600,
 * owner-only — it sits beside the copied `auth.json` credential). Replaces every
 * `copyFileSync(host config.toml, …)` site: the container config has NO necessary
 * connection to the host's, only `auth.json` does.
 */
export function writeContainerCodexConfig(destPath: string): void {
  writeFileSync(destPath, CONTAINER_CODEX_CONFIG_TOML, { mode: 0o600 });
  chmodSync(destPath, 0o600);
}
