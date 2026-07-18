#!/usr/bin/env node
/**
 * #1010 — thin postinstall CLI wrap around src/applySandcastleCancelPatch.mjs.
 * Product code imports the src module directly (tsc rootDir coheres); this
 * file only provides the `node scripts/…` / postinstall entry that exits 0/1.
 */
import { fileURLToPath } from "node:url";
import { applySandcastleCancelPatch } from "../src/applySandcastleCancelPatch.mjs";

const isMain =
  process.argv[1] !== undefined &&
  fileURLToPath(import.meta.url) === process.argv[1];

if (isMain) {
  try {
    const result = applySandcastleCancelPatch();
    process.stdout.write(
      `sandcastle-cancel-patch: root=${result.root} changed=${result.changed}\n`,
    );
    process.exit(0);
  } catch (err) {
    process.stderr.write(
      `sandcastle-cancel-patch FAILED: ${
        err instanceof Error ? err.message : String(err)
      }\n`,
    );
    process.exit(1);
  }
}

export { applySandcastleCancelPatch };
