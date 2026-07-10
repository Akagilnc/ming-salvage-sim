import { describe, expect, it } from "vitest";
import {
  resolveRouteModels,
  routeSmokeFailure,
  smokeRouteModels,
} from "../src/modelRoutes.js";

describe("#685 route tool smoke", () => {
  it("rejects a route before its model×pipe entries have been smoked", () => {
    const route = resolveRouteModels("normal", {});

    expect(routeSmokeFailure(route)).toMatch(/route smoke required/i);
  });

  it("records a passed smoke with a timestamp and CLI version and allows dispatch", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async () => ({ cliVersion: "cli-1" }));

    expect(Object.values(smoked.smoke).every((status) => status.state === "passed")).toBe(true);
    expect(routeSmokeFailure(smoked)).toBeUndefined();
    expect(smoked.smoke["coder:sonnet"]).toMatchObject({
      state: "passed",
      cliVersion: "cli-1",
    });
  });

  it("rejects a passed smoke after its configured TTL", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(
      route,
      async () => ({ cliVersion: "cli-1" }),
      new Date("2026-07-01T00:00:00.000Z"),
    );

    expect(routeSmokeFailure(smoked, Date.parse("2026-07-03T00:00:01.000Z"), 48 * 60 * 60 * 1000)).toMatch(
      /route smoke expired/i,
    );
  });

  it("rejects a passed smoke when the selected CLI version changes", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async () => ({ cliVersion: "cli-1" }));

    expect(routeSmokeFailure(smoked, Date.now(), 24 * 60 * 60 * 1000, { sonnet: "cli-2" })).toMatch(
      /CLI version changed/i,
    );
  });

  it("records failures and keeps the route fail-closed", async () => {
    const route = resolveRouteModels("normal", {});
    const smoked = await smokeRouteModels(route, async ({ slug }) => {
      if (slug === "sonnet") throw new Error("bash tool unavailable");
      return { cliVersion: "cli-1" };
    });

    expect(routeSmokeFailure(smoked)).toMatch(/route smoke failed.*sonnet/i);
  });
});
