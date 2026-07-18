import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { classifyTestFile, classifyTestSource, discoverTestPools } from "../vitest.test-pools.js";

describe("canonical test pool classification (#990)", () => {
  it("keeps pure logic tests in the fast pool", () => {
    expect(classifyTestSource('import { expect, it } from "vitest";\nit("works", () => expect(1).toBe(1));')).toBe(
      "fast",
    );
  });

  it("rejects process, Sandcastle, and real-git taxes from the fast pool", () => {
    const keyword = ["im", "port"].join("");
    const taxedSources = [
      `${keyword} { execFileSync } from "node:child_process";\nexecFileSync("node", ["worker.js"]);`,
      `${keyword} { Sandcastle } from "@ai-hero/sandcastle";\nawait Sandcastle.create();`,
      `${keyword} { runScriptedStructuredOutput } from "./helpers/scripted-sandcastle-run.js";\nawait runScriptedStructuredOutput({});`,
      `${keyword} { execFileSync } from "node:child_process";\nexecFileSync("git", ["init"]);`,
    ];

    expect(taxedSources.map(classifyTestSource)).toEqual(["heavy", "heavy", "heavy", "heavy"]);
    expect(classifyTestFile(resolve("test/family/route/e2e-driver.test.ts"))).toBe("heavy");
  });

  it("fails if any mechanically heavy test is discovered in the fast pool", () => {
    const pools = discoverTestPools();
    const realSandboxTest = "test/helpers/scripted-sandcastle-run.test.ts";

    expect(pools.heavy).toContain(realSandboxTest);
    expect(pools.fast).not.toContain(realSandboxTest);
  });
});
