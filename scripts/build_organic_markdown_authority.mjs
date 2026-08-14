#!/usr/bin/env node
/**
 * Emit the single organic-markdown authority product consumed by:
 *   - production write seam (Python in-process via quickjs)
 *   - release layout under web/dist/ (packaged by Ming_LLM.spec)
 *
 * Source of truth remains web/src/organicMarkdown.mjs (also bundled into the UI).
 */
import { createRequire } from "node:module";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const webDir = join(root, "web");
const entry = join(webDir, "src/organicMarkdown.mjs");
const distOut = join(webDir, "dist/organicMarkdown.js");
const siblingOut = join(root, "ming_sim/organic_markdown.authority.js");

mkdirSync(dirname(distOut), { recursive: true });
mkdirSync(dirname(siblingOut), { recursive: true });

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

copyFileSync(distOut, siblingOut);

if (!existsSync(distOut) || !existsSync(siblingOut)) {
  throw new Error("organic markdown authority product was not emitted");
}

console.log(`[organic-authority] ${distOut}`);
console.log(`[organic-authority] ${siblingOut}`);
