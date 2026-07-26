/**
 * #916 — route presets leave code for a config file; claude-tight factory
 * lineup + gpt-5.6-sol-low registry row; env > config file (sole table;
 * missing custom path falls back to shipped factory JSON only).
 */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveModelSlug } from "../../src/modelRegistry.js";
import {
  MODEL_ROUTE_SLOTS,
  activeModelRoute,
  applyRelayBatonToRoute,
  applyTightRoutePolicy,
  getRoutePresets,
  resetRoutePresetsCacheForTests,
  resolveRouteModels,
  routeSmokeEntries,
  withCoderSlot,
} from "../../src/modelRoutes.js";
import {
  DEFAULT_POOL_MODELS,
  billingPoolForModelRef,
} from "../../src/quotaPoolTable.js";

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

function writeRawPresetsFile(body: string): string {
  const dir = mkdtempSync(join(tmpdir(), "route-presets-916-"));
  tempDirs.push(dir);
  const path = join(dir, "route-presets.json");
  writeFileSync(path, body);
  return path;
}

/** Minimal valid slot map for negative-path fixtures. */
function fullSlots(
  overrides: Partial<Record<(typeof MODEL_ROUTE_SLOTS)[number], string>> = {},
): Record<(typeof MODEL_ROUTE_SLOTS)[number], string> {
  return {
    coder: "grok-4.5",
    coderFix: "grok-4.5",
    ship: "gpt-5.6-sol-low",
    merger: "gpt-5.6-sol-low",
    cmrCompleteness: "gpt-5.6-sol",
    cmrCorrectness: "gpt-5.6-sol",
    collector: "grok-4.5",
    verify: "gpt-5.6-sol",
    fixer: "gpt-5.6-sol-low",
    cleanup: "gpt-5.6-sol-low",
    landing: "gpt-5.6-sol-low",
    ...overrides,
  };
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

  // #916 F10: factory utility seats (sol-low) + sol-high must bill on codex-5h.
  it("sol effort variants are codex-5h pool members", () => {
    expect(DEFAULT_POOL_MODELS["codex-5h"]).toEqual(
      expect.arrayContaining([
        "gpt-5.6-sol",
        "gpt-5.6-sol-low",
        "gpt-5.6-sol-high",
      ]),
    );
  });

  // Family CR H1: registry-only effort variants are not on CODER_ROSTER, but
  // billingPoolForModelRef must still resolve them to codex-5h (not fall through
  // poolForModelRef→unknown→default grok-build and mis-bind SuperGrok).
  it("billingPoolForModelRef maps sol effort variants + bare codex/grok correctly", () => {
    expect(billingPoolForModelRef("gpt-5.6-sol-low")).toBe("codex-5h");
    expect(billingPoolForModelRef("gpt-5.6-sol-high")).toBe("codex-5h");
    expect(billingPoolForModelRef("gpt-5.6-sol")).toBe("codex-5h");
    expect(billingPoolForModelRef("gpt-5.6-terra")).toBe("codex-5h");
    expect(billingPoolForModelRef("grok-4.5")).toBe("grok-build");
  });

  // family/914 Gemini R2 G2: registry keys are lowercase; trim+lower must
  // feed provider/registry lookup, not only DEFAULT_POOL_MODELS membership.
  it("billingPoolForModelRef trims and case-folds registry-only slugs", () => {
    expect(billingPoolForModelRef("  GPT-5.6-SOL-LOW  ")).toBe("codex-5h");
    expect(billingPoolForModelRef("Grok-4.5")).toBe("grok-build");
    expect(billingPoolForModelRef("  ")).toBeUndefined();
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
      collector: "grok-4.5",
      verify: "gpt-5.6-sol",
      fixer: "gpt-5.6-sol-low",
      cleanup: "gpt-5.6-sol-low",
      landing: "gpt-5.6-sol-low",
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
        slots: fullSlots(),
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

  it("negative: slot env overrides no longer beat config file preset (#936)", () => {
    const path = writePresetsFile({
      "env-wins": {
        slots: fullSlots(),
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
    // Preset coder from fullSlots(), not env.
    expect(route.slots.coder).toBe(fullSlots().coder);
    expect(route.slots.coder).not.toBe("gpt-5.6-terra");
    expect(route.slots.ship).toBe("gpt-5.6-sol-low");
  });

  it("custom path file is the sole table (no twin merge with factory routes)", () => {
    const path = writePresetsFile({
      normal: {
        slots: fullSlots({ coder: "grok-4.5", coderFix: "grok-4.5" }),
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    // File wins for listed routes; factory-only names are not silently merged.
    expect(resolveRouteModels("normal", {}).slots.coder).toBe("grok-4.5");
    expect(() => resolveRouteModels("claude-tight", {})).toThrow(
      /unknown route "claude-tight"/,
    );
  });

  it("falls back to shipped factory JSON when custom path is missing", () => {
    vi.stubEnv(
      "ORCHESTRATOR_ROUTE_PRESETS_PATH",
      join(tmpdir(), "does-not-exist-916-route-presets.json"),
    );
    resetRoutePresetsCacheForTests();

    // Sole source remains config/route-presets.json — not a hand-copied TS table.
    const route = resolveRouteModels("normal", {});
    expect(route.slots.coder).toBe("gpt-5.6-terra");
    expect(route.slots.ship).toBe("sonnet");
    expect(resolveRouteModels("claude-tight", {}).slots.coder).toBe("grok-4.5");
  });

  // family/914 Gemini R3 G5: cache must key by the path actually loaded
  // (loadPath), not the requested path. Missing custom → factory load must
  // not be cached under the missing path, or a later-created file is ignored.
  it("reloads when a previously-missing custom presets path appears (same env, no cache reset)", () => {
    const dir = mkdtempSync(join(tmpdir(), "route-presets-916-"));
    tempDirs.push(dir);
    const path = join(dir, "route-presets.json"); // does not exist yet

    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    // Missing custom path → factory fallback (within one cache lifetime).
    expect(resolveRouteModels("claude-tight", {}).slots.coder).toBe("grok-4.5");

    // File appears later with a route factory never had — no reset between.
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          "late-custom": {
            slots: fullSlots({
              coder: "gpt-5.6-terra",
              coderFix: "gpt-5.6-terra",
            }),
            legCollections: {
              cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
            },
          },
        },
        null,
        2,
      )}\n`,
    );

    // Must re-resolve against the new file, not serve stale factory under the
    // requested-path cache key.
    const route = resolveRouteModels("late-custom", {});
    expect(route.routeName).toBe("late-custom");
    expect(route.slots.coder).toBe("gpt-5.6-terra");
  });

  // G5 follow-up: cache check must compare against loadPath (resolved after
  // missing-custom → DEFAULT fallback), not the requested custom path. Otherwise
  // every getRoutePresets under a missing custom path re-reads factory JSON.
  it("cache-hits factory DEFAULT when missing custom path is resolved twice without reset", () => {
    const dir = mkdtempSync(join(tmpdir(), "route-presets-916-"));
    tempDirs.push(dir);
    const path = join(dir, "route-presets-missing.json"); // never created

    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    const first = getRoutePresets();
    const second = getRoutePresets();
    // Same object ⇒ loadPath-keyed cache hit (no second factory I/O).
    expect(second).toBe(first);
    expect(resolveRouteModels("claude-tight", {}).slots.coder).toBe("grok-4.5");
  });
});

describe("#914 C1 custom tightFamilies survive route mutations", () => {
  // Disease: withCoderSlot / withSingleRouteSlot re-fetched tightFamilies via
  // tightFamiliesForRoute(routeName) → process.env, not the resolve-time env.
  // Custom ORCHESTRATOR_ROUTE_PRESETS_PATH only in the resolve env arg dropped
  // policy to [] after mutation — teeth gone.
  it("withCoderSlot still enforces tightFamilies resolved from custom presets path env", () => {
    const path = writePresetsFile({
      "custom-tight": {
        tightFamilies: ["claude"],
        slots: fullSlots(),
        legCollections: {
          cmrReview: [
            { family: "codex", slug: "gpt-5.6-sol" },
            { family: "other", slug: "grok-4.5" },
          ],
        },
      },
    });
    // Resolve with env ARG only — process.env is NOT stubbed with the path.
    // Mutations must not re-consult process.env for tightFamilies.
    resetRoutePresetsCacheForTests();
    const route = resolveRouteModels(
      "custom-tight",
      {},
      {},
      {},
      { ORCHESTRATOR_ROUTE_PRESETS_PATH: path },
    );
    expect(route.tightFamilies).toEqual(["claude"]);
    expect(route.tightFamilyViolations).toEqual([]);

    const mutated = withCoderSlot(route, "opus");
    expect(mutated.tightFamilies).toEqual(["claude"]);
    expect(mutated.tightFamilyViolations).toEqual([
      { slot: "coder", slug: "opus", family: "claude" },
      { slot: "coderFix", slug: "opus", family: "claude" },
    ]);
    expect(applyTightRoutePolicy(mutated).kind).toBe(
      "stop",
    );
  });

  it("applyRelayBatonToRoute / withSingleRouteSlot keep custom tight policy teeth", () => {
    const path = writePresetsFile({
      "custom-tight": {
        tightFamilies: ["claude"],
        slots: fullSlots(),
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    resetRoutePresetsCacheForTests();
    const route = resolveRouteModels(
      "custom-tight",
      {},
      {},
      {},
      { ORCHESTRATOR_ROUTE_PRESETS_PATH: path },
    );

    const relayed = applyRelayBatonToRoute(route, { slug: "opus" }, "S7", {
      slots: ["ship"],
    });
    expect(relayed.tightFamilies).toEqual(["claude"]);
    expect(relayed.tightFamilyViolations).toEqual([
      { slot: "ship", slug: "opus", family: "claude" },
    ]);
    expect(applyTightRoutePolicy(relayed).kind).toBe(
      "stop",
    );
  });
});

describe("#916 route presets parse / resolve fail-loud paths", () => {
  it("throws on bad JSON with path in the message", () => {
    const path = writeRawPresetsFile("{ not-json");
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("normal", {})).toThrow(
      new RegExp(
        `failed to parse route presets at ${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
      ),
    );
  });

  it("throws when a required slot is missing", () => {
    const slots = fullSlots();
    delete (slots as { coder?: string }).coder;
    const path = writePresetsFile({
      broken: {
        slots,
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken" missing slot "coder"/,
    );
  });

  it("throws on unknown slot keys", () => {
    const path = writePresetsFile({
      broken: {
        slots: { ...fullSlots(), reviewer: "opus" },
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken" has unknown slot "reviewer"/,
    );
  });

  it("throws when cmrReview is empty", () => {
    const path = writePresetsFile({
      broken: {
        slots: fullSlots(),
        legCollections: { cmrReview: [] },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken" missing non-empty cmrReview legs/,
    );
  });

  it("rejects top-level cmrReview without legCollections (single nested form only)", () => {
    const path = writePresetsFile({
      broken: {
        slots: fullSlots(),
        // Dual form DELETE target: top-level cmrReview must not load.
        cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken" missing legCollections/,
    );
  });

  it("throws when declared leg family disagrees with registry", () => {
    const path = writePresetsFile({
      broken: {
        slots: fullSlots(),
        legCollections: {
          // gpt-5.6-sol is codex in registry — claude declaration is a lie.
          cmrReview: [{ family: "claude", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /cmr review leg "gpt-5.6-sol" declares family "claude" but registry says "codex"/,
    );
  });

  // family/914 Gemini R2 G3: invalid family string must not silently fall
  // back to modelFamilyForSlug — config load fail-loud.
  it("throws on invalid cmrReview leg family string", () => {
    const path = writePresetsFile({
      broken: {
        slots: fullSlots(),
        legCollections: {
          cmrReview: [{ family: "openai", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken".*cmrReview leg "gpt-5.6-sol".*invalid family "openai"/,
    );
  });

  // family/914 Gemini R2 G4: LEG_COLLECTION_SET must reject unknown keys the
  // same way SLOT_SET rejects unknown slot keys.
  it("throws on unknown legCollection keys", () => {
    const path = writePresetsFile({
      broken: {
        slots: fullSlots(),
        legCollections: {
          cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
          extraReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
        },
      },
    });
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", path);
    resetRoutePresetsCacheForTests();

    expect(() => resolveRouteModels("broken", {})).toThrow(
      /route preset "broken" has unknown legCollection "extraReview"/,
    );
  });
});
