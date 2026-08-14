#!/usr/bin/env node
/**
 * Emit the single organic-markdown authority product.
 *
 * One file: web/dist/organicMarkdown.js (IIFE, global OrganicMarkdown).
 * Browser loads it from the release layout; the write seam executes the same bytes.
 * Source remains web/src/organicMarkdown.mjs (build input only — not a second runtime product).
 */
import { createRequire } from "node:module";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const webDir = join(root, "web");
const entry = join(webDir, "src/organicMarkdown.mjs");
const distOut = join(webDir, "dist/organicMarkdown.js");

mkdirSync(dirname(distOut), { recursive: true });

const require = createRequire(join(webDir, "package.json"));
const esbuildPath = require.resolve("esbuild");
const esbuild = (await import(pathToFileURL(esbuildPath).href)).default;

await esbuild.build({
  entryPoints: [entry],
  bundle: true,
  minify: true,
  format: "iife",
  globalName: "OrganicMarkdown",
  platform: "browser",
  outfile: distOut,
  logLevel: "info",
});

if (!existsSync(distOut)) {
  throw new Error("organic markdown authority product was not emitted");
}

console.log(`[organic-authority] ${distOut}`);
