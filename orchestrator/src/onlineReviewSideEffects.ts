/**
 * Host-side GitHub side effects for the online review loop (#600).
 *
 * The verify worker owns disposition judgment; this module applies deterministic
 * gh calls for deferred-issue tracking, evidence-bearing thread replies, and
 * post-recheck thread resolution. No LLM calls.
 */

import {
  paginateGhApi,
  paginateReviewThreadNodes,
  parsePrRef,
} from "./botPolling.js";
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

class VerifyCargoSideEffectError extends Error {
  override readonly name = "VerifyCargoSideEffectError";
}

/** Stable title for a deferred online-review tracking issue (#600 / #742). */
export const DEFERRED_TRACKING_ISSUE_TITLE_PREFIX =
  "Deferred online review finding: ";

export function deferredTrackingIssueTitle(identityKey: string): string {
  return `${DEFERRED_TRACKING_ISSUE_TITLE_PREFIX}${identityKey}`;
}

/**
 * Derive the deferred-finding identity on the host, from GitHub's landing
 * identifiers. Worker-provided identity keys are judgment output and may
 * change between rounds; the review thread/comment is the durable anchor.
 */
export function hostSideDeferredIdentityKey(
  echoedThreadId: string,
  landingThreads: ReadonlyArray<LandingThreadRef> | undefined,
): string {
  const landing = landingThreads?.find(
    (thread) =>
      thread.id === echoedThreadId ||
      String(thread.id) === echoedThreadId ||
      thread.threadNodeId === echoedThreadId,
  );
  return landing?.threadNodeId ?? landing?.id ?? echoedThreadId;
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

/**
 * Find an open tracking issue with the exact title (stable finding identity).
 * GitHub's issues list also returns PRs — those are skipped (#742).
 */
export function findOpenDeferredTrackingIssueUrl(
  sh: Sh,
  repo: string,
  title: string,
): string | undefined {
  const matching = listOpenDeferredTrackingIssues(sh, repo, title);
  return matching[0]?.htmlUrl;
}

type OpenDeferredTrackingIssue = {
  readonly htmlUrl: string;
  readonly number?: number;
  readonly createdAt?: string;
};

function listOpenDeferredTrackingIssues(
  sh: Sh,
  repo: string,
  title: string,
): OpenDeferredTrackingIssue[] {
  const matches: OpenDeferredTrackingIssue[] = [];
  for (const item of paginateGhApi(sh, `repos/${repo}/issues?state=open`)) {
    if (item === null || typeof item !== "object") continue;
    const obj = item as {
      title?: unknown;
      html_url?: unknown;
      pull_request?: unknown;
      number?: unknown;
      created_at?: unknown;
    };
    if (
      (obj.pull_request !== undefined && obj.pull_request !== null) ||
      obj.title !== title
    ) continue;
    if (typeof obj.html_url !== "string") continue;
    const htmlUrl = obj.html_url.trim();
    if (!isValidGithubIssueUrl(htmlUrl)) continue;
    matches.push({
      htmlUrl,
      ...(typeof obj.number === "number" && Number.isSafeInteger(obj.number)
        ? { number: obj.number }
        : {}),
      ...(typeof obj.created_at === "string" ? { createdAt: obj.created_at } : {}),
    });
  }
  matches.sort(compareDeferredIssues);
  return matches;
}

function compareDeferredIssues(
  a: OpenDeferredTrackingIssue,
  b: OpenDeferredTrackingIssue,
): number {
  const aTime = a.createdAt === undefined ? Number.POSITIVE_INFINITY : Date.parse(a.createdAt);
  const bTime = b.createdAt === undefined ? Number.POSITIVE_INFINITY : Date.parse(b.createdAt);
  if (!Number.isNaN(aTime) && !Number.isNaN(bTime) && aTime !== bTime) {
    return aTime - bTime;
  }
  if (a.number !== undefined && b.number !== undefined && a.number !== b.number) {
    return a.number - b.number;
  }
  return a.htmlUrl.localeCompare(b.htmlUrl);
}

function issueNumberFromUrl(url: string): number | undefined {
  const match = url.match(/\/issues\/(\d+)(?:[/?#]|$)/i);
  return match === null ? undefined : Number(match[1]);
}

function closeDuplicateDeferredIssue(
  sh: Sh,
  repo: string,
  issue: OpenDeferredTrackingIssue,
): void {
  const number = issue.number ?? issueNumberFromUrl(issue.htmlUrl);
  if (number === undefined || !Number.isSafeInteger(number)) return;
  sh("gh", [
    "api",
    `repos/${repo}/issues/${number}`,
    "-X",
    "PATCH",
    "-f",
    "state=closed",
  ]);
}

function adoptOldestDeferredIssue(
  sh: Sh,
  repo: string,
  issues: OpenDeferredTrackingIssue[],
): string | undefined {
  const canonical = issues[0];
  if (canonical === undefined) return undefined;
  for (const duplicate of issues.slice(1)) {
    closeDuplicateDeferredIssue(sh, repo, duplicate);
  }
  return canonical.htmlUrl;
}

/**
 * Create a tracked deferral issue via `gh api repos/{repo}/issues` (#600 AC5).
 * Idempotent (#742): reuses an existing open issue with the same title before
 * creating, so crash-resume / repeated rounds do not open duplicates for the
 * same finding identity key (embedded in the stable title).
 */
export function createDeferredTrackingIssue(
  sh: Sh,
  repo: string,
  title: string,
  body: string,
): string {
  const existing = adoptOldestDeferredIssue(
    sh,
    repo,
    listOpenDeferredTrackingIssues(sh, repo, title),
  );
  if (existing !== undefined) return existing;

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
  const afterCreate = adoptOldestDeferredIssue(
    sh,
    repo,
    listOpenDeferredTrackingIssues(sh, repo, title),
  );
  if (afterCreate === undefined) {
    throw new Error(
      `createDeferredTrackingIssue: issue ${trimmed} did not converge to a canonical issue`,
    );
  }
  return afterCreate;
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

type ReviewReplyMatch = {
  readonly id?: number;
  readonly createdAt?: string;
};

function listIdenticalReviewReplies(
  sh: Sh,
  repo: string,
  prNumber: number,
  commentId: string,
  body: string,
): ReviewReplyMatch[] {
  const parentId = Number(commentId);
  const matches: ReviewReplyMatch[] = [];
  for (const item of paginateGhApi(
    sh,
    `repos/${repo}/pulls/${prNumber}/comments`,
  )) {
    if (item === null || typeof item !== "object") continue;
    const comment = item as {
      id?: unknown;
      body?: unknown;
      in_reply_to_id?: unknown;
      created_at?: unknown;
    };
    const replyParent = comment.in_reply_to_id;
    const sameParent =
      replyParent !== undefined &&
      (replyParent === commentId ||
        String(replyParent) === commentId ||
        (Number.isSafeInteger(parentId) && replyParent === parentId));
    if (!sameParent || comment.body === undefined || comment.body !== body) continue;
    matches.push({
      ...(typeof comment.id === "number" && Number.isSafeInteger(comment.id)
        ? { id: comment.id }
        : {}),
      ...(typeof comment.created_at === "string"
        ? { createdAt: comment.created_at }
        : {}),
    });
  }
  return matches;
}

function compareReviewReplies(a: ReviewReplyMatch, b: ReviewReplyMatch): number {
  const aTime = a.createdAt === undefined ? Number.POSITIVE_INFINITY : Date.parse(a.createdAt);
  const bTime = b.createdAt === undefined ? Number.POSITIVE_INFINITY : Date.parse(b.createdAt);
  if (!Number.isNaN(aTime) && !Number.isNaN(bTime) && aTime !== bTime) {
    return aTime - bTime;
  }
  if (a.id !== undefined && b.id !== undefined && a.id !== b.id) {
    return a.id - b.id;
  }
  return 0;
}

/** Keep the oldest matching reply and remove duplicates created by overlap. */
function adoptOldestReviewReply(
  sh: Sh,
  repo: string,
  prNumber: number,
  commentId: string,
  body: string,
): boolean {
  const matches = listIdenticalReviewReplies(sh, repo, prNumber, commentId, body);
  if (matches.length === 0) return false;
  const canonical = [...matches].sort(compareReviewReplies)[0];
  if (canonical === undefined) return false;
  for (const duplicate of matches) {
    if (duplicate === canonical || duplicate.id === undefined) continue;
    sh("gh", [
      "api",
      `repos/${repo}/pulls/comments/${duplicate.id}`,
      "-X",
      "DELETE",
    ]);
  }
  return true;
}

/**
 * Post only when the canonical parent/body reply is absent, then reconcile
 * overlapping posts. This gives every reply path the same crash/overlap
 * behavior as deferred issue creation (#742 R2).
 */
function ensureReviewReply(
  sh: Sh,
  repo: string,
  prNumber: number,
  commentId: string,
  body: string,
): boolean {
  if (adoptOldestReviewReply(sh, repo, prNumber, commentId, body)) {
    return false;
  }
  replyToReviewThread(sh, repo, prNumber, commentId, body);
  adoptOldestReviewReply(sh, repo, prNumber, commentId, body);
  return true;
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
): boolean {
  let threadNodeId: string | undefined;
  let alreadyResolved = false;
  const nodes = paginateReviewThreadNodes(
    sh,
    repo,
    prNumber,
    "id isResolved comments(first:1){nodes{databaseId}}",
  );
  const targetId = Number(threadId);
  for (const obj of nodes) {
    const firstCommentId = obj.comments?.nodes?.[0]?.databaseId;
    if (
      obj.id === threadId ||
      (firstCommentId !== undefined &&
        (firstCommentId === targetId || String(firstCommentId) === threadId))
    ) {
      threadNodeId = obj.id;
      alreadyResolved = obj.isResolved === true;
      break;
    }
  }
  if (threadNodeId === undefined || threadNodeId.length === 0) {
    console.warn(
      `[orchestrator] skipped unresolvable verify cargo for thread ${threadId}; reviewer artifacts remain available to the next worker`,
    );
    return false;
  }
  if (alreadyResolved) return true;
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
  return true;
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
  return new VerifyCargoSideEffectError(
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
      throw new VerifyCargoSideEffectError(
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
    throw new VerifyCargoSideEffectError(
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
 * Invalid reviewer cargo makes the whole side-effect plan unpublishable; the
 * caller skips it atomically while the review/fix topology continues.
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
    throw new VerifyCargoSideEffectError(
      "applyVerifySideEffects: threadsToResolve requires a fresh re-check verify (isRecheck)",
    );
  }
  if (
    (verify.threadsToResolve?.length ?? 0) > 0 &&
    (input.fixingCommitSha === undefined || input.fixingCommitSha.length === 0)
  ) {
    throw new VerifyCargoSideEffectError(
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
      title: deferredTrackingIssueTitle(
        hostSideDeferredIdentityKey(disposition.threadId, landingThreads),
      ),
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

  // Reject dispositions with publishable evidence get a PR-thread reply. A thin
  // disposition is reviewer cargo, not a runner failure: skip that side effect
  // and leave the original worker artifacts for the next worker to inspect.
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
      console.warn(
        `[orchestrator] skipped unpublishable reject disposition cargo ${disposition.identityKey}; reviewer artifacts remain available to the next worker`,
      );
      continue;
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
  let plan: VerifySideEffectPlan;
  try {
    plan = planVerifySideEffects({ ...input, repo });
  } catch (err) {
    if (!(err instanceof VerifyCargoSideEffectError)) throw err;
    console.warn(
      `[orchestrator] skipped unpublishable verify cargo: ${err.message}; reviewer artifacts remain available to the next worker`,
    );
    return { deferredIssueUrls: [], repliesPosted: [], threadsResolved: [] };
  }
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
    if (ensureReviewReply(sh, repo, prNumber, item.commentId, replyBody)) {
      repliesPosted.push({ threadId: item.commentId, body: replyBody });
    }
  }

  for (const reply of plan.replies) {
    if (ensureReviewReply(sh, repo, prNumber, reply.commentId, reply.body)) {
      repliesPosted.push({ threadId: reply.commentId, body: reply.body });
    }
  }

  for (const item of plan.resolves) {
    if (item.needsFixedReply) {
      if (ensureReviewReply(sh, repo, prNumber, item.commentId, item.fixedReply)) {
        repliesPosted.push({ threadId: item.commentId, body: item.fixedReply });
      }
    }
    if (resolveReviewThread(sh, repo, prNumber, item.nodeId)) {
      threadsResolved.push(item.nodeId);
    }
  }

  return { deferredIssueUrls, repliesPosted, threadsResolved };
}

/** Preserve only the verify worker's self-reported fix-marked identity keys. */
export function fixMarkedKeysFromVerify(verify: VerifyResult): string[] {
  return [...(verify.fixMarkedFindingIdentityKeys ?? [])];
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
