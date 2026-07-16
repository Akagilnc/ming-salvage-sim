/**
 * Scene Provisioning / Recovery Action (#934 ID-005 / ID-009 / ID-015, #936).
 * Owns resident-worksite discovery before productive work. Fresh only when
 * neither worksite nor ledger exists. Local Git no-stale-base / no-second-worktree
 * boundaries live on RealBackend (cutRefFor / prepareWorktree).
 *
 * Optional branchHEAD warn+omit lives inline on the runner ledger path (ID-015);
 * no unused helper exported from this module.
 */

import type { Backend, ResumeState, WorktreeHandle } from "./types.js";

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
 *
 * `findResumeState` throws on partial/corrupted residue → `corrupted` (preserve
 * scene, fail loud). Only `undefined` (no worksite) is typed `fresh`.
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
