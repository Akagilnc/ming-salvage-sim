# Orchestrator checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as `npm run typecheck:test`) before Vitest. That TypeScript lane checks all of
`test/**`, so every test fixture and mock must satisfy the current production
contracts before the behavioral suite runs.
