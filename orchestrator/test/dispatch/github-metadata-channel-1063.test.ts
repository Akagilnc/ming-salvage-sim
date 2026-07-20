import { describe, expect, it, vi } from "vitest";

import {
  withGithubHttpStatus,
} from "../../src/admissionPreflight.js";
import { classifyExternalCallFailure } from "../../src/externalCall.js";
import {
  DualChannelMetadataError,
  readGithubMetadataDualChannel,
  type MetadataChannel,
} from "../../src/githubMetadataChannel.js";

/**
 * What the dual-channel seam actually sees in production: the gh error AFTER the
 * `readMetadataWithRetry` boundary attached a numeric `httpStatus` (the raw gh
 * error only has exit code 1 + the status in stderr text — see the enrichment
 * test below and graphql-fallback-1063 for the end-to-end).
 */
function transient(msg: string): Error {
  return Object.assign(new Error(msg), { httpStatus: 503 });
}
function durable(status: number, msg: string): Error {
  return Object.assign(new Error(msg), { httpStatus: status });
}

describe("#1063 dual-channel gh metadata read", () => {
  it("REST succeeds: decodes REST payload, records rest, never calls GraphQL", () => {
    const graphql = vi.fn(() => ["should-not-run"]);
    const channels: MetadataChannel[] = [];
    const out = readGithubMetadataDualChannel<number>({
      rest: () => 41,
      graphql,
      decode: (p) => (p as number) + 1,
      onChannel: (c) => channels.push(c),
    });
    expect(out).toBe(42);
    expect(graphql).not.toHaveBeenCalled();
    expect(channels).toEqual(["rest"]);
  });

  it("REST transient exhaustion → GraphQL fallback decodes same shape, records graphql", () => {
    const channels: MetadataChannel[] = [];
    const decode = vi.fn((p: unknown) => (p as { n: number }).n);
    const out = readGithubMetadataDualChannel<number>({
      rest: () => {
        throw transient("REST 503 for 40 minutes");
      },
      graphql: () => ({ n: 7 }),
      decode,
      onChannel: (c) => channels.push(c),
    });
    expect(out).toBe(7);
    expect(channels).toEqual(["graphql"]);
    // single decode point: same decoder ran for the GraphQL payload.
    expect(decode).toHaveBeenCalledWith({ n: 7 });
  });

  it("REST durable (401) never switches channel: rethrows loud, GraphQL untouched", () => {
    const graphql = vi.fn(() => 0);
    const channels: MetadataChannel[] = [];
    expect(() =>
      readGithubMetadataDualChannel<number>({
        rest: () => {
          throw durable(401, "HTTP 401 bad credentials");
        },
        graphql,
        decode: (p) => p as number,
        onChannel: (c) => channels.push(c),
      }),
    ).toThrow(/401 bad credentials/);
    expect(graphql).not.toHaveBeenCalled();
    expect(channels).toEqual([]);
  });

  it("REST 200 but schema garbage (decode throws durable) does NOT fall back", () => {
    const graphql = vi.fn(() => ({ ok: true }));
    expect(() =>
      readGithubMetadataDualChannel({
        rest: () => ({ malformed: true }),
        graphql,
        decode: () => {
          throw new Error("blocked_by schema error: expected array");
        },
      }),
    ).toThrow(/schema error/);
    expect(graphql).not.toHaveBeenCalled();
  });

  it("negative: both channels fail → aggregated DualChannelMetadataError names both", () => {
    let thrown: unknown;
    try {
      readGithubMetadataDualChannel({
        rest: () => {
          throw transient("REST 503");
        },
        graphql: () => {
          throw new Error("GraphQL 502 too");
        },
        decode: (p) => p,
      });
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(DualChannelMetadataError);
    expect((thrown as Error).message).toMatch(/REST=REST 503/);
    expect((thrown as Error).message).toMatch(/GraphQL=GraphQL 502 too/);
  });
});

describe("#1063 gh HTTP status enrichment (the root of the false-green)", () => {
  /** The verified real `gh api` failure: exit code 1, HTTP status only in text. */
  function rawGhError(httpStatus: number, phrase: string): Error {
    const line = `gh: ${phrase} (HTTP ${httpStatus})`;
    return Object.assign(new Error(`Command failed: gh api …\n${line}\n`), {
      status: 1,
      stderr: `${line}\n`,
    });
  }

  it("raw gh 5xx is durable (exit code masks HTTP); enriched it classifies transient", () => {
    const raw = rawGhError(503, "Service Unavailable");
    // Before enrichment the exit code (1) is the only numeric field → durable,
    // which is exactly why the fallback never fired.
    expect(classifyExternalCallFailure(raw)).toBe("durable");
    // Enrichment recovers the numeric 503 from gh's own error line.
    expect(classifyExternalCallFailure(withGithubHttpStatus(raw))).toBe("transient");
  });

  it("enriched gh 404/401 stay durable (no fallback / needs a human)", () => {
    expect(
      classifyExternalCallFailure(withGithubHttpStatus(rawGhError(404, "Not Found"))),
    ).toBe("durable");
    expect(
      classifyExternalCallFailure(withGithubHttpStatus(rawGhError(401, "Bad credentials"))),
    ).toBe("durable");
  });

  it("network errno with no HTTP text still classifies transient (untouched path)", () => {
    const errno = Object.assign(new Error("socket hang up"), { code: "ECONNRESET" });
    expect(withGithubHttpStatus(errno)).toBe(errno);
    expect(classifyExternalCallFailure(errno)).toBe("transient");
  });
});
