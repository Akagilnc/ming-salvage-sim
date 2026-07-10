# Orchestrator checks

`npm test` first runs `npm run typecheck:test`. That dedicated TypeScript lane
checks `test/defer-removed-617.test.ts`, so its `@ts-expect-error` rejects any
return of `"defer"` to `Finding["action"]` before Vitest executes.

The test tree currently has legacy type errors outside this contract test; this
lane intentionally targets the regression guard until those tests are made
type-clean.
