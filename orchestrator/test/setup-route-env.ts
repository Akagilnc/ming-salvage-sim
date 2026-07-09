import { beforeEach, vi } from "vitest";

// The orchestrator runner may execute `npm test` under a non-default
// ORCHESTRATOR_ROUTE or per-slot model overrides. Unit tests default to the
// normal route and opt into route variants explicitly with vi.stubEnv.
const ROUTE_ENV_KEYS = [
  "ORCHESTRATOR_CODER_MODEL",
  "ORCHESTRATOR_REVIEWER_MODEL",
  "ORCHESTRATOR_CODER_FIX_MODEL",
  "ORCHESTRATOR_SHIP_MODEL",
  "ORCHESTRATOR_MERGER_MODEL",
  "ORCHESTRATOR_CMR_COMPLETENESS_MODEL",
  "ORCHESTRATOR_CMR_CORRECTNESS_MODEL",
  "ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS",
] as const;

process.env.ORCHESTRATOR_ROUTE = "normal";
process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
// Suite-wide hatch for #602 offline auto-merge when fakes have no doc-release
// commit paths. Production host wiring never sets this; #602 unit tests that
// assert fail-closed explicitly clear it.
process.env.ORCHESTRATOR_AUTO_MERGE_ALLOW_UNVERIFIED_DOC_PATHS = "1";
for (const key of ROUTE_ENV_KEYS) {
  delete process.env[key];
}

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
  vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "1");
  vi.stubEnv("ORCHESTRATOR_AUTO_MERGE_ALLOW_UNVERIFIED_DOC_PATHS", "1");
  for (const key of ROUTE_ENV_KEYS) {
    delete process.env[key];
  }
});
