/**
 * Scene Provisioning / Recovery Action (#934 ID-005 / ID-009 / ID-015, #936).
 * Owns resident-worksite discovery before productive work. Fresh only when
 * neither worksite nor ledger exists. Local Git no-stale-base / no-second-worktree
 * boundaries live on RealBackend (cutRefFor / prepareWorktree).
 */

import type { Backend, HandoffStatus, ResumeState, WorktreeHandle } from "./types.js";

export type SceneDiscovery =
  | { readonly kind: "fresh" }
  | { readonly kind: "resident"; readonly state: ResumeState }
  | {
      readonly kind: "corrupted";
      readonly reason: string;
      readonly worktree?: WorktreeHandle;
      readonly stateDir?: string;
    };

/**
 * Resident-worksite discovery. Run before admission network work when a durable
 * scene may already exist (ID-005: Recovery first). Never invents a second worksite.
 */
export async function discoverResidentScene(
  backend: Pick<Backend, "findResumeState">,
  issueNumber: number,
): Promise<SceneDiscovery> {
  try {
    const state = await backend.findResumeState(issueNumber);
    if (state === undefined) return { kind: "fresh" };
    return { kind: "resident", state };
  } catch (err) {
    return {
      kind: "corrupted",
      reason: `resident scene discovery failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }
}

export function isDurableTerminalHandoff(
  status: HandoffStatus | undefined,
): status is "success" | "error" | "escalate" {
  return status === "success" || status === "error" || status === "escalate";
}

/** ID-015: optional branchHEAD read may warn and omit. */
export function omitOptionalBranchHead(
  read: () => string | undefined,
  warn: (message: string) => void = (m) => console.warn(m),
): string | undefined {
  try {
    return read();
  } catch (err) {
    warn(
      `[orchestrator] optional branchHEAD read failed (omit): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return undefined;
  }
}
