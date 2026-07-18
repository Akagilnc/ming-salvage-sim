/**
 * #923 — judge identity merge: reviewer model-route slot folds into verify.
 *
 * Seams (issue AC):
 *   - MODEL_ROUTE_SLOTS / presets: no reviewer slot; verify staffs both courts
 *   - deleted reviewer env cannot restaff either court
 *   - S3/S6 stepSpecs + single-slice relay read verify
 *   - behavior defaults preserved (same preset slug as prior reviewer+verify pair)
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MODEL_ROUTE_SLOTS,
  activeModelRoute,
  modelForSlot,
  printableRouteLineup,
  relaySlotForSingleSliceWallStep,
  resolveActiveModelRoute,
  resolveRouteModels,
} from "../../src/modelRoutes.js";

describe("#923 judge identity merge — model-route slot", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("drops reviewer from MODEL_ROUTE_SLOTS; verify remains the sole judge slot", () => {
    expect(MODEL_ROUTE_SLOTS).not.toContain("reviewer");
    expect(MODEL_ROUTE_SLOTS).toContain("verify");
    expect(Object.keys(resolveRouteModels("normal", {}).slots)).not.toContain(
      "reviewer",
    );
  });

  it("every preset staffs S3/S6 courts via verify (no separate reviewer key)", () => {
    for (const routeName of [
      "normal",
      "codex-cheap",
      "codex-tight",
      "claude-cheap",
      "claude-tight",
    ] as const) {
      const route = resolveRouteModels(routeName, {});
      expect(route.slots).not.toHaveProperty("reviewer");
      expect(typeof route.slots.verify).toBe("string");
      expect(route.slots.verify.length).toBeGreaterThan(0);
    }

    // Default codex-enabled presets keep Sol on the unified judge slot
    // (same slug the retired reviewer seat previously held).
    for (const routeName of [
      "normal",
      "codex-cheap",
      "claude-cheap",
      "claude-tight",
    ] as const) {
      expect(resolveRouteModels(routeName, {}).slots.verify).toBe("gpt-5.6-sol");
    }
    expect(resolveRouteModels("codex-tight", {}).slots.verify).toBe("opus");
  });

  it("single-slice S3/S6 relay targets the verify slot", () => {
    expect(relaySlotForSingleSliceWallStep("S3")).toBe("verify");
    expect(relaySlotForSingleSliceWallStep("S6")).toBe("verify");
    expect(relaySlotForSingleSliceWallStep("S5")).toBe("coderFix");
    expect(relaySlotForSingleSliceWallStep("S2")).toBe("coder");
  });

  it("S3/S6 stepSpecs take their model from the verify slot", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.resetModules();

    const { stepSpecsForEnv } = await import("../../src/runner.js");
    const specs = stepSpecsForEnv();
    // normal preset: verify = gpt-5.6-sol
    expect(specs.S3.model).toBe("gpt-5.6-sol");
    expect(specs.S6.model).toBe("gpt-5.6-sol");
    // #919 S2 / #923: model-route slot + seat role/soul are all verify.
    // "reviewer" remains multi-model leg-soul vocabulary only.
    expect(specs.S3.role).toBe("verify");
    expect(specs.S6.role).toBe("verify");
    expect(specs.S3.soul).toBe("verify");
    expect(specs.S6.soul).toBe("verify");
  });

  it("ORCHESTRATOR_VERIFY_MODEL env override is deleted (#936); preset owns judge seat", () => {
    expect(
      modelForSlot("verify", {
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_VERIFY_MODEL: "opus",
      }),
    ).toBe("gpt-5.6-sol");
    expect(
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_VERIFY_MODEL: "gpt-5.6-terra",
      }).slots.verify,
    ).toBe("gpt-5.6-sol");
  });

  it("deleted reviewer env cannot restaff the judge", () => {
    const env = {
      ORCHESTRATOR_ROUTE: "normal",
      ORCHESTRATOR_REVIEWER_MODEL: "opus",
    };
    expect(resolveActiveModelRoute(env).slots.verify).toBe("gpt-5.6-sol");
    expect(activeModelRoute(env).slots.verify).toBe("gpt-5.6-sol");
  });

  it("programmatic reviewer override key is unknown (slot gone, no silent map)", () => {
    expect(() =>
      resolveRouteModels("normal", { reviewer: "opus" } as Record<string, string>),
    ).toThrow(/unknown model slot/i);
  });

  it("printable lineup lists verify once and never a reviewer line", () => {
    const lineup = printableRouteLineup(resolveRouteModels("normal", {}));
    expect(lineup).toContain("verify=gpt-5.6-sol");
    expect(lineup).not.toMatch(/^reviewer=/m);
    expect(lineup).not.toContain("\nreviewer=");
  });
});
