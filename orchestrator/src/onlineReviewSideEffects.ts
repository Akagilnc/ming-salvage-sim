/**
 * Host-side GitHub side effects for the online review loop (#600).
 *
 * The verify worker owns disposition judgment; this module applies deterministic
 * gh calls for deferred-issue tracking, evidence-bearing thread replies, and
 * post-recheck thread resolution. No LLM calls.
 */

import { paginateReviewThreadNodes, parsePrRef } from "./botPolling.js";
import type { Sh } from "./familyDriver.js";
import type {
  OnlineReviewFindingDisposition,
  OnlineReviewThreadReply,
  VerifyResult,
} from "./types.js";

export interface ApplyVerifySideEffectsInput {
  readonly sh: Sh;
  readonly repo: string;
  readonly prUrl: string;
  readonly verify: VerifyResult;
  readonly fixingCommitSha?: string;
}

export interface ApplyVerifySideEffectsResult {
  readonly deferredIssueUrls: ReadonlyArray<string>;
  readonly repliesPosted: ReadonlyArray<OnlineReviewThreadReply>;
  readonly threadsResolved: ReadonlyArray<string>;
}

/** GitHub issue URL shape returned by `gh api repos/{repo}/issues --jq .html_url`. */
export function isValidGithubIssueUrl(url: string): boolean {
  const trimmed = url.trim();
  return (
    trimmed.length > 0 &&
    /^https:\/\/github\.com\/[^/]+\/[^/]+\/issues\/\d+\/?(?:[?#].*)?$/i.test(
      trimmed,
    )
  );
}

/** Create a tracked deferral issue via `gh api repos/{repo}/issues` (#600 AC5). */
export function createDeferredTrackingIssue(
  sh: Sh,
  repo: string,
  title: string,
  body: string,
): string {
  const url = sh("gh", [
    "api",
    `repos/${repo}/issues`,
    "-f",
    `title=${title}`,
    "-f",
    `body=${body}`,
    "--jq",
    ".html_url",
  ]);
  const trimmed = url.trim();
  if (!isValidGithubIssueUrl(trimmed)) {
    throw new Error(
      `createDeferredTrackingIssue: gh returned invalid issue URL "${url}"`,
    );
  }
  return trimmed;
}

/** Post an evidence-bearing reply on a PR review thread (#600 AC6). */
export function replyToReviewThread(
  sh: Sh,
  repo: string,
  prNumber: number,
  threadId: string,
  body: string,
): void {
  sh("gh", [
    "api",
    `repos/${repo}/pulls/${prNumber}/comments/${threadId}/replies`,
    "-f",
    `body=${body}`,
  ]);
}

/**
 * Resolve a review thread via GraphQL `resolveReviewThread` (#600 AC4).
 * REST `PATCH /pulls/comments/{id}` edits comment content — it does NOT resolve
 * the conversation. See:
 * https://docs.github.com/en/rest/pulls/comments?apiVersion=2022-11-28
 */
export function resolveReviewThread(
  sh: Sh,
  repo: string,
  prNumber: number,
  threadId: string,
): void {
  const nodes = paginateReviewThreadNodes(
    sh,
    repo,
    prNumber,
    "id isResolved comments(first:1){nodes{databaseId}}",
  );
  let threadNodeId: string | undefined;
  if (threadId.startsWith("PRRT_")) {
    threadNodeId = threadId;
  } else {
    const targetId = Number(threadId);
    for (const obj of nodes) {
      const firstCommentId = obj.comments?.nodes?.[0]?.databaseId;
      if (firstCommentId === targetId || String(firstCommentId) === threadId) {
        threadNodeId = obj.id;
        break;
      }
    }
  }
  if (threadNodeId === undefined || threadNodeId.length === 0) {
    throw new Error(
      `onlineReviewSideEffects: no GraphQL review thread for comment id ${threadId}`,
    );
  }
  const mutation = [
    "mutation($threadId:ID!){",
    "resolveReviewThread(input:{threadId:$threadId}){",
    "thread{isResolved}}}",
  ].join("");
  sh("gh", [
    "api",
    "graphql",
    "-f",
    `query=${mutation}`,
    "-f",
    `threadId=${threadNodeId}`,
  ]);
}

function deferDispositions(
  verify: VerifyResult,
): ReadonlyArray<OnlineReviewFindingDisposition> {
  return (verify.findingDispositions ?? []).filter((d) => d.action === "defer");
}

function replyByThreadId(
  verify: VerifyResult,
): Map<string, OnlineReviewThreadReply> {
  const map = new Map<string, OnlineReviewThreadReply>();
  for (const reply of verify.threadReplies ?? []) {
    map.set(reply.threadId, reply);
  }
  return map;
}

function isFixedEvidenceReplyForCommit(
  body: string,
  repo: string,
  fixingCommitSha: string,
): boolean {
  const expected = `fixed: https://github.com/${repo}/commit/${fixingCommitSha}`;
  return body.trim() === expected;
}

function deferReplyBody(
  existingBody: string | undefined,
  disposition: OnlineReviewFindingDisposition,
  issueUrl: string,
): string {
  const reason =
    disposition.reason ??
    `Deferred from online review loop for thread ${disposition.threadId}`;
  if (existingBody !== undefined && existingBody.trim().length > 0) {
    return existingBody.includes(issueUrl)
      ? existingBody
      : `${existingBody}\nTracked issue: ${issueUrl}`;
  }
  return `deferred: ${reason}\nTracked issue: ${issueUrl}`;
}

/**
 * Apply GitHub side effects from a verify verdict: defer → tracked issue + reply,
 * reject/defer/fixed replies with evidence, resolve after recheck confirmation.
 */
export function applyVerifySideEffects(
  input: ApplyVerifySideEffectsInput,
): ApplyVerifySideEffectsResult {
  const { sh, repo, prUrl, verify } = input;
  const { prNumber } = parsePrRef(prUrl, repo);
  const deferredIssueUrls: string[] = [];
  const repliesPosted: OnlineReviewThreadReply[] = [];
  const threadsResolved: string[] = [];
  const existingReplies = replyByThreadId(verify);

  for (const disposition of deferDispositions(verify)) {
    const title = `Deferred online review finding: ${disposition.identityKey}`;
    const body =
      disposition.reason ??
      `Deferred from online review loop for thread ${disposition.threadId}`;
    const issueUrl = createDeferredTrackingIssue(sh, repo, title, body);
    deferredIssueUrls.push(issueUrl);
    const replyBody = deferReplyBody(
      existingReplies.get(disposition.threadId)?.body,
      disposition,
      issueUrl,
    );
    replyToReviewThread(sh, repo, prNumber, disposition.threadId, replyBody);
    repliesPosted.push({ threadId: disposition.threadId, body: replyBody });
  }

  for (const reply of verify.threadReplies ?? []) {
    if (deferDispositions(verify).some((d) => d.threadId === reply.threadId)) {
      continue;
    }
    replyToReviewThread(sh, repo, prNumber, reply.threadId, reply.body);
    repliesPosted.push(reply);
  }

  if (
    (verify.threadsToResolve?.length ?? 0) > 0 &&
    verify.isRecheck !== true
  ) {
    throw new Error(
      "applyVerifySideEffects: threadsToResolve requires a fresh re-check verify (isRecheck)",
    );
  }
  if (
    (verify.threadsToResolve?.length ?? 0) > 0 &&
    (input.fixingCommitSha === undefined || input.fixingCommitSha.length === 0)
  ) {
    throw new Error(
      "applyVerifySideEffects: threadsToResolve requires fixingCommitSha on recheck",
    );
  }

  for (const threadId of verify.threadsToResolve ?? []) {
    const fixingCommitSha = input.fixingCommitSha!;
    const fixedReply = `fixed: https://github.com/${repo}/commit/${fixingCommitSha}`;
    const hasEvidenceReply = repliesPosted.some(
      (r) =>
        r.threadId === threadId &&
        isFixedEvidenceReplyForCommit(r.body, repo, fixingCommitSha),
    );
    if (!hasEvidenceReply) {
      replyToReviewThread(sh, repo, prNumber, threadId, fixedReply);
      repliesPosted.push({ threadId, body: fixedReply });
    }
    resolveReviewThread(sh, repo, prNumber, threadId);
    threadsResolved.push(threadId);
  }

  return { deferredIssueUrls, repliesPosted, threadsResolved };
}

/** Derive fix-marked identity keys from verify dispositions when omitted. */
export function fixMarkedKeysFromVerify(verify: VerifyResult): string[] {
  if (verify.fixMarkedFindingIdentityKeys !== undefined) {
    return [...verify.fixMarkedFindingIdentityKeys];
  }
  return (verify.findingDispositions ?? [])
    .filter((d) => d.action === "fix")
    .map((d) => d.identityKey);
}