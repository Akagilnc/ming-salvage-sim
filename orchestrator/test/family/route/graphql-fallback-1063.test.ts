import { describe, expect, it, vi } from "vitest";

import { readFamilyEpic, type Sh } from "../../../src/familyDriver.js";
import { type MetadataChannel } from "../../../src/githubMetadataChannel.js";

const REPO = "Akagilnc/ming-salvage-sim";

/** A 5xx error `classifyExternalCallFailure` treats as transient (fallback-eligible). */
function http5xx(msg: string): Error {
  return Object.assign(new Error(msg), { status: 503 });
}

function isGraphql(args: string[]): boolean {
  return args[0] === "api" && args[1] === "graphql";
}
function graphqlNumber(args: string[]): number {
  const raw = args.find((a) => a.startsWith("number="));
  return Number(raw?.slice("number=".length));
}

describe("#1063 admission GraphQL fallback (readFamilyEpic)", () => {
  it("REST 5xx persists on sub_issues + blocked_by → GraphQL serves same data, epic builds, channel recorded", () => {
    const recorded: Array<{ resource: string; issue: number; channel: MetadataChannel }> = [];
    const sh: Sh = (file, args) => {
      expect(file).toBe("gh");
      // gh issue view (body/author) — module declarations, REST-only, healthy.
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: Number(args[2]), body: "", author: { login: "Akagilnc" } });
      }
      if (isGraphql(args)) {
        const query = args[3] ?? "";
        if (query.includes("subIssues")) {
          // GraphQL sub_issues shape: repository.issue.subIssues.nodes.
          return JSON.stringify({
            data: { repository: { issue: { subIssues: { nodes: [{ number: 11 }, { number: 12 }] } } } },
          });
        }
        // GraphQL blocked_by shape: repository.issue.blockedBy.nodes, IssueState enum.
        const n = graphqlNumber(args);
        const nodes = n === 12 ? [{ number: 11, state: "OPEN" }] : [];
        return JSON.stringify({ data: { repository: { issue: { blockedBy: { nodes } } } } });
      }
      // Every REST metadata endpoint is in a persistent 5xx outage.
      if (String(args[1]).includes("/sub_issues") || String(args[1]).includes("/blocked_by")) {
        throw http5xx("REST 503: dependencies temporarily unavailable");
      }
      throw new Error(`unexpected REST call: ${args.join(" ")}`);
    };

    const epic = readFamilyEpic(291, REPO, sh, new Map(), (resource, issue, channel) =>
      recorded.push({ resource, issue, channel }),
    );

    expect(epic).toEqual({
      issue: 291,
      children: [
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [11] },
      ],
    });
    // Ledger records the transport actually used: every read fell back to graphql.
    expect(recorded).toContainEqual({ resource: "sub_issues", issue: 291, channel: "graphql" });
    expect(recorded).toContainEqual({ resource: "blocked_by", issue: 291, channel: "graphql" });
    expect(recorded).toContainEqual({ resource: "blocked_by", issue: 12, channel: "graphql" });
    expect(recorded.every((r) => r.channel === "graphql")).toBe(true);
  });

  it("REST healthy → GraphQL is never invoked, channel recorded as rest", () => {
    const recorded: MetadataChannel[] = [];
    const graphqlCalls: string[] = [];
    const sh: Sh = (file, args) => {
      if (isGraphql(args)) {
        graphqlCalls.push(args.join(" "));
        throw new Error("graphql must not be called when REST is healthy");
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: Number(args[2]), body: "", author: { login: "Akagilnc" } });
      }
      if (String(args[1]).includes("/sub_issues")) {
        return JSON.stringify([{ number: 11 }, { number: 12 }]);
      }
      const n = Number(/issues\/(\d+)\//.exec(args[1] ?? "")?.[1]);
      return n === 12 ? JSON.stringify([{ number: 11, state: "open" }]) : "[]";
    };

    const epic = readFamilyEpic(291, REPO, sh, new Map(), (_r, _i, channel) =>
      recorded.push(channel),
    );

    expect(epic.children).toEqual([
      { issue: 11, blockedBy: [] },
      { issue: 12, blockedBy: [11] },
    ]);
    expect(graphqlCalls).toEqual([]);
    expect(recorded.every((c) => c === "rest")).toBe(true);
  });

  it("REST 401 → no channel switch, loud terminal (aggregated infra_failure), GraphQL untouched", () => {
    const graphqlCalls: string[] = [];
    const sh: Sh = (file, args) => {
      if (isGraphql(args)) {
        graphqlCalls.push(args.join(" "));
        return "{}";
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: Number(args[2]), body: "", author: { login: "Akagilnc" } });
      }
      // 401 is durable: needs a human, switching transport is pointless.
      throw Object.assign(new Error("HTTP 401: Bad credentials"), { status: 401 });
    };

    expect(() => readFamilyEpic(291, REPO, sh, new Map(), () => {})).toThrow(
      /issue metadata unavailable/,
    );
    expect(graphqlCalls).toEqual([]);
  });

  it("negative: REST 5xx AND GraphQL also fails → aggregated both-channel error, infra_failure preserved", () => {
    const sh: Sh = (file, args) => {
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({ number: Number(args[2]), body: "", author: { login: "Akagilnc" } });
      }
      if (isGraphql(args)) {
        throw http5xx("GraphQL 502 also down");
      }
      throw http5xx("REST 503 also down");
    };

    let thrown: unknown;
    try {
      readFamilyEpic(291, REPO, sh, new Map(), () => {});
    } catch (err) {
      thrown = err;
    }
    const message = (thrown as Error).message;
    expect(message).toMatch(/issue metadata unavailable/);
    // Both transports' failures survive into the aggregated diagnosis.
    expect(message).toMatch(/REST 503 also down/);
    expect(message).toMatch(/GraphQL 502 also down/);
  });
});
