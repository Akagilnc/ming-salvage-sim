/**
 * #916 — route presets leave code for a config file; claude-tight factory
 * lineup + gpt-5.6-sol-low registry row; env > config > built-in fallback.
 */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveModelSlug } from "../../src/modelRegistry.js";
import {
  MODEL_ROUTE_SLOTS,
  activeModelRoute,
  resetRoutePresetsCacheForTests,
  resolveRouteModels,
  routeSmokeEntries,
} from "../../src/modelRoutes.js";

const tempDirs: string[] = [];

afterEach(() => {
  vi.unstubAllEnvs();
  resetRoutePresetsCacheForTests();
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
  }
});

function writePresetsFile(presets: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "route-presets-916-"));
  tempDirs.push(dir);
  const path = join(dir, "route-presets.json");
  writeFileSync(path, `${JSON.stringify(presets, null, 2)}\n`);
  return path;
}

describe("#916 gpt-5.6-sol-low registry", () => {
  it("mirrors sol-high: same model string, effort low", () => {
    expect(resolveModelSlug("gpt-5.6-sol-low")).toEqual({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "low" },
    });
    expect(resolveModelSlug("gpt-5.6-sol-high")).toEqual({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "high" },
    });
  });
});

describe("#916 claude-tight factory lineup", () => {
  it("matches owner seating table (effort via sol-low registry row)", () => {
    const route = resolveRouteModels("claude-tight", {});

    expect(route.slots).toEqual({
      coder: "grok-4.5",
      coderFix: "grok-4.5",
      ship: "gpt-5.6-sol-low",
      merger: "gpt-5.6-sol-low",
      cmrCompleteness: "gpt-5.6-sol",
      cmrCorrectness: "gpt-5.6-sol",
      verify: "gpt-5.6-sol",
      fixer: "gpt-5.6-sol-low",
      cleanup: "gpt-5.6-sol-low",
      docRelease: "gpt-5.6-sol-low",
    });
    expect(route.legCollections.cmrReview).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "other", slug: "grok-4.5" },
      { family: "agy", slug: "agy", optional: true },
    ]);
    expect(route.tightFamilyViolations).toEqual([]);
    expect(route.slots).not.toHaveProperty("reviewer");
  });

  it("route smoke enumerates every model×pipe in the resolved lineup", () => {
    const keys = routeSmokeEntries(resolveRouteModels("claude-tight", {})).map(
      (entry) => entry.key,
    );

    for (const slot of MODEL_ROUTE_SLOTS) {
      const slug = resolveRouteModels("claude-tight", {}).slots[slot];
      expect(keys).toContain(`${slot}:${slug}`);
    }
    expect(keys).toContain("cmrReview:gpt-5.6-sol");
    expect(keys).toContain("cmrReview:grok-4.5");
    expect(keys).toContain("cmrReview:agy");
    // New combos that must be smoke-gated (#685 fail-closed).
    expect(keys).toContain("coder:grok-4.5");
    expect(keys).toContain("ship:gpt-5.6-sol-low");
    expect(keys).toContain("merger:gpt-5.6-sol-low");
  });
});

describe("#916 route presets config load + priority", () => {
  it("loads presets from config file (env path override)", () => {
    const path = writePresetsFile({
      "custom-tight": {
        tightFamilies: ["claude"],
        slots: {
          coder: "grok-4.5",
          coderFix: "grok-4.5",
          ship: "gpt-5.6-sol-low",
          merger: "gpt-5.6-sol-low",
          cmrCompleteness: "gpt-5.6-sol",
          cmrCorrectness: "gpt-5.6-sol",
          verify: "gpt-5.6-sol",
          fixer: "gpt-5.6-sol-low",
          cleanup: "gpt-5.6-sol-low",
          docRelease: "gpt-5.6-sol-low",
        },
        legCollections: {
          cmrReview: [
            { family: "codex", slug: "gpt-5.6-sol" },
            { family: "other", slug: "grok-4.5" },
            { family: "agy", slug: "agy", optional: true },
          ],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    const route = resolveRouteModels("custom-tight", {});
    expect(route.routeName).toBe("custom-tight");
    expect(route.slots.coder).toBe("grok-4.5");
    expect(route.slots.ship).toBe("gpt-5.6-sol-low");
  });

  it("env slot overrides beat config file preset values", () => {
    const path = writePresetsFile({
      "env-wins": {
        slots: {
          coder: "grok-4.5",
          coderFix: "grok-4.5",
          ship: "gpt-5.6-sol-low",
          merger: "gpt-5.6-sol-low",
          cmrCompleteness: "gpt-5.6-sol",
          cmrCorrectness: "gpt-5.6-sol",
          verify: "gpt-5.6-sol",
          fixer: "gpt-5.6-sol-low",
          cleanup: "gpt-5.6-sol-low",
          docRelease: "gpt-5.6-sol-low",
        },
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "env-wins");
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "gpt-5.6-terra");
    resetRoutePresetsCacheForTests();

    const route = activeModelRoute();
    expect(route.slots.coder).toBe("gpt-5.6-terra");
    expect(route.slots.ship).toBe("gpt-5.6-sol-low");
  });

  it("config file values beat built-in fallback for the same route name", () => {
    const path = writePresetsFile({
      normal: {
        slots: {
          coder: "grok-4.5",
          coderFix: "grok-4.5",
          ship: "gpt-5.6-sol-low",
          merger: "gpt-5.6-sol-low",
          cmrCompleteness: "gpt-5.6-sol",
          cmrCorrectness: "gpt-5.6-sol",
          verify: "gpt-5.6-sol",
          fixer: "gpt-5.6-sol-low",
          cleanup: "gpt-5.6-sol-low",
          docRelease: "gpt-5.6-sol-low",
        },
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    // Without config, factory normal coder is terra; with this file, grok wins.
    expect(resolveRouteModels("normal", {}).slots.coder).toBe("grok-4.5");
  });

  it("falls back to built-in when config path is missing", () => {
    vi.stubEnv(
      "ORCHESTRATOR_ROUTE_PRESETS_PATH",
      join(tmpdir(), "does-not-exist-916-route-presets.json"),
    );
    resetRoutePresetsCacheForTests();

    const route = resolveRouteModels("normal", {});
    expect(route.slots.coder).toBe("gpt-5.6-terra");
    expect(route.slots.ship).toBe("sonnet");
  });
});
