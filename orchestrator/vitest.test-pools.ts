import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";

export type TestPool = "fast" | "heavy";

const HEAVY_IMPORTS = [
  /^\s*import(?:[^;\r\n]|\r?\n){0,500}?from\s+["'](?:node:)?child_process["'];/m,
  /^\s*import(?:[^;\r\n]|\r?\n){0,500}?from\s+["']@ai-hero\/sandcastle["'];/m,
  /^\s*import(?:[^;\r\n]|\r?\n){0,500}?from\s+["'][^"']*scripted-sandcastle-run\.js["'];/m,
] as const;

export function classifyTestSource(source: string): TestPool {
  return HEAVY_IMPORTS.some((pattern) => pattern.test(source)) ? "heavy" : "fast";
}

const RELATIVE_IMPORT = /(?:import|export)(?:[^;\r\n]|\r?\n){0,500}?from\s+["'](\.{1,2}\/[^"']+)["'];/g;

function resolveModule(from: string, specifier: string): string | undefined {
  const target = resolve(dirname(from), specifier);
  const candidates = specifier.endsWith(".js")
    ? [target.slice(0, -3) + ".ts", target.slice(0, -3) + ".tsx"]
    : [target, `${target}.ts`, `${target}.tsx`, resolve(target, "index.ts")];
  return candidates.find(existsSync);
}

export function classifyTestFile(file: string, visited = new Set<string>()): TestPool {
  if (visited.has(file)) return "fast";
  visited.add(file);
  const source = readFileSync(file, "utf8");
  if (classifyTestSource(source) === "heavy") return "heavy";
  for (const match of source.matchAll(RELATIVE_IMPORT)) {
    const dependency = resolveModule(file, match[1]!);
    if (dependency && classifyTestFile(dependency, visited) === "heavy") return "heavy";
  }
  return "fast";
}

export function discoverTestPools(root = resolve("test")): Record<TestPool, string[]> {
  const pools: Record<TestPool, string[]> = { fast: [], heavy: [] };
  const files = readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".test.ts"))
    .map((entry) => resolve(entry.parentPath, entry.name))
    .sort();

  for (const file of files) {
    const pool = classifyTestFile(file);
    pools[pool].push(relative(process.cwd(), file).split(sep).join("/"));
  }
  return pools;
}
