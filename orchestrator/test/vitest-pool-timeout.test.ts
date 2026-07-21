/**
 * #1071 — real-process test pools must give a load-tolerant `testTimeout`.
 *
 * The heavy pool is real-process / real-git / real-sandcastle e2e tax run under
 * full-fleet parallelism (`fileParallelism` on, no worker cap). Under CPU
 * contention a *correct* real-process test finishes late — the #1070 sibling
 * caught one taking 6.5s that reddened solely because it rode vitest's 5000ms
 * default `testTimeout`, then passed 44/44 when re-run alone. Neither pool may
 * leave the timeout unset at that default: the assertion is what must decide
 * pass/fail, never the wall-clock budget under load.
 *
 * Seam: the `vitest.config.ts` default export that vitest actually consumes.
 */

import { describe, expect, it } from "vitest";

import vitestConfig from "../vitest.config.js";

const VITEST_DEFAULT_TEST_TIMEOUT_MS = 5000;
const LOAD_TOLERANT_FLOOR_MS = 20_000;

const projects = vitestConfig.test?.projects ?? [];

function poolTestTimeout(name: string): number | undefined {
  for (const project of projects) {
    if (
      project !== null &&
      typeof project === "object" &&
      "test" in project &&
      project.test?.name === name
    ) {
      return project.test.testTimeout;
    }
  }
  return undefined;
}

describe("vitest pool testTimeout is load-tolerant (#1071)", () => {
  it.each(["heavy", "fast"])(
    "%s pool tolerates slow-under-load runs (>= 20s budget)",
    (pool) => {
      const timeout = poolTestTimeout(pool);
      expect(timeout).toBeGreaterThanOrEqual(LOAD_TOLERANT_FLOOR_MS);
    },
  );

  it("neither pool rides the 5000ms default that reddens a correct 6.5s run", () => {
    // Negative guard: the #1070 failure mode is an unset (=5000ms) budget.
    for (const pool of ["heavy", "fast"] as const) {
      const timeout = poolTestTimeout(pool);
      expect(timeout).toBeDefined();
      expect(timeout).not.toBe(VITEST_DEFAULT_TEST_TIMEOUT_MS);
    }
  });
});
