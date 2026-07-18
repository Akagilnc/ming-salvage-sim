import { defineConfig } from "vitest/config";

import { discoverTestPools } from "./vitest.test-pools.js";

export default defineConfig({
  test: {
    name: "fast",
    include: discoverTestPools().fast,
    environment: "node",
    setupFiles: ["test/setup-route-env.ts"],
  },
});
