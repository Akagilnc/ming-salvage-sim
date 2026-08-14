/**
 * Vitest setup: load the same release-layout authority product the browser and
 * write seam consume (web/dist/organicMarkdown.js).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createContext, runInContext } from "node:vm";

const product = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "organicMarkdown.js");
const source = readFileSync(product, "utf8");
const context = createContext({ globalThis });
runInContext(source, context);
const api = (context as { OrganicMarkdown?: unknown }).OrganicMarkdown
  ?? (globalThis as { OrganicMarkdown?: unknown }).OrganicMarkdown;
if (!api) {
  throw new Error(`failed to load organic authority product at ${pathToFileURL(product).href}`);
}
(globalThis as { OrganicMarkdown?: unknown }).OrganicMarkdown = api;
