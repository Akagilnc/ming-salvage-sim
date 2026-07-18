import { spawnSync } from "node:child_process";

import { expect, it } from "vitest";

it("keeps an unused process import in the fast pool", () => {
  expect(typeof spawnSync).toBe("function");
});
