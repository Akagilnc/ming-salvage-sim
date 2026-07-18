import { defineConfig } from "vitest/config";

/**
 * ADR 0140 — fast vs full test pools (mechanical tax-class split).
 *
 * - fast: pure logic / unit (majority). Used by fixer/coder self-check
 *   (`npm run test:fast` = typecheck + this project).
 * - heavy: real process / real sandcastle / real-git e2e-class tax
 *   (name/path convention only — no hand-curated smoke list).
 * - full (`npm test`): typecheck + all projects (fast + heavy).
 *
 * Residual: many unit tests still spin tmp git fixtures for setup; those stay
 * in fast. True process/sandbox/e2e tax files match the heavy include patterns.
 * Further directory moves can tighten the split without rewriting souls.
 */
const shared = {
  environment: "node" as const,
  setupFiles: ["test/setup-route-env.ts"],
  // #962: scripted noSandbox injects per-run GIT_CONFIG_GLOBAL, so concurrent
  // sc.run no longer races on host ~/.gitconfig. Default fileParallelism on.
};

/** Path patterns for process/sandbox/e2e tax (ADR 0140 mechanical criterion). */
const heavyInclude = [
  "test/**/*e2e*.test.ts",
  "test/**/sandcastle-*.test.ts",
  "test/**/scripted-sandcastle-run.test.ts",
  "test/**/real-backend.test.ts",
  "test/**/live-*.test.ts",
  "test/sandbox-stream-heartbeat.test.ts",
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
