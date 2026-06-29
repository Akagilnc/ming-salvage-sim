import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeModelRoute,
  MODEL_ROUTE_SLOTS,
  modelForSlot,
  printableRouteLineup,
  resolveRouteModels,
} from "../src/modelRoutes.js";

describe("#422 model route presets", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("normal is an explicit full-slot route and can be printed before a run", () => {
    const resolved = resolveRouteModels("normal", {});

    expect(Object.keys(resolved.slots).sort()).toEqual(
      [...MODEL_ROUTE_SLOTS].sort(),
    );
    expect(resolved.slots).toEqual({
      coder: "gpt-5.5",
      reviewer: "gpt-5.5",
      coderFix: "gpt-5.5",
      ship: "sonnet",
      merger: "opus",
      cmrCompleteness: "opus",
      cmrCorrectness: "opus",
    });
    expect(printableRouteLineup(resolved)).toEqual(
      [
        "route=normal",
        "coder=gpt-5.5",
        "reviewer=gpt-5.5",
        "coderFix=gpt-5.5",
        "ship=sonnet",
        "merger=opus",
        "cmrCompleteness=opus",
        "cmrCorrectness=opus",
        "cmrReview=[codex:gpt-5.5,claude:opus,agy:agy]",
      ].join("\n"),
    );
  });

  it("single-slot overrides win over the selected base route", () => {
    const resolved = resolveRouteModels("normal", {
      reviewer: "opus",
      ship: "gpt-5.5",
    });

    expect(resolved.slots.reviewer).toBe("opus");
    expect(resolved.slots.ship).toBe("gpt-5.5");
    expect(resolved.slots.coder).toBe("gpt-5.5");
  });

  it("fails closed for unknown routes, slots, and slugs", () => {
    expect(() => resolveRouteModels("missing", {})).toThrow(/unknown route/i);
    expect(() =>
      resolveRouteModels("normal", { nope: "gpt-5.5" }),
    ).toThrow(/unknown model slot/i);
    expect(() =>
      resolveRouteModels("normal", { coder: "does-not-exist" }),
    ).toThrow(/unknown model slug/i);
  });

  it("claude-tight has no Claude-family slots across every slot", () => {
    const resolved = resolveRouteModels("claude-tight", {});

    expect(resolved.tightFamilyViolations).toEqual([]);
    expect(new Set(Object.values(resolved.slots))).toEqual(new Set(["gpt-5.5"]));
    expect(resolved.legCollections.cmrReview.map((leg) => leg.family)).not.toContain(
      "claude",
    );
  });

  it("flags an override or review leg that breaks a tight route invariant", () => {
    const overridden = resolveRouteModels("claude-tight", { merger: "opus" });

    expect(overridden.tightFamilyViolations).toEqual([
      { slot: "merger", slug: "opus", family: "claude" },
    ]);

    const badLeg = resolveRouteModels(
      "claude-tight",
      {},
      { cmrReview: ["gpt-5.5", "opus"] },
    );

    expect(badLeg.tightFamilyViolations).toEqual([
      { slot: "cmrReview", slug: "opus", family: "claude" },
    ]);
  });

  it("reads ORCHESTRATOR_ROUTE plus slot env overrides for runtime selection", () => {
    expect(
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
      }).slots.coder,
    ).toBe("gpt-5.5");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_SHIP_MODEL: "sonnet",
      }),
    ).toThrow(/tight route violation/i);

    expect(
      modelForSlot("ship", {
        ORCHESTRATOR_ROUTE: "normal",
        ORCHESTRATOR_SHIP_MODEL: "gpt-5.5",
      }),
    ).toBe("gpt-5.5");

    expect(() =>
      activeModelRoute({
        ORCHESTRATOR_ROUTE: "claude-tight",
        ORCHESTRATOR_CMR_REVIEW_LEGS: "gpt-5.5,opus",
      }),
    ).toThrow(/tight route violation/i);
  });

  it("feeds the resolved route into every worker spec model slot", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    vi.resetModules();

    const { STEP_SPECS } = await import("../src/runner.js");
    const { shipWorkerSpec } = await import("../src/dispatchWorker.js");
    const { cmrWorkerSpec, familyShipWorkerSpec } = await import(
      "../src/family/dispatchFamilyWorker.js"
    );
    const { mergerModel } = await import("../src/family/realFamilyBackend.js");

    expect(STEP_SPECS.S2.model).toBe("gpt-5.5");
    expect(STEP_SPECS.S3.model).toBe("gpt-5.5");
    expect(STEP_SPECS.S5.model).toBe("gpt-5.5");
    expect(STEP_SPECS.S6.model).toBe("gpt-5.5");
    expect(shipWorkerSpec().model).toBe("gpt-5.5");
    expect(cmrWorkerSpec("fresh", "completeness").model).toBe("gpt-5.5");
    expect(cmrWorkerSpec("fresh", "correctness").model).toBe("gpt-5.5");
    expect(familyShipWorkerSpec().model).toBe("gpt-5.5");
    expect(mergerModel()).toBe("gpt-5.5");
  });
});
