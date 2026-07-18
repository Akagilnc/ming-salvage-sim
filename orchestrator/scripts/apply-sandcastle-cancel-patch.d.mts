/** Type surface for the #1010 sandcastle cancel patch entry (postinstall + ensure). */
export function applySandcastleCancelPatch(root?: string): {
  readonly root: string;
  readonly changed: number;
  readonly files: readonly string[];
};
