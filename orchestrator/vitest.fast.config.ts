import { defineConfig } from "vitest/config";
import { heavyInclude } from "./vitest.config.js";

export default defineConfig({
  test: {
    name: "fast",
    pool: "threads",
    include: ["test/**/*.test.ts"],
    exclude: heavyInclude,
    environment: "node",
    setupFiles: ["test/setup-route-env.ts"],
  },
});
