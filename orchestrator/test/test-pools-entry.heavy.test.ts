import { execFileSync } from "node:child_process";

import { describe, expect, it } from "vitest";

describe("canonical fast entry tax guard (#990)", () => {
  it.each([
    "test/fixtures/fast-tax-probe.ts",
    "test/fixtures/fast-tax-import-original-probe.ts",
  ])("fails when real-process fixture %s is forced into fast", (fixture) => {
    expect(() =>
      execFileSync("npm", ["run", "test:fast"], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          ...(fixture.endsWith("import-original-probe.ts")
            ? {
                NODE_OPTIONS: "--trace-warnings",
              }
            : {}),
          VITEST_FAST_GUARD_FIXTURE: fixture,
        },
        encoding: "utf8",
        stdio: "pipe",
      }),
    ).toThrow(/fast-tax-guard/);
  }, 30_000);
});
