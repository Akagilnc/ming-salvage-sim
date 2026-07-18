import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "fast",
    include: process.env.VITEST_FAST_GUARD_FIXTURE
      ? [process.env.VITEST_FAST_GUARD_FIXTURE]
      : ["test/**/*.test.ts"],
    exclude: ["test/**/*.heavy.test.ts"],
    environment: "node",
    setupFiles: ["test/setup-route-env.ts", "test/setup-fast-tax-guard.ts"],
  },
});
