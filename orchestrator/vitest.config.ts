import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { defineConfig } from "vitest/config";

/**
 * ADR 0140 — fast vs full test pools (mechanical tax-class split).
 *
 * - fast: pure logic / unit (majority). Used by fixer/coder self-check
 *   (`npm run test:fast` = typecheck + this project).
 * - heavy: real process / real sandcastle / real-git e2e-class tax
 *   (path/name convention + harness-nature scan — no hand-curated smoke list).
 * - full (`npm test`): typecheck + all projects (fast + heavy).
 *
 * Residual: many unit tests still spin tmp git fixtures for setup; those stay
 * in fast. True process/sandbox/e2e tax is classified below. Further directory
 * moves can tighten the split without rewriting souls.
 */
const shared = {
  environment: "node" as const,
  setupFiles: ["test/setup-route-env.ts"],
  // #962: scripted noSandbox injects per-run GIT_CONFIG_GLOBAL, so concurrent
  // sc.run no longer races on host ~/.gitconfig. Default fileParallelism on.
  // #1071: real-process/real-git tax runs under full-fleet parallelism on a
  // contended box, so a *correct* test can finish late (the #1070 sibling
  // caught one at 6.5s). Vitest's 5000ms default reddens those slow-but-green
  // runs; give both pools a load-tolerant budget so the assertion — not the
  // wall-clock — decides pass/fail. Not a retry: the test still must pass.
  testTimeout: 30_000,
};

/**
 * Path/name conventions for process/e2e/live tax (ADR 0140).
 * New tests of these classes should follow the same naming so they auto-join heavy.
 */
const heavyPathPatterns: string[] = [
  "test/**/*.heavy.test.ts",
  "test/**/*e2e*.test.ts",
  "test/**/sandcastle-*.test.ts",
  "test/**/real-backend.test.ts",
  // Do not use bare live-*: domain names like live-officer-effort are pure
  // registry units. Real live/e2e tax is covered by nature scan + *e2e* /
  // sandcastle / real-backend / *-worker. Prefer *live-e2e* if a path signal
  // is ever needed for a true live-e2e suite.
  // Worker integration suites (cmr-worker, ship-worker, …) — real SO four-case homes.
  // Pure unit files use other stems (worker-dispatch, worker-reporting, …).
  "test/**/*-worker.test.ts",
];

/**
 * Nature scan: any `*.test.ts` that imports the real sc.run harness pays sandbox
 * tax. New harness users join heavy automatically — not a hand-picked file list.
 * Covers e.g. route/*-scripted* persist SO suites that do not match path globs.
 */
function heavyByHarnessNature(root = "test"): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      // Cheap guard: never descend into dependency / vcs trees under test/.
      if (name === "node_modules" || name === ".git") continue;
      const p = join(dir, name);
      if (statSync(p).isDirectory()) {
        walk(p);
        continue;
      }
      if (!name.endsWith(".test.ts")) continue;
      const src = readFileSync(p, "utf8");
      const importsHarness =
        src.includes("runScriptedStructuredOutput") ||
        (/\bfrom\s+["']@ai-hero\/sandcastle(?:\/[^"']*)?["']/.test(src) &&
          (/\bnoSandbox\s*\(/.test(src) || /\bsc\.run\s*\(/.test(src)));
      if (importsHarness) {
        out.push(p.replaceAll("\\", "/"));
      }
    }
  };
  walk(root);
  return out;
}

/** Union of path conventions + harness-nature hits (deduped). */
export const heavyInclude = [
  ...new Set<string>([...heavyPathPatterns, ...heavyByHarnessNature()]),
];

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "fast",
          include: ["test/**/*.test.ts"],
          exclude: heavyInclude,
          ...shared,
        },
      },
      {
        test: {
          name: "heavy",
          include: heavyInclude,
          ...shared,
        },
      },
    ],
  },
});
