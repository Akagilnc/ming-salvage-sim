/**
 * #1075 / ADR 0146 S3 — registry data rows switch to S1 config read-at-use;
 * provider wiring stays in code; constant data rows deleted.
 */
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MODEL_DATA_PATH_ENV,
  loadModelData,
} from "../../src/modelDataConfig.js";
import {
  agentForSlug,
  modelFamilyForSlug,
  modelIsStrongLeg,
  providerForModelSlug,
  resolveModelSlug,
} from "../../src/modelRegistry.js";
import {
  activeModelRoute,
  resetRoutePresetsCacheForTests,
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

function writeModelDataFile(body: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "model-registry-1075-"));
  tempDirs.push(dir);
  const path = join(dir, "model-data.json");
  writeFileSync(path, `${JSON.stringify(body, null, 2)}\n`);
  return path;
}

/** Factory-shaped doc with shipped-like defaults + optional overrides. */
function baseDoc(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    version: "test-1075",
    roster: [
      {
        id: "grok-4.5",
        slug: "grok-4.5",
        pool: "supergrok",
      },
      {
        id: "terra@med",
        slug: "gpt-5.6-terra",
        pool: "codex",
      },
    ],
    defaultCoderRecOrder: ["grok-4.5", "terra@med"],
    registry: {
      "grok-4.5": {
        provider: "grok",
        model: "grok-4.5",
        family: "other",
        strongLeg: true,
      },
      "gpt-5.6-terra": {
        provider: "codex",
        model: "gpt-5.6-terra",
        options: { effort: "low" },
        family: "codex",
        strongLeg: true,
      },
      "gpt-5.6-sol": {
        provider: "codex",
        model: "gpt-5.6-sol",
        options: { effort: "medium" },
        family: "codex",
        strongLeg: true,
      },
      "gpt-5.6-sol-low": {
        provider: "codex",
        model: "gpt-5.6-sol",
        options: { effort: "low" },
        family: "codex",
        strongLeg: true,
      },
      sonnet: {
        provider: "claudeCode",
        model: "claude-sonnet-5",
        options: { permissionMode: "bypassPermissions" },
        family: "claude",
      },
      haiku: {
        provider: "claudeCode",
        model: "claude-haiku-4-5",
        options: { permissionMode: "bypassPermissions" },
        family: "claude",
      },
      opus: {
        provider: "claudeCode",
        model: "claude-opus-4-8",
        options: { permissionMode: "bypassPermissions" },
        family: "claude",
        strongLeg: true,
      },
      agy: {
        provider: "agy",
        model: "",
        family: "agy",
      },
    },
    ...overrides,
  };
}

describe("#1075 registry from config — zero-code new model row", () => {
  it("config-only kimi-class slug resolves without code change", () => {
    const path = writeModelDataFile(
      baseDoc({
        registry: {
          ...(baseDoc().registry as Record<string, unknown>),
          "kimi-k2": {
            provider: "codex",
            model: "kimi-k2",
            options: { effort: "medium" },
            family: "other",
            strongLeg: true,
          },
        },
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    expect(resolveModelSlug("kimi-k2")).toEqual({
      provider: "codex",
      model: "kimi-k2",
      options: { effort: "medium" },
    });
    expect(modelFamilyForSlug("kimi-k2")).toBe("other");
    expect(modelIsStrongLeg("kimi-k2")).toBe(true);
    expect(providerForModelSlug("kimi-k2")).toBe("codex");
  });

  it("route slot may reference config-only slug (zero code change)", () => {
    const modelPath = writeModelDataFile(
      baseDoc({
        registry: {
          ...(baseDoc().registry as Record<string, unknown>),
          "kimi-k2": {
            provider: "codex",
            model: "kimi-k2",
            family: "other",
          },
        },
      }),
    );
    // #936: slot env no longer overrides presets — write a route that names
    // the config-only slug so route resolution exercises the live registry.
    const presetsDir = mkdtempSync(join(tmpdir(), "route-presets-1075-"));
    tempDirs.push(presetsDir);
    const presetsPath = join(presetsDir, "route-presets.json");
    writeFileSync(
      presetsPath,
      `${JSON.stringify(
        {
          "kimi-route": {
            slots: {
              coder: "kimi-k2",
              coderFix: "kimi-k2",
              ship: "sonnet",
              merger: "sonnet",
              cmrCompleteness: "gpt-5.6-sol",
              cmrCorrectness: "gpt-5.6-sol",
              verify: "gpt-5.6-sol",
              fixer: "sonnet",
              cleanup: "sonnet",
              landing: "sonnet",
            },
            legCollections: {
              cmrReview: [{ family: "other", slug: "kimi-k2" }],
            },
          },
        },
        null,
        2,
      )}\n`,
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, modelPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetsPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "kimi-route");
    resetRoutePresetsCacheForTests();

    const route = activeModelRoute();
    expect(route.slots.coder).toBe("kimi-k2");
    expect(resolveModelSlug(route.slots.coder).model).toBe("kimi-k2");
    expect(route.legCollections.cmrReview.map((l) => l.slug)).toContain(
      "kimi-k2",
    );
  });

  it("agentForSlug builds provider for config-only row", () => {
    const path = writeModelDataFile(
      baseDoc({
        registry: {
          ...(baseDoc().registry as Record<string, unknown>),
          "kimi-k2": {
            provider: "codex",
            model: "kimi-k2",
            options: { effort: "high" },
            family: "other",
          },
        },
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    const command = agentForSlug("kimi-k2")
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false })
      .command;
    expect(command).toContain("kimi-k2");
    expect(command).toContain('model_reasoning_effort="high"');
  });
});

describe("#1075 registry read-at-use (no constant table)", () => {
  it("edit registry row → next resolveModelSlug sees new values", () => {
    const path = writeModelDataFile(
      baseDoc({
        registry: {
          ...(baseDoc().registry as Record<string, unknown>),
          "gpt-5.6-terra": {
            provider: "codex",
            model: "gpt-5.6-terra",
            options: { effort: "low" },
            family: "codex",
          },
        },
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    expect(resolveModelSlug("gpt-5.6-terra").options).toEqual({ effort: "low" });

    writeFileSync(
      path,
      `${JSON.stringify(
        baseDoc({
          registry: {
            ...(baseDoc().registry as Record<string, unknown>),
            "gpt-5.6-terra": {
              provider: "codex",
              model: "gpt-5.6-terra",
              options: { effort: "high" },
              family: "codex",
            },
          },
        }),
        null,
        2,
      )}\n`,
    );

    expect(resolveModelSlug("gpt-5.6-terra").options).toEqual({
      effort: "high",
    });
  });

  it("shipped factory still resolves live slugs via loader", () => {
    delete process.env[MODEL_DATA_PATH_ENV];
    expect(resolveModelSlug("grok-4.5").provider).toBe("grok");
    expect(resolveModelSlug("gpt-5.6-sol-low")).toMatchObject({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "low" },
    });
    expect(loadModelData({}).registry["gpt-5.6-sol-low"]?.options).toEqual({
      effort: "low",
    });
  });
});

describe("#1075 fail-closed — unknown provider / unknown slug", () => {
  it("config row with unknown provider → load fails loud (path + reason)", () => {
    const path = writeModelDataFile(
      baseDoc({
        registry: {
          "bad-model": {
            provider: "kimi-cloud",
            model: "kimi-k2",
            family: "other",
          },
        },
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/provider/);
    expect(() => loadModelData()).toThrow(
      new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
    expect(() => resolveModelSlug("bad-model")).toThrow(/provider|model data/);
  });

  it("unknown slug → resolveModelSlug fails closed (no silent default)", () => {
    const path = writeModelDataFile(baseDoc());
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => resolveModelSlug("definitely-not-registered-xyz")).toThrow(
      /unknown model slug/,
    );
    expect(providerForModelSlug("definitely-not-registered-xyz")).toBeUndefined();
  });

  it("route naming unknown registry slug fails closed", () => {
    const modelPath = writeModelDataFile(baseDoc());
    const presetsDir = mkdtempSync(join(tmpdir(), "route-presets-1075-bad-"));
    tempDirs.push(presetsDir);
    const presetsPath = join(presetsDir, "route-presets.json");
    writeFileSync(
      presetsPath,
      `${JSON.stringify(
        {
          "bad-route": {
            slots: {
              coder: "not-a-real-slug",
              coderFix: "gpt-5.6-terra",
              ship: "sonnet",
              merger: "sonnet",
              cmrCompleteness: "gpt-5.6-sol",
              cmrCorrectness: "gpt-5.6-sol",
              verify: "gpt-5.6-sol",
              fixer: "sonnet",
              cleanup: "sonnet",
              landing: "sonnet",
            },
            legCollections: {
              cmrReview: [{ family: "codex", slug: "gpt-5.6-sol" }],
            },
          },
        },
        null,
        2,
      )}\n`,
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, modelPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", presetsPath);
    vi.stubEnv("ORCHESTRATOR_ROUTE", "bad-route");
    resetRoutePresetsCacheForTests();
    expect(() => activeModelRoute()).toThrow(
      /unknown model slug|not-a-real-slug/,
    );
  });
});
