/**
 * #1145 test helper — build OnlineReviewLoopDispatch with independent
 * Collector + Verify seats (no host poll / retriggerAfterFix dual-owner seams).
 */
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import { toLandingSnapshot } from "../../src/family/onlineReviewLoop.js";
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

export type LegacyVerifyReturn =
  | VerifyResult
  | {
      readonly kind: "rawReviewerArtifacts";
      readonly artifacts: NonNullable<
        WorkerLandingPayload["rawReviewerArtifacts"]
      >;
      readonly verify?: VerifyResult;
    }
  | OnlineReviewVerifyDispatchResult
  | (OnlineReviewVerifyDispatchResult & {
      readonly snapshot?: PrReviewSnapshot;
    });

function snapshotToEvidence(
  snapshot: PrReviewSnapshot,
): OnlineReviewLandingSnapshot {
  return toLandingSnapshot(snapshot);
}

function normalizeVerify(
  raw: LegacyVerifyReturn | undefined,
): OnlineReviewVerifyDispatchResult {
  if (raw && typeof raw === "object" && "verify" in raw && !("converged" in raw)) {
    const r = raw as OnlineReviewVerifyDispatchResult & {
      artifacts?: NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]>;
    };
    return {
      ...(r.verify !== undefined ? { verify: r.verify } : {}),
      ...(r.artifacts !== undefined ? { artifacts: r.artifacts } : {}),
    };
  }
  if (
    raw &&
    typeof raw === "object" &&
    (raw as { kind?: string }).kind === "rawReviewerArtifacts"
  ) {
    const r = raw as {
      artifacts?: NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]>;
      verify?: VerifyResult;
    };
    return {
      ...(r.artifacts !== undefined ? { artifacts: r.artifacts } : {}),
      ...(r.verify !== undefined ? { verify: r.verify } : {}),
    };
  }
  if (raw && typeof raw === "object" && "converged" in raw) {
    return { verify: raw as VerifyResult };
  }
  return {};
}

/**
 * Build stage dispatch for unit tests.
 * - `snapshot` feeds the default Collector evidence (host does not poll).
 * - `dispatchVerify` is judgment only (may still return legacy shapes).
 * - optional `dispatchCollector` overrides the default snapshot→evidence seat.
 */
export function onlineReviewDispatch(input: {
  readonly snapshot:
    | PrReviewSnapshot
    | ((round: number) => PrReviewSnapshot | Promise<PrReviewSnapshot>);
  readonly dispatchCollector?: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<OnlineReviewCollectorDispatchResult>;
  readonly dispatchVerify: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<LegacyVerifyReturn | OnlineReviewVerifyDispatchResult>;
  readonly dispatchFixer: (
    landing: WorkerLandingPayload,
  ) => Promise<FixerResult | undefined>;
  readonly resolveFixCommitSha?: (
    envelopeFixSha: string,
  ) => string | Promise<string>;
}): OnlineReviewLoopDispatch {
  return {
    dispatchCollector:
      input.dispatchCollector ??
      (async (_landing, round) => {
        const snapshot =
          typeof input.snapshot === "function"
            ? await input.snapshot(round)
            : input.snapshot;
        return { evidence: snapshotToEvidence(snapshot) };
      }),
    dispatchVerify: async (landing, round) => {
      const raw = await input.dispatchVerify(landing, round);
      return normalizeVerify(raw);
    },
    dispatchFixer: input.dispatchFixer,
    ...(input.resolveFixCommitSha !== undefined
      ? { resolveFixCommitSha: input.resolveFixCommitSha }
      : {}),
  };
}
