/**
 * #1063 — REST-primary / GraphQL-fallback dual transport for admission's gh
 * metadata reads (issue metadata / sub_issues / blocked_by).
 *
 * REST is ALWAYS the primary channel and owns the #1062/#936 retry budget
 * (`readMetadataWithRetry`). GraphQL is a SECOND transport face used ONLY when
 * the REST budget is exhausted AND the failure is a 5xx/network (transient)
 * class — a persistent partial outage where GitHub's GraphQL backend stays up
 * (2026-07-20 incident: REST `dependencies/blocked_by` down 40+ min while the
 * GraphQL `blockedBy` field served identical data).
 *
 * Both channels funnel into ONE semantic `decode` (single shape source — no two
 * parallel parsers). Durable failures (401/403, schema garbage) never switch
 * channel — they rethrow straight to the loud terminal path. When BOTH channels
 * fail the two errors aggregate into one {@link DualChannelMetadataError} so the
 * caller's `infra_failure` semantics are unchanged.
 */

import { classifyExternalCallFailure } from "./externalCall.js";

/** Which transport actually produced the decoded metadata (ledger/telemetry). */
export type MetadataChannel = "rest" | "graphql";

/** A `(file, args) => stdout` host seam — the same shape `Sh` / RealBackend use. */
export type ShLike = (file: string, args: string[]) => string;

/** REST failed transient AND the GraphQL fallback also failed — aggregate both. */
export class DualChannelMetadataError extends Error {
  readonly restError: unknown;
  readonly graphqlError: unknown;

  constructor(restError: unknown, graphqlError: unknown) {
    super(
      `issue metadata unavailable on both channels: ` +
        `REST=${describe(restError)}; GraphQL=${describe(graphqlError)}`,
    );
    this.name = "DualChannelMetadataError";
    this.restError = restError;
    this.graphqlError = graphqlError;
    if (restError instanceof Error) this.cause = restError;
  }
}

function describe(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Record which transport served a metadata resource, isomorphic with the other
 * `[orchestrator:…]` stage lines. Only the GraphQL fallback is notable (REST is
 * the silent primary), so the line fires on the second-transport hop.
 */
export function logMetadataChannel(
  resource: string,
  issue: number,
  channel: MetadataChannel,
): void {
  if (channel === "graphql") {
    console.warn(
      `[orchestrator:gh-channel] ${resource} #${issue} via graphql (REST budget exhausted)`,
    );
  }
}

function splitRepo(repo: string): { readonly owner: string; readonly name: string } {
  const slash = repo.indexOf("/");
  const owner = slash > 0 ? repo.slice(0, slash) : "";
  const name = slash > 0 ? repo.slice(slash + 1) : "";
  if (owner.length === 0 || name.length === 0) {
    throw new Error(`invalid repo slug (expected owner/name): ${repo}`);
  }
  return { owner, name };
}

/** Navigate a `gh api graphql` envelope to `data.repository.issue` (fail-closed). */
function graphqlIssueNode(raw: string): Record<string, unknown> {
  const parsed = JSON.parse(raw) as {
    readonly data?: { readonly repository?: { readonly issue?: unknown } };
  };
  const issue = parsed?.data?.repository?.issue;
  if (issue === null || typeof issue !== "object") {
    throw new Error(
      `GraphQL schema error: missing data.repository.issue (got ${
        issue === null ? "null" : typeof issue
      })`,
    );
  }
  return issue as Record<string, unknown>;
}

// ── blocked_by ────────────────────────────────────────────────────────────────
// REST : `gh api repos/O/R/issues/N/dependencies/blocked_by` → [{number, state:"open"|"closed"}]
// GraphQL: repository.issue.blockedBy.nodes → {number, state: IssueState enum OPEN|CLOSED}.
// Map the enum → REST lower-case so the single `parseBlockedBy` decoder and every
// downstream `state !== "closed"` compare stay REST-shaped (one shape source).

export function restBlockedByArgs(repo: string, issue: number): string[] {
  return ["api", `repos/${repo}/issues/${issue}/dependencies/blocked_by`];
}

export function graphqlBlockedByArgs(repo: string, issue: number): string[] {
  const { owner, name } = splitRepo(repo);
  return [
    "api",
    "graphql",
    "-f",
    "query=query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)" +
      "{issue(number:$number){blockedBy(first:100){nodes{number state}}}}}",
    "-F",
    `owner=${owner}`,
    "-F",
    `name=${name}`,
    "-F",
    `number=${issue}`,
  ];
}

/** GraphQL blocked_by envelope → the REST array shape `parseBlockedBy` consumes. */
export function graphqlBlockedByToRestShape(raw: string): unknown {
  const blockedBy = graphqlIssueNode(raw).blockedBy;
  const nodes =
    blockedBy !== null && typeof blockedBy === "object"
      ? (blockedBy as { readonly nodes?: unknown }).nodes
      : undefined;
  if (!Array.isArray(nodes)) {
    throw new Error("blocked_by GraphQL schema error: missing blockedBy.nodes array");
  }
  return nodes.map((n) => {
    const node = n as { readonly number?: unknown; readonly state?: unknown };
    return {
      number: node.number,
      // IssueState enum OPEN|CLOSED → REST lower-case open|closed.
      state: typeof node.state === "string" ? node.state.toLowerCase() : node.state,
    };
  });
}

// ── sub_issues ────────────────────────────────────────────────────────────────
// REST : `gh api repos/O/R/issues/<epic>/sub_issues` → array of issue nodes.
// GraphQL: repository.issue.subIssues.nodes (labels{nodes{name}}, subIssues{totalCount},
// IssueState enum) — the `{subIssues:{nodes}}` object `decodeSubIssueNodes` and the
// `labelNames` / `subIssueCount` field readers already normalize (one shape source).

export function restSubIssuesArgs(repo: string, epic: number, page: number): string[] {
  return ["api", `repos/${repo}/issues/${epic}/sub_issues?per_page=100&page=${page}`];
}

export function graphqlSubIssuesArgs(repo: string, epic: number): string[] {
  const { owner, name } = splitRepo(repo);
  return [
    "api",
    "graphql",
    "-f",
    "query=query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)" +
      "{issue(number:$number){subIssues(first:100){nodes{number state " +
      "labels(first:50){nodes{name}} subIssues{totalCount}}}}}}",
    "-F",
    `owner=${owner}`,
    "-F",
    `name=${name}`,
    "-F",
    `number=${epic}`,
  ];
}

/** GraphQL sub_issues envelope → the `{subIssues:{nodes}}` object shape decoders read. */
export function graphqlSubIssuesToNodeShape(raw: string): unknown {
  const issue = graphqlIssueNode(raw);
  return { subIssues: issue.subIssues };
}

/**
 * Read one metadata resource REST-first with a GraphQL fallback.
 *
 * - `rest()` is the primary read (the caller wraps it in the shared retry
 *   budget). If it throws a DURABLE class (401/403, schema garbage) the error
 *   rethrows immediately — no channel switch, loud terminal.
 * - Only a TRANSIENT (5xx/network) REST exhaustion crosses to `graphql()`,
 *   which is attempted a single round (the caller does not lend it the REST
 *   retry budget).
 * - Both channels' raw payloads pass through the SAME `decode` — the single
 *   typed-shape source. A `decode` throw on the REST payload is a durable schema
 *   error and does NOT trigger fallback.
 * - `onChannel` is fired with the transport that actually produced the value.
 */
export function readGithubMetadataDualChannel<T>(opts: {
  readonly rest: () => unknown;
  readonly graphql: () => unknown;
  readonly decode: (payload: unknown) => T;
  readonly onChannel?: (channel: MetadataChannel) => void;
}): T {
  let restError: unknown;
  try {
    const value = opts.decode(opts.rest());
    opts.onChannel?.("rest");
    return value;
  } catch (err) {
    // 401/403 (needs a human) and schema garbage are durable: switching
    // transport is pointless, so surface the REST error as the loud terminal.
    if (classifyExternalCallFailure(err) !== "transient") throw err;
    restError = err;
  }
  try {
    const value = opts.decode(opts.graphql());
    opts.onChannel?.("graphql");
    return value;
  } catch (graphqlError) {
    throw new DualChannelMetadataError(restError, graphqlError);
  }
}
