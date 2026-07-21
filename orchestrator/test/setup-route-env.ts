import { beforeEach, vi } from "vitest";
// #1010: patch Sandcastle cancel seam before any test imports sc.run / docker.
import "../src/sandcastleCancelSeam.js";
import { resetRoutePresetsCacheForTests } from "../src/modelRoutes.js";

/**
 * #1090 — never let unit tests shell out to a real `gh pr list` for ship-PR
 * resolution. Suites that intentionally exercise resolveFamilyShipPr mock
 * `shWithClock` themselves (see ship-pr-resolution-1090.test.ts).
 */
vi.mock("../src/externalCall.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/externalCall.js")>();
  return {
    ...actual,
    shWithClock(
      file: string,
      args: readonly string[],
      opts?: { readonly stage?: string },
    ) {
      if (
        file === "gh" &&
        args[0] === "pr" &&
        args[1] === "list" &&
        opts?.stage === "resolve:shipPr"
      ) {
        // Opt-in for suites whose src fixtures still emit non-URL ship.pr
        // (e.g. dogfoodReplay) — resolve to a fixture PR instead of live gh.
        const fixture = process.env.ORCHESTRATOR_TEST_RESOLVE_SHIP_PR?.trim();
        if (fixture && /^https?:\/\/\S*\/pull\/\d+/.test(fixture)) {
          return JSON.stringify([{ url: fixture }]);
        }
        return "[]";
      }
      return actual.shWithClock(file, args, opts);
    },
  };
});

// The orchestrator runner may execute `npm test` under a non-default
// ORCHESTRATOR_ROUTE or per-slot model overrides. Unit tests default to the
// normal route and opt into route variants explicitly with vi.stubEnv.
const ROUTE_ENV_KEYS = [
  "ORCHESTRATOR_CODER_MODEL",
  // #923: retired — still cleared so host env cannot fail-loud every suite.
  "ORCHESTRATOR_REVIEWER_MODEL",
  "ORCHESTRATOR_CODER_FIX_MODEL",
  "ORCHESTRATOR_SHIP_MODEL",
  "ORCHESTRATOR_MERGER_MODEL",
  "ORCHESTRATOR_CMR_COMPLETENESS_MODEL",
  "ORCHESTRATOR_CMR_CORRECTNESS_MODEL",
  "ORCHESTRATOR_VERIFY_MODEL",
  "ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS",
  // #916: custom presets path must not leak across suites.
  "ORCHESTRATOR_ROUTE_PRESETS_PATH",
] as const;

process.env.ORCHESTRATOR_ROUTE = "normal";
process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
for (const key of ROUTE_ENV_KEYS) {
  delete process.env[key];
}

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
  vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "1");
  for (const key of ROUTE_ENV_KEYS) {
    delete process.env[key];
  }
  // #916: drop config-file cache so path/env isolation is real between tests.
  resetRoutePresetsCacheForTests();
});
