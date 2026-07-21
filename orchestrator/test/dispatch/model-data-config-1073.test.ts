/**
 * #1073 / ADR 0146 S1 — model-data config base: env-path injection,
 * read-at-use loader, fail-closed shape validation.
 * #1074 S2 switched the coder roster onto this loader (constants deleted).
 * #1075 S3 switched the model registry onto this loader (data rows deleted
 * from code; provider factories stay in modelRegistry).
 */
import { mkdtempSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getCoderRoster } from "../../src/coderRoster.js";
import {
  MODEL_DATA_PATH_ENV,
  loadModelData,
  resolveModelDataPath,
} from "../../src/modelDataConfig.js";

const tempDirs: string[] = [];
const afterEachFiles: string[] = [];

afterEach(() => {
  vi.unstubAllEnvs();
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
  }
  while (afterEachFiles.length > 0) {
    const file = afterEachFiles.pop();
    if (file !== undefined) {
      try {
        unlinkSync(file);
      } catch {
        // best-effort cleanup
      }
    }
  }
});

function writeModelDataFile(body: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "model-data-1073-"));
  tempDirs.push(dir);
  const path = join(dir, "model-data.json");
  writeFileSync(
    path,
    typeof body === "string" ? body : `${JSON.stringify(body, null, 2)}\n`,
  );
  return path;
}

/** Minimal valid document for negative-path mutations. */
function validDoc(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    version: "test-1",
    roster: [
      {
        id: "grok-4.5",
        slug: "grok-4.5",
        pool: "supergrok",
      },
    ],
    defaultCoderRecOrder: ["grok-4.5"],
    registry: {
      "grok-4.5": {
        provider: "grok",
        model: "grok-4.5",
        family: "other",
        strongLeg: true,
      },
    },
    ...overrides,
  };
}

describe("#1073 model-data config path resolution", () => {
  it("uses ORCHESTRATOR_MODEL_DATA_PATH when set (absolute)", () => {
    const path = writeModelDataFile(validDoc());
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(resolveModelDataPath()).toBe(path);
  });

  it("resolves cwd-relative env override", () => {
    const relative = "tmp-model-data-1073-relative.json";
    const abs = join(process.cwd(), relative);
    writeFileSync(abs, `${JSON.stringify(validDoc(), null, 2)}\n`);
    afterEachFiles.push(abs);
    vi.stubEnv(MODEL_DATA_PATH_ENV, relative);
    expect(resolveModelDataPath()).toBe(abs);
    expect(loadModelData().version).toBe("test-1");
  });

  it("default path ends with config/model-data.json when env unset", () => {
    delete process.env[MODEL_DATA_PATH_ENV];
    const path = resolveModelDataPath({});
    expect(path.replace(/\\/g, "/")).toMatch(/config\/model-data\.json$/);
  });
});

describe("#1073 loadModelData read-at-use (zero rebuild)", () => {
  it("edit config → next loader call returns new values", () => {
    const path = writeModelDataFile(validDoc({ version: "v1" }));
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    const first = loadModelData();
    expect(first.version).toBe("v1");
    expect(first.roster).toHaveLength(1);

    writeFileSync(
      path,
      `${JSON.stringify(
        validDoc({
          version: "v2-hot",
          roster: [
            {
              id: "sol@low",
              slug: "gpt-5.6-sol-low",
              pool: "codex",
            },
            {
              id: "grok-4.5",
              slug: "grok-4.5",
              pool: "supergrok",
            },
          ],
          defaultCoderRecOrder: ["sol@low", "grok-4.5"],
          registry: {
            "gpt-5.6-sol-low": {
              provider: "codex",
              model: "gpt-5.6-sol",
              family: "codex",
              options: { effort: "low" },
              strongLeg: true,
            },
            "grok-4.5": {
              provider: "grok",
              model: "grok-4.5",
              family: "other",
            },
          },
        }),
        null,
        2,
      )}\n`,
    );

    const second = loadModelData();
    expect(second.version).toBe("v2-hot");
    expect(second.roster.map((e) => e.id)).toEqual(["sol@low", "grok-4.5"]);
    expect(second.defaultCoderRecOrder).toEqual(["sol@low", "grok-4.5"]);
    expect(second.registry["gpt-5.6-sol-low"]?.options).toEqual({
      effort: "low",
    });
  });

  it("shipped factory loads without env override", () => {
    delete process.env[MODEL_DATA_PATH_ENV];
    const data = loadModelData({});
    expect(data.version.length).toBeGreaterThan(0);
    expect(data.roster.length).toBeGreaterThan(0);
    expect(Object.keys(data.registry).length).toBeGreaterThan(0);
    expect(data.defaultCoderRecOrder.length).toBeGreaterThan(0);
  });
});

describe("#1073 loadModelData fail-closed (path + reason)", () => {
  it("missing file → loud error with path, no silent fallback", () => {
    const missing = join(tmpdir(), "model-data-1073-does-not-exist.json");
    vi.stubEnv(MODEL_DATA_PATH_ENV, missing);
    expect(() => loadModelData()).toThrow(
      new RegExp(
        `model data file not found:.*${missing.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
      ),
    );
  });

  it("invalid JSON → loud error with path and parse reason", () => {
    const path = writeModelDataFile("{ not json");
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(
      new RegExp(`failed to parse model data at ${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`),
    );
  });

  it("non-object top-level → loud error with path", () => {
    const path = writeModelDataFile([1, 2, 3]);
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(
      new RegExp(`model data file must be a JSON object: ${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`),
    );
  });

  it("missing version → loud error with path and field reason", () => {
    const doc = validDoc();
    delete doc.version;
    const path = writeModelDataFile(doc);
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/missing non-empty string "version"/);
    expect(() => loadModelData()).toThrow(new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  it("bad roster entry shape → loud error with path and reason", () => {
    const path = writeModelDataFile(
      validDoc({
        roster: [{ id: "x", slug: "y" /* pool missing */ }],
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/roster\[0\].*pool/);
    expect(() => loadModelData()).toThrow(new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  it("unknown roster pool → loud error", () => {
    const path = writeModelDataFile(
      validDoc({
        roster: [{ id: "x", slug: "y", pool: "openai" }],
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/unknown pool "openai"/);
  });

  it("empty roster → loud error", () => {
    const path = writeModelDataFile(validDoc({ roster: [] }));
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/roster must be a non-empty array/);
  });

  it("bad registry row → loud error with slug and path", () => {
    const path = writeModelDataFile(
      validDoc({
        registry: {
          "bad-slug": { provider: "nope", model: "m", family: "codex" },
        },
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/registry\["bad-slug"\].*provider/);
    expect(() => loadModelData()).toThrow(new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  it("empty registry → loud error", () => {
    const path = writeModelDataFile(validDoc({ registry: {} }));
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/registry must be a non-empty object/);
  });

  it("missing defaultCoderRecOrder → loud error", () => {
    const doc = validDoc();
    delete doc.defaultCoderRecOrder;
    const path = writeModelDataFile(doc);
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(/defaultCoderRecOrder/);
  });

  it("defaultCoderRecOrder unknown roster id → loud error (fail-closed referential integrity)", () => {
    const path = writeModelDataFile(
      validDoc({
        defaultCoderRecOrder: ["grok-4.5", "not-a-roster-id"],
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);
    expect(() => loadModelData()).toThrow(
      /defaultCoderRecOrder references unknown roster id "not-a-roster-id"/,
    );
    expect(() => loadModelData()).toThrow(
      new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
  });
});

// Dual-track residual closed: S2 (#1074) put roster on the loader; S3 (#1075)
// put registry on the loader. Registry resolution is covered by #1075 tests.
describe("#1074 roster on loader matches factory model-data", () => {
  it("getCoderRoster matches shipped factory model-data roster", () => {
    delete process.env[MODEL_DATA_PATH_ENV];
    const data = loadModelData({});
    expect(getCoderRoster({}).map((e) => e.id)).toEqual(
      data.roster.map((e) => e.id),
    );
  });
});
