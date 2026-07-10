# Orchestrator checks

`npm test` first runs `npm run typecheck:test`. That dedicated TypeScript lane
checks only `test/defer-removed-617.test.ts`, so its `@ts-expect-error` rejects
any return of `"defer"` to `Finding["action"]` before Vitest executes.

The rest of `test/**` currently has historical TypeScript failures tracked
separately under #307. They are outside this defer-guard contract and are not
used to judge this diff.
