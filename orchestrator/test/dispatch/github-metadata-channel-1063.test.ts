import { describe, expect, it, vi } from "vitest";

import {
  DualChannelMetadataError,
  readGithubMetadataDualChannel,
  type MetadataChannel,
} from "../../src/githubMetadataChannel.js";

/** A 5xx/network class error `classifyExternalCallFailure` treats as transient. */
function transient(msg: string): Error {
  return Object.assign(new Error(msg), { status: 503 });
}
/** A 401/403 class error `classifyExternalCallFailure` treats as durable. */
function durable(status: number, msg: string): Error {
  return Object.assign(new Error(msg), { status });
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
