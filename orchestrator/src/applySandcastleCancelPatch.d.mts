/** Type surface for the #1010 sandcastle cancel patch (src apply + postinstall CLI). */
export function applySandcastleCancelPatch(root?: string): {
  readonly root: string;
  readonly changed: number;
  readonly files: readonly string[];
};

export function patchNoSandbox(source: string): string;
export function patchContainerRuntime(
  source: string,
  runtime: "docker" | "podman",
): string;
export function patchInvokeAgent(source: string): string;
export function ensureHelper(source: string): string;
export function stripHostKillHelper(source: string): string;
export function upgradeKillLoopSelfExclude(source: string): string | null;
export function hasSelfExcludeKillLoop(source: string): boolean;

export const HOST_KILL_START: string;
export const HOST_KILL_END: string;
export const MARKER_TOKEN: string;
export const HOST_KILL_HELPER: string;
