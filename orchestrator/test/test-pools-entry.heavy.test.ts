import { execFileSync } from "node:child_process";
import { writeFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("canonical fast entry tax guard (#990)", () => {
  it("fails when a real-process fixture is forced into fast", () => {
    const fixture = resolve("test/.fast-tax-probe.test.ts");
    writeFileSync(
      fixture,
      [
        'import { spawnSync } from "node:child_process";',
        'import { it } from "vitest";',
        'it("pays process tax", () => spawnSync(process.execPath, ["-v"]));',
      ].join("\n"),
    );

    try {
      expect(() =>
        execFileSync("npm", ["run", "test:fast"], {
          cwd: process.cwd(),
          env: {
            ...process.env,
            VITEST_FAST_GUARD_FIXTURE: "test/.fast-tax-probe.test.ts",
          },
          encoding: "utf8",
          stdio: "pipe",
        }),
      ).toThrow(/fast-tax-guard/);
    } finally {
      rmSync(fixture, { force: true });
    }
  }, 30_000);
});
