/**
 * #1074 / ADR 0146 S2 — coder roster consumes S1 model-data loader (用时现读);
 * in-code CODER_ROSTER constant table deleted; docs pointer only.
 *
 * Seams:
 *   1. getCoderRoster / lookupCoderRosterEntry / resolveAdvanceCoderSuggestion
 *      re-read config every call (edit file → next call sees new candidate)
 *   2. Negative: unknown token stay_put; broken/missing config fail-closed
 *   3. No second source of truth: exported CODER_ROSTER constant is gone
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as coderRoster from "../../src/coderRoster.js";
import {
  getCoderRoster,
  getCoderRosterVersion,
  getDefaultCoderRecOrder,
  lookupCoderRosterEntry,
  resolveAdvanceCoderSuggestion,
  resolveCoderRecOrder,
} from "../../src/coderRoster.js";
import {
  MODEL_DATA_PATH_ENV,
  loadModelData,
} from "../../src/modelDataConfig.js";

const tempDirs: string[] = [];

afterEach(() => {
  vi.unstubAllEnvs();
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
  }
});

function writeModelDataFile(body: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "model-data-1074-"));
  tempDirs.push(dir);
  const path = join(dir, "model-data.json");
  writeFileSync(path, `${JSON.stringify(body, null, 2)}\n`);
  return path;
}

/** Minimal valid document seeded with factory-shaped rows for hot-edit demos. */
function baseDoc(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    version: "1074-test-v1",
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
        aliases: ["terra@med+fast", "gpt-5.6-terra"],
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
        family: "codex",
        options: { effort: "low" },
      },
    },
    ...overrides,
  };
}

describe("#1074 S2 roster is config-backed (no constant table)", () => {
  it("does not export an in-code CODER_ROSTER / DEFAULT_CODER_REC_ORDER constant", () => {
    // Second-source residual would reintroduce the #1003 PR tax.
    expect(
      Object.prototype.hasOwnProperty.call(coderRoster, "CODER_ROSTER"),
    ).toBe(false);
    expect(
      Object.prototype.hasOwnProperty.call(coderRoster, "CODER_ROSTER_VERSION"),
    ).toBe(false);
    expect(
      Object.prototype.hasOwnProperty.call(
        coderRoster,
        "DEFAULT_CODER_REC_ORDER",
      ),
    ).toBe(false);
    expect(typeof getCoderRoster).toBe("function");
    expect(typeof getCoderRosterVersion).toBe("function");
    expect(typeof getDefaultCoderRecOrder).toBe("function");
  });

  it("shipped factory path yields the live roster without env override", () => {
    delete process.env[MODEL_DATA_PATH_ENV];
    const data = loadModelData({});
    const roster = getCoderRoster({});
    expect(roster.length).toBeGreaterThan(0);
    expect(roster.map((e) => e.id)).toEqual(data.roster.map((e) => e.id));
    expect(getDefaultCoderRecOrder({})).toEqual(data.defaultCoderRecOrder);
    expect(getCoderRosterVersion({})).toBe(data.version);
  });
});

describe("#1074 #1003 scenario: edit config → next advance picks new candidate", () => {
  it("adding a roster candidate is visible on the next resolveAdvanceCoderSuggestion", () => {
    const path = writeModelDataFile(baseDoc());
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    // Before edit: unknown candidate → stay_put (negative baseline).
    const before = resolveAdvanceCoderSuggestion("sol@low", "grok-4.5");
    expect(before).toEqual({
      kind: "stay_put",
      reason: "unknown_target",
      suggestion: "sol@low",
      currentSlug: "grok-4.5",
    });
    expect(lookupCoderRosterEntry("sol@low")).toBeUndefined();

    // #1003-shaped edit: add sol@low (no rebuild, no PR).
    const doc = JSON.parse(readFileSync(path, "utf8")) as Record<
      string,
      unknown
    >;
    const roster = [
      ...(doc.roster as Array<Record<string, unknown>>),
      {
        id: "sol@low",
        slug: "gpt-5.6-sol-low",
        pool: "codex",
      },
    ];
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          ...doc,
          version: "1074-hot-add-sol-low",
          roster,
          registry: {
            ...(doc.registry as Record<string, unknown>),
            "gpt-5.6-sol-low": {
              provider: "codex",
              model: "gpt-5.6-sol",
              family: "codex",
              options: { effort: "low" },
            },
          },
        },
        null,
        2,
      )}\n`,
    );

    // Next call (no process restart) sees the new candidate.
    expect(lookupCoderRosterEntry("sol@low")).toMatchObject({
      id: "sol@low",
      slug: "gpt-5.6-sol-low",
      pool: "codex",
    });
    const after = resolveAdvanceCoderSuggestion("sol@low", "grok-4.5");
    expect(after.kind).toBe("advanced");
    if (after.kind === "advanced") {
      expect(after.entry.id).toBe("sol@low");
      expect(after.entry.slug).toBe("gpt-5.6-sol-low");
      expect(after.fromSlug).toBe("grok-4.5");
    }
    expect(getCoderRosterVersion()).toBe("1074-hot-add-sol-low");
    expect(
      resolveCoderRecOrder("Coder-Rec: grok-4.5 → sol@low").map((e) => e.id),
    ).toEqual(["grok-4.5", "sol@low"]);
  });

  it("negative: removing a candidate makes the next advance stay_put", () => {
    const path = writeModelDataFile(
      baseDoc({
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
      }),
    );
    vi.stubEnv(MODEL_DATA_PATH_ENV, path);

    expect(resolveAdvanceCoderSuggestion("terra@med", "grok-4.5").kind).toBe(
      "advanced",
    );

    writeFileSync(
      path,
      `${JSON.stringify(
        baseDoc({
          version: "1074-hot-drop-terra",
          roster: [
            {
              id: "grok-4.5",
              slug: "grok-4.5",
              pool: "supergrok",
            },
          ],
          defaultCoderRecOrder: ["grok-4.5"],
        }),
        null,
        2,
      )}\n`,
    );

    expect(resolveAdvanceCoderSuggestion("terra@med", "grok-4.5")).toEqual({
      kind: "stay_put",
      reason: "unknown_target",
      suggestion: "terra@med",
      currentSlug: "grok-4.5",
    });
    expect(lookupCoderRosterEntry("terra@med")).toBeUndefined();
  });

  it("negative: missing model-data file fail-closes on roster read", () => {
    vi.stubEnv(MODEL_DATA_PATH_ENV, join(tmpdir(), "missing-1074-model-data.json"));
    expect(() => getCoderRoster()).toThrow(/model data file not found/);
    expect(() => lookupCoderRosterEntry("grok-4.5")).toThrow(
      /model data file not found/,
    );
    expect(() => resolveAdvanceCoderSuggestion("grok-4.5", "terra@med")).toThrow(
      /model data file not found/,
    );
  });
});
