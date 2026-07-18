import { defineConfig } from "vitest/config";

import { discoverTestPools } from "./vitest.test-pools.js";

export default defineConfig({
  test: {
    name: "fast",
    include: process.env.VITEST_FAST_GUARD_FIXTURE
      ? [process.env.VITEST_FAST_GUARD_FIXTURE]
      : discoverTestPools().fast,
    environment: "node",
    setupFiles: ["test/setup-route-env.ts", "test/setup-fast-tax-guard.ts"],
  },
});
