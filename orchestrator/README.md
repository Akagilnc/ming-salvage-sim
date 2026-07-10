# Orchestrator checks

`npm test` first runs the `tsconfig.test.json` compile gate (same check as `npm run typecheck:test`) before vitest. That dedicated TypeScript lane
checks only `test/defer-removed-617.test.ts`. The sentinel assigns `"defer"` to
`Finding["action"]` under `@ts-expect-error`: when `"defer"` is absent from the
union the assignment errors and satisfies the directive; if `"defer"` is
re-added the assignment becomes legal and TS2578 (unused `@ts-expect-error`)
fires before Vitest executes.

The rest of `test/**` currently has historical TypeScript failures tracked
separately under #766. They are outside this defer-guard contract and are not
used to judge this diff.
