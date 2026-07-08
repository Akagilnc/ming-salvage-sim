/**
 * Host-side GitHub side effects for the online review loop (#600).
 *
 * The verify worker owns disposition judgment; this module applies deterministic
 * gh calls for deferred-issue tracking, evidence-bearing thread replies, and
 * post-recheck thread resolution. No LLM calls.
 */

import { parsePrRef } from "./botPolling.js";
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

/** Create a tracked deferral issue via `gh issue create` (#600 AC5). */
export function createDeferredTrackingIssue(
  sh: Sh,
  repo: string,
  title: string,
  body: string,
): string {
  const url = sh("gh", [
    "issue",
    "create",
    "--repo",
    repo,
    "--title",
    title,
    "--body",
    body,
    "--json",
    "url",
    "-q",
    ".url",
  ]);
  return url.trim();
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

/** Resolve a review thread only after fresh re-check confirms the fix (#600 AC4). */
export function resolveReviewThread(
  sh: Sh,
  repo: string,
  threadId: string,
): void {
  sh("gh", [
    "api",
    "-X",
    "PUT",
    `repos/${repo}/pulls/comments/${threadId}`,
    "-f",
    "body=resolved by online review re-check",
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

/**
 * Apply GitHub side effects from a verify verdict: defer → tracked issue + reply,
 * reject/defer/fixed replies with evidence, resolve after recheck confirmation.
 */
export function applyVerifySideEffects(
  input: ApplyVerifySideEffectsInput,
): ApplyVerifySideEffectsResult {
  const { sh, repo, prUrl, verify } = input;
  let prNumber: number;
  try {
    ({ prNumber } = parsePrRef(prUrl, repo));
  } catch {
    return { deferredIssueUrls: [], repliesPosted: [], threadsResolved: [] };
  }
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
    const replyBody =
      existingReplies.get(disposition.threadId)?.body ??
      `deferred: ${body}\nTracked issue: ${issueUrl}`;
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

  for (const threadId of verify.threadsToResolve ?? []) {
    if (input.fixingCommitSha !== undefined && input.fixingCommitSha.length > 0) {
      const fixedReply = `fixed: https://github.com/${repo}/commit/${input.fixingCommitSha}`;
      if (!repliesPosted.some((r) => r.threadId === threadId)) {
        replyToReviewThread(sh, repo, prNumber, threadId, fixedReply);
        repliesPosted.push({ threadId, body: fixedReply });
      }
    }
    resolveReviewThread(sh, repo, threadId);
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