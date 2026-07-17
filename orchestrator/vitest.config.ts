import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
    setupFiles: ["test/setup-route-env.ts"],
    // #962: scripted noSandbox injects per-run GIT_CONFIG_GLOBAL, so concurrent
    // sc.run no longer races on host ~/.gitconfig. Default fileParallelism on.
  },
});
