/**
 * #1145 test helper — build OnlineReviewLoopDispatch with independent
 * Collector + Verify seats (no host poll / side-effect dual-owner seams).
 */
import type {
  OnlineReviewCollectorDispatchResult,
  OnlineReviewLoopDispatch,
  OnlineReviewVerifyDispatchResult,
} from "../../src/family/onlineReviewLoop.js";
import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  VerifyResult,
  WorkerLandingPayload,
} from "../../src/types.js";
import { stubCollectorEvidence } from "../../src/reviewLoopOutcome.js";

/**
 * Build stage dispatch for unit tests.
 * - `evidence` feeds the default Collector cargo (host does not poll).
 * - `dispatchVerify` is judgment only.
 * - optional `dispatchCollector` overrides the default evidence seat.
 */
/** Loose fixture shape accepted by tests (PrReviewSnapshot-compatible). */
type EvidenceFixture =
  | OnlineReviewLandingSnapshot
  | (OnlineReviewLandingSnapshot & Record<string, unknown>)
  | {
      readonly prUrl: string;
      readonly headOid: string;
      readonly totalFindingCount?: number;
      readonly quiescent?: boolean;
      readonly bots?: OnlineReviewLandingSnapshot["bots"];
      readonly threads?: OnlineReviewLandingSnapshot["threads"];
      readonly checkRuns?: OnlineReviewLandingSnapshot["checkRuns"];
      readonly checkRunsEmptyMeans?: OnlineReviewLandingSnapshot["checkRunsEmptyMeans"];
      readonly [key: string]: unknown;
    };

function toEvidence(raw: EvidenceFixture): OnlineReviewLandingSnapshot {
  return {
    prUrl: raw.prUrl,
    headOid: raw.headOid,
    ...(typeof raw.totalFindingCount === "number"
      ? { totalFindingCount: raw.totalFindingCount }
      : {}),
    ...(typeof raw.quiescent === "boolean" ? { quiescent: raw.quiescent } : {}),
    ...(raw.bots !== undefined ? { bots: raw.bots } : {}),
    ...(raw.threads !== undefined ? { threads: raw.threads } : {}),
    ...(raw.checkRuns !== undefined ? { checkRuns: raw.checkRuns } : {}),
    ...(raw.checkRunsEmptyMeans !== undefined
      ? { checkRunsEmptyMeans: raw.checkRunsEmptyMeans }
      : {}),
  };
}

export function onlineReviewDispatch(input: {
  readonly evidence?:
    | EvidenceFixture
    | ((
        round: number,
      ) =>
        | EvidenceFixture
        | Promise<EvidenceFixture>
        | OnlineReviewCollectorDispatchResult
        | Promise<OnlineReviewCollectorDispatchResult>);
  /** Fixture alias — accepts evidence or PrReviewSnapshot-shaped objects. */
  readonly snapshot?:
    | EvidenceFixture
    | ((
        round: number,
      ) => EvidenceFixture | Promise<EvidenceFixture>);
  readonly dispatchVerify?: (
    landing: WorkerLandingPayload,
    round: number,
  ) =>
    | OnlineReviewVerifyDispatchResult
    | VerifyResult
    | undefined
    | Promise<OnlineReviewVerifyDispatchResult | VerifyResult | undefined>;
  readonly dispatchCollector?: (
    landing: WorkerLandingPayload,
    round: number,
  ) =>
    | OnlineReviewCollectorDispatchResult
    | Promise<OnlineReviewCollectorDispatchResult>;
  readonly dispatchFixer?: (
    landing: WorkerLandingPayload,
  ) => FixerResult | undefined | Promise<FixerResult | undefined>;
  readonly resolveFixCommitSha?: (
    envelopeFixSha: string,
  ) => string | Promise<string>;
}): OnlineReviewLoopDispatch {
  const defaultEvidence = (): OnlineReviewLandingSnapshot =>
    stubCollectorEvidence();

  return {
    dispatchCollector: async (landing, round) => {
      if (input.dispatchCollector !== undefined) {
        return input.dispatchCollector(landing, round);
      }
      const src = input.evidence ?? input.snapshot ?? defaultEvidence;
      const raw = typeof src === "function" ? await src(round) : src;
      if (
        raw &&
        typeof raw === "object" &&
        "evidence" in raw &&
        !("prUrl" in raw)
      ) {
        return raw as OnlineReviewCollectorDispatchResult;
      }
      return { evidence: toEvidence(raw as EvidenceFixture) };
    },
    dispatchVerify: async (landing, round) => {
      if (input.dispatchVerify === undefined) {
        return { verify: { kind: "verify", converged: true } };
      }
      const raw = await input.dispatchVerify(landing, round);
      if (raw === undefined) return {};
      if (
        typeof raw === "object" &&
        "converged" in raw &&
        !("verify" in raw)
      ) {
        return { verify: raw as VerifyResult };
      }
      return raw as OnlineReviewVerifyDispatchResult;
    },
    dispatchFixer: async (landing) => {
      if (input.dispatchFixer === undefined) return undefined;
      return input.dispatchFixer(landing);
    },
    ...(input.resolveFixCommitSha !== undefined
      ? { resolveFixCommitSha: input.resolveFixCommitSha }
      : {}),
  };
}
