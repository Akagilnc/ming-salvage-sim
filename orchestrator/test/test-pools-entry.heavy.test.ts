import { execFileSync } from "node:child_process";

import { describe, expect, it } from "vitest";

describe("canonical fast entry tax guard (#990)", () => {
  it("fails when a real-process fixture is forced into fast", () => {
    expect(() =>
      execFileSync("npm", ["run", "test:fast"], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          VITEST_FAST_GUARD_FIXTURE: "test/fixtures/fast-tax-probe.ts",
        },
        encoding: "utf8",
        stdio: "pipe",
      }),
    ).toThrow(/fast-tax-guard/);
  }, 30_000);
});
