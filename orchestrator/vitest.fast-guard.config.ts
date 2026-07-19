import { defineConfig } from "vitest/config";

const fixture = process.env.VITEST_FAST_GUARD_FIXTURE;
if (!fixture) throw new Error("VITEST_FAST_GUARD_FIXTURE is required");

export default defineConfig({
  test: {
    name: "fast-tax-guard",
    pool: "threads",
    include: [fixture],
    environment: "node",
    setupFiles: ["test/setup-route-env.ts"],
  },
});
