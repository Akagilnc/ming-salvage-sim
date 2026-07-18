#!/usr/bin/env node
/**
 * #1010 — thin postinstall CLI wrap around src/applySandcastleCancelPatch.ts.
 * Product code value-imports the TS module (tsc emits to dist/); this file
 * only provides the `node scripts/…` / postinstall entry that exits 0/1.
 *
 * Optional argv[2] = sandcastle package root (tests + manual apply); default
 * resolves the installed @ai-hero/sandcastle package.
 *
 * Loads the .ts source so postinstall works before a product `npx tsc` emit
 * (Node type-stripping; dist/ may not exist yet at install time).
 */
import { fileURLToPath } from "node:url";
import { applySandcastleCancelPatch } from "../src/applySandcastleCancelPatch.ts";

const isMain =
  process.argv[1] !== undefined &&
  fileURLToPath(import.meta.url) === process.argv[1];

if (isMain) {
  try {
    const rootArg = process.argv[2];
    const result = applySandcastleCancelPatch(rootArg);
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
