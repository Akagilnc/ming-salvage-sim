/**
 * Host-side deterministic PR bot polling (#600).
 *
 * Polls GitHub for the four online review bots (CodeRabbit auto-updates on push;
 * Sourcery / Codex / Gemini need a manual R2/R3 re-trigger comment after a fix
 * push). No LLM calls — runner scheduling only. Every `gh api` list is paginated
 * with `per_page=100` (wiki pr-review-loop cadence); GraphQL `reviewThreads`
 * uses cursor pagination via `pageInfo { endCursor hasNextPage }`.
 */

import type { Sh } from "./familyDriver.js";
import {
  buildRoundTrigger,
  evidenceAdmissible,
  liveArtifactEvidenceRecord,
  type RoundTrigger,
} from "./evidenceAdmissibility.js";

/** The four bots the online review loop waits on (ADR 0061 / wiki pr-review-loop). */
export const ONLINE_REVIEW_BOT_IDS = [
  "coderabbit",
  "sourcery",
  "codex",
  "gemini",
] as const;

export type OnlineReviewBotId = (typeof ONLINE_REVIEW_BOT_IDS)[number];

/**
 * Bot-poll cadence and overdue window (R15–R16 Codex P1 — do not hand-count).
 *
 * `waitForBotQuiescence` does:
 *   for poll = 1..N: pollOnce(); if poll < N: sleep(INTERVAL)
 * so wall-clock sleeps = N − 1 (first poll is immediate).
 *
 * Codex body often lands 9–13+ min after `eyes`; require ≥15 min of sleeps:
 *   N = ceil(MIN_WALL / INTERVAL) + 1
 *   e.g. 15 min / 2 min → 8 sleeps → N = 9 → 16 min wall clock.
 */
export const BOT_POLL_INTERVAL_MS = 120_000;
/** Minimum quiet wall-clock before a bot leg may be dropped. */
export const BOT_OVERDUE_MIN_WALL_MS = 15 * 60_000;
/**
 * Polls until drop (inclusive). Derived — never set by hand without the +1.
 * @see {@link botOverdueWallClockMs}
 */
export const BOT_OVERDUE_POLL_COUNT =
  Math.ceil(BOT_OVERDUE_MIN_WALL_MS / BOT_POLL_INTERVAL_MS) + 1;

/** Wall-clock ms after completing `pollCount` polls (first poll at t=0). */
export function botOverdueWallClockMs(pollCount: number): number {
  if (!Number.isFinite(pollCount) || pollCount < 1) return 0;
  return Math.max(0, pollCount - 1) * BOT_POLL_INTERVAL_MS;
}

/**
 * Manual re-trigger comment posted for Sourcery / Codex / Gemini after a fix push.
 * Wiki contract (ADR 0061): three @mentions. Also post `/gemini review` — current
 * Gemini Code Assist docs accept the slash form; @-only can miss the leg (Codex R12 P2).
 */
export const BOT_RETRIGGER_COMMENT =
  "@sourcery-ai review\n@codex review\n@gemini-code-assist please review\n/gemini review";

/** Core wiki lines that identify a re-trigger (old 3-line + new 4-line bodies). */
const BOT_RETRIGGER_REQUIRED_LINES = [
  "@sourcery-ai review",
  "@codex review",
  "@gemini-code-assist please review",
] as const;

/**
 * Pure ACK reactions — bot is alive/queued, NOT a completed review (wiki +
 * online R14 Codex P1: `eyes` only must not flip the leg to complete/0 findings).
 */
export const BOT_REACTION_ACK_ONLY_CONTENT = new Set(["eyes"]);

/**
 * Verdict reactions that complete a bot leg with zero findings (wiki: Codex
 * PR `+1` is an approval). Not counted as findings in {@link countBotFindings}.
 */
export const BOT_REACTION_VERDICT_CONTENT = new Set(["+1"]);

export type BotLegStatus =
  | { readonly state: "pending" }
  | { readonly state: "complete"; readonly findingCount: number }
  | { readonly state: "dropped"; readonly reason: string };

export interface ReviewThreadSnapshot {
  /** Top-level review-comment databaseId — REST reply parent (#600 r7). */
  readonly id: string;
  /** GraphQL reviewThread node id — resolution target (#600 r7). */
  readonly threadNodeId: string;
  readonly path?: string;
  readonly line?: number;
  readonly body: string;
  readonly authorLogin: string;
  readonly isResolved: boolean;
  /** Head OID the thread targets when GitHub exposes it (undefined for artifact bots). */
  readonly headOid?: string;
}

export interface CheckRunSnapshot {
  readonly id: number;
  readonly name: string;
  readonly headSha: string;
  readonly status: string;
  readonly conclusion?: string;
}

export interface PrReviewSnapshot {
  readonly repo: string;
  readonly prNumber: number;
  readonly prUrl: string;
  readonly headOid: string;
  readonly pollCount: number;
  readonly bots: Readonly<Record<OnlineReviewBotId, BotLegStatus>>;
  readonly threads: ReadonlyArray<ReviewThreadSnapshot>;
  /** Head-correlated CI check-runs (ADR 0061 / wiki pr-review-loop). */
  readonly checkRuns: ReadonlyArray<CheckRunSnapshot>;
  readonly totalFindingCount: number;
  readonly quiescent: boolean;
  /**
   * Round trigger actually used for evidence on this poll (online R5 Codex P1).
   * Equals the input trigger when head matches; after mid-round head drift this
   * is the re-anchored trigger — callers must chain it into subsequent polls /
   * ledger markers so the next poll does not re-anchor with a newer now and
   * stale out real post-drift bot replies.
   */
  readonly roundTriggerUsed: RoundTrigger;
  /**
   * How {@link classifyCheckRuns} treats an empty check-run list:
   * - offline/synthetic: "converged" (no CI substrate)
   * - live GitHub poll: "pending" (post-push race before checks appear)
   */
  readonly checkRunsEmptyMeans: "converged" | "pending";
}

export interface PollPrReviewInput {
  readonly repo: string;
  readonly prUrl: string;
  readonly pollCount: number;
  /** Round freshness anchor — required for admissible bot/check evidence (#600 r4). */
  readonly roundTrigger: RoundTrigger;
  /** Per-bot poll counts without a completion signal — used to drop overdue bots. */
  readonly botPendingPolls?: Readonly<Partial<Record<OnlineReviewBotId, number>>>;
  /**
   * Optional clock for fail-closed head-drift re-anchor (online R2 Codex P2).
   * When the live PR head differs from the round trigger head, a new trigger is
   * built with this instant (default: now) so timestamp-only bot artifacts from
   * the previous head cannot satisfy the new head.
   */
  readonly nowIso?: string;
}

/**
 * Parse `owner/repo` and PR number from a GitHub PR URL.
 * Accepts `https://github.com/o/r/pull/123` and `o/r#123` style handles.
 */
/** True when `prUrl` names a live GitHub PR the host can poll via `gh api`. */
export function isPollableGithubPrUrl(prUrl: string, defaultRepo: string): boolean {
  try {
    parsePrRef(prUrl, defaultRepo);
  } catch {
    return false;
  }
  const trimmed = prUrl.trim();
  return (
    /^https?:\/\/github\.com\//i.test(trimmed) ||
    /^[^/]+\/[^#]+#\d+$/.test(trimmed) ||
    /^\d+$/.test(trimmed)
  );
}

/**
 * True when the host may issue live `gh` calls for online review (poll, side
 * effects, re-trigger). Unit tests set `ORCHESTRATOR_OFFLINE_REVIEW_POLL=1` so
 * synthetic `pr://` handles and fake GitHub URLs stay deterministic.
 */
export function isLiveGithubReviewPollEnabled(
  prUrl: string,
  defaultRepo: string,
): boolean {
  return (
    isPollableGithubPrUrl(prUrl, defaultRepo) &&
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL !== "1"
  );
}

export function parsePrRef(
  prUrl: string,
  defaultRepo: string,
): { repo: string; prNumber: number } {
  const trimmed = prUrl.trim();
  const web = trimmed.match(
    /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?(?:[?#].*)?$/i,
  );
  if (web) {
    return { repo: `${web[1]}/${web[2]}`, prNumber: Number(web[3]) };
  }
  const short = trimmed.match(/^([^/]+\/[^#]+)#(\d+)$/);
  if (short) {
    return { repo: short[1]!, prNumber: Number(short[2]) };
  }
  const numOnly = trimmed.match(/^(\d+)$/);
  if (numOnly) {
    return { repo: defaultRepo, prNumber: Number(numOnly[1]) };
  }
  throw new Error(`botPolling: cannot parse PR reference from "${prUrl}"`);
}

/** Paginate a GitHub REST collection (`gh api` returns a JSON array). */
export function paginateGhApi(
  sh: Sh,
  path: string,
  perPage = 100,
): unknown[] {
  const items: unknown[] = [];
  for (let page = 1; ; page += 1) {
    const sep = path.includes("?") ? "&" : "?";
    const raw = sh("gh", [
      "api",
      `${path}${sep}per_page=${perPage}&page=${page}`,
    ]);
    const parsed: unknown = JSON.parse(raw);
    // Fail closed on non-array (error objects / rate-limit payloads) — silent
    // empty would fake "no bots / no comments" and green-path the review loop
    // (online R8 Gemini high).
    if (!Array.isArray(parsed)) {
      throw new Error(
        `paginateGhApi: expected array from ${path}, got ${typeof parsed}`,
      );
    }
    if (parsed.length === 0) break;
    items.push(...parsed);
    if (parsed.length < perPage) break;
  }
  return items;
}

/** Default page size for GraphQL `reviewThreads` cursor pagination (#600 AC2). */
export const REVIEW_THREADS_GRAPHQL_PAGE_SIZE = 100;

type ReviewThreadGraphqlNode = {
  id?: string;
  isResolved?: boolean;
  comments?: {
    nodes?: Array<{
      databaseId?: number;
      body?: string;
      path?: string;
      line?: number;
      author?: { login?: string };
      commit?: { oid?: string };
    }>;
  };
};

type ReviewThreadsConnection = {
  nodes?: unknown[];
  pageInfo?: { endCursor?: string | null; hasNextPage?: boolean };
};

type ParsedReviewThreadsPage = {
  readonly nodes: ReviewThreadGraphqlNode[];
  readonly hasNextPage: boolean;
  readonly endCursor: string;
};

function parseReviewThreadsGraphqlPage(parsed: unknown): ParsedReviewThreadsPage {
  if (parsed != null && typeof parsed === "object") {
    const errors = (parsed as { errors?: unknown }).errors;
    if (Array.isArray(errors) && errors.length > 0) {
      throw new Error(
        `botPolling: GraphQL reviewThreads errors: ${JSON.stringify(errors)}`,
      );
    }
  }

  const connection: ReviewThreadsConnection | null | undefined =
    parsed != null && typeof parsed === "object"
      ? (
          parsed as {
            data?: {
              repository?: {
                pullRequest?: { reviewThreads?: ReviewThreadsConnection | null };
              };
            };
          }
        ).data?.repository?.pullRequest?.reviewThreads
      : undefined;
  // GraphQL nullable field may be null (not undefined) — use == null (repo rule).
  if (connection == null) {
    throw new Error(
      "botPolling: malformed GraphQL reviewThreads response (missing connection)",
    );
  }

  const pageInfo = connection.pageInfo;
  // typeof null === "object" in JS — must exclude null explicitly.
  if (pageInfo == null || typeof pageInfo !== "object") {
    throw new Error(
      "botPolling: malformed GraphQL reviewThreads response (missing pageInfo)",
    );
  }

  const rawNodes = connection.nodes;
  if (rawNodes == null) {
    throw new Error(
      "botPolling: malformed GraphQL reviewThreads response (missing nodes)",
    );
  }
  if (!Array.isArray(rawNodes)) {
    throw new Error(
      "botPolling: malformed GraphQL reviewThreads response (non-array nodes)",
    );
  }

  const hasNextPage = pageInfo.hasNextPage === true;
  const endCursor =
    typeof pageInfo.endCursor === "string" ? pageInfo.endCursor : "";
  if (hasNextPage && endCursor.length === 0) {
    throw new Error(
      "botPolling: malformed GraphQL reviewThreads pagination (hasNextPage without endCursor)",
    );
  }

  return {
    nodes: rawNodes as ReviewThreadGraphqlNode[],
    hasNextPage,
    endCursor,
  };
}

/**
 * Cursor-paginate `pullRequest.reviewThreads` via GraphQL `pageInfo` (#600 AC2).
 * Malformed pages fail closed; only a well-formed terminal page ends pagination (#600 r32).
 */
export function paginateReviewThreadNodes(
  sh: Sh,
  repo: string,
  prNumber: number,
  nodesFields: string,
  pageSize: number = REVIEW_THREADS_GRAPHQL_PAGE_SIZE,
): ReviewThreadGraphqlNode[] {
  const { owner, name } = splitRepoSlug(repo);
  const allNodes: ReviewThreadGraphqlNode[] = [];
  let after: string | undefined;

  for (;;) {
    const query = [
      "query($owner:String!,$name:String!,$number:Int!,$first:Int!,$after:String){",
      "repository(owner:$owner,name:$name){",
      "pullRequest(number:$number){",
      "reviewThreads(first:$first,after:$after){",
      "pageInfo{endCursor hasNextPage}",
      `nodes{${nodesFields}}`,
      "}}}}}",
    ].join("");
    const ghArgs = [
      "api",
      "graphql",
      "-f",
      `query=${query}`,
      "-f",
      `owner=${owner}`,
      "-f",
      `name=${name}`,
      "-F",
      `number=${prNumber}`,
      "-F",
      `first=${pageSize}`,
    ];
    if (after !== undefined) {
      ghArgs.push("-f", `after=${after}`);
    }
    const raw = sh("gh", ghArgs);
    const page = parseReviewThreadsGraphqlPage(JSON.parse(raw));
    if (page.nodes.length > 0) {
      allNodes.push(...page.nodes);
    }
    if (!page.hasNextPage) {
      break;
    }
    after = page.endCursor;
  }

  return allNodes;
}

/**
 * Known GitHub logins for each online-review bot (#741).
 * Exact whole-login match only (case-insensitive per GitHub login rules).
 * Substring match would let logins like `xxx-coderabbit-fan` spoof bot evidence.
 */
export const ONLINE_REVIEW_BOT_LOGINS: Readonly<
  Record<OnlineReviewBotId, readonly string[]>
> = {
  coderabbit: ["coderabbitai[bot]"],
  sourcery: ["sourcery-ai[bot]"],
  codex: ["chatgpt-codex-connector[bot]"],
  gemini: ["gemini-code-assist[bot]"],
};

/** True when `login` is exactly a known login for `bot` (case-insensitive). */
function loginMatchesBot(login: string, bot: OnlineReviewBotId): boolean {
  if (!login) return false;
  const lower = login.toLowerCase();
  return ONLINE_REVIEW_BOT_LOGINS[bot].some(
    (known) => known === lower,
  );
}

/** REST issue/PR comments expose `user.login`; tolerate legacy `author.login` in fakes. */
function commentAuthorLogin(
  comment: { user?: { login?: string }; author?: { login?: string } },
): string {
  return comment.user?.login ?? comment.author?.login ?? "";
}

type BotComment = {
  id?: number;
  user?: { login?: string };
  author?: { login?: string };
  body?: string;
  created_at?: string;
  updated_at?: string;
  commit_id?: string;
};

type BotReview = {
  user?: { login?: string };
  state?: string;
  submitted_at?: string;
  commit_id?: string;
};

type BotReaction = {
  user?: { login?: string };
  content?: string;
  created_at?: string;
};

/**
 * Freshness timestamp for bot artifacts.
 * Prefer `updated_at` when present: bots like CodeRabbit auto-update the same
 * comment after a fix push, leaving `created_at` at the original pre-trigger time
 * (online R8 Codex P1). Falling back to created_at/submitted_at for artifacts
 * that never update.
 */
function artifactTimestamp(
  item: {
    created_at?: string;
    submitted_at?: string;
    updated_at?: string;
  },
): string | undefined {
  return item.updated_at ?? item.created_at ?? item.submitted_at;
}

function isAdmissibleBotArtifact(
  artifact: { headOid?: string; timestamp?: string },
  head: string,
  roundTrigger: RoundTrigger,
): boolean {
  return evidenceAdmissible(
    liveArtifactEvidenceRecord({
      headOid: artifact.headOid,
      timestamp: artifact.timestamp,
      head,
      roundTrigger,
    }),
    head,
    roundTrigger,
  );
}

/**
 * True when the bot left a fresh **completion** signal (findings optional —
 * zero is valid when the signal is a real review/comment or a verdict reaction).
 * Pure ACK reactions (`eyes`) do not complete the leg (R14 Codex P1).
 */
function hasBotReviewSignal(
  bot: OnlineReviewBotId,
  comments: ReadonlyArray<BotComment>,
  reviews: ReadonlyArray<BotReview>,
  reactions: ReadonlyArray<BotReaction>,
  head: string,
  roundTrigger: RoundTrigger,
): boolean {
  for (const c of comments) {
    const login = commentAuthorLogin(c);
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { headOid: c.commit_id, timestamp: artifactTimestamp(c) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    if ((c.body ?? "").trim().length > 0) return true;
  }
  for (const r of reviews) {
    const login = r.user?.login ?? "";
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { headOid: r.commit_id, timestamp: artifactTimestamp(r) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    if ((r.state ?? "").trim().length > 0) return true;
  }
  for (const reaction of reactions) {
    const login = reaction.user?.login ?? "";
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { timestamp: artifactTimestamp(reaction) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    const content = (reaction.content ?? "").trim();
    // Verdict (+1) completes; pure ACK (eyes) does not.
    if (BOT_REACTION_VERDICT_CONTENT.has(content)) return true;
    if (content.length > 0 && !BOT_REACTION_ACK_ONLY_CONTENT.has(content)) {
      // Unknown non-empty reaction (e.g. rocket) — treat as signal, not pure ACK.
      return true;
    }
  }
  return false;
}

function countBotFindings(
  bot: OnlineReviewBotId,
  comments: ReadonlyArray<BotComment>,
  reviews: ReadonlyArray<BotReview>,
  reactions: ReadonlyArray<BotReaction>,
  head: string,
  roundTrigger: RoundTrigger,
): number {
  let count = 0;
  for (const c of comments) {
    const login = commentAuthorLogin(c);
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { headOid: c.commit_id, timestamp: artifactTimestamp(c) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    const body = (c.body ?? "").trim();
    if (body.length === 0) continue;
    // CodeRabbit / gemini often post summary comments — count non-trivial bodies.
    if (body.length >= 20) count += 1;
  }
  for (const r of reviews) {
    const login = r.user?.login ?? "";
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { headOid: r.commit_id, timestamp: artifactTimestamp(r) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    const state = (r.state ?? "").toUpperCase();
    if (state === "COMMENTED" || state === "CHANGES_REQUESTED") count += 1;
  }
  for (const reaction of reactions) {
    const login = reaction.user?.login ?? "";
    if (!loginMatchesBot(login, bot)) continue;
    if (
      !isAdmissibleBotArtifact(
        { timestamp: artifactTimestamp(reaction) },
        head,
        roundTrigger,
      )
    ) {
      continue;
    }
    const content = (reaction.content ?? "").trim();
    // ACK-only and verdict reactions are not findings (+1 = clean approve).
    if (
      content.length > 0 &&
      !BOT_REACTION_ACK_ONLY_CONTENT.has(content) &&
      !BOT_REACTION_VERDICT_CONTENT.has(content)
    ) {
      count += 1;
    }
  }
  return count;
}

/**
 * CI check-run gate for online-review convergence (ADR 0061).
 * - empty list: offline/synthetic → treated as converged
 * - any non-completed (queued/in_progress): pending (re-poll; do not fixer)
 * - any completed non-success: failed (block merge)
 * - else all completed success: converged
 */
export type CheckRunsGate = "converged" | "pending" | "failed";

export function classifyCheckRuns(
  runs: ReadonlyArray<CheckRunSnapshot>,
  emptyMeans: "converged" | "pending" = "converged",
): CheckRunsGate {
  if (runs.length === 0) return emptyMeans;
  let sawPending = false;
  for (const run of runs) {
    const status = (run.status ?? "").toLowerCase();
    if (status !== "completed") {
      sawPending = true;
      continue;
    }
    // GitHub Actions: skipped/neutral are not failures and should not block
    // online-review mergeability (verified against GH check-run conclusions).
    const conclusion = (run.conclusion ?? "").toLowerCase();
    if (
      conclusion !== "success" &&
      conclusion !== "skipped" &&
      conclusion !== "neutral"
    ) {
      return "failed";
    }
  }
  return sawPending ? "pending" : "converged";
}

/** True when every admissible head-correlated check-run completed successfully. */
export function checkRunsConverged(
  runs: ReadonlyArray<CheckRunSnapshot>,
  emptyMeans: "converged" | "pending" = "converged",
): boolean {
  return classifyCheckRuns(runs, emptyMeans) === "converged";
}

function resolveBotStatuses(
  input: PollPrReviewInput,
  comments: ReadonlyArray<BotComment>,
  reviews: ReadonlyArray<BotReview>,
  reactions: ReadonlyArray<BotReaction>,
  head: string,
): Record<OnlineReviewBotId, BotLegStatus> {
  const pending = input.botPendingPolls ?? {};
  const roundTrigger = input.roundTrigger;
  const bots = {} as Record<OnlineReviewBotId, BotLegStatus>;
  for (const bot of ONLINE_REVIEW_BOT_IDS) {
    const findingCount = countBotFindings(
      bot,
      comments,
      reviews,
      reactions,
      head,
      roundTrigger,
    );
    if (hasBotReviewSignal(bot, comments, reviews, reactions, head, roundTrigger)) {
      bots[bot] = { state: "complete", findingCount };
      continue;
    }
    const waited = pending[bot] ?? input.pollCount;
    if (waited >= BOT_OVERDUE_POLL_COUNT) {
      const approxMin = Math.round(botOverdueWallClockMs(waited) / 60_000);
      bots[bot] = {
        state: "dropped",
        reason: `no review signal after ${waited} polls (~${approxMin} min)`,
      };
      continue;
    }
    bots[bot] = { state: "pending" };
  }
  return bots;
}

function splitRepoSlug(repo: string): { owner: string; name: string } {
  const [owner, name] = repo.split("/");
  if (owner === undefined || name === undefined || owner.length === 0 || name.length === 0) {
    throw new Error(`botPolling: invalid repo slug "${repo}"`);
  }
  return { owner, name };
}

/** GraphQL reviewThreads — authoritative thread id + isResolved + top comment (#600 r7). */
function fetchReviewThreadsFromGraphql(
  sh: Sh,
  repo: string,
  prNumber: number,
): ReviewThreadSnapshot[] {
  const nodes = paginateReviewThreadNodes(
    sh,
    repo,
    prNumber,
    "id isResolved comments(first:1){nodes{databaseId body path line author{login} commit{oid}}}",
  );
  const out: ReviewThreadSnapshot[] = [];
  for (const obj of nodes) {
    const threadNodeId = typeof obj.id === "string" ? obj.id : "";
    const first = obj.comments?.nodes?.[0];
    if (threadNodeId.length === 0 || first?.databaseId === undefined) continue;
    out.push({
      id: String(first.databaseId),
      threadNodeId,
      path: typeof first.path === "string" ? first.path : undefined,
      line: typeof first.line === "number" ? first.line : undefined,
      body: typeof first.body === "string" ? first.body : "",
      authorLogin: first.author?.login ?? "unknown",
      isResolved: Boolean(obj.isResolved),
      headOid:
        typeof first.commit?.oid === "string" ? first.commit.oid : undefined,
    });
  }
  return out;
}

function paginateCheckRuns(
  sh: Sh,
  repo: string,
  headOid: string,
  perPage = 100,
): CheckRunSnapshot[] {
  const items: CheckRunSnapshot[] = [];
  for (let page = 1; ; page += 1) {
    const raw = sh("gh", [
      "api",
      `repos/${repo}/commits/${headOid}/check-runs?per_page=${perPage}&page=${page}`,
    ]);
    const parsed: unknown = JSON.parse(raw);
    // Fail closed: missing check_runs must not become [] → classify "converged"
    // and let a green verify merge (online R8 Gemini critical).
    if (parsed == null || typeof parsed !== "object") {
      throw new Error(
        `paginateCheckRuns: expected object with check_runs for ${repo}@${headOid}, got ${typeof parsed}`,
      );
    }
    const checkRunsField = (parsed as { check_runs?: unknown }).check_runs;
    if (!Array.isArray(checkRunsField)) {
      throw new Error(
        `paginateCheckRuns: missing check_runs array for ${repo}@${headOid}`,
      );
    }
    const runs = checkRunsField;
    if (runs.length === 0) break;
    for (const run of runs) {
      if (run == null || typeof run !== "object") continue;
      const obj = run as Record<string, unknown>;
      const id = typeof obj.id === "number" ? obj.id : Number(obj.id);
      const headSha = typeof obj.head_sha === "string" ? obj.head_sha : "";
      const name = typeof obj.name === "string" ? obj.name : "unknown";
      const status = typeof obj.status === "string" ? obj.status : "unknown";
      const conclusion =
        typeof obj.conclusion === "string" ? obj.conclusion : undefined;
      if (!Number.isFinite(id) || headSha.length === 0) continue;
      items.push({ id, name, headSha, status, conclusion });
    }
    if (runs.length < perPage) break;
  }
  return items;
}

function admissibleCheckRuns(
  runs: ReadonlyArray<CheckRunSnapshot>,
  head: string,
  roundTrigger: RoundTrigger,
): CheckRunSnapshot[] {
  return runs.filter((run) =>
    evidenceAdmissible(
      liveArtifactEvidenceRecord({
        headOid: run.headSha,
        head,
        roundTrigger,
      }),
      head,
      roundTrigger,
    ),
  );
}

/**
 * Collect a single poll snapshot for a PR. Deterministic given `sh` stdout.
 * Does NOT sleep — the caller owns cadence / retry loops.
 */
export function pollPrReviewState(
  sh: Sh,
  input: PollPrReviewInput,
): PrReviewSnapshot {
  const { repo, prNumber } = parsePrRef(input.prUrl, input.repo);
  const prRaw = sh("gh", [
    "api",
    `repos/${repo}/pulls/${prNumber}`,
    "--jq",
    "{head:{sha:.head.sha},html_url:.html_url}",
  ]);
  const prParsed: unknown = JSON.parse(prRaw);
  if (prParsed == null || typeof prParsed !== "object") {
    throw new Error(`botPolling: malformed gh pr payload for ${input.prUrl}`);
  }
  const prObj = prParsed as {
    head?: { sha?: string };
    html_url?: string;
  };
  const headOid = prObj.head?.sha ?? "";
  if (headOid.length === 0) {
    throw new Error(`botPolling: PR ${input.prUrl} has no head sha`);
  }

  // Fail closed on mid-round head advance (online R2 Codex P2): re-anchor the
  // trigger to the new head with a fresh timestamp. Keeping the old triggeredAt
  // would admit timestamp-only bot artifacts (no commit_id) from the previous
  // head against the new SHA and let the loop converge without a re-review.
  const roundTrigger =
    input.roundTrigger.headOid === headOid
      ? input.roundTrigger
      : buildRoundTrigger(
          headOid,
          input.nowIso ?? new Date().toISOString(),
        );

  const issueComments = paginateGhApi(
    sh,
    `repos/${repo}/issues/${prNumber}/comments`,
  ) as BotComment[];
  const reviewComments = paginateGhApi(
    sh,
    `repos/${repo}/pulls/${prNumber}/comments`,
  ) as Array<BotComment & { id?: number }>;
  const reviews = paginateGhApi(
    sh,
    `repos/${repo}/pulls/${prNumber}/reviews`,
  ) as BotReview[];
  const threads = fetchReviewThreadsFromGraphql(sh, repo, prNumber);
  const reactions: BotReaction[] = [
    ...(paginateGhApi(
      sh,
      `repos/${repo}/issues/${prNumber}/reactions`,
    ) as BotReaction[]),
  ];
  // Fetch reactions only where online-review bots signal (not every human
  // comment — rate-limit poison). Include: (1) bot-authored comments, (2)
  // re-trigger comments bots often react on (Codex eyes/+1).
  const shouldFetchReactions = (comment: BotComment): boolean => {
    if (comment.id === undefined) return false;
    const login = commentAuthorLogin(comment);
    if (ONLINE_REVIEW_BOT_IDS.some((bot) => loginMatchesBot(login, bot))) {
      return true;
    }
    return isBotRetriggerCommentBody(comment.body ?? "");
  };
  for (const comment of issueComments) {
    if (!shouldFetchReactions(comment)) continue;
    const raw = paginateGhApi(
      sh,
      `repos/${repo}/issues/comments/${comment.id}/reactions`,
    ) as BotReaction[];
    reactions.push(...raw);
  }
  for (const comment of reviewComments) {
    if (!shouldFetchReactions(comment)) continue;
    const raw = paginateGhApi(
      sh,
      `repos/${repo}/pulls/comments/${comment.id}/reactions`,
    ) as BotReaction[];
    reactions.push(...raw);
  }

  const allComments = [...issueComments, ...reviewComments];
  // Use re-anchored roundTrigger for bot evidence (online R4 Codex P1): if head
  // drifted, input.roundTrigger still has the old head+timestamp and would admit
  // timestamp-only artifacts from the previous head.
  const bots = resolveBotStatuses(
    { ...input, roundTrigger },
    allComments,
    reviews,
    reactions,
    headOid,
  );
  const checkRuns = admissibleCheckRuns(
    paginateCheckRuns(sh, repo, headOid),
    headOid,
    roundTrigger,
  );
  const totalFindingCount = ONLINE_REVIEW_BOT_IDS.reduce((sum, bot) => {
    const leg = bots[bot];
    return sum + (leg.state === "complete" ? leg.findingCount : 0);
  }, 0);
  const quiescent = ONLINE_REVIEW_BOT_IDS.every((bot) => {
    const leg = bots[bot];
    return leg.state === "complete" || leg.state === "dropped";
  });

  return {
    repo,
    prNumber,
    prUrl: prObj.html_url ?? input.prUrl,
    headOid,
    pollCount: input.pollCount,
    bots,
    threads,
    checkRuns,
    totalFindingCount,
    quiescent,
    roundTriggerUsed: roundTrigger,
    // Live API empty check_runs is a post-push race, not "CI green".
    checkRunsEmptyMeans: "pending",
  };
}

type RetriggerIssueComment = {
  readonly body?: string;
  readonly created_at?: string;
  readonly updated_at?: string;
};

/** True when an issue-comment body matches the manual R2/R3 re-trigger contract. */
export function isBotRetriggerCommentBody(body: string): boolean {
  const trimmed = body.trim();
  if (trimmed === BOT_RETRIGGER_COMMENT.trim()) return true;
  // Accept wiki 3-line bodies and 4-line bodies that add `/gemini review`.
  return BOT_RETRIGGER_REQUIRED_LINES.every((line) => trimmed.includes(line));
}

/**
 * Find an admissible R2/R3 re-trigger comment already on the PR (#600 r34 gap-resume).
 * Uses the same issue-comment evidence collection as pollPrReviewState.
 *
 * Invariant (head-drift fail-closed, deep self-check of online R2–R6 Codex chain):
 * - If live PR head !== gapTrigger.headOid → **never** reuse an existing re-trigger
 *   comment (timestamp-only comments from the prior head would otherwise look
 *   "fresh" after re-anchor). Caller must post a new re-trigger for the new head.
 * - If heads match → admit comments by gapTrigger timestamp window only.
 */
export function findAdmissibleRetriggerComment(
  sh: Sh,
  repo: string,
  prUrl: string,
  gapTrigger: RoundTrigger,
): RoundTrigger | undefined {
  const headProbe = pollPrReviewState(sh, {
    repo,
    prUrl,
    pollCount: 0,
    roundTrigger: gapTrigger,
  });
  // Live head left the gap fix SHA → force a fresh re-trigger (do not search).
  if (headProbe.headOid !== gapTrigger.headOid) {
    return undefined;
  }
  const evidenceTrigger = gapTrigger;
  const { prNumber } = parsePrRef(prUrl, repo);
  const issueComments = paginateGhApi(
    sh,
    `repos/${repo}/issues/${prNumber}/comments`,
  ) as RetriggerIssueComment[];
  // Prefer the chronologically latest admissible re-trigger (Cursor R12 medium) —
  // API order is not guaranteed newest-first; first-match can pin a stale window.
  let latest: { readonly headOid: string; readonly timestamp: string } | undefined;
  for (const comment of issueComments) {
    const body = comment.body ?? "";
    if (!isBotRetriggerCommentBody(body)) continue;
    const timestamp = artifactTimestamp(comment);
    if (timestamp === undefined || timestamp.length === 0) continue;
    if (
      !evidenceAdmissible(
        liveArtifactEvidenceRecord({
          timestamp,
          head: headProbe.headOid,
          roundTrigger: evidenceTrigger,
        }),
        headProbe.headOid,
        evidenceTrigger,
      )
    ) {
      continue;
    }
    if (latest === undefined) {
      latest = { headOid: headProbe.headOid, timestamp };
      continue;
    }
    const candMs = Date.parse(timestamp);
    const latestMs = Date.parse(latest.timestamp);
    if (
      Number.isFinite(candMs) &&
      Number.isFinite(latestMs) &&
      candMs >= latestMs
    ) {
      latest = { headOid: headProbe.headOid, timestamp };
    } else if (Number.isFinite(candMs) && !Number.isFinite(latestMs)) {
      latest = { headOid: headProbe.headOid, timestamp };
    }
  }
  if (latest === undefined) return undefined;
  return buildRoundTrigger(latest.headOid, latest.timestamp);
}

/** Post the manual R2/R3 re-trigger comment for Sourcery / Codex / Gemini. */
export function postBotRetriggerComment(
  sh: Sh,
  repo: string,
  prNumber: number,
  body: string = BOT_RETRIGGER_COMMENT,
): void {
  sh("gh", [
    "api",
    `repos/${repo}/issues/${prNumber}/comments`,
    "-f",
    `body=${body}`,
  ]);
}

/** Bot ids explicitly dropped after the overdue window (not convergence evidence). */
export function droppedBotIds(snapshot: PrReviewSnapshot): OnlineReviewBotId[] {
  return ONLINE_REVIEW_BOT_IDS.filter((bot) => snapshot.bots[bot].state === "dropped");
}

/** True when every bot leg is complete or explicitly dropped (polling may stop). */
export function isBotQuiescent(snapshot: PrReviewSnapshot): boolean {
  return snapshot.quiescent;
}

/** True when any bot was dropped — verify must judge, never treat as clean silence. */
export function hasDroppedBots(snapshot: PrReviewSnapshot): boolean {
  return droppedBotIds(snapshot).length > 0;
}

/** Count open (unresolved) review threads on the current head. */
export function unresolvedThreadCount(snapshot: PrReviewSnapshot): number {
  return snapshot.threads.filter((t) => !t.isResolved).length;
}

/** True only when a thread's native head matches the current PR head (#600 AC3). */
export function isThreadEvidenceFresh(
  thread: ReviewThreadSnapshot,
  currentHead: string,
  roundTrigger: RoundTrigger = buildRoundTrigger(currentHead, "1970-01-01T00:00:00.000Z"),
): boolean {
  return evidenceAdmissible(
    liveArtifactEvidenceRecord({
      headOid: thread.headOid,
      head: currentHead,
      roundTrigger,
    }),
    currentHead,
    roundTrigger,
  );
}
