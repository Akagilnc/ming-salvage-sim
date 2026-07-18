import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";

export type TestPool = "fast" | "heavy";

const HEAVY_IMPORTS = [
  /^\s*\/\/\s*@vitest-pool\s+heavy\s*$/m,
  /^\s*import(?:[^;\r\n]|\r?\n){0,500}?from\s+["'](?:node:)?child_process["'];/m,
  /\bimport\s*\(\s*["'](?:node:)?child_process["']\s*\)/m,
  /^\s*import(?:[^;\r\n]|\r?\n){0,500}?from\s+["']@ai-hero\/sandcastle["'];/m,
  /\bimport\s*\(\s*["']@ai-hero\/sandcastle["']\s*\)/m,
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

export function classifyTestFile(
  file: string,
  visited = new Set<string>(),
  testRoot = resolve("test"),
): TestPool {
  if (file.endsWith(".heavy.test.ts")) return "heavy";
  if (visited.has(file)) return "fast";
  visited.add(file);
  const source = readFileSync(file, "utf8");
  if (classifyTestSource(source) === "heavy") return "heavy";
  for (const match of source.matchAll(RELATIVE_IMPORT)) {
    const dependency = resolveModule(file, match[1]!);
    const relativeDependency = dependency && relative(testRoot, dependency);
    if (
      dependency &&
      relativeDependency &&
      !relativeDependency.startsWith(`..${sep}`) &&
      classifyTestFile(dependency, visited, testRoot) === "heavy"
    ) {
      return "heavy";
    }
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
    const pool = classifyTestFile(file, new Set(), root);
    pools[pool].push(relative(process.cwd(), file).split(sep).join("/"));
  }
  return pools;
}
