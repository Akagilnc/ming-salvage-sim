import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
    setupFiles: ["test/setup-route-env.ts"],
    // Real sc.run nests `git config --global`; under file-parallelism concurrent
    // test files race on ~/.gitconfig → FiberFailure ExecError
    // "could not lock config file … File exists" (CI flake). describe.sequential
    // only serializes within one file; cross-file SO suites still collide.
    // CI always sets CI=true; keep local file-parallelism for speed.
    fileParallelism: process.env.CI !== "true",
  },
});
