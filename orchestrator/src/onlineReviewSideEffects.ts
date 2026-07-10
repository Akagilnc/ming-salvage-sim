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

/** Landing thread pairing: REST comment id + GraphQL node id (#600 r23). */
export type LandingThreadRef = {
  readonly id: string;
  readonly threadNodeId?: string;
};

/** Fixer authority is the finding identity and the thread where it was marked. */
export type FixMarkedFindingThread = {
  readonly identityKey: string;
  readonly threadId: string;
};

export interface ApplyVerifySideEffectsInput {
  readonly sh: Sh;
  readonly repo: string;
  readonly prUrl: string;
  readonly verify: VerifyResult;
  readonly fixingCommitSha?: string;
  /** Runner-approved identity/thread bindings. Missing or empty means resolve nothing. */
  readonly approvedFixMarkedFindingThreads?: ReadonlyArray<FixMarkedFindingThread>;
  /** Poll snapshot threads — required for live side effects to translate worker-echoed ids. */
  readonly landingThreads?: ReadonlyArray<LandingThreadRef>;
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
  let threadNodeId: string | undefined;
  if (threadId.startsWith("PRRT_")) {
    threadNodeId = threadId;
  } else {
    const nodes = paginateReviewThreadNodes(
      sh,
      repo,
      prNumber,
      "id isResolved comments(first:1){nodes{databaseId}}",
    );
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
  const raw = sh("gh", [
    "api",
    "graphql",
    "-f",
    `query=${mutation}`,
    "-f",
    `threadId=${threadNodeId}`,
  ]);
  // Fail-closed: gh may exit 0 with GraphQL `errors` or isResolved:false (Cursor R12).
  // Gemini R13: JSON.parse can yield null — guard before property access.
  let parsed: {
    errors?: ReadonlyArray<{ message?: string }>;
    data?: {
      resolveReviewThread?: { thread?: { isResolved?: boolean } };
    };
  } | null;
  try {
    parsed = JSON.parse(raw) as typeof parsed;
  } catch {
    throw new Error(
      `onlineReviewSideEffects: resolveReviewThread returned non-JSON: ${raw.slice(0, 200)}`,
    );
  }
  if (parsed === null || typeof parsed !== "object") {
    throw new Error(
      `onlineReviewSideEffects: resolveReviewThread returned non-object JSON: ${raw.slice(0, 200)}`,
    );
  }
  if (Array.isArray(parsed.errors) && parsed.errors.length > 0) {
    const msg = parsed.errors
      .map((e) => e.message ?? "unknown")
      .join("; ");
    throw new Error(
      `onlineReviewSideEffects: resolveReviewThread GraphQL errors: ${msg}`,
    );
  }
  if (parsed.data?.resolveReviewThread?.thread?.isResolved !== true) {
    throw new Error(
      `onlineReviewSideEffects: resolveReviewThread did not set isResolved=true for ${threadNodeId}`,
    );
  }
}

function findLandingThread(
  echoedId: string,
  threads: ReadonlyArray<LandingThreadRef>,
): LandingThreadRef | undefined {
  return threads.find(
    (t) =>
      t.id === echoedId ||
      String(t.id) === echoedId ||
      t.threadNodeId === echoedId,
  );
}

function landingThreadIdMismatchError(echoedId: string): Error {
  return new Error(
    `onlineReviewSideEffects: thread id ${echoedId} matches neither REST comment id nor GraphQL node id in landing`,
  );
}

/** Replies post via REST — require the top-level review-comment databaseId. */
export function restCommentIdForReply(
  echoedId: string,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): string {
  if (landingThreads === undefined || landingThreads.length === 0) {
    if (echoedId.startsWith("PRRT_")) {
      throw new Error(
        `onlineReviewSideEffects: thread reply requires REST comment id, got GraphQL node id ${echoedId}`,
      );
    }
    return echoedId;
  }
  const thread = findLandingThread(echoedId, landingThreads);
  if (thread === undefined) {
    throw landingThreadIdMismatchError(echoedId);
  }
  return thread.id;
}

/** Resolution uses GraphQL `resolveReviewThread` — require the reviewThread node id. */
export function graphqlNodeIdForResolve(
  echoedId: string,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): string {
  if (landingThreads === undefined || landingThreads.length === 0) {
    return echoedId;
  }
  const thread = findLandingThread(echoedId, landingThreads);
  if (thread === undefined) {
    throw landingThreadIdMismatchError(echoedId);
  }
  if (thread.threadNodeId === undefined || thread.threadNodeId.length === 0) {
    throw new Error(
      `onlineReviewSideEffects: landing thread ${thread.id} has no GraphQL node id for resolution`,
    );
  }
  return thread.threadNodeId;
}

function threadIdsReferToSameLandingThread(
  a: string,
  b: string,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): boolean {
  if (a === b) {
    return true;
  }
  if (landingThreads === undefined || landingThreads.length === 0) {
    return false;
  }
  const threadA = findLandingThread(a, landingThreads);
  const threadB = findLandingThread(b, landingThreads);
  return (
    threadA !== undefined &&
    threadB !== undefined &&
    threadA.id === threadB.id
  );
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

function findReplyForThread(
  threadId: string,
  replies: Map<string, OnlineReviewThreadReply>,
  verify: VerifyResult,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): OnlineReviewThreadReply | undefined {
  const direct = replies.get(threadId);
  if (direct !== undefined) {
    return direct;
  }
  for (const reply of verify.threadReplies ?? []) {
    if (
      threadIdsReferToSameLandingThread(
        reply.threadId,
        threadId,
        landingThreads,
      )
    ) {
      return reply;
    }
  }
  return undefined;
}

function deferDispositionMatchesReplyThread(
  disposition: OnlineReviewFindingDisposition,
  replyThreadId: string,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): boolean {
  return threadIdsReferToSameLandingThread(
    disposition.threadId,
    replyThreadId,
    landingThreads,
  );
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

type DeferredSideEffectPlan = {
  readonly disposition: OnlineReviewFindingDisposition;
  readonly title: string;
  readonly issueBody: string;
  readonly replyBodyTemplate: string;
  readonly commentId: string;
};

type ReplySideEffectPlan = {
  readonly commentId: string;
  readonly body: string;
};

type ResolveSideEffectPlan = {
  readonly threadId: string;
  readonly commentId: string;
  readonly nodeId: string;
  readonly fixedReply: string;
  readonly needsFixedReply: boolean;
};

type VerifySideEffectPlan = {
  readonly deferred: ReadonlyArray<DeferredSideEffectPlan>;
  readonly replies: ReadonlyArray<ReplySideEffectPlan>;
  readonly resolves: ReadonlyArray<ResolveSideEffectPlan>;
};

/**
 * Validate and normalize all disposition/thread mappings before any GitHub write.
 * Fail-closed: invalid thread ids in the batch must not create partial side effects.
 */
export function planVerifySideEffects(
  input: ApplyVerifySideEffectsInput,
): VerifySideEffectPlan {
  const {
    repo,
    verify,
    landingThreads,
    approvedFixMarkedFindingThreads = [],
  } = input;
  const existingReplies = replyByThreadId(verify);
  const defers = deferDispositions(verify);

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

  const deferred: DeferredSideEffectPlan[] = [];
  for (const disposition of defers) {
    const commentId = restCommentIdForReply(disposition.threadId, landingThreads);
    const issueBody =
      disposition.reason ??
      `Deferred from online review loop for thread ${disposition.threadId}`;
    const existingReplyBody = findReplyForThread(
      disposition.threadId,
      existingReplies,
      verify,
      landingThreads,
    )?.body;
    deferred.push({
      disposition,
      title: `Deferred online review finding: ${disposition.identityKey}`,
      issueBody,
      replyBodyTemplate: existingReplyBody ?? "",
      commentId,
    });
  }

  const replies: ReplySideEffectPlan[] = [];
  for (const reply of verify.threadReplies ?? []) {
    if (
      defers.some((d) =>
        deferDispositionMatchesReplyThread(d, reply.threadId, landingThreads),
      )
    ) {
      continue;
    }
    replies.push({
      commentId: restCommentIdForReply(reply.threadId, landingThreads),
      body: reply.body,
    });
  }

  // Reject dispositions require an evidence reply on the PR thread (online R3
  // Codex P2). Synthesize from disposition.reason when the worker omitted
  // threadReplies; fail closed when reason is also missing.
  for (const disposition of verify.findingDispositions ?? []) {
    if (disposition.action !== "reject") {
      continue;
    }
    const existing = findReplyForThread(
      disposition.threadId,
      existingReplies,
      verify,
      landingThreads,
    );
    if (existing !== undefined) {
      continue;
    }
    const reason = disposition.reason?.trim() ?? "";
    if (reason.length === 0) {
      throw new Error(
        `applyVerifySideEffects: reject disposition for ${disposition.identityKey} requires a threadReplies entry or a non-empty reason`,
      );
    }
    const body = reason.toLowerCase().startsWith("rejected:")
      ? reason
      : `rejected: ${reason}`;
    replies.push({
      commentId: restCommentIdForReply(disposition.threadId, landingThreads),
      body,
    });
  }

  const fixingCommitSha = input.fixingCommitSha;
  const resolves: ResolveSideEffectPlan[] = [];
  for (const threadId of verify.threadsToResolve ?? []) {
    const isApprovedFixThread = (verify.findingDispositions ?? []).some(
      (disposition) =>
        disposition.action === "fix" &&
        approvedFixMarkedFindingThreads.some(
          (approved) =>
            approved.identityKey === disposition.identityKey &&
            threadIdsReferToSameLandingThread(
              approved.threadId,
              disposition.threadId,
              landingThreads,
            ) &&
            threadIdsReferToSameLandingThread(
              approved.threadId,
              threadId,
              landingThreads,
            ),
        ) &&
        threadIdsReferToSameLandingThread(
          disposition.threadId,
          threadId,
          landingThreads,
        ),
    );
    if (!isApprovedFixThread) continue;
    const commentId = restCommentIdForReply(threadId, landingThreads);
    const nodeId = graphqlNodeIdForResolve(threadId, landingThreads);
    const fixedReply = `fixed: https://github.com/${repo}/commit/${fixingCommitSha}`;
    const hasEvidenceReply =
      replies.some(
        (r) =>
          (r.commentId === commentId ||
            threadIdsReferToSameLandingThread(
              r.commentId,
              threadId,
              landingThreads,
            )) &&
          isFixedEvidenceReplyForCommit(r.body, repo, fixingCommitSha!),
      ) ||
      deferred.some(
        (d) =>
          threadIdsReferToSameLandingThread(
            d.commentId,
            threadId,
            landingThreads,
          ) &&
          isFixedEvidenceReplyForCommit(
            d.replyBodyTemplate,
            repo,
            fixingCommitSha!,
          ),
      );
    resolves.push({
      threadId,
      commentId,
      nodeId,
      fixedReply,
      needsFixedReply: !hasEvidenceReply,
    });
  }

  return { deferred, replies, resolves };
}

/**
 * Apply GitHub side effects from a verify verdict: defer → tracked issue + reply,
 * reject/defer/fixed replies with evidence, resolve after recheck confirmation.
 */
/** Single parse of PR URL → repo; fail closed when caller repo disagrees (#600 r27). */
export function resolvePrRepoFromUrl(
  prUrl: string,
  callerRepo: string,
): { readonly repo: string; readonly prNumber: number } {
  const parsed = parsePrRef(prUrl, callerRepo);
  const normalizedCaller = callerRepo.trim();
  if (
    normalizedCaller.length > 0 &&
    parsed.repo.toLowerCase() !== normalizedCaller.toLowerCase()
  ) {
    throw new Error(
      `applyVerifySideEffects: caller repo "${callerRepo}" conflicts with PR URL repo "${parsed.repo}"`,
    );
  }
  return parsed;
}

export function applyVerifySideEffects(
  input: ApplyVerifySideEffectsInput,
): ApplyVerifySideEffectsResult {
  const { sh, prUrl, landingThreads } = input;
  const { repo, prNumber } = resolvePrRepoFromUrl(prUrl, input.repo);
  const plan = planVerifySideEffects({ ...input, repo });
  const deferredIssueUrls: string[] = [];
  const repliesPosted: OnlineReviewThreadReply[] = [];
  const threadsResolved: string[] = [];

  for (const item of plan.deferred) {
    const issueUrl = createDeferredTrackingIssue(
      sh,
      repo,
      item.title,
      item.issueBody,
    );
    deferredIssueUrls.push(issueUrl);
    const replyBody = deferReplyBody(
      item.replyBodyTemplate.length > 0 ? item.replyBodyTemplate : undefined,
      item.disposition,
      issueUrl,
    );
    replyToReviewThread(sh, repo, prNumber, item.commentId, replyBody);
    repliesPosted.push({ threadId: item.commentId, body: replyBody });
  }

  for (const reply of plan.replies) {
    replyToReviewThread(sh, repo, prNumber, reply.commentId, reply.body);
    repliesPosted.push({ threadId: reply.commentId, body: reply.body });
  }

  for (const item of plan.resolves) {
    if (item.needsFixedReply) {
      replyToReviewThread(sh, repo, prNumber, item.commentId, item.fixedReply);
      repliesPosted.push({ threadId: item.commentId, body: item.fixedReply });
    }
    resolveReviewThread(sh, repo, prNumber, item.nodeId);
    threadsResolved.push(item.nodeId);
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

/** Preserve the thread that a fix-marked identity was judged against. */
export function fixMarkedFindingThreadsFromVerify(
  verify: VerifyResult,
): FixMarkedFindingThread[] {
  const keys = new Set(fixMarkedKeysFromVerify(verify));
  return (verify.findingDispositions ?? []).flatMap((disposition) =>
    disposition.action === "fix" && keys.has(disposition.identityKey)
      ? [{ identityKey: disposition.identityKey, threadId: disposition.threadId }]
      : [],
  );
}
