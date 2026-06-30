import { beforeEach, vi } from "vitest";

// The orchestrator runner may execute `npm test` under a non-default
// ORCHESTRATOR_ROUTE. Unit tests default to the normal route and opt into route
// variants explicitly with vi.stubEnv.
process.env.ORCHESTRATOR_ROUTE = "normal";

beforeEach(() => {
  vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
});
